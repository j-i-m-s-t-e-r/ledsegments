# 14-Segment LED Sign App

A tiny containerized app that turns any text into a 14-segment LED display,
rendered from a single composite sprite sheet (`font/14segmentLEDFont.png`).

- **Frontend**: static HTML/JS page (`static/index.html`) with a text box,
  a live SVG preview, and Copy Image / Download PNG / Download SVG buttons.
- **Backend**: Flask app (`app.py`) that serves two renderers:
  - `/api/render.svg` — a **true vector SVG**. Every glyph was traced from
    the sprite sheet into vector paths once at build time (see
    `tools/trace_glyphs.py`, using `potrace`), so the output stays crisp at
    any zoom level or print size — no pixelation, ever. The deployed app
    does not need `potrace` installed; the traced paths are baked into
    `font/glyphs.json`.
  - `/api/render.png` — a raster PNG, composited directly from the sprite
    sheet, used for the Copy/Download buttons and anywhere a flat image is
    needed (e.g. pasting into a document or chat).
  - `/api/render` is kept as a legacy alias for `/api/render.png`.

## Run locally with Docker

```bash
docker build -t led-sign-app .
docker run -p 8080:8080 led-sign-app
```

Then open http://localhost:8080

## Run locally without Docker

```bash
pip install -r requirements.txt
python app.py
```

Then open http://localhost:8080

## Deploy to Render.com

1. Push this folder to a Git repository (GitHub/GitLab), making sure
   `app.py`, `Dockerfile`, `render.yaml`, `font/`, and `static/` all end up
   at the **repo root** (not nested inside another folder).
2. In Render, choose **New > Web Service**, connect the repo, and pick
   **Docker** as the environment (Render will auto-detect the `Dockerfile`).
   Alternatively, Render can pick up the included `render.yaml` blueprint
   automatically if you use **New > Blueprint**.
3. No environment variables are required (the app reads `PORT` automatically,
   which Render sets for you).
4. Deploy. Render will build the image and expose the service on your
   `*.onrender.com` URL.

## How the font mapping works

The composite sprite sheet is a 10-column x 7-row grid, but the characters
are **not** evenly spaced (e.g. "I" is much narrower than "M"). `app.py`
scans the sheet for real background gaps to find each glyph's true
bounding box, rather than assuming a uniform grid — this avoids cropping
into neighboring characters.

Characters map to grid cells as:

- `A-J` -> row 3
- `K-T` -> row 4
- `U-Z` -> row 5 (columns 2-7)
- `1-9,0` -> row 6
- `-` -> row 0, column 2
- space or any unsupported character -> renders nothing (blank)

If you want to support lowercase distinctly, add more mappings to
`CHAR_MAP` in `app.py` (currently lowercase input is upper-cased before
lookup, since the font only has one case per letter).

## Re-tracing glyphs (only needed if you change the sprite sheet)

`font/glyphs.json` holds the pre-traced vector path for every character.
It's generated once by `tools/trace_glyphs.py`, which requires `potrace`
and `numpy` (already in `requirements.txt`) to be available:

```bash
apt-get install -y potrace   # or your platform's equivalent
python tools/trace_glyphs.py
```

This only needs to be re-run if you swap in a different font sprite sheet.
The deployed app itself never calls `potrace` — it just reads the JSON.

## API

`GET /api/render.svg?text=HELLO WORLD` — returns a vector SVG.

`GET /api/render.png?text=HELLO WORLD` — returns a raster PNG.

Both wrap text automatically at 20 characters per line and honor literal
newlines (`\n`) in the input, up to 200 characters total per request.

`GET /api/health` returns `{"status": "ok"}` for health checks.

