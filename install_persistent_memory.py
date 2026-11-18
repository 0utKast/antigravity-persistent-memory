#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Instalador multiplataforma en 1 comando para el plugin `persistent-memory` (L0–L3)
en Antigravity (Windows, macOS y Linux).

Uso:
  python install_persistent_memory.py
  python install_persistent_memory.py --gemini-home ~/.gemini
  python install_persistent_memory.py --check
  python install_persistent_memory.py --uninstall
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent
SOURCE_PLUGIN_DIR = REPO_ROOT / "plugin" / "persistent-memory"

PLUGIN_FILES = (
    "memctl.py",
    "memory_mcp_server.py",
    "plugin.json",
    "rules/AGENTS.md",
    "skills/memory-steward/SKILL.md",
)


def check_environment() -> None:
    """Verifica Python >= 3.10 y soporte SQLite FTS5."""
    if sys.version_info < (3, 10):
        raise RuntimeError(
            f"Se requiere Python 3.10 o superior (detectado: {sys.version.split()[0]})."
        )
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute(
            "CREATE VIRTUAL TABLE _fts5_probe USING fts5(k, body, tokenize='unicode61 remove_diacritics 2')"
        )
    except sqlite3.OperationalError as exc:
        raise RuntimeError(f"SQLite compilado sin soporte FTS5: {exc}") from exc
    finally:
        conn.close()


def quote_shell_token(token: str) -> str:
    """Escapa un argumento para `cmd /c` (Windows) o `sh -c` (macOS/Linux)."""
    if os.name == "nt":
        return subprocess.list2cmdline([token])
    return shlex.quote(token)


def _replace_placeholders(obj: Any, py_token: str, memctl_token: str) -> Any:
    if isinstance(obj, str):
        return obj.replace("__PYTHON_CMD__", py_token).replace("__MEMCTL_PATH__", memctl_token)
    if isinstance(obj, list):
        return [_replace_placeholders(item, py_token, memctl_token) for item in obj]
    if isinstance(obj, dict):
        return {k: _replace_placeholders(v, py_token, memctl_token) for k, v in obj.items()}
    return obj


def render_hooks_json(template_path: Path, python_exe: str, memctl_dst: Path) -> str:
    parsed = json.loads(template_path.read_text(encoding="utf-8"))
    py_token = quote_shell_token(python_exe)
    memctl_token = quote_shell_token(str(memctl_dst.resolve()))
    rendered = _replace_placeholders(parsed, py_token, memctl_token)
    return json.dumps(rendered, ensure_ascii=False, indent=2) + "\n"


