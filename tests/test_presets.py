import pytest

from pvmppt_lab.presets import (
    REFERENCE_BUCK_BOOST,
    REFERENCE_PO_CONTROLLER,
    REFERENCE_TRINA_ARRAY,
)


def test_trina_array_reference_values():
    assert REFERENCE_TRINA_ARRAY.series_modules == 10
    assert REFERENCE_TRINA_ARRAY.parallel_strings == 4
    assert REFERENCE_TRINA_ARRAY.pmp_ref_w == pytest.approx(9994.4)
    assert REFERENCE_TRINA_ARRAY.vmp_ref_v == 310.0
    assert REFERENCE_TRINA_ARRAY.imp_ref_a == pytest.approx(32.24)
    assert REFERENCE_TRINA_ARRAY.voc_ref_v == 376.0
    assert REFERENCE_TRINA_ARRAY.isc_ref_a == pytest.approx(34.2)


def test_controller_reference_values():
    assert REFERENCE_PO_CONTROLLER.delta_d == 0.001
    assert REFERENCE_PO_CONTROLLER.min_duty == 0.0
    assert REFERENCE_PO_CONTROLLER.max_duty == 0.8
    assert REFERENCE_PO_CONTROLLER.sample_time_s == 1e-4
    assert REFERENCE_PO_CONTROLLER.filter_time_constant_s == 1e-3


def test_buck_boost_reference_values():
    assert REFERENCE_BUCK_BOOST.dc_source_v == 48.0
    assert REFERENCE_BUCK_BOOST.main_pulse_period_s == 0.0001
    assert REFERENCE_BUCK_BOOST.main_pulse_width_pct == 5.0
    assert REFERENCE_BUCK_BOOST.complementary_pulse_width_pct == 95.0
    assert REFERENCE_BUCK_BOOST.inductor_h == 0.01e-3
    assert REFERENCE_BUCK_BOOST.capacitor_f == 2200e-6
    assert REFERENCE_BUCK_BOOST.load_resistance_ohm == 100.0
    assert REFERENCE_BUCK_BOOST.solver_sample_time_s == 1e-6
