"""
Bella Vista, AR trail poster -> layered laser-cut SVGs (units: mm).

Layers produced in output/ (stack bottom -> top):
  0_backer.svg       solid board (blue) - shows through lake cutouts
  1_base.svg         map board: CUT lakes + outline, SCORE roads, light SCORE contours/streams,
                     ENGRAVE (filled) small lettering: subtitle, tagline, rules, "MILES OF TRAIL", N
  2_trails.svg       raised trail strips (omitted with --lines)
  3_lettering.svg    raised title, trail-system names, mileage numbers, north arrow
  4_scene_far.svg    far ridgeline (lightest)
  5_scene_lake.svg   lake that peeks between the hills
  6_scene_mid.svg    mid hills + small pines
  7_scene_near.svg   near hills, big pines, rock and bike (darkest)
  8_frame.svg        frame ring
  topo/              optional stacked elevation layers (--stacked N)
  preview.png        colored assembly preview

Laser color convention (LightBurn/xTool import by color):
  red     #FF0000 = CUT through
  black   #000000 = ENGRAVE (filled raster) lettering
  blue    #0000FF = SCORE (roads)
  green   #00A000 = light SCORE (contours, streams)
  orange  #FF8000 = trail lines (--lines mode only)
  magenta #FF00FF = registration board outline (cut LAST to make an alignment jig, or disable)
  gray    #B4B4B4 = glue guides: light engrave just inside where the next layer's pieces go
"""
import argparse, json, math, io
from pathlib import Path

import numpy as np
import requests
from PIL import Image
from pyproj import Transformer
from shapely import affinity
from shapely.geometry import (LineString, MultiLineString, Polygon, MultiPolygon,
                              box, shape, GeometryCollection)
from shapely.ops import unary_union, linemerge, polygonize
from skimage import measure

ROOT = Path(__file__).parent
DATA = ROOT / "data"
OUT = ROOT / "output"

# ----------------------------------------------------------------- settings
CFG = dict(
    board_w=609.6, board_h=609.6,    # 24 x 24 in board; override with --size 14x11
    frame_w=19.0,                    # frame ring width (mm), overlaps board edge by frame_lip
    frame_lip=6.0,
    margin=8.0,                      # map margin inside the visible area (mm)
    trail_width=1.5,                 # finished width of raised trail strip (mm)
    trail_gap=0.6,                   # roads/contours stop this far (mm) from a trail line
    min_hole_area=6.0,               # fill holes in trail layer smaller than this (mm^2)
    min_lake_area=12.0,              # drop lakes smaller than this on the map (mm^2)
    road_simplify=0.15,              # mm
    trail_simplify=0.12,             # mm
    contour_interval_ft=40,          # engraved contour spacing (0 = none)
    clip_to_city=True,               # only trails within Bella Vista city limits (+buffer)
    city_buffer_m=400,
    title="BELLA VISTA",
    subtitle="ARKANSAS",
    tagline="MOUNTAIN BIKE TRAILS OF THE OZARKS",
    title_max=95,                    # max title cap height (mm, at 24")
    # trail-system panels (official mileage); miles=None -> measured from the map (trails west/east of split_lon)
    systems=[dict(name="LITTLE\nSUGAR", side="left", miles=50),
             dict(name="THE\nBACK 40", side="right", miles=40)],
    system_split_lon=-94.244,
    scene_clear=45,                  # mm of landscape kept below the lowest trail (at 24")
    seed=7,
    bike_image=None,                 # path to a dark-on-light bike silhouette PNG to trace instead                          # change for different hills / tree shapes
    dem_zoom=13,
)

TO_UTM = Transformer.from_crs("EPSG:4326", "EPSG:32615", always_xy=True)

# ----------------------------------------------------------------- OSM helpers
def load(name):
    return json.loads((DATA / f"{name}.json").read_text(encoding="utf-8"))["elements"]

def way_line(e):
    xs, ys = TO_UTM.transform([p["lon"] for p in e["geometry"]], [p["lat"] for p in e["geometry"]])
    return LineString(zip(xs, ys))

def rel_polys(e):
    """Assemble a multipolygon relation into shapely polygons (outer minus inner)."""
    outers, inners = [], []
    for m in e.get("members", []):
        if m["type"] != "way" or "geometry" not in m:
            continue
        ln = way_line(m)
        (inners if m.get("role") == "inner" else outers).append(ln)
    def assemble(lines):
        merged = linemerge(lines) if lines else None
        return list(polygonize(merged)) if merged is not None else []
    outer = unary_union(assemble(outers))
    inner = unary_union(assemble(inners))
    return outer.difference(inner) if not inner.is_empty else outer

TRAIL_HW = {"path", "cycleway", "bridleway", "track", "footway"}

def is_trail(t):
    if t.get("highway") not in TRAIL_HW:
        return False
    if t.get("footway") in ("sidewalk", "crossing") or t.get("path") == "sidewalk":
        return False
    if t.get("access") in ("private", "no"):
        return False
    mtb = "mtb:scale" in t or "mtb:scale:imba" in t or "mtb:name" in t
    bike = t.get("bicycle") in ("designated", "yes", "permissive")
    if t.get("highway") == "track":
        return mtb
    if t.get("highway") == "footway":
        return mtb or (bike and "name" in t)
    return mtb or bike or "name" in t

def get_trails():
    return [way_line(e) for e in load("trails") if e["type"] == "way" and is_trail(e.get("tags", {}))]

MAJOR = {"motorway", "trunk", "primary", "secondary", "tertiary"}

def get_roads():
    major, minor = [], []
    for e in load("roads"):
        if e["type"] != "way":
            continue
        hw = e.get("tags", {}).get("highway", "")
        if hw == "service":
            continue
        (major if hw.split("_")[0] in MAJOR else minor).append(way_line(e))
    return major, minor

