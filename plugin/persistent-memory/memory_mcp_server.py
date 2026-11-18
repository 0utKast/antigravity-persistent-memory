#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Servidor MCP local Stdio para Memoria Persistente (`persistent_memory`).

Expone herramientas de inicialización, búsqueda BM25/FTS5 (local y federada
de solo lectura), consolidación con compuerta anti-envenenamiento, ciclo de vida
y auditoría del límite de 24.000 bytes sobre `AGENTS.md`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import memctl  # noqa: E402

TOOLS = [
    {
        "name": "memory_init",
        "description": (
            "Inicializa la memoria persistente Local-First (AGENTS.md L0, .agents/rules/ L1, "
            "memoria/MEMORIA_INDICE.md + diarios/ L2 y caché FTS5 L3) en un proyecto nuevo o existente."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace_path": {
                    "type": "string",
                    "description": "Ruta absoluta del área de trabajo a inicializar.",
                },
                "project_name": {
                    "type": "string",
                    "description": "Nombre legible del proyecto (opcional).",
                },
                "prefix": {
                    "type": "string",
                    "description": "Prefijo de IDs episódicos, ej. FO4, CP77, DC (opcional).",
                },
                "scopes": {
                    "oneOf": [
                        {"type": "string"},
                        {"type": "array", "items": {"type": "string"}},
                    ],
                    "description": "Ámbitos iniciales (lista o cadena separada por comas). Si se omite, se autodetectan.",
                },
            },
            "required": ["workspace_path"],
        },
    },
    {
        "name": "memory_search",
        "description": (
            "Busca episodios verificados mediante SQLite FTS5 + BM25 en el workspace indicado "
            "o usando un alias registrado (ej. 'DesarrolloCursos', 'Mods_Fallout', 'Mods_cyberpunk2077') "
            "para consulta federada de solo lectura."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace_path": {
                    "type": "string",
                    "description": "Ruta absoluta del workspace o alias registrado en workspaces_registry.json.",
                },
                "query": {
                    "type": "string",
                    "description": "Síntoma, código de error, símbolo o palabra clave a buscar.",
                },
                "scope": {
                    "type": "string",
                    "description": "Filtro opcional por ámbito exacto.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Máximo de resultados (por defecto 5).",
                    "default": 5,
                },
                "include_superseded": {
                    "type": "boolean",
                    "description": "Incluir entradas sustituidas (SUPERSEDED_BY).",
                    "default": False,
                },
            },
            "required": ["workspace_path", "query"],
        },
    },
    {
        "name": "memory_record",
        "description": (
            "Consolida un hallazgo técnico en memoria/diarios/<scope>.md pasando la compuerta "
            "anti-envenenamiento (exige exit_code == 0, 0 log_errors, semantic_trap, root_cause, "
            "deterministic_fix y provenance). Reconstruye MEMORIA_INDICE.md e índice FTS5."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace_path": {"type": "string"},
                "scope": {"type": "string"},
                "title": {"type": "string"},
                "environment": {"type": "string"},
                "symptom": {"type": "string"},
                "semantic_trap": {"type": "string"},
                "root_cause": {"type": "string"},
                "deterministic_fix": {"type": "string"},
                "provenance": {"type": "string"},
                "status": {
                    "type": "string",
                    "enum": ["PROVISIONAL", "VERIFIED"],
                    "default": "PROVISIONAL",
                },
                "exit_code": {"type": "integer", "default": 0},
                "log_errors": {
                    "type": "array",
                    "items": {"type": "string"},
                    "default": [],
                },
            },
            "required": [
                "workspace_path",
                "scope",
                "title",
                "environment",
                "symptom",
                "semantic_trap",
                "root_cause",
                "deterministic_fix",
                "provenance",
            ],
        },
    },
    {
        "name": "memory_lifecycle",
        "description": (
            "Gestiona el ciclo de vida de una entrada episódica: 'verify' (PROVISIONAL -> VERIFIED), "
            "'recurrence' (incrementa N), 'promote' (asciende entrada VERIFIED con N >= 2 a .agents/rules/) "
            "o 'supersede' (marca SUPERSEDED_BY)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace_path": {"type": "string"},
                "action": {
                    "type": "string",
                    "enum": ["verify", "recurrence", "promote", "supersede"],
                },
                "entry_id": {"type": "string"},
                "target_rule_file": {"type": "string"},
                "rule_title": {"type": "string"},
                "new_entry_id": {"type": "string"},
                "provenance_note": {"type": "string"},
            },
            "required": ["workspace_path", "action", "entry_id"],
        },
    },
    {
        "name": "memory_audit",
        "description": (
            "Audita el presupuesto de bytes de AGENTS.md, GEMINI.md y .agents/rules/*.md (expandiendo "
            "includes @[label](ruta)) frente al límite duro de 24.000 bytes, las reglas globales y el "
            "presupuesto agregado Always-On de 20.000 tokens, además del ahorro de MEMORIA_INDICE.md. "
            "Si se omite workspace_path, audita todos los workspaces registrados."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace_path": {
                    "type": "string",
                    "description": "Ruta o alias opcional; omitir para auditar todos los proyectos registrados.",
                }
            },
        },
    },
]


