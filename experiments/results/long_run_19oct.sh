#!/bin/bash
# Long evaluation block started 19 Oct 2026: core rounds 5-20, then extra rounds 2-10.
# Retries a block after an Abort (exit 1); stops on Ctrl+C / kill (exit 130).
set -o pipefail
cd "/Users/shayaan/Desktop/intellegent devops"
block() {  # $1 = log file, rest = run_eval args
  log=$1; shift
  for i in 1 2 3 4 5; do
    echo "=== $(date -u +%FT%TZ) attempt $i: run_eval.py run $* ===" | tee -a "$log"
    python3 -u experiments/run_eval.py run "$@" 2>&1 | tee -a "$log"
    rc=$?
    [ $rc -eq 0 ] && return 0
    [ $rc -eq 130 ] && { echo "=== interrupted, stopping ===" | tee -a "$log"; exit 130; }
    echo "=== exit $rc, retrying in 600 s ===" | tee -a "$log"; sleep 600
  done
  echo "=== gave up after 5 attempts ===" | tee -a "$log"; exit 1
}
block experiments/results/eval_core_r5-20_console.log --stage 3
block experiments/results/eval_extra_r2-10_console.log --suite extra --stage 3
echo "=== $(date -u +%FT%TZ) all done ==="
