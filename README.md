# Bella Vista Trails – Layered Laser Map

Generates laser-ready SVG layers of every mountain-bike trail in Bella Vista, AR
(Back 40, Blowing Springs, Tunnel Vision, Lago Vista, Bella Vista Lake, Little Sugar, …)
from OpenStreetMap trail/road/water data, plus elevation from AWS Terrain Tiles.

## Run

```
py -m pip install requests shapely pyproj numpy pillow scikit-image scipy matplotlib
py fetch_osm.py            # downloads OSM data to data/ (add --force to refresh)
py make_map.py             # 24x24" map, raised trail strips -> output/
py make_map.py --stacked 6 # also 6 stacked elevation layers -> output/topo/
py make_map.py --size 14x11   # any board size in inches (title scales with it)
py make_map.py --no-clip   # include trails outside city limits (Bentonville etc.)
py make_map.py --lines     # trails as single scored lines on the base instead of raised strips
```

Settings live in `CFG` at the top of `make_map.py`:
- `title`, `subtitle`, `tagline` – the header text
- `systems` – the trail-system panels, e.g. `dict(name="THE\nBACK 40", side="right", miles=None)`.
  `miles=None` measures trail miles on that side of `system_split_lon` from the map; put a number to override.
- `trail_width`, `contour_interval_ft`, `seed` (different hills/trees), board size via `--size`
- `bike_image` – optional path to a dark-on-light bike silhouette PNG (one you own/licensed) to trace
  instead of the built-in full-suspension mountain bike

Panels and the north arrow are placed automatically, and the map shrinks until they fit without
covering trails. The landscape hills and trees always stay below the lowest trail.
Always check `output/preview.png` before cutting.

## Layers (bottom → top), all at full board size so they register by their outer edge

| File | Suggested material / finish | Operation |
|---|---|---|
| `0_backer.svg` | 1/8" ply painted lake blue | cut outline |
| `1_base.svg` | 1/8" birch ply, cream paint or natural | engrave lettering (black), score roads (blue), light score contours/streams (green), cut lakes + outline (red) |
| `2_trails.svg` | 1/16" (1.5 mm) ply, dark green stain/paint | cut |
| `3_lettering.svg` | 1/8" ply, dark green (title, panel names, mileage, north arrow) | cut |
| `4_scene_far.svg` | 1/8" ply, pale blue-gray | cut |
| `5_scene_lake.svg` | 1/8" ply, blue | cut |
| `6_scene_mid.svg` | 1/8" ply, sage green | cut |
| `7_scene_near.svg` | 1/8" ply, dark green (hills, big pines, rock, bike) | cut |
| `8_frame.svg` | 1/4" ply, dark green or walnut | cut |
| `topo/topo_NN_*.svg` (optional) | 1/8" ply, one sheet per level | cut; alternative 3D build – see below |

Tip: paint/stain full sheets *before* cutting – the cut edges stay clean and you never have to mask.

**Stacked-topo alternative:** instead of the flat base, glue the `topo_NN` layers on the backer
(lowest number first) to get real terrain relief, then paint or stain each level.

Laser color convention: **red = cut**, **black fill = engrave**, **blue = score**, **green = light score**,
**orange = trail lines** (`--lines` only), **magenta = registration outline** (layers 2–7).
SVGs are in millimetres – in LightBurn import and confirm the size reads 609.6 × 609.6 mm.

## Assembly tips
- Cut the base first. For the trail layer, cut red first and the magenta outline **last**.
  The leftover sheet (with trail-shaped holes) is a jig: line it up on the base, drop the
  trail pieces into their holes, glue, then lift the jig off. If your sheet is smaller
  than the board, set magenta to "don't output" and place the trails by eye.
- The trail layer is a few long, delicate pieces (1.5 mm wide) – cut it from 1/16" (1.5 mm) ply
  or veneer; 1/8" ply strips this thin tend to char through and snap. Lay it on the base, then
  wick in thin CA or use spray adhesive on the back before placing.
- Trail strip width is `trail_width` (1.5 mm default). Go wider for sturdier strips,
  narrower to separate dense areas (the Tunnel Vision / skills-park area merges into a solid patch).
- Little enclosed gaps under `min_hole_area` are filled in deliberately – they'd be too small to weed out.

Data © OpenStreetMap contributors (ODbL). Elevation: Mapzen/AWS Terrain Tiles.
