"""
Show the full hue distribution of a card back image to see what the
"yellow" mask is actually capturing.
"""

import io
import numpy as np
import requests
from PIL import Image

_HEADERS = {'User-Agent': 'Mozilla/5.0'}
_THUMB = (150, 200)

# yellow window as used in image_analysis.py
_YELLOW_H_LO, _YELLOW_H_HI = 15, 55   # Pillow HSV units (0-255)
# In real degrees: 15/255*360 = 21 deg (orange), 55/255*360 = 78 deg (yellow-green)

URLS = {
    "Row2 back (Gengar EX PF)":       "https://i.ebayimg.com/images/g/o3UAAeSwPtlqHMde/s-l960.jpg",
    "Row3 back (Black Kyurem EX BC)": "https://i.ebayimg.com/images/g/IM8AAeSw6SZqGwEr/s-l960.jpg",
    "Row7 back (Celebi+Venusaur GX)": "https://i.ebayimg.com/images/g/zm0AAeSw5p9qHKwV/s-l960.jpg",
}

for label, url in URLS.items():
    print(f"\n{'='*60}")
    print(f"  {label}")
    r = requests.get(url, timeout=10, headers=_HEADERS)
    img = Image.open(io.BytesIO(r.content)).convert('RGB')
    img.thumbnail(_THUMB, Image.LANCZOS)
    hsv = np.array(img.convert('HSV'))
    h = hsv[:, :, 0]

    total = h.size
    print(f"  Image size: {img.size}  ({total} px)")
    print(f"\n  Hue bucket distribution (Pillow 0-255 -> real degrees):")
    buckets = [
        ("red/orange  (0-14  / 0-20 deg)",    0,   14),
        ("orange/yel (15-27  / 21-38 deg)",   15,  27),
        ("yellow     (28-39  / 39-55 deg)",   28,  39),
        ("yel-green  (40-55  / 56-78 deg)",   40,  55),
        ("green      (56-106 / 79-150 deg)",  56, 106),
        ("cyan       (107-141/ 151-200 deg)", 107, 141),
        ("blue/teal  (142-185/ 200-261 deg)", 142, 185),
        ("indigo/vio (186-213/ 261-301 deg)", 186, 213),
        ("magenta    (214-255/ 301-360 deg)", 214, 255),
    ]
    for name, lo, hi in buckets:
        n = ((h >= lo) & (h <= hi)).sum()
        pct = n / total * 100
        bar = '#' * int(pct / 2)
        flag = " <-- COUNTED AS YELLOW" if lo >= 15 and hi <= 55 else ""
        print(f"  {name:45s}  {pct:5.1f}%  {bar}{flag}")

    in_window = ((h >= _YELLOW_H_LO) & (h <= _YELLOW_H_HI)).sum()
    print(f"\n  Total in yellow window (H 15-55): {in_window/total*100:.1f}%")
    print(f"  -> orange/yel sub-window (15-27): {((h>=15)&(h<=27)).sum()/total*100:.1f}%")
    print(f"  -> pure yellow sub-window (28-39): {((h>=28)&(h<=39)).sum()/total*100:.1f}%")
    print(f"  -> yel-green sub-window (40-55): {((h>=40)&(h<=55)).sum()/total*100:.1f}%")
