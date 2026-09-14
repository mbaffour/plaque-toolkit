# Changelog

All notable changes to the Plaque Toolkit. The version lives in `_version.py`
(one source of truth — see `AUDIT-2026-09.md`, PT-13).

**Honesty policy for this file.** Any release that changes a *measurement number*
says so explicitly, under a "Numbers that change" heading, naming the engine and
the conditions. A release with no such heading changed no number.

---

## 1.1.0 — 2026-09-14

The 2026-09 audit release. Every change below is traceable to a finding in
[`AUDIT-2026-09.md`](AUDIT-2026-09.md).

### Numbers that change

* **Turbidity OD on 16-bit input (PT-2).** `plaque_turbidity.py` used to truncate a
  16-bit linear TIFF to 8 bits and then apply an inverse-sRGB gamma unconditionally.
  Such input is now read at native depth and linearised according to what the file
  actually is, which corrects errors of **0.53–0.89 OD**. Runs on ordinary 8-bit
  sRGB photographs are unaffected. Any previously recorded OD from a 16-bit linear
  capture should be re-measured.
* **Agreement report wording (PT-4).** The "paste-ready" manuscript sentence is now
  derived from the statistics instead of hard-coding "closely agreed / highly
  correlated". Reports whose statistics did not support the old adjectives now read
  differently. No statistic changed — only the sentence describing it.

**No size-measurement number changes in this release.** `plaque_size_tool.py`'s
default (Current) and `--published` outputs are byte-for-byte identical to 1.0.x on
the bundled `Test_plates` set, in both modes; this was verified by diffing every
`data-green-*.csv` against the pre-audit code.

### Added

* `--upstream-exact` on `plaque_size_tool.py` (PT-1): a bit-for-bit reproduction of
  the *original* upstream read path — red-channel `ImageStat` brightness gate, lossy
  temp-file dimming, no EXIF transpose — for reproducing a number the upstream tool
  itself produced. Implies `--published`. Opt-in; the Published default is unchanged
  and the decision to flip it belongs to the maintainer (see AUDIT-2026-09.md →
  "Owner decisions"). Documented in `docs/UPSTREAM_EXACT.md`.
* `run_metadata.json` beside every size CSV (PT-9), written by the new
  `provenance.py` from both `plaque_size_tool.py` and `app/batch_measure.py`:
  engine name, the settings used, toolkit version, library versions, and a per-image
  digest, count, brightness and mm/px. Purely additive — no measurement column moved.
* A real automated test suite (`tests/`, pytest) covering PT-1 through PT-6 and PT-9,
  plus a `Tests` GitHub Actions workflow that runs it and `--smoke` (PT-7, partial).
* `find_python.bat` (PT-5): runtime interpreter resolution for every Windows launcher.
* `_version.py` (PT-13): the single source of truth for the version.

### Changed

* Zero-plaque plates now always write a header-only CSV and stay in `summary.csv`
  with `N_PLAQUES = 0` (PT-3). Previously they wrote nothing and vanished from the
  summary, biasing every mean count and titer upward and silently defeating the
  negative-control protocol.
* `--precise-smoke` is a gate that can actually fail (PT-6): it now requires
  `n_final >= PRECISE_SMOKE_MIN` (default 1) *and* that the overlay was written, and
  exits non-zero otherwise. `build_macos.sh` checks both the exit status and the
  verdict line.
* Every launcher resolves Python at run time instead of hard-coding the author's own
  `C:\Users\...` path (PT-5).
* Versions reconciled to `1.1.0` across `pyproject.toml`, `setup.py`, `app/__init__.py`,
  the engine modules and `CITATION.cff` (PT-13). `pyproject.toml` gained a real
  `[project]` table.
* `plaque_turbidity.py`'s `run_metadata.json` now reports the toolkit version that
  produced the data rather than a stale hand-maintained module string (PT-9/PT-13).
* The matplotlib floor is `>=3.9` in `requirements.txt` and `environment.yml` too, not
  just in `pyproject.toml`/`setup.py` (PT-10). On 3.5–3.8 the turbidity comparison
  plots raised `TypeError` inside a broad `except` and were silently skipped while the
  run still reported success.

### Known issues

See `AUDIT-2026-09.md` for the full disposition of all 22 findings, including the
ones deliberately left open (PT-8, PT-10 through PT-12, PT-14 through PT-22) and the
maintainer decisions that are not the toolkit's to make.

---

## 1.0.x and earlier

Not tracked in this file. See the git history and `docs/HOW_IT_WAS_BUILT.md`.
