# -*- coding: utf-8 -*-
"""Add CP_ERP_Weight and CP_BOM_Weight shared parameters to the active family.

Workflow
--------
1. Detect the existing weight parameter in the family by unit type
   (Force = lbf, or Mass = lbm).
2. Add CP_ERP_Weight from the ERP shared parameter file.
3. Add CP_BOM_Weight from the BOM shared parameter file.
4. Set formulas:
   - Force source : CP_ERP_Weight = <existing> / 32.174
   - Mass source  : CP_ERP_Weight = <existing>  (no conversion needed)
   - CP_BOM_Weight = CP_ERP_Weight  (chained; one conversion to maintain)

Version compatibility
---------------------
- Revit 2022+  : SpecTypeId.Force / SpecTypeId.Mass  (ForgeTypeId API)
- Revit 2021-  : ParameterType.Force / ParameterType.Mass
"""

from pyrevit import DB, forms, script
from shared_param_utils import load_definition, make_formula  # noqa: F401 -- lib/

# ---------------------------------------------------------------------------
# CONFIGURE -- fill in once network paths are available
# ---------------------------------------------------------------------------
ERP_PARAM_FILE = r"\\server\share\CP_ERP_Params.txt"   # CONFIGURE
BOM_PARAM_FILE = r"\\server\share\CP_BOM_Params.txt"   # CONFIGURE
ERP_GROUP_NAME = "CP Parameters"                         # CONFIGURE
BOM_GROUP_NAME = "CP Parameters"                         # CONFIGURE
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
# Step 1 -- Find the existing weight parameter by unit type.
# ---------------------------------------------------------------------------
def _unit_kind(fp):
    """Return 'force', 'mass', or None for a FamilyParameter."""
    if REVIT_VERSION >= 2022:
        spec = fp.Definition.GetSpecTypeId()
        if spec == DB.SpecTypeId.Force:
            return 'force'
        if spec == DB.SpecTypeId.Mass:
            return 'mass'
    else:
        pt = fp.Definition.ParameterType
        if pt == DB.ParameterType.Force:
            return 'force'
        if pt == DB.ParameterType.Mass:
            return 'mass'
    return None

weight_candidates = [
    (fp, _unit_kind(fp))
    for fp in doc.FamilyManager.GetParameters()
    if _unit_kind(fp) is not None
]

if not weight_candidates:
    forms.alert(
        "No Force or Mass parameter found in this family.\n"
        "Add a weight parameter first, then run this button.",
        exitscript=True,
    )

if len(weight_candidates) == 1:
    source_fp, source_kind = weight_candidates[0]
else:
    names = [fp.Definition.Name for fp, _ in weight_candidates]
    chosen = forms.ask_for_one_item(
        names,
        prompt="Multiple weight parameters found. Select the source:",
        title="Select Weight Parameter",
    )
    if not chosen:
        script.exit()
    source_fp, source_kind = next(
        (fp, k) for fp, k in weight_candidates if fp.Definition.Name == chosen
    )

existing_name = source_fp.Definition.Name
is_force = (source_kind == 'force')

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
        erp_def = load_definition(app, ERP_PARAM_FILE, ERP_GROUP_NAME, ERP_PARAM_NAME)
        erp_fp = doc.FamilyManager.AddParameter(erp_def, PROP_PANEL_GROUP, IS_INSTANCE)

    bom_fp = _get_family_param(BOM_PARAM_NAME)
    if bom_fp is None:
        bom_def = load_definition(app, BOM_PARAM_FILE, BOM_GROUP_NAME, BOM_PARAM_NAME)
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
