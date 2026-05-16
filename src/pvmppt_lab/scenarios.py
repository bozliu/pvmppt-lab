from __future__ import annotations

from pathlib import Path

import pandas as pd

from .converter import BoostConverter
from .mppt import POController, simulate_po_mppt
from .pv import PVModule
from .reporting import ensure_dir, plot_mppt, plot_static_curves, write_json


def run_static_sweep(
    output_dir: Path,
    irradiances: list[float] | None = None,
    temperatures: list[float] | None = None,
    points: int = 240,
) -> dict[str, object]:
    output_dir = ensure_dir(output_dir)
    module = PVModule()
    irradiances = irradiances or [400.0, 650.0, 800.0, 1000.0]
    temperatures = temperatures or [0.0, 25.0, 50.0, 75.0]
    rows: list[dict[str, float]] = []
    mpp_rows: list[dict[str, float]] = []

    for irradiance in irradiances:
        for temperature in temperatures:
            curve = module.curve(irradiance, temperature, points=points)
            mpp = module.max_power_point(irradiance, temperature)
            mpp_rows.append(
                {
                    "irradiance_w_m2": irradiance,
                    "temperature_c": temperature,
                    "v_mpp": mpp.voltage_v,
                    "i_mpp": mpp.current_a,
                    "p_mpp": mpp.power_w,
                }
            )
            for voltage, current, power in zip(
                curve["voltage_v"], curve["current_a"], curve["power_w"]
            ):
                rows.append(
                    {
                        "irradiance_w_m2": irradiance,
                        "temperature_c": temperature,
                        "voltage_v": float(voltage),
                        "current_a": float(current),
                        "power_w": float(power),
                    }
                )

    curve_df = pd.DataFrame(rows)
    mpp_df = pd.DataFrame(mpp_rows)
    curve_csv = output_dir / "static_curves.csv"
    mpp_csv = output_dir / "static_mpp.csv"
    curve_df.to_csv(curve_csv, index=False)
    mpp_df.to_csv(mpp_csv, index=False)
    plots = plot_static_curves(curve_df, output_dir)
    ref_mpp = module.max_power_point(1000.0, 25.0)
    metrics = {
        "module": module.to_dict(),
        "reference_mpp_power_w": ref_mpp.power_w,
        "datasheet_pmp_ref_w": module.pmp_ref_w,
        "reference_pmp_error_pct": 100.0
        * (ref_mpp.power_w - module.pmp_ref_w)
        / module.pmp_ref_w,
        "scenario_count": len(mpp_rows),
        "curve_rows": len(rows),
    }
    write_json(output_dir / "metrics.json", metrics)
    return {
        "output_dir": str(output_dir),
        "curves_csv": str(curve_csv),
        "mpp_csv": str(mpp_csv),
        "plots": [str(p) for p in plots],
        "metrics": metrics,
    }


def run_mppt_demo(
    output_dir: Path,
    total_time_s: float = 0.25,
    temperature_c: float = 25.0,
) -> dict[str, object]:
    output_dir = ensure_dir(output_dir)
    module = PVModule()
    converter = BoostConverter()
    controller = POController()
    df, metrics = simulate_po_mppt(
        module=module,
        converter=converter,
        controller=controller,
        total_time_s=total_time_s,
        temperature_c=temperature_c,
    )
    trace_csv = output_dir / "mppt_trace.csv"
    df.to_csv(trace_csv, index=False)
    plots = plot_mppt(df, output_dir)
    payload = {
        **metrics,
        "module": module.to_dict(),
        "converter": converter.to_dict(),
        "controller": controller.to_dict(),
        "rows": int(len(df)),
    }
    write_json(output_dir / "metrics.json", payload)
    return {
        "output_dir": str(output_dir),
        "trace_csv": str(trace_csv),
        "plots": [str(p) for p in plots],
        "metrics": payload,
    }
