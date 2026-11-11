---
name: layer-buildup
description: Make a stacked laser-cut layer design physically buildable. Every layer is supported by all the layers below it, and a glue guide for each layer's pieces is engraved on the layer just below. Use when creating or fixing any multi-layer (layered/3D/shadow-box) SVG generator in this repo, e.g. the ornament, the Bella Vista map scene layers, or a new layered piece.
---

# Layer build-up and glue guides

The two rules below apply to every stacked laser-cut design in this repo. Layers are numbered back (bottom) to front (top).

## Rule 1: build up from the top down
Any piece on layer *k* must sit on solid material in **every** layer below it, all the way to the back.
Never let a piece float over air. For example, a star on the top-tree layer that sticks out into the sky would otherwise
float over the sky gap.

- Each layer's cut = its own visible features ∪ the footprint of every layer above it.
- Shapes that touch after the union merge into one piece. Shapes that don't touch stay separate pieces
  (e.g. the star stays its own piece on the top layer, but becomes part of the tree on the layer below).
- The footprint copies are hidden under the piece above, so the front view doesn't change.
  Only the stacked side edges show, so tell the user to paint the stack's edges after gluing, or paint those sheets to match.
- Leave out anything that is deliberately unsupported (none so far), and say so in the README.

## Rule 2: engrave a glue guide on the layer below
On layer *k*, engrave a thin filled band (≈0.7 mm) **just inside** the outline of each piece of layer *k+1*.
It is hidden once the piece is glued on and shows exactly where to put the piece.

- Drop the band wherever that edge already lines up with a cut edge of layer *k* (within ~0.9 mm). That edge is already
  your guide, and engraving there would just scorch the cut edge.
- Drop it along shared registration edges (a rim, a frame, a board outline) that line up by themselves.
- Drop slivers under ~0.4 mm².
- Color: **#B4B4B4** (gray, LightBurn layer 08), on its own SVG group named
  `... - glue guides (light engrave)`. Run it fast and at low power. It only needs to be visible.
- In multi-layer sheet files, keep the guides on their own color so they import as their own LightBurn layer.

## Rule 3: back-face engraving is its own layer
Anything engraved on the *other* face of a piece (e.g. a message on the back of the backer) is its own layer,
never mixed into the front engrave of that piece:
- Its own file (`layer_Nb_<name>.svg`) and its own panel and color on any combined sheet (LightBurn 07 magenta).
- Pair it with a jig outline (the piece's outer outline) that cuts along with the piece's own cut color. The piece drops
  into the jig hole face-down, and only the back layer runs. Never mirror the text, because it reads correctly from the back as drawn.
  If the piece isn't left-right symmetric, mirror the **jig outline** so the face-down piece fits it.

## How to apply

1. Copy [layer_stack.py](layer_stack.py) into the project folder (projects don't share files) or paste in its functions.
2. In the generator, build `own[k]`, a list of polygons each layer *visibly adds* (back → front), then:
   ```python
   cuts   = build_up(own)
   guides = glue_guides(cuts, keep_out=[rim_or_frame_edge.buffer(0.9)])
   assert not list(unsupported(cuts))
   ```
3. Write `cuts[k]` as the cut color and `guides[k]` as a filled #B4B4B4 path in each layer's SVG and in any combined sheet.
4. Draw the guides on the preview's cut-sheet panel (gray) and check that the assembled front view hasn't changed.
5. Add a line to the project README covering the build-up, the guide layer and its color, and "paint the stack's edges".

## Notes per project
- **christmas-tree-ornament**: already does this (`build()` in `make_ornament.py`). The rim is the shared edge left out of the guides.
- **bella-vista-trail-map**: scene layers `4_scene_far` … `7_scene_near` and `3_lettering` sit on `1_base`.
  Check each with `unsupported()`. The base is full-board, so most of it is supported already. The gaps are likely to be
  the scene layers stacked on each other. Put the glue guides on `1_base` (or on the scene layer below), and keep the magenta
  registration outline out of the guides. Raised trail strips (`2_trails`) already use the leftover-sheet jig, so a guide there is optional.
- Flat engravings (e.g. ride-bella-vista-poster) have no stack, so this skill doesn't apply.
