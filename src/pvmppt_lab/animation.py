from __future__ import annotations

from dataclasses import asdict, dataclass
import importlib.metadata
from pathlib import Path
import shutil
import subprocess
import sys

import mpl_animator

from .reporting import ensure_dir, write_json


ANIMATION_PRESETS = {"all", "pv-sweep", "mppt-tracking", "converter-duty", "pv-surface"}
BACKEND_NAME = "mpl-animator"


@dataclass(frozen=True)
class AnimationResult:
    backend: str
    backend_version: str
    preset: str
    command: list[str]
    render_command: list[str]
    variables: list[str]
    ranges: list[str] | None
    values: list[str] | None
    frames: int
    fps: int
    dpi: int
    format: str
    output_files: list[str]
    source_artifact_paths: list[str]
    generated_script: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def render_animation_presets(
    run_dir: Path,
    output_dir: Path,
    preset: str = "all",
    fmt: str = "gif",
    frames: int = 60,
    fps: int = 20,
    workers: int = 0,
    dpi: int = 110,
) -> dict[str, object]:
    if preset not in ANIMATION_PRESETS:
        raise ValueError(f"unknown animation preset: {preset}")
    _validate_animation_options(fmt, frames, fps, dpi)
    run_dir = Path(run_dir)
    output_dir = ensure_dir(Path(output_dir))
    work_dir = ensure_dir(run_dir / "animation-work")
    names = (
        ["pv-sweep", "mppt-tracking", "converter-duty", "pv-surface"]
        if preset == "all"
        else [preset]
    )
    results = [
        _render_preset(name, run_dir, output_dir, work_dir, fmt, frames, fps, workers, dpi)
        for name in names
    ]
    payload = {
        "backend": BACKEND_NAME,
        "backend_version": _backend_version(),
        "preset": preset,
        "run_dir": str(run_dir),
        "output_dir": str(output_dir),
        "results": [result.to_dict() for result in results],
        "output_files": [path for result in results for path in result.output_files],
    }
    write_json(output_dir / "animation_manifest.json", payload)
    return payload


def render_readme_hero(
    run_dir: Path,
    output_dir: Path,
    frames: int = 24,
    fps: int = 12,
    workers: int = 1,
    dpi: int = 110,
) -> AnimationResult:
    run_dir = Path(run_dir)
    output_dir = ensure_dir(Path(output_dir))
    work_dir = ensure_dir(run_dir / "animation-work")
    static_curves = run_dir / "static" / "static_curves.csv"
    static_mpp = run_dir / "static" / "static_mpp.csv"
    mppt_trace = run_dir / "mppt" / "mppt_trace.csv"
    mppt_metrics = run_dir / "mppt" / "metrics.json"
    _require_paths([static_curves, static_mpp, mppt_trace, mppt_metrics])
    script = work_dir / "readme_hero.py"
    script.write_text(
        _script_readme_hero(static_curves, static_mpp, mppt_trace, mppt_metrics, frames),
        encoding="utf-8",
    )
    return render_script_animation(
        script,
        variables=["frame"],
        values=[",".join(str(i) for i in range(frames))],
        frames=frames,
        fps=fps,
        workers=workers,
        dpi=dpi,
        fmt="gif",
        output_path=output_dir / "pvmppt-lab-hero.gif",
        work_dir=work_dir,
        preset="readme-hero",
        source_artifact_paths=[static_curves, static_mpp, mppt_trace, mppt_metrics],
    )


