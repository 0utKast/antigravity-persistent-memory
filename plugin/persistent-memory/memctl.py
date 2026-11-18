#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Motor Local-First de Memoria Persistente en 4 Capas (L0-L3).

Gestiona diarios Markdown portables bajo Git (Escape Hatch), enrutamiento por
ámbitos (MEMORIA_INDICE.md), índice efímero SQLite FTS5/BM25, compuerta
anti-envenenamiento (PROVISIONAL -> VERIFIED), ascenso N >= 2 a reglas
modulares (.agents/rules/*.md) y auditoría estricta del límite de 24.000 bytes.

Python 3 estándar (0 dependencias externas).
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime
import json
import os
import re
import sqlite3
import sys
import tempfile
import time
import urllib.parse
from pathlib import Path
from typing import Any


def configure_utf8_stdio() -> None:
    """Fuerza codificación UTF-8 segura en consola Windows."""
    for stream_name in ("stdin", "stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


configure_utf8_stdio()

PLUGIN_ROOT = Path(__file__).resolve().parent
REGISTRY_PATH = PLUGIN_ROOT / "workspaces_registry.json"

RULE_HARD_LIMIT_BYTES = 24000
SAFE_PROMOTE_LIMIT_BYTES = 18000
RULE_OK_LIMIT_BYTES = 12000
RULE_WARN_LIMIT_BYTES = 16000
RULE_CRIT_LIMIT_BYTES = 23000

AGGREGATE_TOKEN_LIMIT = 20000
AGGREGATE_TOKEN_OK = 12000
AGGREGATE_TOKEN_WARN = 15000
AGGREGATE_TOKEN_CRIT = 18500
RULE_INCLUDE_RE = re.compile(r"@\[[^\]]*\]\(([^)]+)\)")
SEVERITY_ORDER = {"OK": 0, "WATCH": 1, "WARNING": 2, "CRITICAL": 3}

ENTRY_HEADER_RE = re.compile(r"^##\s+\[([A-Za-z0-9_]+-EP-\d+)\]\s+(.+?)\s*$")
FIELD_RE = re.compile(r"^-\s+\*\*([^*:]+):\*\*\s*(.*)$")

FIELD_KEY_MAP = {
    "estado": "status",
    "fecha": "date",
    "ámbito": "scope",
    "ambito": "scope",
    "entorno / herramientas": "environment",
    "entorno": "environment",
    "ocurrencias": "occurrences",
    "regla promovida": "promoted_rule",
    "síntoma / log exacto": "symptom",
    "sintoma / log exacto": "symptom",
    "síntoma": "symptom",
    "sintoma": "symptom",
    "trampa semántica (hipótesis descartadas)": "semantic_trap",
    "trampa semantica (hipotesis descartadas)": "semantic_trap",
    "trampa semántica": "semantic_trap",
    "trampa semantica": "semantic_trap",
    "causa raíz": "root_cause",
    "causa raiz": "root_cause",
    "solución determinista": "deterministic_fix",
    "solucion determinista": "deterministic_fix",
    "evidencia de verificación (provenance)": "provenance",
    "evidencia de verificacion (provenance)": "provenance",
    "evidencia de verificación": "provenance",
    "evidencia de verificacion": "provenance",
}

SCOPE_DESCRIPTIONS = {
    "camtasia_montaje_4k": "Camtasia `.tscproj`, `rangeEnd` UTF-8, transiciones y enmarcados 4K.",
    "elevenlabs_locucion_es_en": "Locución ElevenLabs ES/EN, aislamiento de siglas y calibración PVC.",
    "guiones_visualizadores_typst": "Guiones, textos de diapositivas, visualizadores HTML y maquetación Typst/PDF.",
    "combate_ia_y_actores": "Facciones, `Aggression`/`Assistance`, `NPC_` faciales y equipo en `Creation Engine`.",
    "havok_celdas_y_nifs": "Física Havok, `Precombines`, `LAND`/`STAT`, orientación `.nif` y colocación `TERM`.",
    "misiones_escenas_y_saves": "`QUST`/`GREE`/`SCEN`, `OnPlayerLoadGame`, `OnMenuItemRun` y migraciones `.fos`.",
    "binarios_ba2_y_compilador": "Cabeceras `.esp` `HEDR`, `.ba2 v1`, `.esl` 12 bits y `PapyrusCompiler.exe`.",
    "misiones_mappins_y_mundo": "Rutas GPS `.journal`, bloqueo Watson Acto 1 y guardias `SceneTier == 1`.",
    "dialogos_ui_y_cet": "Menús `dialogWidgetGameController`, `LinearWipe_0`, `LootData` y paneles `CET`.",
    "audioware_voces_y_animacion": "`Audioware` `Session/Ready`, `LocaleExt`, recorte PCM y lip-sync facial.",
    "entidades_dispositivos_y_combate": "Cámaras, torretas, depósitos, `IsNpcNeutralized`, `HasSmartLink` y CR2W.",
    "arquitectura_y_diseno": "Decisiones arquitectónicas, contratos de módulos y límites del sistema.",
    "depuracion_y_entorno": "Errores de compilación, entorno local, dependencias y pruebas en vivo.",
    "arquitectura_python_y_modulos": "Diseño de módulos Python, empaquetado, UTF-8 y compatibilidad CLI/MCP.",
    "dependencias_y_entorno": "Entornos virtuales, librerías estándar y configuración local Windows.",
    "pruebas_y_depuracion": "Suites de pruebas, diagnósticos deterministas y manejo de fallos.",
    "arquitectura_rust_y_crates": "Crates, lifetimes, FFI y estructura de módulos en Rust.",
    "compilacion_y_ffi": "Toolchain Cargo, enlazado nativo y objetivos de compilación.",
    "arquitectura_frontend_y_api": "Componentes, estado, contratos HTTP/WebSocket y UI.",
    "dependencias_y_build": "Empaquetadores, lockfiles y configuración de compilación.",
}


@dataclasses.dataclass
class DiaryEntry:
    """Representa una entrada episódica persistida en Markdown."""

    entry_id: str
    title: str
    status: str
    date: str
    scope: str
    environment: str
    occurrences: int
    promoted_rule: str
    symptom: str
    semantic_trap: str
    root_cause: str
    deterministic_fix: str
    provenance: str
    file_path: str = ""


def today_iso() -> str:
    return datetime.date.today().isoformat()


def strip_backticks(value: str) -> str:
    txt = value.strip()
    if txt.startswith("`") and txt.endswith("`") and len(txt) >= 2:
        return txt[1:-1].strip()
    return txt


def parse_occurrences(value: str) -> int:
    clean = strip_backticks(value)
    match = re.search(r"\d+", clean)
    return int(match.group(0)) if match else 1


def estimate_tokens(text: str) -> int:
    byte_len = len(text.encode("utf-8"))
    return max(1, (byte_len + 3) // 4) if byte_len > 0 else 0


def classify_rule_bytes(byte_len: int) -> str:
    if byte_len >= RULE_CRIT_LIMIT_BYTES:
        return "CRITICAL"
    if byte_len >= RULE_WARN_LIMIT_BYTES:
        return "WARNING"
    if byte_len >= RULE_OK_LIMIT_BYTES:
        return "WATCH"
    return "OK"


def classify_aggregate_tokens(tokens: int) -> str:
    if tokens >= AGGREGATE_TOKEN_CRIT:
        return "CRITICAL"
    if tokens >= AGGREGATE_TOKEN_WARN:
        return "WARNING"
    if tokens >= AGGREGATE_TOKEN_OK:
        return "WATCH"
    return "OK"


def parse_rule_trigger(path: Path, text: str) -> str:
    if path.name.upper() in ("AGENTS.MD", "GEMINI.MD") and path.parent.name.lower() != "rules":
        return "always_on"
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        for line in lines[1:40]:
            stripped = line.strip()
            if stripped == "---":
                break
            if re.match(r"^trigger\s*:\s*model_decision\b", stripped, flags=re.IGNORECASE):
                return "model_decision"
    return "always_on"


def resolve_include_target(base_dir: Path, raw_target: str) -> Path | None:
    target = raw_target.strip().strip('"').strip("'")
    if not target or target.startswith("#"):
        return None
    low = target.lower()
    if low.startswith(("http://", "https://", "mailto:", "javascript:")):
        return None

    candidates_raw: list[str] = []
    if low.startswith("file://"):
        parsed = urllib.parse.urlparse(target)
        p_str = urllib.parse.unquote(parsed.path)
        if re.match(r"^/[A-Za-z]:", p_str):
            p_str = p_str[1:]
        if p_str:
            candidates_raw.append(p_str)
    else:
        candidates_raw.append(target)
        if "#" in target:
            candidates_raw.append(target.split("#", 1)[0])

    for raw_cand in candidates_raw:
        if not raw_cand:
            continue
        try:
            cand = Path(raw_cand).expanduser()
            if not cand.is_absolute():
                cand = base_dir / cand
            resolved = cand.resolve()
            if resolved.exists():
                return resolved
        except Exception:
            continue
    return None


def expand_rule_includes(
    base_dir: Path,
    text: str,
    _visited: set[Path] | None = None,
    _depth: int = 0,
) -> str:
    if _depth >= 3:
        return text
    visited = set(_visited) if _visited is not None else set()

    def _replace(match: re.Match[str]) -> str:
        target_path = resolve_include_target(base_dir, match.group(1))
        if target_path is None or target_path in visited:
            return match.group(0)
        try:
            if not target_path.is_file() or target_path.stat().st_size >= 512 * 1024:
                return match.group(0)
            inc_text = target_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return match.group(0)
        return expand_rule_includes(
            target_path.parent,
            inc_text,
            _visited=visited | {target_path},
            _depth=_depth + 1,
        )

    return RULE_INCLUDE_RE.sub(_replace, text)


def measure_rule_file(
    path: Path,
    raw_text: str | None = None,
    rel_label: str | None = None,
) -> dict[str, Any]:
    raw = raw_text if raw_text is not None else path.read_text(encoding="utf-8", errors="replace")
    raw_bytes = len(raw.encode("utf-8"))
    resolved_path = path.resolve()
    expanded = expand_rule_includes(path.parent, raw, _visited={resolved_path})
    effective_bytes = max(raw_bytes, len(expanded.encode("utf-8")))
    trigger = parse_rule_trigger(path, raw)
    tokens_est = estimate_tokens(expanded)
    st = classify_rule_bytes(effective_bytes)
    return {
        "file": rel_label or path.name,
        "path": str(resolved_path),
        "bytes": raw_bytes,
        "effective_bytes": effective_bytes,
        "tokens_est": tokens_est,
        "trigger": trigger,
        "limit_bytes": RULE_HARD_LIMIT_BYTES,
        "usage_pct": round((effective_bytes / RULE_HARD_LIMIT_BYTES) * 100.0, 1),
        "status": st,
    }


def get_default_gemini_home() -> Path:
    raw = os.environ.get("AGY_GEMINI_HOME") or str(Path.home() / ".gemini")
    return Path(raw).expanduser().resolve()


def audit_global_rules(gemini_home: Path | None = None) -> dict[str, Any]:
    gh = (gemini_home or get_default_gemini_home()).resolve()
    plugins_cfg: dict[str, Any] = {}
    cfg_path = gh / "config" / "config.json"
    if cfg_path.exists():
        try:
            cfg_data = json.loads(cfg_path.read_text(encoding="utf-8", errors="replace"))
            if isinstance(cfg_data, dict) and isinstance(cfg_data.get("plugins"), dict):
                plugins_cfg = cfg_data["plugins"]
        except Exception:
            pass

    candidates: list[tuple[Path, str]] = []
    seen: set[Path] = set()

    def add_candidate(p: Path) -> None:
        if not p.is_file():
            return
        resolved = p.resolve()
        if resolved in seen:
            return
        seen.add(resolved)
        try:
            rel = resolved.relative_to(gh).as_posix()
            label = f"~/.gemini/{rel}"
        except ValueError:
            label = str(resolved)
        candidates.append((p, label))

    for root_name in ("GEMINI.md", "AGENTS.md"):
        add_candidate(gh / root_name)

    global_rules_dir = gh / "config" / "rules"
    if global_rules_dir.exists():
        for p in sorted(global_rules_dir.glob("*.md")):
            add_candidate(p)

    plugins_dir = gh / "config" / "plugins"
    if plugins_dir.exists():
        for pdir in sorted(plugins_dir.iterdir()):
            if not pdir.is_dir():
                continue
            p_info = plugins_cfg.get(pdir.name)
            if isinstance(p_info, dict) and p_info.get("enabled") is False:
                continue
            prules_dir = pdir / "rules"
            if prules_dir.exists():
                for p in sorted(prules_dir.glob("*.md")):
                    add_candidate(p)

    rule_files_report: list[dict[str, Any]] = []
    worst_status = "OK"
    for p, label in candidates:
        metrics = measure_rule_file(p, rel_label=label)
        if SEVERITY_ORDER[metrics["status"]] > SEVERITY_ORDER[worst_status]:
            worst_status = metrics["status"]
        rule_files_report.append(metrics)

    global_always_on_tokens = sum(
        item["tokens_est"] for item in rule_files_report if item["trigger"] == "always_on"
    )
    return {
        "gemini_home": str(gh),
        "status": worst_status,
        "always_on_tokens_est": global_always_on_tokens,
        "rule_files": rule_files_report,
    }


def collect_workspace_rule_files(workspace: Path) -> list[Path]:
    candidates: list[Path] = []
    seen: set[Path] = set()

    def add_if_new(p: Path) -> None:
        if not p.is_file():
            return
        resolved = p.resolve()
        if resolved not in seen:
            seen.add(resolved)
            candidates.append(p)

    if workspace.exists():
        skip_dirs = {
            ".git",
            ".agents",
            ".agent",
            "_agents",
            "_agent",
            "memoria",
            "node_modules",
            ".venv",
            "venv",
            "__pycache__",
            "dist",
            "build",
            "target",
        }
        for root, dirs, _files in os.walk(workspace):
            root_path = Path(root)
            rel_parts = root_path.relative_to(workspace).parts
            dirs[:] = sorted(d for d in dirs if d not in skip_dirs)
            if len(rel_parts) >= 3:
                dirs[:] = []
            for root_name in ("AGENTS.md", "GEMINI.md"):
                add_if_new(root_path / root_name)

    rules_dir = workspace / ".agents" / "rules"
    if rules_dir.exists():
        for p in sorted(rules_dir.glob("*.md")):
            add_if_new(p)

    return candidates


def load_registry() -> dict[str, Any]:
    if not REGISTRY_PATH.exists():
        return {"workspaces": {}}
    try:
        data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("workspaces"), dict):
            return data
    except Exception:
        pass
    return {"workspaces": {}}


def save_registry(data: dict[str, Any]) -> None:
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def register_workspace(
    workspace_path: Path,
    name: str | None = None,
    prefix: str | None = None,
) -> None:
    resolved = workspace_path.resolve()
    key = (name or resolved.name).strip()
    data = load_registry()
    workspaces = data.setdefault("workspaces", {})
    existing = workspaces.get(key, {})
    workspaces[key] = {
        "path": str(resolved),
        "prefix": prefix or existing.get("prefix") or derive_prefix(key),
        "updated_at": today_iso(),
    }
    save_registry(data)


def unregister_workspace(workspace_or_alias: str) -> bool:
    data = load_registry()
    workspaces = data.get("workspaces", {})
    removed = False
    target_norm = workspace_or_alias.strip().lower()
    to_delete = []
    for key, info in workspaces.items():
        path_val = str(info.get("path", "")).lower()
        if key.lower() == target_norm or path_val == target_norm:
            to_delete.append(key)
    for key in to_delete:
        del workspaces[key]
        removed = True
    if removed:
        save_registry(data)
    return removed


def resolve_workspace(workspace_arg: str) -> Path:
    raw = workspace_arg.strip()
    registry = load_registry()
    for alias, info in registry.get("workspaces", {}).items():
        if alias.lower() == raw.lower():
            return Path(info["path"]).resolve()
    return Path(raw).expanduser().resolve()


def derive_prefix(project_name: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9]+", " ", project_name).strip()
    if not clean:
        return "PRJ"
    words = clean.split()
    if len(words) == 1:
        caps = re.findall(r"[A-Z]", words[0])
        if 2 <= len(caps) <= 4:
            return "".join(caps)
        return re.sub(r"[^A-Za-z0-9]", "", words[0])[:4].upper() or "PRJ"
    initials = "".join(w[0].upper() for w in words[:4] if w)
    return initials or "PRJ"


def detect_project_profile(workspace: Path) -> tuple[str, list[str]]:
    name_low = workspace.name.lower()
    exts: set[str] = set()
    names: set[str] = set()

    if workspace.exists():
        skip_dirs = {".git", ".agents", "memoria", "__pycache__", "node_modules", ".venv"}
        for root, dirs, files in os.walk(workspace):
            rel_parts = Path(root).relative_to(workspace).parts
            dirs[:] = [d for d in dirs if d not in skip_dirs]
            if len(rel_parts) >= 2:
                dirs[:] = []
            for d in dirs:
                names.add(d.lower())
            for f in files:
                names.add(f.lower())
                exts.add(Path(f).suffix.lower())

    if "fallout" in name_low or exts & {".esp", ".esm", ".esl", ".psc"}:
        return (
            "FO4",
            [
                "combate_ia_y_actores",
                "havok_celdas_y_nifs",
                "misiones_escenas_y_saves",
                "binarios_ba2_y_compilador",
            ],
        )
    if "cyberpunk" in name_low or ".reds" in exts or ".archive" in exts or "r6" in names:
        return (
            "CP77",
            [
                "misiones_mappins_y_mundo",
                "dialogos_ui_y_cet",
                "audioware_voces_y_animacion",
                "entidades_dispositivos_y_combate",
            ],
        )
    if "curso" in name_low or ".tscproj" in exts:
        return (
            "DC",
            [
                "camtasia_montaje_4k",
                "elevenlabs_locucion_es_en",
                "guiones_visualizadores_typst",
            ],
        )
    if "cargo.toml" in names or ".rs" in exts:
        return (
            derive_prefix(workspace.name),
            ["arquitectura_rust_y_crates", "compilacion_y_ffi", "depuracion_y_tests"],
        )
    if "package.json" in names or exts & {".ts", ".tsx", ".js", ".jsx"}:
        return (
            derive_prefix(workspace.name),
            ["arquitectura_frontend_y_api", "dependencias_y_build", "depuracion_y_entorno"],
        )
    if "pyproject.toml" in names or "requirements.txt" in names or ".py" in exts:
        return (
            derive_prefix(workspace.name),
            ["arquitectura_python_y_modulos", "dependencias_y_entorno", "pruebas_y_depuracion"],
        )
    return (
        derive_prefix(workspace.name),
        ["arquitectura_y_diseno", "depuracion_y_entorno"],
    )


def get_workspace_config(workspace: Path) -> dict[str, Any]:
    cfg_path = workspace / "memoria" / "memoria_config.json"
    if cfg_path.exists():
        try:
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {}


def save_workspace_config(workspace: Path, project_name: str, prefix: str) -> None:
    cfg_path = workspace / "memoria" / "memoria_config.json"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(
        json.dumps(
            {
                "project_name": project_name,
                "prefix": prefix,
                "updated_at": today_iso(),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def get_project_prefix(workspace: Path) -> str:
    cfg = get_workspace_config(workspace)
    if cfg.get("prefix"):
        return str(cfg["prefix"]).upper()
    diaries_dir = workspace / "memoria" / "diarios"
    if diaries_dir.exists():
        for p in sorted(diaries_dir.glob("*.md")):
            for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
                m = ENTRY_HEADER_RE.match(line)
                if m:
                    return m.group(1).split("-EP-")[0].upper()
    detected_prefix, _ = detect_project_profile(workspace)
    return detected_prefix


def parse_diary_file(path: Path) -> tuple[str, list[DiaryEntry]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    scope_default = path.stem

    header_lines: list[str] = []
    entries: list[DiaryEntry] = []

    idx = 0
    while idx < len(lines):
        if ENTRY_HEADER_RE.match(lines[idx]):
            break
        header_lines.append(lines[idx])
        idx += 1

    while len(header_lines) > 0 and header_lines[-1].strip() in ("", "---"):
        header_lines.pop()

    header = "\n".join(header_lines).strip()
    if not header:
        header = (
            f"# Diario Episódico — `{scope_default}`\n\n"
            "Registro verificable de descubrimientos técnicos y trampas semánticas."
        )

    current_id: str | None = None
    current_title = ""
    current_fields: dict[str, list[str]] = {}
    active_field_key: str | None = None

    def flush_entry() -> None:
        nonlocal current_id, current_title, current_fields, active_field_key
        if not current_id:
            return
        fields_str = {k: "\n".join(v).strip() for k, v in current_fields.items()}
        entries.append(
            DiaryEntry(
                entry_id=current_id,
                title=current_title,
                status=strip_backticks(fields_str.get("status", "PROVISIONAL")) or "PROVISIONAL",
                date=strip_backticks(fields_str.get("date", today_iso())) or today_iso(),
                scope=strip_backticks(fields_str.get("scope", scope_default)) or scope_default,
                environment=strip_backticks(fields_str.get("environment", "No especificado")),
                occurrences=parse_occurrences(fields_str.get("occurrences", "1")),
                promoted_rule=strip_backticks(fields_str.get("promoted_rule", "Ninguna")) or "Ninguna",
                symptom=fields_str.get("symptom", ""),
                semantic_trap=fields_str.get("semantic_trap", ""),
                root_cause=fields_str.get("root_cause", ""),
                deterministic_fix=fields_str.get("deterministic_fix", ""),
                provenance=fields_str.get("provenance", ""),
                file_path=str(path),
            )
        )
        current_id = None
        current_title = ""
        current_fields = {}
        active_field_key = None

    while idx < len(lines):
        line = lines[idx]
        m_head = ENTRY_HEADER_RE.match(line)
        if m_head:
            flush_entry()
            current_id = m_head.group(1).strip()
            current_title = m_head.group(2).strip()
            idx += 1
            continue

        if current_id is not None:
            if line.strip() == "---":
                active_field_key = None
                idx += 1
                continue
            m_field = FIELD_RE.match(line)
            if m_field:
                raw_key = m_field.group(1).strip().lower()
                mapped_key = FIELD_KEY_MAP.get(raw_key)
                if mapped_key:
                    active_field_key = mapped_key
                    first_val = m_field.group(2).rstrip()
                    current_fields[mapped_key] = [first_val] if first_val else []
                    idx += 1
                    continue
            if active_field_key is not None:
                if line.strip() or current_fields.get(active_field_key):
                    current_fields.setdefault(active_field_key, []).append(line.rstrip())
        idx += 1

    flush_entry()
    return header, entries


def format_multiline_field(value: str) -> str:
    clean = value.strip()
    if "\n" not in clean:
        return clean
    lines = clean.splitlines()
    first = lines[0].strip()
    rest = "\n".join(line if line.startswith("  ") else f"  {line}" for line in lines[1:])
    if first:
        return f"{first}\n{rest}"
    return f"\n{rest}"


def render_diary_file(header: str, entries: list[DiaryEntry]) -> str:
    parts = [header.rstrip(), ""]
    for entry in entries:
        parts.append("---")
        parts.append("")
        parts.append(f"## [{entry.entry_id}] {entry.title}")
        parts.append(f"- **Estado:** `{entry.status}`")
        parts.append(f"- **Fecha:** `{entry.date}`")
        parts.append(f"- **Ámbito:** `{entry.scope}`")
        parts.append(f"- **Entorno / Herramientas:** `{entry.environment}`")
        parts.append(f"- **Ocurrencias:** `{entry.occurrences}`")
        parts.append(f"- **Regla Promovida:** `{entry.promoted_rule}`")
        parts.append(f"- **Síntoma / Log Exacto:** {format_multiline_field(entry.symptom)}")
        parts.append(
            f"- **Trampa Semántica (Hipótesis Descartadas):** {format_multiline_field(entry.semantic_trap)}"
        )
        parts.append(f"- **Causa Raíz:** {format_multiline_field(entry.root_cause)}")
        parts.append(
            f"- **Solución Determinista:** {format_multiline_field(entry.deterministic_fix)}"
        )
        parts.append(
            f"- **Evidencia de Verificación (Provenance):** {format_multiline_field(entry.provenance)}"
        )
        parts.append("")
    return "\n".join(parts).rstrip() + "\n"


def load_all_entries(workspace: Path) -> list[DiaryEntry]:
    diaries_dir = workspace / "memoria" / "diarios"
    if not diaries_dir.exists():
        return []
    entries: list[DiaryEntry] = []
    for p in sorted(diaries_dir.glob("*.md")):
        _, file_entries = parse_diary_file(p)
        entries.extend(file_entries)
    return entries


def rebuild_fts(workspace: Path, entries: list[DiaryEntry] | None = None) -> Path:
    if entries is None:
        entries = load_all_entries(workspace)
    cache_dir = workspace / "memoria" / ".cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    db_path = cache_dir / "memoria_fts.sqlite"

    conn = sqlite3.connect(str(db_path), timeout=10.0)
    try:
        conn.execute("PRAGMA journal_mode=DELETE;")
        with conn:
            conn.execute("DROP TABLE IF EXISTS episodes_fts;")
            conn.execute(
                "CREATE VIRTUAL TABLE episodes_fts USING fts5("
                "entry_id, title, status, scope, environment, "
                "symptom, semantic_trap, root_cause, deterministic_fix, provenance, file_path, "
                "tokenize='unicode61 remove_diacritics 2'"
                ");"
            )
            for e in entries:
                conn.execute(
                    "INSERT INTO episodes_fts("
                    "entry_id, title, status, scope, environment, "
                    "symptom, semantic_trap, root_cause, deterministic_fix, provenance, file_path"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);",
                    (
                        e.entry_id,
                        e.title,
                        e.status,
                        e.scope,
                        e.environment,
                        e.symptom,
                        e.semantic_trap,
                        e.root_cause,
                        e.deterministic_fix,
                        e.provenance,
                        e.file_path,
                    ),
                )
    finally:
        conn.close()
    return db_path


def ensure_fts_fresh(workspace: Path) -> Path:
    db_path = workspace / "memoria" / ".cache" / "memoria_fts.sqlite"
    diaries_dir = workspace / "memoria" / "diarios"
    diary_files = sorted(diaries_dir.glob("*.md")) if diaries_dir.exists() else []
    if not db_path.exists():
        return rebuild_fts(workspace)
    db_mtime = db_path.stat().st_mtime
    for p in diary_files:
        if p.stat().st_mtime > db_mtime:
            return rebuild_fts(workspace)
    return db_path


def entry_num_key(entry: DiaryEntry) -> tuple[int, str]:
    """Ordena entradas por número de secuencia EP."""
    m = re.search(r"-EP-(\d+)$", entry.entry_id)
    return (int(m.group(1)) if m else 0, entry.entry_id)


def entry_chrono_key(entry: DiaryEntry) -> tuple[str, int]:
    """Ordena entradas cronológicamente por fecha y secuencia EP."""
    num, _ = entry_num_key(entry)
    return (entry.date, num)


def sync_index(workspace: Path) -> dict[str, Any]:
    memoria_dir = workspace / "memoria"
    diaries_dir = memoria_dir / "diarios"
    diaries_dir.mkdir(parents=True, exist_ok=True)

    cfg = get_workspace_config(workspace)
    project_name = cfg.get("project_name") or workspace.name
    prefix = get_project_prefix(workspace)

    diary_files = sorted(diaries_dir.glob("*.md"))
    all_entries: list[DiaryEntry] = []
    scope_rows: list[str] = []
    active_entries: list[DiaryEntry] = []
    superseded_count = 0

    for p in diary_files:
        scope_name = p.stem
        _, entries = parse_diary_file(p)
        all_entries.extend(entries)
        verified_n = sum(1 for e in entries if e.status.upper() == "VERIFIED")
        provisional_n = sum(1 for e in entries if e.status.upper() == "PROVISIONAL")
        sup_n = sum(1 for e in entries if e.status.upper().startswith("SUPERSEDED_BY"))
        superseded_count += sup_n
        active_n = verified_n + provisional_n
        rel_link = f"diarios/{p.name}"
        scope_rows.append(
            f"| `{scope_name}` | {active_n} ({verified_n} VERIFIED / {provisional_n} PROVISIONAL) | [`{p.name}`]({rel_link}) |"
        )
        for e in entries:
            if not e.status.upper().startswith("SUPERSEDED_BY"):
                active_entries.append(e)

    map_lines = [
        f"- `{e.entry_id}` [{'V' if e.status.upper() == 'VERIFIED' else 'P'} x{e.occurrences}] "
        f"{e.title if len(e.title) <= 68 else e.title[:65] + '...'}"
        for e in sorted(active_entries, key=entry_num_key)
    ]

    lines = [
        f"# Índice de Memoria Persistente — `{project_name}` (`{prefix}`)",
        "",
        "> Enrutador ligero (*Scoped Access*). Usa `memory_search` para consultas puntuales o abre **solo** el diario del ámbito necesario.",
        "",
        "| Ámbito | Entradas Activas | Diario Canónico |",
        "| :--- | :---: | :--- |",
        *scope_rows,
        "",
        "## Mapa Compacto de Entradas Activas",
        *(map_lines if map_lines else ["- *(Sin entradas activas todavía)*"]),
    ]
    if superseded_count > 0:
        lines.append(f"\n*Entradas obsoletas sustituidas (`SUPERSEDED_BY`): {superseded_count}.*")

    index_path = memoria_dir / "MEMORIA_INDICE.md"
    index_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    gitignore_path = memoria_dir / ".gitignore"
    if not gitignore_path.exists():
        gitignore_path.write_text(".cache/\n*.sqlite\n*.sqlite-*\n", encoding="utf-8")

    db_path = rebuild_fts(workspace, all_entries)
    return {
        "index_path": str(index_path),
        "db_path": str(db_path),
        "entries_total": len(all_entries),
        "scopes": [p.stem for p in diary_files],
    }


def init_workspace(
    workspace_arg: str,
    project_name: str | None = None,
    prefix: str | None = None,
    scopes: list[str] | None = None,
    register: bool = True,
) -> dict[str, Any]:
    workspace = Path(workspace_arg).expanduser().resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    resolved_name = (project_name or workspace.name).strip()

    detected_prefix, detected_scopes = detect_project_profile(workspace)
    resolved_prefix = (prefix or detected_prefix).upper()
    resolved_scopes = [s.strip() for s in (scopes or detected_scopes) if s.strip()]
    if not resolved_scopes:
        resolved_scopes = ["arquitectura_y_diseno", "depuracion_y_entorno"]

    save_workspace_config(workspace, resolved_name, resolved_prefix)

    memoria_dir = workspace / "memoria"
    diaries_dir = memoria_dir / "diarios"
    diaries_dir.mkdir(parents=True, exist_ok=True)
    (memoria_dir / ".cache").mkdir(parents=True, exist_ok=True)
    (memoria_dir / ".gitignore").write_text(".cache/\n*.sqlite\n*.sqlite-*\n", encoding="utf-8")

    rules_dir = workspace / ".agents" / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)

    created_diaries: list[str] = []
    for sc in resolved_scopes:
        diary_file = diaries_dir / f"{sc}.md"
        if not diary_file.exists():
            desc = SCOPE_DESCRIPTIONS.get(
                sc,
                f"Descubrimientos técnicos verificados y trampas semánticas del ámbito `{sc}`.",
            )
            diary_file.write_text(
                f"# Diario Episódico — `{sc}` ({resolved_name})\n\n{desc}\n",
                encoding="utf-8",
            )
            created_diaries.append(str(diary_file))

    agents_path = workspace / "AGENTS.md"
    agents_created = False
    if not agents_path.exists():
        agents_text = (
            f"# Constitución Operativa — `{resolved_name}` (`AGENTS.md`)\n\n"
            "Archivo de memoria procedimental preventiva (*Capa L0*). Debe mantenerse siempre compacto "
            "(`< 12.000 bytes`, lejos del límite duro de `24.000 bytes` de Antigravity).\n\n"
            "## Protocolo de Memoria Persistente (Capas L0–L3)\n"
            "1. **Consulta previa obligatoria:** Antes de depurar fallos no triviales o modificar subsistemas "
            "críticos, consulta `memory_search` sobre este espacio de trabajo o abre el ámbito exacto desde "
            "[`memoria/MEMORIA_INDICE.md`](memoria/MEMORIA_INDICE.md).\n"
            "2. **Compuerta Anti-Envenenamiento (`PROVISIONAL` -> `VERIFIED`):** Toda solución verificada con "
            "compilador/tests en verde se consolida mediante `memory_record` con **Trampa Semántica** y **Provenance**.\n"
            "3. **Ascenso modular ($N \\ge 2$):** Las reglas recurrentes verificadas se promueven a archivos "
            "condicionales en `.agents/rules/` (`trigger: model_decision`), nunca engordando `AGENTS.md`.\n"
        )
        agents_path.write_text(agents_text, encoding="utf-8")
        agents_created = True

    sync_res = sync_index(workspace)
    if register:
        register_workspace(workspace, name=resolved_name, prefix=resolved_prefix)

    return {
        "status": "INITIALIZED",
        "workspace": str(workspace),
        "project_name": resolved_name,
        "prefix": resolved_prefix,
        "scopes": resolved_scopes,
        "agents_created": agents_created,
        "created_diaries": created_diaries,
        "sync": sync_res,
    }


def sanitize_fts_terms(query: str) -> list[str]:
    raw_tokens = re.findall(r"\w+", query, flags=re.UNICODE)
    tokens: list[str] = []
    seen: set[str] = set()
    for tok in raw_tokens:
        if len(tok) >= 2 and tok.lower() not in seen:
            seen.add(tok.lower())
            tokens.append(tok)
    if not tokens:
        for tok in raw_tokens:
            if tok and tok.lower() not in seen:
                seen.add(tok.lower())
                tokens.append(tok)
    return tokens


def search_memory(
    workspace_arg: str,
    query: str,
    scope: str | None = None,
    limit: int = 5,
    include_superseded: bool = False,
) -> dict[str, Any]:
    workspace = resolve_workspace(workspace_arg)
    if not (workspace / "memoria" / "diarios").exists():
        return {
            "status": "NOT_INITIALIZED",
            "workspace": str(workspace),
            "hits": [],
            "message": "El workspace no tiene memoria inicializada en memoria/diarios/.",
        }

    db_path = ensure_fts_fresh(workspace)
    tokens = sanitize_fts_terms(query)
    if not tokens:
        return {
            "status": "EMPTY_QUERY",
            "workspace": str(workspace),
            "hits": [],
            "query_tokens": [],
        }

    entries_by_id = {e.entry_id: e for e in load_all_entries(workspace)}
    fts_queries: list[str] = []
    and_q = " AND ".join(f'"{t}"' for t in tokens)
    fts_queries.append(and_q)
    if len(tokens) > 1:
        fts_queries.append(" OR ".join(f'"{t}"' for t in tokens))

    hits: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    conn = sqlite3.connect(str(db_path), timeout=10.0)
    try:
        for fq in fts_queries:
            if len(hits) >= limit:
                break
            sql = (
                "SELECT entry_id, bm25(episodes_fts, 8.0, 5.0, 1.0, 2.0, 2.0, 6.0, 3.0, 4.0, 5.0, 1.5, 0.5) AS rank "
                "FROM episodes_fts WHERE episodes_fts MATCH ?"
            )
            params: list[Any] = [fq]
            if scope:
                sql += " AND scope = ?"
                params.append(scope)
            if not include_superseded:
                sql += " AND status NOT LIKE 'SUPERSEDED_BY%'"
            sql += " ORDER BY rank LIMIT ?"
            params.append(limit)

            rows = conn.execute(sql, params).fetchall()
            for entry_id, rank in rows:
                if entry_id in seen_ids:
                    continue
                seen_ids.add(entry_id)
                e = entries_by_id.get(entry_id)
                if e is None:
                    continue
                hits.append(
                    {
                        "entry_id": e.entry_id,
                        "title": e.title,
                        "status": e.status,
                        "date": e.date,
                        "scope": e.scope,
                        "environment": e.environment,
                        "occurrences": e.occurrences,
                        "promoted_rule": e.promoted_rule,
                        "symptom": e.symptom,
                        "semantic_trap": e.semantic_trap,
                        "root_cause": e.root_cause,
                        "deterministic_fix": e.deterministic_fix,
                        "provenance": e.provenance,
                        "file_path": e.file_path,
                        "bm25_score": round(float(rank), 4),
                    }
                )
    finally:
        conn.close()

    return {
        "status": "OK",
        "workspace": str(workspace),
        "query": query,
        "query_tokens": tokens,
        "fts_queries_used": fts_queries,
        "total_hits": len(hits),
        "hits": hits,
    }


def next_entry_id(workspace: Path, prefix: str) -> str:
    diaries_dir = workspace / "memoria" / "diarios"
    max_num = 0
    pattern = re.compile(rf"^{re.escape(prefix)}-EP-(\d+)$")
    if diaries_dir.exists():
        for e in load_all_entries(workspace):
            m = pattern.match(e.entry_id)
            if m:
                max_num = max(max_num, int(m.group(1)))
    return f"{prefix}-EP-{max_num + 1:03d}"


def record_memory(
    workspace_arg: str,
    scope: str,
    title: str,
    environment: str,
    symptom: str,
    semantic_trap: str,
    root_cause: str,
    deterministic_fix: str,
    provenance: str,
    status: str = "PROVISIONAL",
    exit_code: int = 0,
    log_errors: list[str] | None = None,
    entry_date: str | None = None,
    occurrences: int = 1,
    promoted_rule: str = "Ninguna",
) -> dict[str, Any]:
    workspace = resolve_workspace(workspace_arg)
    norm_status = status.strip().upper()
    if norm_status not in ("PROVISIONAL", "VERIFIED"):
        norm_status = "PROVISIONAL"

    cleaned_errors = [err.strip() for err in (log_errors or []) if err and err.strip()]
    rejection_reasons: list[str] = []
    if exit_code != 0:
        rejection_reasons.append(f"exit_code={exit_code} (!= 0)")
    if cleaned_errors:
        rejection_reasons.append(f"log_errors presentes={cleaned_errors}")
    if len(root_cause.strip()) < 10:
        rejection_reasons.append("root_cause insuficiente (< 10 caracteres)")
    if len(deterministic_fix.strip()) < 10:
        rejection_reasons.append("deterministic_fix insuficiente (< 10 caracteres)")
    if len(provenance.strip()) < 10:
        rejection_reasons.append("provenance insuficiente (< 10 caracteres)")
    if len(semantic_trap.strip()) < 5:
        rejection_reasons.append("semantic_trap insuficiente (< 5 caracteres)")

    if rejection_reasons:
        return {
            "status": "REJECTED_MEMORY_POISONING",
            "workspace": str(workspace),
            "scope": scope,
            "reason": "; ".join(rejection_reasons),
        }

    diaries_dir = workspace / "memoria" / "diarios"
    if not diaries_dir.exists():
        init_workspace(str(workspace), scopes=[scope], register=True)

    prefix = get_project_prefix(workspace)
    entry_id = next_entry_id(workspace, prefix)
    safe_scope = re.sub(r"[^A-Za-z0-9_\-]", "_", scope.strip())
    diary_path = diaries_dir / f"{safe_scope}.md"

    if diary_path.exists():
        header, entries = parse_diary_file(diary_path)
    else:
        cfg = get_workspace_config(workspace)
        pname = cfg.get("project_name") or workspace.name
        desc = SCOPE_DESCRIPTIONS.get(
            safe_scope,
            f"Descubrimientos técnicos verificados y trampas semánticas del ámbito `{safe_scope}`.",
        )
        header = f"# Diario Episódico — `{safe_scope}` ({pname})\n\n{desc}"
        entries = []

    new_entry = DiaryEntry(
        entry_id=entry_id,
        title=title.strip(),
        status=norm_status,
        date=entry_date or today_iso(),
        scope=safe_scope,
        environment=environment.strip(),
        occurrences=max(1, int(occurrences)),
        promoted_rule=promoted_rule.strip() or "Ninguna",
        symptom=symptom.strip(),
        semantic_trap=semantic_trap.strip(),
        root_cause=root_cause.strip(),
        deterministic_fix=deterministic_fix.strip(),
        provenance=provenance.strip(),
        file_path=str(diary_path),
    )
    entries.append(new_entry)
    diary_path.write_text(render_diary_file(header, entries), encoding="utf-8")
    sync_res = sync_index(workspace)

    return {
        "status": "CONSOLIDATED_WITH_PROVENANCE",
        "workspace": str(workspace),
        "entry_id": entry_id,
        "entry_status": norm_status,
        "scope": safe_scope,
        "file_path": str(diary_path),
        "provenance": new_entry.provenance,
        "sync": sync_res,
    }


def locate_entry(workspace: Path, entry_id: str) -> tuple[Path, str, list[DiaryEntry], int] | None:
    diaries_dir = workspace / "memoria" / "diarios"
    if not diaries_dir.exists():
        return None
    for p in sorted(diaries_dir.glob("*.md")):
        header, entries = parse_diary_file(p)
        for idx, e in enumerate(entries):
            if e.entry_id.upper() == entry_id.strip().upper():
                return p, header, entries, idx
    return None


def next_invariant_id(rules_dir: Path, prefix: str) -> str:
    max_num = 0
    pattern = re.compile(rf"\[{re.escape(prefix)}-INV-(\d+)\]")
    if rules_dir.exists():
        for p in rules_dir.glob("*.md"):
            content = p.read_text(encoding="utf-8", errors="replace")
            for m in pattern.finditer(content):
                max_num = max(max_num, int(m.group(1)))
    return f"{prefix}-INV-{max_num + 1:02d}"


def lifecycle_action(
    workspace_arg: str,
    action: str,
    entry_id: str,
    target_rule_file: str | None = None,
    rule_title: str | None = None,
    new_entry_id: str | None = None,
    provenance_note: str | None = None,
) -> dict[str, Any]:
    workspace = resolve_workspace(workspace_arg)
    found = locate_entry(workspace, entry_id)
    if not found:
        return {
            "status": "ENTRY_NOT_FOUND",
            "workspace": str(workspace),
            "entry_id": entry_id,
        }

    diary_path, header, entries, idx = found
    entry = entries[idx]
    act = action.strip().lower()

    if act == "verify":
        if entry.status.upper().startswith("SUPERSEDED_BY"):
            return {
                "status": "REJECTED_SUPERSEDED",
                "entry_id": entry.entry_id,
                "reason": f"La entrada ya está marcada como {entry.status}.",
            }
        entry.status = "VERIFIED"
        if provenance_note and provenance_note.strip():
            entry.provenance = f"{entry.provenance} | Verificado ({today_iso()}): {provenance_note.strip()}"
        diary_path.write_text(render_diary_file(header, entries), encoding="utf-8")
        sync_index(workspace)
        return {
            "status": "ENTRY_VERIFIED",
            "workspace": str(workspace),
            "entry_id": entry.entry_id,
            "entry_status": entry.status,
            "occurrences": entry.occurrences,
        }

    if act == "recurrence":
        entry.occurrences += 1
        if provenance_note and provenance_note.strip():
            entry.provenance = f"{entry.provenance} | Recurrencia #{entry.occurrences} ({today_iso()}): {provenance_note.strip()}"
        diary_path.write_text(render_diary_file(header, entries), encoding="utf-8")
        sync_index(workspace)
        ready = (
            entry.status.upper() == "VERIFIED"
            and entry.occurrences >= 2
            and entry.promoted_rule in ("", "Ninguna")
        )
        return {
            "status": "RECURRENCE_RECORDED",
            "workspace": str(workspace),
            "entry_id": entry.entry_id,
            "entry_status": entry.status,
            "occurrences": entry.occurrences,
            "ready_for_promotion": ready,
        }

    if act == "promote":
        if entry.status.upper() != "VERIFIED":
            return {
                "status": "REJECTED_PROMOTION",
                "entry_id": entry.entry_id,
                "reason": f"Solo se pueden promover entradas VERIFIED (estado actual: {entry.status}).",
            }
        if entry.occurrences < 2:
            return {
                "status": "REJECTED_PROMOTION",
                "entry_id": entry.entry_id,
                "reason": f"Se requiere Ocurrencias >= 2 para ascenso a regla L1 (actual: {entry.occurrences}).",
            }

        rules_dir = workspace / ".agents" / "rules"
        rules_dir.mkdir(parents=True, exist_ok=True)
        fname = (target_rule_file or f"{entry.scope.replace('_', '-')}.md").strip()
        if not fname.endswith(".md"):
            fname += ".md"
        fname = Path(fname).name
        rule_path = rules_dir / fname

        prefix = entry.entry_id.split("-EP-")[0] if "-EP-" in entry.entry_id else get_project_prefix(workspace)
        inv_id = next_invariant_id(rules_dir, prefix)
        sec_title = (rule_title or entry.title).strip()

        if rule_path.exists():
            existing_rule_text = rule_path.read_text(encoding="utf-8", errors="replace")
            if entry.entry_id in existing_rule_text:
                return {
                    "status": "ALREADY_PROMOTED",
                    "entry_id": entry.entry_id,
                    "rule_file": str(rule_path),
                }
            addition = (
                f"\n## [{inv_id}] {sec_title} (desde `{entry.entry_id}`)\n"
                f"- **Solución Determinista:** {entry.deterministic_fix}\n"
                f"- **Trampa a Evitar:** {entry.semantic_trap}\n"
                f"- **Evidencia:** {entry.provenance}\n"
            )
            new_rule_text = existing_rule_text.rstrip() + "\n" + addition
        else:
            desc = (
                f"Invariantes promovidas del ámbito {entry.scope} "
                f"(cargadas bajo demanda cuando aplica este subdominio)."
            )
            new_rule_text = (
                "---\n"
                "trigger: model_decision\n"
                f'description: "{desc}"\n'
                "---\n\n"
                f"# Reglas Promovidas — `{entry.scope}`\n\n"
                f"## [{inv_id}] {sec_title} (desde `{entry.entry_id}`)\n"
                f"- **Solución Determinista:** {entry.deterministic_fix}\n"
                f"- **Trampa a Evitar:** {entry.semantic_trap}\n"
                f"- **Evidencia:** {entry.provenance}\n"
            )

        byte_len = measure_rule_file(rule_path, raw_text=new_rule_text)["effective_bytes"]
        if byte_len > SAFE_PROMOTE_LIMIT_BYTES:
            return {
                "status": "REJECTED_RULE_BUDGET_EXCEEDED",
                "entry_id": entry.entry_id,
                "rule_file": str(rule_path),
                "resulting_bytes": byte_len,
                "safe_limit_bytes": SAFE_PROMOTE_LIMIT_BYTES,
                "reason": "El archivo de regla superaría 18.000 bytes; divide en un archivo nuevo en .agents/rules/.",
            }

        rule_path.write_text(new_rule_text, encoding="utf-8")
        entry.promoted_rule = f".agents/rules/{fname} ({inv_id})"
        diary_path.write_text(render_diary_file(header, entries), encoding="utf-8")
        sync_index(workspace)

        return {
            "status": "PROMOTED_TO_PROCEDURAL_RULE",
            "workspace": str(workspace),
            "entry_id": entry.entry_id,
            "invariant_id": inv_id,
            "rule_file": str(rule_path),
            "rule_bytes": byte_len,
        }

    if act == "supersede":
        if not new_entry_id or not new_entry_id.strip():
            return {
                "status": "REJECTED_SUPERSEDE",
                "entry_id": entry.entry_id,
                "reason": "Se requiere new_entry_id para marcar SUPERSEDED_BY.",
            }
        entry.status = f"SUPERSEDED_BY: {new_entry_id.strip()}"
        if provenance_note and provenance_note.strip():
            entry.provenance = f"{entry.provenance} | Sustituida ({today_iso()}): {provenance_note.strip()}"
        diary_path.write_text(render_diary_file(header, entries), encoding="utf-8")
        sync_index(workspace)
        return {
            "status": "ENTRY_SUPERSEDED",
            "workspace": str(workspace),
            "entry_id": entry.entry_id,
            "entry_status": entry.status,
        }

    return {
        "status": "UNKNOWN_ACTION",
        "action": action,
        "supported": ["verify", "recurrence", "promote", "supersede"],
    }


def audit_single_workspace(
    workspace: Path,
    gemini_home: Path | None = None,
) -> dict[str, Any]:
    rule_files_report: list[dict[str, Any]] = []
    candidates = collect_workspace_rule_files(workspace)

    worst_status = "OK"
    for p in candidates:
        rel_label = str(p.relative_to(workspace)).replace("\\", "/")
        metrics = measure_rule_file(p, rel_label=rel_label)
        if SEVERITY_ORDER[metrics["status"]] > SEVERITY_ORDER[worst_status]:
            worst_status = metrics["status"]
        rule_files_report.append(metrics)

    ws_always_on_tokens = sum(
        r["tokens_est"] for r in rule_files_report if r["trigger"] == "always_on"
    )
    global_rep = audit_global_rules(gemini_home)
    total_always_on = ws_always_on_tokens + global_rep["always_on_tokens_est"]
    agg_status = classify_aggregate_tokens(total_always_on)

    if SEVERITY_ORDER[global_rep["status"]] > SEVERITY_ORDER[worst_status]:
        worst_status = global_rep["status"]
    if SEVERITY_ORDER[agg_status] > SEVERITY_ORDER[worst_status]:
        worst_status = agg_status

    index_path = workspace / "memoria" / "MEMORIA_INDICE.md"
    diaries_dir = workspace / "memoria" / "diarios"
    diary_files = sorted(diaries_dir.glob("*.md")) if diaries_dir.exists() else []
    entries = load_all_entries(workspace)

    index_tokens = estimate_tokens(index_path.read_text(encoding="utf-8", errors="replace")) if index_path.exists() else 0
    diaries_tokens = sum(
        estimate_tokens(p.read_text(encoding="utf-8", errors="replace")) for p in diary_files
    )
    saved_tokens = max(0, diaries_tokens - index_tokens)
    savings_pct = round((saved_tokens / diaries_tokens) * 100.0, 1) if diaries_tokens > 0 else 0.0

    verified_ids = [e.entry_id for e in entries if e.status.upper() == "VERIFIED"]
    provisional_ids = [e.entry_id for e in entries if e.status.upper() == "PROVISIONAL"]
    superseded_ids = [e.entry_id for e in entries if e.status.upper().startswith("SUPERSEDED_BY")]
    promotion_candidates = [
        e.entry_id
        for e in entries
        if e.status.upper() == "VERIFIED"
        and e.occurrences >= 2
        and e.promoted_rule in ("", "Ninguna")
    ]

    latest_sorted = sorted(entries, key=entry_chrono_key)[-3:]

    return {
        "workspace": str(workspace),
        "initialized": index_path.exists(),
        "rules_budget_status": worst_status,
        "rule_files": rule_files_report,
        "aggregate_always_on_budget": {
            "workspace_always_on_tokens_est": ws_always_on_tokens,
            "global_always_on_tokens_est": global_rep["always_on_tokens_est"],
            "total_always_on_tokens_est": total_always_on,
            "limit_tokens": AGGREGATE_TOKEN_LIMIT,
            "usage_pct": round((total_always_on / AGGREGATE_TOKEN_LIMIT) * 100.0, 1),
            "status": agg_status,
            "global_rules_status": global_rep["status"],
            "global_rule_files": global_rep["rule_files"],
        },
        "scoped_routing_metrics": {
            "index_tokens_est": index_tokens,
            "full_diaries_tokens_est": diaries_tokens,
            "fixed_overhead_saved_tokens": saved_tokens,
            "fixed_overhead_savings_pct": savings_pct,
        },
        "entries_summary": {
            "total": len(entries),
            "verified": len(verified_ids),
            "provisional": len(provisional_ids),
            "superseded": len(superseded_ids),
            "provisional_ids": provisional_ids,
            "promotion_candidates": promotion_candidates,
            "scopes": [p.stem for p in diary_files],
            "latest_entries": [
                {"entry_id": e.entry_id, "status": e.status, "title": e.title}
                for e in latest_sorted
            ],
        },
    }


def audit_workspace(
    workspace_arg: str | None = None,
    gemini_home: Path | None = None,
) -> dict[str, Any]:
    if workspace_arg:
        ws = resolve_workspace(workspace_arg)
        return audit_single_workspace(ws, gemini_home=gemini_home)

    registry = load_registry()
    reports: dict[str, Any] = {}
    for alias, info in registry.get("workspaces", {}).items():
        ws = Path(info["path"])
        if ws.exists():
            reports[alias] = audit_single_workspace(ws, gemini_home=gemini_home)
        else:
            reports[alias] = {"workspace": str(ws), "error": "Ruta no encontrada"}
    return {
        "registered_workspaces": len(reports),
        "global_rules": audit_global_rules(gemini_home),
        "reports": reports,
    }


def get_baseline_store_path(workspace: Path) -> Path:
    cache_dir = workspace / "memoria" / ".cache"
    if cache_dir.exists():
        return cache_dir / "rule_budget_baselines.json"
    return Path(tempfile.gettempdir()) / "agy_persistent_memory_baselines.json"


def build_budget_snapshot(audit_rep: dict[str, Any]) -> dict[str, int]:
    agg = audit_rep.get("aggregate_always_on_budget", {})
    snapshot: dict[str, int] = {}
    for rf in audit_rep.get("rule_files", []) + agg.get("global_rule_files", []):
        snapshot[str(rf["path"])] = int(rf["effective_bytes"])
    snapshot["__aggregate_always_on_tokens__"] = int(agg.get("total_always_on_tokens_est", 0))
    return snapshot


def _baseline_key(workspace: Path, conversation_id: str) -> str:
    cid = (conversation_id or "default").strip() or "default"
    return f"{workspace.resolve()}::{cid}"


def save_session_baseline(workspace: Path, conversation_id: str, snapshot: dict[str, int]) -> None:
    store_path = get_baseline_store_path(workspace)
    store_path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {"sessions": {}}
    if store_path.exists():
        try:
            loaded = json.loads(store_path.read_text(encoding="utf-8", errors="replace"))
            if isinstance(loaded, dict) and isinstance(loaded.get("sessions"), dict):
                data = loaded
        except Exception:
            data = {"sessions": {}}
    sessions = data.setdefault("sessions", {})
    key = _baseline_key(workspace, conversation_id)
    if key in sessions:
        del sessions[key]
    sessions[key] = {
        "updated_at": time.time(),
        "snapshot": snapshot,
    }
    while len(sessions) > 25:
        oldest_key = next(iter(sessions))
        del sessions[oldest_key]
    store_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_session_baseline(workspace: Path, conversation_id: str) -> dict[str, int] | None:
    key = _baseline_key(workspace, conversation_id)
    candidates = [get_baseline_store_path(workspace)]
    fallback = Path(tempfile.gettempdir()) / "agy_persistent_memory_baselines.json"
    if fallback not in candidates:
        candidates.append(fallback)
    for store_path in candidates:
        if not store_path.exists():
            continue
        try:
            loaded = json.loads(store_path.read_text(encoding="utf-8", errors="replace"))
            sessions = loaded.get("sessions", {}) if isinstance(loaded, dict) else {}
            entry = sessions.get(key)
            if isinstance(entry, dict) and isinstance(entry.get("snapshot"), dict):
                return {str(k): int(v) for k, v in entry["snapshot"].items()}
        except Exception:
            continue
    return None


def is_ignored_hook_path(path: Path) -> bool:
    if not path.exists():
        return True
    if path.parent == path:
        return True
    parts_low = [part.lower() for part in path.parts]
    parts_set = set(parts_low)
    if parts_set & {".gemini", "windows", "program files", "program files (x86)", "system32"}:
        return True
    if "appdata" in parts_set:
        # Ignora carpetas internas de configuración en AppData, salvo pruebas en AppData/Local/Temp
        if not ("local" in parts_set and "temp" in parts_set):
            return True
    return False


def handle_session_start(stdin_text: str, gemini_home: Path | None = None) -> dict[str, Any]:
    try:
        payload = json.loads(stdin_text) if stdin_text.strip() else {}
        if not isinstance(payload, dict):
            return {}
        ws_list = payload.get("workspacePaths") or []
        raw_ws = ws_list[0] if isinstance(ws_list, list) and ws_list else payload.get("cwd", "")
        if not raw_ws:
            return {}
        workspace = Path(str(raw_ws)).expanduser().resolve()
        if is_ignored_hook_path(workspace):
            return {}

        conv_id = str(payload.get("conversationId") or "default")
        audit = audit_single_workspace(workspace, gemini_home=gemini_home)
        save_session_baseline(workspace, conv_id, build_budget_snapshot(audit))

        index_path = workspace / "memoria" / "MEMORIA_INDICE.md"
        if not index_path.exists():
            msg = (
                "[Memoria Persistente — Nuevo Proyecto Detectado] Este espacio de trabajo aún no tiene "
                "inicializada su memoria persistente en disco. Al abordar la primera tarea técnica en este "
                "proyecto, ejecuta primero la herramienta MCP `memory_init` (o `memctl.py init`) adaptando "
                "los ámbitos al stack del proyecto para garantizar memoria persistente desde el primer día."
            )
            return {"injectSteps": [{"systemMessage": {"systemMessage": msg}}]}

        ensure_fts_fresh(workspace)
        agents_info = next(
            (r for r in audit["rule_files"] if r["file"] == "AGENTS.md"),
            None,
        )
        agents_str = (
            f"AGENTS.md={agents_info['effective_bytes']}/24000 B ({agents_info['status']})"
            if agents_info
            else "AGENTS.md=no encontrado"
        )
        l1_rules = [r for r in audit["rule_files"] if r["file"].startswith(".agents/rules/")]
        worst_l1_status = "OK"
        for r in l1_rules:
            if SEVERITY_ORDER[r["status"]] > SEVERITY_ORDER[worst_l1_status]:
                worst_l1_status = r["status"]
        l1_str = f"Reglas L1={len(l1_rules)} ({worst_l1_status})"

        agg = audit["aggregate_always_on_budget"]
        agg_str = f"Always-On={agg['total_always_on_tokens_est']}/{agg['limit_tokens']} tok ({agg['status']})"

        summary = audit["entries_summary"]
        scopes_str = ", ".join(summary["scopes"]) or "ninguno"
        latest_str = "; ".join(
            f"{item['entry_id']} ({item['status']}): {item['title'][:55]}"
            for item in summary["latest_entries"]
        )
        extras: list[str] = []
        if audit["rules_budget_status"] != "OK":
            flagged: list[str] = []
            for rf in audit["rule_files"] + agg["global_rule_files"]:
                if rf["status"] != "OK":
                    flagged.append(f"{rf['file']}={rf['effective_bytes']} B ({rf['status']})")
            if agg["status"] != "OK":
                flagged.append(agg_str)
            if flagged:
                extras.append(f"ALERTA PRESUPUESTO: {', '.join(flagged)}")
        if summary["provisional_ids"]:
            extras.append(f"Pendientes de confirmar (PROVISIONAL): {', '.join(summary['provisional_ids'])}")
        if summary["promotion_candidates"]:
            extras.append(f"Listas para ascenso N>=2: {', '.join(summary['promotion_candidates'])}")

        msg = (
            f"[Memoria Persistente Activa — {workspace.name}] {agents_str} | {l1_str} | {agg_str} | "
            f"Ámbitos: {scopes_str} | Entradas: {summary['verified']} VERIFIED, {summary['provisional']} PROVISIONAL. "
            f"Recientes: {latest_str or 'ninguna'}. "
            + (" | ".join(extras) + ". " if extras else "")
            + "Usa `memory_search` antes de depurar fallos no triviales y `memory_record` al consolidar soluciones verificadas."
        )
        return {"injectSteps": [{"systemMessage": {"systemMessage": msg}}]}
    except Exception:
        return {}


def handle_stop(stdin_text: str, gemini_home: Path | None = None) -> dict[str, Any]:
    try:
        payload = json.loads(stdin_text) if stdin_text.strip() else {}
        if not isinstance(payload, dict):
            return {"decision": "stop"}
        if bool(payload.get("continuationActive", False)):
            return {"decision": "stop"}
        if payload.get("terminationReason", "NO_TOOL_CALL") != "NO_TOOL_CALL":
            return {"decision": "stop"}

        ws_list = payload.get("workspacePaths") or []
        raw_ws = ws_list[0] if isinstance(ws_list, list) and ws_list else payload.get("cwd", "")
        if not raw_ws:
            return {"decision": "stop"}
        workspace = Path(str(raw_ws)).expanduser().resolve()
        if is_ignored_hook_path(workspace):
            return {"decision": "stop"}

        conv_id = str(payload.get("conversationId") or "default")
        audit = audit_single_workspace(workspace, gemini_home=gemini_home)
        baseline = load_session_baseline(workspace, conv_id)
        agg = audit["aggregate_always_on_budget"]
        all_rule_files = audit["rule_files"] + agg["global_rule_files"]
        now_ts = time.time()

        def grew(key: str, current_val: int, file_path: Path | None = None) -> bool:
            if baseline is not None:
                return current_val > baseline.get(key, 0)
            if file_path is not None:
                try:
                    return file_path.exists() and file_path.stat().st_mtime >= now_ts - 180
                except Exception:
                    return False
            return False

        violations: list[str] = []
        for rf in all_rule_files:
            p = Path(rf["path"])
            eff = int(rf["effective_bytes"])
            name_up = p.name.upper()
            if name_up in ("AGENTS.MD", "GEMINI.MD"):
                if eff >= RULE_WARN_LIMIT_BYTES and grew(rf["path"], eff, p):
                    violations.append(f"{rf['file']}={eff} B (límite alerta {RULE_WARN_LIMIT_BYTES} B)")
            elif p.parent.name.lower() == "rules":
                if eff > SAFE_PROMOTE_LIMIT_BYTES and grew(rf["path"], eff, p):
                    violations.append(f"{rf['file']}={eff} B (límite modular {SAFE_PROMOTE_LIMIT_BYTES} B)")

        total_tok = int(agg["total_always_on_tokens_est"])
        if total_tok >= AGGREGATE_TOKEN_CRIT:
            if baseline is not None:
                agg_grew = total_tok > baseline.get("__aggregate_always_on_tokens__", 0)
            else:
                agg_grew = any(
                    Path(rf["path"]).exists() and Path(rf["path"]).stat().st_mtime >= now_ts - 180
                    for rf in all_rule_files
                    if rf["trigger"] == "always_on"
                )
            if agg_grew:
                violations.append(f"Always-On={total_tok}/{AGGREGATE_TOKEN_LIMIT} tokens")

        if violations:
            save_session_baseline(workspace, conv_id, build_budget_snapshot(audit))
            return {
                "decision": "continue",
                "reason": (
                    "[Memoria Persistente — Guardián de Límites L0/L1] Se ha superado el presupuesto seguro "
                    f"tras modificar reglas en este turno ({'; '.join(violations)}). Refactoriza ahora "
                    "extrayendo el detalle técnico a archivos modulares en `.agents/rules/<subdominio>.md` "
                    "con `trigger: model_decision` o a diarios en `memoria/diarios/`."
                ),
            }

        if baseline is not None:
            curr_snap = build_budget_snapshot(audit)
            if any(curr_snap.get(k, 0) < v for k, v in baseline.items()):
                save_session_baseline(workspace, conv_id, curr_snap)

        return {"decision": "stop"}
    except Exception:
        return {"decision": "stop"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CLI del sistema de memoria persistente (L0-L3).")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init")
    p_init.add_argument("--workspace", required=True)
    p_init.add_argument("--name")
    p_init.add_argument("--prefix")
    p_init.add_argument("--scopes")
    p_init.add_argument("--no-register", action="store_true")

    p_search = sub.add_parser("search")
    p_search.add_argument("--workspace", required=True)
    p_search.add_argument("--query", required=True)
    p_search.add_argument("--scope")
    p_search.add_argument("--limit", type=int, default=5)
    p_search.add_argument("--include-superseded", action="store_true")

    p_rec = sub.add_parser("record")
    p_rec.add_argument("--workspace", required=True)
    p_rec.add_argument("--scope", required=True)
    p_rec.add_argument("--title", required=True)
    p_rec.add_argument("--environment", required=True)
    p_rec.add_argument("--symptom", required=True)
    p_rec.add_argument("--semantic-trap", required=True)
    p_rec.add_argument("--root-cause", required=True)
    p_rec.add_argument("--deterministic-fix", required=True)
    p_rec.add_argument("--provenance", required=True)
    p_rec.add_argument("--status", default="PROVISIONAL", choices=["PROVISIONAL", "VERIFIED"])
    p_rec.add_argument("--exit-code", type=int, default=0)
    p_rec.add_argument("--log-errors", nargs="*", default=[])
    p_rec.add_argument("--date")
    p_rec.add_argument("--occurrences", type=int, default=1)
    p_rec.add_argument("--promoted-rule", default="Ninguna")

    p_ver = sub.add_parser("verify")
    p_ver.add_argument("--workspace", required=True)
    p_ver.add_argument("--entry-id", required=True)
    p_ver.add_argument("--provenance-note")

    p_recur = sub.add_parser("recurrence")
    p_recur.add_argument("--workspace", required=True)
    p_recur.add_argument("--entry-id", required=True)
    p_recur.add_argument("--provenance-note")

    p_prom = sub.add_parser("promote")
    p_prom.add_argument("--workspace", required=True)
    p_prom.add_argument("--entry-id", required=True)
    p_prom.add_argument("--target-rule-file")
    p_prom.add_argument("--rule-title")

    p_sup = sub.add_parser("supersede")
    p_sup.add_argument("--workspace", required=True)
    p_sup.add_argument("--entry-id", required=True)
    p_sup.add_argument("--new-entry-id", required=True)
    p_sup.add_argument("--provenance-note")

    p_reidx = sub.add_parser("reindex")
    p_reidx.add_argument("--workspace", required=True)

    p_aud = sub.add_parser("audit")
    p_aud.add_argument("--workspace")

    sub.add_parser("hook-session-start")
    sub.add_parser("hook-stop")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.cmd == "hook-session-start":
        stdin_text = sys.stdin.read() if not sys.stdin.isatty() else "{}"
        res = handle_session_start(stdin_text)
        print(json.dumps(res, ensure_ascii=False))
        return 0

    if args.cmd == "hook-stop":
        stdin_text = sys.stdin.read() if not sys.stdin.isatty() else "{}"
        res = handle_stop(stdin_text)
        print(json.dumps(res, ensure_ascii=False))
        return 0

    if args.cmd == "init":
        scopes = [s.strip() for s in args.scopes.split(",")] if args.scopes else None
        res = init_workspace(
            args.workspace,
            project_name=args.name,
            prefix=args.prefix,
            scopes=scopes,
            register=not args.no_register,
        )
    elif args.cmd == "search":
        res = search_memory(
            args.workspace,
            args.query,
            scope=args.scope,
            limit=args.limit,
            include_superseded=args.include_superseded,
        )
    elif args.cmd == "record":
        res = record_memory(
            workspace_arg=args.workspace,
            scope=args.scope,
            title=args.title,
            environment=args.environment,
            symptom=args.symptom,
            semantic_trap=args.semantic_trap,
            root_cause=args.root_cause,
            deterministic_fix=args.deterministic_fix,
            provenance=args.provenance,
            status=args.status,
            exit_code=args.exit_code,
            log_errors=args.log_errors,
            entry_date=args.date,
            occurrences=args.occurrences,
            promoted_rule=args.promoted_rule,
        )
    elif args.cmd == "verify":
        res = lifecycle_action(
            args.workspace, "verify", args.entry_id, provenance_note=args.provenance_note
        )
    elif args.cmd == "recurrence":
        res = lifecycle_action(
            args.workspace, "recurrence", args.entry_id, provenance_note=args.provenance_note
        )
    elif args.cmd == "promote":
        res = lifecycle_action(
            args.workspace,
            "promote",
            args.entry_id,
            target_rule_file=args.target_rule_file,
            rule_title=args.rule_title,
        )
    elif args.cmd == "supersede":
        res = lifecycle_action(
            args.workspace,
            "supersede",
            args.entry_id,
            new_entry_id=args.new_entry_id,
            provenance_note=args.provenance_note,
        )
    elif args.cmd == "reindex":
        ws = resolve_workspace(args.workspace)
        res = sync_index(ws)
    elif args.cmd == "audit":
        res = audit_workspace(args.workspace)
    else:
        res = {"error": f"Comando desconocido: {args.cmd}"}

    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
