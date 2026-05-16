from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
import csv
import re
from pathlib import Path
import zipfile
import xml.etree.ElementTree as ET

from .reporting import ensure_dir, write_json


MODEL_SUFFIXES = {".m", ".mdl", ".slx"}
DOCUMENT_SUFFIXES = {".doc", ".docx", ".pdf", ".ppt", ".pptx", ".txt"}
MEDIA_SUFFIXES = {".gif", ".jpeg", ".jpg", ".m4a", ".mov", ".mp3", ".mp4", ".png", ".wav"}
GENERATED_PARTS = {
    ".git",
    ".omx",
    ".pytest_cache",
    "__pycache__",
    "runs",
    "slprj",
}


@dataclass(frozen=True)
class ModelAsset:
    path: str
    suffix: str
    role: str
    simulator_family: str
    stop_time_s: str | None
    solver: str | None
    output_variables: list[str]
    source_blocks: list[str]
    parameter_hints: dict[str, str]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def audit_model_assets(root: Path, output_dir: Path | None = None) -> dict[str, object]:
    root = Path(root).resolve()
    files = _iter_files(root)
    by_suffix = Counter(_suffix(path) for path in files)
    by_category = Counter(_category(path, root) for path in files)
    model_assets = [_inspect_model_asset(path, root) for path in files if _suffix(path) in MODEL_SUFFIXES]
    replacement_map = [_python_replacement_for_asset(asset) for asset in model_assets]

    payload = {
        "root": str(root),
        "summary": {
            "total_files": len(files),
            "by_suffix": dict(sorted(by_suffix.items())),
            "by_category": dict(sorted(by_category.items())),
            "model_asset_count": len(model_assets),
            "mdl_count": sum(1 for asset in model_assets if asset.suffix == ".mdl"),
            "slx_count": sum(1 for asset in model_assets if asset.suffix == ".slx"),
            "matlab_script_count": sum(1 for asset in model_assets if asset.suffix == ".m"),
        },
        "model_assets": [asset.to_dict() for asset in model_assets],
        "python_replacement_map": replacement_map,
        "reproduction_boundary": {
            "included": [
                "PV cell/module/array numerical models",
                "parameter sensitivity sweeps",
                "MPP extraction",
                "converter reference calculations",
                "P&O MPPT traces",
            ],
            "excluded": [
                "document archives",
                "audio/media inputs",
                "generated caches",
                "third-party model source redistribution",
            ],
        },
    }
    if output_dir is not None:
        _write_audit_outputs(payload, Path(output_dir))
    return payload


def _python_replacement_for_asset(asset: ModelAsset) -> dict[str, object]:
    path_lower = asset.path.lower()
    role_lower = asset.role.lower()
    asset_name = Path(asset.path).name.lower()
    if "buck_boost" in path_lower or "converter" in role_lower:
        suite = "converter"
        outputs = ["converter/converter_reference.csv", "converter/converter_reference.png", "converter/metrics.json"]
    elif "mppt" in path_lower:
        suite = "mppt"
        outputs = ["mppt/mppt_dynamic/mppt_trace.csv", "mppt/mppt_fixed_500w_25c/mppt_trace.csv", "mppt/metrics.json"]
    elif "findmpp" in asset_name or "cell" in asset_name or "mpp extraction" in role_lower:
        suite = "pv-cell"
        outputs = ["pv-cell/pv_cell_curves.csv", "pv-cell/pv_cell_mpp.csv", "pv-cell/parameter_sweeps.csv"]
    elif "array" in asset_name:
        suite = "pv-array"
        outputs = ["pv-array/pv_array_curves.csv", "pv-array/pv_array_mpp.csv", "pv-array/metrics.json"]
    elif "module" in asset_name:
        suite = "pv-module"
        outputs = ["pv-module/pv_module_curves.csv", "pv-module/pv_module_mpp.csv", "pv-module/metrics.json"]
    else:
        suite = "all"
        outputs = ["summary.json"]
    return {
        "model_asset": asset.path,
        "local_input_role": asset.role,
        "python_suite": suite,
        "python_command": f"pvmppt-lab reproduce --suite {suite} --output runs/reproduction",
        "generated_outputs": outputs,
        "public_release_policy": "local audit input only; do not publish original model file",
    }


