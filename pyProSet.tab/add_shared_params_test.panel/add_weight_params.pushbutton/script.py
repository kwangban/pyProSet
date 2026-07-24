# -*- coding: utf-8 -*-
"""Add CP_ERP_Weight and CP_BOM_Weight shared parameters to the active family.

Workflow
--------
1. Find the family's total-weight parameter (two-pass detection):
   a. Parameters typed as Force (lbf) or Mass (lbm) — unambiguous unit check
   b. Fallback: parameters whose name contains "Weight" (case-insensitive),
      excluding per-unit names like Weight_per_foot
2. Add CP_ERP_Weight from group "Enterprise Resource Planning" in the ERP file.
3. Add CP_BOM_Weight from group "CP_BOM_Reporting" in the BOM file.
4. Both parameters are placed under the Construction group in the family editor.
5. Set formulas:
   - Force source : CP_ERP_Weight = <existing> / 32.174  (lbf -> lbm)
   - Other source : CP_ERP_Weight = <existing>  (no conversion)
   - CP_BOM_Weight = CP_ERP_Weight  (chained)

Version compatibility
---------------------
- Revit 2022+  : SpecTypeId.Force / GroupTypeId.Construction  (ForgeTypeId API)
- Revit 2021-  : ParameterType.Force / BuiltInParameterGroup.PG_CONSTRUCTION
"""

from pyrevit import DB, forms, script
from shared_param_utils import load_definition, make_formula, is_per_unit  # noqa: F401 -- lib/

# ---------------------------------------------------------------------------
# CONFIGURE -- fixed business constants (paths are prompted at runtime)
# ---------------------------------------------------------------------------
ERP_GROUP_NAME = "Enterprise Resource Planning"   # group inside ERP shared param file
BOM_GROUP_NAME = "CP_BOM_Reporting"               # group inside BOM shared param file
ERP_PARAM_NAME = "CP_ERP_Weight"
BOM_PARAM_NAME = "CP_BOM_Weight"
GRAVITY_CONV   = 32.174
IS_INSTANCE    = True
# ---------------------------------------------------------------------------

app = __revit__.Application                # noqa: F821
doc = __revit__.ActiveUIDocument.Document  # noqa: F821

REVIT_VERSION = int(app.VersionNumber)

if REVIT_VERSION >= 2022:
    PROP_PANEL_GROUP = DB.GroupTypeId.Construction
else:
    PROP_PANEL_GROUP = DB.BuiltInParameterGroup.PG_CONSTRUCTION

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
def _is_force(fp):
    """Return True if fp reports in lbf (Force unit type)."""
    if REVIT_VERSION >= 2022:
        return fp.Definition.GetSpecTypeId() == DB.SpecTypeId.Force
    return fp.Definition.ParameterType == DB.ParameterType.Force

def _is_mass(fp):
    """Return True if fp reports in lbm (Mass unit type)."""
    if REVIT_VERSION >= 2022:
        return fp.Definition.GetSpecTypeId() == DB.SpecTypeId.Mass
    return fp.Definition.ParameterType == DB.ParameterType.Mass

all_params = list(doc.FamilyManager.GetParameters())

typed_weight = [fp for fp in all_params if _is_force(fp) or _is_mass(fp)]
name_weight  = [
    fp for fp in all_params
    if 'weight' in fp.Definition.Name.lower()
    and not is_per_unit(fp.Definition.Name)
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
        erp_def = load_definition(app, erp_file_path, ERP_GROUP_NAME, ERP_PARAM_NAME)
        erp_fp = doc.FamilyManager.AddParameter(erp_def, PROP_PANEL_GROUP, IS_INSTANCE)

    bom_fp = _get_family_param(BOM_PARAM_NAME)
    if bom_fp is None:
        bom_def = load_definition(app, bom_file_path, BOM_GROUP_NAME, BOM_PARAM_NAME)
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
