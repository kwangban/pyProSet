# -*- coding: utf-8 -*-
"""Add CP_ERP_Weight and CP_BOM_Weight shared parameters to the active family.

Workflow
--------
1. Find parameters whose name contains "Weight" (case-insensitive).
2. If the parameter reports in lbf (Force unit type), convert to lbm by dividing
   by 32.174 in the CP_ERP_Weight formula. Otherwise no conversion is needed.
3. Add CP_ERP_Weight from the ERP shared parameter file.
4. Add CP_BOM_Weight from the BOM shared parameter file.
5. Set formulas:
   - Force source : CP_ERP_Weight = <existing> / 32.174
   - Other source : CP_ERP_Weight = <existing>  (no conversion)
   - CP_BOM_Weight = CP_ERP_Weight  (chained; one conversion to maintain)

Version compatibility
---------------------
- Revit 2022+  : SpecTypeId.Force  (ForgeTypeId API)
- Revit 2021-  : ParameterType.Force
"""

from pyrevit import DB, forms, script
from shared_param_utils import load_definition, make_formula  # noqa: F401 -- lib/

# ---------------------------------------------------------------------------
# CONFIGURE -- fixed business constants (paths are prompted at runtime)
# ---------------------------------------------------------------------------
GROUP_NAME     = "Construction"   # group name inside both shared param files
ERP_PARAM_NAME = "CP_ERP_Weight"
BOM_PARAM_NAME = "CP_BOM_Weight"
GRAVITY_CONV   = 32.174
IS_INSTANCE    = True
# ---------------------------------------------------------------------------

app = __revit__.Application                # noqa: F821
doc = __revit__.ActiveUIDocument.Document  # noqa: F821

REVIT_VERSION = int(app.VersionNumber)

if REVIT_VERSION >= 2022:
    PROP_PANEL_GROUP = DB.GroupTypeId.Data
else:
    PROP_PANEL_GROUP = DB.BuiltInParameterGroup.PG_DATA

# ---------------------------------------------------------------------------
# Guard: family documents only.
# ---------------------------------------------------------------------------
if not doc.IsFamilyDocument:
    forms.alert(
        "The active document is not a family (.rfa).\n"
        "Open a family document and try again.",
        exitscript=True,
    )

# ---------------------------------------------------------------------------
# Prompt for shared parameter file paths.
# ---------------------------------------------------------------------------
erp_file_path = forms.pick_file(
    file_ext="txt",
    title="Select ERP Shared Parameter File (CP_ERP_Weight)",
)
if not erp_file_path:
    script.exit()

bom_file_path = forms.pick_file(
    file_ext="txt",
    title="Select BOM Shared Parameter File (CP_BOM_Weight)",
)
if not bom_file_path:
    script.exit()

# ---------------------------------------------------------------------------
# Step 1 -- Find the total-weight parameter.
#
# Strategy (in priority order):
#   1. Parameters typed as Force or Mass — unambiguous unit-aware detection.
#   2. Parameters whose name contains "weight" but NOT a per-unit suffix
#      (e.g. _per_foot, _per_ft, /ft, _linear) — catches Number-typed params.
#
# "Weight_per_foot" and similar are excluded here; they will be handled
# by a separate button in a later phase.
# ---------------------------------------------------------------------------
_PER_UNIT_PATTERNS = ('per_foot', 'per_ft', 'per_meter', 'per_m', '/ft', '/m', '_linear')

def _is_force(fp):
    """Return True if fp reports in lbf (Force unit type)."""
    if REVIT_VERSION >= 2022:
        return fp.Definition.GetSpecTypeId() == DB.SpecTypeId.Force
    return fp.Definition.ParameterType == DB.ParameterType.Force

def _is_mass(fp):
    if REVIT_VERSION >= 2022:
        return fp.Definition.GetSpecTypeId() == DB.SpecTypeId.Mass
    return fp.Definition.ParameterType == DB.ParameterType.Mass

def _is_per_unit(name):
    lower = name.lower()
    return any(pat in lower for pat in _PER_UNIT_PATTERNS)

all_params = list(doc.FamilyManager.GetParameters())

typed_weight = [fp for fp in all_params if _is_force(fp) or _is_mass(fp)]
name_weight  = [
    fp for fp in all_params
    if 'weight' in fp.Definition.Name.lower()
    and not _is_per_unit(fp.Definition.Name)
    and fp not in typed_weight
]

weight_candidates = typed_weight + name_weight

if not weight_candidates:
    forms.alert(
        "No total-weight parameter found.\n\n"
        "Expected a parameter typed as Force or Mass, or a parameter whose\n"
        "name contains 'Weight' (excluding per-unit variants like Weight_per_foot).\n\n"
        "Add a weight parameter first, then run this button.",
        exitscript=True,
    )

if len(weight_candidates) == 1:
    source_fp = weight_candidates[0]
else:
    names = [fp.Definition.Name for fp in weight_candidates]
    chosen = forms.ask_for_one_item(
        names,
        prompt="Select the parameter that holds the total weight of this family:",
        title="Select Weight Parameter",
    )
    if not chosen:
        script.exit()
    source_fp = next(fp for fp in weight_candidates if fp.Definition.Name == chosen)

existing_name = source_fp.Definition.Name
is_force = _is_force(source_fp)

# ---------------------------------------------------------------------------
# Step 2 -- Add CP_ERP_Weight and CP_BOM_Weight, then set formulas.
# ---------------------------------------------------------------------------
def _get_family_param(name):
    return next(
        (fp for fp in doc.FamilyManager.GetParameters()
         if fp.Definition.Name == name),
        None,
    )

original_sp = app.SharedParametersFilename
success = False
error_msg = ""

t = DB.Transaction(doc, "Add CP Weight Parameters")
try:
    t.Start()

    erp_fp = _get_family_param(ERP_PARAM_NAME)
    if erp_fp is None:
        erp_def = load_definition(app, erp_file_path, GROUP_NAME, ERP_PARAM_NAME)
        erp_fp = doc.FamilyManager.AddParameter(erp_def, PROP_PANEL_GROUP, IS_INSTANCE)

    bom_fp = _get_family_param(BOM_PARAM_NAME)
    if bom_fp is None:
        bom_def = load_definition(app, bom_file_path, GROUP_NAME, BOM_PARAM_NAME)
        bom_fp = doc.FamilyManager.AddParameter(bom_def, PROP_PANEL_GROUP, IS_INSTANCE)

    doc.FamilyManager.SetFormula(erp_fp, make_formula(existing_name, is_force, GRAVITY_CONV))
    doc.FamilyManager.SetFormula(bom_fp, ERP_PARAM_NAME)

    t.Commit()
    success = True

except Exception as ex:
    if t.HasStarted() and not t.HasEnded():
        t.RollBack()
    error_msg = str(ex)
finally:
    app.SharedParametersFilename = original_sp or ""

if not success:
    forms.alert("Failed:\n{}".format(error_msg), exitscript=True)

# ---------------------------------------------------------------------------
# Step 3 -- Save in-place and report.
# ---------------------------------------------------------------------------
doc.Save()

conv_note = " (converted from lbf / {})".format(GRAVITY_CONV) if is_force else ""
forms.alert(
    "Done.\n\n"
    "Source : {name}{conv}\n"
    "{erp}  = {formula}\n"
    "{bom}  = {erp}".format(
        name=existing_name,
        conv=conv_note,
        erp=ERP_PARAM_NAME,
        formula=make_formula(existing_name, is_force, GRAVITY_CONV),
        bom=BOM_PARAM_NAME,
    ),
    title="CP Weight Parameters Linked",
)
