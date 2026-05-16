from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Callable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.optimize import brentq

from .converter import ideal_inverting_buck_boost_output
from .mppt import POController, simulate_po_mppt
from .pv import K_BOLTZMANN, PVModule, Q_ELECTRON
from .reporting import ensure_dir, plot_mppt, write_json
from .scenarios import run_mppt_demo


SUITES = {"all", "pv-cell", "pv-module", "pv-array", "mppt", "converter"}


@dataclass(frozen=True)
class SingleDiodeSpec:
    name: str
    cells_in_series: int
    photocurrent_ref_a: float
    saturation_current_ref_a: float
    ideality_factor: float = 1.5
    series_resistance_ohm: float = 0.0017
    shunt_resistance_ohm: float = 1000.0
    temperature_ref_c: float = 25.0
    irradiance_ref_w_m2: float = 1000.0
    band_gap_ev: float = 1.12
    alpha_isc_a_per_c: float = 0.0

    def to_dict(self) -> dict[str, float | int | str]:
        return asdict(self)


def spec_from_voc(
    name: str,
    cells_in_series: int,
    isc_ref_a: float,
    voc_ref_v: float,
    ideality_factor: float,
    series_resistance_ohm: float,
    shunt_resistance_ohm: float,
) -> SingleDiodeSpec:
    thermal = (
        ideality_factor
        * cells_in_series
        * K_BOLTZMANN
        * (25.0 + 273.15)
        / Q_ELECTRON
    )
    saturation = isc_ref_a / max(np.expm1(voc_ref_v / thermal), 1e-30)
    return SingleDiodeSpec(
        name=name,
        cells_in_series=cells_in_series,
        photocurrent_ref_a=isc_ref_a,
        saturation_current_ref_a=float(saturation),
        ideality_factor=ideality_factor,
        series_resistance_ohm=series_resistance_ohm,
        shunt_resistance_ohm=shunt_resistance_ohm,
    )


MOTAHHIR_CELL = SingleDiodeSpec(
    name="Motahhir-style PV cell",
    cells_in_series=1,
    photocurrent_ref_a=3.8,
    saturation_current_ref_a=1e-9,
    ideality_factor=1.5,
    series_resistance_ohm=0.0017,
    shunt_resistance_ohm=1000.0,
)

MOTAHHIR_MODULE = SingleDiodeSpec(
    name="Motahhir-style 36-cell PV module",
    cells_in_series=36,
    photocurrent_ref_a=3.8,
    saturation_current_ref_a=2.16e-8,
    ideality_factor=1.5,
    series_resistance_ohm=0.0017,
    shunt_resistance_ohm=1000.0,
)

PHYSICAL_PARAMETER_MODULE = spec_from_voc(
    name="Single-diode 36-cell PV module",
    cells_in_series=36,
    isc_ref_a=8.9,
    voc_ref_v=22.75,
    ideality_factor=1.2,
    series_resistance_ohm=0.05,
    shunt_resistance_ohm=1000.0,
)

RUPESH_PANEL = spec_from_voc(
    name="Rupesh-style PV panel",
    cells_in_series=36,
    isc_ref_a=1.0,
    voc_ref_v=19.44,
    ideality_factor=1.2,
    series_resistance_ohm=0.1,
    shunt_resistance_ohm=1000.0,
)


def run_reproduction_suite(
    output_dir: Path,
    suite: str = "all",
    points: int = 240,
) -> dict[str, object]:
    if suite not in SUITES:
        raise ValueError(f"unknown suite: {suite}")
    output_dir = ensure_dir(Path(output_dir))
    suite_names = ["pv-cell", "pv-module", "pv-array", "mppt", "converter"] if suite == "all" else [suite]
    results: dict[str, object] = {}
    for name in suite_names:
        suite_dir = output_dir / name
        if name == "pv-cell":
            results[name] = run_pv_cell_reproduction(suite_dir, points=points)
        elif name == "pv-module":
            results[name] = run_pv_module_reproduction(suite_dir, points=points)
        elif name == "pv-array":
            results[name] = run_pv_array_reproduction(suite_dir, points=points)
        elif name == "mppt":
            results[name] = run_mppt_reproduction(suite_dir)
        elif name == "converter":
            results[name] = run_converter_reproduction(suite_dir)

    summary = {
        "suite": suite,
        "completed_suites": suite_names,
        "output_dir": str(output_dir),
        "metrics": {
            name: value.get("metrics", {})
            for name, value in results.items()
            if isinstance(value, dict)
        },
    }
    write_json(output_dir / "summary.json", summary)
    return {"summary": summary, "results": results}


