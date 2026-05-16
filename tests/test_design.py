import json
import importlib.util
from pathlib import Path

import pandas as pd
import pytest

from pvmppt_lab.design import design_module, fit_module, load_module_design_spec, validate_module


EXAMPLE_SPEC = Path("docs/examples/trina-module.yaml")


def test_load_design_spec_from_yaml():
    spec = load_module_design_spec(EXAMPLE_SPEC)

    assert spec.name == "Trina Solar TSM-250PA05.08"
    assert spec.cells_in_series == 60
    assert spec.array_series_modules == 10
    assert spec.array_parallel_strings == 4
    assert spec.points == 240


def test_design_module_outputs_curves_tables_plots_and_report(tmp_path):
    output = tmp_path / "design"
    summary = design_module(EXAMPLE_SPEC, output)

    assert summary["workflow"] == "python-only module design"
    assert (output / "design_summary.json").exists()
    assert (output / "iv_pv_curves.csv").exists()
    assert (output / "mpp_table.csv").exists()
    assert (output / "sensitivity.csv").exists()
    assert (output / "array_iv_pv_curves.csv").exists()
    assert (output / "array_mpp_table.csv").exists()
    assert (output / "iv_curves.png").stat().st_size > 0
    assert (output / "pv_curves.png").stat().st_size > 0
    assert (output / "sensitivity.png").stat().st_size > 0
    assert (output / "design_report.md").exists()
    curves = pd.read_csv(output / "iv_pv_curves.csv")
    sensitivity = pd.read_csv(output / "sensitivity.csv")
    assert len(curves) == 16 * 240
    assert set(sensitivity["parameter"]) >= {
        "irradiance_w_m2",
        "temperature_c",
        "series_resistance_ohm",
        "shunt_resistance_ohm",
        "saturation_current_ref_a",
    }
    assert abs(summary["metrics"]["datasheet_pmp_error_pct"]) < 1.0


def test_validate_module_internal_backend(tmp_path):
    output = tmp_path / "validation"
    summary = validate_module(EXAMPLE_SPEC, output, backend="internal")

    assert summary["status"] == "pass"
    assert summary["backend"] == "internal"
    assert (output / "validation_mpp.csv").exists()
    rows = pd.read_csv(output / "validation_mpp.csv")
    assert rows.loc[0, "backend"] == "internal"


def test_fit_module_emits_fitted_spec_and_mpp_table(tmp_path):
    output = tmp_path / "fit"
    summary = fit_module(EXAMPLE_SPEC, output, method="desoto")

    assert summary["method"] == "desoto"
    assert (output / "fitted_module.yaml").exists()
    assert (output / "fit_mpp_table.csv").exists()
    payload = json.loads((output / "fit_summary.json").read_text(encoding="utf-8"))
    assert payload["workflow"] == "python-only module fit"


def test_validate_module_pvlib_backend_requires_optional_dependency(tmp_path):
    if importlib.util.find_spec("pvlib") is not None:
        pytest.skip("pvlib is installed in this environment")
    with pytest.raises(RuntimeError, match="pvlib backend requires"):
        validate_module(EXAMPLE_SPEC, tmp_path / "validation", backend="pvlib")
