from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Callable

import numpy as np
import pandas as pd

from .converter import BoostConverter, solve_operating_point
from .pv import PVModule


@dataclass(frozen=True)
class POController:
    delta_d: float = 0.001
    initial_duty: float = 0.45
    min_duty: float = 0.0
    max_duty: float = 0.8
    sample_time_s: float = 1e-4
    filter_time_constant_s: float = 1e-3
    deadband: float = 0.0

    def to_dict(self) -> dict[str, float]:
        return asdict(self)

    def clamp(self, duty: float) -> float:
        return min(self.max_duty, max(self.min_duty, float(duty)))

    def direction(self, delta_power: float, delta_voltage: float) -> int:
        product = delta_power * delta_voltage
        if self.deadband > 0.0 and abs(product) <= self.deadband:
            return 0
        # Boost-converter convention: duty down moves PV voltage up.
        return -1 if product >= 0 else 1

    def update(self, duty: float, delta_power: float, delta_voltage: float) -> float:
        return self.clamp(duty + self.delta_d * self.direction(delta_power, delta_voltage))


def default_irradiance_profile(total_time_s: float) -> Callable[[float], float]:
    def profile(t: float) -> float:
        fraction = t / max(total_time_s, 1e-12)
        if fraction < 0.25:
            return 800.0
        if fraction < 0.55:
            return 1000.0
        if fraction < 0.8:
            return 650.0
        return 900.0

    return profile


def simulate_po_mppt(
    module: PVModule | None = None,
    converter: BoostConverter | None = None,
    controller: POController | None = None,
    total_time_s: float = 0.25,
    temperature_c: float = 25.0,
    irradiance_profile: Callable[[float], float] | None = None,
) -> tuple[pd.DataFrame, dict[str, float]]:
    module = module or PVModule()
    converter = converter or BoostConverter()
    controller = controller or POController()
    irradiance_profile = irradiance_profile or default_irradiance_profile(total_time_s)

    dt = controller.sample_time_s
    steps = int(round(total_time_s / dt)) + 1
    duty = controller.clamp(controller.initial_duty)
    alpha = dt / (controller.filter_time_constant_s + dt)

    v_filtered = None
    i_filtered = None
    previous_v = None
    previous_p = None
    rows: list[dict[str, float]] = []

    for step in range(steps):
        t = step * dt
        irradiance = float(irradiance_profile(t))
        op = solve_operating_point(module, converter, duty, irradiance, temperature_c)
        mpp = module.max_power_point(irradiance, temperature_c, points=360)

        if v_filtered is None:
            v_filtered = op.voltage_v
            i_filtered = op.current_a
        else:
            v_filtered = v_filtered + alpha * (op.voltage_v - v_filtered)
            i_filtered = i_filtered + alpha * (op.current_a - i_filtered)
        p_filtered = v_filtered * i_filtered

        rows.append(
            {
                "time_s": t,
                "irradiance_w_m2": irradiance,
                "temperature_c": temperature_c,
                "duty": duty,
                "v_pv": op.voltage_v,
                "i_pv": op.current_a,
                "p_pv": op.power_w,
                "v_filtered": v_filtered,
                "i_filtered": i_filtered,
                "p_filtered": p_filtered,
                "v_mpp": mpp.voltage_v,
                "i_mpp": mpp.current_a,
                "p_mpp": mpp.power_w,
                "instant_tracking_efficiency": op.power_w / mpp.power_w
                if mpp.power_w > 0
                else 0.0,
            }
        )

        if previous_v is not None and previous_p is not None:
            duty = controller.update(duty, p_filtered - previous_p, v_filtered - previous_v)
        previous_v = v_filtered
        previous_p = p_filtered

    df = pd.DataFrame(rows)
    energy_pv = float(np.trapezoid(df["p_pv"], df["time_s"]))
    energy_mpp = float(np.trapezoid(df["p_mpp"], df["time_s"]))
    within_2_pct = df[df["instant_tracking_efficiency"] >= 0.98]
    convergence_time = (
        float(within_2_pct.iloc[0]["time_s"]) if not within_2_pct.empty else float("nan")
    )
    metrics = {
        "energy_pv_j": energy_pv,
        "energy_mpp_j": energy_mpp,
        "tracking_efficiency": energy_pv / energy_mpp if energy_mpp > 0 else 0.0,
        "mean_power_w": float(df["p_pv"].mean()),
        "mean_mpp_power_w": float(df["p_mpp"].mean()),
        "steady_state_duty": float(df["duty"].iloc[-1]),
        "steady_state_power_w": float(df["p_pv"].tail(max(1, steps // 10)).mean()),
        "convergence_time_98pct_s": convergence_time,
    }
    return df, metrics
