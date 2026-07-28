# -*- coding: utf-8 -*-
"""Import CP shared parameters from a user-supplied CSV into the active family.

Workflow
--------
1. Prompt for the shared parameter .txt file and the parameter CSV file.
2. Parse the CSV to get the list of parameters (Name, DataType, Instance, Group).
3. For each parameter: if it already exists in the family, skip it. Otherwise,
   locate its definition in the shared parameter file (any group) and add it
   under the family editor group specified in the CSV.
4. Transaction 1 -- Add all missing parameters.
5. For each newly added non-Text parameter, search existing family parameters by
   keyword (derived from the CP_* name) and build formula assignments:
   - CP_Weight       : matches weight params (not per-unit); /32.174 if lbf source
   - CP_Weight_Per_Foot : matches per-unit weight params; direct reference
   - Others          : keyword match on suffix; direct reference
   - 0 matches  -> skip (noted in report)
   - 1 match    -> auto-assign
   - 2+ matches -> user picks via dialog
6. Transaction 2 -- Set all formulas (rolls back on failure; T1 results kept).
7. Save and report summary.

Group -> Revit API mapping (from CSV 'Group' column):
  Constraints   -> PG_CONSTRAINTS  / GroupTypeId.Constraints
  Construction  -> PG_CONSTRUCTION / GroupTypeId.Construction
  Set           -> PG_SETS         / GroupTypeId.Sets
  Data          -> PG_DATA         / GroupTypeId.Data
  Identity Data -> PG_IDENTITY_DATA/ GroupTypeId.IdentityData

Version compatibility
---------------------
- Revit 2022+  : SpecTypeId / GroupTypeId  (ForgeTypeId API)
- Revit 2021-  : ParameterType / BuiltInParameterGroup
"""

from pyrevit import DB, forms, script
from shared_param_utils import (  # noqa: F401 -- lib/
    parse_param_csv,
    find_definition,
    is_output_param,
    is_per_unit,
    make_formula,
)

# ---------------------------------------------------------------------------
# CONFIGURE
# ---------------------------------------------------------------------------
GRAVITY_CONV = 32.174   # lbf -> lbm divisor
# When the Revit API cannot determine a source parameter's unit type, this flag
# controls whether mass-target parameters receive the / 32.174 conversion.
# True  = assume source is lbf (correct for most structural weight parameters).
# False = assume source is already lbm (direct reference, no conversion).
ASSUME_WEIGHT_SOURCE_IS_LBF = True
# ---------------------------------------------------------------------------

app = __revit__.Application                # noqa: F821
doc = __revit__.ActiveUIDocument.Document  # noqa: F821

REVIT_VERSION = int(app.VersionNumber)

# ---------------------------------------------------------------------------
# Group name -> Revit API constant (version-aware)
# ---------------------------------------------------------------------------
if REVIT_VERSION >= 2022:
    _GROUP_MAP = {
        'constraints':   DB.GroupTypeId.Constraints,
        'construction':  DB.GroupTypeId.Construction,
        'set':           getattr(DB.GroupTypeId, 'Sets', DB.GroupTypeId.Construction),
        'data':          DB.GroupTypeId.Data,
        'identity data': DB.GroupTypeId.IdentityData,
    }
else:
    _GROUP_MAP = {
        'constraints':   DB.BuiltInParameterGroup.PG_CONSTRAINTS,
        'construction':  DB.BuiltInParameterGroup.PG_CONSTRUCTION,
        'set':           getattr(DB.BuiltInParameterGroup, 'PG_SETS',
                                 DB.BuiltInParameterGroup.PG_CONSTRUCTION),
        'data':          DB.BuiltInParameterGroup.PG_DATA,
        'identity data': DB.BuiltInParameterGroup.PG_IDENTITY_DATA,
    }
_DEFAULT_GROUP = _GROUP_MAP['construction']


def _get_revit_group(group_name):
    return _GROUP_MAP.get(group_name.strip().lower(), _DEFAULT_GROUP)


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
# Prompt for files.
# ---------------------------------------------------------------------------
sp_file_path = forms.pick_file(
    file_ext="txt",
    title="Select Shared Parameter File",
)
if not sp_file_path:
    script.exit()

