from pvmppt_lab.pv import PVModule


def test_reference_mpp_is_close_to_datasheet():
    module = PVModule()
    mpp = module.max_power_point(1000.0, 25.0)
    error = abs(mpp.power_w - module.pmp_ref_w) / module.pmp_ref_w
    assert error < 0.12
    assert 0.85 * module.vmp_ref_v < mpp.voltage_v < 1.15 * module.vmp_ref_v
    assert 0.85 * module.imp_ref_a < mpp.current_a < 1.15 * module.imp_ref_a


def test_power_increases_with_irradiance_at_reference_temperature():
    module = PVModule()
    low = module.max_power_point(500.0, 25.0)
    high = module.max_power_point(1000.0, 25.0)
    assert high.power_w > low.power_w * 1.8


def test_power_drops_with_high_temperature():
    module = PVModule()
    cool = module.max_power_point(1000.0, 25.0)
    hot = module.max_power_point(1000.0, 75.0)
    assert hot.power_w < cool.power_w
