from __future__ import annotations

from dataclasses import asdict, dataclass
import math

import numpy as np
from scipy.optimize import brentq


K_BOLTZMANN = 1.380649e-23
Q_ELECTRON = 1.602176634e-19
T_REF_K = 298.15
G_REF = 1000.0


@dataclass(frozen=True)
class PVOperatingPoint:
    voltage_v: float
    current_a: float
    power_w: float
    irradiance_w_m2: float
    temperature_c: float


@dataclass(frozen=True)
class PVModule:
    """Single-diode module model calibrated from datasheet-style parameters."""

    name: str = "Trina Solar TSM-250PA05.08"
    cells_in_series: int = 60
    pmp_ref_w: float = 249.86
    voc_ref_v: float = 37.6
    isc_ref_a: float = 8.55
    vmp_ref_v: float = 31.0
    imp_ref_a: float = 8.06
    alpha_isc_a_per_c: float = 0.00513
    beta_voc_v_per_c: float = -0.1316
    light_current_ref_a: float = 8.5795
    saturation_current_ref_a: float = 2.0381e-10
    series_resistance_ohm: float = 0.247
    shunt_resistance_ohm: float = 301.8149
    ideality_factor: float = 0.99766
    band_gap_ev: float = 1.121

    def to_dict(self) -> dict[str, float | int | str]:
        return asdict(self)

    def thermal_voltage(self, temperature_c: float) -> float:
        temperature_k = temperature_c + 273.15
        return (
            self.ideality_factor
            * self.cells_in_series
            * K_BOLTZMANN
            * temperature_k
            / Q_ELECTRON
        )

    def photocurrent(self, irradiance_w_m2: float, temperature_c: float) -> float:
        if irradiance_w_m2 <= 0:
            return 0.0
        return (
            self.light_current_ref_a
            + self.alpha_isc_a_per_c * (temperature_c - 25.0)
        ) * (irradiance_w_m2 / G_REF)

    def saturation_current(self, temperature_c: float) -> float:
        temperature_k = temperature_c + 273.15
        exponent = (self.band_gap_ev * Q_ELECTRON) / (
            self.ideality_factor * K_BOLTZMANN
        ) * (1.0 / T_REF_K - 1.0 / temperature_k)
        exponent = float(np.clip(exponent, -80.0, 80.0))
        return self.saturation_current_ref_a * (temperature_k / T_REF_K) ** 3 * math.exp(
            exponent
        )

    def estimate_voc(self, irradiance_w_m2: float, temperature_c: float) -> float:
        if irradiance_w_m2 <= 0:
            return 0.0
        g_ratio = max(irradiance_w_m2 / G_REF, 1e-6)
        irradiance_shift = self.thermal_voltage(temperature_c) * math.log(g_ratio)
        temperature_shift = self.beta_voc_v_per_c * (temperature_c - 25.0)
        return max(0.0, self.voc_ref_v + irradiance_shift + temperature_shift)

    def current_at_voltage(
        self, voltage_v: float, irradiance_w_m2: float = G_REF, temperature_c: float = 25.0
    ) -> float:
        if irradiance_w_m2 <= 0 or voltage_v < 0:
            return 0.0

        iph = self.photocurrent(irradiance_w_m2, temperature_c)
        i0 = self.saturation_current(temperature_c)
        a = max(self.thermal_voltage(temperature_c), 1e-9)
        rs = self.series_resistance_ohm
        rsh = max(self.shunt_resistance_ohm, 1e-9)

        def residual(current_a: float) -> float:
            diode_arg = np.clip((voltage_v + current_a * rs) / a, -100.0, 100.0)
            diode_current = i0 * math.expm1(float(diode_arg))
            shunt_current = (voltage_v + current_a * rs) / rsh
            return iph - diode_current - shunt_current - current_a

        if residual(0.0) <= 0.0:
            return 0.0

        upper = max(iph * 1.5 + 0.5, self.isc_ref_a * 1.5)
        for _ in range(8):
            if residual(upper) < 0.0:
                break
            upper *= 2.0
        else:
            return max(0.0, iph)

        return max(0.0, float(brentq(residual, 0.0, upper, xtol=1e-9, maxiter=100)))

    def curve(
        self,
        irradiance_w_m2: float = G_REF,
        temperature_c: float = 25.0,
        points: int = 240,
    ) -> dict[str, np.ndarray]:
        voc = self.estimate_voc(irradiance_w_m2, temperature_c)
        voltages = np.linspace(0.0, max(voc * 1.02, 0.1), points)
        currents = np.array(
            [
                self.current_at_voltage(v, irradiance_w_m2, temperature_c)
                for v in voltages
            ]
        )
        powers = voltages * currents
        return {"voltage_v": voltages, "current_a": currents, "power_w": powers}

    def max_power_point(
        self,
        irradiance_w_m2: float = G_REF,
        temperature_c: float = 25.0,
        points: int = 720,
    ) -> PVOperatingPoint:
        curve = self.curve(irradiance_w_m2, temperature_c, points=points)
        index = int(np.argmax(curve["power_w"]))
        return PVOperatingPoint(
            voltage_v=float(curve["voltage_v"][index]),
            current_a=float(curve["current_a"][index]),
            power_w=float(curve["power_w"][index]),
            irradiance_w_m2=float(irradiance_w_m2),
            temperature_c=float(temperature_c),
        )
