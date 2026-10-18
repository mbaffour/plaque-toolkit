# Frozen record of Plaque Toolkit v1.1.0

This folder is the in-repo freeze of the version released on 2026-10-13. It does **not**
copy the source (the tag does that); it records what the source *was* and what numbers it
*produced*, so any later change can be checked against it.

| Item | Value |
|---|---|
| Tag | `v1.1.0` (annotated) |
| Commit | `cd7b75b` |
| Branch pointer | `release/v1.1.0` (same commit; never move it) |
| GitHub Release | https://github.com/mbaffour/plaque-toolkit/releases/tag/v1.1.0 |
| macOS asset | `PlaqueToolkit-1.1.0-macos-arm64.dmg`, SHA-256 `c87c55fe3e669da18ada8b788cec16777ab05e0221036601c9e5a225686671ee` |
| Version string | `_version.py` → `1.1.0` |
| Frozen on | 2026-10-18 |

## Files here

| File | What it is |
|---|---|
| `SHA256SUMS-source.txt` | SHA-256 of all 291 files in `git archive v1.1.0`. Proves a checkout is the frozen source. |
| `SHA256SUMS-baseline-outputs.txt` | SHA-256 of the 99 CSV/JSON outputs v1.1.0 produced on the bundled `Test_plates` in every engine mode (below). The regression oracle. |
| `requirements-frozen.txt` | Exact library versions that produced those outputs. |
| `run_baseline.sh` | The commands that produced them, so they can be re-run. |

## Baseline runs recorded

`plaque_size_tool.py` on `Test_plates/large` (`-p 90`, 10 plates) and `Test_plates/small`
(`-p 55`, 7 plates) in five modes: default (Current), `-published`, `--upstream-exact`,
`-sensitive`, `-watershed`; `summarize_plates.py` on the two Current runs;
`plaque_turbidity.py` on both folders in default and `--published` mode
(`--no-overlay --no-plots`). `run_metadata.json` files are excluded from the checksums
because they record the platform and library versions.

| Run | Files recorded |
|---|---|
| `size/large-current` | 11 |
| `size/large-published` | 10 |
| `size/large-sensitive` | 10 |
| `size/large-upstream` | 10 |
| `size/large-watershed` | 10 |
| `size/small-current` | 8 |
| `size/small-published` | 7 |
| `size/small-sensitive` | 7 |
| `size/small-upstream` | 7 |
| `size/small-watershed` | 7 |
| `turbidity/large-current` | 3 |
| `turbidity/large-published` | 3 |
| `turbidity/small-current` | 3 |
| `turbidity/small-published` | 3 |

## How to get the frozen source back

```bash
git checkout v1.1.0                      # or: git checkout release/v1.1.0
git archive v1.1.0 -o plaque-toolkit-1.1.0.tar   # a tarball of exactly this version
```

## How to check that a change did not move a number

```bash
REPO=/path/to/checkout SCRATCH=/tmp/pt-check VENV_PY=/path/to/python releases/v1.1.0/run_baseline.sh
cd /tmp/pt-check/baseline-v1.1.0 && shasum -a 256 -c /path/to/checkout/releases/v1.1.0/SHA256SUMS-baseline-outputs.txt
```

Any line that fails is a measurement or output that changed. Under the repo's honesty policy
(`CHANGELOG.md`) a change to a Published-mode line needs a "Numbers that change" entry.
