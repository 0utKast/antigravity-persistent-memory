---
name: memory-steward
description: >-
  Use this skill when starting work in a new workspace without persistent memory,
  investigating non-trivial bugs or engine quirks, recording verified technical
  lessons with provenance, promoting recurring rules (N >= 2) to .agents/rules/,
  or auditing AGENTS.md against the 24,000-byte truncation limit.
---

# Memory Steward — Protocolo de Memoria Persistente (L0–L3)

Este flujo coordina el uso diario del servidor MCP `persistent_memory` y del CLI `memctl.py` para que cada proyecto acumule experiencia real verificada sin saturar la ventana de contexto ni alcanzar el límite de `24.000 bytes` de `AGENTS.md`.

## Cuándo Activar Cada Herramienta

1. **Al iniciar en un proyecto nuevo sin `memoria/MEMORIA_INDICE.md`:**
   - Llama a `memory_init(workspace_path="<ruta>", project_name="<nombre>", prefix="<PREFIJO>")`.
   - Opcionalmente especifica `scopes` separados por comas si el proyecto requiere ámbitos propios.
2. **Antes de investigar un fallo sutil o tocar subsistemas críticos:**
   - Llama a `memory_search(workspace_path="<ruta_o_alias>", query="<síntoma, error o subsistema>")`.
   - Si estás en `DesarrolloCursos` documentando casos reales, puedes consultar en **solo lectura** otros proyectos registrados (`workspace_path="Mods_Fallout"` o `"Mods_cyberpunk2077"`).
3. **Al resolver un incidente técnico real (con compilador/test/auditor en 0 errores):**
   - Llama a `memory_record(...)` rellenando obligatoriamente `semantic_trap` (qué hipótesis parecía lógica pero falló), `root_cause`, `deterministic_fix` y `provenance`.
   - Si solo superó compilación/tests estáticos pero falta prueba en vivo (ej. dentro del videojuego o Camtasia), usa `status="PROVISIONAL"`. Cuando el usuario o la ejecución real lo confirme, llama a `memory_lifecycle(action="verify", entry_id="...")`.
4. **Cuando un mismo patrón reaparece o madura ($N \ge 2$):**
   - Llama a `memory_lifecycle(action="recurrence", entry_id="...")`.
   - Si la entrada ya está en `VERIFIED` y `Ocurrencias >= 2`, promuévela a L1 con `memory_lifecycle(action="promote", entry_id="...", target_rule_file="<subdominio>.md")`.
   - Si un parche del motor deja obsoleto un hallazgo previo, regístralo en una entrada nueva y marca la antigua con `memory_lifecycle(action="supersede", entry_id="<VIEJO>", new_entry_id="<NUEVO>")`.
5. **Auditoría de presupuesto y salud:**
   - Llama a `memory_audit(workspace_path="<ruta>")` para verificar que `AGENTS.md`, `GEMINI.md`, `.agents/rules/*.md` (expandiendo includes `@[label](ruta)`) y las reglas globales estén en estado `OK` (`< 12.000 bytes`, lejos del tope duro de `24.000 bytes`) y dentro del presupuesto conjunto `Always-On` (`< 20.000 tokens`). Los hooks automáticos `SessionStart` y `Stop` vigilan el crecimiento en vivo en cada sesión.
