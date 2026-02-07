# places-pipeline

A repeatable, config-driven pipeline to publish **US Census “Places” (cities + CDPs) boundaries** as **MapLibre-ready PMTiles**, and **ACS 5-year demographic attributes** as compact **JSON lookups** keyed by **GEOID** for fast MapLibre + Chart.js interactivity.

This repo is intentionally **pipeline-only**: it builds and publishes datasets. The map UI lives elsewhere.

---

## What this repo produces

### 1) Places boundary tiles (geometry)
- **PMTiles (MVT vector tiles)** built from Census cartographic boundary “Places” polygons.
- Used by MapLibre to draw and interact with place boundaries.

Example output:
- `dist/places_cb_2024_500k_z5.pmtiles`

### 2) Places attributes (demographics)
- Per-state JSON files keyed by **7-digit place GEOID** (`STATEFP + PLACEFP`)
- Designed for **lazy-loading** by state and **fast client-side joins** on click/hover.

Example outputs:
- `dist/acs5_2024/attrs_by_state/attrs_places_acs5_2024_08.json` (Colorado)
- `dist/acs5_2024/manifest.json`

---

## Data sources

### Boundaries
- **Census cartographic boundary (CB) Places** shapefile  
  Example: `cb_2024_us_place_500k`

Why CB and not full TIGER? CB is generalized/smaller → faster for the web.

### Demographics
- **ACS 5-year “profile” dataset via Census API**  
  Example vintage: **2024** (ACS 2020–2024)

---

## Repo philosophy (important)

- **Git stores the recipe**, not the artifacts.
- Large outputs (`dist/`, `.pmtiles`, `.mbtiles`, raw shapefiles) should be published to your CDN/R2 and **not committed**.

---

## Requirements

### Required for the ACS attrs build (Phase 1)
- Python 3.x (script uses **standard library only**)

Recommended:
- A virtual environment (venv)

Optional:
- **Census API key** as `CENSUS_API_KEY` for more reliable API access

### Required for the PMTiles boundary build (Phase 0) *if you rebuild geometry*
- GDAL (`ogr2ogr`, `ogrinfo`)
- tippecanoe
- pmtiles CLI

### Required to publish to R2/CDN
- AWS CLI configured for Cloudflare R2 (`--endpoint-url` + profile)

---

## Quick start (ACS attrs build)

From repo root:

```bash
# optional but recommended
python3 -m venv .venv
source .venv/bin/activate

# optional API key
export CENSUS_API_KEY="YOUR_KEY"

python3 scripts/build_attrs.py
```

Outputs:
- `dist/acs5_2024/attrs_by_state/*.json`
- `dist/acs5_2024/manifest.json`

---

## Project structure (recommended)

```
places-pipeline/
  README.md
  LICENSE
  .gitignore
  config.json

  scripts/
    build_attrs.py

  examples/
    places-smoketest.html   # optional local sanity check UI

  data/
    manifests/              # optional small “release pointer” JSON (committed)

  dist/                     # build outputs (ignored)
```

---

## config.json (the “contract”)

This repo works best when you treat `config.json` as a stable contract:

- **Vintage**: ACS year + boundary year
- **Join key**: always 7-digit place GEOID
- **Schema**: stable friendly keys like `pop_total`, `median_hh_income`, etc.
- **Output paths**: where the build writes artifacts

Typical high-level shape:

- `vintage`: ACS and boundary versions
- `pmtiles`: where your already-published PMTiles lives (file + CDN URL)
- `join_key`: how we compute GEOID
- `census_api`: dataset endpoint
- `fields`: list of ACS variables + stable keys
- `outputs`: dist folders + filename templates

---

## Phase 0 (optional): build the Places PMTiles boundary tiles

> Skip this if you already built and published your PMTiles.

### A) Download the CB Places shapefile
Unzip it into a raw folder (example paths only):

```bash
mkdir -p data/raw data/work dist
# download + unzip (method varies)
```

### B) Convert to GeoJSON with selected fields
Example:

```bash
ogr2ogr -f GeoJSON -t_srs EPSG:4326   data/work/places_cb_2024_500k.geojson   data/raw/cb_us_place_500k/cb_2024_us_place_500k.shp   -select GEOID,NAME,STATEFP,PLACEFP,ALAND,AWATER
```

You may see a warning like:

> “Several coordinate operations have been used…”

This is common when GDAL chooses among multiple NAD83 → WGS84 transforms. If it ever becomes a *visual* problem, you can tighten the transform selection with `-ct_opt`, but most CB workflows are fine as-is.

### C) Build MBTiles using tippecanoe
Example minzoom/maxzoom (yours is z5-based):

```bash
tippecanoe   -o dist/places_cb_2024_500k_z5.mbtiles   -l places   -Z5 -z12   --force   --drop-densest-as-needed   --coalesce   data/work/places_cb_2024_500k.geojson
```

### D) Convert MBTiles → PMTiles
```bash
pmtiles convert dist/places_cb_2024_500k_z5.mbtiles dist/places_cb_2024_500k_z5.pmtiles
```

### E) Inspect metadata
```bash
pmtiles show dist/places_cb_2024_500k_z5.pmtiles
pmtiles show --metadata dist/places_cb_2024_500k_z5.pmtiles | jq
```

