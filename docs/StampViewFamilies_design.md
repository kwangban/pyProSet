# StampViewFamilies — Design Document

## Purpose

`stamp_view_families` is a pyRevit pushbutton in the **pyProSet** extension's
`add_shared_params_test` panel. It applies the same CSV-driven CP parameter
import as `add_stratus_params` — but in bulk, across every unique loadable
family whose instances appear in the active project view. Each family is opened
with `EditFamily`, modified, and reloaded back into the project in one click.

---

## UX Workflow

1. Open a Revit project (`.rvt`) in any view that contains placed family
   instances.
2. Make that view active.
3. Click **stamp_view_families** on the pyProSet ribbon tab.
4. Select the primary shared parameter `.txt` file.
5. Select the parameter CSV (sample: `sample_params/CP_Parameters.csv`).
6. If the CSV references alternate SP files via the `SPFile` column, each is
   resolved automatically (see SP File Resolution). A file-picker prompt
   appears only when a referenced file cannot be found.
7. The button processes each family in the view and shows a per-family summary.

---

## Context: Project Document Only

Guard at startup:

```python
if doc.IsFamilyDocument:
    forms.alert("Open a project (.rvt) and try again.", exitscript=True)
```

The button is the inverse of `add_stratus_params`. For editing a single open
family, use `add_stratus_params` instead.

---

## CSV Format

Same five-column format as `add_stratus_params`:

`Name,DataType,Instance,Group,SPFile`

See `docs/AddStratusParams_design.md` for column definitions. Parsed by
`lib/shared_param_utils.parse_param_csv()`.

---

## SP File Resolution

Identical to `add_stratus_params`: `_resolve_alt_sp_file()` resolves each
unique non-blank `SPFile` value before any family is opened, building
`sp_file_map` (`param_name → absolute path`). Resolution order:

1. Absolute path that exists → use as-is
2. Bare filename → join with directory of primary SP file
3. Not found → `forms.pick_file()` prompt; `script.exit()` if cancelled

---

## Family Collection

```python
instances = (
    DB.FilteredElementCollector(doc, doc.ActiveView.Id)
    .OfClass(DB.FamilyInstance)
    .ToElements()
)
```

Unique `Family` objects are extracted via `fi.Symbol.Family`, then filtered:

- **Skip** `fam.IsInPlace` — in-place families cannot be opened with `EditFamily`
- **Skip** not `fam.IsEditable` — system and non-editable families
- Deduplicated by `fam.Id` so each family is processed once even if it has
  many instances in the view

---

## Definition Pre-load

All `ExternalDefinition` objects are looked up **once before any family is
opened**, using the resolved `sp_file_map` per parameter. This avoids repeated
file I/O inside the per-family loop and ensures that a missing parameter is
reported up-front rather than discovered mid-batch.

```python
for p in param_list:
    definitions[p['name']] = find_definition(app, sp_file_map[p['name']], p['name'])
```

Parameters not found in any SP file are skipped for all families, and the
missing names are shown in a warning before processing begins.

---

## Per-Family Loop

For each family:

### 1. Open
```python
family_doc = doc.EditFamily(family)
```
Returns a `Document` (the family in edit mode). If it returns `None` or throws,
the family is recorded as FAILED and the loop continues.

### 2. Skip-if-complete check
Existing parameter names are read from `family_doc.FamilyManager.GetParameters()`.
If all CSV parameters already exist, `family_doc.Close(False)` is called and the
family is recorded as `already complete — skipped` without opening a transaction.

### 3. T1 — Add missing parameters
```python
app.SharedParametersFilename = sp_file_map[p['name']]   # per-param file
family_doc.FamilyManager.AddParameter(definitions[p['name']], group, is_instance)
```
The `SharedParametersFilename` must point to the correct file at the moment of
each `AddParameter` call (see SharedParametersFilename Contract below). T1
rolls back the whole family on exception; the family is closed and recorded as
FAILED T1.

### 4. Formula assignment (batch mode)
After T1 commits, `all_fp` is re-fetched. For each newly added non-Text
parameter the same keyword derivation and synonym fallback as `add_stratus_params`
is applied, with these differences:

