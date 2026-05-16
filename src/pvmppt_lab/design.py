from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yaml

from .pv import K_BOLTZMANN, PVModule, Q_ELECTRON, T_REF_K
from .reporting import ensure_dir, write_json


@dataclass(frozen=True)
class ModuleDesignSpec:
    name: str
    cells_in_series: int
    pmp_ref_w: float
    voc_ref_v: float
    isc_ref_a: float
    vmp_ref_v: float
    imp_ref_a: float
    alpha_isc_a_per_c: float = 0.0
    beta_voc_v_per_c: float = 0.0
    light_current_ref_a: float | None = None
    saturation_current_ref_a: float | None = None
    series_resistance_ohm: float = 0.25
    shunt_resistance_ohm: float = 300.0
    ideality_factor: float = 1.2
    band_gap_ev: float = 1.121
    array_series_modules: int = 1
    array_parallel_strings: int = 1
    irradiances_w_m2: tuple[float, ...] = (400.0, 650.0, 800.0, 1000.0)
    temperatures_c: tuple[float, ...] = (0.0, 25.0, 50.0, 75.0)
    points: int = 240

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["irradiances_w_m2"] = list(self.irradiances_w_m2)
        payload["temperatures_c"] = list(self.temperatures_c)
        return payload


def load_module_design_spec(path: Path) -> ModuleDesignSpec:
    path = Path(path)
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"module spec must be a mapping: {path}")
    module_payload = payload.get("module", payload)
    if not isinstance(module_payload, dict):
        raise ValueError("module spec must contain a mapping under 'module'")
    array_payload = payload.get("array", {}) if isinstance(payload.get("array", {}), dict) else {}
    sweep_payload = payload.get("sweeps", {}) if isinstance(payload.get("sweeps", {}), dict) else {}

    required = ["name", "cells_in_series", "pmp_ref_w", "voc_ref_v", "isc_ref_a", "vmp_ref_v", "imp_ref_a"]
    missing = [key for key in required if key not in module_payload]
    if missing:
        raise ValueError(f"missing required module spec fields: {', '.join(missing)}")

    return ModuleDesignSpec(
        name=str(module_payload["name"]),
        cells_in_series=int(module_payload["cells_in_series"]),
        pmp_ref_w=float(module_payload["pmp_ref_w"]),
        voc_ref_v=float(module_payload["voc_ref_v"]),
        isc_ref_a=float(module_payload["isc_ref_a"]),
        vmp_ref_v=float(module_payload["vmp_ref_v"]),
        imp_ref_a=float(module_payload["imp_ref_a"]),
        alpha_isc_a_per_c=float(module_payload.get("alpha_isc_a_per_c", 0.0)),
        beta_voc_v_per_c=float(module_payload.get("beta_voc_v_per_c", 0.0)),
        light_current_ref_a=_optional_float(module_payload.get("light_current_ref_a")),
        saturation_current_ref_a=_optional_float(module_payload.get("saturation_current_ref_a")),
        series_resistance_ohm=float(module_payload.get("series_resistance_ohm", 0.25)),
        shunt_resistance_ohm=float(module_payload.get("shunt_resistance_ohm", 300.0)),
        ideality_factor=float(module_payload.get("ideality_factor", 1.2)),
        band_gap_ev=float(module_payload.get("band_gap_ev", 1.121)),
        array_series_modules=int(array_payload.get("series_modules", 1)),
        array_parallel_strings=int(array_payload.get("parallel_strings", 1)),
        irradiances_w_m2=tuple(float(value) for value in sweep_payload.get("irradiances_w_m2", [400, 650, 800, 1000])),
        temperatures_c=tuple(float(value) for value in sweep_payload.get("temperatures_c", [0, 25, 50, 75])),
        points=int(sweep_payload.get("points", module_payload.get("points", 240))),
    )


