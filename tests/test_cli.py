import json
import os
from pathlib import Path
import subprocess
import sys

from PIL import Image, ImageSequence


def run_cli(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path.cwd() / "src")
    return subprocess.run(
        [sys.executable, "-m", "pvmppt_lab.cli", *args],
        cwd=Path.cwd(),
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )


def test_cli_static_and_report(tmp_path):
    static_dir = tmp_path / "static"
    result = run_cli(tmp_path, "run-static", "--output", str(static_dir), "--points", "48")
    payload = json.loads(result.stdout)
    assert Path(payload["curves_csv"]).exists()
    assert (static_dir / "metrics.json").exists()


def test_cli_does_not_expose_private_inspector(tmp_path):
    result = run_cli(tmp_path, "--help")
    assert "inspect" not in result.stdout
    assert "audit-models" in result.stdout
    assert "reproduce" in result.stdout
    assert "design-module" in result.stdout
    assert "validate-module" in result.stdout
    assert "fit-module" in result.stdout
    assert "animate" in result.stdout
    assert "animate-script" in result.stdout


def test_cli_audit_models(tmp_path):
    output = tmp_path / "audit"
    result = run_cli(tmp_path, "audit-models", "--output", str(output))
    payload = json.loads(result.stdout)
    assert payload["summary"]["total_files"] > 0
    assert (output / "inventory.json").exists()


def test_cli_reproduce_pv_cell(tmp_path):
    output = tmp_path / "repro"
    result = run_cli(
        tmp_path,
        "reproduce",
        "--suite",
        "pv-cell",
        "--points",
        "24",
        "--output",
        str(output),
    )
    payload = json.loads(result.stdout)
    assert payload["completed_suites"] == ["pv-cell"]
    assert (output / "pv-cell" / "pv_cell_mpp.csv").exists()


def test_cli_design_validate_and_fit_module(tmp_path):
    spec = Path("docs/examples/trina-module.yaml")
    design_dir = tmp_path / "design"
    design_result = run_cli(
        tmp_path,
        "design-module",
        "--spec",
        str(spec),
        "--output",
        str(design_dir),
    )
    design_payload = json.loads(design_result.stdout)
    assert design_payload["workflow"] == "python-only module design"
    assert (design_dir / "design_summary.json").exists()
    assert (design_dir / "iv_pv_curves.csv").exists()

    validation_dir = tmp_path / "validation"
    validation_result = run_cli(
        tmp_path,
        "validate-module",
        "--spec",
        str(spec),
        "--backend",
        "internal",
        "--output",
        str(validation_dir),
    )
    validation_payload = json.loads(validation_result.stdout)
    assert validation_payload["status"] == "pass"
    assert (validation_dir / "validation_summary.json").exists()

    fit_dir = tmp_path / "fit"
    fit_result = run_cli(
        tmp_path,
        "fit-module",
        "--datasheet",
        str(spec),
        "--method",
        "desoto",
        "--output",
        str(fit_dir),
    )
    fit_payload = json.loads(fit_result.stdout)
    assert fit_payload["workflow"] == "python-only module fit"
    assert (fit_dir / "fitted_module.yaml").exists()


def test_cli_animate_preset_creates_gif_and_manifest(tmp_path):
    run_dir = tmp_path / "comparison"
    run_cli(tmp_path, "compare", "--output", str(run_dir), "--total-time-s", "0.03")
    output = run_dir / "animations"
    result = run_cli(
        tmp_path,
        "animate",
        "--preset",
        "pv-sweep",
        "--run-dir",
        str(run_dir),
        "--output-dir",
        str(output),
        "--frames",
        "4",
        "--fps",
        "2",
        "--workers",
        "1",
        "--dpi",
        "80",
    )
    payload = json.loads(result.stdout)
    gif_path = Path(payload["output_files"][0])
    assert gif_path.exists()
    assert (output / "animation_manifest.json").exists()
    image = Image.open(gif_path)
    assert image.size[0] > 300
    assert sum(1 for _ in ImageSequence.Iterator(image)) == 4
    run_cli(tmp_path, "report", "--run-dir", str(run_dir))
    report = (run_dir / "report.md").read_text(encoding="utf-8")
    assert "animations/animation_manifest.json" in report
    assert "animations/pvmppt-lab-pv-sweep.gif" in report


def test_cli_animate_script_renders_range_and_values(tmp_path):
    script = tmp_path / "my_plot.py"
    script.write_text(
        "\n".join(
            [
                "import matplotlib.pyplot as plt",
                "freq = 1",
                "gain = 1",
                "x = [0, 1, 2, 3]",
                "y = [gain * freq * item for item in x]",
                "fig, ax = plt.subplots()",
                "ax.plot(x, y)",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    by_range = tmp_path / "range.gif"
    range_result = run_cli(
        tmp_path,
        "animate-script",
        str(script),
        "--var",
        "freq",
        "--range",
        "1,4",
        "--frames",
        "3",
        "--workers",
        "1",
        "--fps",
        "2",
        "--dpi",
        "80",
        "--out",
        str(by_range),
    )
    range_payload = json.loads(range_result.stdout)
    assert Path(range_payload["output_files"][0]).exists()
    assert Path(range_payload["manifest"]).exists()

    by_values = tmp_path / "values.gif"
    values_result = run_cli(
        tmp_path,
        "animate-script",
        str(script),
        "--var",
        "freq",
        "gain",
        "--values",
        "1,2,3",
        "1,0.5,0.25",
        "--workers",
        "1",
        "--fps",
        "2",
        "--dpi",
        "80",
        "--out",
        str(by_values),
    )
    values_payload = json.loads(values_result.stdout)
    assert Path(values_payload["output_files"][0]).exists()
    assert values_payload["values"] == ["1,2,3", "1,0.5,0.25"]


def test_cli_release_check(tmp_path):
    output = tmp_path / "release.json"
    result = run_cli(tmp_path, "release-check", "--output", str(output))
    payload = json.loads(result.stdout)
    assert payload["status"] == "pass"
    assert "Prompt.md" not in payload["public_release_manifest"]
    assert "private source folders" in payload["excluded_private_inputs"]
    assert output.exists()


def test_cli_export_public(tmp_path):
    output = tmp_path / "public"
    result = run_cli(tmp_path, "export-public", "--output", str(output), "--init-git")
    payload = json.loads(result.stdout)
    assert payload["status"] == "pass"
    assert (output / "README.md").exists()
    assert (output / ".git").exists()
    assert not (output / "src" / "pvmppt_lab" / "legacy.py").exists()
    assert not (output / "tests" / "test_legacy.py").exists()
    assert not (output / "Prompt.md").exists()
