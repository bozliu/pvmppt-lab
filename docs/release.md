# Public Release SOP

## Product Positioning

`pvmppt-lab` is B2B/B2Pro engineering infrastructure. It helps practitioners run repeatable PV module, converter, and MPPT experiments with generated, reviewable evidence.

Primary users:

- Power-electronics engineers validating controller behavior.
- PV R&D teams comparing module, converter, and controller assumptions.
- Technical consultants producing auditable experiment evidence.
- Training labs and educators needing a reusable PV/MPPT SOP.

The product should not be positioned as consumer solar advice or as a full PV plant design/proposal platform.

## MVP Workflows

1. Inventory local model assets and separate them from documents, media, and generated caches.
2. Design PV modules from datasheet-style YAML specs with Python-generated I-V/P-V curves, MPP tables, sensitivity data, array scaling, and reports.
3. Replace PV cell/module/array I-V and P-V workflows with Python-generated curves, MPP tables, and parameter sweeps.
4. Reproduce buck-boost reference calculations and P&O MPPT fixed/dynamic traces.
5. Run static/dynamic demo benchmarks for compact public evidence.
6. Export CSV, plots, metrics JSON, and Markdown/HTML reports.
7. Generate GIF/MP4 animations through `mpl-animator` from the same run data.
8. Generate README visuals from the same Python animation and plotting layer.
9. Run tests and release checks in CI before publishing.
10. Export a clean GitHub-ready tree from the manifest.

## Public Release Manifest

Include:

- `pyproject.toml`
- `.gitignore`
- `.github/workflows/ci.yml`
- `README.md`
- `LICENSE`
- `THIRD_PARTY_NOTICES.md`
- `docs/`
- `examples/`
- `src/`
- `tests/`
- Generated README assets under `docs/assets/`.

Exclude unless explicitly reviewed:

- Private source folders and local task memory.
- Third-party model, document, media, archive, and runtime-cache inputs.
- Generated run directories except reviewed README assets.

The machine-readable manifest is [public-release-manifest.json](public-release-manifest.json).

To create a fresh publishable repo locally:

```bash
conda run -n dl python -m pvmppt_lab.cli export-public --output runs/public-release/pvmppt-lab --init-git
```

## Pre-Release Audit

Run:

```bash
conda run -n dl pytest
conda run -n dl python -m pvmppt_lab.cli design-module --spec docs/examples/trina-module.yaml --output runs/design
conda run -n dl python -m pvmppt_lab.cli validate-module --spec docs/examples/trina-module.yaml --backend internal --output runs/validation
conda run -n dl python -m pvmppt_lab.cli fit-module --datasheet docs/examples/trina-module.yaml --method desoto --output runs/fitted
conda run -n dl python -m pvmppt_lab.cli audit-models --output runs/model-audit
conda run -n dl python -m pvmppt_lab.cli reproduce --suite all --output runs/reproduction
conda run -n dl python -m pvmppt_lab.cli report --run-dir runs/reproduction
conda run -n dl python -m pvmppt_lab.cli compare --output runs/comparison-demo
conda run -n dl python -m pvmppt_lab.cli report --run-dir runs/comparison-demo
conda run -n dl python -m pvmppt_lab.cli animate --preset all --run-dir runs/comparison-demo --output-dir runs/comparison-demo/animations
conda run -n dl python -m pvmppt_lab.cli build-readme-assets --run-dir runs/comparison-demo --output-dir docs/assets
conda run -n dl python -m pvmppt_lab.cli release-check
conda run -n dl python -m pvmppt_lab.cli export-public --output runs/public-release/pvmppt-lab --init-git
git status --short
```

Review:

- README states the commercial buyer, value, workflow, benchmark, and limits.
- Datasheet-driven design artifacts include `design_summary.json`, `iv_pv_curves.csv`, `mpp_table.csv`, `sensitivity.csv`, plots, and a report.
- Reproduction artifacts include all suites: PV cell, PV module, PV array, MPPT, and converter.
- Metrics, plots, and animations are generated from code and CSV/JSON artifacts.
- README hero GIF has clean, non-overlapping title/subtitle text and a generated contact sheet for visual review.
- Animation manifests name `mpl-animator` as the backend; MP4 output is optional and requires `ffmpeg`.
- No private source context or local paths appear in the clean release manifest.
- Third-party notices are present.
