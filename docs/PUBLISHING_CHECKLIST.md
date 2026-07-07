# Publishing checklist — Plaque Toolkit

A practical, tailored checklist for getting work that uses this tool through peer review.
Your situation: **the tool produces data for a figure in a paper you're writing now**, you want
**minimal (local) validation** for that, and you may grow it into a **standalone "resource" paper later**.
So this is split into **Track 1 (now)** and **Track 2 (later)**.

See also: [METHODS_TEMPLATE.md](METHODS_TEMPLATE.md) (ready-to-adapt Methods prose),
[VALIDATION_GUIDE.md](VALIDATION_GUIDE.md) (how to validate on your plates),
[PUBLICATION.md](PUBLICATION.md) (what is / isn't defensible),
[CREDITS_AND_LINEAGE.md](CREDITS_AND_LINEAGE.md) (what to cite).

---

## Track 1 — NOW: use the tool as a *method* in your current paper

You do **not** need to publish the tool to use it. Treat it like any instrument: describe it, validate it
locally, cite it. Roughly a day of work.

### 1. Local validation for the figure  *(this is the “minimal” validation)*
- [ ] Correct **≥ 5–9 plates** by hand in the editor (spanning sparse → dense), then **Export → Ground-truth labels**.
- [ ] Run the **Validate** tab on that label folder → record, per engine: **precision, recall, F1** (per-plate mean ± 95% CI).
- [ ] **Size agreement** on matched plaques: Bland–Altman bias + 95% limits of agreement, and/or ICC vs manual Fiji diameters.
- [ ] **Negative control**: run a few **uninfected-lawn** plates → report the false-positive count (`_research/neg_control.py` or the app).
- [ ] Decide the engine for the paper: **Published** (citable-as-validated) *or* **Precise** (report the local numbers above).

### 2. Calibration & imaging (say these in Methods)
- [ ] Calibrate to the **agar** diameter (or an in-frame ruler) — **not the lid**. State the value (e.g. 85 mm, ~0.040 mm/px).
- [ ] Image **straight-on**; discard/reshoot tilted plates (the app warns at axis-ratio > 1.03).
- [ ] State that “plaque size” = **convex-hull area-equivalent diameter** (`d = 2√(area/π)`), **halo-inclusive** (an upper bound).

### 3. Statistics (the #1 reviewer trap)
- [ ] **Plate = biological replicate, not the plaque.** Aggregate per-plaque values to **per-plate means/medians** first.
- [ ] **≥ 3 plates per condition**; compare with non-parametric tests (Mann–Whitney / Kruskal–Wallis) or a mixed model with plate as a random effect.
- [ ] Never treat individual plaques as independent *n* (pseudoreplication inflates significance).

### 4. Write it up
- [ ] Paste and fill the **Methods** paragraph from [METHODS_TEMPLATE.md](METHODS_TEMPLATE.md) (imaging → calibration → engine → size definition → your validation numbers).
- [ ] **Cite**: the tool (via DOI, below) **+** Plaque Size Tool (Trofimova & Jaschke, *Virology* 2021, doi:10.1016/j.virol.2021.05.011) **+** PlaqSeg/OnePetri if you used Precise.
- [ ] Keep the honest caveat: Sensitive/Precise are in-house, not independently validated.

### 5. Make the tool citable (get a DOI) — 4 clicks, do once
1. On GitHub: **Releases → Draft a new release**, tag `v1.0.0`, publish.
2. Go to **https://zenodo.org** → log in with GitHub → **Settings → GitHub** → flip the switch **ON** for `mbaffour/plaque-toolkit`.
3. (Zenodo only archives releases created *after* the switch is on — so create/re-publish the release *after* step 2.)
4. Zenodo mints a **DOI**. Paste it into `CITATION.cff` (`doi:` line) and cite that DOI in your paper.
- [ ] DOI obtained and added to `CITATION.cff`.
- [ ] Confirm author list + affiliations + ORCID iDs in `CITATION.cff`.

### 6. Data / code availability statement
- [ ] “Analysis used Plaque Toolkit vX (DOI …), source at github.com/mbaffour/plaque-toolkit (Apache-2.0).”
- [ ] Deposit the **raw plate images + your ground-truth labels + per-plate CSVs** (Zenodo/Figshare) so the figure is reproducible.

---

## Track 2 — LATER: a standalone / “resource” paper about the tool

Only when you want the tool itself to be the contribution. Pick the venue by how much benchmarking you'll do.

### Novelty framing (answer this up front)
- [ ] State clearly what is **new** vs prior art: the **PST + PlaqSeg fusion**, the mm-calibration workflow, the correction editor, turbidity/OD, batch, Fiji-calibrated crops, cross-platform packaging. (Pre-empt the “thin wrapper” critique.)

### Rigorous validation / benchmarking  *(the real gate for a strong software paper)*
- [ ] A **blinded, hand-labelled benchmark dataset** (dozens of plates; ideally deposited publicly).
- [ ] **Head-to-head** vs **PST**, **OnePetri/PlaqSeg**, and **ImageJ/Fiji** on the same plates (precision/recall/F1 + size agreement).
- [ ] **Generalization**: ≥ 1 independent camera/lighting/strain — or state the limitation loudly.

### Reproducibility / open-source  *(you're ~80% here already ✓)*
- [x] Public repo, OSI license (Apache-2.0), extensive docs (guide, **Tool Atlas**, methods, validation, credits), cross-platform installers, macOS build CI.
- [ ] **Automated tests wired into CI** (you have `plaque_app.py --uitest`, `--smoke`, `_research/full_test.py`; add a GitHub Actions test workflow that runs them on push).
- [ ] `CITATION.cff` ✓ (added) · add `CONTRIBUTING.md` · a Zenodo DOI (above).

### Venue options
| Venue | Bar | Good if |
|---|---|---|
| **JOSS** (Journal of Open Source Software) | Software quality/docs/tests, **not** novelty of results | You want a citable DOI with the least friction. Needs a ~1-page `paper.md` + tests in CI. |
| **PeerJ / BMC Bioinformatics / Bioinformatics (Application Note)** | Novelty **+** benchmarking vs existing tools | You've done the Track-2 benchmarking and want a conventional paper. |
| **Resource/methods section of your biology paper** | Local validation | You fold the tool into the biology paper (your current plan). |

---

## The honest gates (what a reviewer *will* catch)
1. **Only “Published” mode is peer-reviewed.** Any claim from Current/Sensitive/**Precise** needs *your own* reported validation. Don’t call Precise “a validated method.”
2. **Pseudoreplication** — aggregate to the plate.
3. **Calibration to the lid instead of the agar** — silently scales every size; use the agar (or a ruler).
4. **Halo-inclusive size** — state it; it’s an upper bound on the sharp clear zone.
5. **Turbidity from phone photos is *apparent* OD** — screening-grade, not absolute; caveat it.
6. **PlaqSeg is not peer-reviewed** — cite its lineage (OnePetri) and treat it as in-house.
