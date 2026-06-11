"""
Identifies and ranks card back images from a list of eBay listing URLs.

Pokemon detection:
    blue ratio >= _BLUE_RATIO_MIN   (card-back blue dominant)
    yellow ratio >= _YELLOW_RATIO_MIN (Pokémon logo yellow present)
    yellow ratio <= _YELLOW_RATIO_MAX (card fronts with lots of yellow art rejected)
    red ratio <= _RED_RATIO_MAX       (rejects fire/fighting card fronts)

MTG detection:
    brown ratio >= _MTG_BROWN_RATIO_MIN  (central tan/leather oval)
    teal ratio >= _MTG_TEAL_RATIO_MIN    ("Magic" logo + "Deckmaster" banner)
    teal ratio <= _MTG_TEAL_RATIO_MAX    (reject blue-art card fronts)

Scoring (both games, 0–3):
    3  full card: both text zones (top + bottom) confirmed + prominent card body
    2  both text zones confirmed, or body + one zone
    1  one text zone confirmed
    0  back detected but text barely visible
"""

import io

import numpy as np
import requests
from PIL import Image

# ---------------------------------------------------------------------------
# Shared
# ---------------------------------------------------------------------------

_THUMB = (150, 200)
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


# ---------------------------------------------------------------------------
# Pokemon back detection
# (Pillow HSV: H 0-255 maps to 0-360°, S/V 0-255)
# ---------------------------------------------------------------------------

# Card-back blue  ~200-230° real → ~142-163 Pillow
_BLUE_H_LO,  _BLUE_H_HI  = 105, 185
_BLUE_S_MIN, _BLUE_V_MIN  =  40,  30

# Pokémon logo yellow-gold  ~35-55° real → ~25-39 Pillow
_YELLOW_H_LO,  _YELLOW_H_HI  = 15, 55
_YELLOW_S_MIN, _YELLOW_V_MIN  = 65, 80

_BLUE_RATIO_MIN   = 0.03
_YELLOW_RATIO_MIN = 0.005
_YELLOW_RATIO_MAX = 0.80

_YELLOW_ZONE_RATIO = 0.022

_RED_H_MAX = 12
_RED_H_MIN = 243
_RED_S_MIN = 70
_RED_V_MIN = 70
_RED_RATIO_MIN = 0.003
_RED_RATIO_MAX = 0.07


