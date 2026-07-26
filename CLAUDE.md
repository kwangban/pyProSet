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
- `sample_params/` — starter CSV files for end users. `CP_Parameters.csv` lists the 16
  default CP_* parameters used with `add_stratus_params`.

## script.py files are thin glue
Each pushbutton `script.py` should:
1. Call `lib/` functions for any parsing or validation logic
2. Then call Revit API via pyRevit (`from pyrevit import DB, forms`)
3. Nothing else — no business logic directly in `script.py`

## CSV-driven parameter import (add_stratus_params)
The `add_stratus_params` button reads which parameters to import from a user-selected CSV.
CSV columns: `Name`, `DataType`, `Instance` (Yes/No), `Group`.

**Group -> Revit API mapping** (version-aware; unknown names fall back to Construction):

| CSV Group    | Pre-2022                              | 2022+                        |
|---|---|---|
| Constraints  | PG_CONSTRAINTS                        | GroupTypeId.Constraints      |
| Construction | PG_CONSTRUCTION                       | GroupTypeId.Construction     |
| Set          | PG_SETS                               | GroupTypeId.Sets             |
| Data         | PG_DATA                               | GroupTypeId.Data             |
| Identity Data| PG_IDENTITY_DATA                      | GroupTypeId.IdentityData     |

`find_definition()` (not `load_definition()`) is used in this button — it searches ALL
groups in the `.txt` file so the caller does not need to know which group a parameter
belongs to.

## Weight parameter detection pattern
`add_stratus_params` detects a formula source by keyword matching:
- Strip the `CP_` prefix and lowercase the suffix to get the keyword.
- Match against existing family parameter names (substring, case-insensitive).
- Exclude output parameters (`is_output_param()` with the frozenset from the CSV).
- Respect per-unit flag: `is_per_unit()` must match between candidate and target
  (e.g. `CP_Weight_Per_Foot` only matches per-unit candidates).
- **Revit's "Weight" (Discipline: Structural, Type: Weight)** is a distinct API type
  from "Force" (`SpecTypeId.Weight` vs `SpecTypeId.Force`) but both report in lbf.
  `_is_force()` checks both.
- Apply `/32.174` only when: target DataType is `mass` AND source `_is_force()` is True.

## CONFIGURE block convention
Fixed business constants (conversion factors) live in a `# CONFIGURE` block at the top
of `script.py`. File paths that vary per user are prompted at runtime via `forms.pick_file()`.

## Unit testing pattern
`lib/` modules detect the Revit API at import time (`try: from Autodesk.Revit.DB import ...`).
When the import fails (outside Revit), stubs defined in the same file are used instead.
Tests call `lib/` functions with `app=None` or `app=StubApp()` to exercise the stub path.
Do not introduce mocking libraries or additional pip packages.

## Two-transaction pattern for AddParameter + SetFormula
Revit requires a transaction commit before newly-added parameters can be referenced
in formulas. Always use two separate transactions:

```python
# T1 — add parameters
t1 = DB.Transaction(doc, "Add Parameters")
t1.Start()
doc.FamilyManager.AddParameter(defn, group, is_instance)
t1.Commit()

# Re-fetch handle — stale handles from inside a committed transaction are unsafe
fp = next(p for p in doc.FamilyManager.GetParameters() if p.Definition.Name == name)

# T2 — set formulas
t2 = DB.Transaction(doc, "Set Formulas")
t2.Start()
doc.FamilyManager.SetFormula(fp, formula_string)
t2.Commit()
```

If T2 fails (e.g. unit-type mismatch), roll it back and report which formulas need
manual entry — the parameters added in T1 are still saved.

## SharedParametersFilename gotcha
`load_definition()` and `find_definition()` temporarily set `app.SharedParametersFilename`
to open the file, then **always restore it** in a `finally` block before returning.
After they return, the shared parameter file is no longer active.

Revit's `FamilyManager.AddParameter()` requires the file to still be active at call
time. Always re-set the path immediately before each `AddParameter`:

```python
defn = find_definition(app, sp_path, param_name)
app.SharedParametersFilename = sp_path   # re-set — find_definition restored original
fp = doc.FamilyManager.AddParameter(defn, group, is_instance)
```

Forgetting this step produces the misleading error "Shared parameter creation failed."

## Formula type mismatch
Revit's formula engine enforces dimensional consistency. If the source parameter is
dimensionless (`NUMBER`) and the target is `MASS` in the shared param file, Revit
rejects the formula with "invalid formula string."

Fix: open the `.txt` file and change the target parameter's `DATATYPE` from `MASS`
to `NUMBER`. The `StubExternalDefinition.DataType` attribute exposes this field in
tests (read from column 4 of the `PARAM` line).