def update_mcp_config(mcp_config_path: Path, python_exe: str, mcp_server_dst: Path) -> None:
    """Registra `persistent_memory` preservando todos los servidores existentes y creando .bak."""
    mcp_config_path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {"mcpServers": {}}
    if mcp_config_path.exists():
        backup_path = mcp_config_path.with_suffix(".json.bak")
        shutil.copy2(mcp_config_path, backup_path)
        try:
            loaded = json.loads(mcp_config_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"El archivo {mcp_config_path} contiene JSON inválido; corrígelo antes de continuar: {exc}"
            ) from exc

    servers = data.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        servers = {}
        data["mcpServers"] = servers

    servers["persistent_memory"] = {
        "command": python_exe,
        "args": [str(mcp_server_dst.resolve())],
    }
    mcp_config_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def verify_installed_plugin(gemini_home: Path) -> dict[str, Any]:
    """Ejecuta pruebas en vivo sobre el servidor MCP y los hooks recién instalados."""
    plugin_dst = gemini_home / "config" / "plugins" / "persistent-memory"
    mcp_server_dst = plugin_dst / "memory_mcp_server.py"
    memctl_dst = plugin_dst / "memctl.py"
    hooks_dst = plugin_dst / "hooks.json"
    mcp_cfg_path = gemini_home / "config" / "mcp_config.json"

    for required in (mcp_server_dst, memctl_dst, hooks_dst, mcp_cfg_path):
        if not required.is_file():
            raise RuntimeError(f"Falta archivo requerido tras la instalación: {required}")

    # 1) Handshake JSON-RPC stdio (initialize + tools/list)
    proc = subprocess.Popen(
        [sys.executable, str(mcp_server_dst)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        assert proc.stdin is not None and proc.stdout is not None
        reqs = [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2024-11-05", "capabilities": {}},
            },
            {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        ]
        for msg in reqs:
            proc.stdin.write((json.dumps(msg) + "\n").encode("utf-8"))
        proc.stdin.flush()
        proc.stdin.close()

        responses: dict[int, dict[str, Any]] = {}
        while True:
            raw_line = proc.stdout.readline()
            if not raw_line:
                break
            txt = raw_line.decode("utf-8", errors="replace").strip()
            if not txt:
                continue
            obj = json.loads(txt)
            if "id" in obj:
                responses[int(obj["id"])] = obj
    finally:
        proc.wait(timeout=5)

    if 1 not in responses or 2 not in responses:
        raise RuntimeError("No se recibió respuesta completa JSON-RPC desde memory_mcp_server.py.")
    tool_names = sorted(t["name"] for t in responses[2]["result"]["tools"])
    expected_tools = ["memory_audit", "memory_init", "memory_lifecycle", "memory_record", "memory_search"]
    if tool_names != expected_tools:
        raise RuntimeError(f"Lista de herramientas MCP inesperada: {tool_names}")

    # 2) Validar hook SessionStart y Stop sobre directorio temporal aislado
    tmp_ws = Path(tempfile.mkdtemp(prefix="agy_verify_ws_"))
    try:
        env = os.environ.copy()
        env["AGY_GEMINI_HOME"] = str(gemini_home)
        payload = json.dumps(
            {
                "conversationId": "installer-self-check",
                "workspacePaths": [str(tmp_ws)],
                "cwd": str(tmp_ws),
                "terminationReason": "NO_TOOL_CALL",
                "continuationActive": False,
            }
        )
        start_res = subprocess.run(
            [sys.executable, str(memctl_dst), "hook-session-start"],
            input=payload,
            text=True,
            capture_output=True,
            encoding="utf-8",
            env=env,
            check=True,
        )
        stop_res = subprocess.run(
            [sys.executable, str(memctl_dst), "hook-stop"],
            input=payload,
            text=True,
            capture_output=True,
            encoding="utf-8",
            env=env,
            check=True,
        )
        start_json = json.loads(start_res.stdout)
        stop_json = json.loads(stop_res.stdout)
        if "injectSteps" not in start_json:
            raise RuntimeError(f"Salida inesperada de hook-session-start: {start_json}")
        if stop_json.get("decision") != "stop":
            raise RuntimeError(f"Salida inesperada de hook-stop: {stop_json}")
    finally:
        shutil.rmtree(tmp_ws, ignore_errors=True)

    return {
        "status": "VERIFIED",
        "gemini_home": str(gemini_home),
        "plugin_dir": str(plugin_dst),
        "mcp_config": str(mcp_cfg_path),
        "mcp_tools": tool_names,
        "hooks_verified": ["SessionStart", "Stop"],
    }


def install_plugin(gemini_home: Path) -> dict[str, Any]:
    check_environment()
    if not SOURCE_PLUGIN_DIR.is_dir():
        raise RuntimeError(f"No se encontró el directorio fuente del plugin: {SOURCE_PLUGIN_DIR}")

    plugin_dst = gemini_home / "config" / "plugins" / "persistent-memory"
    plugin_dst.mkdir(parents=True, exist_ok=True)

    for rel_path in PLUGIN_FILES:
        src_file = SOURCE_PLUGIN_DIR / rel_path
        dst_file = plugin_dst / rel_path
        dst_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_file, dst_file)

    template_path = SOURCE_PLUGIN_DIR / "hooks.template.json"
    hooks_text = render_hooks_json(template_path, sys.executable, plugin_dst / "memctl.py")
    (plugin_dst / "hooks.json").write_text(hooks_text, encoding="utf-8")

    mcp_cfg_path = gemini_home / "config" / "mcp_config.json"
    update_mcp_config(mcp_cfg_path, sys.executable, plugin_dst / "memory_mcp_server.py")

    result = verify_installed_plugin(gemini_home)
    result["action"] = "INSTALLED"
    return result


def uninstall_plugin(gemini_home: Path) -> dict[str, Any]:
    plugin_dst = gemini_home / "config" / "plugins" / "persistent-memory"
    mcp_cfg_path = gemini_home / "config" / "mcp_config.json"

    removed_mcp = False
    if mcp_cfg_path.is_file():
        shutil.copy2(mcp_cfg_path, mcp_cfg_path.with_suffix(".json.bak"))
        data = json.loads(mcp_cfg_path.read_text(encoding="utf-8"))
        servers = data.get("mcpServers", {})
        if isinstance(servers, dict) and "persistent_memory" in servers:
            del servers["persistent_memory"]
            mcp_cfg_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            removed_mcp = True

    removed_plugin_dir = False
    if plugin_dst.exists():
        shutil.rmtree(plugin_dst)
        removed_plugin_dir = True

    return {
        "action": "UNINSTALLED",
        "gemini_home": str(gemini_home),
        "removed_mcp_entry": removed_mcp,
        "removed_plugin_dir": removed_plugin_dir,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Instalador oficial del plugin persistent-memory (L0-L3) para Antigravity."
    )
    parser.add_argument(
        "--gemini-home",
        default=str(Path.home() / ".gemini"),
        help="Ruta al directorio de configuración de Antigravity (por defecto ~/.gemini).",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Comprueba requisitos y verifica la instalación existente sin modificar archivos.",
    )
    parser.add_argument(
        "--uninstall",
        action="store_true",
        help="Desinstala el plugin y limpia la entrada persistent_memory de mcp_config.json.",
    )
    args = parser.parse_args()
    gemini_home = Path(args.gemini_home).expanduser().resolve()

    if args.uninstall:
        res = uninstall_plugin(gemini_home)
    elif args.check:
        check_environment()
        res = verify_installed_plugin(gemini_home)
        res["action"] = "CHECK_OK"
    else:
        res = install_plugin(gemini_home)

    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