def _iter_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel_parts = set(path.relative_to(root).parts)
        if ".git" in rel_parts:
            continue
        files.append(path)
    return sorted(files)


def _suffix(path: Path) -> str:
    return path.suffix.lower() or "<none>"


def _category(path: Path, root: Path) -> str:
    rel = path.relative_to(root)
    rel_parts = set(rel.parts)
    suffix = _suffix(path)
    if rel_parts & GENERATED_PARTS or any(part.endswith(".egg-info") for part in rel.parts):
        return "generated/cache"
    if suffix in MODEL_SUFFIXES:
        return "runnable model source"
    if suffix in DOCUMENT_SUFFIXES:
        return "documentation/reference"
    if suffix in MEDIA_SUFFIXES:
        return "media/evidence"
    if suffix in {".json", ".csv", ".html"}:
        return "generated output/evidence"
    if suffix in {".py", ".toml", ".yml", ".md"}:
        return "tooling/source"
    return "other"


def _inspect_model_asset(path: Path, root: Path) -> ModelAsset:
    suffix = _suffix(path)
    if suffix == ".slx":
        return _inspect_slx(path, root)
    if suffix == ".mdl":
        return _inspect_mdl(path, root)
    return ModelAsset(
        path=str(path.relative_to(root)),
        suffix=suffix,
        role="mpp extraction script" if path.name.lower() == "findmpp.m" else "matlab script",
        simulator_family="numeric script",
        stop_time_s=None,
        solver=None,
        output_variables=_unique(re.findall(r"PV\.signals\.values|figure|plot", _read_text(path))),
        source_blocks=[],
        parameter_hints={},
    )


def _inspect_mdl(path: Path, root: Path) -> ModelAsset:
    text = _read_text(path)
    output_variables = _unique(re.findall(r'VariableName\s+"([^"]+)"', text))
    source_blocks = _unique(re.findall(r'SourceBlock\s+"([^"]+)"', text))
    parameter_hints = _parameter_hints(text)
    return ModelAsset(
        path=str(path.relative_to(root)),
        suffix=".mdl",
        role=_infer_role(path),
        simulator_family=_infer_simulator_family(text),
        stop_time_s=_first(r'StopTime\s+"([^"]+)"', text),
        solver=_first(r'Solver\s+"([^"]+)"', text),
        output_variables=output_variables,
        source_blocks=source_blocks[:20],
        parameter_hints=parameter_hints,
    )


def _inspect_slx(path: Path, root: Path) -> ModelAsset:
    parameter_hints: dict[str, str] = {}
    output_variables: list[str] = []
    source_blocks: list[str] = []
    stop_time = None
    solver = None
    try:
        with zipfile.ZipFile(path) as archive:
            cfg = archive.read("simulink/configSet0.xml").decode("utf-8", errors="ignore")
            diagram = archive.read("simulink/blockdiagram.xml").decode("utf-8", errors="ignore")
        stop_time = _xml_param_text(cfg, "StopTime")
        solver = _xml_param_text(cfg, "Solver")
        source_blocks, parameter_hints = _slx_block_hints(diagram)
    except (KeyError, OSError, zipfile.BadZipFile, ET.ParseError):
        pass
    return ModelAsset(
        path=str(path.relative_to(root)),
        suffix=".slx",
        role=_infer_role(path),
        simulator_family="block-diagram archive",
        stop_time_s=stop_time,
        solver=solver,
        output_variables=output_variables,
        source_blocks=source_blocks[:20],
        parameter_hints=parameter_hints,
    )


def _slx_block_hints(xml_text: str) -> tuple[list[str], dict[str, str]]:
    root = ET.fromstring(xml_text)
    source_blocks: list[str] = []
    hints: dict[str, str] = {}
    for block in root.iter("Block"):
        name = (block.attrib.get("Name") or "").replace("\n", " ")
        block_type = block.attrib.get("BlockType") or "Block"
        if name:
            source_blocks.append(f"{block_type}:{name}")
        params = {
            child.attrib.get("Name"): (child.text or "").strip()
            for child in block
            if child.tag == "P" and child.attrib.get("Name")
        }
        for key in [
            "ModuleName",
            "Nser",
            "Npar",
            "Pm",
            "Voc",
            "Isc",
            "Vm",
            "Im",
            "alpha_Isc",
            "beta_Voc",
            "IL",
            "I0",
            "nI",
            "Rsh",
            "Rs",
            "SampleTime",
            "Period",
            "PulseWidth",
            "Resistance",
            "Inductance",
            "Capacitance",
        ]:
            value = params.get(key)
            if value and len(hints) < 40:
                label = f"{name}.{key}" if name else key
                hints[label] = value
    return _unique(source_blocks), hints


