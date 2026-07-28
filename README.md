# pyProSet

A pyRevit extension for project setup workflows. Provides a `pyProSet` tab
in the Revit ribbon with tools for managing shared parameters and key plan configuration.

---

## Long-Term Vision

Build a suite of one-click Revit tools that automate repetitive project setup tasks —
shared parameter management, key plan configuration, and family data standardization —
backed by a testable, CI-friendly Python library that runs outside Revit.

---

## Roadmap

### Phase 1 — CSV-Driven Shared Parameter Import *(in progress)*

Import any set of CP shared parameters into an open family from a single shared
parameter file. The parameter list is defined in a user-editable CSV — no Python
changes needed when the list grows or changes.

### Button: `add_stratus_params` (family editor)

> Use this when you have a single `.rfa` open in the family editor and want to
> apply CP parameters to it. For bulk project-wide stamping, see `stamp_view_families`.

**Button: `add_stratus_params`**

1. Prompts the user to select:
   - A Revit shared parameter `.txt` file (all parameters must exist in this file)
   - A CSV file defining which parameters to import (sample: `sample_params/CP_Parameters.csv`)
2. Reads the CSV (`Name`, `DataType`, `Instance`, `Group` columns).
3. Skips any parameter that already exists in the family.
4. Imports missing parameters from the shared parameter file (searching all groups).
5. For each newly added non-Text parameter, searches existing family parameters by
   keyword (derived from the CP_* name) and sets a formula automatically:
   - `CP_Weight` → matches family's weight parameter; divides by 32.174 if source is lbf
   - `CP_Weight_Per_Foot` → matches per-unit weight parameter; direct reference
   - Other numeric types → keyword match on name suffix; direct reference
   - If multiple candidates match, the user picks from a dialog.
   - If no candidate is found, the parameter is noted in the report for manual formula entry.
6. Saves the family and reports: added, skipped, formulas set, and manual-entry-needed.

**CSV format (`sample_params/CP_Parameters.csv`):**

```csv
Name,DataType,Instance,Group
CP_Weight,Mass,Yes,Construction
CP_Weight_Per_Foot,Mass per Unit Length,Yes,Construction
CP_Length,Length,No,Constraints
CP_Size,Text,No,Constraints
CP_Description,Text,No,Identity Data
...
```

- `Instance`: `Yes` or `No` (case-insensitive)
- `Group`: one of `Constraints`, `Construction`, `Set`, `Data`, `Identity Data`
  (case-insensitive; unknown values fall back to `Construction`)
- `DataType`: used only for formula conversion logic (actual Revit type comes from the `.txt` file)

**Group meanings:**

| Group | Used for |
|---|---|
| Constraints | User-editable parameters |
| Construction | Report-only / calculated parameters |
| Set | Backend parameters (not for direct user interaction) |
| Data | Specialty parameters (e.g. GPT/AI parameters) |
| Identity Data | Sheet-related parameters |

**Weight parameter detection (for formula chaining):**

Any parameter typed as Force (lbf), Structural Weight (lbf), or Mass (lbm), or whose
name contains "weight" (case-insensitive), excluding per-unit variants like
`Weight_per_foot`. If the source reports in lbf, the formula divides by 32.174.
Both Force and Weight (Structural) require this conversion — they are distinct Revit
API types (`SpecTypeId.Force` vs `SpecTypeId.Weight`) but both report in lbf.

**Transaction pattern:**

Parameters are added in T1, formulas set in T2. If T2 fails (e.g. unit-type mismatch),
T2 rolls back but T1 results are kept. The report lists formulas that need manual entry.

### Button: `stamp_view_families` (project)

> Use this when you have a Revit project (`.rvt`) open and want to stamp CP
> parameters onto every loadable family visible in the active view in one click.

1. Prompts for the shared parameter `.txt` file and the CSV (same files as above).
2. Collects every unique loadable family whose instances appear in the active view.
   Skips in-place families and non-editable (system) families.
3. For each family: opens it with `EditFamily`, adds any missing CP parameters,
   sets keyword-matched formulas, then reloads the family back into the project.
4. Multi-match formula candidates (batch mode): takes the first alphabetically and
   notes ambiguity in the report — no interactive picker to avoid repeated dialogs.
5. Shows a per-family summary: added, already complete, failed, manual-entry needed.

- `lib/shared_param_utils.py`: stub-aware parser for Revit shared param `.txt` files,
  `parse_param_csv()`, `find_definition()`, `make_formula()` — all testable without Revit
- `tests/`: pytest suite (56 tests) covering parser, CSV reader, and formula logic

**Definition of done:** Phase 1 is complete when:
- All `tests/` pass in a plain Python environment (`pytest tests/ -v`)
- The `add_stratus_params` button correctly imports and links parameters in an open `.rfa`
- The `stamp_view_families` button correctly stamps all loadable families in the active view
- A push to this repo is reflected in Revit after a pyRevit reload

---

### Phase 2 — Key Plan Tools

Tools for standardizing key plan families and type naming.

**Goals:**
- `Types` button: interactive type management for key plan families
- Validation: flag families that don't meet naming conventions

---

### Phase 3 — Project Setup Automation

Bulk operations that set up a full Revit project from a configuration template.

**Goals:**
- Load a shared parameter file and map parameters to multiple families in one operation
- Apply standard parameter groups and naming conventions across a project
- Export a parameter audit report

---

## Repository Structure

```
pyProSet/
├── pyProSet.tab/                    pyRevit extension — tabs at repo root for direct clone
│   ├── add_shared_params_test.panel/
│   │   ├── add_stratus_params.pushbutton/
│   │   │   ├── script.py            Family-editor: CSV-driven import into a single open .rfa
│   │   │   └── icon.png
│   │   └── stamp_view_families.pushbutton/
│   │       ├── script.py            Project: bulk-stamp all families visible in the active view
│   │       └── icon.png
│   └── key_plan.panel/
│       └── Types.pushbutton/
│           ├── script.py
│           └── icon.png
├── lib/
│   └── shared_param_utils.py        Stub-aware parser + CSV reader + make_formula()
├── tests/
│   └── test_shared_param_utils.py   56 tests; runs in CPython without Revit
├── sample_params/
│   └── CP_Parameters.csv            Starter CSV with 16 CP_* parameters
├── CLAUDE.md                        Rules for Claude Code agents working in this repo
└── README.md
```

---

## Getting Started

### Running Tests

```bash
pip install pytest
pytest tests/ -v
```

No Revit installation required. Tests run on the stub path of `lib/shared_param_utils.py`.

### Installing the pyRevit Extension

In Revit: **pyRevit tab -> Settings -> Extensions -> Add extension from URL**

URL: `https://github.com/kwangban/pyProSet.git`

pyRevit clones the repo into `Extensions/pyProSet.extension/` and loads `pyProSet.tab/`
from the root. After the initial install, every push to `main` is picked up on the next
pyRevit reload — no manual file copying needed.

### Automated Git Deployment Loop

1. Edit scripts in `pyProSet.tab/` or `lib/` locally
2. Run `pytest tests/ -v` — confirm all tests pass
3. Push to `main`
4. In Revit: pyRevit tab -> Reload (or close/reopen Revit)

The button updates automatically.