def run_pv_cell_reproduction(output_dir: Path, points: int = 240) -> dict[str, object]:
    output_dir = ensure_dir(output_dir)
    base_cases = [
        ("cell_400w", MOTAHHIR_CELL, 400.0, 27.0),
        ("cell_700w", MOTAHHIR_CELL, 700.0, 27.0),
        ("cell_1000w", MOTAHHIR_CELL, 1000.0, 27.0),
    ]
    curve_df, mpp_df = _curves_for_cases(base_cases, points=points)
    curve_path = output_dir / "pv_cell_curves.csv"
    mpp_path = output_dir / "pv_cell_mpp.csv"
    curve_df.to_csv(curve_path, index=False)
    mpp_df.to_csv(mpp_path, index=False)
    _plot_curve_family(curve_df, output_dir / "pv_cell_iv_curves.png", "current_a", "Current (A)", "PV cell I-V reproduction")
    _plot_curve_family(curve_df, output_dir / "pv_cell_pv_curves.png", "power_w", "Power (W)", "PV cell P-V reproduction")

    sweep_rows: list[dict[str, float | str]] = []
    for parameter, values in {
        "irradiance_w_m2": [250.0, 500.0, 750.0, 1000.0],
        "temperature_c": [0.0, 25.0, 50.0, 75.0],
        "series_resistance_ohm": [0.0, 0.0017, 0.02, 0.05],
        "shunt_resistance_ohm": [50.0, 200.0, 1000.0, 5000.0],
        "saturation_current_ref_a": [1e-10, 1e-9, 1e-8, 1e-7],
    }.items():
        for value in values:
            spec = MOTAHHIR_CELL
            irradiance = 1000.0
            temperature = 27.0
            if parameter == "irradiance_w_m2":
                irradiance = value
            elif parameter == "temperature_c":
                temperature = value
            else:
                spec = replace(spec, **{parameter: value})
            mpp = max_power_point(spec, irradiance, temperature)
            sweep_rows.append(
                {
                    "parameter": parameter,
                    "value": value,
                    "v_mpp": mpp["v_mpp"],
                    "i_mpp": mpp["i_mpp"],
                    "p_mpp": mpp["p_mpp"],
                }
            )
    sweep_df = pd.DataFrame(sweep_rows)
    sweep_df.to_csv(output_dir / "parameter_sweeps.csv", index=False)
    _plot_parameter_sweeps(sweep_df, output_dir / "parameter_sweeps.png")
    metrics = {
        "source_models_reproduced": [
            "pv_cell_model",
            "pv_cell_effects_of_solar_radiation",
            "pv_cell_effects_of_temp",
            "pv_cell_effect_of_varying_Rs",
            "pv_cell_effect_of_varying_Rsh",
            "pv_cell_effects_of_varying_Is",
            "FindMPP",
        ],
        "curve_rows": int(len(curve_df)),
        "sweep_rows": int(len(sweep_df)),
        "base_1000w_p_mpp": float(mpp_df.loc[mpp_df["case"] == "cell_1000w", "p_mpp"].iloc[0]),
    }
    write_json(output_dir / "metrics.json", metrics)
    return {"output_dir": str(output_dir), "metrics": metrics}


def run_pv_module_reproduction(output_dir: Path, points: int = 240) -> dict[str, object]:
    output_dir = ensure_dir(output_dir)
    cases = [
        ("motahhir_module", MOTAHHIR_MODULE, 1000.0, 25.0),
        ("single_diode_36_cell_module", PHYSICAL_PARAMETER_MODULE, 1000.0, 25.0),
    ]
    curve_df, mpp_df = _curves_for_cases(cases, points=points)
    curve_df.to_csv(output_dir / "pv_module_curves.csv", index=False)
    mpp_df.to_csv(output_dir / "pv_module_mpp.csv", index=False)
    _plot_curve_family(curve_df, output_dir / "pv_module_iv_curves.png", "current_a", "Current (A)", "PV module I-V reproduction")
    _plot_curve_family(curve_df, output_dir / "pv_module_pv_curves.png", "power_w", "Power (W)", "PV module P-V reproduction")
    metrics = {
        "source_models_reproduced": ["pv_module", "PV_module"],
        "curve_rows": int(len(curve_df)),
        "mpp": mpp_df.to_dict(orient="records"),
    }
    write_json(output_dir / "metrics.json", metrics)
    return {"output_dir": str(output_dir), "metrics": metrics}


