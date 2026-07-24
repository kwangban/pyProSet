# -*- coding: utf-8 -*-
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))

from shared_param_utils import StubSharedParamFile, StubApp, load_definition, make_formula, is_per_unit, is_output_param

SAMPLE_SP = (
    "*META\tVERSION\tMINVERSION\n"
    "META\t2\t1\n"
    "*GROUP\tID\tNAME\n"
    "GROUP\t4\tTEST\n"
    "*PARAM\tGUID\tNAME\tDATATYPE\tDATACATEGORY\tGROUP\tVISIBLE\tDESCRIPTION\tUSERMODIFIABLE\n"
    "PARAM\tb8c244bb-d8e4-4b60-8f63-df41cb0591cb\tTEST_weight\tMASS\t\t4\t1\tWeight in lbm\t1\n"
)

MULTI_GROUP_SP = (
    "*META\tVERSION\tMINVERSION\n"
    "META\t2\t1\n"
    "*GROUP\tID\tNAME\n"
    "GROUP\t1\tGroupA\n"
    "GROUP\t2\tGroupB\n"
    "*PARAM\tGUID\tNAME\tDATATYPE\tDATACATEGORY\tGROUP\tVISIBLE\tDESCRIPTION\tUSERMODIFIABLE\n"
    "PARAM\taaaa-0001\tParamA\tTEXT\t\t1\t1\t\t1\n"
    "PARAM\taaaa-0002\tParamB\tTEXT\t\t2\t1\t\t1\n"
)


class TestIsPerUnit:
    def test_per_foot_excluded(self):
        assert is_per_unit("Weight_per_foot") is True

    def test_per_ft_excluded(self):
        assert is_per_unit("Weight_per_ft") is True

    def test_per_meter_excluded(self):
        assert is_per_unit("Weight_per_meter") is True

    def test_per_m_excluded(self):
        assert is_per_unit("Weight_per_m") is True

    def test_slash_ft_excluded(self):
        assert is_per_unit("Weight/ft") is True

    def test_linear_excluded(self):
        assert is_per_unit("Weight_linear") is True

    def test_plain_weight_allowed(self):
        assert is_per_unit("Weight") is False

    def test_total_weight_allowed(self):
        assert is_per_unit("Total_Weight") is False

    def test_case_insensitive(self):
        assert is_per_unit("WEIGHT_PER_FOOT") is True


class TestIsOutputParam:
    def test_erp_weight_is_output(self):
        assert is_output_param("CP_ERP_Weight") is True

    def test_bom_weight_is_output(self):
        assert is_output_param("CP_BOM_Weight") is True

    def test_plain_weight_is_not_output(self):
        assert is_output_param("Weight") is False

    def test_check_is_case_sensitive(self):
        assert is_output_param("cp_erp_weight") is False


class TestMakeFormula:
    def test_force_param_gets_division_formula(self):
        assert make_formula("Weight", True) == "Weight / 32.174"

    def test_mass_param_gets_direct_reference(self):
        assert make_formula("Weight", False) == "Weight"

    def test_formula_preserves_exact_param_name(self):
        assert make_formula("My Weird Name", True) == "My Weird Name / 32.174"

    def test_custom_gravity_constant(self):
        assert make_formula("W", True, gravity_conv=9.81) == "W / 9.81"

    def test_mass_ignores_gravity_constant(self):
        assert make_formula("W", False, gravity_conv=9.81) == "W"


