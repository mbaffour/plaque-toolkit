# Documentation index

Everything documenting the **Plaque Toolkit** lives in this folder. It is intentionally kept
**flat** — the desktop app opens several of these files by name from its Help menu, and the
installers bundle the whole `docs/` folder, so files are not moved into subfolders. Use this
index (and [`STRUCTURE.md`](STRUCTURE.md), the repo map) to navigate.

> New here? Start with the project [README](../README.md), then the [User guide](USER_GUIDE.md).

---

## 1 · Start here (using the tool)
| Doc | What it covers |
|---|---|
| [USER_GUIDE.md](USER_GUIDE.md) | Every task: measure, edit, batch, turbidity, scale bars, outputs, troubleshooting. |
| [INSTALL.md](INSTALL.md) | Install on Windows / macOS / Linux; the two installers; the optional Precise env. |
| [ENGINES.md](ENGINES.md) | The four detection engines in depth and **when to use each** (+ validation status). |
| **Interactive guides** (open in a browser) | [TOOL_ATLAS.html](TOOL_ATLAS.html) · [guide.html](guide.html) · [setup_and_run.html](setup_and_run.html) · [HOWTO_AND_VERIFICATION.html](HOWTO_AND_VERIFICATION.html) |

## 2 · For a paper (methods, validation, reproducibility, AI use)
| Doc | What it covers |
|---|---|
| [MANUSCRIPT_METHODS_AND_AI.md](MANUSCRIPT_METHODS_AND_AI.md) | **Paste-ready** brief Methods paragraph + the use-of-AI statement. |
| [PAPER_METHODS.md](PAPER_METHODS.md) | Full, fully-referenced Methods & Results wording (with your real numbers). |
| [METHODS_TEMPLATE.md](METHODS_TEMPLATE.md) | A fill-in-the-blanks Methods template. |
| [VALIDATION_RESULTS.md](VALIDATION_RESULTS.md) | The authors' own local validation (Precise vs Fiji: ICC 0.97; negative controls; size stats). |
| [TRAINING_AND_MODELS.md](TRAINING_AND_MODELS.md) | **How the models were built and trained** — the classifier, datasets, the fine-tune loop, tuning, and provenance. |
| [PUBLICATION.md](PUBLICATION.md) | The honest validation playbook — what is and isn't citable, and how to validate on your own plates. |
| [PUBLISHING_CHECKLIST.md](PUBLISHING_CHECKLIST.md) | What's still needed before publication. |
| [TESTING_AND_VALIDATION.md](TESTING_AND_VALIDATION.md) | The acceptance gates and validation harness. |
| [VALIDATION_GUIDE.md](VALIDATION_GUIDE.md) · [LABELLING_GUIDE.md](LABELLING_GUIDE.md) | How to validate the tool on your plates, and how to hand-label ground truth. |
| **Figures / interactive** | [plaque_pipeline.svg](plaque_pipeline.svg) (pipeline diagram) · [PlaqueToolkit_vs_Fiji_BlandAltman.png](PlaqueToolkit_vs_Fiji_BlandAltman.png) · [STATS_EXPLAINED.html](STATS_EXPLAINED.html) · [FIJI_VALIDATION_PROTOCOL.html](FIJI_VALIDATION_PROTOCOL.html) · [FIJI_TUTORIAL.html](FIJI_TUTORIAL.html) |

## 3 · How it works & development
| Doc | What it covers |
|---|---|
| [HOW_IT_WAS_BUILT.md](HOW_IT_WAS_BUILT.md) | The build-and-design narrative: origin, architecture, the four engines, honesty. |
| [STRUCTURE.md](STRUCTURE.md) | The repo map — every top-level item and whether it's safe to move. |
| [DEVELOPER.md](DEVELOPER.md) | Two-env vs unified-env design, the ML classifier, rebuilding the installers, acceptance gates. |
| [PLAQUE_SIZE_TOOL.md](PLAQUE_SIZE_TOOL.md) | Focused reference for the core `plaque_size_tool.py` size CLI. |
| [CREDITS_AND_LINEAGE.md](CREDITS_AND_LINEAGE.md) | Lineage and credit to upstream projects (PST, PlaqSeg/OnePetri, datasets). |
| [UPSTREAM_README.md](UPSTREAM_README.md) | The original upstream Plaque Size Tool manual, preserved verbatim. |

## 4 · Related, outside this folder
| Location | What it is |
|---|---|
| [../plaque_stats/README.md](../plaque_stats/README.md) | The standalone **stats & violin** analysis workspace (CLI + R-Shiny + Python-Shiny + frozen app). |
| [../LICENSING.md](../LICENSING.md) · [../THIRD_PARTY_LICENSES.md](../THIRD_PARTY_LICENSES.md) · [../NOTICE](../NOTICE) | Licensing of the toolkit and its third-party components. |
| [../CITATION.cff](../CITATION.cff) | How to cite this software. |

---

*The app's Help menu opens `USER_GUIDE.md`, `VALIDATION_GUIDE.md`, `HOW_IT_WAS_BUILT.md`,
`ENGINES.md`, `PUBLICATION.md`, `CREDITS_AND_LINEAGE.md`, and `LICENSING.md` in-app — so these
filenames must stay put. See [`STRUCTURE.md`](STRUCTURE.md) for what else is load-bearing.*
