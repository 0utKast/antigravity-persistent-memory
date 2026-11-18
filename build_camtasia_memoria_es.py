# -*- coding: utf-8 -*-
"""
Constructor maestro Camtasia 10.0 (3840x2160 @ 60 fps) — Tutorial:
Memoria Persistente Local-First en Antigravity (Capas L0–L3) (ES).

REGLA DE ORO DE PRODUCCION (DC-EP-002):
  Este script se ejecuta UNA SOLA VEZ con `--force-reset-from-scratch` tras validar
  las hojas de prueba con `--dry-run-proofs`. Una vez entregado `.tscproj`, queda
  bloqueado contra sobreescrituras para preservar las ediciones manuales en Track 1/3/4.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import pathlib
import subprocess
import sys
from datetime import datetime
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

EDIT_RATE = 705600000
FPS = 60
TICKS_PER_FRAME = EDIT_RATE // FPS  # 11760000
W, H = 3840, 2160

TRANS_WIPE_TICKS = int(round(0.50 * FPS)) * TICKS_PER_FRAME  # 352800000
DRAW_FADE_TICKS = int(round(0.80 * FPS)) * TICKS_PER_FRAME   # 564480000
FADE_OUT_TICKS = int(round(1.40 * FPS)) * TICKS_PER_FRAME    # 987840000

INTRO_S = 10.05  # Intro musical limpia (603 frames exactos = 7091280000 ticks)
TAIL_S = 1.50    # Cola musical de salida tras finalizar locucion

CAM_DIR = pathlib.Path(r"C:\Videotutoriales\DesarrolloCursos\001MemoriaPersistente\001MemoriaPersistente.tscproj")
OUT_TSCPROJ = CAM_DIR / "001MemoriaPersistente.tscproj"
TEMPLATE_TSCPROJ = pathlib.Path(
    r"C:\Videotutoriales\CursoModding\003CursoModding\003CursoModding.tscproj\003CursoModding.tscproj"
)
SVG_PATH = pathlib.Path(r"C:\Program Files\TechSmith\Camtasia\Media\Studio\Callouts\anim_drawnperfectrectangle.svg")

SCRATCH_DIR = pathlib.Path(
    r"C:\Users\educa\.gemini\antigravity\brain\3b966c2b-3f36-4941-ad98-6cb475c45e01\scratch\memoria_video"
)
COLORS_JSON = SCRATCH_DIR / "curated_slide_colors.json"
LAB_DOM_JSON = SCRATCH_DIR / "memoria_lab_dom_boxes.json"
SCRIBE_WORDS_JSON = SCRATCH_DIR / "es_memoria_scribe_words.json"

OUT_WORD_AUDIT = SCRATCH_DIR / "es_memoria_callout_word_audit.txt"
OUT_PROOF_SLIDES_1 = SCRATCH_DIR / "callout_memoria_slides_proof_1.jpg"
OUT_PROOF_SLIDES_2 = SCRATCH_DIR / "callout_memoria_slides_proof_2.jpg"
OUT_PROOF_LABS = SCRATCH_DIR / "callout_memoria_labs_proof.jpg"

AUDIO_VO = "locucion_memoria_persistente_antigravity_jesus_conde_completa.mp3"
AUDIO_BG = "Nuclear Baby.mp3"

# Colores sobrios nativos del tema oscuro de visualizador_memoria_persistente_antigravity.html (max <= 0.86)
LAB_COL_CYAN = (0.219608, 0.725490, 0.854902)
LAB_COL_GREEN = (0.247059, 0.764706, 0.450980)
LAB_COL_AMBER = (0.835294, 0.650980, 0.215686)
LAB_COL_CORAL = (0.823529, 0.360784, 0.360784)


def s2t(seconds: float) -> int:
    return int(round(seconds * FPS)) * TICKS_PER_FRAME


def t2s(ticks: int) -> float:
    return ticks / float(EDIT_RATE)


def pad_rect(r: list[int], px: int = 12) -> list[int]:
    x1, y1, x2, y2 = r
    return [max(14, x1 - px), max(14, y1 - px), min(W - 14, x2 + px), min(H - 14, y2 + px)]


def probe_media(path: pathlib.Path) -> dict[str, Any]:
    cmd = ["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)]
    data = json.loads(subprocess.check_output(cmd, text=True))
    v = next((s for s in data["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in data["streams"] if s["codec_type"] == "audio"), None)
    dur = float(data["format"]["duration"]) if "duration" in data["format"] else 0.0
    return {"video": v, "audio": a, "duration": dur}


def pick_contrasting_slide_color(
    img_cache: dict[str, np.ndarray],
    slide_colors: dict[str, Any],
    slide_name: str,
    rect_4k: list[int],
    rank: int = 0,
) -> tuple[float, float, float]:
    """
    Selecciona un color de acento autentico de `slide_name` comprobando contraste local
    en el anillo perimetral de `rect_4k` (evitando tonos mimetizados con el fondo o neones).
    """
    cands = [c["rgb01"] for c in slide_colors.get(slide_name, {}).get("colors", [])]
    if not cands:
        return (0.290196, 0.560784, 0.658824)

    if slide_name not in img_cache:
        with Image.open(CAM_DIR / slide_name) as im:
            img_cache[slide_name] = np.asarray(im.convert("RGB"), dtype=np.float32)

    arr = img_cache[slide_name]
    x1, y1, x2, y2 = [max(0, min(lim, v)) for v, lim in zip(rect_4k, (W - 1, H - 1, W - 1, H - 1))]
    pad = 14
    ox1, oy1 = max(0, x1 - pad), max(0, y1 - pad)
    ox2, oy2 = min(W, x2 + pad), min(H, y2 + pad)

    samples = []
    if oy1 < y1:
        samples.append(arr[oy1:y1, ox1:ox2].reshape(-1, 3))
    if y2 < oy2:
        samples.append(arr[y2:oy2, ox1:ox2].reshape(-1, 3))
    if ox1 < x1:
        samples.append(arr[oy1:oy2, ox1:x1].reshape(-1, 3))
    if x2 < ox2:
        samples.append(arr[oy1:oy2, x2:ox2].reshape(-1, 3))

    ring_rgb = np.median(np.vstack(samples), axis=0) if samples else np.array([128.0, 128.0, 128.0])

    scored: list[tuple[int, float, tuple[float, float, float]]] = []
    for idx, rgb01 in enumerate(cands):
        rgb255 = np.array([c * 255.0 for c in rgb01], dtype=np.float32)
        dist = float(np.linalg.norm(rgb255 - ring_rgb))
        sat = (max(rgb01) - min(rgb01)) / max(max(rgb01), 1e-4)
        # Prioriza la preferencia `rank` si supera distancia minima 48; si no, maximo contraste
        pref_bonus = 1 if idx == (rank % len(cands)) else 0
        ok_dist = 1 if dist >= 48.0 else 0
        scored.append((ok_dist * 10 + pref_bonus, dist + sat * 25.0, (float(rgb01[0]), float(rgb01[1]), float(rgb01[2]))))

    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
    chosen = list(scored[0][2])
    m = max(chosen)
    if m > 0.90:
        fac = 0.88 / m
        chosen = [round(v * fac, 6) for v in chosen]
    return float(chosen[0]), float(chosen[1]), float(chosen[2])


class IdGen:
    def __init__(self, start: int = 1) -> None:
        self.val = start

    def next(self) -> int:
        v = self.val
        self.val += 1
        return v


def build_source_bin(ids: IdGen, media_files: list[str]) -> tuple[list[dict], dict[str, dict]]:
    sb: list[dict] = []
    meta_map: dict[str, dict] = {}
    for fname in media_files:
        fpath = CAM_DIR / fname
        assert fpath.exists(), f"Falta archivo en carpeta Camtasia: {fpath}"
        ext = fpath.suffix.lower()
        sid = ids.next()
        mtime = datetime.fromtimestamp(fpath.stat().st_mtime).strftime("%Y%m%dT%H%M%S")

        if ext == ".png":
            with Image.open(fpath) as im:
                assert im.size == (W, H), f"Dimension invalida en {fname}: {im.size}"
            sb.append(
                {
                    "id": sid,
                    "src": fname,
                    "rect": [0, 0, W, H],
                    "lastMod": mtime,
                    "loudnessNormalization": True,
                    "sourceTracks": [
                        {
                            "range": [0, 1],
                            "type": 1,
                            "editRate": 10000000,
                            "trackRect": [0, 0, W, H],
                            "sampleRate": 0,
                            "bitDepth": 32,
                            "numChannels": 0,
                            "integratedLUFS": 100.0,
                            "peakLevel": -1.0,
                            "tag": 0,
                            "metaData": f"{fname};",
                            "parameters": {},
                        }
                    ],
                    "metadata": {"timeAdded": datetime.now().strftime("%Y%m%dT%H%M%S.000000")},
                }
            )
            meta_map[fname] = {"id": sid, "type": "png", "duration": 0.0, "channels": 0}
        elif ext == ".mp3":
            info = probe_media(fpath)
            dur = info["duration"]
            a = info["audio"]
            sr, ch = int(a["sample_rate"]), int(a["channels"])
            rng_end = int(math.floor(dur * 10000000))
            sb.append(
                {
                    "id": sid,
                    "src": fname,
                    "rect": [0, 0, 0, 0],
                    "lastMod": mtime,
                    "loudnessNormalization": True,
                    "sourceTracks": [
                        {
                            "range": [0, rng_end],
                            "type": 2,
                            "editRate": 10000000,
                            "trackRect": [0, 0, 0, 0],
                            "sampleRate": sr,
                            "bitDepth": 0,
                            "numChannels": ch,
                            "integratedLUFS": -19.2,
                            "peakLevel": 0.87,
                            "tag": 0,
                            "metaData": f"{fname};",
                            "parameters": {},
                        }
                    ],
                    "metadata": {"timeAdded": datetime.now().strftime("%Y%m%dT%H%M%S.000000")},
                }
            )
            meta_map[fname] = {"id": sid, "type": "mp3", "duration": dur, "channels": ch}
        elif ext == ".mp4":
            info = probe_media(fpath)
            dur = info["duration"]
            v, a = info["video"], info["audio"]
            vw, vh = int(v["width"]), int(v["height"])
            assert (vw, vh) == (W, H), f"{fname} no es 4K: {vw}x{vh}"
            ms_end = int(math.floor(dur * 1000))
            sr = int(a["sample_rate"]) if a else 48000
            ch = int(a["channels"]) if a else 2
            sb.append(
                {
                    "id": sid,
                    "src": fname,
                    "rect": [0, 0, W, H],
                    "lastMod": mtime,
                    "loudnessNormalization": True,
                    "sourceTracks": [
                        {
                            "range": [0, ms_end],
                            "type": 0,
                            "editRate": 1000,
                            "trackRect": [0, 0, W, H],
                            "sampleRate": "60/1",
                            "bitDepth": 24,
                            "numChannels": 0,
                            "integratedLUFS": 100.0,
                            "peakLevel": -1.0,
                            "tag": 0,
                            "metaData": f"{fname};",
                            "parameters": {},
                        },
                        {
                            "range": [0, ms_end],
                            "type": 2,
                            "editRate": 1000,
                            "trackRect": [0, 0, 0, 0],
                            "sampleRate": sr,
                            "bitDepth": 16,
                            "numChannels": ch,
                            "integratedLUFS": -70.0,
                            "peakLevel": 0.0,
                            "tag": 0,
                            "metaData": f"{fname};",
                            "parameters": {},
                        },
                    ],
                    "metadata": {"timeAdded": datetime.now().strftime("%Y%m%dT%H%M%S.000000")},
                }
            )
            meta_map[fname] = {"id": sid, "type": "mp4", "duration": dur, "channels": ch}
        else:
            raise ValueError(f"Tipo de medio no soportado: {fname}")

    return sb, meta_map


def make_gradient_wipe(left_id: int | None = None, right_id: int | None = None, dur: int = TRANS_WIPE_TICKS) -> dict:
    tr: dict[str, Any] = {
        "name": "GradientWipe",
        "duration": dur,
        "attributes": {
            "Angle": 0.0,
            "Width": 0.2,
            "bypass": False,
            "reverse": False,
            "trivial": False,
            "useAudioPreRoll": True,
            "useVisualPreRoll": True,
        },
    }
    if left_id is not None:
        tr["leftMedia"] = left_id
    if right_id is not None:
        tr["rightMedia"] = right_id
    return tr


def make_rect_callout(
    ids: IdGen,
    svg_xml: str,
    label: str,
    start_s: float,
    end_s: float,
    rect_4k: list[int],
    rgb01: tuple[float, float, float],
    border_w: float = 12.0,
) -> dict:
    x1, y1, x2, y2 = rect_4k
    assert 0 <= x1 < x2 <= W and 0 <= y1 < y2 <= H, f"Rect fuera de 4K ({label}): {rect_4k}"
    st, en = s2t(start_s), s2t(end_s)
    dur = en - st
    assert dur >= 15 * TICKS_PER_FRAME, f"Callout demasiado corto ({label}): {dur/EDIT_RATE:.2f}s"
    tx = (x1 + x2) / 2.0 - 1920.0
    ty = 1080.0 - (y1 + y2) / 2.0
    sx = (x2 - x1) / 960.0
    sy = (y2 - y1) / 540.0
    r, g, b = rgb01
    assert max(r, g, b) <= 0.905, f"Color fuera de techo armonico ({label}): {rgb01}"

    return {
        "id": ids.next(),
        "_type": "Callout",
        "def": {
            "kind": "TypeWinSVG",
            "shape": "",
            "style": "",
            "DrawTime": 1.0,
            "borderColorBlue": round(b, 6),
            "borderColorGreen": round(g, 6),
            "borderColorRed": round(r, 6),
            "borderWidth": border_w,
            "corner-radius": 6.0,
            "enable-ligatures": 0.0,
            "flipOnXAxis": 0.0,
            "flipOnYAxis": 0.0,
            "height": 540.0,
            "width": 960.0,
            "filename": str(SVG_PATH),
            "name": "",
            "resize-behavior": "resizeCallout",
            "xmlContent": svg_xml,
        },
        "attributes": {"ident": label, "autoRotateText": True},
        "parameters": {
            "translation0": round(tx, 6),
            "translation1": round(ty, 6),
            "scale0": round(sx, 6),
            "scale1": round(sy, 6),
            "geometryCrop0": 0.0,
            "geometryCrop1": 0.0,
            "geometryCrop2": 0.0,
            "geometryCrop3": 0.0,
        },
        "leftEdgeMods": [
            {
                "group": "DrawPercentageFade",
                "duration": min(DRAW_FADE_TICKS, max(15 * TICKS_PER_FRAME, (dur // 3 // TICKS_PER_FRAME) * TICKS_PER_FRAME)),
                "parameters": [{"name": "DrawTime", "func": "FadeInFunc"}],
            }
        ],
        "effects": [],
        "start": st,
        "duration": dur,
        "mediaStart": 0,
        "mediaDuration": dur,
        "scalar": 1,
        "metadata": {
            "audiateLinkedSession": "",
            "clipSpeedAttribute": {"type": "bool", "value": False},
            "colorAttribute": {"type": "color", "value": [0, 0, 0, 0]},
            "default-anchor0": {"type": "double", "value": 0.0},
            "default-anchor1": {"type": "double", "value": 0.0},
            "default-anchor2": {"type": "double", "value": 0.0},
            "default-height": {"type": "double", "value": 540.0},
            "default-rotation0": {"type": "double", "value": 0.0},
            "default-rotation1": {"type": "double", "value": 0.0},
            "default-rotation2": {"type": "double", "value": 0.0},
            "default-scale0": {"type": "double", "value": 1.0},
            "default-scale1": {"type": "double", "value": 1.0},
            "default-scale2": {"type": "double", "value": 1.0},
            "default-shear0": {"type": "double", "value": 0.0},
            "default-shear1": {"type": "double", "value": 0.0},
            "default-shear2": {"type": "double", "value": 0.0},
            "default-stroke-color-blue": {"type": "double", "value": 0.0},
            "default-stroke-color-green": {"type": "double", "value": 0.0},
            "default-stroke-color-red": {"type": "double", "value": 1.0},
            "default-stroke-width": {"type": "double", "value": 5.0},
            "default-translation0": {"type": "double", "value": 0.0},
            "default-translation1": {"type": "double", "value": 0.0},
            "default-translation2": {"type": "double", "value": 0.0},
            "default-width": {"type": "double", "value": 960.0},
        },
        "animationTracks": {},
    }


def make_text_badge(ids: IdGen, text: str, start_s: float, end_s: float, rect_4k: list[int]) -> dict:
    x1, y1, x2, y2 = rect_4k
    st, en = s2t(start_s), s2t(end_s)
    dur = en - st
    tx = (x1 + x2) / 2.0 - 1920.0
    ty = 1080.0 - (y1 + y2) / 2.0
    bw = max(1920.0, float(x2 - x1))
    bh = max(200.0, float(y2 - y1))
    n_utf8 = len(text.encode("utf-8"))  # Obligatorio bytes UTF-8 para motor C++ de Camtasia (DC-INV-01)

    return {
        "id": ids.next(),
        "_type": "Callout",
        "def": {
            "kind": "remix",
            "shape": "text",
            "style": "basic",
            "corner-radius": 8.0,
            "enable-ligatures": 1.0,
            "height": bh,
            "line-spacing": 0.0,
            "text-stroke-alignment": 2.0,
            "text-stroke-color-alpha": 1.0,
            "text-stroke-color-blue": 0.12,
            "text-stroke-color-green": 0.09,
            "text-stroke-color-red": 0.06,
            "text-stroke-width": 6.0,
            "width": bw,
            "word-wrap": 1.0,
            "horizontal-alignment": "center",
            "resize-behavior": "resizeText",
            "text": text,
            "vertical-alignment": "center",
            "font": {
                "color-blue": 0.98,
                "color-green": 0.96,
                "color-red": 0.33,
                "size": 48.0,
                "tracking": 0.0,
                "name": "Montserrat",
                "weight": "Bold",
            },
            "textAttributes": {
                "type": "textAttributeList",
                "keyframes": [
                    {
                        "endTime": 0,
                        "time": 0,
                        "duration": 0,
                        "value": [
                            {"name": "fontSize", "rangeStart": 0, "rangeEnd": n_utf8, "value": 48.0, "valueType": "double"},
                            {"name": "fontName", "rangeStart": 0, "rangeEnd": n_utf8, "value": "Montserrat", "valueType": "string"},
                            {"name": "underline", "rangeStart": 0, "rangeEnd": n_utf8, "value": 0, "valueType": "int"},
                            {"name": "kerning", "rangeStart": 0, "rangeEnd": n_utf8, "value": 0.0, "valueType": "double"},
                            {"name": "strikethrough", "rangeStart": 0, "rangeEnd": n_utf8, "value": 0, "valueType": "int"},
                            {"name": "fgColor", "rangeStart": 0, "rangeEnd": n_utf8, "value": "(83,246,250,255)", "valueType": "color"},
                            {"name": "fontItalic", "rangeStart": 0, "rangeEnd": n_utf8, "value": 0, "valueType": "int"},
                            {"name": "fontWeight", "rangeStart": 0, "rangeEnd": n_utf8, "value": 700, "valueType": "int"},
                        ],
                    }
                ],
            },
        },
        "attributes": {"ident": text.replace("\r", " "), "autoRotateText": True},
        "parameters": {
            "translation0": round(tx, 6),
            "translation1": round(ty, 6),
            "geometryCrop0": 0.0,
            "geometryCrop1": 0.0,
            "geometryCrop2": 0.0,
            "geometryCrop3": 0.0,
        },
        "effects": [],
        "start": st,
        "duration": dur,
        "mediaStart": 0,
        "mediaDuration": dur,
        "scalar": 1,
        "metadata": {
            "audiateLinkedSession": "",
            "clipSpeedAttribute": {"type": "bool", "value": False},
            "colorAttribute": {"type": "color", "value": [0, 0, 0, 0]},
            "default-HAlign": "center",
            "default-LineSpace": {"type": "double", "value": 0.0},
            "default-VAlign": "center",
            "default-height": {"type": "double", "value": bh},
            "default-width": {"type": "double", "value": bw},
        },
        "animationTracks": {},
    }


def build_track2_slots(video_end_s: float) -> list[tuple[str, str, float, float, float]]:
    """(kind, filename, start_s, end_s, media_start_s)"""
    return [
        ("img", "slide_01_portada_amnesia_memoria.png",         0.00,   21.85,  0.00),
        ("img", "slide_02_direccion_tecnica_estudio.png",       21.85,   63.05,  0.00),
        ("img", "slide_03_choque_teoria_gregory.png",           63.05,  112.10,  0.00),
        ("img", "slide_04_ciclo_amnesia_operativa.png",        112.10,  149.50,  0.00),
        ("img", "slide_05_lecciones_empiricas_resumen.png",    149.50,  172.10,  0.00),
        ("img", "slide_06_colision_practica_fo4_tabla.png",    172.10,  256.95,  0.00),
        ("lab", "lab_01_trampas_reales.mp4",                   256.95,  307.65,  0.00),
        ("img", "slide_07_coste_invisible_olvidar.png",        307.65,  333.15,  0.00),
        ("img", "slide_08_parche_ingenuo_archivo_plano.png",   333.15,  362.85,  0.00),
        ("img", "slide_09_limite_24kb_truncamiento.png",       362.85,  396.65,  0.00),
        ("img", "slide_10_auditoria_fo4_983.png",              396.65,  416.95,  0.00),
        ("img", "slide_11_limite_20k_gemini_ingenieria.png",   416.95,  460.00,  0.00),
        ("img", "slide_12_davidson_hogar_contexto.png",        460.00,  506.05,  0.00),
        ("img", "slide_13_escotilla_escape_git.png",           506.05,  527.30,  0.00),
        ("img", "slide_14_taxonomia_cuatro_memorias.png",      527.30,  563.55,  0.00),
        ("img", "slide_15_aislamiento_se_johnson.png",         563.55,  591.30,  0.00),
        ("img", "slide_16_sistema_cuatro_capas.png",           591.30,  610.95,  0.00),
        ("img", "slide_17_capa_l0_constitucion.png",           610.95,  652.90,  0.00),
        ("img", "slide_18_capa_l1_reglas_modulares.png",       652.90,  683.30,  0.00),
        ("img", "slide_19_capa_l2_indice_ahorro.png",          683.30,  717.80,  0.00),
        ("img", "slide_20_capa_l3_sqlite_mcp.png",             717.80,  737.30,  0.00),
        ("lab", "lab_02_enrutador_l2_federacion.mp4",          737.30,  755.00,  0.00),
        ("lab", "lab_03_motor_fts5_poisoning_hooks.mp4",       755.00,  792.05,  0.00),
        ("img", "slide_21_saneador_fts5_modding.png",          792.05,  808.45,  0.00),
        ("lab", "lab_03_motor_fts5_poisoning_hooks.mp4",       808.45,  839.80, 37.05),
        ("img", "slide_22_compuerta_provisional_verified.png", 839.80,  852.80,  0.00),
        ("img", "slide_23_promocion_autonoma_n2.png",          852.80,  875.15,  0.00),
        ("lab", "lab_03_motor_fts5_poisoning_hooks.mp4",       875.15,  895.00, 68.40),
        ("img", "slide_24_ganchos_nativos_antigravity.png",    895.00,  916.20,  0.00),
        ("img", "slide_25_auditoria_estacion_estado.png",      916.20,  946.10,  0.00),
        ("img", "slide_26_telemetria_consultas_federadas.png", 946.10,  971.10,  0.00),
        ("lab", "lab_04_simulacion_6_etapas_pass1.mp4",        971.10, 1033.95,  0.00),
        ("img", "slide_27_simulador_roi_879.png",             1033.95, 1046.65,  0.00),
        ("img", "slide_28_ventaja_competitiva_estudio.png",   1046.65, 1071.45,  0.00),
        ("img", "slide_29_especialistas_veteranos_perm.png",  1071.45, 1101.35,  0.00),
        ("img", "slide_30_cierre_repositorio_listo.png",      1101.35, video_end_s, 0.00),
    ]


def build_callout_specs(
    dom: dict[str, list[int]],
    slide_colors: dict[str, Any],
    img_cache: dict[str, np.ndarray],
    video_end_s: float,
) -> tuple[list[tuple[str, float, float, list[int], tuple[float, float, float], str]], list[tuple]]:
    def sc(slide: str, rect: list[int], rank: int = 0) -> tuple[float, float, float]:
        return pick_contrasting_slide_color(img_cache, slide_colors, slide, rect, rank)

    # Track 3: Marcadores Primarios sincronizados palabra por palabra con Scribe
    t3: list[tuple[str, float, float, list[int], tuple[float, float, float], str]] = [
        ("slide_01_portada_amnesia_memoria.png", 10.50, 21.30, [160, 480, 3680, 1220], sc("slide_01_portada_amnesia_memoria.png", [160, 480, 3680, 1220], 0), "Portada: Arquitectura de Memoria Persistente L0-L3"),
        ("slide_02_direccion_tecnica_estudio.png", 27.80, 38.90, [120, 230, 1265, 1480], sc("slide_02_direccion_tecnica_estudio.png", [120, 230, 1265, 1480], 0), "Fallout 4: Cronicas del Refugio 13 y Piper Wright"),
        ("slide_02_direccion_tecnica_estudio.png", 39.20, 43.20, [1300, 230, 2525, 1480], sc("slide_02_direccion_tecnica_estudio.png", [1300, 230, 2525, 1480], 1), "Cyberpunk 2077: Misiones de Mundo Abierto"),
        ("slide_02_direccion_tecnica_estudio.png", 43.45, 48.35, [2560, 230, 3720, 1480], sc("slide_02_direccion_tecnica_estudio.png", [2560, 230, 3720, 1480], 2), "Estudio Audiovisual: Produccion 4K Automatizada"),
        ("slide_02_direccion_tecnica_estudio.png", 48.85, 62.55, [880, 1590, 2960, 2005], sc("slide_02_direccion_tecnica_estudio.png", [880, 1590, 2960, 2005], 0), "Direccion Humana (Arquitecto / Planificador / QA)"),
        ("slide_03_choque_teoria_gregory.png", 66.60, 83.00, [155, 1455, 1905, 1985], sc("slide_03_choque_teoria_gregory.png", [155, 1455, 1905, 1985], 0), "Cita Impresa: Jason Gregory — Motores"),
        ("slide_03_choque_teoria_gregory.png", 83.55, 111.60, [1925, 445, 3685, 1985], sc("slide_03_choque_teoria_gregory.png", [1925, 445, 3685, 1985], 1), "La Realidad: Comportamiento Empirico en Windows"),
        ("slide_04_ciclo_amnesia_operativa.png", 112.60, 115.40, [1340, 495, 2500, 745], sc("slide_04_ciclo_amnesia_operativa.png", [1340, 495, 2500, 745], 0), "1. Fallo Sutil y Lectura de Registros"),
        ("slide_04_ciclo_amnesia_operativa.png", 115.65, 122.40, [2490, 815, 3430, 1155], sc("slide_04_ciclo_amnesia_operativa.png", [2490, 815, 3430, 1155], 0), "2. Pruebas Controladas e Hipotesis Descartadas"),
        ("slide_04_ciclo_amnesia_operativa.png", 122.65, 126.10, [2480, 1490, 3470, 1845], sc("slide_04_ciclo_amnesia_operativa.png", [2480, 1490, 3470, 1845], 2), "3. Exito: Causa Raiz Exacta"),
        ("slide_04_ciclo_amnesia_operativa.png", 126.55, 132.95, [400, 1485, 1365, 1845], sc("slide_04_ciclo_amnesia_operativa.png", [400, 1485, 1365, 1845], 1), "4. Cierre de Sesion: Vaciado Volatil"),
        ("slide_04_ciclo_amnesia_operativa.png", 133.25, 148.95, [380, 815, 1350, 1165], sc("slide_04_ciclo_amnesia_operativa.png", [380, 815, 1350, 1165], 1), "5. Amnesia Operativa al Dia Siguiente"),
        ("slide_05_lecciones_empiricas_resumen.png", 150.10, 161.90, [135, 585, 3705, 1790], sc("slide_05_lecciones_empiricas_resumen.png", [135, 585, 3705, 1790], 0), "Lecciones Empiricas Fuera de los Libros"),
        ("slide_05_lecciones_empiricas_resumen.png", 162.30, 171.60, [145, 595, 1295, 1785], sc("slide_05_lecciones_empiricas_resumen.png", [145, 595, 1295, 1785], 2), "Compilacion y Registros Reales en Vivo"),
        ("slide_06_colision_practica_fo4_tabla.png", 172.60, 219.65, [345, 685, 3695, 1025], sc("slide_06_colision_practica_fo4_tabla.png", [345, 685, 3695, 1025], 0), "FO4-EP-001: Escuadron en Adytum (Aggression=1.0)"),
        ("slide_06_colision_practica_fo4_tabla.png", 220.45, 256.40, [345, 1030, 3695, 1375], sc("slide_06_colision_practica_fo4_tabla.png", [345, 1030, 3695, 1375], 1), "West Tek: Coordenada Logica Congelada en Partida"),
        ("lab_01_trampas_reales.mp4", 265.70, 288.45, pad_rect(dom["code_container"]), LAB_COL_CYAN, "Lab (s3): CP77-EP-004 Audioware 150ms & Escaner"),
        ("lab_01_trampas_reales.mp4", 289.10, 307.15, pad_rect(dom["station_cards"]), LAB_COL_GREEN, "Lab: DC-EP-001 UTF-8 en Estudio 4K y Repos Activos"),
        ("slide_07_coste_invisible_olvidar.png", 308.15, 315.40, [190, 540, 3660, 1480], sc("slide_07_coste_invisible_olvidar.png", [190, 540, 3660, 1480], 2), "Coste de API, Compilaciones y Testeo Humano"),
        ("slide_07_coste_invisible_olvidar.png", 315.80, 332.65, [245, 1510, 3585, 1985], sc("slide_07_coste_invisible_olvidar.png", [245, 1510, 3585, 1985], 0), "Acumulacion de Veterania Sesion tras Sesion"),
        ("slide_08_parche_ingenuo_archivo_plano.png", 333.80, 351.00, [170, 550, 1055, 1185], sc("slide_08_parche_ingenuo_archivo_plano.png", [170, 550, 1055, 1185], 0), "Error Inicial: Acumular en Raiz AGENTS.md"),
        ("slide_08_parche_ingenuo_archivo_plano.png", 351.60, 362.35, [380, 1810, 3455, 2070], sc("slide_08_parche_ingenuo_archivo_plano.png", [380, 1810, 3455, 2070], 1), "Choque Inminente Contra el Limite de Plataforma"),
        ("slide_09_limite_24kb_truncamiento.png", 375.30, 386.45, [390, 620, 2610, 1055], sc("slide_09_limite_24kb_truncamiento.png", [390, 620, 2610, 1055], 0), "Tope Duro: 24.000 Bytes Tras Expansion"),
        ("slide_09_limite_24kb_truncamiento.png", 386.95, 396.15, [2630, 430, 3715, 1130], sc("slide_09_limite_24kb_truncamiento.png", [2630, 430, 3715, 1130], 1), "Truncamiento Silencioso por Lineas"),
        ("slide_10_auditoria_fo4_983.png", 397.15, 408.85, [2520, 760, 3765, 1250], sc("slide_10_auditoria_fo4_983.png", [2520, 760, 3765, 1250], 0), "Auditoria Fallout 4: 23.585 B (98,3 %)"),
        ("slide_10_auditoria_fo4_983.png", 409.10, 416.45, [930, 1430, 2910, 1930], sc("slide_10_auditoria_fo4_983.png", [930, 1430, 2910, 1930], 5), "A Un Solo Parrafo de Perder Reglas Finales"),
        ("slide_11_limite_20k_gemini_ingenieria.png", 417.45, 431.20, [2140, 450, 3490, 880], sc("slide_11_limite_20k_gemini_ingenieria.png", [2140, 450, 3490, 880], 5), "GEMINI.md Global Inflado: 5.321 Bytes"),
        ("slide_11_limite_20k_gemini_ingenieria.png", 431.45, 441.35, [210, 620, 1420, 1130], sc("slide_11_limite_20k_gemini_ingenieria.png", [210, 620, 1420, 1130], 1), "Presupuesto Agregado Always-On: 20.000 Tokens"),
        ("slide_11_limite_20k_gemini_ingenieria.png", 441.80, 459.45, [350, 1490, 3495, 1970], sc("slide_11_limite_20k_gemini_ingenieria.png", [350, 1490, 3495, 1970], 2), "Necesidad de Ingenieria de Contexto Escalable"),
        ("slide_12_davidson_hogar_contexto.png", 475.70, 486.60, [2030, 325, 3620, 505], sc("slide_12_davidson_hogar_contexto.png", [2030, 325, 3620, 505], 5), "Cita Impresa: Duncan Davidson / O'Reilly"),
        ("slide_12_davidson_hogar_contexto.png", 487.00, 505.55, [130, 315, 1850, 1970], sc("slide_12_davidson_hogar_contexto.png", [130, 315, 1850, 1970], 1), "Diagnostico: Silos Cerrados en la Nube"),
        ("slide_13_escotilla_escape_git.png", 506.55, 514.90, [1980, 430, 3580, 1490], sc("slide_13_escotilla_escape_git.png", [1980, 430, 3580, 1490], 0), "Enfoque Local-First y Escotilla de Escape"),
        ("slide_13_escotilla_escape_git.png", 515.15, 526.80, [245, 1490, 3595, 2010], sc("slide_13_escotilla_escape_git.png", [245, 1490, 3595, 2010], 4), "Markdown Limpio y Versionado con Git"),
        ("slide_14_taxonomia_cuatro_memorias.png", 527.80, 543.80, [450, 1850, 3395, 2030], sc("slide_14_taxonomia_cuatro_memorias.png", [450, 1850, 3395, 2030], 5), "Cita Impresa: 7 Autores O'Reilly en Pie de Lamina"),
        ("slide_14_taxonomia_cuatro_memorias.png", 544.30, 549.90, [450, 610, 2050, 1210], sc("slide_14_taxonomia_cuatro_memorias.png", [450, 610, 2050, 1210], 0), "1. Memoria de Trabajo Volatil"),
        ("slide_14_taxonomia_cuatro_memorias.png", 550.25, 553.20, [2080, 610, 3695, 1210], sc("slide_14_taxonomia_cuatro_memorias.png", [2080, 610, 3695, 1210], 0), "2. Memoria Semantica Congelada"),
        ("slide_14_taxonomia_cuatro_memorias.png", 553.55, 558.80, [450, 1230, 2050, 1825], sc("slide_14_taxonomia_cuatro_memorias.png", [450, 1230, 2050, 1825], 2), "3. Memoria Episodica (Incidentes Reales)"),
        ("slide_14_taxonomia_cuatro_memorias.png", 559.15, 563.05, [2080, 1230, 3695, 1825], sc("slide_14_taxonomia_cuatro_memorias.png", [2080, 1230, 3695, 1825], 1), "4. Memoria Procedimental (Leyes Activas)"),
        ("slide_15_aislamiento_se_johnson.png", 564.05, 572.50, [165, 430, 2135, 2055], sc("slide_15_aislamiento_se_johnson.png", [165, 430, 2135, 2055], 5), "Acceso por Ambitos y Bloqueo de Infeccion"),
        ("slide_15_aislamiento_se_johnson.png", 573.10, 590.75, [2185, 430, 3655, 1895], sc("slide_15_aislamiento_se_johnson.png", [2185, 430, 3655, 1895], 0), "Cita Impresa: Ksenia Se y Pete Johnson"),
        ("slide_16_sistema_cuatro_capas.png", 591.85, 610.45, [580, 585, 3720, 2060], sc("slide_16_sistema_cuatro_capas.png", [580, 585, 3720, 2060], 2), "Plugin Global L0-L3 Operativo desde el Dia Uno"),
        ("slide_17_capa_l0_constitucion.png", 611.45, 620.30, [200, 400, 1745, 1090], sc("slide_17_capa_l0_constitucion.png", [200, 400, 1745, 1090], 0), "Capa L0: Constitucion Minima Siempre Cargada"),
        ("slide_17_capa_l0_constitucion.png", 620.80, 644.30, [200, 1120, 1745, 1915], sc("slide_17_capa_l0_constitucion.png", [200, 1120, 1745, 1915], 5), "Metricas L0 Reales: 5.071 / 6.525 / 3.860 / 1.364 B"),
        ("slide_17_capa_l0_constitucion.png", 644.65, 652.40, [200, 400, 1745, 1090], sc("slide_17_capa_l0_constitucion.png", [200, 400, 1745, 1090], 1), "Sin Diarios Largos: Solo Leyes y Puntero al Indice"),
        ("slide_18_capa_l1_reglas_modulares.png", 653.40, 674.70, [2110, 375, 3750, 1945], sc("slide_18_capa_l1_reglas_modulares.png", [2110, 375, 3750, 1945], 1), "Capa L1: Carga Bajo Demanda (~30 tok en Reposo)"),
        ("slide_18_capa_l1_reglas_modulares.png", 675.00, 682.80, [210, 395, 1975, 2020], sc("slide_18_capa_l1_reglas_modulares.png", [210, 395, 1975, 2020], 3), "Subdominios: .esp/.ba2, Dialogos y Fonetica"),
        ("slide_19_capa_l2_indice_ahorro.png", 683.80, 697.40, [200, 400, 1745, 1090], sc("slide_19_capa_l2_indice_ahorro.png", [200, 400, 1745, 1090], 0), "Capa L2: Indice Ligero + Diarios Git Markdown"),
        ("slide_19_capa_l2_indice_ahorro.png", 697.80, 717.30, [200, 1120, 1745, 1915], sc("slide_19_capa_l2_indice_ahorro.png", [200, 1120, 1745, 1915], 4), "339-542 Tokens: Ahorro del 87,0 % al 90,3 %"),
        ("slide_20_capa_l3_sqlite_mcp.png", 718.30, 736.80, [200, 400, 1745, 1475], sc("slide_20_capa_l3_sqlite_mcp.png", [200, 400, 1745, 1475], 0), "Capa L3: Cache SQLite FTS5 + BM25 y MCP 5 Herramientas"),
        ("lab_02_enrutador_l2_federacion.mp4", 737.80, 754.50, pad_rect(dom["code_container"]), LAB_COL_CYAN, "Lab (s2): Federacion Solo Lectura FO4/CP77 -> Estudio"),
        ("lab_03_motor_fts5_poisoning_hooks.mp4", 755.50, 770.70, pad_rect(dom["editor_window"]), LAB_COL_GREEN, "Lab: Motor Python 3 Estandar Cero Dependencias"),
        ("lab_03_motor_fts5_poisoning_hooks.mp4", 771.40, 791.55, pad_rect(dom["code_container"]), LAB_COL_CYAN, "Lab (s4): Consultas Crudas Rompen FTS5"),
        ("slide_21_saneador_fts5_modding.png", 792.55, 807.95, [1140, 1250, 2335, 1955], sc("slide_21_saneador_fts5_modding.png", [1140, 1250, 2335, 1955], 4), "Saneador Unicode: Limpieza de Ruido e Insensible a Tildes"),
        ("lab_03_motor_fts5_poisoning_hooks.mp4", 809.10, 839.30, pad_rect(dom["code_container"]), LAB_COL_AMBER, "Lab (s5): Compuerta Anti-Envenenamiento 2 Fases"),
        ("slide_22_compuerta_provisional_verified.png", 840.30, 852.30, [190, 1290, 3675, 1985], sc("slide_22_compuerta_provisional_verified.png", [190, 1290, 3675, 1985], 1), "PROVISIONAL Bloquea Ascenso Hasta Prueba en Vivo"),
        ("slide_23_promocion_autonoma_n2.png", 853.30, 867.10, [1150, 430, 3375, 1530], sc("slide_23_promocion_autonoma_n2.png", [1150, 430, 3375, 1530], 1), "Recurrencia N>=2: Promocion Autonoma a Capa L1"),
        ("slide_23_promocion_autonoma_n2.png", 867.35, 874.65, [2430, 1470, 3575, 1990], sc("slide_23_promocion_autonoma_n2.png", [2430, 1470, 3575, 1990], 4), "Tope Seguro: 18.000 Bytes por Regla Modular"),
        ("lab_03_motor_fts5_poisoning_hooks.mp4", 875.65, 894.50, pad_rect(dom["code_container"]), LAB_COL_CYAN, "Lab (s6): SessionStart y Guardian Stop Anti-Bucle"),
        ("slide_24_ganchos_nativos_antigravity.png", 895.50, 915.70, [2350, 1210, 3775, 1955], sc("slide_24_ganchos_nativos_antigravity.png", [2350, 1210, 3775, 1955], 5), "Gancho Stop: Vigila Anexos @[include] y Permisos"),
        ("slide_25_auditoria_estacion_estado.png", 927.80, 935.00, [150, 460, 3690, 1130], sc("slide_25_auditoria_estacion_estado.png", [150, 460, 3690, 1130], 1), "Auditoria Real: 3 Repos y 29 Episodios VERIFIED"),
        ("slide_25_auditoria_estacion_estado.png", 935.40, 945.60, [160, 1210, 1790, 1900], sc("slide_25_auditoria_estacion_estado.png", [160, 1210, 1790, 1900], 5), "Menos del 18 % Consumido de los 20.000 Tokens"),
        ("slide_26_telemetria_consultas_federadas.png", 946.60, 970.60, [170, 1330, 3675, 1995], sc("slide_26_telemetria_consultas_federadas.png", [170, 1330, 3675, 1995], 4), "Consultas Federadas Instantaneas: FO4, .esl, CP77 y UTF-8"),
        ("lab_04_simulacion_6_etapas_pass1.mp4", 971.60, 983.50, pad_rect(dom["station_cards"]), LAB_COL_CYAN, "Lab Sim: Estacion Auditada vs Arranque en Frio"),
        ("lab_04_simulacion_6_etapas_pass1.mp4", 983.90, 1004.50, pad_rect(dom["stage_box"]), LAB_COL_CORAL, "Etapa 1/6 Frio: 0x00FFFFFF -> 5 Turnos, 9.240 tok"),
        ("lab_04_simulacion_6_etapas_pass1.mp4", 1009.40, 1015.50, pad_rect(dom["terminal_log"]), LAB_COL_AMBER, "Etapa 2/6: Bloqueo REJECTED_MEMORY_POISONING"),
        ("lab_04_simulacion_6_etapas_pass1.mp4", 1015.80, 1020.10, pad_rect(dom["stage_box"]), LAB_COL_CYAN, "Etapa 3/6: Consolidacion PROVISIONAL -> VERIFIED"),
        ("lab_04_simulacion_6_etapas_pass1.mp4", 1020.40, 1033.45, pad_rect(dom["metric_pass"]), LAB_COL_GREEN, "Etapa 4-6: Pass@1 en 1 Turno (1.120 tok) y L1 N>=2"),
        ("slide_27_simulador_roi_879.png", 1034.45, 1046.15, [520, 1690, 3340, 2065], sc("slide_27_simulador_roi_879.png", [520, 1690, 3340, 2065], 3), "Metricas Clave: 87,9 % Ahorro y 4 Ciclos Eliminados"),
        ("slide_28_ventaja_competitiva_estudio.png", 1049.70, 1056.20, [250, 610, 1855, 1915], sc("slide_28_ventaja_competitiva_estudio.png", [250, 610, 1855, 1915], 0), "Modelos Base y Herramientas Cambian"),
        ("slide_28_ventaja_competitiva_estudio.png", 1056.80, 1070.95, [2290, 730, 3675, 1995], sc("slide_28_ventaja_competitiva_estudio.png", [2290, 730, 3675, 1995], 2), "Propiedad Intelectual: Tu Veterania Empirica"),
        ("slide_29_especialistas_veteranos_perm.png", 1072.00, 1100.85, [1470, 810, 3455, 1530], sc("slide_29_especialistas_veteranos_perm.png", [1470, 810, 3455, 1530], 0), "De Recien Llegados a Especialistas Veteranos"),
        ("slide_30_cierre_repositorio_listo.png", 1101.85, video_end_s - 0.65, [370, 550, 1815, 1115], sc("slide_30_cierre_repositorio_listo.png", [370, 550, 1815, 1115], 4), "Laboratorio, Visualizador y Plantillas Listas en Git"),
    ]

    # Track 4: Detalles Secundarios y Enlace de Repositorio
    t4: list[tuple] = [
        ("rect", "slide_03_choque_teoria_gregory.png", 66.60, 76.20, [155, 445, 1905, 1455], sc("slide_03_choque_teoria_gregory.png", [155, 445, 1905, 1455], 2), "Teoria Academica del Modelo"),
        ("rect", "slide_03_choque_teoria_gregory.png", 98.70, 111.60, [1930, 1455, 3680, 1980], sc("slide_03_choque_teoria_gregory.png", [1930, 1455, 3680, 1980], 2), "Friccion con Ejecutable Real Windows"),
        ("rect", "slide_06_colision_practica_fo4_tabla.png", 196.70, 219.50, [1910, 685, 3695, 1025], sc("slide_06_colision_practica_fo4_tabla.png", [1910, 685, 3695, 1025], 2), "Comportamiento Real: Autoalianza + Agg 1.0"),
        ("rect", "slide_06_colision_practica_fo4_tabla.png", 241.00, 256.30, [1910, 1030, 3695, 1375], sc("slide_06_colision_practica_fo4_tabla.png", [1910, 1030, 3695, 1375], 2), "Desync Camara/Proteccion Distancia"),
        ("rect", "lab_01_trampas_reales.mp4", 289.10, 307.15, pad_rect(dom["banner"]), LAB_COL_CYAN, "Banner Lab: FO4-EP-001 / CP77-EP-004 / DC-EP-001"),
        ("rect", "slide_08_parche_ingenuo_archivo_plano.png", 351.60, 356.50, [2775, 1215, 3670, 1745], sc("slide_08_parche_ingenuo_archivo_plano.png", [2775, 1215, 3670, 1745], 0), "Funciono Varias Semanas Hasta el Tope"),
        ("rect", "slide_12_davidson_hogar_contexto.png", 475.70, 486.60, [1975, 1500, 3720, 1965], sc("slide_12_davidson_hogar_contexto.png", [1975, 1500, 3720, 1965], 1), "Hogar Propio: Markdown y Git"),
        ("rect", "slide_17_capa_l0_constitucion.png", 611.45, 620.30, [1810, 1140, 3690, 1930], sc("slide_17_capa_l0_constitucion.png", [1810, 1140, 3690, 1930], 0), "Esquema 3D Capa L0 AGENTS.md"),
        ("rect", "lab_02_enrutador_l2_federacion.mp4", 741.40, 754.50, pad_rect(dom["station_cards"]), LAB_COL_GREEN, "Repositorios Federados en Solo Lectura"),
        ("rect", "lab_03_motor_fts5_poisoning_hooks.mp4", 771.40, 791.55, pad_rect(dom["banner"]), LAB_COL_AMBER, "Banner Lab: Saneamiento FTS5 + BM25"),
        ("rect", "slide_21_saneador_fts5_modding.png", 803.80, 807.95, [2390, 610, 3615, 1775], sc("slide_21_saneador_fts5_modding.png", [2390, 610, 3615, 1775], 5), "Resultado FTS5 en Milisegundos"),
        ("rect", "lab_03_motor_fts5_poisoning_hooks.mp4", 812.70, 839.30, pad_rect(dom["banner"]), LAB_COL_GREEN, "Banner Lab: Validacion 2 Fases PROVISIONAL->VERIFIED"),
        ("rect", "lab_04_simulacion_6_etapas_pass1.mp4", 996.00, 1004.50, pad_rect(dom["metrics_grid"]), LAB_COL_CORAL, "Metricas Frio: Barra Roja Pass@1"),
        ("rect", "lab_04_simulacion_6_etapas_pass1.mp4", 1020.40, 1033.45, pad_rect(dom["stage_box"]), LAB_COL_GREEN, "Detalle Etapa 4-6 Pass@1 en Vivo"),
        ("rect", "slide_27_simulador_roi_879.png", 1034.45, 1037.00, [1990, 1480, 3615, 1670], sc("slide_27_simulador_roi_879.png", [1990, 1480, 3615, 1670], 2), "Resultado: 1 Turno de Chat | 1.120 Tokens"),
        ("badge", "slide_30_cierre_repositorio_listo.png", 1101.95, video_end_s - 0.65, "Repositorio GitHub (MIT):\r0utKast/antigravity-persistent-memory", [140, 1170, 2060, 1430]),
    ]
    return t3, t4


def validate_all_tracks(tracks: list[dict], video_end_ticks: int, t2_plan: list[tuple[str, str, float, float, float]]) -> None:
    assert len(tracks) == 5, f"Se esperaban 5 pistas, hay {len(tracks)}"
    for ti, tr in enumerate(tracks):
        ms = sorted(tr["medias"], key=lambda m: m["start"])
        prev_end = 0
        for mi, m in enumerate(ms):
            st, du = m["start"], m["duration"]
            assert st % TICKS_PER_FRAME == 0, f"Track {ti}[{mi}] start no multiplo de frame: {st}"
            assert du % TICKS_PER_FRAME == 0 and du > 0, f"Track {ti}[{mi}] dur invalida: {du}"
            assert st >= prev_end, f"Track {ti}[{mi}] solape ({t2s(st):.2f}s < {t2s(prev_end):.2f}s)"
            if ti == 2 and mi > 0:
                assert st == prev_end, f"Track 2 hueco en clip {mi}: {st} != {prev_end}"
            prev_end = st + du
            assert prev_end <= video_end_ticks + TICKS_PER_FRAME, f"Track {ti} desborda fin de video"

    t2m = sorted(tracks[2]["medias"], key=lambda m: m["start"])
    assert t2m[0]["start"] == 0, f"Track 2 no arranca en 0: {t2m[0]['start']}"
    assert t2m[-1]["start"] + t2m[-1]["duration"] == video_end_ticks

    min_margin = s2t(0.28)
    for ti in (3, 4):
        for m in tracks[ti]["medias"]:
            st, en = m["start"], m["start"] + m["duration"]
            ok = any(p["start"] + min_margin <= st and en <= p["start"] + p["duration"] - min_margin for p in t2m)
            assert ok, f"Track {ti} '{m['attributes'].get('ident')}' [{t2s(st):.2f}..{t2s(en):.2f}] fuera/cerca borde de Track 2"


def generate_word_audit(tracks: list[dict]) -> None:
    words_data = json.loads(SCRIBE_WORDS_JSON.read_text(encoding="utf-8"))
    words = [w for w in words_data.get("words", []) if w.get("type") == "word"]
    lines = ["# Auditoria Semantica Scribe <-> Callouts (Memoria Persistente L0-L3 ES)", ""]
    for ti in (3, 4):
        lines.append(f"## Track {ti} ({len(tracks[ti]['medias'])} elementos)")
        for m in tracks[ti]["medias"]:
            s0, s1 = t2s(m["start"]), t2s(m["start"] + m["duration"])
            spoken = [w["text"] for w in words if (w["start"] + INTRO_S) >= s0 - 0.15 and (w["end"] + INTRO_S) <= s1 + 0.15]
            lines.append(f"- [{s0:7.2f}..{s1:7.2f}] {m['attributes'].get('ident')} -> {' '.join(spoken[:28])}")
        lines.append("")
    OUT_WORD_AUDIT.write_text("\n".join(lines), encoding="utf-8")
    print(f"[AUDIT TXT] {OUT_WORD_AUDIT.name} escrito ({sum(len(tracks[ti]['medias']) for ti in (3, 4))} callouts)")


def cam_callout_to_rect(m: dict) -> list[int]:
    p, d = m["parameters"], m["def"]
    cx = p["translation0"] + 1920.0
    cy = 1080.0 - p["translation1"]
    bw = d["width"] * p.get("scale0", 1.0)
    bh = d["height"] * p.get("scale1", 1.0)
    return [int(round(cx - bw / 2)), int(round(cy - bh / 2)), int(round(cx + bw / 2)), int(round(cy + bh / 2))]


def render_proof_sheets(tracks: list[dict], src_by_id: dict[int, str]) -> None:
    t2m = tracks[2]["medias"]
    c3, c4 = tracks[3]["medias"], tracks[4]["medias"]
    font_b = ImageFont.truetype("C:/Windows/Fonts/consolab.ttf", 22)
    font_s = ImageFont.truetype("C:/Windows/Fonts/consolab.ttf", 14)

    def clip_src_id(clip: dict) -> int:
        return clip["video"]["src"] if clip.get("_type") == "UnifiedMedia" else clip["src"]

    def draw_callout_overlay(dr: ImageDraw.ImageDraw, c: dict, sx: float, sy: float, cw: int) -> None:
        r4k = cam_callout_to_rect(c)
        rx1, ry1, rx2, ry2 = [int(round(r4k[0] * sx)), int(round(r4k[1] * sy)), int(round(r4k[2] * sx)), int(round(r4k[3] * sy))]
        if c["def"].get("kind") == "TypeWinSVG":
            col = tuple(int(round(255 * c["def"][k])) for k in ("borderColorRed", "borderColorGreen", "borderColorBlue"))
            dr.rectangle([rx1, ry1, rx2, ry2], outline=col, width=4)
            dr.rectangle([rx1, max(0, ry1 - 20), min(cw, rx1 + 430), ry1], fill=(10, 14, 20))
            dr.text((rx1 + 4, max(0, ry1 - 18)), c["attributes"]["ident"][:46], fill=col, font=font_s)
        else:
            dr.rectangle([rx1, ry1, rx2, ry2], outline=(83, 246, 250), fill=(16, 24, 34), width=3)
            dr.text((rx1 + 10, ry1 + 10), c["def"]["text"].replace("\r", "\n"), fill=(83, 246, 250), font=font_s)

    def make_slide_tile(clip: dict) -> Image.Image:
        fname = src_by_id[clip_src_id(clip)]
        with Image.open(CAM_DIR / fname) as im:
            cw, ch = 1280, 720
            tile = im.convert("RGB").resize((cw, ch), Image.Resampling.LANCZOS)
        dr = ImageDraw.Draw(tile)
        sx, sy = cw / float(W), ch / float(H)
        st0, en0 = clip["start"], clip["start"] + clip["duration"]
        for c in c3 + c4:
            cst, cen = c["start"], c["start"] + c["duration"]
            if cen <= st0 or cst >= en0:
                continue
            draw_callout_overlay(dr, c, sx, sy, cw)
        dr.rectangle([0, 0, 620, 30], fill=(0, 0, 0))
        dr.text((8, 4), f"{fname[:36]} [{t2s(st0):.1f}-{t2s(en0):.1f}s]", fill=(80, 240, 190), font=font_b)
        return tile

    def make_lab_tiles(clip: dict) -> list[Image.Image]:
        fname = src_by_id[clip_src_id(clip)]
        fpath = CAM_DIR / fname
        st0, en0 = clip["start"], clip["start"] + clip["duration"]
        m_off_s = t2s(clip.get("mediaStart", 0))
        child_calls = [c for c in c3 if c["start"] >= st0 and (c["start"] + c["duration"]) <= en0]
        if not child_calls:
            child_calls = [None]
        tiles: list[Image.Image] = []
        cap = cv2.VideoCapture(str(fpath))
        cw, ch = 1280, 720
        sx, sy = cw / float(W), ch / float(H)
        for c in child_calls:
            if c is None:
                rel_clip_s = t2s(clip["duration"]) * 0.45
                lbl = f"{fname} [{t2s(st0):.1f}-{t2s(en0):.1f}s]"
            else:
                mid_abs = (c["start"] + c["start"] + c["duration"]) / 2.0
                rel_clip_s = max(0.10, t2s(int(mid_abs - st0)))
                lbl = f"{fname} m={m_off_s+rel_clip_s:.1f}s | {c['attributes']['ident'][:34]}"
            cap.set(cv2.CAP_PROP_POS_MSEC, (m_off_s + rel_clip_s) * 1000.0)
            ok, fr = cap.read()
            assert ok, f"Fallo leyendo frame prueba {fname} @ m={m_off_s+rel_clip_s:.2f}s"
            im = Image.fromarray(cv2.cvtColor(fr, cv2.COLOR_BGR2RGB))
            tile = im.resize((cw, ch), Image.Resampling.LANCZOS)
            dr = ImageDraw.Draw(tile)
            for ov in (c3 + c4):
                if c is not None and ov["start"] <= (c["start"] + c["duration"] // 2) <= (ov["start"] + ov["duration"]):
                    draw_callout_overlay(dr, ov, sx, sy, cw)
            dr.rectangle([0, 0, 860, 30], fill=(0, 0, 0))
            dr.text((8, 4), lbl, fill=(80, 240, 190), font=font_b)
            tiles.append(tile)
        cap.release()
        return tiles

    slide_clips = [m for m in t2m if src_by_id[clip_src_id(m)].startswith("slide_")]
    lab_clips = [m for m in t2m if not src_by_id[clip_src_id(m)].startswith("slide_")]

    def save_tiles(tiles: list[Image.Image], out_path: pathlib.Path, cols: int = 2) -> None:
        cw, ch = 1280, 720
        rows = math.ceil(len(tiles) / cols)
        canvas = Image.new("RGB", (cw * cols, ch * rows), (12, 16, 22))
        for idx, tile in enumerate(tiles):
            canvas.paste(tile, ((idx % cols) * cw, (idx // cols) * ch))
        canvas.save(out_path, quality=88)
        print(f"[PROOF] {out_path.name}: {len(tiles)} paneles")

    save_tiles([make_slide_tile(cl) for cl in slide_clips[:15]], OUT_PROOF_SLIDES_1, cols=2)
    save_tiles([make_slide_tile(cl) for cl in slide_clips[15:]], OUT_PROOF_SLIDES_2, cols=2)
    lab_tiles = [t for cl in lab_clips for t in make_lab_tiles(cl)]
    save_tiles(lab_tiles, OUT_PROOF_LABS, cols=2)


def main() -> None:
    parser = argparse.ArgumentParser(description="Construir proyecto Camtasia 10.0 001MemoriaPersistente.tscproj (ES).")
    parser.add_argument("--dry-run-proofs", action="store_true", help="Valida pistas y genera hojas de prueba sin escribir el .tscproj.")
    parser.add_argument("--force-reset-from-scratch", action="store_true", help="Requerido para escribir/reemplazar .tscproj desde cero.")
    args = parser.parse_args()

    if not args.dry_run_proofs:
        if OUT_TSCPROJ.exists() and not args.force_reset_from_scratch:
            raise SystemExit(
                f"BLOQUEO DE SEGURIDAD: {OUT_TSCPROJ} ya existe y puede contener ediciones manuales "
                "del usuario en Camtasia. Queda prohibido regenerarlo desde cero; aplica parches JSON quirurgicos."
            )
        if not args.force_reset_from_scratch:
            print("[ABORTADO] Ejecuta primero --dry-run-proofs y luego pasa --force-reset-from-scratch para escritura unica.")
            sys.exit(2)

    assert TEMPLATE_TSCPROJ.exists(), f"Falta plantilla Camtasia: {TEMPLATE_TSCPROJ}"
    assert SVG_PATH.exists(), f"Falta SVG Camtasia: {SVG_PATH}"
    tpl = json.loads(TEMPLATE_TSCPROJ.read_text(encoding="utf-8"))
    svg_xml = SVG_PATH.read_text(encoding="utf-8")
    slide_colors = json.loads(COLORS_JSON.read_text(encoding="utf-8"))
    dom = json.loads(LAB_DOM_JSON.read_text(encoding="utf-8"))
    img_cache: dict[str, np.ndarray] = {}

    vo_info = probe_media(CAM_DIR / AUDIO_VO)
    vo_dur_s = vo_info["duration"]
    vo_ticks = int(math.floor(vo_dur_s * FPS)) * TICKS_PER_FRAME
    intro_ticks = s2t(INTRO_S)
    video_end_ticks = int(round((INTRO_S + vo_dur_s + TAIL_S) * FPS)) * TICKS_PER_FRAME
    video_end_s = t2s(video_end_ticks)

    t2_plan = build_track2_slots(video_end_s)
    ids = IdGen(1)
    unique_media = [AUDIO_VO, AUDIO_BG]
    seen = set(unique_media)
    for _, fname, _, _, _ in t2_plan:
        if fname not in seen:
            unique_media.append(fname)
            seen.add(fname)

    source_bin, meta_map = build_source_bin(ids, unique_media)
    src_by_id = {m["id"]: name for name, m in meta_map.items()}

    # Track 0: Nuclear Baby.mp3 (intro musical limpia heredada de 003 + bucles continuos sin huecos + fade-out final 1.40s)
    t0_medias: list[dict] = []
    bg_meta = meta_map[AUDIO_BG]
    bg_src_id = bg_meta["id"]
    nb_max_end_t = s2t(bg_meta["duration"] - 0.03)

    es_t0 = copy.deepcopy(tpl["timeline"]["sceneTrack"]["scenes"][0]["csml"]["tracks"][0]["medias"])
    for i, m in enumerate(es_t0):
        m["id"] = ids.next()
        m["src"] = bg_src_id
        if i >= 1:
            m["parameters"] = {}
        if m["mediaStart"] + m["duration"] > nb_max_end_t:
            clamped_dur = ((nb_max_end_t - m["mediaStart"]) // TICKS_PER_FRAME) * TICKS_PER_FRAME
            m["duration"] = clamped_dur
            m["mediaDuration"] = clamped_dur
        t0_medias.append(m)

    nb_full_t = int(math.floor((bg_meta["duration"] - 0.05) * FPS)) * TICKS_PER_FRAME
    cur_t = t0_medias[-1]["start"] + t0_medias[-1]["duration"]
    while cur_t < video_end_ticks:
        rem = video_end_ticks - cur_t
        seg_dur = min(nb_full_t, rem)
        is_last = (cur_t + seg_dur) >= video_end_ticks
        params: dict[str, Any] = {}
        if is_last:
            fade_t = min(FADE_OUT_TICKS, max(TICKS_PER_FRAME, seg_dur // 3))
            params = {
                "volume": {
                    "type": "double",
                    "keyframes": [
                        {"endTime": 0, "time": 0, "value": 1.0, "duration": 0},
                        {"endTime": seg_dur - fade_t, "time": seg_dur - fade_t, "value": 1.0, "duration": 0},
                        {"endTime": seg_dur, "time": seg_dur, "value": 0.0, "duration": 0},
                    ],
                }
            }
        t0_medias.append(
            {
                "id": ids.next(),
                "_type": "AMFile",
                "src": bg_src_id,
                "trackNumber": 0,
                "attributes": {"ident": "Nuclear Baby", "gain": 1.0, "mixToMono": False, "loudnessNormalization": True, "sourceFileOffset": 0},
                "channelNumber": "0,1",
                "parameters": params,
                "effects": [],
                "start": cur_t,
                "duration": seg_dur,
                "mediaStart": 0,
                "mediaDuration": seg_dur,
                "scalar": 1,
                "metadata": {"audiateLinkedSession": "", "clipSpeedAttribute": {"type": "bool", "value": False}, "colorAttribute": {"type": "color", "value": [0, 0, 0, 0]}},
                "animationTracks": {},
            }
        )
        cur_t += seg_dur

    # Track 1: Locucion Jesus Conde (WinCompression + Emphasize 0.98)
    vo_meta = meta_map[AUDIO_VO]
    vo_ch = "0" if vo_meta["channels"] == 1 else "0,1"
    t1_medias = [
        {
            "id": ids.next(),
            "_type": "AMFile",
            "src": vo_meta["id"],
            "trackNumber": 0,
            "attributes": {"ident": pathlib.Path(AUDIO_VO).stem, "gain": 1.0, "mixToMono": False, "loudnessNormalization": True, "sourceFileOffset": 0},
            "channelNumber": vo_ch,
            "parameters": {},
            "effects": [
                {
                    "effectName": "WinCompression",
                    "bypassed": False,
                    "category": "categoryAudioEffects",
                    "parameters": {"ratio": 10.0, "threshold": -20.0, "gain": 9.0, "attack": 0.0, "release": 3500.0, "preset": 1},
                    "metadata": {"presetName": "Compresión de audio"},
                },
                {
                    "effectName": "Emphasize",
                    "bypassed": False,
                    "category": "categoryAudioEffects",
                    "parameters": {"emphasizeAmount": 0.98, "emphasizeRampPosition": 0, "emphasizeRampInTime": 705600000, "emphasizeRampOutTime": 705600000},
                    "metadata": {"default-Emphasize_emphasizeAmount": {"type": "double", "value": 0.8}, "presetName": "Enfatizar"},
                },
            ],
            "start": intro_ticks,
            "duration": vo_ticks,
            "mediaStart": 0,
            "mediaDuration": vo_ticks,
            "scalar": 1,
            "metadata": {"audiateLinkedSession": "", "clipSpeedAttribute": {"type": "bool", "value": False}, "colorAttribute": {"type": "color", "value": [0, 0, 0, 0]}},
            "animationTracks": {},
        }
    ]

    # Track 2: 36 Segmentos Continuos 4K + GradientWipe en uniones con IMFile
    t2_medias: list[dict] = []
    t2_trans: list[dict] = []
    for _, fname, s0, s1, ms0 in t2_plan:
        st, en, mst = s2t(s0), s2t(s1), s2t(ms0)
        dur = en - st
        m_info = meta_map[fname]
        if m_info["type"] == "png":
            item = {
                "id": ids.next(),
                "_type": "IMFile",
                "src": m_info["id"],
                "trackNumber": 0,
                "trimStartSum": 0,
                "attributes": {"ident": pathlib.Path(fname).stem},
                "parameters": {"geometryCrop0": 0.0, "geometryCrop1": 0.0, "geometryCrop2": 0.0, "geometryCrop3": 0.0},
                "effects": [],
                "start": st,
                "duration": dur,
                "mediaStart": 0,
                "mediaDuration": 1,
                "scalar": 1,
                "metadata": {"audiateLinkedSession": "", "clipSpeedAttribute": {"type": "bool", "value": False}, "colorAttribute": {"type": "color", "value": [0, 0, 0, 0]}},
                "animationTracks": {},
            }
        else:
            clip_max_ticks = int(math.floor(m_info["duration"] * FPS)) * TICKS_PER_FRAME
            assert mst + dur <= clip_max_ticks, f"Clip {fname} insuficiente: need {t2s(mst+dur):.2f}s > file {t2s(clip_max_ticks):.2f}s"
            item = {
                "id": ids.next(),
                "_type": "UnifiedMedia",
                "video": {
                    "id": ids.next(),
                    "_type": "VMFile",
                    "src": m_info["id"],
                    "trackNumber": 0,
                    "attributes": {"ident": pathlib.Path(fname).stem},
                    "parameters": {"geometryCrop0": 0.0, "geometryCrop1": 0.0, "geometryCrop2": 0.0, "geometryCrop3": 0.0},
                    "effects": [],
                    "start": st,
                    "duration": dur,
                    "mediaStart": mst,
                    "mediaDuration": dur,
                    "scalar": 1,
                    "animationTracks": {},
                },
                "audio": {
                    "id": ids.next(),
                    "_type": "AMFile",
                    "src": m_info["id"],
                    "trackNumber": 1,
                    "attributes": {"ident": "", "gain": 0.0, "mixToMono": False, "loudnessNormalization": True, "sourceFileOffset": 0},
                    "channelNumber": "0,1",
                    "parameters": {},
                    "effects": [],
                    "start": st,
                    "duration": dur,
                    "mediaStart": mst,
                    "mediaDuration": dur,
                    "scalar": 1,
                    "animationTracks": {},
                },
                "effects": [],
                "start": st,
                "duration": dur,
                "mediaStart": mst,
                "mediaDuration": dur,
                "scalar": 1,
                "metadata": {
                    "audiateLinkedSession": "",
                    "clipSpeedAttribute": {"type": "bool", "value": False},
                    "colorAttribute": {"type": "color", "value": [0, 0, 0, 0]},
                    "default-anchor0": {"type": "double", "value": 0.0},
                    "default-anchor1": {"type": "double", "value": 0.0},
                    "default-anchor2": {"type": "double", "value": 0.0},
                    "default-height": {"type": "double", "value": float(H)},
                    "default-rotation0": {"type": "double", "value": 0.0},
                    "default-rotation1": {"type": "double", "value": 0.0},
                    "default-rotation2": {"type": "double", "value": 0.0},
                    "default-scale0": {"type": "double", "value": 1.0},
                    "default-scale1": {"type": "double", "value": 1.0},
                    "default-scale2": {"type": "double", "value": 1.0},
                    "default-shear0": {"type": "double", "value": 0.0},
                    "default-shear1": {"type": "double", "value": 0.0},
                    "default-shear2": {"type": "double", "value": 0.0},
                    "default-translation0": {"type": "double", "value": 0.0},
                    "default-translation1": {"type": "double", "value": 0.0},
                    "default-translation2": {"type": "double", "value": 0.0},
                    "default-width": {"type": "double", "value": float(W)},
                },
            }
        t2_medias.append(item)

    for left_m, right_m in zip(t2_medias, t2_medias[1:]):
        if left_m["_type"] == "IMFile" or right_m["_type"] == "IMFile":
            t2_trans.append(make_gradient_wipe(left_id=left_m["id"], right_id=right_m["id"], dur=TRANS_WIPE_TICKS))

    # Track 3 & Track 4: Callouts Sincronizados + Colores Nativos Muestreados por PIL.Image
    t3_specs, t4_specs = build_callout_specs(dom, slide_colors, img_cache, video_end_s)
    t3_medias = [make_rect_callout(ids, svg_xml, lbl, s0, s1, rect, col, border_w=12.5) for (_, s0, s1, rect, col, lbl) in t3_specs]

    t4_medias: list[dict] = []
    t4_trans: list[dict] = []
    for item in t4_specs:
        if item[0] == "rect":
            _, _, s0, s1, rect, col, lbl = item
            t4_medias.append(make_rect_callout(ids, svg_xml, lbl, s0, s1, rect, col, border_w=10.5))
        else:
            _, _, s0, s1, txt, rect = item
            badge = make_text_badge(ids, txt, s0, s1, rect)
            t4_medias.append(badge)
            t4_trans.append(make_gradient_wipe(right_id=badge["id"], dur=TRANS_WIPE_TICKS))
            t4_trans.append(make_gradient_wipe(left_id=badge["id"], dur=TRANS_WIPE_TICKS))

    tracks = [
        {"trackIndex": 0, "medias": t0_medias, "parameters": {}},
        {"trackIndex": 1, "medias": t1_medias, "parameters": {}},
        {"trackIndex": 2, "medias": t2_medias, "transitions": t2_trans, "parameters": {}},
        {"trackIndex": 3, "medias": t3_medias, "parameters": {}},
        {"trackIndex": 4, "medias": t4_medias, "transitions": t4_trans, "parameters": {}},
    ]

    validate_all_tracks(tracks, video_end_ticks, t2_plan)
    generate_word_audit(tracks)
    render_proof_sheets(tracks, src_by_id)

    if args.dry_run_proofs:
        print(
            f"[DRY-RUN OK] Validacion matematica y pruebas visuales OK "
            f"(dur={video_end_s:.2f}s, Track2={len(t2_medias)}, T3={len(t3_medias)}, T4={len(t4_medias)}). "
            f"NO se ha escrito {OUT_TSCPROJ.name}."
        )
        return

    project = copy.deepcopy(tpl)
    project["sourceBin"] = source_bin
    project["timeline"]["sceneTrack"]["scenes"][0]["csml"]["tracks"] = tracks
    project["timeline"]["trackAttributes"] = [
        {
            "ident": name,
            "audioMuted": False,
            "videoHidden": False,
            "magnetic": False,
            "matte": 0,
            "solo": False,
            "metadata": {"IsLocked": "False", "WinTrackHeight": "78"},
        }
        for name in [
            "Musica de Fondo",
            "Locucion Jesus Conde",
            "Visuales 4K + Laboratorio HTML",
            "Marcadores Primarios",
            "Detalles Secundarios y Repo",
        ]
    ]
    if "metadata" in project:
        project["metadata"]["Title"] = "001MemoriaPersistente"
        project["metadata"]["Language"] = "ESN"
        project["metadata"]["ProjectThumbnail"] = ""

    CAM_DIR.mkdir(parents=True, exist_ok=True)
    OUT_TSCPROJ.write_text(json.dumps(project, indent=2, ensure_ascii=False), encoding="utf-8")
    print(
        f"[BUILD OK] {OUT_TSCPROJ} escrito ({OUT_TSCPROJ.stat().st_size:,} bytes) | "
        f"dur={video_end_s:.2f}s | Track2={len(t2_medias)} ({len(t2_trans)} wipes) | "
        f"T3={len(t3_medias)} | T4={len(t4_medias)}"
    )


if __name__ == "__main__":
    main()