def get_water():
    polys, streams = [], []
    for e in load("water"):
        t = e.get("tags", {})
        if e["type"] == "way" and t.get("waterway") in ("river", "stream"):
            streams.append(way_line(e))
        elif e["type"] == "way" and t.get("natural") == "water":
            ln = way_line(e)
            if len(ln.coords) >= 4 and ln.is_ring:
                polys.append(Polygon(ln.coords))
        elif e["type"] == "relation":
            polys.append(rel_polys(e))
    return unary_union([p.buffer(0) for p in polys]), streams

def get_city():
    rels = [e for e in load("boundary") if e["type"] == "relation"]
    return unary_union([rel_polys(r) for r in rels])

# ----------------------------------------------------------------- elevation (AWS terrarium tiles)
def deg2tile(lat, lon, z):
    n = 2 ** z
    x = (lon + 180) / 360 * n
    y = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n
    return x, y

def get_dem(lonlat_bounds, z):
    """Return (elev_m array, lon/lat-of-pixel function) covering bounds."""
    w, s, e, n = lonlat_bounds
    x0, y0 = deg2tile(n, w, z); x1, y1 = deg2tile(s, e, z)
    tx0, ty0, tx1, ty1 = int(x0), int(y0), int(x1), int(y1)
    cache = DATA / "dem"; cache.mkdir(exist_ok=True)
    rows = []
    for ty in range(ty0, ty1 + 1):
        row = []
        for tx in range(tx0, tx1 + 1):
            f = cache / f"{z}_{tx}_{ty}.png"
            if not f.exists():
                url = f"https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{tx}/{ty}.png"
                f.write_bytes(requests.get(url, timeout=60).content)
            a = np.asarray(Image.open(f).convert("RGB"), dtype=np.float64)
            row.append(a[..., 0] * 256 + a[..., 1] + a[..., 2] / 256 - 32768)
        rows.append(np.hstack(row))
    dem = np.vstack(rows)
    def px_to_lonlat(r, c):
        n2 = 2 ** z
        X = tx0 + c / 256.0; Y = ty0 + r / 256.0
        lon = X / n2 * 360 - 180
        lat = np.degrees(np.arctan(np.sinh(np.pi * (1 - 2 * Y / n2))))
        return lon, lat
    return dem, px_to_lonlat

def contour_lines(dem, px2ll, levels_m, smooth=1.0):
    from scipy.ndimage import gaussian_filter
    d = gaussian_filter(dem, smooth) if smooth else dem
    out = {}
    for lv in levels_m:
        lines = []
        for c in measure.find_contours(d, lv):
            if len(c) < 8:
                continue
            lon, lat = px2ll(c[:, 0], c[:, 1])
            xs, ys = TO_UTM.transform(lon, lat)
            lines.append(LineString(zip(xs, ys)))
        out[lv] = lines
    return d, out

def contour_polys(d, px2ll, level):
    """Filled region where elevation >= level, as UTM polygons."""
    pad = np.pad(d, 1, constant_values=d.min() - 100)
    polys = []
    for c in measure.find_contours(pad, level):
        if len(c) < 4:
            continue
        lon, lat = px2ll(c[:, 0] - 1, c[:, 1] - 1)
        xs, ys = TO_UTM.transform(lon, lat)
        p = Polygon(zip(xs, ys)).buffer(0)
        if not p.is_empty:
            polys.append(p)
    # even-odd assembly: nested rings alternate solid / hole
    polys.sort(key=lambda p: -p.area)
    result = Polygon()
    for p in polys:
        result = result.symmetric_difference(p)
    return result.buffer(0)

# ----------------------------------------------------------------- SVG writer
def _rings(g):
    if g.is_empty:
        return
    if isinstance(g, Polygon):
        yield g.exterior.coords
        for i in g.interiors:
            yield i.coords
    elif isinstance(g, LineString):
        yield g.coords
    elif hasattr(g, "geoms"):
        for sub in g.geoms:
            yield from _rings(sub)

def path_d(g, closed):
    parts = []
    for coords in _rings(g):
        pts = list(coords)
        if len(pts) < 2:
            continue
        s = "M" + " L".join(f"{x:.3f},{y:.3f}" for x, y in pts)
        parts.append(s + ("Z" if closed and isinstance(g, (Polygon, MultiPolygon)) or closed else ""))
    return " ".join(parts)

class SVG:
    def __init__(self, w, h):
        self.w, self.h, self.items = w, h, []
    def add(self, g, color, closed=True, fill="none", width=0.1):
        if g is None or g.is_empty:
            return
        self.items.append(f'<path d="{path_d(g, closed)}" fill="{fill}" stroke="{color}" '
                          f'stroke-width="{width}" fill-rule="evenodd"/>')
    def save(self, f):
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}mm" height="{self.h}mm" '
            f'viewBox="0 0 {self.w} {self.h}">\n' + "\n".join(self.items) + "\n</svg>\n",
            encoding="utf-8")

CUT, SCORE, LIGHT, REG, TRAIL, ENGRAVE = "#FF0000", "#0000FF", "#00A000", "#FF00FF", "#FF8000", "#000000"
GUIDE = "#B4B4B4"   # glue guides (light engrave), LightBurn layer 08

# ----------------------------------------------------------------- text
def text_geom(s, height_mm, weight="bold", family="DejaVu Serif"):
    from matplotlib.textpath import TextPath
    from matplotlib.font_manager import FontProperties
    tp = TextPath((0, 0), s, size=100, prop=FontProperties(family=family, weight=weight))
    polys = []
    for verts in tp.to_polygons():
        if len(verts) >= 3:
            polys.append(Polygon(verts).buffer(0))
    # even-odd fill for letter counters
    polys.sort(key=lambda p: -p.area)
    g = Polygon()
    for p in polys:
        g = g.symmetric_difference(p)
    minx, miny, maxx, maxy = g.bounds
    sc = height_mm / (maxy - miny)
    g = affinity.translate(g, -minx, -miny)
    g = affinity.scale(g, sc, -sc, origin=(0, 0))       # flip y for SVG
    return affinity.translate(g, 0, height_mm)