class PersistentMemoryMCPServer:
    def __init__(self) -> None:
        self.protocol_version = "2024-11-05"

    def _call_tool(self, name: str, args: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        if name == "memory_init":
            raw_scopes = args.get("scopes")
            scopes_list: list[str] | None = None
            if isinstance(raw_scopes, str) and raw_scopes.strip():
                scopes_list = [s.strip() for s in raw_scopes.split(",") if s.strip()]
            elif isinstance(raw_scopes, list):
                scopes_list = [str(s).strip() for s in raw_scopes if str(s).strip()]
            res = memctl.init_workspace(
                workspace_arg=str(args["workspace_path"]),
                project_name=args.get("project_name"),
                prefix=args.get("prefix"),
                scopes=scopes_list,
            )
            return res, False

        if name == "memory_search":
            res = memctl.search_memory(
                workspace_arg=str(args["workspace_path"]),
                query=str(args["query"]),
                scope=args.get("scope"),
                limit=int(args.get("limit", 5)),
                include_superseded=bool(args.get("include_superseded", False)),
            )
            return res, False

        if name == "memory_record":
            res = memctl.record_memory(
                workspace_arg=str(args["workspace_path"]),
                scope=str(args["scope"]),
                title=str(args["title"]),
                environment=str(args["environment"]),
                symptom=str(args["symptom"]),
                semantic_trap=str(args["semantic_trap"]),
                root_cause=str(args["root_cause"]),
                deterministic_fix=str(args["deterministic_fix"]),
                provenance=str(args["provenance"]),
                status=str(args.get("status", "PROVISIONAL")),
                exit_code=int(args.get("exit_code", 0)),
                log_errors=args.get("log_errors") or [],
            )
            return res, res.get("status") == "REJECTED_MEMORY_POISONING"

        if name == "memory_lifecycle":
            res = memctl.lifecycle_action(
                workspace_arg=str(args["workspace_path"]),
                action=str(args["action"]),
                entry_id=str(args["entry_id"]),
                target_rule_file=args.get("target_rule_file"),
                rule_title=args.get("rule_title"),
                new_entry_id=args.get("new_entry_id"),
                provenance_note=args.get("provenance_note"),
            )
            is_err = str(res.get("status", "")).startswith("REJECTED") or res.get("status") in (
                "ENTRY_NOT_FOUND",
                "UNKNOWN_ACTION",
            )
            return res, is_err

        if name == "memory_audit":
            res = memctl.audit_workspace(args.get("workspace_path"))
            return res, False

        return {"error": f"Herramienta desconocida: {name}"}, True

    def handle_message(self, msg: dict[str, Any]) -> dict[str, Any] | None:
        method = msg.get("method", "")
        req_id = msg.get("id")
        if req_id is None:
            return None

        if method == "initialize":
            params = msg.get("params") or {}
            if isinstance(params, dict) and params.get("protocolVersion"):
                self.protocol_version = str(params["protocolVersion"])
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": self.protocol_version,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "persistent_memory", "version": "1.0.0"},
                },
            }

        if method == "ping":
            return {"jsonrpc": "2.0", "id": req_id, "result": {}}

        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}}

        if method == "resources/list":
            return {"jsonrpc": "2.0", "id": req_id, "result": {"resources": []}}

        if method == "resources/templates/list":
            return {"jsonrpc": "2.0", "id": req_id, "result": {"resourceTemplates": []}}

        if method == "prompts/list":
            return {"jsonrpc": "2.0", "id": req_id, "result": {"prompts": []}}

        if method == "tools/call":
            params = msg.get("params") or {}
            tool_name = str(params.get("name", ""))
            tool_args = params.get("arguments") or {}
            try:
                result_obj, is_err = self._call_tool(tool_name, tool_args)
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(result_obj, ensure_ascii=False, indent=2),
                            }
                        ],
                        "isError": is_err,
                    },
                }
            except Exception as exc:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": json.dumps({"error": str(exc)})}],
                        "isError": True,
                    },
                }

        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }


def write_stdout_message(msg: dict[str, Any]) -> None:
    out = json.dumps(msg, ensure_ascii=False) + "\n"
    sys.stdout.buffer.write(out.encode("utf-8"))
    sys.stdout.buffer.flush()


def main() -> None:
    server = PersistentMemoryMCPServer()
    while True:
        raw_line = sys.stdin.buffer.readline()
        if not raw_line:
            break
        line_str = raw_line.decode("utf-8", errors="replace").strip()
        if not line_str:
            continue
        try:
            msg = json.loads(line_str)
        except json.JSONDecodeError:
            continue
        if not isinstance(msg, dict):
            continue
        resp = server.handle_message(msg)
        if resp is not None:
            write_stdout_message(resp)


if __name__ == "__main__":
    main()
