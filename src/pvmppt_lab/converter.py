from __future__ import annotations

from dataclasses import asdict, dataclass

from scipy.optimize import brentq

from .pv import PVModule, PVOperatingPoint


@dataclass(frozen=True)
class BoostConverter:
    """Averaged boost converter load-reflection model."""

    load_resistance_ohm: float = 12.5
    efficiency: float = 0.96
    min_duty: float = 0.0
    max_duty: float = 0.8

    def to_dict(self) -> dict[str, float]:
        return asdict(self)

    def clamp_duty(self, duty: float) -> float:
        return min(self.max_duty, max(self.min_duty, float(duty)))

    def input_resistance(self, duty: float) -> float:
        duty = self.clamp_duty(duty)
        return max(1e-9, self.load_resistance_ohm * (1.0 - duty) ** 2 / self.efficiency)

    def output_voltage(self, input_voltage_v: float, duty: float) -> float:
        duty = self.clamp_duty(duty)
        return self.efficiency * input_voltage_v / max(1e-6, 1.0 - duty)

    def output_current(self, input_voltage_v: float, duty: float) -> float:
        return self.output_voltage(input_voltage_v, duty) / self.load_resistance_ohm


def solve_operating_point(
    module: PVModule,
    converter: BoostConverter,
    duty: float,
    irradiance_w_m2: float,
    temperature_c: float,
) -> PVOperatingPoint:
    """Find the PV operating point where PV current matches reflected load current."""

    rin = converter.input_resistance(duty)
    voc = module.estimate_voc(irradiance_w_m2, temperature_c)
    if voc <= 0:
        return PVOperatingPoint(0.0, 0.0, 0.0, irradiance_w_m2, temperature_c)

    def residual(voltage_v: float) -> float:
        return module.current_at_voltage(voltage_v, irradiance_w_m2, temperature_c) - (
            voltage_v / rin
        )

    low, high = 0.0, voc
    if residual(low) <= 0:
        voltage = 0.0
    elif residual(high) >= 0:
        voltage = high
    else:
        voltage = float(brentq(residual, low, high, xtol=1e-7, maxiter=100))
    current = module.current_at_voltage(voltage, irradiance_w_m2, temperature_c)
    return PVOperatingPoint(
        voltage_v=voltage,
        current_a=current,
        power_w=voltage * current,
        irradiance_w_m2=float(irradiance_w_m2),
        temperature_c=float(temperature_c),
    )


def ideal_inverting_buck_boost_output(input_voltage_v: float, duty: float) -> float:
    duty = min(0.95, max(0.0, float(duty)))
    return -input_voltage_v * duty / max(1e-9, 1.0 - duty)