Note: some `pmtiles show --metadata` fields are JSON strings; you may need `| jq '.strategies|fromjson'`.

---

## Phase 1: build ACS attrs (the main pipeline step)

### What `scripts/build_attrs.py` does
For each supported state/territory in the dataset:
1. Calls the Census API for `place:* in state:XX`
2. Builds a JSON object:
   - keys: `GEOID` (7 digits)
   - values: `{ pop_total, median_hh_income, ... }`
3. Writes one file per state:
   - `attrs_places_acs5_2024_{STATEFP}.json`
4. Writes a `manifest.json` tying geometry + attrs together.

### Run it
```bash
export CENSUS_API_KEY="YOUR_KEY"   # optional
python3 scripts/build_attrs.py
```

### Sanity checks
Counts:

```bash
cat dist/acs5_2024/manifest.json | jq '.totals'
```

Spot-check a known GEOID (Colorado examples):
- Loveland: `0846465`
- Fort Collins: `0827425`

```bash
jq '.["0846465"]' dist/acs5_2024/attrs_by_state/attrs_places_acs5_2024_08.json
jq '.["0827425"]' dist/acs5_2024/attrs_by_state/attrs_places_acs5_2024_08.json
```

---

## Publishing to Cloudflare R2 + CDN

Recommended CDN layout:

- PMTiles:
  - `pmtiles/places_cb_2024_500k_z5.pmtiles`
  - (or `pmtiles/places/places_cb_2024_500k_z5.pmtiles` if you prefer a subfolder)

- Attrs + manifest:
  - `attrs/places/acs5_2024/manifest.json`
  - `attrs/places/acs5_2024/attrs_by_state/*.json`

### Upload (example)
Adjust bucket, endpoint, and profile to your setup:

```bash
aws s3 sync dist/acs5_2024/ s3://YOUR_BUCKET/attrs/places/acs5_2024/   --profile r2   --endpoint-url https://YOUR_ACCOUNT_ID.r2.cloudflarestorage.com   --exclude ".DS_Store"   --exclude "*" --include "*.json"
```

### Verify Brotli/gzip is happening at the edge
```bash
curl -I -H "accept-encoding: br,gzip"   https://data.storypath.studio/attrs/places/acs5_2024/manifest.json
```

Look for:
- `content-type: application/json`
- `content-encoding: br` (or gzip)

---

## Local smoke test (optional): MapLibre + PMTiles + attrs + Chart.js

This repo can include a tiny HTML file under `examples/` just to prove the pipeline outputs are usable.

### Why this matters
It validates the whole chain:
- MapLibre renders your PMTiles Places polygons
- Click returns `GEOID`
- App lazy-loads the correct state attrs JSON
- Chart updates

### Run locally
From repo root:

```bash
python3 -m http.server 5173
```

Open:
- `http://localhost:5173/examples/places-smoketest.html`

#### Notes
- If your PMTiles minzoom is 5, you must zoom in past 5 to see features.
- If the map looks “tilted” or weird while testing, disable rotate/pitch interactions in the smoke test (recommended).

---

## Updating next year (repeatable process)

When a new ACS 5-year vintage arrives:

1) Copy your config:
- `config.json` → `config.2025.json` (optional pattern)
2) Update:
- `vintage.acs_year`
- `census_api.base_url`
- (optional) `boundary_year` / CB boundary shapefile if you rebuild geometry
3) Re-run:
```bash
python3 scripts/build_attrs.py
```
4) Publish to a new folder:
- `attrs/places/acs5_2025/…`
5) Update your app’s pointer (recommended):
- keep a tiny `places-latest.json` that points to the current manifest

This way the app can always load “latest” without hardcoding years.

---

## Common issues & troubleshooting

### “My Places layer isn’t showing”
- Check your PMTiles **minzoom**. If built with `-Z5`, zoom must be ≥ 5.
- Confirm the layer name: tippecanoe `-l places` ⇒ `source-layer: "places"`.

### “CORS blocked ESM imports from unpkg”
Some browsers/CDNs will block `type="module"` imports without CORS headers.
Fix: use classic `<script src="...">` builds for MapLibre + PMTiles in the smoke test.

### “No attrs found for a clicked place”
- Some place GEOIDs may exist in the boundary product but not in the ACS profile response (or vice versa).
- Handle missing attrs gracefully in the UI.
- Optional: write a coverage diff script to quantify missing GEOIDs.

### “Map looks rotated/tilted and clicking is annoying”
Disable rotate/pitch interactions in the smoke test:
- `map.dragRotate.disable()`
- `map.touchZoomRotate.disableRotation()`
- `map.touchPitch.disable()`

---

## Git hygiene

Recommended: ignore build artifacts and raw data. Example `.gitignore` pattern:

- ignore:
  - `dist/`
  - `data/raw/`, `data/work/`
  - `*.mbtiles`, `*.pmtiles`
- commit:
  - `config.json`
  - `scripts/`
  - `README.md`
  - (optional) `data/manifests/*.json` pointer files

---

## Suggested next repo (consumer app)

Once this pipeline is stable, build the UI in a separate repo:
- MapLibre + PMTiles places layer
- Lazy-load attrs JSON by state on click/hover
- Drive Chart.js / UI panels with those values

This keeps the pipeline repo lean and fast.

---

## License
Add your preferred license (MIT is common for pipelines like this) and include it as `LICENSE`.