def run_pv_array_reproduction(output_dir: Path, points: int = 240) -> dict[str, object]:
    output_dir = ensure_dir(output_dir)
    curve_rows: list[dict[str, float | str]] = []
    mpp_rows: list[dict[str, float | str]] = []

    for case, spec, series_units, parallel_units in [
        ("motahhir_array_6s6p", MOTAHHIR_MODULE, 6, 6),
        ("rupesh_panel_1s1p", RUPESH_PANEL, 1, 1),
        ("rupesh_array_2s2p", RUPESH_PANEL, 2, 2),
    ]:
        curve = scaled_curve(spec, 1000.0, 25.0, series_units, parallel_units, points)
        for row in curve.to_dict(orient="records"):
            curve_rows.append({"case": case, **row})
        mpp = _mpp_from_curve(curve)
        mpp_rows.append({"case": case, "series_units": series_units, "parallel_units": parallel_units, **mpp})

    trina_curve = _trina_array_curve(series_units=10, parallel_units=4, points=points)
    for row in trina_curve.to_dict(orient="records"):
        curve_rows.append({"case": "trina_array_10s4p", **row})
    mpp_rows.append({"case": "trina_array_10s4p", "series_units": 10, "parallel_units": 4, **_mpp_from_curve(trina_curve)})

    curve_df = pd.DataFrame(curve_rows)
    mpp_df = pd.DataFrame(mpp_rows)
    curve_df.to_csv(output_dir / "pv_array_curves.csv", index=False)
    mpp_df.to_csv(output_dir / "pv_array_mpp.csv", index=False)
    _plot_curve_family(curve_df, output_dir / "pv_array_iv_curves.png", "current_a", "Current (A)", "PV array I-V reproduction")
    _plot_curve_family(curve_df, output_dir / "pv_array_pv_curves.png", "power_w", "Power (W)", "PV array P-V reproduction")
    metrics = {
        "source_models_reproduced": ["pv_array", "PV_Array_Author_rupesh", "P_and_O PV Array"],
        "curve_rows": int(len(curve_df)),
        "mpp": mpp_df.to_dict(orient="records"),
    }
    write_json(output_dir / "metrics.json", metrics)
    return {"output_dir": str(output_dir), "metrics": metrics}


def run_mppt_reproduction(output_dir: Path) -> dict[str, object]:
    output_dir = ensure_dir(output_dir)
    dynamic = run_mppt_demo(output_dir / "mppt_dynamic", total_time_s=0.25, temperature_c=25.0)
    fixed_profile: Callable[[float], float] = lambda _t: 500.0
    fixed_df, fixed_metrics = simulate_po_mppt(
        module=PVModule(),
        controller=POController(),
        total_time_s=0.1,
        temperature_c=25.0,
        irradiance_profile=fixed_profile,
    )
    fixed_dir = ensure_dir(output_dir / "mppt_fixed_500w_25c")
    fixed_trace = fixed_dir / "mppt_trace.csv"
    fixed_df.to_csv(fixed_trace, index=False)
    fixed_plots = plot_mppt(fixed_df, fixed_dir)
    fixed_payload = {
        **fixed_metrics,
        "irradiance_w_m2": 500.0,
        "temperature_c": 25.0,
        "rows": int(len(fixed_df)),
    }
    write_json(fixed_dir / "metrics.json", fixed_payload)
    metrics = {
        "source_models_reproduced": ["PV_MPPT", "P_and_O_MPPT"],
        "dynamic_tracking_efficiency": dynamic["metrics"]["tracking_efficiency"],
        "fixed_tracking_efficiency": fixed_payload["tracking_efficiency"],
        "fixed_trace_csv": str(fixed_trace),
        "fixed_plots": [str(path) for path in fixed_plots],
    }
    write_json(output_dir / "metrics.json", metrics)
    return {"output_dir": str(output_dir), "metrics": metrics}