class TestStubSharedParamFile:
    def test_parses_single_group(self, tmp_path):
        sp = tmp_path / "params.txt"
        sp.write_text(SAMPLE_SP)
        stub = StubSharedParamFile(str(sp))
        assert len(stub.Groups) == 1
        assert stub.Groups[0].Name == "TEST"

    def test_parses_param_in_group(self, tmp_path):
        sp = tmp_path / "params.txt"
        sp.write_text(SAMPLE_SP)
        stub = StubSharedParamFile(str(sp))
        assert len(stub.Groups[0].Definitions) == 1
        assert stub.Groups[0].Definitions[0].Name == "TEST_weight"

    def test_parses_multiple_groups(self, tmp_path):
        sp = tmp_path / "params.txt"
        sp.write_text(MULTI_GROUP_SP)
        stub = StubSharedParamFile(str(sp))
        names = [g.Name for g in stub.Groups]
        assert "GroupA" in names
        assert "GroupB" in names

    def test_params_assigned_to_correct_group(self, tmp_path):
        sp = tmp_path / "params.txt"
        sp.write_text(MULTI_GROUP_SP)
        stub = StubSharedParamFile(str(sp))
        group_a = next(g for g in stub.Groups if g.Name == "GroupA")
        assert group_a.Definitions[0].Name == "ParamA"

    def test_param_data_type_parsed(self, tmp_path):
        sp = tmp_path / "params.txt"
        sp.write_text(SAMPLE_SP)  # SAMPLE_SP defines MASS for TEST_weight
        stub = StubSharedParamFile(str(sp))
        assert stub.Groups[0].Definitions[0].DataType == "MASS"

    def test_param_data_type_number(self, tmp_path):
        minimal = (
            "*GROUP\tID\tNAME\n"
            "GROUP\t1\tG\n"
            "*PARAM\tGUID\tNAME\tDATATYPE\tDATACATEGORY\tGROUP\tVISIBLE\tDESCRIPTION\tUSERMODIFIABLE\n"
            "PARAM\tguid\tP\tNUMBER\t\t1\t1\t\t1\n"
        )
        sp = tmp_path / "p.txt"
        sp.write_text(minimal)
        stub = StubSharedParamFile(str(sp))
        assert stub.Groups[0].Definitions[0].DataType == "NUMBER"


class TestLoadDefinitionPathRestoration:
    """Document the SharedParametersFilename contract.

    In CPython (no Revit), _REVIT_AVAILABLE is False, so load_definition always
    takes the stub branch and never touches app.SharedParametersFilename.  These
    tests use StubApp to verify the interface and to pin the expected behaviour
    for the Revit path: after load_definition returns, the caller must re-set
    app.SharedParametersFilename before calling FamilyManager.AddParameter().
    """

    def test_stub_app_accepted_without_error(self, tmp_path):
        sp = tmp_path / "params.txt"
        sp.write_text(SAMPLE_SP)
        app = StubApp(shared_params_filename="original_path")
        defn = load_definition(app, str(sp), "TEST", "TEST_weight")
        assert defn.Name == "TEST_weight"

    def test_stub_app_filename_unchanged_after_call(self, tmp_path):
        # In stub mode (CPython), load_definition never touches the filename.
        # In Revit mode it would restore it — this test documents that the
        # contract is "filename is the same before and after the call".
        sp = tmp_path / "params.txt"
        sp.write_text(SAMPLE_SP)
        app = StubApp(shared_params_filename="original_path")
        load_definition(app, str(sp), "TEST", "TEST_weight")
        assert app.SharedParametersFilename == "original_path"

    def test_stub_app_raises_on_missing_param(self, tmp_path):
        sp = tmp_path / "params.txt"
        sp.write_text(SAMPLE_SP)
        app = StubApp()
        with pytest.raises(ValueError, match="Parameter 'MISSING'"):
            load_definition(app, str(sp), "TEST", "MISSING")


class TestLoadDefinition:
    def test_returns_correct_definition(self, tmp_path):
        sp = tmp_path / "params.txt"
        sp.write_text(SAMPLE_SP)
        defn = load_definition(None, str(sp), "TEST", "TEST_weight")
        assert defn.Name == "TEST_weight"

    def test_raises_on_missing_group(self, tmp_path):
        sp = tmp_path / "params.txt"
        sp.write_text(SAMPLE_SP)
        with pytest.raises(ValueError, match="Group 'MISSING'"):
            load_definition(None, str(sp), "MISSING", "TEST_weight")

    def test_raises_on_missing_param(self, tmp_path):
        sp = tmp_path / "params.txt"
        sp.write_text(SAMPLE_SP)
        with pytest.raises(ValueError, match="Parameter 'MISSING'"):
            load_definition(None, str(sp), "TEST", "MISSING")

    def test_raises_on_missing_file(self, tmp_path):
        with pytest.raises(ValueError, match="not found"):
            load_definition(None, str(tmp_path / "nonexistent.txt"), "TEST", "TEST_weight")

    def test_multiple_groups_cross_lookup(self, tmp_path):
        sp = tmp_path / "params.txt"
        sp.write_text(MULTI_GROUP_SP)
        defn_a = load_definition(None, str(sp), "GroupA", "ParamA")
        defn_b = load_definition(None, str(sp), "GroupB", "ParamB")
        assert defn_a.Name == "ParamA"
        assert defn_b.Name == "ParamB"

    def test_wrong_group_for_param_raises(self, tmp_path):
        sp = tmp_path / "params.txt"
        sp.write_text(MULTI_GROUP_SP)
        with pytest.raises(ValueError, match="Parameter 'ParamB'"):
            load_definition(None, str(sp), "GroupA", "ParamB")
