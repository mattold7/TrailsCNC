"""Trace a raster poster into laser ENGRAVE layers (filled vector shapes).

    py vectorize.py                      # data/rides_bikes.jpg -> output/
    py vectorize.py --width 18 --topo none

Two layers are pulled out of the image:
  art   the bright artwork (bikes, terrain lines, lettering)       -> black  (#000000)
  topo  the faint background linework (contours, dashed grid)     -> blue   (#0000FF)
Different colors so LightBurn / the laser software treats them as separate engrave
layers with their own power/speed (e.g. topo lighter than art).

Writes, all sized in inches (--width):
  <name>_engrave.svg       both layers in one file, aligned
  <name>_engrave_art.svg   art layer alone
  <name>_engrave_topo.svg  topo layer alone
  <name>_check.png         preview: art white, topo cyan, on black
"""
import argparse
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage as ndi
from shapely.geometry import Polygon
from skimage import measure

HERE = Path(__file__).parent
UPSCALE = 4  # trace at 4x so curves are sub-pixel smooth
LAYERS = {"art": "#000000", "topo": "#0000FF"}


def load(img_path):
    g = Image.open(img_path).convert("L")
    w, h = g.size
    big = g.resize((w * UPSCALE, h * UPSCALE), Image.LANCZOS)
    return np.asarray(big, dtype=float), (w, h)


def trace_field(field, level, size, min_area, simplify, drop_edge=True):
    """Contours of a float field at `level` -> list of rings in original-pixel coords."""
    w, h = size
    a = np.pad(field, 1, constant_values=field.min())  # close shapes touching the edge
    rings = []
    for c in measure.find_contours(a, level):
        pts = [((x - 1) / UPSCALE, (y - 1) / UPSCALE) for y, x in c]
        if len(pts) < 4:
            continue
        p = Polygon(pts)
        if not p.is_valid:
            p = p.buffer(0)
            if p.geom_type != "Polygon":
                continue
        if abs(p.area) < min_area:
            continue
        x0, y0, x1, y1 = p.bounds
        if drop_edge and (x0 < 1 or y0 < 1 or x1 > w - 1 or y1 > h - 1):
            continue  # page margin / scan border, not artwork
        p = p.simplify(simplify, preserve_topology=True)
        rings.append(list(p.exterior.coords)[:-1])
    return rings


def trace_art(a, size, threshold, args):
    field = ndi.gaussian_filter(a, UPSCALE * 0.6)
    return trace_field(field, threshold, size, args.min_area, args.simplify), field > threshold


def trace_topo(a, size, art_mask, args):
    """Faint thin lines: subtract the local background, ignore the art and its halo."""
    s = ndi.gaussian_filter(a, UPSCALE * 0.5)
    bg = ndi.median_filter(ndi.zoom(a, 1 / UPSCALE, order=1), size=9)  # lines are thin, median ignores them
    bg = ndi.zoom(bg, (a.shape[0] / bg.shape[0], a.shape[1] / bg.shape[1]), order=1)
    detail = s - bg
    halo = ndi.binary_dilation(art_mask, iterations=UPSCALE * 3)
    detail[halo] = 0
    return trace_field(detail, args.topo_level, size, args.topo_min_area, args.simplify * 0.8)


def art_geometry(rings):
    """Even-odd rings -> one shapely geometry (holes stay holes)."""
    from shapely.geometry import Polygon as P
    g = P()
    for r in rings:
        g = g.symmetric_difference(P(r).buffer(0))
    return g


