# Protocolo Global de Memoria Persistente en 4 Capas (L0–L3)

Todo espacio de trabajo operado por Antigravity mantiene su propia memoria técnica soberana (*Local-First* y portable en Markdown bajo Git) conectada mediante el motor global `persistent-memory` (`persistent_memory` MCP).

## 1. Arquitectura Obligatoria por Capas
1. **Capa L0 (`AGENTS.md`, tope saludable `< 12.000 bytes`, alerta `>= 16.000 bytes`, límite duro `24.000 bytes`; presupuesto conjunto `Always-On < 20.000 tokens`):** Solo leyes universales del proyecto y enlace a `memoria/MEMORIA_INDICE.md`. Nunca acumular diarios ni tablas extensas aquí para evitar el truncamiento silencioso o degradación del presupuesto global.
2. **Capa L1 (`.agents/rules/*.md` con `trigger: model_decision` y `.agents/skills/`):** Reglas modulares por subdominio que consumen ~30 tokens en reposo y se cargan únicamente cuando aplican.
3. **Capa L2 (`memoria/MEMORIA_INDICE.md` y `memoria/diarios/<ambito>.md`):** Única Fuente de Verdad legible por humanos y versionable en Git (*Escape Hatch Principle*).
4. **Capa L3 (`memoria/.cache/memoria_fts.sqlite`):** Índice efímero `SQLite FTS5` + `BM25` consultado vía `memory_search`.

## 2. Garantía en Proyectos Nuevos y Flujo Operativo
- **Todo proyecto nuevo debe inicializarse desde su primera tarea técnica:** Si el proyecto activo carece de `memoria/MEMORIA_INDICE.md`, ejecuta primero `memory_init(workspace_path=...)` adaptando los ámbitos al stack detectado.
- **Antes de depurar o modificar subsistemas no triviales:** Consulta `memory_search` en el workspace actual (o lee solo el ámbito relevante vía `memoria/MEMORIA_INDICE.md`).
- **Compuerta Anti-Envenenamiento (`PROVISIONAL` -> `VERIFIED`):** Tras resolver un fallo técnico no trivial con código/compilación/test en verde (`exit_code == 0`), regístralo con `memory_record` incluyendo obligatoriamente la **Trampa Semántica** (hipótesis descartadas) y la **Evidencia de Verificación (Provenance)**. Usa `PROVISIONAL` hasta confirmar en ejecución real en vivo (`memory_lifecycle(action="verify")`).
- **Ascenso Progresivo ($N \ge 2$):** Cuando una entrada `VERIFIED` alcance `Ocurrencias >= 2`, promuévela a regla L1 modular con `memory_lifecycle(action="promote")` sin inflar `AGENTS.md`.