def run_converter_reproduction(output_dir: Path) -> dict[str, object]:
    output_dir = ensure_dir(output_dir)
    vin = 48.0
    load = 100.0
    duty_values = [0.05, 0.1, 0.25, 0.5, 0.75, 0.8, 0.95]
    rows = []
    for duty in duty_values:
        vout = ideal_inverting_buck_boost_output(vin, duty)
        rows.append(
            {
                "duty": duty,
                "input_voltage_v": vin,
                "ideal_inverting_output_voltage_v": vout,
                "load_resistance_ohm": load,
                "ideal_output_current_a": vout / load,
                "ideal_output_power_w": (vout * vout) / load,
            }
        )
    df = pd.DataFrame(rows)
    df.to_csv(output_dir / "converter_reference.csv", index=False)
    _plot_converter(df, output_dir / "converter_reference.png")
    metrics = {
        "source_models_reproduced": ["Open_loop_Buck-Boost_Converter"],
        "dc_source_v": vin,
        "pulse_period_s": 0.0001,
        "main_pulse_width_pct": 5.0,
        "complementary_pulse_width_pct": 95.0,
        "inductor_h": 0.01e-3,
        "capacitor_f": 2200e-6,
        "load_resistance_ohm": load,
        "reference_rows": int(len(df)),
    }
    write_json(output_dir / "metrics.json", metrics)
    return {"output_dir": str(output_dir), "metrics": metrics}


def curve_for_spec(
    spec: SingleDiodeSpec,
    irradiance_w_m2: float,
    temperature_c: float,
    points: int = 240,
) -> pd.DataFrame:
    voc = estimate_voc(spec, irradiance_w_m2, temperature_c)
    voltages = np.linspace(0.0, max(voc * 1.02, 0.1), points)
    rows = []
    for voltage in voltages:
        current = current_at_voltage(spec, float(voltage), irradiance_w_m2, temperature_c)
        rows.append(
            {
                "voltage_v": float(voltage),
                "current_a": current,
                "power_w": float(voltage) * current,
                "irradiance_w_m2": irradiance_w_m2,
                "temperature_c": temperature_c,
            }
        )
    return pd.DataFrame(rows)


def scaled_curve(
    spec: SingleDiodeSpec,
    irradiance_w_m2: float,
    temperature_c: float,
    series_units: int,
    parallel_units: int,
    points: int = 240,
) -> pd.DataFrame:
    df = curve_for_spec(spec, irradiance_w_m2, temperature_c, points=points).copy()
    df["voltage_v"] *= float(series_units)
    df["current_a"] *= float(parallel_units)
    df["power_w"] = df["voltage_v"] * df["current_a"]
    return df


def max_power_point(spec: SingleDiodeSpec, irradiance_w_m2: float, temperature_c: float) -> dict[str, float]:
    return _mpp_from_curve(curve_for_spec(spec, irradiance_w_m2, temperature_c, points=720))


def current_at_voltage(
    spec: SingleDiodeSpec,
    voltage_v: float,
    irradiance_w_m2: float,
    temperature_c: float,
) -> float:
    if irradiance_w_m2 <= 0 or voltage_v < 0:
        return 0.0
    iph = photocurrent(spec, irradiance_w_m2, temperature_c)
    i0 = saturation_current(spec, temperature_c)
    thermal = thermal_voltage(spec, temperature_c)
    rs = spec.series_resistance_ohm
    rsh = max(spec.shunt_resistance_ohm, 1e-9)

    def residual(current_a: float) -> float:
        arg = np.clip((voltage_v + current_a * rs) / thermal, -100.0, 100.0)
        return iph - i0 * np.expm1(float(arg)) - (voltage_v + current_a * rs) / rsh - current_a

    if residual(0.0) <= 0.0:
        return 0.0
    upper = max(iph * 1.5 + 0.5, 1.0)
    for _ in range(8):
        if residual(upper) < 0.0:
            break
        upper *= 2.0
    return max(0.0, float(brentq(residual, 0.0, upper, xtol=1e-9, maxiter=100)))


def photocurrent(spec: SingleDiodeSpec, irradiance_w_m2: float, temperature_c: float) -> float:
    return (
        spec.photocurrent_ref_a
        + spec.alpha_isc_a_per_c * (temperature_c - spec.temperature_ref_c)
    ) * (irradiance_w_m2 / spec.irradiance_ref_w_m2)


