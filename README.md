# pyProSet

A pyRevit extension for Southland project setup workflows. Provides a `pyProSet` tab
in the Revit ribbon with tools for managing shared parameters and key plan configuration.

---

## Long-Term Vision

Build a suite of one-click Revit tools that automate repetitive project setup tasks —
shared parameter management, key plan configuration, and family data standardization —
backed by a testable, CI-friendly Python library that runs outside Revit.

---

## Roadmap

### Phase 1 — Shared Parameter Tools *(in progress)*

Interactive tools for adding shared parameters to Revit family files.

**Goals:**
- `add_shared_params` button: lets the user pick a shared parameter file, group,
  parameter, and binding type via dialogs, then adds it to the active family
- `lib/shared_param_utils.py`: pure Python parser for the Revit shared parameter
  `.txt` format, usable in tests without a Revit installation
- `tests/`: pytest suite covering the parser (stub mode, no Revit required)

**Definition of done:** Phase 1 is complete when:
- All `tests/` pass in a plain Python environment (`pytest tests/ -v`)
- The `add_shared_params` button successfully adds a shared parameter to an open `.rfa`
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
├── pyProSet.tab/               pyRevit extension — tabs at repo root for direct clone
│   ├── add_shared_params_test.panel/
│   │   └── add_shared_params.pushbutton/
│   │       ├── script.py       Interactive shared parameter picker
│   │       └── icon.png
│   └── key_plan.panel/
│       └── Types.pushbutton/
│           ├── script.py
│           └── icon.png
├── lib/
│   └── shared_param_utils.py   Stub-aware parser — works in and out of Revit
├── tests/
│   └── test_shared_param_utils.py
├── CLAUDE.md                   Rules for Claude Code agents working in this repo
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
