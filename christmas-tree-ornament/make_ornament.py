"""Layered Christmas tree ornament: a round bauble with a night scene of a decorated pine
in the snow, built from five stacked laser-cut layers.

Every layer shares the same outer rim and hanger cap, so the layers register by their edge
and the stack is solid all the way round.

  1 back      disk + cap. Engrave stars on the front (sky).
  1b message  engrave on the back of disk 1 (own layer/pass, with a jig outline to hold it face-down)
  2 hills     rim + snowy hills with little pines, plus a crescent moon
  3 tree      rim + the big tree (its trunk joins the rim under the snow, so it self-aligns)
  4 snow+deco rim + back snow drift, plus the star and garland strands (separate pieces)
  5 front     rim + front snow drift, scored cap band

Outputs (output/):
  layer_N_*.svg         one file per layer; red = cut, black = engrave, blue = score,
                        gray = glue guides; layer_1b: black = message, magenta = jig outline
  ornament_sheet.svg    all layers side by side on one sheet (message as its own panel); each uses its
                        own LightBurn palette colour so it imports as its own LightBurn layer
  preview.png           assembled front, back, and the cut sheet
"""
import argparse
import math
import random
from pathlib import Path

import numpy as np
from shapely import affinity
from shapely.geometry import Point, Polygon, LineString, MultiPolygon, box
from shapely.ops import unary_union

HERE = Path(__file__).resolve().parent
OUT = HERE / "output"

# Design units: millimetres for a 90 mm ornament (radius 45). Everything is scaled by --diameter.
R = 45.0        # outer radius
RIM = 4.0       # rim width
RI = R - RIM    # inner (window) radius

# Per-layer file colours (repo convention)
CUT, ENGRAVE, SCORE, REG = "#FF0000", "#000000", "#0000FF", "#FF00FF"   # REG = jig outline
GUIDE = "#B4B4B4"   # light engrave: glue/placement guides (LightBurn 08)
# LightBurn default palette colours for the combined sheet: one cut layer per ornament layer
LB_LAYER = ["#FF0000", "#00E000", "#D0D000", "#FF8000", "#00E0E0"]   # LightBurn 02..06
LB_ENGRAVE, LB_SCORE, LB_BACK = "#000000", "#0000FF", "#FF00FF"     # LightBurn 00, 01, 07

LAYER_NAMES = ["back", "hills", "tree", "snow_deco", "front"]
PAINT = dict(back="#16264a", hills="#e9eef2", moon="#f3e3a1", tree="#2f6b3a", snow="#f7fafc",
             deco="#c9a227", bauble="#b8282e", front="#ffffff", stars="#e8c98a", wood="#d9b98a")


# ------------------------------------------------------------------ geometry helpers
def star_poly(cx, cy, r_out, r_in=None, n=5, rot=90):
    r_in = r_out * 0.45 if r_in is None else r_in
    pts = []
    for i in range(2 * n):
        r = r_out if i % 2 == 0 else r_in
        a = math.radians(rot + i * 180 / n)
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return Polygon(pts)


def rounded_box(x0, y0, x1, y1, r):
    return box(x0 + r, y0 + r, x1 - r, y1 - r).buffer(r, quad_segs=16)


def cap_shape():
    # bauble cap: rounded block on top of the disk, flat where it meets the disk
    top = rounded_box(-8, 38, 8, 53, 3)
    return unary_union([top, box(-8, 38, 8, 46)])


HOLE = Point(0, 48.6).buffer(2.3, quad_segs=24)


def outline():
    return unary_union([Point(0, 0).buffer(R, quad_segs=64), cap_shape()]).difference(HOLE)


def rim():
    return outline().difference(Point(0, 0).buffer(RI, quad_segs=64))


def window():
    return Point(0, 0).buffer(RI, quad_segs=64)


def curve_region(f, below=True, x0=-R, x1=R, n=200):
    """Region below (or above) y = f(x)."""
    xs = np.linspace(x0, x1, n)
    top = [(x, f(x)) for x in xs]
    edge = -R - 5 if below else R + 5
    return Polygon(top + [(x1, edge), (x0, edge)])


def pine(cx, base_y, h, w):
    """Small flat-triangle pine for the hills (sunk into the hill so it joins it)."""
    return Polygon([(cx - w / 2, base_y - 2), (cx + w / 2, base_y - 2), (cx, base_y + h)])


# ------------------------------------------------------------------ scene
def hills_line(x):
    return (-7 + 6.0 * math.exp(-((x + 24) / 14) ** 2) + 4.0 * math.exp(-((x - 26) / 12) ** 2)
            - 0.04 * abs(x))


