# -*- coding: utf-8 -*-
"""Stamp CP shared parameters onto every loadable family visible in the active view.

Works in a Revit project (.rvt) document. For each unique loadable family whose
instances appear in the active view, opens the family with EditFamily, applies the
same CSV-driven parameter + formula logic used by add_stratus_params, and reloads
the modified family back into the project.

Workflow
--------
1. Guard: must be a project document, not a family editor.
2. Prompt for the shared parameter .txt file and the parameter CSV.
3. Parse CSV; pre-load ExternalDefinitions for all CSV parameters once.
4. Collect unique loadable Family objects visible in the active view.
5. For each family:
   a. Open with doc.EditFamily(family).
   b. Determine which CSV parameters are missing from the family.
   c. Transaction 1: Add missing parameters (SharedParametersFilename re-set before each call).
   d. Re-fetch handles; build formula assignments by keyword matching.
   e. Transaction 2: Set formulas (independent rollback; T1 results kept on failure).
   f. Reload into project via LoadFamily; close the family doc.
6. Show per-family summary report.

Multi-match formula candidates (batch mode)
-------------------------------------------
Unlike add_stratus_params, this button does NOT show an interactive picker when
multiple source candidates match a keyword. Instead it takes the first candidate
alphabetically and notes the ambiguity in the final report. This avoids repeated
dialogs when many families are processed.

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
# ---------------------------------------------------------------------------

app = __revit__.Application                # noqa: F821
doc = __revit__.ActiveUIDocument.Document  # noqa: F821

REVIT_VERSION = int(app.VersionNumber)

# ---------------------------------------------------------------------------
# Group name -> Revit API constant (version-aware, same as add_stratus_params)
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
# IFamilyLoadOptions — overwrites existing parameters when reloading.
# out parameters in IronPython are exposed as clr.Reference[T] with a .Value attr.
# ---------------------------------------------------------------------------
class _FamilyLoadOptions(DB.IFamilyLoadOptions):
    def OnFamilyFound(self, familyInUse, overwriteParameterValues):
        overwriteParameterValues.Value = True
        return True

    def OnSharedFamilyFound(self, sharedFamily, familyInUse, source, overwriteParameterValues):
        source.Value = DB.FamilySource.Family
        overwriteParameterValues.Value = True
        return True


# ---------------------------------------------------------------------------
# Guard: project documents only.
# ---------------------------------------------------------------------------
if doc.IsFamilyDocument:
    forms.alert(
        "The active document is a family (.rfa).\n"
        "Open a Revit project (.rvt) and try again.\n\n"
        "To stamp parameters on a single open family, use add_stratus_params instead.",
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
# Pre-load all ExternalDefinitions ONCE before opening any family.
# find_definition restores SharedParametersFilename each call; we also restore
# here as a belt-and-suspenders measure.
# ---------------------------------------------------------------------------
definitions  = {}   # name -> ExternalDefinition
missing_defs = []
original_sp  = app.SharedParametersFilename

for p in param_list:
    try:
        definitions[p['name']] = find_definition(app, sp_file_path, p['name'])
    except ValueError:
        missing_defs.append(p['name'])

app.SharedParametersFilename = original_sp or ""

if missing_defs:
    forms.alert(
        "The following parameters were not found in the shared parameter file\n"
        "and will be skipped for all families:\n\n  {}".format(
            "\n  ".join(missing_defs)
        ),
    )

# ---------------------------------------------------------------------------
# Collect unique loadable families from the active view.
# ---------------------------------------------------------------------------
try:
    instances = (
        DB.FilteredElementCollector(doc, doc.ActiveView.Id)
        .OfClass(DB.FamilyInstance)
        .ToElements()
    )
except Exception as ex:
    forms.alert(
        "Could not collect families from the active view:\n{}".format(str(ex)),
        exitscript=True,
    )

families = {}   # ElementId -> Family
skipped_inplace = []
for fi in instances:
    try:
        fam = fi.Symbol.Family
    except Exception:
        continue
    if fam is None:
        continue
    if fam.IsInPlace:
        skipped_inplace.append(fam.Name)
        continue
    if not fam.IsEditable:
        continue
    families[fam.Id] = fam

if not families:
    msg = "No loadable families found in the active view.\n\n"
    if skipped_inplace:
        msg += "In-place families cannot be stamped with this button:\n  {}\n\n".format(
            "\n  ".join(set(skipped_inplace))
        )
    msg += "Make sure the active view contains placed loadable family instances."
    forms.alert(msg, exitscript=True)

# ---------------------------------------------------------------------------
# Unit-type helpers (depend on DB; cannot live in lib/).
# ---------------------------------------------------------------------------
def _is_force(fp):
    """True if fp reports in lbf (Force or Structural Weight type).

    Tries GetSpecTypeId() first (Revit 2022+ ForgeTypeId API); falls back to
    ParameterType (pre-2022) if the method is absent on InternalDefinition.
    """
    try:
        spec = fp.Definition.GetSpecTypeId()
        if spec == DB.SpecTypeId.Force:
            return True
        w = getattr(DB.SpecTypeId, 'Weight', None)
        return w is not None and spec == w
    except AttributeError:
        pt = fp.Definition.ParameterType
        if pt == DB.ParameterType.Force:
            return True
        w = getattr(DB.ParameterType, 'Weight', None)
        return w is not None and pt == w


TEXT_DATATYPES = frozenset(('text',))

# ---------------------------------------------------------------------------
# Per-family loop.
# ---------------------------------------------------------------------------
results       = []   # (family_name, status_str)
manual_needed = {}   # family_name -> [label_str, ...]

for family in families.values():
    fam_name = family.Name

    # Open family for editing.
    try:
        family_doc = doc.EditFamily(family)
    except Exception as ex:
        results.append((fam_name, "FAILED to open: {}".format(str(ex))))
        continue

    if family_doc is None:
        results.append((fam_name, "FAILED to open (EditFamily returned None)"))
        continue

    # Determine which params are missing from this family.
    try:
        existing = frozenset(
            fp.Definition.Name for fp in family_doc.FamilyManager.GetParameters()
        )
    except Exception as ex:
        family_doc.Close(False)
        results.append((fam_name, "FAILED reading params: {}".format(str(ex))))
        continue

    to_add = [
        p for p in param_list
        if p['name'] not in existing and p['name'] in definitions
    ]

    if not to_add:
        family_doc.Close(False)
        results.append((fam_name, "already complete — skipped"))
        continue

    # ------------------------------------------------------------------
    # Transaction 1 — Add missing parameters.
    # ------------------------------------------------------------------
    added_names = []
    t1 = DB.Transaction(family_doc, "Add Stratus Parameters")
    try:
        t1.Start()
        for p in to_add:
            app.SharedParametersFilename = sp_file_path
            family_doc.FamilyManager.AddParameter(
                definitions[p['name']],
                _get_revit_group(p['group']),
                p['is_instance'],
            )
            added_names.append(p['name'])
        t1.Commit()
    except Exception as ex:
        if t1.HasStarted() and not t1.HasEnded():
            t1.RollBack()
        app.SharedParametersFilename = original_sp or ""
        family_doc.Close(False)
        results.append((fam_name, "FAILED T1 (add params): {}".format(str(ex))))
        continue
    finally:
        app.SharedParametersFilename = original_sp or ""

    # Re-fetch handles after T1 commits.
    all_fp = list(family_doc.FamilyManager.GetParameters())

    # ------------------------------------------------------------------
    # Build formula assignments (keyword match, batch-mode: first-alpha on tie).
    # ------------------------------------------------------------------
    formula_assignments = {}   # param_name -> formula string
    no_source           = []   # param_names with no keyword match
    ambiguous           = []   # param_names where first-alpha was used

    for p in to_add:
        if p['data_type'].strip().lower() in TEXT_DATATYPES:
            continue

        param_name    = p['name']
        suffix        = param_name[3:] if param_name.upper().startswith('CP_') else param_name
        keyword       = suffix.replace('_', ' ').lower()
        want_per_unit = is_per_unit(param_name)

        candidates = sorted(
            [
                fp for fp in all_fp
                if keyword in fp.Definition.Name.lower()
                and not is_output_param(fp.Definition.Name, output_names)
                and is_per_unit(fp.Definition.Name) == want_per_unit
            ],
            key=lambda fp: fp.Definition.Name,
        )

        if not candidates:
            no_source.append(param_name)
            continue

        source_fp = candidates[0]
        if len(candidates) > 1:
            ambiguous.append(param_name)

        source_is_force = (
            p['data_type'].strip().lower() == 'mass'
            and _is_force(source_fp)
        )
        formula_assignments[param_name] = make_formula(
            source_fp.Definition.Name, source_is_force, GRAVITY_CONV
        )

    # ------------------------------------------------------------------
    # Transaction 2 — Set formulas.
    # ------------------------------------------------------------------
    formula_set      = []
    formula_failures = {}

    if formula_assignments:
        t2 = DB.Transaction(family_doc, "Set Stratus Parameter Formulas")
        try:
            t2.Start()
            for param_name, formula in formula_assignments.items():
                fp = next(
                    (f for f in family_doc.FamilyManager.GetParameters()
                     if f.Definition.Name == param_name),
                    None,
                )
                if fp is None:
                    continue
                try:
                    family_doc.FamilyManager.SetFormula(fp, formula)
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

    # ------------------------------------------------------------------
    # Reload into project; close family doc.
    # ------------------------------------------------------------------
    try:
        family_doc.LoadFamily(doc, _FamilyLoadOptions())
    except Exception as ex:
        family_doc.Close(False)
        results.append((fam_name, "FAILED reload: {}".format(str(ex))))
        continue
    family_doc.Close(False)

    # Build per-family status summary.
    parts = []
    if added_names:
        parts.append("{} param(s) added".format(len(added_names)))
    if formula_set:
        parts.append("{} formula(s) set".format(len(formula_set)))
    if formula_failures:
        parts.append("{} formula(s) failed".format(len(formula_failures)))
    if no_source:
        parts.append("{} need manual formula".format(len(no_source)))
        manual_needed.setdefault(fam_name, []).extend(no_source)
    if ambiguous:
        parts.append("{} ambiguous (first-alpha used)".format(len(ambiguous)))
        manual_needed.setdefault(fam_name, []).extend(
            ["{} (ambiguous — verify formula)".format(n) for n in ambiguous]
        )

    results.append((fam_name, " | ".join(parts) if parts else "complete"))

# ---------------------------------------------------------------------------
# Summary report.
# ---------------------------------------------------------------------------
lines = ["Families processed: {}\n".format(len(results))]

for fam_name, status in results:
    if status.startswith("already"):
        prefix = "~"
    elif "FAILED" in status:
        prefix = "!"
    else:
        prefix = "+"
    lines.append("  {} {}  --  {}".format(prefix, fam_name, status))

if manual_needed:
    lines.append("\nManual formula entry needed:")
    for fam_name, labels in manual_needed.items():
        lines.append("  {}:".format(fam_name))
        for label in labels:
            lines.append("    - {}".format(label))

forms.alert("\n".join(lines), title="stamp_view_families - Done")
