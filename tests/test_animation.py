import json
from pathlib import Path

from PIL import Image, ImageSequence

from pvmppt_lab.animation import _script_readme_hero
from pvmppt_lab.reporting import write_readme_assets
from pvmppt_lab.scenarios import run_mppt_demo, run_static_sweep


def test_readme_hero_script_uses_frame_scoped_canvas_text(tmp_path):
    script = _script_readme_hero(
        tmp_path / "static_curves.csv",
        tmp_path / "static_mpp.csv",
        tmp_path / "mppt_trace.csv",
        tmp_path / "metrics.json",
        frames=4,
    )

    assert "fig.text" not in script
    assert "canvas.text" in script


def test_readme_assets_emit_valid_hero_and_contact_sheet(tmp_path):
    run_dir = tmp_path / "comparison"
    run_static_sweep(run_dir / "static", points=48)
    run_mppt_demo(run_dir / "mppt", total_time_s=0.03)
    payload = write_readme_assets(run_dir, tmp_path / "assets")

    hero_path = tmp_path / "assets" / "pvmppt-lab-hero.gif"
    contact_sheet = tmp_path / "assets" / "pvmppt-lab-hero-contact-sheet.png"
    assert hero_path.exists()
    assert contact_sheet.exists()
    image = Image.open(hero_path)
    assert image.size[0] >= 900
    assert image.size[1] >= 480
    assert sum(1 for _ in ImageSequence.Iterator(image)) == 24
    assert image.info.get("loop") == 0
    assert contact_sheet.stat().st_size > 0
    manifest = payload["animation_manifest"]
    assert manifest["backend"] == "mpl-animator"
    assert "fig.text" not in Path(manifest["generated_script"]).read_text(encoding="utf-8")
    assert json.dumps(payload)
