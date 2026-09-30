# AddStratusParams — Design Document

## Purpose

`add_stratus_params` is a pyRevit pushbutton in the **pyProSet** extension's
`add_shared_params_test` panel. It imports a configurable set of CP shared
parameters into a single open Revit family (`.rfa`) using two files the user
selects at runtime: a shared parameter `.txt` file and a parameter CSV. All
business logic for parsing those files lives in `lib/shared_param_utils.py`
and is testable without Revit.

---

## UX Workflow

1. Open a family (`.rfa`) in the Revit family editor.
2. Click **add_stratus_params** on the pyProSet ribbon tab.
3. Select the primary shared parameter `.txt` file.
4. Select the parameter CSV (sample: `sample_params/CP_Parameters.csv`).
5. If the CSV references alternate SP files via the `SPFile` column, the
   script resolves each automatically (see SP File Resolution below). A
   file-picker prompt appears only when a referenced file cannot be found.
6. The button adds missing parameters, sets formulas, and saves the family.
7. A summary alert lists: added, already existed, formulas set, manual entry
   needed.

---

## Context: Family Editor Only

Guard at startup:

```python
if not doc.IsFamilyDocument:
    forms.alert("Open a family document and try again.", exitscript=True)
```

The button operates on the currently active family document. For bulk
project-level stamping, use `stamp_view_families` instead.

---

## CSV Format

`Name,DataType,Instance,Group,SPFile`

| Column | Required | Description |
|---|---|---|
| `Name` | Yes | Shared parameter name (e.g. `CP_Weight`) |
| `DataType` | Yes | Used for formula logic: `Mass`, `Length`, `Text`, etc. |
| `Instance` | Yes | `Yes` or `No` (case-insensitive) |
| `Group` | Yes | Family editor group: `Constraints`, `Construction`, `Set`, `Data`, `Identity Data` |
| `SPFile` | No | Filename or absolute path of the SP `.txt` file containing this parameter. Blank → primary file. |

Parsed by `lib/shared_param_utils.parse_param_csv()`. Unknown `Group` values
fall back to `Construction`.

---

## SP File Resolution

After CSV parse, the script builds `sp_file_map` — a dict mapping each
parameter name to its resolved SP file path:

```python
# _resolve_alt_sp_file priority order:
# 1. SPFile value is an absolute path that exists → use as-is
# 2. Bare filename → join with directory of the primary SP file
# 3. Not found → forms.pick_file() prompt; script.exit() if cancelled
```

All unique non-blank `SPFile` values are resolved once before any transaction
opens. Parameters with a blank `SPFile` use `sp_file_path` (the primary file).

---

## SharedParametersFilename Contract

Revit's `FamilyManager.AddParameter()` requires the shared parameter file to
be the **active** file (`app.SharedParametersFilename`) at the exact moment of
the call. `find_definition()` temporarily sets this path then **always restores
it** in a `finally` block. Therefore the script must re-set the path
immediately before every `AddParameter()` call:

```python
definitions[p['name']] = find_definition(app, sp_file_map[p['name']], p['name'])
# find_definition restored the original path; re-set the per-param file:
app.SharedParametersFilename = sp_file_map[p['name']]
doc.FamilyManager.AddParameter(defn, revit_group, p['is_instance'])
```

The original path is captured before the transaction and always restored in the
`finally` block.

---

## Two-Transaction Pattern

Revit requires a committed transaction before newly-added parameters can be
referenced in formulas.

**T1 — Add Parameters**
- Iterates `to_add` (CSV entries not already in the family).
- Sets `app.SharedParametersFilename` per parameter, then calls `AddParameter`.
- On exception: rolls back T1, restores SP filename, exits with error.

**Re-fetch handles**
- `all_family_params` is re-fetched after T1 commits. Stale handles from
  inside a committed transaction are unsafe.

**T2 — Set Formulas**
- Calls `FamilyManager.SetFormula(fp, formula_string)` for each assignment.
- Individual formula failures are caught per-parameter and noted in the report.
- T2 rolls back independently if it throws; T1 results (the added parameters)
  are kept.

---

## Formula Source Detection

For each newly added non-Text parameter, the script derives a search keyword:

```
CP_Weight          → keyword "weight",           want_per_unit=False
CP_Weight_Per_Foot → keyword "weight per foot",  want_per_unit=True
CP_Length          → keyword "length",            want_per_unit=False
```

**Primary search**: case-insensitive substring match of keyword against
existing family parameter names, excluding self and respecting the per-unit
flag.

**Synonym fallback** (mass-typed targets only): if primary search returns no
candidates, retries with `('weight', 'pound', 'lbf', 'kip', 'plf')` to handle
names like `CP_Pounds Per Foot` that don't substring-match `weight per foot`.

**Multi-match**: `forms.ask_for_one_item()` dialog lets the user choose the
source parameter. If the user cancels, the parameter is noted for manual entry.

---

## lbf → lbm Conversion (`_is_force`)

When the CSV `DataType` is `mass` or `mass per unit length` and the matched
source parameter reports in lbf, the formula becomes `source / 32.174` instead
of a direct reference.

`_is_force()` tries three API paths in order (catching `AttributeError` at
each):

1. `fp.GetSpecTypeId()` — direct on `FamilyParameter` (some 2022+ builds)
2. `fp.Definition.GetSpecTypeId()` — via `Definition` (Revit 2022+)
3. `fp.Definition.ParameterType` — pre-2022 fallback

Checks for both `SpecTypeId.Force` and `SpecTypeId.Weight` (Structural
discipline — distinct API type but also reports in lbf).

Falls back to `ASSUME_WEIGHT_SOURCE_IS_LBF = True` if all three paths raise
`AttributeError`.

---

## Save Behaviour

After T2, the script attempts `doc.Save()` if the family already has a file
path (`doc.PathName`). If the family has never been saved to disk, `doc.Save()`
would throw; instead the script skips the save and appends a "use File > Save
As" note to the report.

---

## Known Limitations

| Limitation | Notes |
|---|---|
| Single family only | For bulk project stamping use `stamp_view_families` |
| Formula unit mismatch | T2 rolls back; affected params listed for manual entry |
| Text parameters | Skipped for formula assignment (no numeric source to chain) |
| Non-CP prefixed names | Keyword derivation strips `CP_` prefix; without it the full name is used as keyword |

---

## File Location

```
pyProSet.tab/
  add_shared_params_test.panel/
    add_stratus_params.pushbutton/
      script.py
lib/
  shared_param_utils.py   ← parse_param_csv, find_definition, make_formula
tests/
  test_shared_param_utils.py
sample_params/
  CP_Parameters.csv
```