def _parameter_hints(text: str) -> dict[str, str]:
    hints: dict[str, str] = {}
    for key in [
        "Initialization",
        "Value",
        "UpperLimit",
        "LowerLimit",
        "SampleTime",
        "VariableName",
        "MaskVariables",
        "MaskDescription",
    ]:
        matches = _unique(re.findall(rf'{key}\s+"([^"]+)"', text))
        for index, value in enumerate(matches[:8]):
            hints[f"{key}_{index + 1}"] = value.replace("\n", " ")[:240]
    return hints


def _infer_role(path: Path) -> str:
    name = path.stem.lower()
    rel = str(path).lower()
    if "findmpp" in name:
        return "mpp extraction script"
    if "buck_boost" in name or "buck-boost" in rel:
        return "converter reference model"
    if "mppt" in name:
        return "mppt controller and pv system model"
    if "array" in name:
        return "pv array model"
    if "module" in name:
        return "pv module model"
    if "cell_effect" in name or "varying" in name:
        return "pv cell parameter sensitivity model"
    if "cell_model" in name:
        return "pv cell model"
    return "model source"


def _infer_simulator_family(text: str) -> str:
    if "powerlib/" in text or "fl_lib/" in text:
        return "block diagram with physical/electrical libraries"
    return "block diagram"


def _write_audit_outputs(payload: dict[str, object], output_dir: Path) -> None:
    output_dir = ensure_dir(output_dir)
    write_json(output_dir / "inventory.json", payload)
    rows = payload["model_assets"]
    assert isinstance(rows, list)
    replacement_rows = payload["python_replacement_map"]
    assert isinstance(replacement_rows, list)
    with (output_dir / "model_assets.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "path",
                "suffix",
                "role",
                "simulator_family",
                "stop_time_s",
                "solver",
                "output_variables",
                "source_blocks",
            ],
        )
        writer.writeheader()
        for row in rows:
            assert isinstance(row, dict)
            writer.writerow(
                {
                    **{key: row.get(key) for key in writer.fieldnames},
                    "output_variables": "; ".join(row.get("output_variables", [])),
                    "source_blocks": "; ".join(row.get("source_blocks", [])),
                }
            )
    summary = payload["summary"]
    assert isinstance(summary, dict)
    lines = [
        "# Model Inventory",
        "",
        "This audit separates runnable model sources from generated/cache files and document/media references.",
        "",
        "## Summary",
        "",
        f"- Total files: {summary['total_files']}",
        f"- Runnable model assets: {summary['model_asset_count']}",
        f"- MDL files: {summary['mdl_count']}",
        f"- SLX files: {summary['slx_count']}",
        f"- M scripts: {summary['matlab_script_count']}",
        "",
        "## Runnable Model Assets",
        "",
    ]
    for row in rows:
        assert isinstance(row, dict)
        lines.append(
            f"- `{row['path']}`: {row['role']} ({row['simulator_family']})"
        )
    lines.extend(["", "## Python Replacement Map", ""])
    for row in replacement_rows:
        assert isinstance(row, dict)
        lines.append(
            f"- `{row['model_asset']}` -> `{row['python_command']}`; outputs: "
            + ", ".join(f"`{item}`" for item in row["generated_outputs"])
        )
    (output_dir / "inventory.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _read_text(path: Path) -> str:
    return path.read_text(errors="ignore")


def _first(pattern: str, text: str) -> str | None:
    match = re.search(pattern, text)
    return match.group(1) if match else None


def _xml_param_text(xml_text: str, name: str) -> str | None:
    match = re.search(rf'<P Name="{re.escape(name)}">([^<]*)</P>', xml_text)
    return match.group(1) if match else None


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        clean = value.replace("\n", " ").strip()
        if clean and clean not in seen:
            seen.add(clean)
            result.append(clean)
    return result
