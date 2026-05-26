"""
Identifies and ranks Pokémon card back images from a list of eBay listing URLs.

Detection:  image must have enough card-back blue AND Pokémon-logo yellow.
Ranking:    score 0–2 based on how much of the card is visible.
              2 = full card (yellow text in both top and bottom thirds)
              1 = partial card (yellow text in one third only)
              0 = very partial (back detected but text barely visible)
"""

import io

import numpy as np
import requests
from PIL import Image

# ---------------------------------------------------------------------------
# Colour thresholds (Pillow HSV: H 0-255 maps to 0-360°, S/V 0-255)
# ---------------------------------------------------------------------------

# Card-back blue  ~200-230° real → ~142-163 Pillow
_BLUE_H_LO,  _BLUE_H_HI  = 105, 185
_BLUE_S_MIN, _BLUE_V_MIN  =  40,  30

# Pokémon logo yellow-gold  ~35-55° real → ~25-39 Pillow
_YELLOW_H_LO,  _YELLOW_H_HI  = 15, 55
_YELLOW_S_MIN, _YELLOW_V_MIN  = 80, 100

# Detection thresholds (fraction of total pixels)
_BLUE_RATIO_MIN   = 0.08   # ≥8 % of image must be card-back blue
_YELLOW_RATIO_MIN = 0.005  # ≥0.5 % must be Pokémon yellow

# Ranking threshold: yellow pixels needed per zone to count as "text present"
# Expressed as a fraction of that zone's total pixels
_YELLOW_ZONE_RATIO = 0.022  # 2.2 % of the zone

_THUMB = (150, 200)   # resize target keeps memory/CPU low; preserves portrait AR

_HEADERS = {'User-Agent': 'Mozilla/5.0'}


def _fetch(url: str) -> Image.Image | None:
    try:
        r = requests.get(url, timeout=10, headers=_HEADERS)
        r.raise_for_status()
        img = Image.open(io.BytesIO(r.content)).convert('RGB')
        img.thumbnail(_THUMB, Image.LANCZOS)
        return img.convert('HSV')
    except Exception:
        return None


def _mask(arr: np.ndarray, h_lo: int, h_hi: int, s_min: int, v_min: int) -> np.ndarray:
    h, s, v = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
    return (h >= h_lo) & (h <= h_hi) & (s >= s_min) & (v >= v_min)


def _score(img: Image.Image) -> tuple[bool, int, float]:
    """
    Return (is_back, rank_score, yellow_ratio) for a single already-resized HSV image.
    yellow_ratio is used as a tiebreaker: a full card with both text blocks visible
    has significantly more yellow pixels than any corner or partial view.
    """
    arr = np.array(img)
    total = arr.shape[0] * arr.shape[1]
    if total == 0:
        return False, 0, 0.0

    blue_mask   = _mask(arr, _BLUE_H_LO,   _BLUE_H_HI,   _BLUE_S_MIN,   _BLUE_V_MIN)
    yellow_mask = _mask(arr, _YELLOW_H_LO, _YELLOW_H_HI, _YELLOW_S_MIN, _YELLOW_V_MIN)

    yellow_ratio = yellow_mask.sum() / total

    if blue_mask.sum() / total < _BLUE_RATIO_MIN:
        return False, 0, 0.0
    if yellow_ratio < _YELLOW_RATIO_MIN:
        return False, 0, 0.0

    # Check whether the Pokémon text appears in the top and/or bottom thirds.
    # A full card shows both; a half/corner crop shows only one.
    h = arr.shape[0]
    third = max(h // 3, 1)

    top_zone    = yellow_mask[:third, :]
    bottom_zone = yellow_mask[h - third:, :]

    has_top    = top_zone.sum()    / top_zone.size    >= _YELLOW_ZONE_RATIO
    has_bottom = bottom_zone.sum() / bottom_zone.size >= _YELLOW_ZONE_RATIO

    return True, int(has_top) + int(has_bottom), yellow_ratio


def find_best_back(image_urls: list[str]) -> tuple[str | None, int]:
    """
    Scan a list of eBay image URLs and return the best card back.

    Returns:
        (url, score)  — url of the best back found and its completeness score.
        (None, -1)    — if no image in the list was identified as a card back.

    Score meaning:
        2  full card visible (both Pokémon text blocks present)
        1  partial view (one text block visible — still useful for condition)
        0  very partial (back detected but text barely visible)
       -1  no back found
    """
    best_url      = None
    best_score    = -1
    best_yellow   = 0.0

    for url in image_urls:
        img = _fetch(url)
        if img is None:
            continue
        is_back, score, yellow_ratio = _score(img)
        if is_back and (score > best_score or (score == best_score and yellow_ratio > best_yellow)):
            best_score  = score
            best_yellow = yellow_ratio
            best_url    = url

    if best_url is None:
        return None, -1
    return best_url, best_score
