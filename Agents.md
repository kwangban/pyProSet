# Agents Guide

## Project Snapshot
- **Goal**: provide a `pyProSet` tab in the Revit ribbon with one-click tools for
  project setup workflows — shared parameter management, key plan configuration, and
  family data standardization.
- **Why it matters**: runs inside Revit via IronPython; logic in `lib/` is testable
  in plain Python without Revit.

## Repo Layout
```
pyProSet/
├── pyProSet.tab/                  pyRevit extension — tab at repo root for direct clone
│   └── add_shared_params_test.panel/
│       ├── add_stratus_params.pushbutton/
│       │   └── script.py          Family editor: CSV-driven import into a single open .rfa
│       └── stamp_view_families.pushbutton/
│           └── script.py          Project: bulk-stamps all loadable families in the active view
├── lib/
│   └── shared_param_utils.py      Stub-aware shared param parser, CSV reader, make_formula()
├── tests/
│   └── test_shared_param_utils.py 56-test pytest suite — runs in CPython, no Revit needed
├── sample_params/
│   └── CP_Parameters.csv          Starter CSV with 16 default CP_* parameters
├── CLAUDE.md                      Rules for Claude Code agents
├── Agents.md                      This file
└── README.md
```

## IronPython Constraints
Scripts in `pyProSet.tab/` and `lib/` must be IronPython 2.7 compatible:
- No f-strings — use `.format()`
- No walrus operator (`:=`), no type annotations
- No `pathlib` — use `os.path`
- `class Foo(object):` not `class Foo:`

## CONFIGURE Block Convention
Fixed constants (conversion factors) go in a `# CONFIGURE` block at the top of
`script.py`. File paths that vary by machine or user are prompted at runtime via
`forms.pick_file()` — not stored as constants.

## CSV-Driven Workflow (add_stratus_params)
The button reads the parameter list from a user-selected CSV instead of hard-coding
parameter names. CSV columns: `Name`, `DataType`, `Instance` (Yes/No), `Group`.

The `sample_params/CP_Parameters.csv` file ships with the repo as a starting point;
users can edit it or substitute their own CSV at run time.

**Group -> Revit API mapping** (version-aware, falls back to Construction if unknown):

| CSV `Group`  | Revit pre-2022         | Revit 2022+              |
|---|---|---|
| Constraints  | PG_CONSTRAINTS         | GroupTypeId.Constraints  |
| Construction | PG_CONSTRUCTION        | GroupTypeId.Construction |
| Set          | PG_SETS                | GroupTypeId.Sets         |
| Data         | PG_DATA                | GroupTypeId.Data         |
| Identity Data| PG_IDENTITY_DATA       | GroupTypeId.IdentityData |

`find_definition()` (searches all groups in `.txt`) is used instead of `load_definition()`
(which requires knowing the group name up front).

## Git Deployment Loop
1. Edit scripts in `pyProSet.tab/` or `lib/`
2. Run `pytest tests/ -v` — confirm all tests pass
3. Commit and push to `main`
4. In Revit: pyRevit tab -> Reload

pyRevit clones this repo into `Extensions/pyProSet.extension/` via the `giturl` in
`pyRevit_config.ini`. After the initial clone, changes are picked up on Reload. If
Reload doesn't pull (known telemetry bug), run `git pull` manually in the Extensions
clone folder or close/reopen Revit.

## How to Run Tests
```bash
pip install pytest
cd pyProSet
pytest tests/ -v
```
No Revit installation required. Tests exercise the stub path of `lib/shared_param_utils.py`.

## Weight Parameter Detection (Formula Chaining)
`add_stratus_params` derives a search keyword from each CP_* parameter name (strip `CP_`
prefix, lowercase, replace `_` with space) and matches it against existing family
parameter names.

- Exclude parameters in `output_names` (the frozenset of names from the CSV) to avoid
  circular references.
- Use `is_per_unit()` to distinguish `CP_Weight` (not per-unit) from `CP_Weight_Per_Foot`
  (per-unit) so each only matches appropriate candidates.
- **Revit's "Weight" (Discipline: Structural, Type: Weight)** is a distinct API type
  from "Force" (`SpecTypeId.Weight` vs `SpecTypeId.Force`) but both report in lbf.
  `_is_force()` checks both.
- Apply `/32.174` only when: target CSV DataType is `mass` AND `_is_force()` is True
  for the matched source parameter.
- 0 matches -> no formula (noted in report for manual entry)
- 1 match -> auto-assign
- 2+ matches -> user picks from `forms.ask_for_one_item()` dialog

## Two-Transaction Pattern for AddParameter + SetFormula
Revit requires a transaction commit before newly-added parameters can be
referenced in formulas. Use two transactions and re-fetch parameter handles
between them:

```python
# T1 — add parameters, then commit
t1 = DB.Transaction(doc, "Add Parameters")
t1.Start()
doc.FamilyManager.AddParameter(defn, group, is_instance)
t1.Commit()

# Re-fetch — stale handles from inside a committed transaction are unsafe
fp = next(p for p in doc.FamilyManager.GetParameters() if p.Definition.Name == name)

# T2 — set formulas
t2 = DB.Transaction(doc, "Set Formulas")
t2.Start()
doc.FamilyManager.SetFormula(fp, formula_string)
t2.Commit()
```

If T2 fails, roll it back, save the family (T1 results kept), and report which
parameters need manual formula entry.

## SharedParametersFilename Gotcha
`find_definition()` sets `app.SharedParametersFilename` temporarily and **always
restores it** before returning.  After it returns, the shared parameter file is
no longer active.

`FamilyManager.AddParameter()` requires the file to be active at the moment it is
called.  Always re-set the path immediately before each `AddParameter` call:

```python
defn = find_definition(app, sp_path, param_name)
app.SharedParametersFilename = sp_path   # re-set — find_definition restored original
fp = doc.FamilyManager.AddParameter(defn, revit_group, is_instance)
```

Omitting this re-set produces the misleading Revit error "Shared parameter creation failed."

## Button Context: Family Editor vs Project

| Button | Context | Guard |
|---|---|---|
| `add_stratus_params` | Family editor (single `.rfa`) | `doc.IsFamilyDocument` must be **True** |
| `stamp_view_families` | Project (`.rvt`) | `doc.IsFamilyDocument` must be **False** |

`stamp_view_families` uses `EditFamily` / `LoadFamily` to open each family doc, apply the
same CSV parameter + formula logic, and reload. Key differences from `add_stratus_params`:
- `FilteredElementCollector(doc, view.Id).OfClass(FamilyInstance)` collects families.
- Transactions open on `family_doc`, not the project `doc`.
- `_FamilyLoadOptions` implements `IFamilyLoadOptions`; `out` params use `.Value`.
- No interactive picker on multi-match — first alphabetically wins; noted in report.

## Typical Tasks for Agents
- **Add a new pushbutton**: create a `<name>.pushbutton/` folder under the appropriate
  panel, add `script.py` (thin glue only — business logic goes in `lib/`)
- **Extend `lib/`**: add helpers to `lib/shared_param_utils.py` (or a new module),
  then add pytest tests before committing
- **Change the parameter list**: edit `sample_params/CP_Parameters.csv` — no Python
  changes needed
- **Add a new group**: extend `_GROUP_MAP` in both `script.py` files with the new group name

## Open Questions / Backlog
- Phase 2: Key Plan Tools (`Types` button)
- Phase 3: Project Setup Automation (bulk parameter mapping, audit report)
- Decide whether CI should auto-run `pytest tests/` on push
