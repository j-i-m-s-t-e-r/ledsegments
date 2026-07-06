# 14-Segment LED Sign App

A tiny containerized app that turns any text into an image rendered with a
14-segment LED display font, sliced from a single composite sprite sheet
(`font/14segmentLEDFont.png`).

- **Frontend**: static HTML/JS page (`static/index.html`) with a text box.
- **Backend**: Flask app (`app.py`) that slices the sprite sheet into
  individual glyph tiles and composites them into a PNG for whatever text
  the user submits, served at `/api/render?text=...`.

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

1. Push this folder to a Git repository (GitHub/GitLab).
2. In Render, choose **New > Web Service**, connect the repo, and pick
   **Docker** as the environment (Render will auto-detect the `Dockerfile`).
   Alternatively, Render can pick up the included `render.yaml` blueprint
   automatically if you use **New > Blueprint**.
3. No environment variables are required (the app reads `PORT` automatically,
   which Render sets for you).
4. Deploy. Render will build the image and expose the service on your
   `*.onrender.com` URL.

## How the font mapping works

The composite sprite sheet is a 10-column x 7-row grid of tiles. `app.py`
maps characters to grid cells:

- `A-J` -> row 3
- `K-T` -> row 4
- `U-Z` -> row 5 (columns 2-7)
- `1-9,0` -> row 6
- `-` -> row 0, column 2
- space or any unsupported character -> a blank/unlit tile

If you want to support lowercase distinctly, add more mappings to
`CHAR_MAP` in `app.py` (currently lowercase input is upper-cased before
lookup, since the font only has one case per letter).

## API

`GET /api/render?text=HELLO WORLD`

Returns a PNG image. Text is wrapped automatically at 20 characters per
line and honors literal newlines (`\n`) in the input, up to 200 characters
total per request.

`GET /api/health` returns `{"status": "ok"}` for health checks.
