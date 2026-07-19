# -*- coding: utf-8 -*-
"""Add a shared parameter to the active Revit family document.

Usage
-----
Place this file as ``script.py`` inside a pyRevit pushbutton folder
(e.g. ``AddSharedParam.pushbutton/script.py``).  The active document
must be an open family (.rfa).

Version compatibility
---------------------
- Revit 2022 - 2027+  : uses ``GroupTypeId`` (ForgeTypeId API)
- Revit 2021 and older : uses ``BuiltInParameterGroup`` enum

The correct path is selected automatically from ``app.VersionNumber``.
"""

import os

from pyrevit import DB, forms, revit, script

# pyRevit injects __revit__ (UIApplication) as a global at runtime.
app = __revit__.Application                       # noqa: F821
doc = __revit__.ActiveUIDocument.Document         # noqa: F821

# ---------------------------------------------------------------------------
# Guard: script only works inside a family document.
# ---------------------------------------------------------------------------
if not doc.IsFamilyDocument:
    forms.alert(
        "The active document is not a family (.rfa).\n"
        "Open a family document and try again.",
        exitscript=True,
    )

# ---------------------------------------------------------------------------
# Version-aware parameter group options.
# Label shown in the picker -> API value passed to FamilyManager.AddParameter.
# ---------------------------------------------------------------------------
REVIT_VERSION = int(app.VersionNumber)

if REVIT_VERSION >= 2022:
    GROUP_OPTIONS = {
        "Construction":  DB.GroupTypeId.Construction,
        "Constraints":   DB.GroupTypeId.Constraints,
        "Data":          DB.GroupTypeId.Data,
        "Electrical":    DB.GroupTypeId.Electrical,
        "Geometry":      DB.GroupTypeId.Geometry,
        "Identity Data": DB.GroupTypeId.IdentityData,
        "Mechanical":    DB.GroupTypeId.Mechanical,
        "Structural":    DB.GroupTypeId.Structural,
    }
else:
    GROUP_OPTIONS = {
        "Construction":  DB.BuiltInParameterGroup.PG_CONSTRUCTION,
        "Constraints":   DB.BuiltInParameterGroup.PG_CONSTRAINTS,
        "Data":          DB.BuiltInParameterGroup.PG_DATA,
        "Electrical":    DB.BuiltInParameterGroup.PG_ELECTRICAL,
        "Geometry":      DB.BuiltInParameterGroup.PG_GEOMETRY,
        "Identity Data": DB.BuiltInParameterGroup.PG_IDENTITY_DATA,
        "Mechanical":    DB.BuiltInParameterGroup.PG_MECHANICAL,
        "Structural":    DB.BuiltInParameterGroup.PG_STRUCTURAL,
    }

# ---------------------------------------------------------------------------
# Step 1 - Locate the shared parameter file.
# Use whatever is already set in Revit; prompt the user if nothing is set.
# ---------------------------------------------------------------------------
original_sp_path = app.SharedParametersFilename
sp_file_path = original_sp_path

if not sp_file_path or not os.path.isfile(sp_file_path):
    sp_file_path = forms.pick_file(
        file_ext="txt",
        title="Select Shared Parameter File",
    )
    if not sp_file_path:
        script.exit()
    app.SharedParametersFilename = sp_file_path

sp_file = app.OpenSharedParameterFile()
if sp_file is None:
    forms.alert("Could not open the shared parameter file.", exitscript=True)

# ---------------------------------------------------------------------------
# Step 2 - Pick a group from the shared parameter file.
# ---------------------------------------------------------------------------
groups = {g.Name: g for g in sp_file.Groups}
if not groups:
    forms.alert(
        "No parameter groups found in:\n{}".format(sp_file_path),
        exitscript=True,
    )

group_name = forms.ask_for_one_item(
    sorted(groups.keys()),
    prompt="Select a parameter group:",
    title="Shared Parameter Group",
)
if not group_name:
    script.exit()

# ---------------------------------------------------------------------------
# Step 3 - Pick a parameter definition from that group.
# ---------------------------------------------------------------------------
definitions = {d.Name: d for d in groups[group_name].Definitions}
if not definitions:
    forms.alert(
        "No parameters found in group '{}'.".format(group_name),
        exitscript=True,
    )

param_name = forms.ask_for_one_item(
    sorted(definitions.keys()),
    prompt="Select a parameter to add:",
    title="Shared Parameter",
)
if not param_name:
    script.exit()

definition = definitions[param_name]

# ---------------------------------------------------------------------------
# Step 4 - Instance or Type?
# ---------------------------------------------------------------------------
binding_choice = forms.ask_for_one_item(
    ["Instance", "Type"],
    prompt="Add as Instance or Type parameter?",
    title="Parameter Binding",
)
if not binding_choice:
    script.exit()

is_instance = binding_choice == "Instance"

# ---------------------------------------------------------------------------
# Step 5 - Which parameter group (where it appears in the Properties panel)?
# ---------------------------------------------------------------------------
group_label = forms.ask_for_one_item(
    sorted(GROUP_OPTIONS.keys()),
    prompt="Select the parameter group (where it appears in Properties):",
    title="Parameter Group",
)
if not group_label:
    script.exit()

param_group = GROUP_OPTIONS[group_label]

# ---------------------------------------------------------------------------
# Step 6 - Add the parameter inside a transaction.
# ---------------------------------------------------------------------------
success = False
error_msg = ""

try:
    with revit.Transaction("Add Shared Parameter"):
        doc.FamilyManager.AddParameter(definition, param_group, is_instance)
    success = True
except Exception as ex:
    error_msg = str(ex)
finally:
    if sp_file_path != original_sp_path:
        app.SharedParametersFilename = original_sp_path or ""

if not success:
    forms.alert(
        "Failed to add parameter:\n{}".format(error_msg),
        exitscript=True,
    )

forms.alert(
    "'{name}' added as a{binding} parameter under '{group}'.".format(
        name=param_name,
        binding="n instance" if is_instance else " type",
        group=group_label,
    ),
    title="Parameter Added",
)