# ----------------------------------------------------------------- main
def clean_polys(g, min_area):
    keep = []
    for p in getattr(g, "geoms", [g]):
        if not isinstance(p, Polygon) or p.area < min_area:
            continue
        holes = [h for h in p.interiors if Polygon(h).area >= min_area]
        keep.append(Polygon(p.exterior, holes))
    return unary_union(keep)

# ----------------------------------------------------------------- poster typography
FONT_DIR = Path("C:/Windows/Fonts")
FONTS = {"display": "impact.ttf", "narrow": "ARIALNB.TTF", "plain": "bahnschrift.ttf"}

def font(name):
    from matplotlib.font_manager import FontProperties
    f = FONT_DIR / FONTS[name]
    fp = FontProperties(fname=str(f)) if f.exists() else FontProperties(family="DejaVu Sans", weight="bold")
    fp.set_size(100)
    return fp

def _even_odd(polys):
    polys = sorted([p for p in polys if not p.is_empty], key=lambda p: -p.area)
    g = Polygon()
    for p in polys:
        g = g.symmetric_difference(p)
    return g.buffer(0)

def text_shape(s, cap_h, fontname="display", tracking=0.0):
    """Text outline, y-down, cap height = cap_h mm. tracking = extra space per letter (x cap height)."""
    from matplotlib.textpath import TextPath, text_to_path
    fp = font(fontname)
    ref = TextPath((0, 0), "H", prop=fp).get_extents()
    chunks = [s] if tracking == 0 else list(s)
    x, polys = 0.0, []
    for ch in chunks:
        if ch.strip():
            tp = TextPath((x, 0), ch, prop=fp)
            polys += [Polygon(v).buffer(0) for v in tp.to_polygons() if len(v) >= 3]
        w = text_to_path.get_text_width_height_descent(ch, fp, ismath=False)[0]
        x += w + tracking * ref.height
    g = _even_odd(polys)
    sc = cap_h / ref.height
    return affinity.scale(g, sc, -sc, origin=(0, ref.y1))   # cap top -> y=0 (after translate below)

def place(g, x, y, align="left"):
    """Move g so its top edge is at y and its left/center/right is at x."""
    x0, y0, x1, _ = g.bounds
    ax = {"left": x0, "center": (x0 + x1) / 2, "right": x1}[align]
    return affinity.translate(g, x - ax, y - y0)

# ----------------------------------------------------------------- poster artwork
def pine(h, rng):
    """Pine tree silhouette, y-up, base at (0,0)."""
    parts = [box(-0.035 * h, -0.03 * h, 0.035 * h, 0.18 * h)]
    n = 7
    for i in range(n):
        t = i / n
        yb = 0.12 * h + t * 0.74 * h
        yt = min(h, yb + 0.27 * h * (1 - 0.3 * t))
        w = (0.27 - 0.21 * t) * h * rng.uniform(0.88, 1.12)
        parts.append(Polygon([
            (-w, yb), (-0.5 * w, yb + 0.42 * (yt - yb)), (0, yt), (0.5 * w, yb + 0.42 * (yt - yb)),
            (w, yb), (0.45 * w, yb + 0.05 * h), (0, yb + 0.035 * h), (-0.45 * w, yb + 0.05 * h)]))
    return unary_union(parts)

BIKE_WB = 3.34   # wheelbase in wheel radii

def bike(r):
    """Full-suspension mountain bike silhouette, y-up, rear hub at (0,0), wheel radius r.
    One connected piece: wheels join the frame through spokes and hubs."""
    from shapely.geometry import Point
    def tube(pts, w):
        return LineString(pts).buffer(w, cap_style="round", join_style="round")
    rear, front = (0.0, 0.0), (BIKE_WB, 0.0)
    bb = (1.16, -0.08)
    parts = []
    for c in (rear, front):
        P = Point(c)
        parts.append(P.buffer(0.955).difference(P.buffer(0.80)))              # tire + rim
        for a in np.radians(np.arange(0, 360, 7.5)):                         # knobs
            knob = box(-0.022, 0.94, 0.022, 1.0).buffer(0.008)
            parts.append(affinity.translate(affinity.rotate(knob, np.degrees(a), origin=(0, 0)), *c))
        for a in np.radians(np.arange(0, 360, 30) + 7):                      # spokes
            parts.append(tube([c, (c[0] + 0.82 * np.cos(a), c[1] + 0.82 * np.sin(a))], 0.022))
        parts.append(P.buffer(0.27).difference(P.buffer(0.21)))                # disc rotor
        parts.append(P.buffer(0.09))                                         # hub
    parts += [
        Point(rear).buffer(0.2),                                             # cassette
        Polygon([(-0.02, -0.12), (0.1, -0.16), (0.05, -0.42), (-0.07, -0.4)]),  # derailleur
        tube([rear, bb], 0.06),                                              # chainstay
        tube([rear, (1.19, 0.65)], 0.05),                                    # seatstay
        tube([(1.19, 0.65), (1.11, 0.86)], 0.045),                           # seatstay to rocker
        Polygon([(1.04, 1.01), (1.38, 1.0), (1.11, 0.83)]),                  # rocker link
        tube([(1.19, 0.65), (1.75, 1.03)], 0.042),                           # shock shaft (rises forward)
        tube([(1.42, 0.81), (1.71, 1.0)], 0.085),                            # shock body / air can
        tube([(1.75, 1.03), (1.78, 1.22)], 0.05),                            # shock mount on top tube
        Point((1.19, 0.65)).buffer(0.065),                                   # lower shock eyelet
        tube([bb, (1.0, 0.9), (0.86, 1.52)], 0.07),                          # seat tube (kinked)
        tube([(0.98, 1.0), (1.44, 1.07)], 0.07),                             # seat-tube brace
        tube([(0.86, 1.52), (0.77, 1.72)], 0.04),                            # dropper post
        Polygon([(0.4, 1.78), (0.62, 1.73), (1.0, 1.75), (1.15, 1.8),
                 (1.0, 1.84), (0.6, 1.83), (0.42, 1.83)]),                   # saddle
        tube([(2.62, 1.7), (1.42, 1.06)], 0.08),                             # top tube
        tube([(2.72, 1.46), (2.2, 1.0), (1.76, 0.4), (1.5, 0.1), (1.18, -0.04)], 0.11),  # down tube
        tube([(2.62, 1.8), (2.8, 1.28)], 0.085),                             # head tube
        tube([(2.8, 1.28), (3.0, 0.8)], 0.065),                              # fork stanchion
        tube([(2.98, 0.85), (BIKE_WB, 0.0)], 0.085),                         # fork lower
        tube([(2.62, 1.8), (2.72, 1.94)], 0.05),                             # stem
        tube([(2.5, 2.03), (2.88, 1.95)], 0.045),                            # bars
        tube([(2.48, 2.04), (2.6, 2.01)], 0.07),                             # grip
        Point(bb).buffer(0.17).difference(Point(bb).buffer(0.1)),            # chainring
        Point(bb).buffer(0.07),
        tube([bb, (1.42, -0.24)], 0.045),                                    # crank
        box(1.32, -0.29, 1.56, -0.22),                                       # pedal
    ]
    g = unary_union(parts)
    return affinity.scale(g, r, r, origin=(0, 0))

