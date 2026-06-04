"""
Diagnostic: run each failing image through the card-back detection pipeline
and print the pixel stats so we can see exactly which threshold it fails.
"""

import csv
import io
import sys

import numpy as np
import requests
from PIL import Image

# ── same constants as image_analysis.py ──────────────────────────────────────
_BLUE_H_LO,  _BLUE_H_HI  = 105, 185
_BLUE_S_MIN, _BLUE_V_MIN  =  40,  30

_YELLOW_H_LO,  _YELLOW_H_HI  = 15, 55
_YELLOW_S_MIN, _YELLOW_V_MIN  = 65, 80

_BLUE_RATIO_MIN   = 0.04
_YELLOW_RATIO_MIN = 0.005
_YELLOW_RATIO_MAX = 0.70
_YELLOW_ZONE_RATIO = 0.022

_RED_H_MAX = 12
_RED_H_MIN = 243
_RED_S_MIN = 70
_RED_V_MIN = 70
_RED_RATIO_MIN = 0.0003

_THUMB = (150, 200)
_HEADERS = {'User-Agent': 'Mozilla/5.0'}
# ─────────────────────────────────────────────────────────────────────────────


def _mask(arr, h_lo, h_hi, s_min, v_min):
    h, s, v = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
    return (h >= h_lo) & (h <= h_hi) & (s >= s_min) & (v >= v_min)


def diagnose(url: str, label: str):
    print(f"\n{'-'*70}")
    print(f"  {label}")
    print(f"  {url}")
    try:
        r = requests.get(url, timeout=10, headers=_HEADERS)
        r.raise_for_status()
        img = Image.open(io.BytesIO(r.content)).convert('RGB')
        img.thumbnail(_THUMB, Image.LANCZOS)
        img = img.convert('HSV')
    except Exception as e:
        print(f"  FETCH ERROR: {e}")
        return

    arr = np.array(img)
    total = arr.shape[0] * arr.shape[1]

    blue_mask   = _mask(arr, _BLUE_H_LO,   _BLUE_H_HI,   _BLUE_S_MIN,   _BLUE_V_MIN)
    yellow_mask = _mask(arr, _YELLOW_H_LO, _YELLOW_H_HI, _YELLOW_S_MIN, _YELLOW_V_MIN)
    h_arr, s_arr, v_arr = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
    red_mask = ((h_arr <= _RED_H_MAX) | (h_arr >= _RED_H_MIN)) & (s_arr >= _RED_S_MIN) & (v_arr >= _RED_V_MIN)

    blue_ratio   = blue_mask.sum() / total
    yellow_ratio = yellow_mask.sum() / total
    red_ratio    = red_mask.sum()    / total

    h = arr.shape[0]
    third = max(h // 3, 1)
    top_zone    = yellow_mask[:third, :]
    bottom_zone = yellow_mask[h - third:, :]
    top_ratio    = top_zone.sum()    / top_zone.size
    bottom_ratio = bottom_zone.sum() / bottom_zone.size

    def chk(val, lo=None, hi=None):
        if lo is not None and val < lo:
            return f"FAIL (<{lo:.4f})"
        if hi is not None and val > hi:
            return f"FAIL (>{hi:.4f})"
        return "ok"

    print(f"  blue_ratio   = {blue_ratio:.4f}  {chk(blue_ratio, lo=_BLUE_RATIO_MIN)}")
    print(f"  yellow_ratio = {yellow_ratio:.4f}  {chk(yellow_ratio, lo=_YELLOW_RATIO_MIN, hi=_YELLOW_RATIO_MAX)}")
    print(f"  red_ratio    = {red_ratio:.4f}  (threshold {_RED_RATIO_MIN})")
    print(f"  top_zone     = {top_ratio:.4f}  {'ok' if top_ratio >= _YELLOW_ZONE_RATIO else f'below {_YELLOW_ZONE_RATIO}'}")
    print(f"  bottom_zone  = {bottom_ratio:.4f}  {'ok' if bottom_ratio >= _YELLOW_ZONE_RATIO else f'below {_YELLOW_ZONE_RATIO}'}")
    tiebreak = blue_ratio / max(yellow_ratio, 1e-4)
    print(f"  tiebreak     = {tiebreak:.2f}  (blue/yellow)")

    passed = (
        blue_ratio   >= _BLUE_RATIO_MIN and
        yellow_ratio >= _YELLOW_RATIO_MIN and
        yellow_ratio <= _YELLOW_RATIO_MAX
    )
    print(f"  DETECTION => {'PASS (back detected)' if passed else 'FAIL (not detected as back)'}")


CSV_PATH = r"C:\Users\chrsh\Documents\01. Programming\06. TCG Arb\card_back_examples\20260602_Fails.csv"

with open(CSV_PATH, newline='', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for i, row in enumerate(reader, 1):
        back_url  = row.get('Back Link', '').strip()
        front_url = row.get('Front Link', '').strip()
        notes     = row.get('Notes', '').strip()
        label = f"Row {i+1}: {notes}" if notes else f"Row {i+1}"
        if back_url:
            diagnose(back_url,  f"{label} - BACK")
        if front_url and notes:
            diagnose(front_url, f"{label} - FRONT (checking for false-positive)")
