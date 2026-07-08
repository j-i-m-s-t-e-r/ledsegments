"""
Build-time script: traces every character glyph on the sprite sheet into a
true vector path using potrace, and bakes the results into font/glyphs.json.

This only needs to be re-run if the source sprite sheet changes. The deployed
Flask app just reads glyphs.json - it does NOT need potrace installed.
"""
import json
import re
import subprocess
import tempfile
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app as fontapp
import numpy as np
from PIL import Image

CHARS = list("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-")

PATH_RE = re.compile(r'<path d="([^"]+)"\s*/>')
TRANSFORM_RE = re.compile(r'<g transform="([^"]+)"')


def trace_char(ch, tmpdir):
    row, col = fontapp.CHAR_MAP[ch]
    tile = fontapp.get_tile(row, col).convert("L")
    arr = np.array(tile)
    mask = arr > 40  # lit-pixel threshold, consistent with the raster path

    # potrace traces BLACK pixels on a WHITE background by default, so
    # invert: glyph strokes -> black, background -> white.
    bw = Image.fromarray((~mask * 255).astype("uint8")).convert("1")

    pbm_path = os.path.join(tmpdir, f"{ord(ch)}.pbm")
    svg_path = os.path.join(tmpdir, f"{ord(ch)}.svg")
    bw.save(pbm_path)

    subprocess.run(
        ["potrace", pbm_path, "-s", "-o", svg_path],
        check=True, capture_output=True,
    )

    with open(svg_path) as f:
        svg_text = f.read()

    paths = PATH_RE.findall(svg_text)
    transform_match = TRANSFORM_RE.search(svg_text)
    transform = transform_match.group(1) if transform_match else None

    combined_d = " ".join(p.replace("\n", " ") for p in paths)
    return combined_d, transform, tile.size


def main():
    fontapp.load_sheet()
    glyphs = {}
    transforms = set()
    canvas_size = None

    with tempfile.TemporaryDirectory() as tmpdir:
        for ch in CHARS:
            d, transform, size = trace_char(ch, tmpdir)
            glyphs[ch] = d
            transforms.add(transform)
            canvas_size = size
            print(f"traced {ch!r}: {len(d)} chars of path data")

    if len(transforms) != 1:
        print("WARNING: transforms differ across glyphs:", transforms)
    transform = next(iter(transforms))

    out = {
        "tile_width": canvas_size[0],
        "tile_height": canvas_size[1],
        "group_transform": transform,
        "glyphs": glyphs,
    }

    out_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "font", "glyphs.json")
    with open(out_path, "w") as f:
        json.dump(out, f)

    print(f"\nWrote {out_path}")
    print(f"Canvas: {canvas_size}, transform: {transform}")


if __name__ == "__main__":
    main()
