---
trigger: model_decision
description: "Reglas e invariantes verificadas sobre binarios .esp/.esl/.ba2 y compilación Papyrus en Creation Engine (cargada bajo demanda cuando aplica este subdominio)."
---

# Reglas Modulares Promovidas — `binarios_ba2_y_compilador` (Capa L1)

> Este archivo solo consume ~30 tokens (nombre + descripción) en reposo. El agente lo carga íntegramente únicamente cuando trabaja con plugins binarios o scripts Papyrus.

## [FO4-INV-01] Máscara local de 12 bits en Light Plugins `.esl` (desde `FO4-EP-008`)
- **Solución Determinista:** Usar estrictamente la máscara de 12 bits (`0x00000FFF`, tres dígitos hexadecimales bajos) al invocar `Game.GetFormFromFile(aiFormID, "MiMod.esl")`.
- **Trampa a Evitar:** Copiar los 6 dígitos hexadecimales bajos mostrados en `FO4Edit` (`0x00FFFFFF`); en plugins `.esl` (`0xFE`), los 12 bits intermedios pertenecen al índice dinámico del gestor de carga y producen `None` silencioso en tiempo de ejecución.
- **Evidencia:** Verificado en compilaciones duales ES/EN y pruebas en partida limpia (`coc SanctuaryExt`) con `Papyrus.0.log` en 0 errores.

## [FO4-INV-02] Compatibilidad binaria `HEDR v1.0` y `.ba2 v1` (desde `FO4-EP-008`)
- **Solución Determinista:** Mantener cabecera `.esp` en `HEDR v1.0`, FormIDs propios `>= 0x800` y empaquetado de archivos `.ba2` (`GNRL` y `DX10`) en versión `v1` para garantizar compatibilidad simultánea en *Fallout 4* `1.10.163` y `1.10.984+` (Next-Gen).
- **Trampa a Evitar:** Empaquetar `.ba2` en `v7`/`v8` por defecto en herramientas actualizadas, lo que provoca cierres inmediatos al arranque en `1.10.163`.
- **Evidencia:** Verificado mediante auditoría binaria automatizada y pruebas en vivo en ambas versiones del motor.
