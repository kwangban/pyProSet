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

### Phase 1 — Weight Parameter Linking *(in progress)*

Automate linking a family's existing weight parameter to the CP_ERP_Weight and
CP_BOM_Weight shared parameters required by downstream ERP and BOM systems.

**Goals:**
- `add_weight_params` button: prompts the user to select the ERP and BOM shared
  parameter files via file-picker dialogs, finds the family's total-weight parameter,
  adds `CP_ERP_Weight` (from group `Enterprise Resource Planning`) and `CP_BOM_Weight`
  (from group `CP_BOM_Reporting`) as shared parameters, places both under `Construction`
  in the family editor, and sets formulas automatically.

  **Weight parameter detection** (in priority order):
  1. Any parameter typed as **Force** (lbf) or **Mass** (lbm) — unit-aware, unambiguous
  2. Any parameter whose name contains **"weight"** (case-insensitive), excluding
     per-unit variants such as `Weight_per_foot` — catches `Number`-typed weight params

  If more than one candidate is found after filtering, the user is prompted to pick.

  **Formula logic:**
  - Parameter reports in **lbf** (Force type) → `CP_ERP_Weight = <param> / 32.174`
  - Any other unit (lbm, Number, etc.) → `CP_ERP_Weight = <param>` (no conversion)
  - `CP_BOM_Weight = CP_ERP_Weight` (chained)

  Per-unit parameters such as `Weight_per_foot` are intentionally excluded and will
  be handled by a separate button in a later phase.
- `lib/shared_param_utils.py`: stub-aware parser for the Revit shared parameter `.txt`
  format and a pure-Python `make_formula()` helper — both testable without Revit
- `tests/`: pytest suite covering the parser and formula logic (stub mode, no Revit required)

**Definition of done:** Phase 1 is complete when:
- All `tests/` pass in a plain Python environment (`pytest tests/ -v`)
- The `add_weight_params` button correctly adds and links parameters in an open `.rfa`
- A push to this repo is reflected in Revit after a pyRevit reload (end-to-end Git loop confirmed)

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
│   │   └── add_weight_params.pushbutton/
│   │       ├── script.py            Detects weight param, adds CP_ERP/BOM_Weight, sets formulas
│   │       └── icon.png
│   └── key_plan.panel/
│       └── Types.pushbutton/
│           ├── script.py
│           └── icon.png
├── lib/
│   └── shared_param_utils.py        Stub-aware parser + make_formula() — works in and out of Revit
├── tests/
│   └── test_shared_param_utils.py
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

In Revit: **pyRevit tab → Settings → Extensions → Add extension from URL**

URL: `https://github.com/kwangban/pyProSet.git`

pyRevit clones the repo into `Extensions/pyProSet.extension/` and loads `pyProSet.tab/`
from the root. After the initial install, every push to `main` is picked up on the next
pyRevit reload — no manual file copying needed.

### Automated Git Deployment Loop

1. Edit scripts in `pyProSet.tab/` or `lib/` locally
2. Run `pytest tests/ -v` — confirm all tests pass
3. Push to `main`
4. In Revit: pyRevit tab → Reload (or close/reopen Revit)

The button updates automatically.
