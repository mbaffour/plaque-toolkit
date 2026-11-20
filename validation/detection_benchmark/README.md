# Detection benchmark (frozen, CT-R2 detection)

**What it measures.** For each detection mode (`standard` = CLI default, `small` = CLI `-small`, `auto` = the app's Auto) and each Auto sizing rule (`auto` = the code as it is, `r1` = the round-1 rule, `S`, `S+`), on synthetic scenes with known diameters: detection rate, and for the SIZED rows the median bias, the share beyond +-5 % and the worst bias, plus the share of detected plaques that are sized. On the bundled plates: plaques / sized / median mm per plate, size_ok and class switches under +-1 % gain, and the sized median's shift under 13 benign perturbations (`perturb.py`).

**How to run.** `python validation/detection_benchmark/score.py --out <folder>` (about 25 min; `--parts synth,split` takes 2 min). Detections are cached in `<folder>/raw/`; results go to `scorecard.csv`, `plates.csv` and the `*_rows.csv` files. `standard_range.py --out <folder>` sweeps the pixel range the standard pass outlines well (Part 3).

**The scenes are frozen.** `scenes.py` and `perturb.py` are the round-2 tester's scenes and perturbations exactly as written (fixed seeds; Auto reproduces the tester's c_synth.csv and c_split.csv row for row). Do not edit, add or drop a scene: every rule before this one was fitted to a few plates and failed the next independent test, so the scenes must stay out of reach of tuning. Add new scenes only as a new, separately named group.

**Decision rule (fixed before scoring candidates).** A candidate beats today's rule if, pooled over ALL synth + split scene rows, its share of sized rows beyond +-5 % is not higher AND its size_ok switches at gain +-1 % (6 plates) are not more, with at least one strictly better; if the two disagree it does not beat it. It must also keep every bundled plate's sized median within 5 % of the CLI default's median on the plaques both size (of `-small`'s for plates it treats as small-plaque plates); a plate with nothing to compare passes but is reported. Ties go to fewer mechanisms.

`tests/test_ct_r2_detection.py` pins a few headline numbers (under 30 s).
