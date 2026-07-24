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
│       └── add_weight_params.pushbutton/
│           └── script.py          Thin glue: prompts, calls lib/, calls Revit API
├── lib/
│   └── shared_param_utils.py      Stub-aware shared param parser + make_formula()
├── tests/
│   └── test_shared_param_utils.py pytest suite — runs in CPython, no Revit needed
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
Fixed constants (parameter names, group names, conversion factors) go in a `# CONFIGURE`
block at the top of `script.py`. File paths that vary by machine or user are prompted
at runtime via `forms.pick_file()` — not stored as constants.

There are two distinct "group" concepts in this codebase — do not conflate them:
- **Shared param file group**: the group name inside the `.txt` file that the parameter
  belongs to (e.g. `ERP_GROUP_NAME = "Enterprise Resource Planning"`,
  `BOM_GROUP_NAME = "CP_BOM_Reporting"`). Passed to `load_definition()`.
- **Family editor group**: the Revit UI category under which the parameter appears in
  the family properties panel (e.g. `PROP_PANEL_GROUP = GroupTypeId.Construction`).
  Passed to `FamilyManager.AddParameter()`.

`IS_INSTANCE = True` — `CP_ERP_Weight` and `CP_BOM_Weight` are always added as
instance parameters. Do not change this to mirror the source parameter.

## Git Deployment Loop
1. Edit scripts in `pyProSet.tab/` or `lib/`
2. Run `pytest tests/ -v` — confirm all tests pass
3. Commit and push to `main`
4. In Revit: pyRevit tab → Reload

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

## Weight Parameter Detection
`add_weight_params` finds the source weight parameter in two passes:

1. **Unit-typed** — parameters typed as Force (lbf), Weight/Structural (lbf), or
   Mass (lbm) via `GetSpecTypeId()` (Revit 2022+) or `ParameterType` (pre-2022).
   This is the preferred path; it works for properly-configured shared parameters.
   **Note**: Revit's "Weight" (Discipline: Structural, Type of parameter: Weight)
   is a distinct API type from "Force" (`SpecTypeId.Weight` ≠ `SpecTypeId.Force`)
   but both report in lbf. `_is_force()` checks both.
2. **Name-based fallback** — parameters whose name contains "weight"
   (case-insensitive), excluding per-unit suffixes: `_per_foot`, `_per_ft`,
   `/ft`, `_per_meter`, `_per_m`, `_linear`. This catches `Number`-typed
   weight parameters that have no unit metadata.

If the matched parameter is Force or Weight-typed → formula divides by 32.174 to
convert lbf → lbm. Mass-typed or other → formula is a direct reference.

`Weight_per_foot` and similar are intentionally excluded; they will be handled
by a future button.

## Two-Transaction Pattern for AddParameter + SetFormula
Revit requires a transaction commit before newly-added parameters can be
referenced in formulas.  Use two transactions and re-fetch parameter handles
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

If T2 fails, roll it back, save the family (parameters from T1 are kept), and
show the user a diagnostic message with the source parameter's type, the likely
mismatch explanation, the fix (change DATATYPE in the ERP `.txt` file), and the
manual formula strings.

**Common T2 failure — type mismatch**: if the source weight param is `NUMBER`
(dimensionless) but `CP_ERP_Weight` is `MASS` in the shared param file, Revit
rejects any formula assignment. Fix: change CP_ERP_Weight's `DATATYPE` to
`NUMBER` in the ERP `.txt` file.

## SharedParametersFilename Gotcha
`load_definition()` sets `app.SharedParametersFilename` temporarily and **always
restores it** before returning.  After it returns, the shared parameter file is
no longer active.

`FamilyManager.AddParameter()` requires the file to be active at the moment it is
called.  Always re-set the path immediately before each `AddParameter` call:

```python
erp_def = load_definition(app, erp_path, ERP_GROUP_NAME, ERP_PARAM_NAME)
app.SharedParametersFilename = erp_path   # re-set — load_definition restored original
erp_fp = doc.FamilyManager.AddParameter(erp_def, PROP_PANEL_GROUP, IS_INSTANCE)
```

Omitting this re-set produces the misleading Revit error "Shared parameter creation failed."
This pattern is tested via `StubApp` in `tests/test_shared_param_utils.py` and documented
in `lib/shared_param_utils.py`'s module-level docstring.

## Typical Tasks for Agents
- **Add a new pushbutton**: create a `<name>.pushbutton/` folder under the appropriate
  panel, add `script.py` (thin glue only — business logic goes in `lib/`)
- **Extend `lib/`**: add helpers to `lib/shared_param_utils.py` (or a new module),
  then add pytest tests before committing
- **Update formulas or param names**: change the `# CONFIGURE` block in `script.py`
- **Add a per-unit weight button** (Phase 2 backlog): follow the same detection pattern
  but target `_per_foot` / `_per_meter` suffixes instead of excluding them

## Companion Repo
This repo is the **pyRevit UI extension**. The pure-Python library and test harness lives in:

- **`PyRevitParameterManagementTool`** — `https://github.com/kwangban/PyRevitParameterManagementTool`
  Contains the stub-based shared parameter parser and a broader test suite.
  When adding automation logic intended to be shared across tools, prototype and test
  it there first, then wire it into a button here.

## Open Questions / Backlog
- Phase 2: Key Plan Tools (`Types` button)
- Phase 3: Project Setup Automation (bulk parameter mapping, audit report)
- Decide whether CI should auto-run `pytest tests/` on push
