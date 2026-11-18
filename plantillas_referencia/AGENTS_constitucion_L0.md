# Constitución Operativa del Proyecto (`AGENTS.md` — Capa L0)

> Archivo de carga incondicional (*Always-On*). Mantener siempre compacto (`< 12.000 bytes`, alerta en `>= 16.000 bytes`, tope duro de truncamiento en `24.000 bytes` y presupuesto conjunto `Always-On < 20.000 tokens`).

## Protocolo de Memoria Persistente en 4 Capas (L0–L3)
1. **Consulta previa obligatoria (`Scoped Access`):** Antes de modificar código o depurar un subsistema no trivial, ejecuta `memory_search` sobre el espacio de trabajo actual (o consulta en solo lectura proyectos hermanos registrados) o abre **únicamente** el diario del ámbito exacto desde [`memoria/MEMORIA_INDICE.md`](memoria/MEMORIA_INDICE.md).
2. **Compuerta Anti-Envenenamiento (`PROVISIONAL` -> `VERIFIED`):** Ninguna hipótesis o parche no probado entra en los diarios. Solo se consolidan hallazgos con `exit_code == 0`, logs limpios (`0` errores) y los campos obligatorios: **Trampa Semántica** (hipótesis descartadas), **Causa Raíz**, **Solución Determinista** y **Evidencia de Verificación (Provenance)**. Usar `PROVISIONAL` hasta confirmar en ejecución real en vivo.
3. **Ascenso modular ($N \ge 2$ hacia Capa L1):** Cuando una lección `VERIFIED` reaparezca dos o más veces (`Ocurrencias >= 2`), promuévela mediante `memory_lifecycle(action="promote")` a un archivo condicional en `.agents/rules/<subdominio>.md` con `trigger: model_decision` (`<= 18.000 bytes`), nunca engordando este `AGENTS.md`.
4. **Higiene de presupuesto:** Si necesitas anexar documentación extensa, sepárala en archivos fuera de la carga incondicional o en diarios por ámbito; no uses `@[label](ruta)` hacia anexos gigantes dentro de reglas siempre activas.
