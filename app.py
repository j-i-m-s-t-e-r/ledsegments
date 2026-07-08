import io
import os
import json
import numpy as np
from flask import Flask, request, send_file, jsonify, send_from_directory
from PIL import Image

APP_DIR = os.path.dirname(os.path.abspath(__file__))
FONT_SHEET_PATH = os.path.join(APP_DIR, "font", "14segmentLEDFont.png")
GLYPHS_JSON_PATH = os.path.join(APP_DIR, "font", "glyphs.json")
STATIC_DIR = os.path.join(APP_DIR, "static")

COLS, ROWS = 10, 7

# Padding added around each detected glyph box before centering it on the
# uniform output tile canvas.
GLYPH_PAD = 6

# LED fill color, sampled from the brightest pixels in the source sheet.
LED_COLOR = "#8CFF5A"
LED_GLOW_COLOR = "#4CFF2A"

# Character -> (row, col) on the composite sheet (0-indexed)
CHAR_MAP = {}

# Letters A-J -> row 3
for i, ch in enumerate("ABCDEFGHIJ"):
    CHAR_MAP[ch] = (3, i)

# Letters K-T -> row 4
for i, ch in enumerate("KLMNOPQRST"):
    CHAR_MAP[ch] = (4, i)

# Letters U-Z -> row 5, columns 2-7
for i, ch in enumerate("UVWXYZ"):
    CHAR_MAP[ch] = (5, i + 2)

# Digits 1-9,0 -> row 6, columns 0-9
for i, ch in enumerate("1234567890"):
    CHAR_MAP[ch] = (6, i)

# Dash
CHAR_MAP["-"] = (0, 2)

# Blank / space / unsupported character tile (unlit display look)
BLANK_TILE = (2, 0)

MAX_CHARS = 200  # safety cap per request

app = Flask(__name__, static_folder=None)

_sheet = None
_cell_w = None
_cell_h = None
_tile_cache = {}
_row_boxes = None      # list of (y0, y1) per row, detected from real gaps
_col_boxes_by_row = None  # dict row -> list of (x0, x1) per column, detected from real gaps
_tile_w = None
_tile_h = None
_glyph_data = None  # traced vector paths, loaded from font/glyphs.json


def _find_boxes(profile, min_gap, min_size):
    """Given a 1D max-brightness profile, find runs of 'lit' content
    separated by background gaps, merging small internal gaps (glyph
    notches) and dropping anything too small to be a real glyph."""
    thresh = profile.mean() * 0.3
    is_gap = profile < thresh

    raw = []
    in_run = False
    start = None
    for i, g in enumerate(is_gap):
        if not g and not in_run:
            in_run = True
            start = i
        elif g and in_run:
            in_run = False
            raw.append((start, i - 1))
    if in_run:
        raw.append((start, len(is_gap) - 1))

    merged = []
    for b in raw:
        if merged and b[0] - merged[-1][1] < min_gap:
            merged[-1] = (merged[-1][0], b[1])
        else:
            merged.append(list(b))

    return [tuple(b) for b in merged if (b[1] - b[0]) >= min_size]


def _detect_grid(sheet):
    """Detect the true per-glyph bounding boxes on the sprite sheet instead
    of assuming a perfectly uniform grid. The sheet's characters are not
    equal-width (e.g. 'I' is much narrower than 'M'), so naive division by
    COLS/ROWS crops into neighboring glyphs. This scans actual background
    gaps to find real column/row boundaries per character."""
    arr = np.array(sheet.convert("L"))
    h, w = arr.shape
    nominal_row_h = h / ROWS

    # Vertical bands: use a representative x-range (first column's nominal
    # span) to find the 7 row bands.
    sample_x0, sample_x1 = 0, int(w / COLS)
    row_profile = arr[:, sample_x0:sample_x1].max(axis=1)
    row_boxes = _find_boxes(row_profile, min_gap=20, min_size=nominal_row_h * 0.5)

    if len(row_boxes) != ROWS:
        # Fall back to uniform rows if detection didn't find exactly ROWS bands
        row_boxes = [(int(r * nominal_row_h), int((r + 1) * nominal_row_h) - 1) for r in range(ROWS)]

    col_boxes_by_row = {}
    for r, (y0, y1) in enumerate(row_boxes):
        band = arr[y0:y1 + 1, :]
        col_profile = band.max(axis=0)
        nominal_col_w = w / COLS
        boxes = _find_boxes(col_profile, min_gap=20, min_size=nominal_col_w * 0.3)
        if len(boxes) != COLS:
            # Fall back to uniform columns for this row if detection is off
            boxes = [(int(c * nominal_col_w), int((c + 1) * nominal_col_w) - 1) for c in range(COLS)]
        col_boxes_by_row[r] = boxes

    return row_boxes, col_boxes_by_row


def load_sheet():
    global _sheet, _cell_w, _cell_h, _row_boxes, _col_boxes_by_row, _tile_w, _tile_h
    if _sheet is None:
        _sheet = Image.open(FONT_SHEET_PATH).convert("RGBA")
        w, h = _sheet.size
        _cell_w = w / COLS
        _cell_h = h / ROWS
        _row_boxes, _col_boxes_by_row = _detect_grid(_sheet)

        # Uniform output tile size: the largest detected glyph box (plus
        # padding) across the whole sheet, so every character renders on a
        # consistent, evenly-spaced canvas regardless of its natural width.
        max_w = max(x1 - x0 + 1 for boxes in _col_boxes_by_row.values() for x0, x1 in boxes)
        max_h = max(y1 - y0 + 1 for y0, y1 in _row_boxes)
        _tile_w = max_w + GLYPH_PAD * 2
        _tile_h = max_h + GLYPH_PAD * 2
    return _sheet


