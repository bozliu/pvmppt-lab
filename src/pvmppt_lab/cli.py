from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .animation import ANIMATION_PRESETS, render_animation_presets, render_script_animation
from .design import design_module, fit_module, validate_module
from .model_inventory import audit_model_assets
from .release import export_public_release, scan_public_release
from .reproduction import SUITES, run_reproduction_suite
from .reporting import (
    ensure_dir,
    write_json,
    write_markdown_report,
    write_readme_assets,
)
from .scenarios import run_mppt_demo, run_static_sweep


ROOT = Path.cwd()


def _float_list(value: str) -> list[float]:
    return [float(item.strip()) for item in value.split(",") if item.strip()]


def cmd_audit_models(args: argparse.Namespace) -> int:
    payload = audit_model_assets(Path(args.root), Path(args.output))
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def cmd_reproduce(args: argparse.Namespace) -> int:
    payload = run_reproduction_suite(
        Path(args.output),
        suite=args.suite,
        points=args.points,
    )
    print(json.dumps(payload["summary"], indent=2, sort_keys=True))
    return 0


def cmd_design_module(args: argparse.Namespace) -> int:
    payload = design_module(Path(args.spec), Path(args.output))
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def cmd_validate_module(args: argparse.Namespace) -> int:
    payload = validate_module(Path(args.spec), Path(args.output), backend=args.backend)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def cmd_fit_module(args: argparse.Namespace) -> int:
    payload = fit_module(Path(args.datasheet), Path(args.output), method=args.method)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def cmd_run_static(args: argparse.Namespace) -> int:
    result = run_static_sweep(
        Path(args.output),
        irradiances=_float_list(args.irradiances),
        temperatures=_float_list(args.temperatures),
        points=args.points,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def cmd_run_mppt(args: argparse.Namespace) -> int:
    result = run_mppt_demo(
        Path(args.output),
        total_time_s=args.total_time_s,
        temperature_c=args.temperature_c,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    static = run_static_sweep(Path(args.output) / "static")
    mppt = run_mppt_demo(Path(args.output) / "mppt", total_time_s=args.total_time_s)
    summary = {
        "static_reference_pmp_error_pct": static["metrics"]["reference_pmp_error_pct"],
        "mppt_tracking_efficiency": mppt["metrics"]["tracking_efficiency"],
        "mppt_energy_pv_j": mppt["metrics"]["energy_pv_j"],
        "mppt_energy_mpp_j": mppt["metrics"]["energy_mpp_j"],
        "value_statement": "Compares achievable oracle MPP energy with P&O-controlled operation.",
    }
    ensure_dir(Path(args.output))
    write_json(Path(args.output) / "comparison_metrics.json", summary)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir)
    report = write_markdown_report(run_dir, title=args.title)
    print(str(report))
    return 0


def cmd_build_readme_assets(args: argparse.Namespace) -> int:
    payload = write_readme_assets(Path(args.run_dir), Path(args.output_dir))
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def cmd_animate(args: argparse.Namespace) -> int:
    payload = render_animation_presets(
        Path(args.run_dir),
        Path(args.output_dir),
        preset=args.preset,
        fmt=args.format,
        frames=args.frames,
        fps=args.fps,
        workers=args.workers,
        dpi=args.dpi,
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def cmd_animate_script(args: argparse.Namespace) -> int:
    output_path = Path(args.out) if args.out else None
    result = render_script_animation(
        Path(args.script),
        variables=args.var,
        ranges=args.range,
        values=args.values,
        frames=args.frames,
        fps=args.fps,
        workers=args.workers,
        dpi=args.dpi,
        fmt=args.format,
        output_path=output_path,
    )
    manifest = result.to_dict()
    manifest_path = Path(result.output_files[0]).parent / "animation_manifest.json"
    write_json(manifest_path, manifest)
    print(json.dumps({**manifest, "manifest": str(manifest_path)}, indent=2, sort_keys=True))
    return 0


def cmd_release_check(args: argparse.Namespace) -> int:
    root = Path(args.root)
    payload = scan_public_release(root).to_dict()
    if args.output:
        write_json(Path(args.output), payload)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["status"] == "pass" else 1


def cmd_export_public(args: argparse.Namespace) -> int:
    payload = export_public_release(
        Path(args.root), Path(args.output), init_git=args.init_git
    ).to_dict()
    if args.manifest_output:
        write_json(Path(args.manifest_output), payload)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["status"] == "pass" else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pvmppt-lab",
        description="Reproducible PV module, converter, and MPPT experiment automation.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    audit = sub.add_parser("audit-models", help="Inventory runnable model assets.")
    audit.add_argument("--root", default=".")
    audit.add_argument("--output", default="runs/model-audit")
    audit.set_defaults(func=cmd_audit_models)

    reproduce = sub.add_parser(
        "reproduce",
        help="Run Python-only reproduction suites for PV/converter/MPPT models.",
    )
    reproduce.add_argument("--suite", choices=sorted(SUITES), default="all")
    reproduce.add_argument("--output", default="runs/reproduction")
    reproduce.add_argument("--points", type=int, default=240)
    reproduce.set_defaults(func=cmd_reproduce)

    design = sub.add_parser(
        "design-module",
        help="Generate Python-only PV module design curves from a datasheet spec.",
    )
    design.add_argument("--spec", required=True, help="YAML/JSON datasheet-style module spec.")
    design.add_argument("--output", default="runs/design")
    design.set_defaults(func=cmd_design_module)

    validate = sub.add_parser(
        "validate-module",
        help="Validate a PV module spec with the internal solver or optional pvlib backend.",
    )
    validate.add_argument("--spec", required=True, help="YAML/JSON datasheet-style module spec.")
    validate.add_argument("--backend", choices=["internal", "pvlib"], default="internal")
    validate.add_argument("--output", default="runs/validation")
    validate.set_defaults(func=cmd_validate_module)

    fit = sub.add_parser(
        "fit-module",
        help="Fit a datasheet-style module spec into single-diode parameters.",
    )
    fit.add_argument("--datasheet", required=True, help="YAML/JSON datasheet-style module spec.")
    fit.add_argument("--method", choices=["desoto", "cec", "pvsyst"], default="desoto")
    fit.add_argument("--output", default="runs/fitted")
    fit.set_defaults(func=cmd_fit_module)

    static = sub.add_parser("run-static", help="Run static I-V/P-V sweeps.")
    static.add_argument("--output", default="runs/static-demo")
    static.add_argument("--irradiances", default="400,650,800,1000")
    static.add_argument("--temperatures", default="0,25,50,75")
    static.add_argument("--points", type=int, default=240)
    static.set_defaults(func=cmd_run_static)

    mppt = sub.add_parser("run-mppt", help="Run averaged P&O MPPT demo.")
    mppt.add_argument("--output", default="runs/mppt-demo")
    mppt.add_argument("--total-time-s", type=float, default=0.25)
    mppt.add_argument("--temperature-c", type=float, default=25.0)
    mppt.set_defaults(func=cmd_run_mppt)

    compare = sub.add_parser("compare", help="Run static and MPPT demos together.")
    compare.add_argument("--output", default="runs/comparison-demo")
    compare.add_argument("--total-time-s", type=float, default=0.25)
    compare.set_defaults(func=cmd_compare)

    report = sub.add_parser("report", help="Generate Markdown and HTML report for a run dir.")
    report.add_argument("--run-dir", default="runs/comparison-demo")
    report.add_argument("--title", default="PV/MPPT Lab Engineering Report")
    report.set_defaults(func=cmd_report)

    assets = sub.add_parser(
        "build-readme-assets",
        help="Generate compact README figures from a comparison run.",
    )
    assets.add_argument("--run-dir", default="runs/comparison-demo")
    assets.add_argument("--output-dir", default="docs/assets")
    assets.set_defaults(func=cmd_build_readme_assets)

    animate = sub.add_parser(
        "animate",
        help="Generate GIF/MP4 animation presets through mpl-animator.",
    )
    animate.add_argument("--preset", choices=sorted(ANIMATION_PRESETS), default="all")
    animate.add_argument("--run-dir", default="runs/comparison-demo")
    animate.add_argument("--output-dir", default="runs/comparison-demo/animations")
    animate.add_argument("--format", choices=["gif", "mp4"], default="gif")
    animate.add_argument("--frames", type=int, default=60)
    animate.add_argument("--fps", type=int, default=20)
    animate.add_argument("--workers", type=int, default=0)
    animate.add_argument("--dpi", type=int, default=110)
    animate.set_defaults(func=cmd_animate)

    animate_script = sub.add_parser(
        "animate-script",
        help="Render a matplotlib script with mpl-animator and run the generated animation.",
    )
    animate_script.add_argument("script")
    animate_script.add_argument("--var", nargs="+", required=True)
    animate_script.add_argument("--range", nargs="+", default=None)
    animate_script.add_argument("--values", nargs="+", default=None)
    animate_script.add_argument("--frames", type=int, default=60)
    animate_script.add_argument("--fps", type=int, default=20)
    animate_script.add_argument("--workers", type=int, default=0)
    animate_script.add_argument("--dpi", type=int, default=110)
    animate_script.add_argument("--format", choices=["gif", "mp4"], default="gif")
    animate_script.add_argument("--out", default=None)
    animate_script.set_defaults(func=cmd_animate_script)

    release = sub.add_parser("release-check", help="Check public-release readiness.")
    release.add_argument("--root", default=".")
    release.add_argument("--output", default="runs/release-check.json")
    release.set_defaults(func=cmd_release_check)

    export = sub.add_parser("export-public", help="Export a clean public-release tree.")
    export.add_argument("--root", default=".")
    export.add_argument("--output", default="runs/public-release/pvmppt-lab")
    export.add_argument("--manifest-output", default="runs/public-release-manifest.json")
    export.add_argument(
        "--init-git",
        action="store_true",
        help="Initialize a fresh Git repo in the exported public tree.",
    )
    export.set_defaults(func=cmd_export_public)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
