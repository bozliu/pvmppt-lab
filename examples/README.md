# Examples

Run the full engineering-model reproduction workflow:

```bash
conda run -n dl python -m pvmppt_lab.cli design-module --spec docs/examples/trina-module.yaml --output runs/design
conda run -n dl python -m pvmppt_lab.cli validate-module --spec docs/examples/trina-module.yaml --backend internal --output runs/validation
conda run -n dl python -m pvmppt_lab.cli fit-module --datasheet docs/examples/trina-module.yaml --method desoto --output runs/fitted
conda run -n dl python -m pvmppt_lab.cli audit-models --output runs/model-audit
conda run -n dl python -m pvmppt_lab.cli reproduce --suite all --output runs/reproduction
conda run -n dl python -m pvmppt_lab.cli report --run-dir runs/reproduction
```

Run the compact public comparison workflow:

```bash
conda run -n dl python -m pvmppt_lab.cli compare --output runs/comparison-demo
conda run -n dl python -m pvmppt_lab.cli report --run-dir runs/comparison-demo
conda run -n dl python -m pvmppt_lab.cli animate --preset all --run-dir runs/comparison-demo --output-dir runs/comparison-demo/animations
conda run -n dl python -m pvmppt_lab.cli build-readme-assets --run-dir runs/comparison-demo --output-dir docs/assets
```

Animate a standalone matplotlib script:

```bash
mpl-animator my_plot.py --var freq --range "1,50" --frames 60 --out my_plot.gif
conda run -n dl python -m pvmppt_lab.cli animate-script my_plot.py --var freq --range "1,50" --frames 60 --format gif --out runs/my_plot.gif
```

Expected outputs:

- `runs/comparison-demo/static/static_curves.csv`
- `runs/comparison-demo/static/static_mpp.csv`
- `runs/comparison-demo/static/*.png`
- `runs/comparison-demo/mppt/mppt_trace.csv`
- `runs/comparison-demo/mppt/*.png`
- `runs/comparison-demo/comparison_metrics.json`
- `runs/comparison-demo/report.md`
- `runs/comparison-demo/report.html`
- `runs/comparison-demo/animations/animation_manifest.json`
- `runs/comparison-demo/animations/*.gif`
- `docs/assets/pvmppt-lab-hero.gif`
- `docs/assets/pvmppt-lab-hero-contact-sheet.png`
- `docs/assets/pvmppt-lab-pv-curves.png`
- `docs/assets/pvmppt-lab-mppt-power.png`
- `runs/design/design_summary.json`
- `runs/design/iv_pv_curves.csv`
- `runs/design/mpp_table.csv`
- `runs/design/sensitivity.csv`
- `runs/design/design_report.md`
- `runs/model-audit/inventory.json`
- `runs/reproduction/summary.json`
- `runs/reproduction/report.md`
