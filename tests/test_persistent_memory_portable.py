#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Suite E2E 100 % portable del plugin `persistent-memory` (L0–L3) e instalador.

No depende de rutas privadas del equipo del autor ni altera ~/.gemini real:
instala y prueba todo dentro de directorios temporales aislados (`tempfile.mkdtemp`).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
INSTALLER = REPO_ROOT / "install_persistent_memory.py"


class StdioMCPClient:
    """Cliente JSON-RPC stdio mínimo para validar servidores MCP reales."""

    def __init__(self, script_path: Path, env: dict[str, str] | None = None) -> None:
        self.script_path = script_path
        self.env = env
        self.proc: subprocess.Popen[bytes] | None = None
        self._next_id = 1

    def __enter__(self) -> "StdioMCPClient":
        self.proc = subprocess.Popen(
            [sys.executable, str(self.script_path)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self.env,
        )
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self.proc is not None:
            for stream in (self.proc.stdin, self.proc.stdout, self.proc.stderr):
                if stream is not None:
                    try:
                        stream.close()
                    except Exception:
                        pass
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.terminate()
                self.proc.wait(timeout=2)

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        assert self.proc is not None and self.proc.stdin is not None and self.proc.stdout is not None
        req_id = self._next_id
        self._next_id += 1
        payload = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or {}}
        self.proc.stdin.write((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
        self.proc.stdin.flush()

        while True:
            line = self.proc.stdout.readline()
            if not line:
                stderr_out = self.proc.stderr.read().decode("utf-8", errors="replace") if self.proc.stderr else ""
                raise RuntimeError(f"EOF inesperado desde {self.script_path.name}: {stderr_out}")
            txt = line.decode("utf-8", errors="replace").strip()
            if not txt:
                continue
            msg = json.loads(txt)
            if msg.get("id") == req_id:
                return msg

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        assert self.proc is not None and self.proc.stdin is not None
        payload = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        self.proc.stdin.write((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
        self.proc.stdin.flush()

    def call_tool(self, name: str, arguments: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        resp = self.request("tools/call", {"name": name, "arguments": arguments})
        result = resp["result"]
        is_error = bool(result.get("isError", False))
        text = result["content"][0]["text"]
        return json.loads(text), is_error


class PortablePersistentMemoryTests(unittest.TestCase):
    def test_01_installer_mcp_lifecycle_federation_and_budget_guards(self) -> None:
        tmp_gh = Path(tempfile.mkdtemp(prefix="agy_port_gh_"))
        ws_alpha = Path(tempfile.mkdtemp(prefix="agy_port_alpha_"))
        ws_beta = Path(tempfile.mkdtemp(prefix="agy_port_beta_"))
        try:
            # Simular configuración MCP previa que debe conservarse intacta
            cfg_dir = tmp_gh / "config"
            cfg_dir.mkdir(parents=True, exist_ok=True)
            mcp_cfg = cfg_dir / "mcp_config.json"
            mcp_cfg.write_text(
                json.dumps(
                    {
                        "mcpServers": {
                            "existing_demo": {"command": "echo", "args": ["ok"]},
                        }
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            (tmp_gh / "GEMINI.md").write_text("# Global Clean\n- Open permissions.\n", encoding="utf-8")

            # 1) Instalar plugin en directorio aislado (--gemini-home)
            inst_proc = subprocess.run(
                [sys.executable, str(INSTALLER), "--gemini-home", str(tmp_gh)],
                text=True,
                capture_output=True,
                encoding="utf-8",
                check=True,
            )
            inst_res = json.loads(inst_proc.stdout)
            self.assertEqual(inst_res["action"], "INSTALLED")
            self.assertEqual(inst_res["status"], "VERIFIED")
            self.assertTrue((cfg_dir / "mcp_config.json.bak").is_file())

            updated_mcp = json.loads(mcp_cfg.read_text(encoding="utf-8"))
            self.assertIn("existing_demo", updated_mcp["mcpServers"])
            self.assertIn("persistent_memory", updated_mcp["mcpServers"])

            plugin_dir = cfg_dir / "plugins" / "persistent-memory"
            hooks_data = json.loads((plugin_dir / "hooks.json").read_text(encoding="utf-8"))
            self.assertIn("SessionStart", hooks_data["persistent-memory-session-start"])
            self.assertIn("Stop", hooks_data["persistent-memory-budget-guard"])

            # Verificar también --check sin modificar archivos
            chk_proc = subprocess.run(
                [sys.executable, str(INSTALLER), "--check", "--gemini-home", str(tmp_gh)],
                text=True,
                capture_output=True,
                encoding="utf-8",
                check=True,
            )
            self.assertEqual(json.loads(chk_proc.stdout)["action"], "CHECK_OK")

            # 2) Probar MCP instalado: init, anti-poisoning, verify, promote N>=2, FTS5 y federación
            installed_mcp = plugin_dir / "memory_mcp_server.py"
            installed_memctl = plugin_dir / "memctl.py"
            env_isolated = os.environ.copy()
            env_isolated["AGY_GEMINI_HOME"] = str(tmp_gh)

            (ws_alpha / "pyproject.toml").write_text("[project]\nname='alpha'\n", encoding="utf-8")
            (ws_beta / "package.json").write_text('{"name": "beta"}\n', encoding="utf-8")

            with StdioMCPClient(installed_mcp, env=env_isolated) as client:
                init_resp = client.request(
                    "initialize",
                    {"protocolVersion": "2024-11-05", "capabilities": {}},
                )
                self.assertEqual(init_resp["result"]["serverInfo"]["name"], "persistent_memory")
                client.notify("notifications/initialized")

                init_a, err_a = client.call_tool(
                    "memory_init",
                    {
                        "workspace_path": str(ws_alpha),
                        "project_name": "AlphaMod",
                        "prefix": "FO4",
                        "scopes": ["binarios_ba2_y_compilador"],
                    },
                )
                self.assertFalse(err_a)
                self.assertEqual(init_a["status"], "INITIALIZED")

                init_b, err_b = client.call_tool(
                    "memory_init",
                    {
                        "workspace_path": str(ws_beta),
                        "project_name": "BetaCourse",
                        "prefix": "BC",
                        "scopes": ["arquitectura_frontend_y_api"],
                    },
                )
                self.assertFalse(err_b)
                self.assertEqual(init_b["status"], "INITIALIZED")

                # Bloqueo Anti-Envenenamiento
                poison_res, poison_err = client.call_tool(
                    "memory_record",
                    {
                        "workspace_path": str(ws_alpha),
                        "scope": "binarios_ba2_y_compilador",
                        "title": "Conjetura sin verificar",
                        "environment": "PapyrusCompiler",
                        "symptom": "Papyrus.0.log muestra None",
                        "semantic_trap": "Cambiar orden de carga",
                        "root_cause": "Hipótesis sin probar en partida",
                        "deterministic_fix": "Mover plugin en plugins.txt",
                        "provenance": "Compilación fallida todavía",
                        "exit_code": 1,
                        "log_errors": ["Cannot call AddItem() on None"],
                    },
                )
                self.assertTrue(poison_err)
                self.assertEqual(poison_res["status"], "REJECTED_MEMORY_POISONING")

                # Registro PROVISIONAL -> bloqueo promote -> VERIFIED -> N=2 -> promote
                rec_res, rec_err = client.call_tool(
                    "memory_record",
                    {
                        "workspace_path": str(ws_alpha),
                        "scope": "binarios_ba2_y_compilador",
                        "title": "Máscara 12 bits y TweakDB:SetFlat con Papyrus.0.log limpio",
                        "environment": "Python 3.13 · Windows/POSIX",
                        "symptom": "Papyrus.0.log reporta None cuando se toma máscara de 24 bits",
                        "semantic_trap": "Usar los 6 dígitos bajos 0x00FFFFFF de FO4Edit",
                        "root_cause": "Los Light Plugins 0xFE reservan 12 bits locales",
                        "deterministic_fix": "Usar máscara 0x00000FFF en Game.GetFormFromFile",
                        "provenance": "PapyrusCompiler exit_code=0 y partida limpia verificada",
                        "status": "PROVISIONAL",
                        "exit_code": 0,
                    },
                )
                self.assertFalse(rec_err)
                entry_id = rec_res["entry_id"]

                premature, prem_err = client.call_tool(
                    "memory_lifecycle",
                    {"workspace_path": str(ws_alpha), "action": "promote", "entry_id": entry_id},
                )
                self.assertTrue(prem_err)
                self.assertEqual(premature["status"], "REJECTED_PROMOTION")

                ver_res, ver_err = client.call_tool(
                    "memory_lifecycle",
                    {
                        "workspace_path": str(ws_alpha),
                        "action": "verify",
                        "entry_id": entry_id,
                        "provenance_note": "Confirmado en juego real",
                    },
                )
                self.assertFalse(ver_err)
                self.assertEqual(ver_res["entry_status"], "VERIFIED")

                rec2, rec2_err = client.call_tool(
                    "memory_lifecycle",
                    {"workspace_path": str(ws_alpha), "action": "recurrence", "entry_id": entry_id},
                )
                self.assertFalse(rec2_err)
                self.assertTrue(rec2["ready_for_promotion"])

                prom_res, prom_err = client.call_tool(
                    "memory_lifecycle",
                    {"workspace_path": str(ws_alpha), "action": "promote", "entry_id": entry_id},
                )
                self.assertFalse(prom_err)
                self.assertEqual(prom_res["status"], "PROMOTED_TO_PROCEDURAL_RULE")
                rule_file = Path(prom_res["rule_file"])
                self.assertIn("trigger: model_decision", rule_file.read_text(encoding="utf-8"))

                # Búsqueda FTS5 con caracteres especiales y consulta federada desde ws_beta hacia AlphaMod
                for special_q in ("Papyrus.0.log", "TweakDB:SetFlat", "FO4-EP-001"):
                    s_res, s_err = client.call_tool(
                        "memory_search",
                        {"workspace_path": "AlphaMod", "query": special_q},
                    )
                    self.assertFalse(s_err)
                    self.assertEqual(s_res["status"], "OK")
                    self.assertGreaterEqual(s_res["total_hits"], 1)
                    self.assertEqual(s_res["hits"][0]["entry_id"], entry_id)

                audit_res, audit_err = client.call_tool("memory_audit", {"workspace_path": str(ws_alpha)})
                self.assertFalse(audit_err)
                self.assertEqual(audit_res["rules_budget_status"], "OK")
                self.assertLess(
                    audit_res["aggregate_always_on_budget"]["total_always_on_tokens_est"],
                    20000,
                )

            # 3) Expansión @[label](ruta), alerta SessionStart y guardián Stop anti-bucle
            docs_dir = ws_alpha / "docs"
            docs_dir.mkdir(parents=True, exist_ok=True)
            (docs_dir / "anexo.md").write_text("detalle extenso " * 1100, encoding="utf-8")
            heavy_rule = ws_alpha / ".agents" / "rules" / "pesada.md"
            heavy_rule.write_text(
                "---\ntrigger: model_decision\ndescription: Anexo pesado\n---\n\n"
                "Ver @[anexo](../../docs/anexo.md).\n",
                encoding="utf-8",
            )
            payload_start = json.dumps(
                {
                    "conversationId": "portable-conv-1",
                    "workspacePaths": [str(ws_alpha)],
                    "cwd": str(ws_alpha),
                    "terminationReason": "NO_TOOL_CALL",
                    "continuationActive": False,
                }
            )
            start_proc = subprocess.run(
                [sys.executable, str(installed_memctl), "hook-session-start"],
                input=payload_start,
                text=True,
                capture_output=True,
                encoding="utf-8",
                env=env_isolated,
                check=True,
            )
            start_msg = json.loads(start_proc.stdout)["injectSteps"][0]["systemMessage"]["systemMessage"]
            self.assertIn("ALERTA PRESUPUESTO", start_msg)

            heavy_rule.unlink()
            payload_stop = json.dumps(
                {
                    "conversationId": "portable-conv-2",
                    "workspacePaths": [str(ws_alpha)],
                    "cwd": str(ws_alpha),
                    "terminationReason": "NO_TOOL_CALL",
                    "continuationActive": False,
                }
            )
            subprocess.run(
                [sys.executable, str(installed_memctl), "hook-session-start"],
                input=payload_stop,
                text=True,
                capture_output=True,
                encoding="utf-8",
                env=env_isolated,
                check=True,
            )
            agents_path = ws_alpha / "AGENTS.md"
            agents_path.write_text(
                agents_path.read_text(encoding="utf-8") + "\n" + ("Linea repetida. " * 1100),
                encoding="utf-8",
            )
            stop_cont = subprocess.run(
                [sys.executable, str(installed_memctl), "hook-stop"],
                input=payload_stop,
                text=True,
                capture_output=True,
                encoding="utf-8",
                env=env_isolated,
                check=True,
            )
            self.assertEqual(json.loads(stop_cont.stdout)["decision"], "continue")

            payload_antiloop = json.dumps(
                {
                    "conversationId": "portable-conv-2",
                    "workspacePaths": [str(ws_alpha)],
                    "cwd": str(ws_alpha),
                    "terminationReason": "NO_TOOL_CALL",
                    "continuationActive": True,
                }
            )
            stop_safe = subprocess.run(
                [sys.executable, str(installed_memctl), "hook-stop"],
                input=payload_antiloop,
                text=True,
                capture_output=True,
                encoding="utf-8",
                env=env_isolated,
                check=True,
            )
            self.assertEqual(json.loads(stop_safe.stdout)["decision"], "stop")

            # Desinstalación limpia preservando servidor previo
            uninst_proc = subprocess.run(
                [sys.executable, str(INSTALLER), "--uninstall", "--gemini-home", str(tmp_gh)],
                text=True,
                capture_output=True,
                encoding="utf-8",
                check=True,
            )
            uninst_res = json.loads(uninst_proc.stdout)
            self.assertEqual(uninst_res["action"], "UNINSTALLED")
            self.assertTrue(uninst_res["removed_mcp_entry"])
            self.assertTrue(uninst_res["removed_plugin_dir"])
            final_mcp = json.loads(mcp_cfg.read_text(encoding="utf-8"))
            self.assertIn("existing_demo", final_mcp["mcpServers"])
            self.assertNotIn("persistent_memory", final_mcp["mcpServers"])
        finally:
            shutil.rmtree(tmp_gh, ignore_errors=True)
            shutil.rmtree(ws_alpha, ignore_errors=True)
            shutil.rmtree(ws_beta, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