def saturation_current(spec: SingleDiodeSpec, temperature_c: float) -> float:
    temperature_k = temperature_c + 273.15
    reference_k = spec.temperature_ref_c + 273.15
    exponent = (spec.band_gap_ev * Q_ELECTRON) / (spec.ideality_factor * K_BOLTZMANN) * (
        1.0 / reference_k - 1.0 / temperature_k
    )
    exponent = float(np.clip(exponent, -80.0, 80.0))
    return spec.saturation_current_ref_a * (temperature_k / reference_k) ** 3 * float(np.exp(exponent))


def thermal_voltage(spec: SingleDiodeSpec, temperature_c: float) -> float:
    return (
        spec.ideality_factor
        * spec.cells_in_series
        * K_BOLTZMANN
        * (temperature_c + 273.15)
        / Q_ELECTRON
    )


def estimate_voc(spec: SingleDiodeSpec, irradiance_w_m2: float, temperature_c: float) -> float:
    iph = max(photocurrent(spec, irradiance_w_m2, temperature_c), 1e-12)
    i0 = max(saturation_current(spec, temperature_c), 1e-30)
    return max(0.0, thermal_voltage(spec, temperature_c) * float(np.log1p(iph / i0)))


def _curves_for_cases(
    cases: list[tuple[str, SingleDiodeSpec, float, float]], points: int
) -> tuple[pd.DataFrame, pd.DataFrame]:
    curve_rows: list[dict[str, float | str]] = []
    mpp_rows: list[dict[str, float | str]] = []
    for case, spec, irradiance, temperature in cases:
        df = curve_for_spec(spec, irradiance, temperature, points=points)
        for row in df.to_dict(orient="records"):
            curve_rows.append({"case": case, **row})
        mpp_rows.append({"case": case, **_mpp_from_curve(df), "spec": spec.name})
    return pd.DataFrame(curve_rows), pd.DataFrame(mpp_rows)


def _mpp_from_curve(df: pd.DataFrame) -> dict[str, float]:
    index = int(df["power_w"].idxmax())
    row = df.loc[index]
    return {
        "v_mpp": float(row["voltage_v"]),
        "i_mpp": float(row["current_a"]),
        "p_mpp": float(row["power_w"]),
    }


def _trina_array_curve(series_units: int, parallel_units: int, points: int) -> pd.DataFrame:
    module = PVModule()
    curve = module.curve(1000.0, 25.0, points=points)
    df = pd.DataFrame(
        {
            "voltage_v": curve["voltage_v"] * float(series_units),
            "current_a": curve["current_a"] * float(parallel_units),
            "irradiance_w_m2": 1000.0,
            "temperature_c": 25.0,
        }
    )
    df["power_w"] = df["voltage_v"] * df["current_a"]
    return df


def _plot_curve_family(
    df: pd.DataFrame,
    output_path: Path,
    y_column: str,
    y_label: str,
    title: str,
) -> None:
    fig, ax = plt.subplots(figsize=(8, 4.5))
    for case, group in df.groupby("case"):
        ax.plot(group["voltage_v"], group[y_column], label=str(case))
    ax.set_title(title)
    ax.set_xlabel("Voltage (V)")
    ax.set_ylabel(y_label)
    ax.grid(True, alpha=0.28)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def _plot_parameter_sweeps(df: pd.DataFrame, output_path: Path) -> None:
    fig, axes = plt.subplots(2, 3, figsize=(11, 6.5))
    axes_flat = axes.flatten()
    for ax, (parameter, group) in zip(axes_flat, df.groupby("parameter")):
        ax.plot(group["value"], group["p_mpp"], marker="o")
        ax.set_title(parameter)
        ax.set_xlabel("Value")
        ax.set_ylabel("Pmp (W)")
        ax.grid(True, alpha=0.28)
    for ax in axes_flat[len(df["parameter"].unique()) :]:
        ax.axis("off")
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def _plot_converter(df: pd.DataFrame, output_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.plot(df["duty"], df["ideal_inverting_output_voltage_v"], marker="o")
    ax.set_title("Ideal inverting buck-boost output reference")
    ax.set_xlabel("Duty cycle")
    ax.set_ylabel("Output voltage (V)")
    ax.grid(True, alpha=0.28)
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