def traced_silhouette(path, length_mm):
    """Trace a dark-on-light silhouette image (PNG/JPG) into a polygon, y-down,
    scaled to length_mm wide, bottom-left at (0,0)."""
    a = np.asarray(Image.open(path).convert("L"), dtype=float)
    mask = np.pad(a < 128, 2)
    polys = []
    for c in measure.find_contours(mask.astype(float), 0.5):
        if len(c) >= 4:
            polys.append(Polygon(c[:, ::-1]).buffer(0))
    g = _even_odd(polys).simplify(0.6)
    x0, y0, x1, y1 = g.bounds
    sc = length_mm / (x1 - x0)
    g = affinity.scale(affinity.translate(g, -x0, -y1), sc, sc, origin=(0, 0))
    return g

def north_arrow(h):
    """North arrow, y-down, tip at (0,0)."""
    return Polygon([(0, 0), (0.42 * h, h), (0, 0.72 * h), (-0.42 * h, h)])

def ridge(xs, base, amp, seed, waves=(260, 140, 70, 33)):
    rng = np.random.default_rng(seed)
    y = np.zeros_like(xs)
    for i, lam in enumerate(waves):
        y += np.sin(2 * np.pi * xs / lam + rng.uniform(0, 2 * np.pi)) / (i + 1)
    y = (y - y.min()) / (y.max() - y.min())
    return base - amp * y          # y-down: larger amp = taller hills

# ----------------------------------------------------------------- obstacle raster (fast placement)
class Occupancy:
    def __init__(self, g, W, H, res=1.0):
        import shapely
        self.res = res
        xs = np.arange(0, W, res) + res / 2
        ys = np.arange(0, H, res) + res / 2
        X, Y = np.meshgrid(xs, ys)
        m = np.zeros(X.shape, bool)
        if not g.is_empty:
            shapely.prepare(g)
            m = shapely.contains_xy(g, X.ravel(), Y.ravel()).reshape(X.shape)
        self.m = m
        self._sum()
    def _sum(self):
        self.S = np.pad(self.m.cumsum(0).cumsum(1), ((1, 0), (1, 0)))
    def add(self, b):
        x0, y0, x1, y1 = (max(0, int(round(v / self.res))) for v in b)
        self.m[y0:y1, x0:x1] = True
        self._sum()
    def count(self, b):
        x0, y0, x1, y1 = (int(round(v / self.res)) for v in b)
        x0, y0 = max(x0, 0), max(y0, 0)
        x1, y1 = min(x1, self.m.shape[1]), min(y1, self.m.shape[0])
        if x1 <= x0 or y1 <= y0:
            return 0
        S = self.S
        return S[y1, x1] - S[y0, x1] - S[y1, x0] + S[y0, x0]
    def lowest(self, y_from):
        """Per-column lowest occupied y (mm) at or below y_from, else -inf."""
        r0 = int(y_from / self.res)
        sub = self.m[r0:]
        has = sub.any(0)
        last = sub.shape[0] - 1 - np.argmax(sub[::-1], 0)
        return np.where(has, (r0 + last + 1) * self.res, -np.inf)

def find_spot(occ, bbox, region, anchor, step=3.0):
    bx0, by0, bx1, by1 = bbox
    rx0, ry0, rx1, ry1 = region
    best = None
    for dx in np.arange(rx0 - bx0, rx1 - bx1 + 1e-6, step):
        for dy in np.arange(ry0 - by0, ry1 - by1 + 1e-6, step):
            hit = occ.count((bx0 + dx, by0 + dy, bx1 + dx, by1 + dy))
            cx, cy = (bx0 + bx1) / 2 + dx, (by0 + by1) / 2 + dy
            score = hit * 1000 + math.hypot(cx - anchor[0], cy - anchor[1])
            if best is None or score < best[0]:
                best = (score, dx, dy, hit)
    return best[1], best[2], best[3]

