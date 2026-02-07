#!/usr/bin/env python3
"""
Build per-state ACS Profile attrs JSON for US Census Places.

Reads:
- config.json (repo root)

Writes:
- outputs.attrs_dir / outputs.attrs_filename_template (per state)
- outputs.manifest

Optional:
- CENSUS_API_KEY env var for higher reliability / rate limits
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


CONFIG_PATH = "config.json"


# ---------------------------
# Helpers
# ---------------------------

def read_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        # minified but deterministic
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def fetch_json(url: str, retries: int = 6, base_sleep_s: float = 1.0) -> List[List[str]]:
    last_err: Optional[Exception] = None
    for i in range(retries):
        try:
            req = Request(url, headers={"User-Agent": "places-acs-builder/1.0"})
            with urlopen(req, timeout=90) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw)
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as e:
            last_err = e
            time.sleep(base_sleep_s * (2 ** i))
    raise RuntimeError(f"Failed to fetch after {retries} tries:\n{url}\nLast error: {last_err}")


def pad_geoid(statefp: str, placefp: str) -> str:
    return statefp.zfill(2) + placefp.zfill(5)


def parse_value(raw: str, vtype: str):
    if raw is None:
        return None
    s = str(raw).strip()
    if s == "" or s.upper() in {"NULL", "N/A"}:
        return None
    try:
        if vtype == "int":
            # Some ACS values can arrive as "123.0"
            return int(float(s))
        if vtype == "float":
            return float(s)
        return s
    except ValueError:
        return None


def get_pmtiles_block(cfg: dict) -> dict:
    """
    Prefer top-level cfg["pmtiles"].
    Fallback to outputs.pmtiles_places_* if present.
    """
    if isinstance(cfg.get("pmtiles"), dict) and cfg["pmtiles"]:
        return cfg["pmtiles"]

    out = cfg.get("outputs", {})
    url = out.get("pmtiles_places_url")
    file_ = out.get("pmtiles_places_file")
    layer = out.get("pmtiles_places_layer")
    promote = out.get("pmtiles_places_promoteId")

    if any([url, file_, layer, promote]):
        return {
            "file": file_,
            "url": url,
            "layer": layer,
            "promoteId": promote
        }

    return {}


# ---------------------------
# Main
# ---------------------------

def main() -> None:
    cfg = read_json(CONFIG_PATH)

    vintage = cfg["vintage"]
    fields = cfg["fields"]
    outputs = cfg["outputs"]
    api = cfg["census_api"]

    base_url: str = api["base_url"]  # e.g. https://api.census.gov/data/2024/acs/acs5/profile

    dist_dir = Path(outputs["dist_dir"])
    attrs_dir = Path(outputs["attrs_dir"])
    filename_tmpl: str = outputs["attrs_filename_template"]
    manifest_path = Path(outputs["manifest"])

    # Optional API key
    api_key = os.getenv("CENSUS_API_KEY")
    key_param = {"key": api_key} if api_key else {}

    # 1) Get supported state list dynamically
    #    This avoids hardcoding states & includes any supported territories.
    state_url = base_url + "?" + urlencode({**key_param, "get": "NAME", "for": "state:*"})
    state_rows = fetch_json(state_url)
    # header: ["NAME","state"]
    states = [r[1] for r in state_rows[1:]]

    # 2) Build the GET var list
    var_list = [f["var"] for f in fields]
    get_vars = ",".join(var_list)

    totals = {
        "states": 0,
        "places_rows": 0,
        "places_written": 0,
        "missing_geoid": 0
    }

    files_out: List[Dict[str, Any]] = []

    # Make sure dist_dir exists (even if unused here, it’s your build root)
    dist_dir.mkdir(parents=True, exist_ok=True)

    for state in states:
        statefp = state.zfill(2)

        url = base_url + "?" + urlencode({
            **key_param,
            "get": get_vars,
            "for": api.get("for", "place:*"),  # usually "place:*"
            "in": f"state:{statefp}"
        })

        rows = fetch_json(url)
        header = rows[0]
        data_rows = rows[1:]

        idx = {name: i for i, name in enumerate(header)}
        if "state" not in idx or "place" not in idx:
            raise RuntimeError(f"Expected 'state' and 'place' columns in ACS response header.\nHeader: {header}")

        out: Dict[str, Dict[str, Any]] = {}
        written = 0

        for r in data_rows:
            st = r[idx["state"]]
            pl = r[idx["place"]]
            geoid = pad_geoid(st, pl)
            if len(geoid) != 7:
                totals["missing_geoid"] += 1
                continue

            rec: Dict[str, Any] = {}
            for f in fields:
                raw = r[idx[f["var"]]]
                rec[f["key"]] = parse_value(raw, f.get("type", "float"))

            out[geoid] = rec
            written += 1

        out_name = filename_tmpl.format(state=statefp)
        out_path = attrs_dir / out_name
        write_json(out_path, out)

        totals["states"] += 1
        totals["places_rows"] += len(data_rows)
        totals["places_written"] += written

        files_out.append({
            "statefp": statefp,
            "file": out_path.as_posix(),
            "count": written
        })

        print(f"state {statefp}: rows={len(data_rows)} written={written}")

    pmtiles_block = get_pmtiles_block(cfg)

    manifest = {
        "dataset": "us_census_places_acs_profile",
        "generated_at": datetime.now(timezone.utc).isoformat(),

        "vintage": vintage,

        "sources": {
            "acs_api_base_url": base_url
        },

        # ties geometry + attrs together
        "pmtiles": pmtiles_block,

        "attrs": {
            "format": "geoid_keyed_object",
            "by_state": True,
            "attrs_dir": attrs_dir.as_posix(),
            "files": files_out
        },

        "schema": {
            "join_key": cfg["join_key"],
            "fields": fields
        },

        "totals": totals
    }

    write_json(manifest_path, manifest)

    print("\nDONE")
    print(f"manifest: {manifest_path.as_posix()}")
    print(f"attrs dir: {attrs_dir.as_posix()}")
    print(f"states: {totals['states']} places_written: {totals['places_written']}")


if __name__ == "__main__":
    main()