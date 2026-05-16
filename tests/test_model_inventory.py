from pathlib import Path

from pvmppt_lab.model_inventory import audit_model_assets


def test_audit_model_assets_writes_inventory(tmp_path):
    payload = audit_model_assets(Path.cwd(), tmp_path)

    assert (tmp_path / "inventory.json").exists()
    assert (tmp_path / "model_assets.csv").exists()
    assert (tmp_path / "inventory.md").exists()
    assert payload["summary"]["total_files"] > 0

    if payload["summary"]["model_asset_count"]:
        assert payload["summary"]["mdl_count"] >= 11
        assert payload["summary"]["slx_count"] >= 2
        assert payload["summary"]["matlab_script_count"] >= 1
        replacement_map = payload["python_replacement_map"]
        assert len(replacement_map) == payload["summary"]["model_asset_count"]
        assert {row["python_suite"] for row in replacement_map} >= {
            "pv-cell",
            "pv-module",
            "pv-array",
            "mppt",
            "converter",
        }
        assert all(row["python_command"].startswith("pvmppt-lab reproduce") for row in replacement_map)
        roles = {asset["role"] for asset in payload["model_assets"]}
        assert "mpp extraction script" in roles
        assert "mppt controller and pv system model" in roles
        assert "converter reference model" in roles
