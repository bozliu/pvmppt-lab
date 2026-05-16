from pvmppt_lab.converter import BoostConverter, solve_operating_point
from pvmppt_lab.mppt import POController, simulate_po_mppt
from pvmppt_lab.pv import PVModule


def test_po_direction_matches_boost_voltage_convention():
    controller = POController()
    assert controller.direction(delta_power=1.0, delta_voltage=1.0) == -1
    assert controller.direction(delta_power=0.0, delta_voltage=1.0) == -1
    assert controller.direction(delta_power=-1.0, delta_voltage=1.0) == 1
    assert controller.clamp(2.0) == controller.max_duty


def test_po_optional_deadband_can_hold_small_changes():
    controller = POController(deadband=1e-6)
    assert controller.direction(delta_power=1e-4, delta_voltage=1e-4) == 0


def test_boost_input_resistance_decreases_as_duty_increases():
    converter = BoostConverter(load_resistance_ohm=12.5)
    assert converter.input_resistance(0.6) < converter.input_resistance(0.2)


def test_operating_point_is_physical():
    module = PVModule()
    converter = BoostConverter()
    op = solve_operating_point(module, converter, 0.45, 1000.0, 25.0)
    assert op.voltage_v > 0
    assert op.current_a > 0
    assert op.power_w > 0


def test_mppt_simulation_tracks_nonzero_energy():
    df, metrics = simulate_po_mppt(total_time_s=0.03)
    assert len(df) > 10
    assert metrics["energy_pv_j"] > 0
    assert metrics["energy_mpp_j"] >= metrics["energy_pv_j"]
    assert 0 < metrics["tracking_efficiency"] <= 1.05