def snow_back_line(x):
    return -24 + 1.6 * math.sin(x / 7.0) + 2.4 * math.exp(-((x + 18) / 10) ** 2) \
        + 1.8 * math.exp(-((x - 20) / 9) ** 2)


def snow_front_line(x):
    return -30.5 + 1.4 * math.sin(x / 5.5 + 1.2) + 3.2 * math.exp(-((x - 24) / 9) ** 2) \
        + 2.2 * math.exp(-((x + 28) / 8) ** 2)


def tree_shape():
    # (bottom y, half width, tip y) for each tier, bottom to top
    # Modern flat style: straight-edged triangles with flat bottoms, stacked so each tier's
    # corners poke out past the one below for a crisp sawtooth outline.
    tiers = [(-22, 22, 2), (-10, 17.5, 14), (1, 13, 24), (12, 8.5, 33)]
    parts = [Polygon([(-hw, yb), (hw, yb), (0, yt)]) for yb, hw, yt in tiers]
    trunk = box(-3, -R, 3, -18)           # runs down into the rim (hidden by snow)
    return unary_union(parts + [trunk]), tiers


def garlands(tree, tiers):
    """Straight slanted garland bands, one per tier, with round beads set on the band."""
    pieces, baubles = [], []
    for k, (yb, hw, yt) in enumerate(tiers[:3]):
        tier = Polygon([(-hw, yb), (hw, yb), (0, yt)]).buffer(-1.0, join_style=2)
        sgn = 1 if k % 2 == 0 else -1
        a = (-sgn * hw, yb + (yt - yb) * 0.55)       # high end, alternating sides
        b = (sgn * hw, yb + 2.4)                    # low end
        line = LineString([a, b])
        band = line.buffer(0.9, cap_style=2)
        beads = [Point(line.interpolate(d, normalized=True).coords[0]).buffer(1.7, quad_segs=16)
                 for d in (0.42, 0.6, 0.78)]
        beads = [p for p in beads if tier.buffer(-0.3).contains(p)]
        g = unary_union([band] + beads).intersection(tier)
        # keep only the biggest connected piece of each strand
        if isinstance(g, MultiPolygon):
            g = max(g.geoms, key=lambda p: p.area)
        pieces.append(g)
        baubles.extend(beads)
    return pieces, unary_union(baubles)


def build(seed=7):
    win = window()
    rim_g = rim()
    tree, tiers = tree_shape()
    tree = tree.intersection(outline().buffer(0)).union(rim_g)   # trunk joins rim
    hills = curve_region(hills_line).intersection(win)
    pines = unary_union([pine(-31, hills_line(-31) - 0.6, 9, 6.5), pine(-24, hills_line(-24) - 0.6, 12, 8),
                         pine(29, hills_line(29) - 0.6, 10, 7), pine(35, hills_line(35) - 0.6, 7, 5)])
    hills = unary_union([hills, pines.intersection(win)])
    moon = Point(-22, 23).buffer(7, quad_segs=32).difference(Point(-18.5, 25).buffer(6.2, quad_segs=32))
    top_star = star_poly(0, 33.5, 6.5, 2.9)
    garl, bauble_pts = garlands(tree_shape()[0], tiers)
    snow_back = curve_region(snow_back_line).intersection(win)
    snow_front = curve_region(snow_front_line).intersection(win)

    # visible sky on the back disk = window minus everything stacked in front
    cover = unary_union([hills, tree.intersection(win), moon, top_star, snow_back])
    sky = win.difference(cover.buffer(1.4)).buffer(-0.6)
    rng = random.Random(seed)
    stars, tries = [], 0
    placed = []
    while len(placed) < 34 and tries < 5000:
        tries += 1
        x, y = rng.uniform(-RI, RI), rng.uniform(-10, RI)
        big = rng.random() < 0.4
        r = rng.uniform(1.3, 2.3) if big else rng.uniform(0.45, 0.75)
        s = star_poly(x, y, r, r * 0.42, rot=90 + rng.uniform(-15, 15)) if big else Point(x, y).buffer(r, quad_segs=8)
        if not sky.contains(s) or any(Point(x, y).distance(Point(p)) < 4.5 for p in placed):
            continue
        placed.append((x, y))
        stars.append(s)
    stars = unary_union(stars)

    # What each layer adds to the picture (its visible features)
    own = [
        [outline()],
        [unary_union([rim_g, hills]), moon],
        [tree],
        [unary_union([rim_g, snow_back]), top_star] + garl,
        [unary_union([rim_g, snow_front])],
    ]
    # Build up from the top down: each layer also carries the footprint of everything above it,
    # so every piece (e.g. the star) sits on solid material all the way to the back.
    cuts, above = [None] * 5, Polygon()
    for k in range(4, -1, -1):
        merged = unary_union(own[k] + [above])
        cuts[k] = list(getattr(merged, "geoms", [merged]))     # touching shapes merge, others stay separate pieces
        above = merged

    # Glue guides: on the layer just below, engrave a thin band inside the outline of each piece
    # of the layer above, except where that edge is already a cut edge of the lower layer or the rim.
    guides = [None] * 5
    rim_edge = win.exterior.buffer(0.9)
    for k in range(4):
        upper = unary_union(cuts[k + 1])
        lower = unary_union(cuts[k])
        band = upper.difference(upper.buffer(-0.7, join_style=2))
        band = band.difference(lower.boundary.buffer(0.9)).difference(rim_edge).intersection(lower)
        band = unary_union([p for p in getattr(band, "geoms", [band]) if isinstance(p, Polygon) and p.area > 0.4])
        guides[k] = band if not band.is_empty else None

    names = ["back", "hills", "tree", "snow_deco", "front"]
    layers = [dict(name=n, cut=c, guide=g) for n, c, g in zip(names, cuts, guides)]
    layers[0]["engrave"] = stars
    layers[4]["score"] = LineString([(-8, 44.2), (8, 44.2)])
    paint = [(own[1][0], "hills"), (own[1][1], "moon"), (own[2][0], "tree"), (own[3][0], "snow"),
             (top_star, "deco")]
    return layers, dict(bauble_pts=bauble_pts, garlands=garl, paint=paint)