def module_from_design_spec(spec: ModuleDesignSpec) -> PVModule:
    light_current = spec.light_current_ref_a
    if light_current is None:
        light_current = spec.isc_ref_a * (
            1.0 + spec.series_resistance_ohm / max(spec.shunt_resistance_ohm, 1e-9)
        )
    saturation_current = spec.saturation_current_ref_a
    if saturation_current is None:
        saturation_current = _estimate_saturation_current(
            cells_in_series=spec.cells_in_series,
            voc_ref_v=spec.voc_ref_v,
            light_current_ref_a=light_current,
            ideality_factor=spec.ideality_factor,
            shunt_resistance_ohm=spec.shunt_resistance_ohm,
        )
    return PVModule(
        name=spec.name,
        cells_in_series=spec.cells_in_series,
        pmp_ref_w=spec.pmp_ref_w,
        voc_ref_v=spec.voc_ref_v,
        isc_ref_a=spec.isc_ref_a,
        vmp_ref_v=spec.vmp_ref_v,
        imp_ref_a=spec.imp_ref_a,
        alpha_isc_a_per_c=spec.alpha_isc_a_per_c,
        beta_voc_v_per_c=spec.beta_voc_v_per_c,
        light_current_ref_a=float(light_current),
        saturation_current_ref_a=float(saturation_current),
        series_resistance_ohm=spec.series_resistance_ohm,
        shunt_resistance_ohm=spec.shunt_resistance_ohm,
        ideality_factor=spec.ideality_factor,
        band_gap_ev=spec.band_gap_ev,
    )


def design_module(spec_path: Path, output_dir: Path) -> dict[str, Any]:
    spec = load_module_design_spec(spec_path)
    module = module_from_design_spec(spec)
    output_dir = ensure_dir(Path(output_dir))

    curve_df, mpp_df = _module_sweep(module, spec.irradiances_w_m2, spec.temperatures_c, spec.points)
    sensitivity_df = _sensitivity_table(module)
    array_curve_df, array_mpp_df = _array_sweep(module, spec)

    curve_path = output_dir / "iv_pv_curves.csv"
    mpp_path = output_dir / "mpp_table.csv"
    sensitivity_path = output_dir / "sensitivity.csv"
    array_curve_path = output_dir / "array_iv_pv_curves.csv"
    array_mpp_path = output_dir / "array_mpp_table.csv"
    curve_df.to_csv(curve_path, index=False)
    mpp_df.to_csv(mpp_path, index=False)
    sensitivity_df.to_csv(sensitivity_path, index=False)
    array_curve_df.to_csv(array_curve_path, index=False)
    array_mpp_df.to_csv(array_mpp_path, index=False)

    plots = [
        _plot_design_family(curve_df, output_dir / "iv_curves.png", "current_a", "Current (A)", "Python PV module I-V design curves"),
        _plot_design_family(curve_df, output_dir / "pv_curves.png", "power_w", "Power (W)", "Python PV module P-V design curves"),
        _plot_sensitivity(sensitivity_df, output_dir / "sensitivity.png"),
        _plot_design_family(array_curve_df, output_dir / "array_pv_curves.png", "power_w", "Power (W)", "Python PV array P-V design curves"),
    ]
    stc_mpp = module.max_power_point(1000.0, 25.0)
    summary = {
        "workflow": "python-only module design",
        "spec_path": str(spec_path),
        "module": module.to_dict(),
        "array": {
            "series_modules": spec.array_series_modules,
            "parallel_strings": spec.array_parallel_strings,
        },
        "metrics": {
            "scenario_count": int(len(spec.irradiances_w_m2) * len(spec.temperatures_c)),
            "curve_rows": int(len(curve_df)),
            "array_curve_rows": int(len(array_curve_df)),
            "sensitivity_rows": int(len(sensitivity_df)),
            "stc_v_mpp": stc_mpp.voltage_v,
            "stc_i_mpp": stc_mpp.current_a,
            "stc_p_mpp": stc_mpp.power_w,
            "datasheet_pmp_error_pct": 100.0 * (stc_mpp.power_w - module.pmp_ref_w) / module.pmp_ref_w,
        },
        "artifacts": {
            "curves_csv": str(curve_path),
            "mpp_csv": str(mpp_path),
            "sensitivity_csv": str(sensitivity_path),
            "array_curves_csv": str(array_curve_path),
            "array_mpp_csv": str(array_mpp_path),
            "plots": [str(path) for path in plots],
        },
    }
    write_json(output_dir / "design_summary.json", summary)
    _write_design_report(output_dir, summary)
    return summary