def get_tile(row, col):
    key = (row, col)
    if key in _tile_cache:
        return _tile_cache[key]
    sheet = load_sheet()

    y0, y1 = _row_boxes[row]
    x0, x1 = _col_boxes_by_row[row][col]

    glyph = sheet.crop((x0, y0, x1 + 1, y1 + 1))

    # Center the glyph on a uniform, padded canvas so every character
    # occupies the same footprint regardless of its natural width/height.
    canvas = Image.new("RGBA", (_tile_w, _tile_h), (0, 0, 0, 0))
    paste_x = (_tile_w - glyph.width) // 2
    paste_y = (_tile_h - glyph.height) // 2
    canvas.alpha_composite(glyph, (paste_x, paste_y))

    _tile_cache[key] = canvas
    return canvas


def load_glyph_data():
    global _glyph_data
    if _glyph_data is None:
        with open(GLYPHS_JSON_PATH) as f:
            _glyph_data = json.load(f)
    return _glyph_data


def tile_for_char(ch):
    ch_upper = ch.upper()
    if ch_upper == " ":
        return get_tile(*BLANK_TILE)
    if ch_upper in CHAR_MAP:
        return get_tile(*CHAR_MAP[ch_upper])
    # Unsupported character (punctuation etc.) -> blank tile
    return get_tile(*BLANK_TILE)


def _wrap_lines(text, max_per_line):
    text = text[:MAX_CHARS]
    lines = text.split("\n") if "\n" in text else [text]

    wrapped_lines = []
    for line in lines:
        if not line:
            wrapped_lines.append(line)
            continue
        for i in range(0, len(line), max_per_line):
            wrapped_lines.append(line[i:i + max_per_line])
    if not wrapped_lines:
        wrapped_lines = [""]
    return wrapped_lines


def render_text(text, max_per_line=20, gap=4, padding=16, bg=(0, 0, 0, 255)):
    load_sheet()
    wrapped_lines = _wrap_lines(text, max_per_line)

    tile_w, tile_h = _tile_w, _tile_h
    max_len = max((len(l) for l in wrapped_lines), default=1)
    max_len = max(max_len, 1)

    canvas_w = padding * 2 + max_len * tile_w + (max_len - 1) * gap
    canvas_h = padding * 2 + len(wrapped_lines) * tile_h + (len(wrapped_lines) - 1) * gap

    canvas = Image.new("RGBA", (canvas_w, canvas_h), bg)

    for row_idx, line in enumerate(wrapped_lines):
        y = padding + row_idx * (tile_h + gap)
        for col_idx, ch in enumerate(line):
            x = padding + col_idx * (tile_w + gap)
            tile = tile_for_char(ch)
            canvas.alpha_composite(tile, (x, y))

    return canvas


def render_svg(text, max_per_line=20, gap=4, padding=16):
    """Render text as a true vector SVG, using pre-traced glyph paths so
    the output stays crisp at any zoom level or print size."""
    data = load_glyph_data()
    tile_w, tile_h = data["tile_width"], data["tile_height"]
    group_transform = data["group_transform"]
    glyphs = data["glyphs"]

    wrapped_lines = _wrap_lines(text, max_per_line)
    max_len = max((len(l) for l in wrapped_lines), default=1)
    max_len = max(max_len, 1)

    canvas_w = padding * 2 + max_len * tile_w + (max_len - 1) * gap
    canvas_h = padding * 2 + len(wrapped_lines) * tile_h + (len(wrapped_lines) - 1) * gap

    parts = []
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{canvas_w}" height="{canvas_h}" '
        f'viewBox="0 0 {canvas_w} {canvas_h}">'
    )
    parts.append(f'<rect x="0" y="0" width="{canvas_w}" height="{canvas_h}" fill="black"/>')
    parts.append(
        '<defs><filter id="ledGlow" x="-60%" y="-60%" width="220%" height="220%">'
        '<feGaussianBlur stdDeviation="3" result="blur"/>'
        '<feMerge>'
        '<feMergeNode in="blur"/>'
        '<feMergeNode in="SourceGraphic"/>'
        '</feMerge>'
        '</filter></defs>'
    )

    for row_idx, line in enumerate(wrapped_lines):
        y = padding + row_idx * (tile_h + gap)
        for col_idx, ch in enumerate(line):
            ch_upper = ch.upper()
            d = glyphs.get(ch_upper)
            if not d:
                continue  # space or unsupported character: render nothing
            x = padding + col_idx * (tile_w + gap)
            parts.append(
                f'<g transform="translate({x},{y})" filter="url(#ledGlow)">'
                f'<g transform="{group_transform}" fill="{LED_COLOR}" stroke="none">'
                f'<path d="{d}"/>'
                f'</g></g>'
            )

    parts.append('</svg>')
    return "".join(parts)


@app.route("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.route("/<path:path>")
def static_files(path):
    return send_from_directory(STATIC_DIR, path)


@app.route("/api/render.png")
@app.route("/api/render")  # legacy alias, defaults to PNG
def api_render_png():
    text = request.args.get("text", "")
    if not text.strip():
        return jsonify({"error": "text parameter is required"}), 400

    img = render_text(text)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")


@app.route("/api/render.svg")
def api_render_svg():
    text = request.args.get("text", "")
    if not text.strip():
        return jsonify({"error": "text parameter is required"}), 400

    svg = render_svg(text)
    return app.response_class(svg, mimetype="image/svg+xml")


@app.route("/api/health")
def health():
    return jsonify({"status": "ok"})


# Warm caches at import time so this works under gunicorn too, not just
# when run directly with `python app.py`.
load_sheet()
load_glyph_data()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
