import io
import os
from flask import Flask, request, send_file, jsonify, send_from_directory
from PIL import Image

APP_DIR = os.path.dirname(os.path.abspath(__file__))
FONT_SHEET_PATH = os.path.join(APP_DIR, "font", "14segmentLEDFont.png")
STATIC_DIR = os.path.join(APP_DIR, "static")

COLS, ROWS = 10, 7

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


def load_sheet():
    global _sheet, _cell_w, _cell_h
    if _sheet is None:
        _sheet = Image.open(FONT_SHEET_PATH).convert("RGBA")
        w, h = _sheet.size
        _cell_w = w / COLS
        _cell_h = h / ROWS
    return _sheet


def get_tile(row, col):
    key = (row, col)
    if key in _tile_cache:
        return _tile_cache[key]
    sheet = load_sheet()
    x0, y0 = int(col * _cell_w), int(row * _cell_h)
    x1, y1 = int((col + 1) * _cell_w), int((row + 1) * _cell_h)
    tile = sheet.crop((x0, y0, x1, y1))
    _tile_cache[key] = tile
    return tile


def tile_for_char(ch):
    ch_upper = ch.upper()
    if ch_upper == " ":
        return get_tile(*BLANK_TILE)
    if ch_upper in CHAR_MAP:
        return get_tile(*CHAR_MAP[ch_upper])
    # Unsupported character (punctuation etc.) -> blank tile
    return get_tile(*BLANK_TILE)


def render_text(text, max_per_line=20, gap=4, padding=16, bg=(0, 0, 0, 255)):
    load_sheet()
    text = text[:MAX_CHARS]
    lines = text.split("\n") if "\n" in text else [text]

    # Wrap long lines to max_per_line characters
    wrapped_lines = []
    for line in lines:
        if not line:
            wrapped_lines.append(line)
            continue
        for i in range(0, len(line), max_per_line):
            wrapped_lines.append(line[i:i + max_per_line])
    if not wrapped_lines:
        wrapped_lines = [""]

    tile_w, tile_h = int(_cell_w), int(_cell_h)
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


@app.route("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.route("/<path:path>")
def static_files(path):
    return send_from_directory(STATIC_DIR, path)


@app.route("/api/render")
def api_render():
    text = request.args.get("text", "")
    if not text.strip():
        return jsonify({"error": "text parameter is required"}), 400

    img = render_text(text)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")


@app.route("/api/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    load_sheet()
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
