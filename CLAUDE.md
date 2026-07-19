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

## Unit testing pattern
`lib/` modules detect the Revit API at import time (`try: from Autodesk.Revit.DB import ...`).
When the import fails (outside Revit), stubs defined in the same file are used instead.
Tests call `lib/` functions with `app=None` to exercise the stub path.
Do not introduce mocking libraries or additional pip packages.