def validate_module(spec_path: Path, output_dir: Path, backend: str = "internal") -> dict[str, Any]:
    if backend not in {"internal", "pvlib"}:
        raise ValueError("backend must be internal or pvlib")
    spec = load_module_design_spec(spec_path)
    module = module_from_design_spec(spec)
    output_dir = ensure_dir(Path(output_dir))
    internal = module.max_power_point(1000.0, 25.0)
    rows = [
        {
            "backend": "internal",
            "v_mpp": internal.voltage_v,
            "i_mpp": internal.current_a,
            "p_mpp": internal.power_w,
            "datasheet_pmp_error_pct": 100.0 * (internal.power_w - module.pmp_ref_w) / module.pmp_ref_w,
        }
    ]
    if backend == "pvlib":
        rows.append(_pvlib_mpp_row(module))
    df = pd.DataFrame(rows)
    csv_path = output_dir / "validation_mpp.csv"
    df.to_csv(csv_path, index=False)
    summary = {
        "workflow": "python-only module validation",
        "backend": backend,
        "spec_path": str(spec_path),
        "status": "pass",
        "validation_csv": str(csv_path),
        "rows": rows,
    }
    if backend == "pvlib" and len(rows) == 2:
        summary["backend_delta"] = {
            "p_mpp_pct": 100.0 * (rows[1]["p_mpp"] - rows[0]["p_mpp"]) / max(rows[0]["p_mpp"], 1e-9),
            "v_mpp_pct": 100.0 * (rows[1]["v_mpp"] - rows[0]["v_mpp"]) / max(rows[0]["v_mpp"], 1e-9),
        }
    write_json(output_dir / "validation_summary.json", summary)
    return summary


def fit_module(datasheet_path: Path, output_dir: Path, method: str = "desoto") -> dict[str, Any]:
    if method not in {"desoto", "cec", "pvsyst"}:
        raise ValueError("method must be desoto, cec, or pvsyst")
    spec = load_module_design_spec(datasheet_path)
    fitted = module_from_design_spec(_with_method_defaults(spec, method))
    output_dir = ensure_dir(Path(output_dir))
    fitted_payload = {
        "module": fitted.to_dict(),
        "fit": {
            "method": method,
            "engine": "internal datasheet-to-single-diode estimator",
            "reference_note": "Use validate-module --backend pvlib for an optional pvlib cross-check.",
        },
        "array": {
            "series_modules": spec.array_series_modules,
            "parallel_strings": spec.array_parallel_strings,
        },
        "sweeps": {
            "irradiances_w_m2": list(spec.irradiances_w_m2),
            "temperatures_c": list(spec.temperatures_c),
            "points": spec.points,
        },
    }
    fitted_path = output_dir / "fitted_module.yaml"
    fitted_path.write_text(yaml.safe_dump(fitted_payload, sort_keys=False), encoding="utf-8")
    mpp = fitted.max_power_point(1000.0, 25.0)
    mpp_df = pd.DataFrame(
        [
            {
                "backend": "internal",
                "method": method,
                "v_mpp": mpp.voltage_v,
                "i_mpp": mpp.current_a,
                "p_mpp": mpp.power_w,
                "datasheet_pmp_error_pct": 100.0 * (mpp.power_w - fitted.pmp_ref_w) / fitted.pmp_ref_w,
            }
        ]
    )
    mpp_path = output_dir / "fit_mpp_table.csv"
    mpp_df.to_csv(mpp_path, index=False)
    summary = {
        "workflow": "python-only module fit",
        "method": method,
        "datasheet_path": str(datasheet_path),
        "fitted_spec": str(fitted_path),
        "mpp_table": str(mpp_path),
        "module": fitted.to_dict(),
    }
    write_json(output_dir / "fit_summary.json", summary)
    return summary


