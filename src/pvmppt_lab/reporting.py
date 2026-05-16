from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from PIL import Image, ImageSequence


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def plot_static_curves(df: pd.DataFrame, output_dir: Path) -> list[Path]:
    paths: list[Path] = []
    for y, ylabel, filename in [
        ("current_a", "Current (A)", "iv_curves.png"),
        ("power_w", "Power (W)", "pv_curves.png"),
    ]:
        fig, ax = plt.subplots(figsize=(8, 5))
        for (irr, temp), group in df.groupby(["irradiance_w_m2", "temperature_c"]):
            ax.plot(group["voltage_v"], group[y], label=f"{irr:.0f} W/m2, {temp:.0f} C")
        ax.set_xlabel("PV voltage (V)")
        ax.set_ylabel(ylabel)
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=8)
        fig.tight_layout()
        path = output_dir / filename
        fig.savefig(path, dpi=160)
        plt.close(fig)
        paths.append(path)
    return paths


def plot_mppt(df: pd.DataFrame, output_dir: Path) -> list[Path]:
    paths: list[Path] = []
    specs = [
        (["p_pv", "p_mpp"], "Power (W)", "mppt_power.png"),
        (["duty"], "Duty cycle", "mppt_duty.png"),
        (["v_pv", "v_mpp"], "Voltage (V)", "mppt_voltage.png"),
        (["irradiance_w_m2"], "Irradiance (W/m2)", "mppt_irradiance.png"),
    ]
    for columns, ylabel, filename in specs:
        fig, ax = plt.subplots(figsize=(8, 4))
        for column in columns:
            ax.plot(df["time_s"], df[column], label=column)
        ax.set_xlabel("Time (s)")
        ax.set_ylabel(ylabel)
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=8)
        fig.tight_layout()
        path = output_dir / filename
        fig.savefig(path, dpi=160)
        plt.close(fig)
        paths.append(path)
    return paths


def write_readme_assets(run_dir: Path, output_dir: Path) -> dict[str, object]:
    """Create compact, generated README visuals from reproducible run data."""

    from .animation import render_readme_hero

    run_dir = Path(run_dir)
    output_dir = ensure_dir(Path(output_dir))
    static_curves = pd.read_csv(run_dir / "static" / "static_curves.csv")
    static_mpp = pd.read_csv(run_dir / "static" / "static_mpp.csv")
    mppt_trace = pd.read_csv(run_dir / "mppt" / "mppt_trace.csv")

    pv_curve_path = output_dir / "pvmppt-lab-pv-curves.png"
    mppt_power_path = output_dir / "pvmppt-lab-mppt-power.png"

    _write_readme_pv_curve(static_curves, static_mpp, pv_curve_path)
    _write_readme_mppt_power(mppt_trace, mppt_power_path)
    hero = render_readme_hero(run_dir, output_dir)
    contact_sheet_path = output_dir / "pvmppt-lab-hero-contact-sheet.png"
    _write_gif_contact_sheet(Path(hero.output_files[0]), contact_sheet_path)

    return {
        "output_dir": str(output_dir),
        "assets": [
            *hero.output_files,
            str(pv_curve_path),
            str(mppt_power_path),
            str(contact_sheet_path),
        ],
        "animation_backend": hero.backend,
        "animation_manifest": hero.to_dict(),
    }


def _write_readme_pv_curve(
    curves: pd.DataFrame, mpp: pd.DataFrame, output_path: Path
) -> None:
    fig, ax = plt.subplots(figsize=(8, 4.5))
    temperature = 25.0
    shown_curves = curves[curves["temperature_c"] == temperature]
    shown_mpp = mpp[mpp["temperature_c"] == temperature]
    for irradiance, group in shown_curves.groupby("irradiance_w_m2"):
        ax.plot(group["voltage_v"], group["power_w"], label=f"{irradiance:.0f} W/m2")
    ax.scatter(
        shown_mpp["v_mpp"],
        shown_mpp["p_mpp"],
        color="#d62728",
        s=38,
        label="computed MPP",
        zorder=3,
    )
    ax.set_title("PV power curves with computed maximum-power points")
    ax.set_xlabel("PV voltage (V)")
    ax.set_ylabel("Power (W)")
    ax.grid(True, alpha=0.28)
    ax.legend(loc="best", fontsize=8)
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def _write_readme_mppt_power(trace: pd.DataFrame, output_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.plot(trace["time_s"], trace["p_mpp"], color="#1f77b4", label="oracle MPP")
    ax.plot(trace["time_s"], trace["p_pv"], color="#ff7f0e", label="P&O tracked PV")
    ax.set_title("Controller trace against the oracle MPP envelope")
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Power (W)")
    ax.grid(True, alpha=0.28)
    ax.legend(loc="best", fontsize=8)
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def _write_gif_contact_sheet(gif_path: Path, output_path: Path) -> None:
    image = Image.open(gif_path)
    frames = [frame.copy().convert("RGB") for frame in ImageSequence.Iterator(image)]
    if not frames:
        raise RuntimeError(f"cannot build contact sheet from empty GIF: {gif_path}")
    indices = sorted({0, len(frames) // 2, len(frames) - 1})
    selected = [frames[index] for index in indices]
    thumb_width = 360
    thumbnails: list[Image.Image] = []
    for frame in selected:
        thumb = frame.copy()
        ratio = thumb_width / thumb.width
        thumb.thumbnail((thumb_width, int(thumb.height * ratio)), Image.Resampling.LANCZOS)
        thumbnails.append(thumb)
    gap = 12
    width = sum(thumb.width for thumb in thumbnails) + gap * (len(thumbnails) - 1)
    height = max(thumb.height for thumb in thumbnails)
    sheet = Image.new("RGB", (width, height), "white")
    x = 0
    for thumb in thumbnails:
        sheet.paste(thumb, (x, 0))
        x += thumb.width + gap
    sheet.save(output_path, optimize=True)


def write_markdown_report(run_dir: Path, title: str = "PV/MPPT Lab Report") -> Path:
    metrics_paths = sorted(run_dir.glob("**/metrics.json"))
    lines = [
        f"# {title}",
        "",
        "This generated report summarizes reproducible PV/MPPT experiment artifacts.",
        "",
        "## Metrics",
        "",
    ]
    for path in metrics_paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        lines.append(f"### {path.relative_to(run_dir)}")
        lines.append("")
        for key, value in data.items():
            if isinstance(value, float):
                lines.append(f"- `{key}`: {value:.6g}")
            else:
                lines.append(f"- `{key}`: {value}")
        lines.append("")
    lines.extend(
        [
            "## Artifacts",
            "",
            *[f"- `{p.relative_to(run_dir)}`" for p in sorted(run_dir.rglob("*")) if p.is_file()],
            "",
            "## Known Limitations",
            "",
            "- This v1 uses an averaged converter/load-reflection model, not a switched SPICE model.",
            "- Proprietary simulator waveforms are not used as golden traces.",
            "- Public releases should include generated evidence artifacts, not source-folder media.",
        ]
    )
    report_path = run_dir / "report.md"
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    html_path = run_dir / "report.html"
    html_path.write_text(
        "<!doctype html><meta charset='utf-8'><title>PV/MPPT Lab Report</title>"
        "<style>body{font-family:system-ui,sans-serif;max-width:900px;margin:40px auto;"
        "line-height:1.5}code{background:#f3f4f6;padding:2px 4px}</style><pre>"
        + report_path.read_text(encoding="utf-8").replace("&", "&amp;").replace("<", "&lt;")
        + "</pre>",
        encoding="utf-8",
    )
    return report_path
