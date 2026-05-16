import pytest

from pvmppt_lab.reproduction import (
    RUPESH_PANEL,
    current_at_voltage,
    run_reproduction_suite,
    scaled_curve,
)


def test_single_diode_current_decreases_with_voltage():
    low_voltage_current = current_at_voltage(RUPESH_PANEL, 1.0, 1000.0, 25.0)
    high_voltage_current = current_at_voltage(RUPESH_PANEL, 18.0, 1000.0, 25.0)

    assert low_voltage_current > high_voltage_current
    assert low_voltage_current > 0


def test_array_scaling_preserves_expected_power_ratio():
    single = scaled_curve(RUPESH_PANEL, 1000.0, 25.0, 1, 1, points=64)
    doubled = scaled_curve(RUPESH_PANEL, 1000.0, 25.0, 2, 2, points=64)

    assert doubled["power_w"].max() == pytest.approx(single["power_w"].max() * 4, rel=0.02)


def test_reproduction_all_suites_emit_artifacts(tmp_path):
    output = tmp_path / "reproduction"
    payload = run_reproduction_suite(output, suite="all", points=32)

    assert payload["summary"]["completed_suites"] == [
        "pv-cell",
        "pv-module",
        "pv-array",
        "mppt",
        "converter",
    ]
    assert (output / "summary.json").exists()
    assert (output / "pv-cell" / "parameter_sweeps.csv").exists()
    assert (output / "pv-module" / "pv_module_mpp.csv").exists()
    assert (output / "pv-array" / "pv_array_mpp.csv").exists()
    assert (output / "mppt" / "mppt_fixed_500w_25c" / "mppt_trace.csv").exists()
    assert (output / "converter" / "converter_reference.csv").exists()
    metrics = payload["summary"]["metrics"]
    assert metrics["mppt"]["fixed_tracking_efficiency"] > 0.9
    assert metrics["converter"]["reference_rows"] == 7
