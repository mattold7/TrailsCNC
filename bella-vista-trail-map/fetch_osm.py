"""Download OSM trails, roads, water and city boundary for Bella Vista, AR (cached to data/)."""
import json, sys, requests
from pathlib import Path

BBOX = (36.40, -94.36, 36.505, -94.14)  # south, west, north, east
URL = "https://overpass-api.de/api/interpreter"
HDR = {"User-Agent": "TrailsCNC/0.1 (personal laser map project)"}
DATA = Path(__file__).parent / "data"

QUERIES = {
    "trails": """way["highway"~"path|footway|cycleway|bridleway|track"](%s);""",
    "roads":  """way["highway"~"motorway|trunk|primary|secondary|tertiary|unclassified|residential|living_street|service"]["service"!~"parking_aisle|driveway"](%s);""",
    "water":  """(way["natural"="water"](%s);relation["natural"="water"](%s);way["waterway"~"river|stream"](%s););""",
    "boundary": """relation["boundary"="administrative"]["name"="Bella Vista"](%s);""",
}

def fetch(name, force=False):
    out = DATA / f"{name}.json"
    if out.exists() and not force:
        return json.loads(out.read_text(encoding="utf-8"))
    bb = ",".join(map(str, BBOX))
    q = QUERIES[name].replace("%s", bb)
    body = f"[out:json][timeout:180];{q}out geom;"
    r = requests.post(URL, data={"data": body}, headers=HDR, timeout=240)
    r.raise_for_status()
    out.write_text(r.text, encoding="utf-8")
    return r.json()

if __name__ == "__main__":
    force = "--force" in sys.argv
    for n in QUERIES:
        d = fetch(n, force)
        print(n, len(d["elements"]), "elements")
