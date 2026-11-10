# Ride Bella Vista – Engraved Poster

Five bikes, five kinds of terrain, "RIDE BELLA VISTA / BE HAPPY." over a topo map. The artwork is
traced from `data/rides_bikes.jpg` into filled vector engrave layers.

```
py -m pip install numpy pillow scipy scikit-image shapely matplotlib
py vectorize.py                     # 12" wide -> output/
py vectorize.py --width 18 --seed 12
```

- `art` (black): the bright artwork, traced. The headline is replaced with `--text "RIDE BELLA VISTA"`
  (the default), set in Arial Narrow Bold (`--font`) and fitted to the width of the BE HAPPY. row.
  `--keep-text` keeps the original wording.
- `topo` (blue): by default a freshly generated topo map with continuous smooth contours, a solid grid
  and a frame. It stays a small gap clear of the artwork, including inside the wheels.
  `--seed N` gives different terrain, and `--topo-spacing`, `--topo-width`, `--grid 8x12` (`0x0` = none)
  and `--topo-gap` adjust the rest. `--topo trace` traces the image's own linework instead.
- `output/rides_bikes_engrave.svg` holds both layers aligned, and `_engrave_art.svg` / `_engrave_topo.svg` hold each one alone.
- Check `output/rides_bikes_check.png` before engraving. Tune the art trace with `--threshold`.