# ----------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stacked", type=int, default=0, help="also output N stacked topo layers")
    ap.add_argument("--no-clip", action="store_true", help="don't clip trails to city limits")
    ap.add_argument("--portrait", action="store_true")
    ap.add_argument("--lines", action="store_true", help="single scored trail lines instead of raised strips")
    ap.add_argument("--size", help="board size in inches, e.g. 24x24 or 18x24")
    args = ap.parse_args()
    C = dict(CFG)
    raised = not args.lines
    if args.size:
        C["board_w"], C["board_h"] = (float(v) * 25.4 for v in args.size.lower().split("x"))
    if args.portrait:
        C["board_w"], C["board_h"] = C["board_h"], C["board_w"]
    W, H = C["board_w"], C["board_h"]
    f = min(W, H) / 609.6                       # artwork sizes are designed for 24"
    rng = np.random.default_rng(C["seed"])

    print("loading OSM...")
    trails = get_trails()
    major, minor = get_roads()
    lakes, streams = get_water()
    city = get_city()
    T = unary_union(trails)
    if C["clip_to_city"] and not args.no_clip and not city.is_empty:
        T = T.intersection(city.buffer(C["city_buffer_m"]))
    print(f"  trails: {T.length/1609.34:.0f} mi")

    inset = C["frame_w"] - C["frame_lip"]
    vis = box(inset, inset, W - inset, H - inset)
    board = box(0, 0, W, H)
    mg = C["margin"]

    # ---- header: BELLA VISTA / -- ARKANSAS -- / tagline
    top = inset + 16 * f
    probe = text_shape(C["title"], 100, "display")
    th = min(C["title_max"] * f, 0.82 * (W - 2 * inset) / (probe.bounds[2] - probe.bounds[0]) * 100)
    title = place(text_shape(C["title"], th, "display"), W / 2, top, "center")
    y = title.bounds[3] + 0.16 * th
    sub = place(text_shape(C["subtitle"], 0.17 * th, "narrow", tracking=0.5), W / 2, y, "center")
    sx0, sy0, sx1, sy1 = sub.bounds
    ym, rl, gap, rt = (sy0 + sy1) / 2, 0.9 * th, 0.15 * th, 0.6 * f
    rules = unary_union([box(sx0 - gap - rl, ym - rt, sx0 - gap, ym + rt),
                         box(sx1 + gap, ym - rt, sx1 + gap + rl, ym + rt)])
    tag = place(text_shape(C["tagline"], 0.105 * th, "plain", tracking=0.4), W / 2,
                sy1 + 0.13 * th, "center")
    header_bottom = tag.bounds[3] + 12 * f
    # ---- mileage per system (split east/west at a meridian)
    split_x = TO_UTM.transform(C["system_split_lon"], 36.45)[0]
    big = 1e7
    side_miles = {
        "left": T.intersection(box(-big, -big, split_x, big)).length / 1609.34,
        "right": T.intersection(box(split_x, -big, big, big)).length / 1609.34,
    }

    # ---- trail-system panels + north arrow (built unplaced)
    def make_panel(sysdef):
        side = sysdef["side"]
        miles = sysdef.get("miles") or side_miles[side]
        al = "left" if side == "left" else "right"
        rows_cut, rows_eng, yy = [], [], 0.0
        for line in sysdef["name"].split("\n"):
            g = place(text_shape(line, 24 * f, "display"), 0, yy, al)
            rows_cut.append(g); yy = g.bounds[3] + 5.5 * f
        nw = max(g.bounds[2] - g.bounds[0] for g in rows_cut)
        rows_eng.append(place(box(0, 0, nw, 1.2 * f), 0, yy + 1.5 * f, al)); yy += 10 * f
        num = place(text_shape(f"{miles:.0f}", 28 * f, "display"), 0, yy, al)
        rows_cut.append(num)
        lx = num.bounds[2] + 5 * f if al == "left" else num.bounds[0] - 5 * f
        rows_eng += [place(text_shape("MILES", 7.5 * f, "narrow", tracking=0.25), lx, num.bounds[1] + 3 * f, al),
                     place(text_shape("OF TRAIL", 7.5 * f, "narrow", tracking=0.25), lx, num.bounds[1] + 16 * f, al)]
        print(f"  {sysdef['name'].replace(chr(10), ' ')}: {miles:.0f} mi")
        return unary_union(rows_cut), unary_union(rows_eng)

    inner = (inset + mg, header_bottom, W - inset - mg, H - inset - mg)
    ih = inner[3] - inner[1]
    groups = []   # (cut, engrave, search region, anchor)
    for sysdef in C["systems"]:
        cut, eng = make_panel(sysdef)
        if sysdef["side"] == "left":
            groups.append((cut, eng, (inner[0], inner[1], W / 2, inner[1] + 0.6 * ih), (inner[0], inner[1])))
        else:
            groups.append((cut, eng, (W / 2, inner[1], inner[2], inner[1] + 0.6 * ih), (inner[2], inner[1])))
    ah = 30 * f
    nlet = place(text_shape("N", 9 * f, "narrow"), 0, -13 * f, "center")
    groups.append((north_arrow(ah), nlet, (W * 0.6, inner[1], inner[2], inner[1] + 0.75 * ih),
                   (inner[2], inner[1] + 0.35 * ih)))

    # ---- fit trails between header and landscape; shrink the map until the panels fit beside it
    clear = 4 * f
    win = box(inset + mg, header_bottom, W - inset - mg, H - inset - C["scene_clear"] * f)
    tminx, tminy, tmaxx, tmaxy = T.bounds
    wx0, wy0, wx1, wy1 = win.bounds
    s_full = min((wx1 - wx0) / (tmaxx - tminx), (wy1 - wy0) / (tmaxy - tminy))
    cx, cy = (tminx + tmaxx) / 2, (tminy + tmaxy) / 2
    ox, oy = (wx0 + wx1) / 2, (wy0 + wy1) / 2

    def M(g, s_):
        g = affinity.translate(g, -cx, -cy)
        g = affinity.scale(g, s_, -s_, origin=(0, 0))
        return affinity.translate(g, ox, oy)

    header_band = box(inset, inset, W - inset, header_bottom - 4 * f)
    big_lakes = unary_union([p for p in getattr(lakes, "geoms", [lakes]) if p.area > 2e4])
    for shrink in np.arange(1.0, 0.70, -0.03):
        s = s_full * shrink
        obs = unary_union([M(T, s).buffer(C["trail_width"] / 2), M(big_lakes, s), header_band]).buffer(clear)
        occ = Occupancy(obs, W, H)
        spots, worst = [], 0
        for cut, eng, region, anchor in groups:
            bb = unary_union([cut, eng]).bounds
            dx, dy, hit = find_spot(occ, bb, region, anchor)
            worst = max(worst, hit)
            spots.append((dx, dy))
            occ.add((bb[0] + dx - 5 * f, bb[1] + dy - 5 * f, bb[2] + dx + 5 * f, bb[3] + dy + 5 * f))
        if worst == 0:
            break
    if worst:
        print("  warning: panels still overlap trails at the smallest map size")
    print(f"  map at {shrink:.0%} of max size; scale 1:{1000/s:,.0f}  ({1/s:.1f} m per mm)")

    raised_text, engraved, panel_boxes = [title], [sub, rules, tag], []
    for (cut, eng, _, _), (dx, dy) in zip(groups, spots):
        cut, eng = affinity.translate(cut, dx, dy), affinity.translate(eng, dx, dy)
        raised_text.append(cut); engraved.append(eng)
        panel_boxes.append(box(*unary_union([cut, eng]).bounds).buffer(5 * f))

    _M = M
    def M(g):
        return _M(g, s)

    def clip(g):
        return g.intersection(vis) if not g.is_empty else g

    # ---- trails
    Tm = M(T).simplify(C["trail_simplify"])
    trail_line = clip(Tm)
    if raised:
        strip = clip(clean_polys(Tm.buffer(C["trail_width"] / 2, quad_segs=6), C["min_hole_area"]))
        trail_obs = strip
    else:
        strip = Polygon()
        trail_obs = trail_line.buffer(1.0)

    # ---- base map
    lakes_m = clean_polys(clip(M(lakes)), C["min_lake_area"])
    if raised:
        lakes_m = clean_polys(lakes_m.difference(strip.buffer(0.8)), C["min_lake_area"])
    lakes_m = clean_polys(lakes_m.difference(header_band), C["min_lake_area"])
    roads_major = clip(M(unary_union(major)).simplify(C["road_simplify"]))
    roads_minor = clip(M(unary_union(minor)).simplify(C["road_simplify"]))
    stream_m = clip(M(unary_union(streams)).simplify(C["road_simplify"]))

    # ---- elevation contours
    inv = Transformer.from_crs("EPSG:32615", "EPSG:4326", always_xy=True)
    def board_to_ll(x, y):
        return inv.transform((x - ox) / s + cx, -(y - oy) / s + cy)
    lons, lats = zip(*[board_to_ll(x, y) for x, y in [(0, 0), (W, 0), (0, H), (W, H)]])
    dem, px2ll = get_dem((min(lons), min(lats), max(lons), max(lats)), C["dem_zoom"])
    contours_m, d = GeometryCollection(), None
    if C["contour_interval_ft"]:
        step = C["contour_interval_ft"] * 0.3048
        levels = np.arange(math.ceil(dem.min() / step) * step, dem.max(), step)
        d, cl = contour_lines(dem, px2ll, levels, smooth=1.2)
        contours_m = clip(M(unary_union([l for ls in cl.values() for l in ls])).simplify(0.2))
        print(f"  contours every {C['contour_interval_ft']} ft "
              f"({dem.min()*3.281:.0f}-{dem.max()*3.281:.0f} ft)")

    # ---- landscape scene: ridgelines kept below the lowest trail in every column
    occ_all = Occupancy(unary_union([trail_obs, *panel_boxes]).buffer(clear), W, H)
    xs = np.arange(0, W + 1, 1.0)
    low = occ_all.lowest(H * 0.3)
    low = np.interp(xs, np.arange(len(low)) + 0.5, low)
    from scipy.ndimage import maximum_filter1d, uniform_filter1d
    sm = int(45 * f) | 1
    need = uniform_filter1d(maximum_filter1d(low, sm), sm)    # smooth slopes, never above trails
    B = H - inset                                             # visible bottom edge
    def clamp(y):
        return np.maximum(y, need)

    far_y = clamp(ridge(xs, B - 95 * f, 55 * f, C["seed"] + 1))
    lake_c = W * 0.68
    valley = 34 * f * np.exp(-((xs - lake_c) / (0.11 * W)) ** 2)
    mid_y = clamp(ridge(xs, B - 52 * f, 38 * f, C["seed"] + 2, (190, 90, 45)) + valley)
    rock_c = inset + 195 * f
    rock_top = B - 40 * f                                     # flat-topped rock the bike stands on
    rock = rock_top + 70 * f * (1 - np.exp(-((xs - rock_c) / (75 * f)) ** 6))
    near_y = clamp(np.minimum(ridge(xs, B - 18 * f, 16 * f, C["seed"] + 3, (120, 60, 25)), rock))
    lake_top = clamp(np.full_like(xs, B - 58 * f) + 1.2 * f * np.sin(xs / 9))

    def band(yv, x0=0, x1=W):
        sel = (xs >= x0) & (xs <= x1)
        pts = list(zip(xs[sel], yv[sel]))
        return Polygon([(xs[sel][0], H)] + pts + [(xs[sel][-1], H)]).buffer(0)

    far = band(far_y)
    lake_piece = band(lake_top, lake_c - 0.2 * W, lake_c + 0.2 * W).intersection(
        box(0, 0, W, H).buffer(0)).difference(band(mid_y).buffer(-1.5 * f))   # small overlap for glue
    lake_piece = clean_polys(lake_piece.buffer(-0.01).buffer(0.01), 20)
    mid = band(mid_y)
    near = band(near_y)

    def ground(x, yv):
        return float(np.interp(x, xs, yv))

    def trees(spec, ground_y, layer_rng):
        out = []
        for x, hgt in spec:
            h = hgt * f * layer_rng.uniform(0.9, 1.1)
            w = 0.27 * h
            gy = ground(x, ground_y) + 2 * f
            sel = (xs >= x - w) & (xs <= x + w)
            room = gy - need[sel].max()
            h = min(h, room)
            if h < 28 * f:
                continue
            t = pine(h, layer_rng)
            out.append(affinity.translate(affinity.scale(t, 1, -1, origin=(0, 0)), x, gy))
        return out

    L, R = inset, W - inset
    near_trees = trees([(L + 14 * f, 215), (L + 42 * f, 165), (L + 66 * f, 235),
                        (R - 16 * f, 225), (R - 44 * f, 175), (R - 70 * f, 250), (R - 98 * f, 140)],
                       near_y, rng)
    mid_trees = trees([(L + 96 * f, 120), (L + 230 * f, 70), (R - 128 * f, 125), (R - 150 * f, 90),
                       (L + 260 * f, 60), (R - 210 * f, 70)], mid_y, rng)
    # bike on the rock (drawn, or traced from CFG["bike_image"])
    r = 21 * f
    blen = (BIKE_WB + 2) * r
    xl, xr = rock_c - blen / 2, rock_c + blen / 2
    gy = max(ground(xl + r, near_y), ground(xr - r, near_y)) + 1.0 * f
    if C.get("bike_image"):
        bk = affinity.translate(traced_silhouette(C["bike_image"], blen), xl, gy)
    else:
        bk = affinity.translate(affinity.scale(bike(r), 1, -1, origin=(0, 0)), xl + r, gy - r)
    if occ_all.count(bk.bounds):
        print("  warning: bike overlaps map features")
    near = unary_union([near, bk, *near_trees]).intersection(board)
    mid = unary_union([mid, *mid_trees]).intersection(board)
    far = far.intersection(board)
    scene = unary_union([far, mid, near])

    # ---- hide base engraving where it's covered or would clutter the lettering
    covered = unary_union([scene, header_band, *panel_boxes])
    hide = unary_union([covered, strip if raised else trail_line.buffer(C["trail_gap"]), lakes_m])
    roads_major = roads_major.difference(hide)
    roads_minor = roads_minor.difference(hide)
    stream_m = stream_m.difference(hide)
    contours_m = contours_m.difference(hide.buffer(0.6))
    lakes_m = clean_polys(lakes_m.difference(covered.buffer(2)), C["min_lake_area"])
    if raised:
        strip = clean_polys(strip.difference(covered), C["min_hole_area"])
    trail_line = trail_line.difference(covered)
    lettering = unary_union(raised_text)
    engrave = unary_union(engraved)

    # ---- write files
    OUT.mkdir(exist_ok=True)
    for old in OUT.glob("*.svg"):
        old.unlink()
    frame = board.difference(vis)

    # ---- build-up (see .claude/skills/layer-buildup): the scene layers and the frame stack on the base
    # (base -> far -> lake -> mid -> near -> frame). Each layer also carries the footprint of everything
    # above it, so the tall pines, the bike and the frame sit on solid wood all the way down instead of
    # over air. Trails and lettering sit straight on the full base, so they need no build-up.
    from layer_stack import build_up, glue_guides, unsupported
    own = [[far], [lake_piece], [mid], [near], [frame]]
    for k, a in unsupported([unary_union(o) for o in [[board]] + own]):
        print(f"  build-up: {['base', 'far', 'lake', 'mid', 'near', 'frame'][k]} overhung the layer "
              f"below by {a/100:.0f} cm^2 -> now supported")
    cuts = build_up(own)
    assert not list(unsupported([[board]] + cuts))
    far_c, lake_c_, mid_c, near_c, frame_c = (unary_union(c) for c in cuts)
    base_cut = board.difference(lakes_m)
    # glue guides: on each layer, mark where the next layer's pieces go. The board edge and the
    # frame's inner edge register by themselves, so they get no guide.
    keep_out = unary_union([board.boundary.buffer(0.9), vis.boundary.buffer(0.9)])
    g_stack = glue_guides([[base_cut]] + cuts, keep_out=[keep_out])
    g_letters = glue_guides([[base_cut], [lettering]])[0]
    base_guide = unary_union([g for g in (g_stack[0], g_letters) if g is not None])
    guides = dict(base=base_guide, far=g_stack[1], lake=g_stack[2], mid=g_stack[3], near=g_stack[4])

    def write(name, *items):
        sv = SVG(W, H)
        for g, col, kw in items:
            sv.add(g, col, **kw)
        sv.save(OUT / name)

    write("0_backer.svg", (board, CUT, {}))
    base_items = [(contours_m, LIGHT, dict(closed=False)), (stream_m, LIGHT, dict(closed=False)),
                  (roads_minor, SCORE, dict(closed=False)), (roads_major, SCORE, dict(closed=False, width=0.2)),
                  (engrave, ENGRAVE, dict(fill=ENGRAVE, width=0))]
    if not raised:
        base_items.append((trail_line, TRAIL, dict(closed=False, width=0.4)))
    base_items += [(base_guide, GUIDE, dict(fill=GUIDE, width=0)), (lakes_m, CUT, {}), (board, CUT, {})]
    write("1_base.svg", *base_items)
    if raised:
        write("2_trails.svg", (strip, CUT, {}), (board, REG, {}))
    write("3_lettering.svg", (lettering, CUT, {}), (board, REG, {}))
    # scene layers now include the frame spacer ring, so their outer edge is a real cut (no magenta needed)
    write("4_scene_far.svg", (guides["far"], GUIDE, dict(fill=GUIDE, width=0)), (far_c, CUT, {}))
    write("5_scene_lake.svg", (guides["lake"], GUIDE, dict(fill=GUIDE, width=0)), (lake_c_, CUT, {}))
    write("6_scene_mid.svg", (guides["mid"], GUIDE, dict(fill=GUIDE, width=0)), (mid_c, CUT, {}))
    write("7_scene_near.svg", (guides["near"], GUIDE, dict(fill=GUIDE, width=0)), (near_c, CUT, {}))
    write("8_frame.svg", (frame, CUT, {}))
    layers_preview(W, H, [("1 base", base_cut, base_guide), ("4 far", far_c, guides["far"]),
                          ("5 lake", lake_c_, guides["lake"]), ("6 mid", mid_c, guides["mid"]),
                          ("7 near", near_c, guides["near"]), ("8 frame", frame_c, None)])

    # ---- optional stacked topo layers
    if args.stacked:
        if d is None:
            from scipy.ndimage import gaussian_filter
            d = gaussian_filter(dem, 1.2)
        lv = np.linspace(d.min(), d.max(), args.stacked + 2)[1:-1]
        regs = []
        (OUT / "topo").mkdir(exist_ok=True)
        for old in (OUT / "topo").glob("*.svg"):
            old.unlink()
        for Lv in lv:
            regs.append(clean_polys(clip(M(contour_polys(d, px2ll, Lv))), 20))
        tcuts = build_up([[r] for r in regs])                 # higher levels always sit on lower ones
        regs = [unary_union(c) for c in tcuts]
        tguides = glue_guides(tcuts, keep_out=[board.boundary.buffer(0.9)])
        for i, (Lv, reg, gd) in enumerate(zip(lv, regs, tguides), 1):
            write(f"topo/topo_{i:02d}_{Lv*3.281:.0f}ft.svg", (gd, GUIDE, dict(fill=GUIDE, width=0)), (reg, CUT, {}))
        topo_preview(W, H, regs, strip if raised else trail_line.buffer(0.5))
        print(f"  wrote {args.stacked} stacked topo layers")

    preview(W, H, dict(frame=frame, lakes=lakes_m, rmaj=roads_major, rmin=roads_minor,
                       streams=stream_m, contours=contours_m, strip=strip,
                       trail_line=None if raised else trail_line, engrave=engrave,
                       lettering=lettering, far=far, lake=lake_piece, mid=mid, near=near))
    print("done ->", OUT)
    if raised:
        print(f"  trail layer: {len(getattr(strip, 'geoms', [strip]))} pieces, "
              f"cut length {strip.boundary.length/1000:.1f} m")
    print(f"  base layer: {len(getattr(lakes_m, 'geoms', [lakes_m]))} lake holes, "
          f"score length {(roads_major.length + roads_minor.length)/1000:.1f} m")

