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

## Typical Tasks for Agents
- **Add a new pushbutton**: create a `<name>.pushbutton/` folder under the appropriate
  panel, add `script.py` (thin glue only — business logic goes in `lib/`)
- **Extend `lib/`**: add helpers to `lib/shared_param_utils.py` (or a new module),
  then add pytest tests before committing
- **Update formulas or param names**: change the `# CONFIGURE` block in `script.py`

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