def text_geom(s, height, family):
    from matplotlib.textpath import TextPath
    from matplotlib.font_manager import FontProperties
    tp = TextPath((0, 0), s, size=100, prop=FontProperties(family=family, weight="bold"))
    polys = sorted([Polygon(v).buffer(0) for v in tp.to_polygons() if len(v) >= 3], key=lambda p: -p.area)
    g = Polygon()
    for p in polys:
        g = g.symmetric_difference(p)
    minx, miny, maxx, maxy = g.bounds
    sc = height / (maxy - miny)
    g = affinity.scale(affinity.translate(g, -(minx + maxx) / 2, -(miny + maxy) / 2), sc, sc, origin=(0, 0))
    return g


def back_message(lines, family):
    """Centered message for the back face. Fits each line into the disk."""
    if not lines:
        return None
    heights = [7.0 if i != 1 else 9.0 for i in range(len(lines))]
    gap = 4.0
    total = sum(heights) + gap * (len(lines) - 1)
    y = total / 2
    parts = []
    for s, h in zip(lines, heights):
        g = text_geom(s, h, family)
        cy = y - h / 2
        half_chord = math.sqrt(max(RI ** 2 - (abs(cy) + h / 2) ** 2, 1)) - 3
        w = g.bounds[2] - g.bounds[0]
        if w / 2 > half_chord:
            g = affinity.scale(g, half_chord * 2 / w, half_chord * 2 / w, origin=(0, 0))
        parts.append(affinity.translate(g, 0, cy))
        y -= h + gap
    return unary_union(parts)


# ------------------------------------------------------------------ SVG output
def _rings(g):
    if isinstance(g, Polygon):
        yield g.exterior.coords
        for i in g.interiors:
            yield i.coords
    elif isinstance(g, LineString):
        yield g.coords
    elif hasattr(g, "geoms"):
        for sub in g.geoms:
            yield from _rings(sub)


def path_d(g, sc, ox, oy):
    parts = []
    for coords in _rings(g):
        pts = [(ox + x * sc, oy - y * sc) for x, y in coords]
        closed = pts[0] == pts[-1]
        s = "M" + " L".join(f"{x:.3f},{y:.3f}" for x, y in pts)
        parts.append(s + ("Z" if closed else ""))
    return " ".join(parts)


class SVG:
    def __init__(self, w, h):
        self.w, self.h, self.groups = w, h, []

    def group(self, gid, label):
        self.groups.append([gid, label, []])

    def add(self, g, color, sc, ox, oy, fill=False):
        if g is None or g.is_empty:
            return
        f = color if fill else "none"
        self.groups[-1][2].append(f'  <path d="{path_d(g, sc, ox, oy)}" fill="{f}" stroke="{color}" '
                                  f'stroke-width="0.1" fill-rule="evenodd"/>')

    def save(self, f):
        body = []
        for gid, label, items in self.groups:
            body.append(f'<g id="{gid}" inkscape:label="{label}" inkscape:groupmode="layer">')
            body += items
            body.append("</g>")
        f.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<svg xmlns="http://www.w3.org/2000/svg" '
            'xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" '
            f'width="{self.w:.3f}mm" height="{self.h:.3f}mm" viewBox="0 0 {self.w:.3f} {self.h:.3f}">\n'
            + "\n".join(body) + "\n</svg>\n", encoding="utf-8")