# ----------------------------------------------------------------- previews
PAL = dict(backer="#3f6e86", base="#efe7d2", contour="#d8ceb4", road="#c3b89d", stream="#9fb6c4",
           trail="#1f3a2b", text="#1f3a2b", engrave="#2c3a30", far="#a9b9bb", lake="#5f8ea6",
           mid="#6f8c69", near="#22392a", frame="#1b3326")

def _patch(ax, g, **kw):
    from matplotlib.patches import PathPatch
    from matplotlib.path import Path as MPath
    for p in getattr(g, "geoms", [g]):
        if not isinstance(p, Polygon) or p.is_empty:
            continue
        verts, codes = [], []
        for ring in [p.exterior, *p.interiors]:
            c = list(ring.coords)
            verts += c; codes += [MPath.MOVETO] + [MPath.LINETO] * (len(c) - 2) + [MPath.CLOSEPOLY]
        ax.add_patch(PathPatch(MPath(verts, codes), **kw))

def _lines(ax, g, **kw):
    for l in getattr(g, "geoms", [g]):
        if isinstance(l, LineString) and not l.is_empty:
            x, y = l.xy; ax.plot(x, y, **kw)

def preview(W, H, L):
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig = plt.figure(figsize=(W / 25.4, H / 25.4), dpi=150)
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, W); ax.set_ylim(H, 0); ax.axis("off")
    ax.add_patch(plt.Rectangle((0, 0), W, H, color=PAL["backer"]))
    _patch(ax, box(0, 0, W, H).difference(L["lakes"]), color=PAL["base"], lw=0)
    _lines(ax, L["contours"], color=PAL["contour"], lw=0.35)
    _lines(ax, L["rmin"], color=PAL["road"], lw=0.3)
    _lines(ax, L["rmaj"], color=PAL["road"], lw=0.8)
    _lines(ax, L["streams"], color=PAL["stream"], lw=0.4)
    _patch(ax, L["engrave"], color=PAL["engrave"], lw=0)
    shadow = dict(color="#00000030", lw=0)
    def raised(g, col):
        _patch(ax, affinity.translate(g, 0.6, 0.8), **shadow)
        _patch(ax, g, color=col, lw=0)
    if L["trail_line"] is not None:
        _lines(ax, L["trail_line"], color=PAL["trail"], lw=1.1)
    else:
        raised(L["strip"], PAL["trail"])
    raised(L["lettering"], PAL["text"])
    raised(L["far"], PAL["far"])
    raised(L["lake"], PAL["lake"])
    raised(L["mid"], PAL["mid"])
    raised(L["near"], PAL["near"])
    raised(L["frame"], PAL["frame"])
    fig.savefig(OUT / "preview.png"); plt.close(fig)

