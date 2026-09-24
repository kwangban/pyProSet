# -*- coding: utf-8 -*-
"""Evenly space selected dimension lines and optionally shift their text.

Workflow
--------
1. User pre-selects two or more dimension elements in the active view.
2. Click the button.
3. A dialog asks whether to move dimension text: None / Left / Right.
4. The button sorts the selected dims by their perpendicular offset from the
   dimension line direction, then moves each one to an evenly spaced position.
5. Spacing is derived from the view's print scale so the gap is constant on
   paper regardless of the drawing scale.
6. If a text direction was chosen, each dimension's TextPosition is placed
   just outside the left or right endpoint of the dimension line.

Spacing math
------------
  model_spacing = PAPER_SPACING_INCHES * view.Scale / 12
  (view.Scale is the integer denominator: 48 for 1/4"=1', 96 for 1/8"=1', etc.)

Stacking direction
------------------
  Perpendicular to the dimension line, in the view plane:
  stack_dir = dim_line_direction x view.ViewDirection   (normalised)

Limitations
-----------
- All selected dims should be parallel. If they differ in direction the first
  dim's direction is used for the stacking axis; a warning is shown.
- TextPosition for multi-segment (string) dimensions may be read-only on some
  Revit builds; failures are silently skipped and noted in the report.
- Works in project views only (guard: doc.IsFamilyDocument must be False).
"""

from pyrevit import DB, forms, script

# ---------------------------------------------------------------------------
# CONFIGURE
# ---------------------------------------------------------------------------
PAPER_SPACING_INCHES    = 0.375   # gap between adjacent dim lines on paper (in)
TEXT_OVERHANG_PAPER_INCHES = 0.0625  # gap from tick mark to text edge on paper (in)
# ---------------------------------------------------------------------------

app   = __revit__.Application                # noqa: F821
doc   = __revit__.ActiveUIDocument.Document  # noqa: F821
uidoc = __revit__.ActiveUIDocument           # noqa: F821

# ---------------------------------------------------------------------------
# Guard: project views only.
# ---------------------------------------------------------------------------
if doc.IsFamilyDocument:
    forms.alert(
        "QuickDimsSpacing works in project views only.\n"
        "Close the family editor and try again from a project view.",
        exitscript=True,
    )

# ---------------------------------------------------------------------------
# Collect selected Dimension elements.
# ---------------------------------------------------------------------------
sel_ids = uidoc.Selection.GetElementIds()
dims    = [
    doc.GetElement(eid)
    for eid in sel_ids
    if isinstance(doc.GetElement(eid), DB.Dimension)
]

if len(dims) < 2:
    forms.alert(
        "Select two or more dimension lines before running this button.\n\n"
        "Hold Ctrl and click each dimension, or window-select a group.",
        exitscript=True,
    )

# ---------------------------------------------------------------------------
# Ask for text direction.
# ---------------------------------------------------------------------------
choice = forms.ask_for_one_item(
    ["None", "Left", "Right"],
    prompt="Move dimension text after spacing?",
    title="QuickDimsSpacing — Text Position",
)
if choice is None:
    script.exit()

# ---------------------------------------------------------------------------
# Stacking direction: perpendicular to dim line, in the view plane.
# ---------------------------------------------------------------------------
view       = doc.ActiveView
view_dir   = view.ViewDirection                         # points into screen
view_right = view.RightDirection                        # points screen-right
dim_dir    = dims[0].Curve.Direction.Normalize()

# Canonicalize: ensure dim_dir always points screen-right so that
# "Left" and "Right" are consistent regardless of how Revit stored
# the dimension curve direction.
if dim_dir.DotProduct(view_right) < 0:
    dim_dir = dim_dir.Negate()

# Warn if dims are not all parallel (tolerance: angle > 1 degree).
_TOL = 0.01745   # sin(1 degree)
non_parallel = [
    d for d in dims[1:]
    if abs(d.Curve.Direction.Normalize().DotProduct(dim_dir)) < (1.0 - _TOL)
]
if non_parallel:
    forms.alert(
        "{} of the selected dimensions are not parallel to the first.\n"
        "The first dimension's direction will be used for spacing.\n"
        "Results may be unexpected for non-parallel dims.".format(
            len(non_parallel)
        ),
    )

stack_dir = dim_dir.CrossProduct(view_dir).Normalize()

# ---------------------------------------------------------------------------
# Sort dims by current stacking offset and compute target positions.
# ---------------------------------------------------------------------------
view_scale   = view.Scale                                      # integer
model_spacing = PAPER_SPACING_INCHES * view_scale / 12.0      # feet

offsets      = [d.Curve.Origin.DotProduct(stack_dir) for d in dims]
sorted_pairs = sorted(zip(offsets, dims), key=lambda x: x[0])
sorted_dims  = [p[1] for p in sorted_pairs]
base_offset  = sorted_pairs[0][0]
targets      = [base_offset + i * model_spacing for i in range(len(sorted_dims))]

# ---------------------------------------------------------------------------
# Text overhang distance (used inside the transaction loop).
# ---------------------------------------------------------------------------
text_overhang = TEXT_OVERHANG_PAPER_INCHES * view_scale / 12.0  # feet

# ---------------------------------------------------------------------------
# Transaction: move dims and reposition text.
# ---------------------------------------------------------------------------
text_skip = []

t = DB.Transaction(doc, "QuickDimsSpacing")
try:
    t.Start()
    for i, dim in enumerate(sorted_dims):
        current = dim.Curve.Origin.DotProduct(stack_dir)
        delta   = targets[i] - current
        move    = stack_dir.Multiply(delta)
        DB.ElementTransformUtils.MoveElement(doc, dim.Id, move)

        if choice != "None":
            try:
                # Re-read the curve after the move so endpoints are current.
                curve = dim.Curve
                pt0   = curve.GetEndPoint(0)
                pt1   = curve.GetEndPoint(1)
                # Identify left/right endpoints relative to canonicalized dim_dir.
                if pt0.DotProduct(dim_dir) < pt1.DotProduct(dim_dir):
                    left_pt  = pt0
                    right_pt = pt1
                else:
                    left_pt  = pt1
                    right_pt = pt0
                if choice == "Right":
                    dim.TextPosition = right_pt.Add(dim_dir.Multiply(text_overhang))
                else:
                    dim.TextPosition = left_pt.Add(dim_dir.Multiply(-text_overhang))
            except Exception:
                text_skip.append(dim.Id.IntegerValue)
    t.Commit()
except Exception as ex:
    if t.HasStarted() and not t.HasEnded():
        t.RollBack()
    forms.alert("QuickDimsSpacing failed:\n{}".format(str(ex)), exitscript=True)

# ---------------------------------------------------------------------------
# Report.
# ---------------------------------------------------------------------------
lines = [
    "{} dimensions spaced at {:.4f}' apart in model ({:.3f}\" on paper at 1:{} scale).".format(
        len(sorted_dims),
        model_spacing,
        PAPER_SPACING_INCHES,
        view_scale,
    ),
    "Text direction: {}.".format(choice),
]
if text_skip:
    lines.append(
        "\nText position could not be set on {} dimension(s) "
        "(multi-segment or locked) — adjust manually.".format(len(text_skip))
    )

forms.alert("\n".join(lines), title="QuickDimsSpacing - Done")