> **No interactive picker.** When multiple source candidates match, the script
> takes the **first alphabetically** and notes the ambiguity in the per-family
> report. This avoids repeated dialogs when many families are processed.

> **Primary search `output_names` exclusion.** The primary keyword candidates
> must not be in `output_names`. This prevents `CP_Weight` from picking
> `CP_BOM_Weight` as its source when both names contain "weight".

> **Synonym fallback allows `output_names` (preferred).** When the primary
> keyword finds nothing (e.g. keyword "bom weight" for `CP_BOM_Weight`), the
> synonym fallback includes CSV params but sorts them first — so `CP_BOM_Weight`
> chains to `CP_Weight` rather than the native family weight param.

> **`source_is_force` guard.** When the chosen source is itself a CSV param,
> the `/32.174` conversion is skipped. Newly added shared params of type Mass
> trigger the `ASSUME_WEIGHT_SOURCE_IS_LBF = True` fallback in `_is_force()`,
> producing a spurious conversion if not guarded.

### 5. T2 — Set formulas
Iterates formula assignments sorted so **native-source formulas run first**
(source NOT in `output_names`), then **CSV-source formulas** (source in
`output_names`). This prevents circular-dependency rejections when re-stamping:
`CP_Weight = CP_Fab Weight` is applied before `CP_BOM_Weight = CP_Weight`,
breaking any existing wrong circular chain before the derived formula is set.
Individual formula failures are caught per-parameter. T2 rolls back
independently on a fatal exception; T1 results (added parameters) are kept.

### 6. Reload and close
```python
family_doc.LoadFamily(doc, _FamilyLoadOptions())
family_doc.Close(False)
```
`_FamilyLoadOptions` implements `IFamilyLoadOptions`:

```python
class _FamilyLoadOptions(DB.IFamilyLoadOptions):
    def OnFamilyFound(self, familyInUse, overwriteParameterValues):
        overwriteParameterValues.Value = True   # IronPython: .Value on clr.Reference
        return True

    def OnSharedFamilyFound(self, sharedFamily, familyInUse, source, overwriteParameterValues):
        source.Value = DB.FamilySource.Family
        overwriteParameterValues.Value = True
        return True
```

---

## SharedParametersFilename Contract

Same constraint as `add_stratus_params`: `find_definition()` restores
`app.SharedParametersFilename` after every call. Immediately before each
`AddParameter`, the script re-sets it to `sp_file_map[p['name']]`. The
original value is restored in a `finally` block after T1.

---

## lbf → lbm Conversion

Same three-path `_is_force()` and `ASSUME_WEIGHT_SOURCE_IS_LBF` logic as
`add_stratus_params`. See that design doc for details.

---

## Batch Mode vs. Interactive Mode

| Behaviour | `add_stratus_params` | `stamp_view_families` |
|---|---|---|
| Multi-match formula | User picks via dialog | First alphabetically; ambiguity noted |
| Save after changes | `doc.Save()` on the open family | `LoadFamily()` reloads into project |
| Context | Single open `.rfa` | Project view; all visible families |

---

## Summary Report

After all families are processed a single alert lists every family with a
status prefix:

| Prefix | Meaning |
|---|---|
| `~` | Already complete — skipped |
| `+` | Parameters added / formulas set |
| `!` | FAILED (open, T1, or reload error) |

A "Manual formula entry needed" section lists parameters per family where no
source was found or formula assignment failed.

---

## Known Limitations

| Limitation | Notes |
|---|---|
| In-place families | Cannot be opened with `EditFamily`; silently skipped |
| Non-editable families | System and linked families skipped |
| Multi-match ambiguity | First-alpha used; verify formula in report |
| View scope | Only families with instances in the **active view** are processed |
| No save step | Families are reloaded into the project; the project itself is not saved by this button |

---

## File Location

```
pyProSet.tab/
  add_shared_params_test.panel/
    stamp_view_families.pushbutton/
      script.py
lib/
  shared_param_utils.py   ← parse_param_csv, find_definition, make_formula
tests/
  test_shared_param_utils.py
sample_params/
  CP_Parameters.csv
```
