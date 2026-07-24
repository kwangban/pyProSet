# -*- coding: utf-8 -*-
"""Shared parameter file utilities.

Works in two modes:
- Inside Revit (app is not None): delegates to app.OpenSharedParameterFile()
  so FamilyManager.AddParameter receives a real ExternalDefinition.
- Outside Revit (tests, app is None): parses the .txt file directly and
  returns stub objects with the same .Name interface.

IMPORTANT — SharedParametersFilename contract
---------------------------------------------
load_definition() temporarily sets app.SharedParametersFilename to open the
file, then restores it to the original value in a finally block.  This means
after load_definition() returns, the shared parameter file is NO LONGER ACTIVE.

Revit's FamilyManager.AddParameter() requires the shared parameter file to
still be active (app.SharedParametersFilename pointing to it) at the moment it
is called.  Callers MUST re-set app.SharedParametersFilename to the correct
path immediately before calling AddParameter():

    erp_def = load_definition(app, erp_path, group, name)
    app.SharedParametersFilename = erp_path   # <-- re-set before AddParameter
    erp_fp = doc.FamilyManager.AddParameter(erp_def, group, is_instance)

IronPython 2.7 compatible.  No imports from pyrevit or Autodesk.Revit.DB
at module level.
"""

import os

try:
    from Autodesk.Revit.DB import DefinitionFile  # noqa: F401 -- import test only
    _REVIT_AVAILABLE = True
except ImportError:
    _REVIT_AVAILABLE = False


class StubApp(object):
    """Minimal stub for Revit's Application object.

    Used in tests to exercise code paths that accept an ``app`` argument
    without requiring a live Revit session.  Mirrors the two attributes
    that ``load_definition`` reads and writes.

    Note: when _REVIT_AVAILABLE is False (all CPython test runs), load_definition
    takes the stub branch regardless of whether app is None or a StubApp.  Use
    StubApp in tests to document the expected interface and to verify behaviour
    of any future code that inspects the app object outside of Revit.
    """
    def __init__(self, shared_params_filename=""):
        self.SharedParametersFilename = shared_params_filename

    def OpenSharedParameterFile(self):
        return None


class StubExternalDefinition(object):
    def __init__(self, name, data_type=""):
        self.Name = name
        self.DataType = data_type  # e.g. "MASS", "FORCE", "NUMBER" — from PARAM col 4


class StubDefinitionGroup(object):
    def __init__(self, name, definitions):
        self.Name = name
        self.Definitions = definitions


class StubSharedParamFile(object):
    """Parses a Revit shared-parameter .txt file into stub objects."""

    def __init__(self, sp_txt_path):
        self.Groups = []
        self._parse(sp_txt_path)

    def _parse(self, path):
        group_map = {}    # group_id -> group_name
        param_groups = {} # group_name -> [StubExternalDefinition]

        with open(path, 'r') as f:
            for line in f:
                line = line.strip()
                if line.startswith('GROUP\t'):
                    parts = line.split('\t')
                    group_id = parts[1]
                    group_name = parts[2]
                    group_map[group_id] = group_name
                    param_groups[group_name] = []
                elif line.startswith('PARAM\t'):
                    parts = line.split('\t')
                    param_name = parts[2]
                    param_data_type = parts[3] if len(parts) > 3 else ""
                    group_id = parts[5]
                    group_name = group_map.get(group_id)
                    if group_name:
                        param_groups[group_name].append(
                            StubExternalDefinition(param_name, param_data_type)
                        )

        self.Groups = [
            StubDefinitionGroup(name, defs)
            for name, defs in param_groups.items()
        ]


# Names of the output parameters that this tool adds. Excluded from weight
# candidate detection to prevent circular formulas when the button is re-run
# on a family that already has these parameters.
OUTPUT_PARAM_NAMES = ("CP_ERP_Weight", "CP_BOM_Weight")

# Substrings that identify per-unit weight parameters (e.g. Weight_per_foot).
# These are excluded from total-weight detection and reserved for a future phase.
PER_UNIT_PATTERNS = (
    'per_foot', 'per_ft', 'per_meter', 'per_m', '/ft', '/m', '_linear',
)


def is_output_param(name):
    """Return True if *name* is one of the output parameters added by this tool.

    CP_ERP_Weight and CP_BOM_Weight are excluded from weight candidate
    detection to prevent circular formulas when the button is re-run on
    a family that already has these parameters.
    """
    return name in OUTPUT_PARAM_NAMES


def is_per_unit(name):
    """Return True if *name* looks like a per-unit weight parameter.

    Used to exclude parameters such as ``Weight_per_foot`` from total-weight
    detection while still allowing a plain ``Weight`` parameter through.
    """
    lower = name.lower()
    return any(pat in lower for pat in PER_UNIT_PATTERNS)


def make_formula(existing_name, is_force, gravity_conv=32.174):
    """Return the Revit formula string for CP_ERP_Weight.

    existing_name : str  -- display name of the source FamilyParameter
    is_force      : bool -- True if source is Force (lbf); False if Mass (lbm)
    gravity_conv  : float -- divisor used when converting lbf to lbm
    """
    if is_force:
        return "{} / {}".format(existing_name, gravity_conv)
    return existing_name


def load_definition(app, sp_file_path, group_name, param_name):
    """Return an ExternalDefinition (or stub) for the named parameter.

    Parameters
    ----------
    app : Revit Application, StubApp, or None
        Pass ``__revit__.Application`` inside Revit; pass ``None`` in tests.
    sp_file_path : str
        Absolute path to the shared parameter .txt file.
    group_name : str
        Name of the group as it appears in the .txt file.
    param_name : str
        Name of the parameter within that group.

    Raises
    ------
    ValueError
        If the file, group, or parameter is not found.

    Warning
    -------
    Inside Revit this function temporarily sets app.SharedParametersFilename
    and ALWAYS restores it before returning (even on error).  After it returns,
    the shared parameter file is no longer active.  If you need to call
    FamilyManager.AddParameter() with the returned definition, you must
    re-set app.SharedParametersFilename = sp_file_path before that call.
    See the module-level docstring for a usage example.
    """
    if _REVIT_AVAILABLE and app is not None:
        old_path = app.SharedParametersFilename
        try:
            app.SharedParametersFilename = sp_file_path
            sp_file = app.OpenSharedParameterFile()
        finally:
            # Always restore so the caller's shared param state is not disturbed.
            # Consequence: AddParameter requires the caller to re-set the path.
            app.SharedParametersFilename = old_path or ""
        if sp_file is None:
            raise ValueError(
                "Could not open shared parameter file: {}".format(sp_file_path)
            )
    else:
        if not os.path.isfile(sp_file_path):
            raise ValueError(
                "Shared parameter file not found: {}".format(sp_file_path)
            )
        sp_file = StubSharedParamFile(sp_file_path)

    group = next((g for g in sp_file.Groups if g.Name == group_name), None)
    if group is None:
        raise ValueError(
            "Group '{}' not found in shared parameter file".format(group_name)
        )

    defn = next((d for d in group.Definitions if d.Name == param_name), None)
    if defn is None:
        raise ValueError(
            "Parameter '{}' not found in group '{}'".format(param_name, group_name)
        )

    return defn
