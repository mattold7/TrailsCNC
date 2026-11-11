"""Build-up and glue-guide helpers for stacked laser-cut layer designs (shapely).

Copy this file next to a project's generator (projects don't share files) or paste the functions in.
Layers are ordered back (index 0) to front (index -1). Coordinates are in mm.

    from layer_stack import build_up, glue_guides, unsupported
    cuts   = build_up(own)                        # own[k] = list of polygons layer k shows
    guides = glue_guides(cuts, keep_out=[rim_edge])
    for k, area in unsupported(cuts):  print(k, area)   # should print nothing
"""
from shapely.geometry import Polygon
from shapely.ops import unary_union


def _polys(g):
    return [p for p in getattr(g, "geoms", [g]) if isinstance(p, Polygon) and not p.is_empty]


def build_up(own):
    """Each layer also carries the footprint of everything above it, so every piece sits on
    solid material down to the back. Shapes that touch merge into one piece; others stay separate.
    Returns a list (per layer) of cut polygons."""
    cuts, above = [None] * len(own), Polygon()
    for k in range(len(own) - 1, -1, -1):
        merged = unary_union(list(own[k]) + [above])
        cuts[k] = _polys(merged)
        above = merged
    return cuts


def glue_guides(cuts, band=0.7, clear=0.9, min_area=0.4, keep_out=()):
    """For each layer k, a thin band (filled, for engraving) just inside the outline of each piece
    of layer k+1, so it is hidden once glued. The band is dropped where the upper edge already lines
    up with a cut edge of layer k (within `clear` mm) and inside any `keep_out` shapes (e.g. a shared
    rim edge that registers by itself). Returns one geometry or None per layer; the top layer gets None."""
    out = [None] * len(cuts)
    keep_out = unary_union(list(keep_out)) if keep_out else Polygon()
    for k in range(len(cuts) - 1):
        upper, lower = unary_union(cuts[k + 1]), unary_union(cuts[k])
        g = upper.difference(upper.buffer(-band, join_style=2))
        g = g.difference(lower.boundary.buffer(clear)).difference(keep_out).intersection(lower)
        g = unary_union([p for p in _polys(g) if p.area > min_area])
        out[k] = None if g.is_empty else g
    return out


def unsupported(cuts, tol=0.05):
    """Yield (layer index, area mm^2) for every layer that overhangs the layer below it."""
    for k in range(1, len(cuts)):
        gap = unary_union(cuts[k]).difference(unary_union(cuts[k - 1]).buffer(tol))
        if gap.area > 0.5:
            yield k, gap.area
