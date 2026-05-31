"""
Identifies and ranks Pokémon card back images from a list of eBay listing URLs.

Detection:  image must pass ALL of:
              - blue ratio >= _BLUE_RATIO_MIN   (card-back blue dominant)
              - yellow ratio >= _YELLOW_RATIO_MIN (Pokémon logo yellow present)
              - yellow ratio <= _YELLOW_RATIO_MAX (card fronts with lots of yellow art rejected)
Ranking:    score 0–3 based on how much of the card is visible.
              3 = full card + Pokéball red confirmed
              2 = full card (yellow text in both top and bottom thirds)
              1 = partial card (yellow text in one third only)
              0 = very partial (back detected but text barely visible)
Tiebreaker: within the same score, highest blue:yellow ratio wins — card backs are
            blue-dominant relative to their yellow; fronts that slip through tend to
            have more yellow relative to blue.
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
_YELLOW_S_MIN, _YELLOW_V_MIN  = 65, 80   # relaxed from (80,100) for dim/dark photos

# Detection thresholds (fraction of total pixels)
_BLUE_RATIO_MIN   = 0.04   # relaxed from 0.05 — catches cards with large non-blue backgrounds
_YELLOW_RATIO_MIN = 0.005  # ≥0.5 % must be Pokémon yellow
_YELLOW_RATIO_MAX = 0.20   # >20 % yellow means card-front artwork, not a back

# Ranking threshold: yellow pixels needed per zone to count as "text present"
_YELLOW_ZONE_RATIO = 0.022  # 2.2 % of the zone

# Pokéball orange-red bonus: H wraps near 0 in Pillow HSV
_RED_H_MAX = 12
_RED_H_MIN = 243
_RED_S_MIN = 70
_RED_V_MIN = 70
_RED_RATIO_MIN = 0.0003   # very low — just needs any Pokéball presence; used for +1 score boost

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
    Return (is_back, rank_score, tiebreak) for a single already-resized HSV image.

    Score:
        3  full card + Pokéball red confirmed
        2  full card (both yellow text blocks present)
        1  partial (one text block)
        0  very partial (back detected, text barely visible)
    tiebreak = blue_ratio / yellow_ratio — higher means more blue-dominant relative to yellow,
    which is characteristic of card backs vs card fronts.
    """
    arr = np.array(img)
    total = arr.shape[0] * arr.shape[1]
    if total == 0:
        return False, 0, 0.0

    blue_mask   = _mask(arr, _BLUE_H_LO,   _BLUE_H_HI,   _BLUE_S_MIN,   _BLUE_V_MIN)
    yellow_mask = _mask(arr, _YELLOW_H_LO, _YELLOW_H_HI, _YELLOW_S_MIN, _YELLOW_V_MIN)

    blue_ratio   = blue_mask.sum() / total
    yellow_ratio = yellow_mask.sum() / total

    if blue_ratio < _BLUE_RATIO_MIN:
        return False, 0, 0.0
    if yellow_ratio < _YELLOW_RATIO_MIN:
        return False, 0, 0.0
    if yellow_ratio > _YELLOW_RATIO_MAX:
        return False, 0, 0.0

    # Check whether the Pokémon text appears in the top and/or bottom thirds.
    h = arr.shape[0]
    third = max(h // 3, 1)

    top_zone    = yellow_mask[:third, :]
    bottom_zone = yellow_mask[h - third:, :]

    has_top    = top_zone.sum()    / top_zone.size    >= _YELLOW_ZONE_RATIO
    has_bottom = bottom_zone.sum() / bottom_zone.size >= _YELLOW_ZONE_RATIO

    zone_score = int(has_top) + int(has_bottom)

    # Pokéball red bonus: gives backs a score edge over fronts with incidental blue+yellow
    h_arr, s_arr, v_arr = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
    red_mask = ((h_arr <= _RED_H_MAX) | (h_arr >= _RED_H_MIN)) & (s_arr >= _RED_S_MIN) & (v_arr >= _RED_V_MIN)
    has_red = red_mask.sum() / total >= _RED_RATIO_MIN

    tiebreak = blue_ratio / max(yellow_ratio, 1e-4)
    return True, zone_score + int(has_red), tiebreak


def find_best_back(image_urls: list[str]) -> tuple[str | None, int]:
    """
    Scan a list of eBay image URLs and return the best card back.

    Returns:
        (url, score)  — url of the best back found and its completeness score.
        (None, -1)    — if no image in the list was identified as a card back.

    Score meaning:
        3  full card visible + Pokéball red confirmed
        2  full card visible (both Pokémon text blocks present)
        1  partial view (one text block visible — still useful for condition)
        0  very partial (back detected but text barely visible)
       -1  no back found
    """
    best_url      = None
    best_score    = -1
    best_tiebreak = 0.0

    for url in image_urls:
        img = _fetch(url)
        if img is None:
            continue
        is_back, score, tiebreak = _score(img)
        if is_back and (score > best_score or (score == best_score and tiebreak > best_tiebreak)):
            best_score    = score
            best_tiebreak = tiebreak
            best_url      = url

    return best_url, best_score
