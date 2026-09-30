# -*- coding: utf-8 -*-
"""Pull latest commits from origin on every pyRevit reload.

pyRevit executes startup.py (this file) at extension root before loading any
button.  Uses .NET System.Diagnostics.Process instead of subprocess — more
reliable in IronPython inside Revit.  All failures are silently swallowed so
a network outage or git error never blocks the extension from loading.
"""
import os
import clr
clr.AddReference('System')
from System.Diagnostics import Process, ProcessStartInfo  # noqa: E402

_EXT_DIR = os.path.dirname(os.path.abspath(__file__))

# Standard Windows git installation; falls back to whatever is on PATH.
_GIT_EXE = r"C:\Program Files\Git\cmd\git.exe"
if not os.path.isfile(_GIT_EXE):
    _GIT_EXE = "git"

try:
    psi = ProcessStartInfo()
    psi.FileName        = _GIT_EXE
    psi.Arguments       = "pull --ff-only"
    psi.WorkingDirectory = _EXT_DIR
    psi.UseShellExecute        = False
    psi.CreateNoWindow         = True
    psi.RedirectStandardOutput = True
    psi.RedirectStandardError  = True
    proc = Process.Start(psi)
    if proc is not None:
        proc.WaitForExit(15000)   # 15-second timeout; fail open if exceeded
except Exception:
    pass   # never block extension load on a pull failure
