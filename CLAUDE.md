# CLAUDE.md — pyProSet extension rules

## Commit conventions
- No "Co-Authored-By" trailers in commit messages. Commits are attributed to the user only.

## IronPython compatibility
Scripts inside `pyProSet.tab/` run in IronPython 2.7 inside Revit. `lib/` must also
be IronPython-compatible so the same code runs in both Revit and tests:
- No f-strings (use `.format()`)
- No walrus operator (`:=`)
- No type annotations (`: str`, `-> bool`, etc.)
- No `pathlib` — use `os.path`
- `class Foo(object):` not just `class Foo:`

## Repository layout contract
- `pyProSet.tab/` — pyRevit extension content. pyRevit auto-discovers `*.tab` at the
  repo root when cloned as a registered extension.
- `lib/` — pure Python utilities. pyRevit adds this to `sys.path` automatically.
  No imports from `pyrevit`, `Autodesk.Revit.DB`, or any package not in stdlib here
  (stubs handle the Revit API boundary; see `lib/shared_param_utils.py`).
- `tests/` — pytest suite that runs in CPython 3. Only `pytest` is required; no extra deps.

## script.py files are thin glue
Each pushbutton `script.py` should:
1. Call `lib/` functions for any parsing or validation logic
2. Then call Revit API via pyRevit (`from pyrevit import DB, forms`)
3. Nothing else — no business logic directly in `script.py`

## Weight parameter detection pattern
`add_weight_params` detects the source weight parameter in two passes:
1. **Unit-typed first**: parameters typed as Force (lbf), Weight/Structural (lbf), or
   Mass (lbm) via `GetSpecTypeId()` (R2022+) or `ParameterType` (pre-R2022).
   **Important**: Revit's "Weight" (Discipline: Structural, Type: Weight) is a distinct
   API type from "Force" (`SpecTypeId.Weight` vs `SpecTypeId.Force`) but both report
   in lbf. `_is_force()` checks both.
2. **Name-based fallback**: parameters whose name contains "weight" (case-insensitive),
   excluding per-unit suffixes (`_per_foot`, `_per_ft`, `/ft`, `_per_meter`, etc.)

If the matched parameter's unit type is Force or Weight → formula applies `/ 32.174`.
Per-unit variants (e.g. `Weight_per_foot`) are excluded from this button and reserved
for a future phase.

## CONFIGURE block convention
Fixed business constants (parameter names, group names, conversion factors) live in a
clearly-labelled `# CONFIGURE` block at the top of `script.py`. Never hardcode these
values inline. File paths that vary per user or environment are prompted at runtime via
`forms.pick_file()` rather than stored as constants.

Note the distinction between two types of "group name":
- **Shared param file group** (`ERP_GROUP_NAME`, `BOM_GROUP_NAME`): the group name as
  it appears inside the `.txt` file (e.g. `"Enterprise Resource Planning"`, `"CP_BOM_Reporting"`)
- **Family editor group** (`PROP_PANEL_GROUP`): the Revit UI group where the parameter
  appears in the family properties panel (currently `Construction`)

`IS_INSTANCE = True` — `CP_ERP_Weight` and `CP_BOM_Weight` are always added as
instance parameters regardless of whether the source weight parameter is a type
or instance parameter.

## Unit testing pattern
`lib/` modules detect the Revit API at import time (`try: from Autodesk.Revit.DB import ...`).
When the import fails (outside Revit), stubs defined in the same file are used instead.
Tests call `lib/` functions with `app=None` or `app=StubApp()` to exercise the stub path.
Do not introduce mocking libraries or additional pip packages.

## Two-transaction pattern for AddParameter + SetFormula
Revit requires a transaction commit before newly-added parameters can be referenced
in formulas.  Always use two separate transactions:

```python
# T1 — add parameters
t1 = DB.Transaction(doc, "Add Parameters")
t1.Start()
fp = doc.FamilyManager.AddParameter(defn, group, is_instance)
t1.Commit()

# Re-fetch handle — stale handles from inside a committed transaction are unsafe
fp = next(p for p in doc.FamilyManager.GetParameters() if p.Definition.Name == name)

# T2 — set formulas
t2 = DB.Transaction(doc, "Set Formulas")
t2.Start()
doc.FamilyManager.SetFormula(fp, formula_string)
t2.Commit()
```

If T2 fails (e.g. unit-type mismatch), roll it back and show the user the exact
formula strings to enter manually — the parameters added in T1 are still saved.

## SharedParametersFilename gotcha
`load_definition()` temporarily sets `app.SharedParametersFilename` to open the file,
then **always restores it** in a `finally` block before returning.  After it returns,
the shared parameter file is no longer active.

Revit's `FamilyManager.AddParameter()` requires the file to still be active at call
time.  Always re-set the path immediately before `AddParameter`:

```python
erp_def = load_definition(app, erp_path, group, name)
app.SharedParametersFilename = erp_path   # re-set — load_definition restored the original
erp_fp = doc.FamilyManager.AddParameter(erp_def, group, is_instance)
```

Forgetting this step produces the misleading error "Shared parameter creation failed."

## Formula type mismatch
Revit's formula engine enforces dimensional consistency. If the source weight
parameter is `NUMBER` (dimensionless — falls to name-based detection, not
unit-typed) and `CP_ERP_Weight` is defined as `MASS` in the ERP shared parameter
file, Revit rejects the formula with "invalid formula string."

**Fix**: open the ERP `.txt` file and change `CP_ERP_Weight`'s `DATATYPE` column
from `MASS` to `NUMBER`. After that change, re-running the button will set formulas
automatically. The `StubExternalDefinition.DataType` attribute exposes this field
in tests (read from column 4 of the `PARAM` line).