csv_file_path = forms.pick_file(
    file_ext="csv",
    title="Select Parameter CSV (Name, DataType, Instance, Group)",
)
if not csv_file_path:
    script.exit()

# ---------------------------------------------------------------------------
# Parse CSV.
# ---------------------------------------------------------------------------
try:
    param_list = parse_param_csv(csv_file_path)
except ValueError as ex:
    forms.alert("Could not read CSV:\n{}".format(str(ex)), exitscript=True)

if not param_list:
    forms.alert("CSV contains no parameter entries.", exitscript=True)

output_names = frozenset(p['name'] for p in param_list)

# ---------------------------------------------------------------------------
# Determine which parameters need to be added.
# ---------------------------------------------------------------------------
all_family_params = list(doc.FamilyManager.GetParameters())
existing_names    = frozenset(fp.Definition.Name for fp in all_family_params)
to_add            = [p for p in param_list if p['name'] not in existing_names]
already_exist     = [p['name'] for p in param_list if p['name'] in existing_names]

# ---------------------------------------------------------------------------
# Load all definitions upfront (before opening any transaction).
# ---------------------------------------------------------------------------
definitions  = {}   # name -> ExternalDefinition (or stub)
missing_defs = []
for p in to_add:
    try:
        definitions[p['name']] = find_definition(app, sp_file_path, p['name'])
    except ValueError:
        missing_defs.append(p['name'])

if missing_defs:
    forms.alert(
        "The following parameters were not found in the shared parameter file\n"
        "and will be skipped:\n\n  {}".format("\n  ".join(missing_defs)),
    )
    to_add = [p for p in to_add if p['name'] not in missing_defs]

# ---------------------------------------------------------------------------
# Helpers for unit-type detection and formula source lookup.
# ---------------------------------------------------------------------------
def _is_force(fp):
    """True if fp reports in lbf (Force or Structural Weight type).

    Tries three paths in order, catching AttributeError at each:
      1. fp.GetSpecTypeId()           -- direct on FamilyParameter (some 2022+ builds)
      2. fp.Definition.GetSpecTypeId()-- via Definition (Revit 2022+)
      3. fp.Definition.ParameterType  -- pre-2022 fallback
    Returns False if none are available (graceful degradation; no /32.174 applied).
    """
    for spec_getter in (
        lambda: fp.GetSpecTypeId(),
        lambda: fp.Definition.GetSpecTypeId(),
    ):
        try:
            spec = spec_getter()
            if spec == DB.SpecTypeId.Force:
                return True
            w = getattr(DB.SpecTypeId, 'Weight', None)
            return w is not None and spec == w
        except AttributeError:
            continue
    try:
        pt = fp.Definition.ParameterType
        if pt == DB.ParameterType.Force:
            return True
        w = getattr(DB.ParameterType, 'Weight', None)
        return w is not None and pt == w
    except AttributeError:
        return ASSUME_WEIGHT_SOURCE_IS_LBF


def _get_family_param(name):
    return next(
        (fp for fp in doc.FamilyManager.GetParameters()
         if fp.Definition.Name == name),
        None,
    )


# ---------------------------------------------------------------------------
# Transaction 1 -- Add missing parameters.
# ---------------------------------------------------------------------------
original_sp = app.SharedParametersFilename
added_names  = []

if to_add:
    t1 = DB.Transaction(doc, "Add Stratus Parameters")
    try:
        t1.Start()
        for p in to_add:
            defn        = definitions[p['name']]
            revit_group = _get_revit_group(p['group'])
            # SharedParametersFilename must be active at the moment of AddParameter.
            # find_definition already restored it; re-set here before each call.
            app.SharedParametersFilename = sp_file_path
            doc.FamilyManager.AddParameter(defn, revit_group, p['is_instance'])
            added_names.append(p['name'])
        t1.Commit()
    except Exception as ex:
        if t1.HasStarted() and not t1.HasEnded():
            t1.RollBack()
        app.SharedParametersFilename = original_sp or ""
        forms.alert("Failed to add parameters:\n{}".format(str(ex)), exitscript=True)
    finally:
        app.SharedParametersFilename = original_sp or ""
else:
    app.SharedParametersFilename = original_sp or ""

