# QuickDimsSpacing — Design Document

## Purpose

`QuickDimsSpacing` is a pyRevit pushbutton in the **pyProSet** extension's
`dim_tools` panel. It solves a common Revit drafting chore: when a view
contains multiple parallel dimension strings, manually spacing them evenly is
tedious and scale-dependent. This button automates the spacing in one click
and optionally repositions dimension text left or right along the dimension
line.

---

## UX Workflow

1. In the active project view, **Ctrl-click** (or window-select) two or more
   dimension lines.
2. Click **QuickDimsSpacing** on the pyProSet ribbon tab.
3. A dialog asks: *Move dimension text?* → choose **None**, **Left**, or **Right**.
4. The button spaces the selected dims evenly and (if chosen) shifts their text.
5. A summary alert shows the model-space gap and paper-space gap, and flags any
   dims whose text could not be repositioned automatically.
6. A single **Ctrl+Z** undoes all changes in one step.

---

## Revit API Concepts

### `Dimension.Curve`
Each `Dimension` element exposes a `Curve` property of type `Line`. The line
sits in the 3D model space and represents the visible dimension string.

- `Curve.Direction` — unit vector along the dimension line (e.g. `(1,0,0)` for
  a horizontal dim in plan view).
- `Curve.Origin` — midpoint of the line; used as the reference point for
  computing each dim's position in the stacking direction.

### Stacking Direction
Dimensions parallel to each other stack perpendicular to their line. The
stacking direction in the view plane is computed with the cross product:

```
stack_dir = dim_line_direction × view.ViewDirection
```

`dim_line_direction` is first canonicalized against `view.RightDirection` so
that it always points screen-right (Revit may store it in either direction):

```python
if dim_dir.DotProduct(view.RightDirection) < 0:
    dim_dir = dim_dir.Negate()
```

`view.ViewDirection` is a unit vector pointing **into the screen** (away from
the viewer). For a plan view looking down this is `(0, 0, -1)`.

**Example — plan view, horizontal dimensions:**
```
dim_dir   = (1, 0, 0)
view_dir  = (0, 0, -1)
stack_dir = (1,0,0) × (0,0,-1) = (0, 1, 0)   ← dims stack northward
```

### Scale Formula
`View.Scale` is an integer representing the denominator of the plot ratio.
For 1/4" = 1'-0" the scale is 48 (1 inch on paper = 48 inches = 4 feet in model).

```
model_spacing = PAPER_SPACING_INCHES × view.Scale / 12
```

*Example — 3/8" paper spacing at 1/4" scale (48):*
```
model_spacing = 0.375 × 48 / 12 = 1.5 feet
```

### Moving Elements
`DB.ElementTransformUtils.MoveElement(doc, elementId, translationVector)`
moves an element by a 3D vector. The vector is in model units (feet).

### Text Repositioning
`Dimension.TextPosition` is an `XYZ` property (in feet, model coordinates).
Setting it moves the label along the dimension line. For multi-segment
dimensions (string dims with multiple references) the property may be read-only
on some Revit builds; failures are caught and reported.

Text is placed **outside the dimension extent** by reading the dimension line's
endpoints after the move and setting `TextPosition` just beyond the chosen end:

```
overhang = TEXT_OVERHANG_PAPER_INCHES × view.Scale / 12   # feet

left_pt  = endpoint with smaller dim_dir dot product       # screen-left end
right_pt = endpoint with larger  dim_dir dot product       # screen-right end

"Left"  → TextPosition = left_pt  + dim_dir × (−overhang)
"Right" → TextPosition = right_pt + dim_dir × (+overhang)
```

`dim_dir` is canonicalized against `view.RightDirection` before use (see
Stacking Direction) so that "Left" is always screen-left regardless of how
Revit internally stored the dimension curve direction.

---

## Spacing Algorithm

1. Project each dim's `Curve.Origin` onto `stack_dir` to get its 1-D offset.
2. Sort dims by offset (innermost → outermost relative to the view origin).
3. Keep the innermost dim in place; assign subsequent dims to:
   `target_i = base_offset + i × model_spacing`
4. Compute the delta (`target_i − current_i`) and call `MoveElement` with
   `stack_dir × delta`.

---

## Known Limitations

| Limitation | Mitigation |
|---|---|
| Non-parallel dims selected | Warning shown; first dim's direction used for stacking axis |
| Multi-segment dim text read-only | Silently skipped; count reported in summary |
| Locked/pinned dims | Revit API will throw; caught per-element; noted in summary |
| Section / elevation views with rotated dims | `view.ViewDirection` is correct for any view type — formula holds |
| Dims referencing elements on different worksets | No special handling; `MoveElement` may fail if workset not editable |

---

## CONFIGURE Constants

```python
PAPER_SPACING_INCHES       = 0.375    # 3/8" on paper between adjacent dim lines
TEXT_OVERHANG_PAPER_INCHES = 0.0625  # 1/16" gap from tick mark to text edge
```

Adjust `PAPER_SPACING_INCHES` to match office standards (common values: 0.25",
0.375", 0.5"). Increase `TEXT_OVERHANG_PAPER_INCHES` if the text overlaps the
extension line at the drawing scale in use.

---

## File Location

```
pyProSet.tab/
  dim_tools.panel/
    quick_dims_spacing.pushbutton/
      script.py
```

No `lib/` utilities are used — all Revit API calls are script-local and cannot
be exercised in a plain CPython test environment.
