"""
Sample the RGB values of pixels that fall in the 'orange/yellow' hue bucket
to understand what color they actually are.
"""

import io
import numpy as np
import requests
from PIL import Image

_HEADERS = {'User-Agent': 'Mozilla/5.0'}
_THUMB = (150, 200)

URLS = {
    "Row2 back (Gengar EX PF)":       "https://i.ebayimg.com/images/g/o3UAAeSwPtlqHMde/s-l960.jpg",
    "Row7 back (Celebi+Venusaur GX)": "https://i.ebayimg.com/images/g/zm0AAeSw5p9qHKwV/s-l960.jpg",
}

for label, url in URLS.items():
    print(f"\n{'='*60}")
    print(f"  {label}")
    r = requests.get(url, timeout=10, headers=_HEADERS)
    img = Image.open(io.BytesIO(r.content)).convert('RGB')
    img.thumbnail(_THUMB, Image.LANCZOS)

    rgb = np.array(img)
    hsv = np.array(img.convert('HSV'))
    h = hsv[:, :, 0]
    s = hsv[:, :, 1]
    v = hsv[:, :, 2]

    # grab pixels in the 'orange' bucket (H 15-27, S>=65, V>=80)
    mask = (h >= 15) & (h <= 27) & (s >= 65) & (v >= 80)
    orange_pixels = rgb[mask]
    print(f"  Pixels in orange/yellow bucket: {mask.sum()} / {h.size}")
    if len(orange_pixels) > 0:
        print(f"  Mean RGB: R={orange_pixels[:,0].mean():.0f}  G={orange_pixels[:,1].mean():.0f}  B={orange_pixels[:,2].mean():.0f}")
        print(f"  Median RGB: R={np.median(orange_pixels[:,0]):.0f}  G={np.median(orange_pixels[:,1]):.0f}  B={np.median(orange_pixels[:,2]):.0f}")
        # sample a few representative pixels
        indices = np.random.choice(len(orange_pixels), min(10, len(orange_pixels)), replace=False)
        print(f"  Sample pixels (RGB):")
        for px in orange_pixels[indices]:
            r_val, g_val, b_val = px
            print(f"    R={r_val:3d}  G={g_val:3d}  B={b_val:3d}  (hex: #{r_val:02x}{g_val:02x}{b_val:02x})")

    # also check: what does the blue bucket look like?
    blue_mask = (h >= 142) & (h <= 185) & (s >= 40) & (v >= 30)
    blue_pixels = rgb[blue_mask]
    print(f"\n  Blue bucket pixels: {blue_mask.sum()}")
    if len(blue_pixels) > 0:
        print(f"  Mean RGB: R={blue_pixels[:,0].mean():.0f}  G={blue_pixels[:,1].mean():.0f}  B={blue_pixels[:,2].mean():.0f}")
        indices = np.random.choice(len(blue_pixels), min(5, len(blue_pixels)), replace=False)
        print(f"  Sample pixels (RGB):")
        for px in blue_pixels[indices]:
            r_val, g_val, b_val = px
            print(f"    R={r_val:3d}  G={g_val:3d}  B={b_val:3d}  (hex: #{r_val:02x}{g_val:02x}{b_val:02x})")
