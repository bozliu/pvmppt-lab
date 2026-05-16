from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import re
import shutil
import subprocess


PUBLIC_RELEASE_PATHS = [
    ".gitignore",
    ".github",
    "pyproject.toml",
    "README.md",
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
    "docs",
    "examples",
    "src",
    "tests",
]

PRIVATE_PATH_PARTS = [
    "Prompt.md",
    "Plan.md",
    "Implement.md",
    "Documentation.md",
    ".omx",
    "runs",
    "slprj",
]

PUBLIC_EXCLUDED_REL_PATHS = {
    "src/pvmppt_lab/legacy.py",
    "tests/test_legacy.py",
}

PUBLIC_EXCLUSION_SUMMARY = [
    "private source folders",
    "local task memory",
    "generated run outputs",
    "third-party model/media inputs",
]

BLOCKED_SUFFIXES = {
    ".doc",
    ".docx",
    ".jpeg",
    ".gif",
    ".jpg",
    ".m4a",
    ".mdl",
    ".mov",
    ".mp3",
    ".mp4",
    ".pdf",
    ".png",
    ".ppt",
    ".pptx",
    ".slx",
    ".wav",
}

GENERATED_ASSET_SUFFIXES = {".gif", ".png"}

SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"OPENAI_API_KEY\s*="),
    re.compile(r"AIza[0-9A-Za-z_-]{20,}"),
    re.compile(r"ghp_[0-9A-Za-z_]{20,}"),
    re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----"),
]

def _literal_pattern(*parts: str) -> re.Pattern[str]:
    return re.compile(re.escape("".join(parts)), re.IGNORECASE)


PUBLIC_TEXT_PATTERNS = [
    re.compile(r"\b" + "20" + "19" + r"\b", re.IGNORECASE),
    _literal_pattern("\u8bba", "\u6587"),
    _literal_pattern("\u8f85", "\u5bfc"),
    _literal_pattern("\u8c22", "\u83f2", "\u5c14", "\u5fb7"),
    _literal_pattern("Shef", "field"),
    _literal_pattern("/", "Users", "/", "boz", "liu"),
    re.compile(r"\b" + "stu" + "dent" + r"\b", re.IGNORECASE),
    re.compile(r"\b" + "course" + "work" + r"\b", re.IGNORECASE),
    re.compile(r"\b" + "tu" + "tor" + r"\b", re.IGNORECASE),
    re.compile(r"\b" + "original" + "ity" + r"\b", re.IGNORECASE),
    re.compile(r"\b" + "screen" + "shot" + r"s?\b", re.IGNORECASE),
]

GENERATED_PARTS = {
    ".git",
    ".omx",
    ".pytest_cache",
    "__pycache__",
    "runs",
    "slprj",
}


@dataclass(frozen=True)
class ReleaseScan:
    status: str
    missing_required_paths: list[str]
    public_release_manifest: list[str]
    excluded_private_inputs: list[str]
    included_file_count: int
    included_files: list[str]
    blocked_path_hits: list[str]
    sensitive_text_hits: list[str]
    broken_readme_asset_links: list[str]
    note: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _iter_manifest_files(root: Path) -> list[Path]:
    files: list[Path] = []
    seen: set[Path] = set()
    for item in PUBLIC_RELEASE_PATHS:
        path = root / item
        if path.is_file():
            if path not in seen:
                files.append(path)
                seen.add(path)
            continue
        if not path.is_dir():
            continue
        for child in path.rglob("*"):
            if not child.is_file():
                continue
            rel = str(child.relative_to(root))
            rel_parts = set(child.relative_to(root).parts)
            if rel_parts & GENERATED_PARTS:
                continue
            if rel in PUBLIC_EXCLUDED_REL_PATHS:
                continue
            if any(part.endswith(".egg-info") for part in child.parts):
                continue
            if child.suffix == ".pyc" or child.name == ".DS_Store":
                continue
            if child not in seen:
                files.append(child)
                seen.add(child)
    return sorted(files)


def scan_public_release(root: Path) -> ReleaseScan:
    root = root.resolve()
    missing = [item for item in PUBLIC_RELEASE_PATHS if not (root / item).exists()]
    files = _iter_manifest_files(root)
    rel_files = [str(path.relative_to(root)) for path in files]

    blocked_hits = [
        rel
        for rel in rel_files
        if _is_blocked_public_path(Path(rel))
    ]

    sensitive_hits: list[str] = []
    for path, rel in zip(files, rel_files):
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".pdf"}:
            continue
        try:
            text = path.read_text(errors="ignore")
        except OSError:
            continue
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                sensitive_hits.append(rel)
                break
        else:
            for pattern in PUBLIC_TEXT_PATTERNS:
                if pattern.search(text):
                    sensitive_hits.append(rel)
                    break

    broken_readme_asset_links = _find_broken_readme_asset_links(root)
    status = (
        "pass"
        if not missing and not blocked_hits and not sensitive_hits and not broken_readme_asset_links
        else "fail"
    )
    return ReleaseScan(
        status=status,
        missing_required_paths=missing,
        public_release_manifest=PUBLIC_RELEASE_PATHS,
        excluded_private_inputs=PUBLIC_EXCLUSION_SUMMARY,
        included_file_count=len(files),
        included_files=rel_files,
        blocked_path_hits=blocked_hits,
        sensitive_text_hits=sensitive_hits,
        broken_readme_asset_links=broken_readme_asset_links,
        note="Publish only this clean, generated export payload to GitHub.",
    )


def _is_blocked_public_path(rel: Path) -> bool:
    suffix = rel.suffix.lower()
    if str(rel).startswith("docs/assets/") and suffix in GENERATED_ASSET_SUFFIXES:
        return False
    return suffix in BLOCKED_SUFFIXES or any(part in PRIVATE_PATH_PARTS for part in rel.parts)


def _find_broken_readme_asset_links(root: Path) -> list[str]:
    readme = root / "README.md"
    if not readme.exists():
        return []
    text = readme.read_text(encoding="utf-8", errors="ignore")
    links = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", text)
    broken: list[str] = []
    for link in links:
        target = link.split("#", 1)[0].split("?", 1)[0].strip()
        if not target or re.match(r"^[a-z]+://", target, re.IGNORECASE):
            continue
        if not (root / target).exists():
            broken.append(link)
    return broken


def export_public_release(
    root: Path, output_dir: Path, init_git: bool = False
) -> ReleaseScan:
    scan = scan_public_release(root)
    if scan.status != "pass":
        return scan

    root = root.resolve()
    output_dir = output_dir.resolve()
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    for item in PUBLIC_RELEASE_PATHS:
        source = root / item
        target = output_dir / item
        if source.is_dir():
            shutil.copytree(
                source,
                target,
                ignore=shutil.ignore_patterns(
                    "__pycache__",
                    "*.pyc",
                    "*.egg-info",
                    ".DS_Store",
                    "legacy.py",
                    "test_legacy.py",
                ),
            )
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

    exported_scan = scan_public_release(output_dir)
    if init_git and exported_scan.status == "pass":
        _init_git_repo(output_dir)
    return scan_public_release(output_dir)


def _init_git_repo(output_dir: Path) -> None:
    commands = [
        ["git", "init"],
        ["git", "config", "user.name", "pvmppt-lab release bot"],
        ["git", "config", "user.email", "release@example.invalid"],
        ["git", "add", "."],
        ["git", "commit", "-m", "Initial public pvmppt-lab release"],
    ]
    for command in commands:
        subprocess.run(command, cwd=output_dir, check=True, capture_output=True, text=True)