def layers_preview(W, H, layers):
    """Cut sheet check: each stacked layer's cut outline with its glue guides in gray."""
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(2, 3, figsize=(15, 10 * H / W + 0.6), dpi=80)
    for ax, (name, cut, guide) in zip(axes.flat, layers):
        ax.set_xlim(0, W); ax.set_ylim(H, 0); ax.set_aspect("equal"); ax.axis("off")
        _patch(ax, cut, fc="#efe7d2", ec="#d00000", lw=0.5)
        if guide is not None:
            _patch(ax, guide, fc="#555555", lw=0)
        ax.set_title(name)
    fig.tight_layout()
    fig.savefig(OUT / "layers_preview.png", facecolor="white"); plt.close(fig)

def topo_preview(W, H, regs, strip):
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig = plt.figure(figsize=(W / 25.4, H / 25.4), dpi=60)
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, W); ax.set_ylim(H, 0); ax.axis("off")
    ax.add_patch(plt.Rectangle((0, 0), W, H, color="#e8dcc4"))
    cmap = plt.get_cmap("YlOrBr")
    for i, g in enumerate(regs):
        _patch(ax, g, fc=cmap(0.15 + 0.7 * i / max(1, len(regs))), ec="#00000055", lw=0.3)
    _patch(ax, strip, fc="#2a5d34", lw=0)
    fig.savefig(OUT / "topo" / "topo_preview.png"); plt.close(fig)

if __name__ == "__main__":
    main()