# ---------------------------------------------------------------------------
# Build formula assignments for newly added non-Text parameters.
#
# Keyword derivation: strip leading 'CP_', replace '_' with ' ', lowercase.
#   CP_Weight          -> 'weight' (want_per_unit=False)
#   CP_Weight_Per_Foot -> 'weight per foot' (want_per_unit=True)
#   CP_Length          -> 'length'
#
# The keyword is matched against existing family param names (substring match).
# output_names are excluded so we never create a circular formula.
# ---------------------------------------------------------------------------
all_family_params = list(doc.FamilyManager.GetParameters())  # re-fetch after T1

TEXT_DATATYPES = frozenset(('text',))
_MASS_DATATYPES = frozenset(('mass', 'mass per unit length'))

formula_assignments = {}   # added CP_* name -> formula string
formula_not_found   = []   # CP_* names where no matching source was found

for p in to_add:
    if p['data_type'].strip().lower() in TEXT_DATATYPES:
        continue

    param_name    = p['name']
    suffix        = param_name[3:] if param_name.upper().startswith('CP_') else param_name
    keyword       = suffix.replace('_', ' ').lower()
    want_per_unit = is_per_unit(param_name)

    candidates = [
        fp for fp in all_family_params
        if keyword in fp.Definition.Name.lower()
        and not is_output_param(fp.Definition.Name, output_names)
        and is_per_unit(fp.Definition.Name) == want_per_unit
    ]

    if not candidates:
        formula_not_found.append(param_name)
        continue

    if len(candidates) == 1:
        source_fp = candidates[0]
    else:
        names  = [fp.Definition.Name for fp in candidates]
        chosen = forms.ask_for_one_item(
            names,
            prompt="Multiple existing parameters match '{}'.\n"
                   "Which should '{}' reference?".format(keyword, param_name),
            title="Select Source Parameter",
        )
        if not chosen:
            formula_not_found.append(param_name)
            continue
        source_fp = next(fp for fp in candidates if fp.Definition.Name == chosen)

    # Apply /32.174 only when target is Mass and source reports in lbf.
    source_is_force = (
        p['data_type'].strip().lower() in _MASS_DATATYPES
        and _is_force(source_fp)
    )
    formula_assignments[param_name] = make_formula(
        source_fp.Definition.Name, source_is_force, GRAVITY_CONV
    )

# ---------------------------------------------------------------------------
# Transaction 2 -- Set formulas.
# Parameters from T1 are already saved; T2 rolls back independently on failure.
# ---------------------------------------------------------------------------
formula_failures = {}   # param_name -> error string
formula_set      = []

if formula_assignments:
    t2 = DB.Transaction(doc, "Set Stratus Parameter Formulas")
    try:
        t2.Start()
        for param_name, formula in formula_assignments.items():
            fp = _get_family_param(param_name)
            if fp is None:
                continue
            try:
                doc.FamilyManager.SetFormula(fp, formula)
                formula_set.append("{} = {}".format(param_name, formula))
            except Exception as ex:
                formula_failures[param_name] = str(ex)
        t2.Commit()
    except Exception as ex:
        if t2.HasStarted() and not t2.HasEnded():
            t2.RollBack()
        for param_name in formula_assignments:
            if param_name not in formula_failures:
                formula_failures[param_name] = str(ex)
        formula_set = []

# ---------------------------------------------------------------------------
# Save and report.
# ---------------------------------------------------------------------------
doc.Save()

lines = []

if added_names:
    lines.append("Added ({}):\n  {}".format(
        len(added_names), "\n  ".join(added_names)
    ))
else:
    lines.append("No new parameters added (all already exist).")

if already_exist:
    lines.append("\nAlready existed, skipped ({}):\n  {}".format(
        len(already_exist), "\n  ".join(already_exist)
    ))

if formula_set:
    lines.append("\nFormulas set ({}):\n  {}".format(
        len(formula_set), "\n  ".join(formula_set)
    ))

needs_manual = list(formula_not_found) + list(formula_failures.keys())
if needs_manual:
    lines.append(
        "\nNo source found / formula failed - enter manually ({}):\n  {}".format(
            len(needs_manual), "\n  ".join(needs_manual)
        )
    )
    if formula_failures:
        lines.append("\nFormula errors:")
        for name, err in formula_failures.items():
            lines.append("  {} : {}".format(name, err))

forms.alert("\n".join(lines), title="Stratus Parameters - Done")