def make_topo(size, art_rings, args):
    """Recreate the background as a generated topo map: continuous smooth contours,
    a solid grid and the frame, all as filled outlines that stop short of the artwork."""
    from shapely.geometry import LineString, box
    from shapely.ops import unary_union

    w, h = size
    x0, y0, x1, y1 = args.frame
    fw, fh = x1 - x0, y1 - y0
    rng = np.random.default_rng(args.seed)

    # smooth height field: a few octaves of blurred noise, sampled at 2 px per unit
    R = 2
    gh, gw = int(fh * R), int(fw * R)
    field = np.zeros((gh, gw))
    for scale, amp in ((130, 1.0), (65, 0.45), (30, 0.12)):
        n = rng.standard_normal((gh, gw))
        f = ndi.gaussian_filter(n, scale * R, mode="wrap")
        field += amp * f / f.std()
    gy, gx = np.gradient(field)
    step = np.median(np.hypot(gx, gy)) * R * args.topo_spacing  # ~even line spacing in px
    levels = np.arange(field.min() + step / 2, field.max(), step)

    lines = []
    for lv in levels:
        for c in measure.find_contours(field, lv):
            pts = np.column_stack([x0 + c[:, 1] / R, y0 + c[:, 0] / R])
            if len(pts) < 8:
                continue
            ls = LineString(pts)
            if ls.length < args.topo_min_len:
                continue
            lines.append(ls.simplify(0.15))

    lw = args.topo_width / 2
    frame = box(x0, y0, x1, y1)
    parts = [ls.buffer(lw, cap_style="round", join_style="round", quad_segs=4) for ls in lines]
    if args.grid:
        nx, ny = args.grid
        for i in range(1, nx):
            x = x0 + fw * i / nx
            parts.append(LineString([(x, y0), (x, y1)]).buffer(lw * args.grid_weight, cap_style="flat"))
        for j in range(1, ny):
            y = y0 + fh * j / ny
            parts.append(LineString([(x0, y), (x1, y)]).buffer(lw * args.grid_weight, cap_style="flat"))
    topo = unary_union(parts).intersection(frame)
    topo = topo.union(frame.exterior.buffer(lw * 1.2, join_style="mitre"))
    art = art_geometry(art_rings)
    solid = unary_union([Polygon(g.exterior) for g in getattr(art, "geoms", [art])])  # wheels/frames filled in
    topo = topo.difference(solid.buffer(args.topo_gap))

    rings = []
    for poly in getattr(topo, "geoms", [topo]):
        if poly.geom_type != "Polygon" or poly.area < 1:
            continue
        poly = poly.simplify(0.08)
        rings.append(list(poly.exterior.coords)[:-1])
        rings += [list(i.coords)[:-1] for i in poly.interiors]
    return rings


def replace_text(art_rings, args):
    """Drop the traced headline and set new text as outlines in its place."""
    from matplotlib.font_manager import FontProperties
    from matplotlib.textpath import TextPath

    cx0, cy0, cx1, cy1 = args.text_clear
    keep = []
    for r in art_rings:
        x0, y0, x1, y1 = Polygon(r).bounds
        if not (x0 >= cx0 and y0 >= cy0 and x1 <= cx1 and y1 <= cy1):
            keep.append(r)
    if not args.text.strip():
        return keep

    tp = TextPath((0, 0), args.text, size=100, prop=FontProperties(fname=args.font))
    polys = [p for p in tp.to_polygons(closed_only=True) if len(p) >= 3]
    allp = np.vstack(polys)
    tx0, ty0 = allp.min(0)
    tx1, ty1 = allp.max(0)
    fx0, fy0, fx1, fy1 = args.text_fit
    s = min((fx1 - fx0) / (tx1 - tx0), (fy1 - fy0) / (ty1 - ty0))
    for p in polys:  # font units are y-up; flip and drop the baseline onto the fit box bottom
        keep.append([(fx0 + (x - tx0) * s, fy1 - (y - ty0) * s) for x, y in p[:-1]])
    return keep


def smooth_path(pts, corner_deg=55):
    """Closed path: quadratic curves through edge midpoints, sharp at real corners."""
    n = len(pts)
    P = np.asarray(pts)
    mids = (P + np.roll(P, -1, axis=0)) / 2

    def is_corner(i):
        v1 = P[i] - P[i - 1]
        v2 = P[(i + 1) % n] - P[i]
        n1, n2 = np.linalg.norm(v1), np.linalg.norm(v2)
        if n1 == 0 or n2 == 0:
            return True
        cos = np.clip(np.dot(v1, v2) / (n1 * n2), -1, 1)
        return np.degrees(np.arccos(cos)) > corner_deg

    f = lambda p: f"{p[0]:.2f},{p[1]:.2f}"
    d = [f"M{f(mids[-1])}"]
    for i in range(n):
        if is_corner(i):
            d.append(f"L{f(P[i])}L{f(mids[i])}")
        else:
            d.append(f"Q{f(P[i])} {f(mids[i])}")
    return "".join(d) + "Z"