def piece_size(sc):
    minx, miny, maxx, maxy = outline().bounds
    return (maxx - minx) * sc, (maxy - miny) * sc, -minx * sc, maxy * sc


def jig_outline():
    """Outer outline of the back disk (symmetric, so the flipped disk fits it)."""
    return Polygon(outline().exterior)


def write_layer_files(layers, message, sc):
    w, h, ox, oy = piece_size(sc)
    m = 2.0
    for i, L in enumerate(layers, 1):
        s = SVG(w + 2 * m, h + 2 * m)
        if L.get("engrave") is not None:
            s.group("engrave", "Engrave (front)")
            s.add(L["engrave"], ENGRAVE, sc, ox + m, oy + m, fill=True)
        if L.get("guide") is not None:
            s.group("guide", "Engrave light - glue guides for the layer above")
            s.add(L["guide"], GUIDE, sc, ox + m, oy + m, fill=True)
        if L.get("score") is not None:
            s.group("score", "Score")
            s.add(L["score"], SCORE, sc, ox + m, oy + m)
        s.group("cut", "Cut")
        for g in L["cut"]:
            s.add(g, CUT, sc, ox + m, oy + m)
        s.save(OUT / f"layer_{i}_{L['name']}.svg")
    if message is not None:
        s = SVG(w + 2 * m, h + 2 * m)
        s.group("back_engrave", "Engrave - back message (layer 1 disk placed face-down in the jig)")
        s.add(message, ENGRAVE, sc, ox + m, oy + m, fill=True)
        s.group("jig", "Jig outline - cut in scrap first, then drop the layer 1 disk in face-down")
        s.add(jig_outline(), REG, sc, ox + m, oy + m)
        s.save(OUT / "layer_1b_back_message.svg")


def write_sheet(layers, message, sc, gap=4.0):
    w, h, ox, oy = piece_size(sc)
    m = 3.0
    n = len(layers) + (message is not None)
    s = SVG(m * 2 + n * w + (n - 1) * gap, h + 2 * m)
    for i, L in enumerate(layers):
        x0 = m + i * (w + gap) + ox
        y0 = m + oy
        if L.get("engrave") is not None:
            s.group(f"L{i+1}_engrave", f"Layer {i+1} {L['name']} - engrave")
            s.add(L["engrave"], LB_ENGRAVE, sc, x0, y0, fill=True)
        if L.get("guide") is not None:
            s.group(f"L{i+1}_guide", f"Layer {i+1} {L['name']} - glue guides (light engrave)")
            s.add(L["guide"], GUIDE, sc, x0, y0, fill=True)
        if L.get("score") is not None:
            s.group(f"L{i+1}_score", f"Layer {i+1} {L['name']} - score")
            s.add(L["score"], LB_SCORE, sc, x0, y0)
        s.group(f"L{i+1}_cut", f"Layer {i+1} {L['name']} - cut")
        for g in L["cut"]:
            s.add(g, LB_LAYER[i], sc, x0, y0)
    if message is not None:
        x0, y0 = m + len(layers) * (w + gap) + ox, m + oy
        s.group("L1b_back_message", "Layer 1b back message - engrave (disk face-down in jig)")
        s.add(message, LB_BACK, sc, x0, y0, fill=True)
        s.group("L1b_jig", "Layer 1b jig outline - cut (same settings as layer 1)")
        s.add(jig_outline(), LB_LAYER[0], sc, x0, y0)
    s.save(OUT / "ornament_sheet.svg")
    return s.w, s.h


