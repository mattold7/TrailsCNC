# Layered Christmas Tree Ornament

A round bauble ornament made from five stacked laser-cut layers. It shows a decorated pine in the snow
under a starry night sky with a crescent moon. You can engrave a message on the back.

```
py -m pip install shapely numpy matplotlib
py make_ornament.py                                  # 90 mm ornament -> output/
py make_ornament.py --diameter 76                    # 3" ornament
py make_ornament.py --message "The Harrisons|Christmas|2026"
py make_ornament.py --message ""                     # no back engraving
py make_ornament.py --seed 3                         # different star field
```

## Layers (back to front)

All five layers have the same outer rim and hanger cap, so they line up by their edges and the stack
stays solid all the way round. The tree's trunk joins the rim under the snow, so the tree also
lines up by itself.

| # | File | Paint | Pieces |
|---|---|---|---|
| 1 | `layer_1_back.svg` | navy (paint *before* engraving so the stars show bare wood) | disk; engrave stars |
| 1b | `layer_1b_back_message.svg` | – | back message (black engrave) + jig outline (magenta cut); only with `--message` |
| 2 | `layer_2_hills.svg` | white / pale gray, moon pale yellow | rim + hills with little pines, crescent moon |
| 3 | `layer_3_tree.svg` | green | rim + tree |
| 4 | `layer_4_snow_deco.svg` | rim/snow white; star + garlands gold, tip the beads red | rim + back snow drift, top star, 3 garland strands |
| 5 | `layer_5_front.svg` | white | rim + front snow drift; score line across the cap |

**Build-up:** every layer also includes the shape of everything above it, so no piece floats over a gap.
The star continues down through the tree and hills layers, the snow drift continues into the tree layer,
and the tree continues into the hills layer. Those copies are hidden behind the pieces in front, but their
side edges show around the star. Paint the edges of the star stack gold after gluing.

**Glue guides:** each layer has a thin gray (#B4B4B4) engraved band marking where the pieces of the
next layer go. The band sits just inside each piece's outline, so it's hidden once glued. It's left out
wherever the edge already lines up with a cut edge or the rim. Engrave it fast and at low power. Pieces
that only need lining up by eye, such as the moon outline on the back and the garlands on the tree,
get the most use out of it. (Rule and helper: `.claude/skills/layer-buildup/`.)

Colors in the per-layer files: **red = cut**, **black fill = engrave**, **blue = score**,
**gray fill = glue guides (light engrave)**, **magenta = jig outline** (1b only).

`ornament_sheet.svg` puts all five layers side by side on one sheet, plus the back message as a 6th panel (566 × 104 mm at 90 mm).
Each ornament layer's cut has its own LightBurn palette color, so it imports as its own LightBurn layer:
02 red = back, 03 green = hills, 04 yellow = tree, 05 orange = snow/deco, 06 cyan = front.
00 black = star engrave, 01 blue = cap score, 07 magenta = back message, 08 gray = glue guides. The 1b jig outline uses 02 red, so it cuts along with layer 1. You can turn each layer
on or off, or give it its own settings. All SVGs are in millimetres.

## Cutting and assembly
- Use 3 mm (1/8") ply, or 2 mm for a slimmer ornament. Five layers of 3 mm make a 15 mm stack.
- The garland strands are 2 mm wide, so cut them slowly and turn on "cut inner shapes first".
- **Back message (layer 1b):** it's on the other face of the back disk, so it's its own layer with its own pass.
  First run the engraves and cuts. The 1b jig outline cuts along with layer 1 (red), leaving a disk-shaped hole in the
  sheet. Drop the layer 1 disk into that hole **face-down** (stars down), then run only the 07 magenta layer.
  The text reads correctly from the back. To save wood, turn off the jig outline instead, flip the disk side to
  side in its own hole, and move the message onto it in LightBurn.
- Paint or stain each sheet before cutting. Glue the layers in order, lining up the rims and hanger holes.
  Then glue the star to the tree tip and lay the garland strands across the tiers (see `output/preview.png`).
- Thread ribbon through the hanger hole.

Always check `output/preview.png` before cutting.