def svg(layers, size, width_in):
    w, h = size
    hin = width_in * h / w
    body = "".join(
        f'<g id="{name}" inkscape:groupmode="layer" inkscape:label="{name} (engrave)">\n'
        f'<path fill="{LAYERS[name]}" fill-rule="evenodd" stroke="none" d="{" ".join(smooth_path(r) for r in rings)}"/>\n'
        f"</g>\n"
        for name, rings in layers.items() if rings)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" '
            f'viewBox="0 0 {w} {h}" width="{width_in:.3f}in" height="{hin:.3f}in">\n{body}</svg>\n')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image", nargs="?", default=str(HERE / "data" / "rides_bikes.jpg"))
    ap.add_argument("--threshold", type=float, default=140, help="0-255; artwork brighter than this")
    ap.add_argument("--width", type=float, default=12.0, help="output width in inches")
    ap.add_argument("--min-area", type=float, default=6.0, help="drop art specks smaller than this (px^2)")
    ap.add_argument("--simplify", type=float, default=0.25, help="Douglas-Peucker tolerance (px)")
    ap.add_argument("--topo", choices=["make", "trace", "none"], default="make",
                    help="make: generate a fresh smooth topo map (default); trace: trace the image's own linework")
    ap.add_argument("--seed", type=int, default=3, help="make: different seed = different terrain")
    ap.add_argument("--frame", type=lambda s: [float(v) for v in s.split(",")], default=[14, 3, 709, 943],
                    help="make: topo frame x0,y0,x1,y1 in source pixels")
    ap.add_argument("--grid", type=lambda s: [int(v) for v in s.split("x")], default=[8, 12],
                    help="make: grid columns x rows, e.g. 8x12; 0x0 for none")
    ap.add_argument("--topo-spacing", type=float, default=22, help="make: average contour spacing (px)")
    ap.add_argument("--topo-width", type=float, default=1.6, help="make: contour line width (px)")
    ap.add_argument("--grid-weight", type=float, default=0.8, help="make: grid width relative to contours")
    ap.add_argument("--topo-gap", type=float, default=3.0, help="make: clearance around the artwork (px)")
    ap.add_argument("--topo-min-len", type=float, default=25, help="make: drop contours shorter than this (px)")
    ap.add_argument("--topo-level", type=float, default=9, help="trace: brightness above local background")
    ap.add_argument("--topo-min-area", type=float, default=1.5, help="trace: drop specks smaller than this (px^2)")
    bbox = lambda s: [float(v) for v in s.split(",")]
    ap.add_argument("--text", default="RIDE BELLA VISTA",
                    help='replace the headline with this text ("" removes it; --keep-text leaves the original)')
    ap.add_argument("--keep-text", dest="text", action="store_const", const=None)
    ap.add_argument("--text-clear", type=bbox, default=[38, 822, 310, 864],
                    help="x0,y0,x1,y1: traced shapes inside this box are removed")
    ap.add_argument("--text-fit", type=bbox, default=[39.8, 826.5, 341.5, 860.5],
                    help="x0,y0,x1,y1: new text is scaled to fit this box (left/baseline aligned)")
    ap.add_argument("--font", default=r"C:\Windows\Fonts\ARIALNB.TTF")
    ap.add_argument("--out", default=str(HERE / "output"))
    args = ap.parse_args()

    src = Path(args.image)
    name = src.stem
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    a, size = load(src)
    art, art_mask = trace_art(a, size, args.threshold, args)
    if args.text is not None:
        art = replace_text(art, args)
    layers = {"art": art}
    if args.grid == [0, 0]:
        args.grid = None
    if args.topo == "make":
        layers["topo"] = make_topo(size, art, args)
    elif args.topo == "trace":
        layers["topo"] = trace_topo(a, size, art_mask, args)
    for k, v in layers.items():
        print(f"{k}: {len(v)} shapes")

    (out / f"{name}_engrave.svg").write_text(svg(layers, size, args.width))
    for k, v in layers.items():
        (out / f"{name}_engrave_{k}.svg").write_text(svg({k: v}, size, args.width))

    # preview
    from PIL import ImageDraw
    w, h = size
    S = 2
    img = Image.new("L", (w * S, h * S), 0)
    colors = {"art": (255, 255, 255), "topo": (0, 200, 255)}
    rgb = Image.new("RGB", img.size, 0)
    for k, rings in layers.items():
        m = Image.new("1", img.size, 0)
        dr = ImageDraw.Draw(m)
        for r in rings:  # even-odd: xor each ring in
            ring = Image.new("1", img.size, 0)
            ImageDraw.Draw(ring).polygon([(x * S, y * S) for x, y in r], fill=1)
            m = Image.fromarray(np.asarray(m) ^ np.asarray(ring))
        rgb.paste(colors[k], mask=m)
    rgb.save(out / f"{name}_check.png")
    print(f"wrote {out}/  ({args.width:.1f} x {args.width * h / w:.1f} in)")


if __name__ == "__main__":
    main()
