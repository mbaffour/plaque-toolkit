#!/bin/bash
# Re-run the v1.1.0 baseline. Set REPO (checkout of v1.1.0), SCRATCH (empty work dir), and
# VENV_PY (interpreter with requirements-frozen.txt installed), then diff the CSVs against
# SHA256SUMS-baseline-outputs.txt.
: "${REPO:?}" "${SCRATCH:?}" "${VENV_PY:?}"
set -u
S="$SCRATCH"; R="$REPO"; V="$VENV_PY"; B="$SCRATCH/baseline-v1.1.0"
run_size() { # name folder plate extra...
  name=$1; folder=$2; plate=$3; shift 3
  mkdir -p "$B/size/$name" && cd "$B/size/$name" || exit 1
  "$V" "$R/plaque_size_tool.py" -d "$R/Test_plates/$folder" -p "$plate" "$@" > run.log 2>&1
  echo "size/$name exit=$? csvs=$(ls out/data-green-*.csv 2>/dev/null | wc -l | tr -d ' ')"
}
run_size large-current   large 90
run_size large-published large 90 -published
run_size large-upstream  large 90 --upstream-exact
run_size large-sensitive large 90 -sensitive
run_size large-watershed large 90 -watershed
run_size small-current   small 55
run_size small-published small 55 -published
run_size small-upstream  small 55 --upstream-exact
run_size small-sensitive small 55 -sensitive
run_size small-watershed small 55 -watershed
run_turb() { name=$1; folder=$2; plate=$3; shift 3
  mkdir -p "$B/turbidity/$name" && cd "$B/turbidity/$name" || exit 1
  "$V" "$R/plaque_turbidity.py" -d "$R/Test_plates/$folder" -p "$plate" -o out --no-overlay --no-plots "$@" > run.log 2>&1
  echo "turbidity/$name exit=$? files=$(find out -type f 2>/dev/null | wc -l | tr -d ' ')"
}
run_turb large-current   large 90
run_turb large-published large 90 --published
run_turb small-current   small 55
run_turb small-published small 55 --published
# summarize_plates on the current-mode outputs
cd "$B/size/large-current" && "$V" "$R/summarize_plates.py" -o out -i "$R/Test_plates/large" > summarize.log 2>&1; echo "summarize large exit=$?"
cd "$B/size/small-current" && "$V" "$R/summarize_plates.py" -o out -i "$R/Test_plates/small" > summarize.log 2>&1; echo "summarize small exit=$?"
echo BASELINE_DONE