def _module_sweep(
    module: PVModule,
    irradiances: tuple[float, ...],
    temperatures: tuple[float, ...],
    points: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    curve_rows: list[dict[str, float | str]] = []
    mpp_rows: list[dict[str, float | str]] = []
    for irradiance in irradiances:
        for temperature in temperatures:
            case = f"{irradiance:.0f}w_m2_{temperature:.0f}c"
            curve = module.curve(irradiance, temperature, points=points)
            for voltage, current, power in zip(curve["voltage_v"], curve["current_a"], curve["power_w"]):
                curve_rows.append(
                    {
                        "case": case,
                        "irradiance_w_m2": float(irradiance),
                        "temperature_c": float(temperature),
                        "voltage_v": float(voltage),
                        "current_a": float(current),
                        "power_w": float(power),
                    }
                )
            mpp = module.max_power_point(irradiance, temperature)
            mpp_rows.append(
                {
                    "case": case,
                    "irradiance_w_m2": float(irradiance),
                    "temperature_c": float(temperature),
                    "v_mpp": mpp.voltage_v,
                    "i_mpp": mpp.current_a,
                    "p_mpp": mpp.power_w,
                }
            )
    return pd.DataFrame(curve_rows), pd.DataFrame(mpp_rows)


def _array_sweep(module: PVModule, spec: ModuleDesignSpec) -> tuple[pd.DataFrame, pd.DataFrame]:
    base_curves, base_mpp = _module_sweep(module, spec.irradiances_w_m2, spec.temperatures_c, spec.points)
    series = max(1, spec.array_series_modules)
    parallel = max(1, spec.array_parallel_strings)
    array_curves = base_curves.copy()
    array_curves["voltage_v"] *= series
    array_curves["current_a"] *= parallel
    array_curves["power_w"] *= series * parallel
    array_curves["series_modules"] = series
    array_curves["parallel_strings"] = parallel
    array_mpp = base_mpp.copy()
    array_mpp["v_mpp"] *= series
    array_mpp["i_mpp"] *= parallel
    array_mpp["p_mpp"] *= series * parallel
    array_mpp["series_modules"] = series
    array_mpp["parallel_strings"] = parallel
    return array_curves, array_mpp


def _sensitivity_table(module: PVModule) -> pd.DataFrame:
    rows: list[dict[str, float | str]] = []
    baseline = module.max_power_point(1000.0, 25.0)
    sweeps = {
        "irradiance_w_m2": [250.0, 500.0, 750.0, 1000.0],
        "temperature_c": [0.0, 25.0, 50.0, 75.0],
        "series_resistance_ohm": [0.0, module.series_resistance_ohm, module.series_resistance_ohm * 2.0, module.series_resistance_ohm * 4.0],
        "shunt_resistance_ohm": [50.0, 200.0, module.shunt_resistance_ohm, 1000.0],
        "saturation_current_ref_a": [
            module.saturation_current_ref_a * 0.1,
            module.saturation_current_ref_a,
            module.saturation_current_ref_a * 10.0,
            module.saturation_current_ref_a * 100.0,
        ],
    }
    for parameter, values in sweeps.items():
        for value in values:
            varied = module
            irradiance = 1000.0
            temperature = 25.0
            if parameter == "irradiance_w_m2":
                irradiance = value
            elif parameter == "temperature_c":
                temperature = value
            else:
                varied = _replace_module_parameter(module, parameter, value)
            mpp = varied.max_power_point(irradiance, temperature)
            rows.append(
                {
                    "parameter": parameter,
                    "value": float(value),
                    "v_mpp": mpp.voltage_v,
                    "i_mpp": mpp.current_a,
                    "p_mpp": mpp.power_w,
                    "p_mpp_delta_pct": 100.0 * (mpp.power_w - baseline.power_w) / max(baseline.power_w, 1e-9),
                }
            )
    return pd.DataFrame(rows)


def _replace_module_parameter(module: PVModule, parameter: str, value: float) -> PVModule:
    payload = module.to_dict()
    payload[parameter] = value
    return PVModule(**payload)


def _plot_design_family(
    df: pd.DataFrame,
    output_path: Path,
    y_column: str,
    ylabel: str,
    title: str,
) -> Path:
    fig, ax = plt.subplots(figsize=(8, 4.8))
    for (irradiance, temperature), group in df.groupby(["irradiance_w_m2", "temperature_c"]):
        ax.plot(group["voltage_v"], group[y_column], label=f"{irradiance:.0f} W/m2, {temperature:.0f} C")
    ax.set_title(title)
    ax.set_xlabel("PV voltage (V)")
    ax.set_ylabel(ylabel)
    ax.grid(True, alpha=0.28)
    ax.legend(fontsize=7, ncol=2)
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
    return output_path


def _plot_sensitivity(df: pd.DataFrame, output_path: Path) -> Path:
    fig, ax = plt.subplots(figsize=(8, 4.8))
    for parameter, group in df.groupby("parameter"):
        x = np.arange(len(group))
        ax.plot(x, group["p_mpp_delta_pct"], marker="o", linewidth=1.8, label=parameter)
    ax.axhline(0, color="#111827", linewidth=0.8)
    ax.set_title("Python PV module parameter sensitivity")
    ax.set_xlabel("Sweep point index")
    ax.set_ylabel("MPP power delta (%)")
    ax.grid(True, alpha=0.28)
    ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
    return output_path


def _write_design_report(output_dir: Path, summary: dict[str, Any]) -> None:
    metrics = summary["metrics"]
    lines = [
        "# PV Module Python Design Report",
        "",
        "This report was generated from a datasheet-style module spec with Python numerical models.",
        "",
        "## Summary",
        "",
        f"- Module: `{summary['module']['name']}`",
        f"- STC MPP: `{metrics['stc_p_mpp']:.3f} W` at `{metrics['stc_v_mpp']:.3f} V`, `{metrics['stc_i_mpp']:.3f} A`",
        f"- Datasheet Pmp error: `{metrics['datasheet_pmp_error_pct']:.3f}%`",
        f"- Scenarios: `{metrics['scenario_count']}`",
        f"- Curve rows: `{metrics['curve_rows']}`",
        f"- Sensitivity rows: `{metrics['sensitivity_rows']}`",
        "",
        "## Artifacts",
        "",
    ]
    for key, value in summary["artifacts"].items():
        lines.append(f"- `{key}`: `{value}`")
    (output_dir / "design_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _pvlib_mpp_row(module: PVModule) -> dict[str, float | str]:
    try:
        from pvlib import pvsystem
    except ImportError as exc:
        raise RuntimeError("pvlib backend requires installing pvmppt-lab with the 'standard' extra.") from exc
    result = pvsystem.singlediode(
        photocurrent=module.photocurrent(1000.0, 25.0),
        saturation_current=module.saturation_current(25.0),
        resistance_series=module.series_resistance_ohm,
        resistance_shunt=module.shunt_resistance_ohm,
        nNsVth=module.thermal_voltage(25.0),
        method="lambertw",
    )
    return {
        "backend": "pvlib",
        "v_mpp": float(result["v_mp"]),
        "i_mpp": float(result["i_mp"]),
        "p_mpp": float(result["p_mp"]),
        "datasheet_pmp_error_pct": 100.0 * (float(result["p_mp"]) - module.pmp_ref_w) / module.pmp_ref_w,
    }


def _with_method_defaults(spec: ModuleDesignSpec, method: str) -> ModuleDesignSpec:
    if spec.saturation_current_ref_a is not None and spec.light_current_ref_a is not None:
        return spec
    method_defaults = {
        "desoto": {"ideality_factor": spec.ideality_factor or 1.2},
        "cec": {"ideality_factor": spec.ideality_factor or 1.15},
        "pvsyst": {"ideality_factor": spec.ideality_factor or 1.3},
    }
    payload = spec.to_dict()
    payload.update(method_defaults[method])
    payload["irradiances_w_m2"] = tuple(payload["irradiances_w_m2"])
    payload["temperatures_c"] = tuple(payload["temperatures_c"])
    return ModuleDesignSpec(**payload)


def _estimate_saturation_current(
    cells_in_series: int,
    voc_ref_v: float,
    light_current_ref_a: float,
    ideality_factor: float,
    shunt_resistance_ohm: float,
) -> float:
    thermal_voltage = ideality_factor * cells_in_series * K_BOLTZMANN * T_REF_K / Q_ELECTRON
    numerator = max(light_current_ref_a - voc_ref_v / max(shunt_resistance_ohm, 1e-9), 1e-12)
    denominator = max(np.expm1(voc_ref_v / max(thermal_voltage, 1e-12)), 1e-30)
    return float(numerator / denominator)


def _optional_float(value: object) -> float | None:
    return None if value is None else float(value)