# ------------------------------------------------------------------ preview
def preview(layers, extra, message, sc, sheet_wh):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import PathPatch
    from matplotlib.path import Path as MPath

    def patch(ax, g, **kw):
        for p in getattr(g, "geoms", [g]):
            if not isinstance(p, Polygon) or p.is_empty:
                continue
            verts, codes = [], []
            for ring in [p.exterior, *p.interiors]:
                c = list(ring.coords)
                verts += c
                codes += [MPath.MOVETO] + [MPath.LINETO] * (len(c) - 2) + [MPath.CLOSEPOLY]
            ax.add_patch(PathPatch(MPath(verts, codes), **kw))

    def shade(ax, g, color, depth):
        patch(ax, affinity.translate(g, 0.6 + 0.25 * depth, -0.8 - 0.25 * depth), fc="#00000040", lw=0)
        patch(ax, g, fc=color, ec="#00000055", lw=0.4)

    fig, axes = plt.subplots(1, 3, figsize=(16, 6.2), gridspec_kw=dict(width_ratios=[1, 1, 2.6]))
    L = layers
    ax = axes[0]
    shade(ax, L[0]["cut"][0], PAINT["back"], 0)
    patch(ax, L[0]["engrave"], fc=PAINT["stars"], lw=0)
    moon = extra["paint"][1][0]
    for g in L[1]["cut"]:
        shade(ax, g, PAINT["moon"] if g.equals(moon) else PAINT["hills"], 1)
    for g in L[2]["cut"]:
        shade(ax, g, PAINT["tree"], 2)
    shade(ax, extra["paint"][3][0], PAINT["snow"], 3)
    shade(ax, extra["paint"][4][0], PAINT["deco"], 3)
    for g in extra["garlands"]:
        shade(ax, g, PAINT["deco"], 3)
        patch(ax, g.intersection(extra["bauble_pts"]), fc=PAINT["bauble"], lw=0)
    shade(ax, L[4]["cut"][0], PAINT["front"], 4)
    ax.plot([-8, 8], [44.2, 44.2], color="#00000066", lw=0.8)
    ax.set_title("Front (assembled, painted)")

    ax = axes[1]
    patch(ax, affinity.scale(outline(), -1, 1, origin=(0, 0)), fc=PAINT["wood"], ec="#00000055", lw=0.4)
    if message is not None:
        patch(ax, message, fc="#5a3a1a", lw=0)
    ax.set_title("Back (layer 1 flipped)")

    for ax in axes[:2]:
        ax.set_xlim(-R - 4, R + 4)
        ax.set_ylim(-R - 4, 56)

    ax = axes[2]
    w, h, ox, oy = piece_size(1)
    for i, Lr in enumerate(layers):
        x0 = i * (w + 4)
        for g in Lr["cut"]:
            patch(ax, affinity.translate(g, x0, 0), fc="none", ec=LB_LAYER[i], lw=0.8)
        if Lr.get("engrave") is not None:
            patch(ax, affinity.translate(Lr["engrave"], x0, 0), fc="black", lw=0)
        if Lr.get("guide") is not None:
            patch(ax, affinity.translate(Lr["guide"], x0, 0), fc="#888888", lw=0)
        ax.text(x0, -R - 7, f"{i+1} {Lr['name']}", ha="center", fontsize=9)
    n = len(layers)
    if message is not None:
        x0 = n * (w + 4)
        patch(ax, affinity.translate(jig_outline(), x0, 0), fc="none", ec=LB_LAYER[0], lw=0.8, ls="--")
        patch(ax, affinity.translate(message, x0, 0), fc=LB_BACK, lw=0)
        ax.text(x0, -R - 7, "1b back message", ha="center", fontsize=9)
        n += 1
    ax.set_xlim(-R - 4, (n - 1) * (w + 4) + R + 4)
    ax.set_ylim(-R - 10, 56)
    ax.set_title(f"Cut sheet ({sheet_wh[0]:.0f} x {sheet_wh[1]:.0f} mm at this size, not to scale here)")
    for ax in axes:
        ax.set_aspect("equal")
        ax.axis("off")
    fig.tight_layout()
    fig.savefig(OUT / "preview.png", dpi=130, facecolor="#f4f1ea")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--diameter", type=float, default=90.0, help="ornament disk diameter in mm (default 90)")
    ap.add_argument("--message", default="Merry|Christmas|2026",
                    help='back-side engraving, lines split by "|"; "" for none')
    ap.add_argument("--font", default="DejaVu Serif", help="font family for the back message")
    ap.add_argument("--seed", type=int, default=7, help="star field layout")
    a = ap.parse_args()

    sc = a.diameter / (2 * R)
    OUT.mkdir(parents=True, exist_ok=True)
    layers, extra = build(a.seed)
    lines = [s for s in a.message.split("|") if s.strip()]
    message = back_message(lines, a.font)
    write_layer_files(layers, message, sc)
    wh = write_sheet(layers, message, sc)
    preview(layers, extra, message, sc, wh)
    w, h, _, _ = piece_size(sc)
    print(f"Each piece {w:.1f} x {h:.1f} mm; sheet {wh[0]:.1f} x {wh[1]:.1f} mm -> {OUT}")
    for i, L in enumerate(layers, 1):
        n = sum(len(getattr(g, 'geoms', [g])) for g in L["cut"])
        print(f"  layer {i} {L['name']:<10} {n} piece(s)")


if __name__ == "__main__":
    main()