def render_script_animation(
    script_path: Path,
    variables: list[str],
    ranges: list[str] | None = None,
    values: list[str] | None = None,
    frames: int = 60,
    fps: int = 20,
    workers: int = 0,
    dpi: int = 110,
    fmt: str = "gif",
    output_path: Path | None = None,
    work_dir: Path | None = None,
    preset: str = "script",
    source_artifact_paths: list[Path] | None = None,
) -> AnimationResult:
    script_path = Path(script_path)
    if not script_path.exists():
        raise FileNotFoundError(f"animation script not found: {script_path}")
    if not variables:
        raise ValueError("at least one animation variable is required")
    if values is not None and ranges is not None:
        raise ValueError("use either values or range, not both")
    if values is None:
        ranges = ranges or ["0,1"]
    _validate_animation_options(fmt, frames, fps, dpi)
    if fmt == "mp4" and shutil.which("ffmpeg") is None:
        raise RuntimeError("MP4 output requires ffmpeg on PATH; use --format gif or install ffmpeg.")

    output_path = Path(output_path) if output_path else script_path.with_suffix(f".{fmt}")
    output_path = output_path.resolve()
    ensure_dir(output_path.parent)
    work_dir = ensure_dir(Path(work_dir) if work_dir else output_path.parent / "_animation_work").resolve()
    generated_script = work_dir / f"{script_path.stem}_animated.py"
    source = script_path.read_text(encoding="utf-8")
    generated = mpl_animator.animate(
        source,
        var=variables[0] if len(variables) == 1 else variables,
        range_str=_single_or_list(ranges),
        values=_single_or_list(values),
        frames=frames,
        fps=fps,
        workers=workers,
        dpi=dpi,
        out=str(output_path),
        fmt=fmt,
        loop=0,
        source_name=str(script_path),
    )
    generated_script.write_text(generated, encoding="utf-8")
    render_command = [sys.executable, str(generated_script)]
    if workers == 1:
        render_command.append("--sequential")
    try:
        subprocess.run(
            render_command,
            cwd=generated_script.parent,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        details = "\n".join(part for part in [exc.stdout, exc.stderr] if part)
        raise RuntimeError(f"animation render failed for {script_path}: {details}") from exc
    if not output_path.exists() or output_path.stat().st_size <= 0:
        raise RuntimeError(f"animation output was not created: {output_path}")
    command = _equivalent_mpl_animator_command(
        script_path, variables, ranges, values, frames, fps, workers, dpi, fmt, output_path
    )
    return AnimationResult(
        backend=BACKEND_NAME,
        backend_version=_backend_version(),
        preset=preset,
        command=command,
        render_command=["python", _display_path(generated_script), *render_command[2:]],
        variables=variables,
        ranges=ranges,
        values=values,
        frames=frames if values is None else _values_frame_count(values),
        fps=fps,
        dpi=dpi,
        format=fmt,
        output_files=[_display_path(output_path)],
        source_artifact_paths=[_display_path(path) for path in (source_artifact_paths or [script_path])],
        generated_script=_display_path(generated_script),
    )


def _render_preset(
    preset: str,
    run_dir: Path,
    output_dir: Path,
    work_dir: Path,
    fmt: str,
    frames: int,
    fps: int,
    workers: int,
    dpi: int,
) -> AnimationResult:
    script = work_dir / f"{preset}.py"
    output_path = output_dir / f"pvmppt-lab-{preset}.{fmt}"
    values = [",".join(str(i) for i in range(frames))]
    source_paths: list[Path]
    if preset == "pv-sweep":
        static_curves = run_dir / "static" / "static_curves.csv"
        static_mpp = run_dir / "static" / "static_mpp.csv"
        _require_paths([static_curves, static_mpp])
        script.write_text(_script_pv_sweep(static_curves, static_mpp, frames), encoding="utf-8")
        source_paths = [static_curves, static_mpp]
    elif preset == "mppt-tracking":
        trace = run_dir / "mppt" / "mppt_trace.csv"
        _require_paths([trace])
        script.write_text(_script_mppt_tracking(trace, frames), encoding="utf-8")
        source_paths = [trace]
    elif preset == "converter-duty":
        script.write_text(_script_converter_duty(frames), encoding="utf-8")
        source_paths = []
    elif preset == "pv-surface":
        static_curves = run_dir / "static" / "static_curves.csv"
        _require_paths([static_curves])
        script.write_text(_script_pv_surface(static_curves, frames), encoding="utf-8")
        source_paths = [static_curves]
    else:
        raise ValueError(f"unknown animation preset: {preset}")
    return render_script_animation(
        script,
        variables=["frame"],
        values=values,
        frames=frames,
        fps=fps,
        workers=workers,
        dpi=dpi,
        fmt=fmt,
        output_path=output_path,
        work_dir=work_dir,
        preset=preset,
        source_artifact_paths=source_paths,
    )


def _script_pv_sweep(static_curves: Path, static_mpp: Path, frames: int) -> str:
    return f'''
import pandas as pd
import matplotlib.pyplot as plt

frame = 0
FRAME_COUNT = {frames}
curves = pd.read_csv({str(static_curves.resolve())!r})
mpp = pd.read_csv({str(static_mpp.resolve())!r})
irradiances = sorted(curves["irradiance_w_m2"].unique())
temperatures = sorted(curves["temperature_c"].unique())
fig, (ax_power, ax_meta) = plt.subplots(1, 2, figsize=(9.6, 5.4), gridspec_kw={{"width_ratios": [2.2, 1.0]}})
idx = max(0, min(int(frame), FRAME_COUNT - 1))
temp = temperatures[idx % len(temperatures)]
visible_count = 1 + int(idx * len(irradiances) / FRAME_COUNT)
visible = irradiances[:max(1, min(len(irradiances), visible_count))]
colors = ["#60a5fa", "#16a34a", "#f97316", "#dc2626", "#7c3aed", "#0891b2"]
for color_index, irradiance in enumerate(visible):
    group = curves[(curves["temperature_c"] == temp) & (curves["irradiance_w_m2"] == irradiance)]
    ax_power.plot(group["voltage_v"], group["power_w"], color=colors[color_index % len(colors)], linewidth=2.4, label=f"{{irradiance:.0f}} W/m2")
marks = mpp[(mpp["temperature_c"] == temp) & (mpp["irradiance_w_m2"].isin(visible))]
ax_power.scatter(marks["v_mpp"], marks["p_mpp"], color="#111827", edgecolor="white", linewidth=0.8, s=48, zorder=4, label="MPP")
ax_power.set_title(f"Python PV sweep at {{temp:.0f}} C")
ax_power.set_xlabel("PV voltage (V)")
ax_power.set_ylabel("Power (W)")
ax_power.set_xlim(0, 42)
ax_power.set_ylim(0, curves["power_w"].max() * 1.08)
ax_power.grid(True, color="#dbe3ef", linewidth=0.8)
ax_power.legend(loc="upper left", fontsize=8)
ax_meta.axis("off")
if frame >= 0:
    ax_meta.set_axis_off()
ax_meta.text(0.05, 0.86, "Python-only design", fontsize=15, weight="bold", color="#111827")
ax_meta.text(0.05, 0.73, f"Frame {{idx + 1}} / {{FRAME_COUNT}}", fontsize=11, color="#475569")
ax_meta.text(0.05, 0.61, f"Temperature: {{temp:.0f}} C", fontsize=11, color="#475569")
ax_meta.text(0.05, 0.49, f"Irradiance curves: {{len(visible)}}", fontsize=11, color="#475569")
ax_meta.text(0.05, 0.31, "Outputs: CSV, JSON, plots, report, GIF/MP4", fontsize=10, color="#64748b", wrap=True)
fig.tight_layout()
'''


def _script_mppt_tracking(trace_path: Path, frames: int) -> str:
    return f'''
import pandas as pd
import matplotlib.pyplot as plt

frame = 0
FRAME_COUNT = {frames}
trace = pd.read_csv({str(trace_path.resolve())!r})
fig, ax = plt.subplots(figsize=(9.6, 5.4))
idx = max(0, min(int(frame), FRAME_COUNT - 1))
row_count = max(2, int((idx + 1) * len(trace) / FRAME_COUNT))
visible = trace.iloc[:row_count]
ax.fill_between(trace["time_s"], trace["p_mpp"], color="#dbeafe", alpha=0.65, label="oracle MPP energy")
ax.plot(trace["time_s"], trace["p_mpp"], color="#2563eb", linewidth=1.6, label="oracle MPP")
ax.plot(visible["time_s"], visible["p_pv"], color="#f97316", linewidth=2.5, label="P&O tracked PV")
latest = visible.iloc[-1]
ax.scatter([latest["time_s"]], [latest["p_pv"]], color="#111827", edgecolor="white", linewidth=0.9, s=54, zorder=4)
eff = 100.0 * visible["p_pv"].sum() / max(visible["p_mpp"].sum(), 1e-9)
ax.set_title(f"Python MPPT tracking, partial efficiency {{eff:.2f}}%")
ax.set_xlabel("Time (s)")
ax.set_ylabel("Power (W)")
ax.set_xlim(trace["time_s"].min(), trace["time_s"].max())
ax.set_ylim(0, trace["p_mpp"].max() * 1.08)
ax.grid(True, color="#dbe3ef", linewidth=0.8)
ax.legend(loc="lower right", fontsize=8)
fig.tight_layout()
'''


def _script_converter_duty(frames: int) -> str:
    return f'''
import numpy as np
import matplotlib.pyplot as plt

frame = 0
FRAME_COUNT = {frames}
vin = 48.0
load = 100.0
duty = np.linspace(0.02, 0.90, 160)
vout = -vin * duty / (1.0 - duty)
pout = (vout * vout) / load
idx = max(0, min(int(frame), FRAME_COUNT - 1))
active = max(2, int((idx + 1) * len(duty) / FRAME_COUNT))
fig, (ax_v, ax_p) = plt.subplots(1, 2, figsize=(9.6, 5.4))
ax_v.plot(duty[:active], vout[:active], color="#7c3aed", linewidth=2.4)
ax_v.scatter([duty[active - 1]], [vout[active - 1]], color="#111827", edgecolor="white", zorder=4)
ax_v.set_title("Inverting buck-boost duty sweep")
ax_v.set_xlabel("Duty cycle")
ax_v.set_ylabel("Ideal output voltage (V)")
ax_v.set_xlim(0, 0.92)
ax_v.set_ylim(vout.min() * 1.08, 0)
ax_v.grid(True, color="#dbe3ef", linewidth=0.8)
ax_p.plot(duty[:active], pout[:active], color="#16a34a", linewidth=2.4)
ax_p.scatter([duty[active - 1]], [pout[active - 1]], color="#111827", edgecolor="white", zorder=4)
ax_p.set_title("Reference load power")
ax_p.set_xlabel("Duty cycle")
ax_p.set_ylabel("Power (W)")
ax_p.set_xlim(0, 0.92)
ax_p.set_ylim(0, pout.max() * 1.05)
ax_p.grid(True, color="#dbe3ef", linewidth=0.8)
fig.tight_layout()
'''


def _script_pv_surface(static_curves: Path, frames: int) -> str:
    return f'''
import pandas as pd
import matplotlib.pyplot as plt

frame = 0
FRAME_COUNT = {frames}
curves = pd.read_csv({str(static_curves.resolve())!r})
surface = curves[curves["temperature_c"] == 25.0]
fig = plt.figure(figsize=(9.6, 5.4))
ax = fig.add_subplot(111, projection="3d")
idx = max(0, min(int(frame), FRAME_COUNT - 1))
angle = 35 + 320 * idx / max(FRAME_COUNT - 1, 1)
for irradiance, group in surface.groupby("irradiance_w_m2"):
    ax.plot(group["voltage_v"], [irradiance] * len(group), group["power_w"], linewidth=2.0)
ax.set_title("Python 3D PV surface at 25 C")
ax.set_xlabel("PV voltage (V)")
ax.set_ylabel("Irradiance (W/m2)")
ax.set_zlabel("Power (W)")
ax.view_init(elev=25, azim=angle)
fig.tight_layout()
'''


def _script_readme_hero(
    static_curves: Path,
    static_mpp: Path,
    mppt_trace: Path,
    mppt_metrics: Path,
    frames: int,
) -> str:
    return f'''
import json
import pandas as pd
import matplotlib.pyplot as plt

frame = 0
FRAME_COUNT = {frames}
curves = pd.read_csv({str(static_curves.resolve())!r})
mpp = pd.read_csv({str(static_mpp.resolve())!r})
trace = pd.read_csv({str(mppt_trace.resolve())!r})
metrics = json.loads(open({str(mppt_metrics.resolve())!r}, encoding="utf-8").read())
fig = plt.figure(figsize=(9.6, 5.4), facecolor="#f8fafc")
canvas = fig.add_axes([0.0, 0.0, 1.0, 1.0], frameon=False)
canvas.set_axis_off()
canvas.patch.set_alpha(0.0)
canvas.set_zorder(10)
ax = fig.add_axes([0.07, 0.18, 0.58, 0.56])
panel = fig.add_axes([0.70, 0.18, 0.24, 0.56])
panel.axis("off")
idx = max(0, min(int(frame), FRAME_COUNT - 1))
phase = idx / max(FRAME_COUNT - 1, 1)
if frame >= 0:
    canvas.set_axis_off()
    panel.set_axis_off()
canvas.text(0.07, 0.925, "pvmppt-lab", fontsize=12, weight="bold", color="#0f172a")
if phase < 0.45:
    canvas.text(0.07, 0.865, "PV curve sweep", fontsize=19, weight="bold", color="#111827")
    canvas.text(0.07, 0.815, "Python-generated IV/PV design evidence", fontsize=10.5, color="#475569")
    irradiances = sorted(curves["irradiance_w_m2"].unique())
    visible_count = max(1, int(1 + phase / 0.45 * len(irradiances)))
    visible = irradiances[:min(len(irradiances), visible_count)]
    shown = curves[curves["temperature_c"] == 25.0]
    marks = mpp[(mpp["temperature_c"] == 25.0) & (mpp["irradiance_w_m2"].isin(visible))]
    colors = ["#60a5fa", "#16a34a", "#f97316", "#dc2626"]
    for color_index, irradiance in enumerate(visible):
        group = shown[shown["irradiance_w_m2"] == irradiance]
        ax.plot(group["voltage_v"], group["power_w"], linewidth=2.4, color=colors[color_index % len(colors)], label=f"{{irradiance:.0f}} W/m2")
    ax.scatter(marks["v_mpp"], marks["p_mpp"], color="#111827", edgecolor="white", s=50, zorder=4, label="MPP")
    ax.set_xlim(0, 42)
    ax.set_ylim(0, curves["power_w"].max() * 1.08)
    ax.set_xlabel("PV voltage (V)")
    ax.set_ylabel("Power (W)")
    ax.grid(True, color="#dbe3ef")
    ax.legend(loc="upper left", fontsize=8)
    panel.text(0.04, 0.82, "16", fontsize=18, weight="bold")
    panel.text(0.04, 0.74, "static scenarios", fontsize=9, color="#64748b")
    panel.text(0.04, 0.56, "3,840", fontsize=18, weight="bold")
    panel.text(0.04, 0.48, "curve rows", fontsize=9, color="#64748b")
    panel.text(0.04, 0.30, "Python", fontsize=18, weight="bold", color="#2563eb")
    panel.text(0.04, 0.22, "design + animation", fontsize=9, color="#64748b")
else:
    canvas.text(0.07, 0.865, "MPPT tracking check", fontsize=19, weight="bold", color="#111827")
    canvas.text(0.07, 0.815, "P&O controller trace vs oracle MPP envelope", fontsize=10.5, color="#475569")
    progress = min(1.0, (phase - 0.45) / 0.55)
    rows = max(2, int(progress * len(trace)))
    visible = trace.iloc[:rows]
    ax.fill_between(trace["time_s"], trace["p_mpp"], color="#dbeafe", alpha=0.65, label="oracle MPP energy")
    ax.plot(trace["time_s"], trace["p_mpp"], color="#2563eb", linewidth=1.6, label="oracle MPP")
    ax.plot(visible["time_s"], visible["p_pv"], color="#f97316", linewidth=2.5, label="P&O tracked PV")
    latest = visible.iloc[-1]
    ax.scatter([latest["time_s"]], [latest["p_pv"]], color="#111827", edgecolor="white", s=50, zorder=4)
    ax.set_xlim(trace["time_s"].min(), trace["time_s"].max())
    ax.set_ylim(0, trace["p_mpp"].max() * 1.08)
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Power (W)")
    ax.grid(True, color="#dbe3ef")
    ax.legend(loc="lower right", fontsize=8)
    panel.text(0.04, 0.82, f"{{100.0 * metrics['tracking_efficiency']:.2f}}%", fontsize=18, weight="bold")
    panel.text(0.04, 0.74, "tracking efficiency", fontsize=9, color="#64748b")
    panel.text(0.04, 0.56, f"{{metrics['energy_pv_j']:.2f}} J", fontsize=18, weight="bold")
    panel.text(0.04, 0.48, "tracked energy", fontsize=9, color="#64748b")
    panel.text(0.04, 0.30, "CSV JSON plots", fontsize=15, weight="bold", color="#16a34a")
    panel.text(0.04, 0.22, "reproducible evidence pack", fontsize=9, color="#64748b")
canvas.text(0.07, 0.075, "Generated by pvmppt-lab animate via mpl-animator", fontsize=9.0, color="#64748b")
canvas.text(0.91, 0.075, f"{{idx + 1:02d}}/{{FRAME_COUNT}}", fontsize=8.0, ha="right", color="#94a3b8")
'''


def _validate_animation_options(fmt: str, frames: int, fps: int, dpi: int) -> None:
    if fmt not in {"gif", "mp4"}:
        raise ValueError("format must be gif or mp4")
    if frames < 2:
        raise ValueError("frames must be at least 2")
    if fps <= 0:
        raise ValueError("fps must be positive")
    if dpi <= 0:
        raise ValueError("dpi must be positive")


def _equivalent_mpl_animator_command(
    script_path: Path,
    variables: list[str],
    ranges: list[str] | None,
    values: list[str] | None,
    frames: int,
    fps: int,
    workers: int,
    dpi: int,
    fmt: str,
    output_path: Path,
) -> list[str]:
    command = ["mpl-animator", _display_path(script_path), "--var", *variables]
    if values is not None:
        command.extend(["--values", *values])
    else:
        command.extend(["--range", *(ranges or ["0,1"])])
        command.extend(["--frames", str(frames)])
    command.extend(
        [
            "--fps",
            str(fps),
            "--workers",
            str(workers),
            "--dpi",
            str(dpi),
            "--format",
            fmt,
            "--out",
            _display_path(output_path),
        ]
    )
    return command


def _require_paths(paths: list[Path]) -> None:
    missing = [str(path) for path in paths if not path.exists()]
    if missing:
        raise FileNotFoundError(
            "missing animation source artifacts; run compare/reproduce first: "
            + ", ".join(missing)
        )


def _backend_version() -> str:
    return importlib.metadata.version("mpl-animator")


def _single_or_list(values: list[str] | None) -> str | list[str] | None:
    if values is None:
        return None
    return values[0] if len(values) == 1 else values


def _values_frame_count(values: list[str]) -> int:
    return len([item for item in values[0].split(",") if item.strip()])


def _display_path(path: str | Path) -> str:
    candidate = Path(path)
    if not candidate.is_absolute():
        return str(candidate)
    try:
        return str(candidate.relative_to(Path.cwd().resolve()))
    except ValueError:
        return str(candidate)