def _score_pokemon(img: Image.Image) -> tuple[bool, int, float]:
    """
    Return (is_back, rank_score, tiebreak) for a Pokemon card back image.

    Score:
        3  full card + Pokéball red confirmed
        2  full card (both yellow text blocks present)
        1  partial (one text block)
        0  very partial (back detected, text barely visible)
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

    h_arr, s_arr, v_arr = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
    red_mask  = ((h_arr <= _RED_H_MAX) | (h_arr >= _RED_H_MIN)) & (s_arr >= _RED_S_MIN) & (v_arr >= _RED_V_MIN)
    red_ratio = red_mask.sum() / total

    if red_ratio > _RED_RATIO_MAX:
        return False, 0, 0.0

    h = arr.shape[0]
    third = max(h // 3, 1)

    top_zone    = yellow_mask[:third, :]
    bottom_zone = yellow_mask[h - third:, :]

    top_ratio    = top_zone.sum()    / top_zone.size
    bottom_ratio = bottom_zone.sum() / bottom_zone.size

    has_top    = top_ratio    >= _YELLOW_ZONE_RATIO
    has_bottom = bottom_ratio >= _YELLOW_ZONE_RATIO
    zone_score = int(has_top) + int(has_bottom)
    has_red    = red_ratio >= _RED_RATIO_MIN

    tiebreak = (top_ratio + bottom_ratio) + red_ratio * 10.0 + blue_ratio * 0.5
    return True, zone_score + int(has_red), tiebreak


# ---------------------------------------------------------------------------
# MTG back detection
# ---------------------------------------------------------------------------

# Central tan/leather oval: H ~20-40° real → ~14-28 Pillow
_MTG_BROWN_H_LO, _MTG_BROWN_H_HI = 12, 28
_MTG_BROWN_S_MIN = 60
_MTG_BROWN_V_MIN = 90
_MTG_BROWN_V_MAX = 215   # exclude highlights/near-white pixels

# "Magic" logo + "Deckmaster" banner teal: H ~170-225° real → ~120-160 Pillow
_MTG_TEAL_H_LO, _MTG_TEAL_H_HI = 120, 160
_MTG_TEAL_S_MIN = 50
_MTG_TEAL_V_MIN = 50

_MTG_BROWN_RATIO_MIN  = 0.10  # central oval must be visible
_MTG_TEAL_RATIO_MIN   = 0.005 # some logo/banner text must be present
_MTG_TEAL_RATIO_MAX   = 0.60  # reject blue-art card fronts

_MTG_TEAL_ZONE_RATIO  = 0.010 # 1% of zone must be teal to count
_MTG_BROWN_RATIO_FULL = 0.20  # brown fraction that indicates full-card view


def _score_mtg(img: Image.Image) -> tuple[bool, int, float]:
    """
    Return (is_back, rank_score, tiebreak) for an MTG card back image.

    Score:
        3  full card: both zones (Magic logo top + Deckmaster bottom) + oval prominent
        2  both zones present, or one zone + oval prominent
        1  one zone only
        0  back detected but minimal zone coverage
    """
    arr = np.array(img)
    total = arr.shape[0] * arr.shape[1]
    if total == 0:
        return False, 0, 0.0

    h_ch, s_ch, v_ch = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]

    brown_mask = (
        (h_ch >= _MTG_BROWN_H_LO) & (h_ch <= _MTG_BROWN_H_HI) &
        (s_ch >= _MTG_BROWN_S_MIN) &
        (v_ch >= _MTG_BROWN_V_MIN) & (v_ch <= _MTG_BROWN_V_MAX)
    )
    teal_mask = _mask(arr, _MTG_TEAL_H_LO, _MTG_TEAL_H_HI, _MTG_TEAL_S_MIN, _MTG_TEAL_V_MIN)

    brown_ratio = brown_mask.sum() / total
    teal_ratio  = teal_mask.sum()  / total

    if brown_ratio < _MTG_BROWN_RATIO_MIN:
        return False, 0, 0.0
    if teal_ratio < _MTG_TEAL_RATIO_MIN:
        return False, 0, 0.0
    if teal_ratio > _MTG_TEAL_RATIO_MAX:
        return False, 0, 0.0

    h_dim = arr.shape[0]
    third = max(h_dim // 3, 1)

    top_teal    = teal_mask[:third, :]
    bottom_teal = teal_mask[h_dim - third:, :]

    top_zone_ratio    = top_teal.sum()    / top_teal.size
    bottom_zone_ratio = bottom_teal.sum() / bottom_teal.size

    has_top    = top_zone_ratio    >= _MTG_TEAL_ZONE_RATIO
    has_bottom = bottom_zone_ratio >= _MTG_TEAL_ZONE_RATIO
    zone_score = int(has_top) + int(has_bottom)
    has_full_brown = brown_ratio >= _MTG_BROWN_RATIO_FULL

    # score = zone_score + has_full_brown → range 0–3
    score    = zone_score + int(has_full_brown)
    tiebreak = (top_zone_ratio + bottom_zone_ratio) + brown_ratio * 2.0 + teal_ratio * 5.0
    return True, score, tiebreak


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def find_best_back(image_urls: list[str], category: str = 'pokemon') -> tuple[str | None, int]:
    """
    Scan a list of eBay image URLs and return the best card back.

    Returns:
        (url, score)  — url of the best back found and its completeness score.
        (None, -1)    — if no image in the list was identified as a card back.

    Score meaning:
        3  full card visible (both logo areas) + body confirmed
        2  both logo zones present, or body + one zone
        1  partial view (one logo zone visible)
        0  very partial (back detected but text barely visible)
       -1  no back found
    """
    score_fn = _score_mtg if category == 'magic' else _score_pokemon

    best_url      = None
    best_score    = -1
    best_tiebreak = 0.0

    for url in image_urls:
        img = _fetch(url)
        if img is None:
            continue
        is_back, score, tiebreak = score_fn(img)
        if is_back and (score > best_score or (score == best_score and tiebreak > best_tiebreak)):
            best_score    = score
            best_tiebreak = tiebreak
            best_url      = url

    return best_url, best_score
