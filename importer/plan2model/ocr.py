"""Odczyt wymiarów i powierzchni z rzutu (Tesseract)."""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass

import cv2
import numpy as np

UPSCALE = 2  # Tesseract lepiej czyta małe cyfry po powiększeniu (sprawdzone na test1: 2× lepsze niż 3–4×)
MIN_CONFIDENCE = 50

_CM = re.compile(r"^\d{2,4}$")  # 335 → 3,35 m (wymiary w cm, typowe na rzutach z gotowych projektów)
_M = re.compile(r"^\d{1,2}[,.]\d{1,2}$")  # 3,35 → 3,35 m
_AREA = re.compile(r"^(\d{1,3}[,.]\d{1,2})m[²2]?$")  # 12,45m² / 12,45m2


@dataclass
class Token:
    """Liczba odczytana z rzutu, położenie w pikselach oryginalnego obrazu."""

    text: str
    meters: float  # wymiar w metrach albo powierzchnia w m²
    is_area: bool
    x: float
    y: float
    vertical: bool  # napis obrócony o 90°
    conf: float


def available() -> bool:
    return shutil.which("tesseract") is not None


def read_tokens(img_bgr: np.ndarray) -> list[Token]:
    """Odczytuje liczby z rzutu: napisy poziome i pionowe (obrócone o 90°)."""
    import pytesseract

    h, w = img_bgr.shape[:2]
    big = cv2.resize(img_bgr, None, fx=UPSCALE, fy=UPSCALE, interpolation=cv2.INTER_CUBIC)
    tokens: list[Token] = []
    for vertical, im in ((False, big), (True, cv2.rotate(big, cv2.ROTATE_90_CLOCKWISE))):
        data = pytesseract.image_to_data(
            im, lang="pol", config="--psm 11", output_type=pytesseract.Output.DICT
        )
        words = [
            (data["text"][i].strip(), float(data["conf"][i]), data["left"][i] + data["width"][i] / 2,
             data["top"][i] + data["height"][i] / 2)
            for i in range(len(data["text"]))
            if data["text"][i].strip()
        ]
        for j, (text, conf, cx, cy) in enumerate(words):
            if conf < MIN_CONFIDENCE:
                continue
            # „12,45 m²” bywa rozbite na dwa słowa – sklejamy z następnym, jeśli to jednostka.
            nxt = words[j + 1][0] if j + 1 < len(words) else ""
            joined = text + nxt if re.fullmatch(r"m[²2]?", nxt) else text
            parsed = _parse(joined)
            if parsed is None:
                continue
            value, is_area = parsed
            if vertical:  # punkt z obrazu obróconego zgodnie ze wskazówkami → oryginał
                x, y = cy / UPSCALE, h - 1 - cx / UPSCALE
            else:
                x, y = cx / UPSCALE, cy / UPSCALE
            tokens.append(Token(text, value, is_area, x, y, vertical, conf))
    return _dedupe(tokens)


def _parse(text: str) -> tuple[float, bool] | None:
    text = text.replace(" ", "")
    if m := _AREA.match(text):
        return float(m.group(1).replace(",", ".")), True
    if _CM.match(text):
        return int(text) / 100, False
    if _M.match(text):
        return float(text.replace(",", ".")), False
    return None


def _dedupe(tokens: list[Token], radius: float = 6) -> list[Token]:
    """Ta sama liczba odczytana dwa razy w tym samym miejscu liczy się raz."""
    out: list[Token] = []
    for t in sorted(tokens, key=lambda t: -t.conf):
        if not any(o.text == t.text and abs(o.x - t.x) < radius and abs(o.y - t.y) < radius for o in out):
            out.append(t)
    return out
