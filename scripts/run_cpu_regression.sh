#!/usr/bin/env bash
# Daily CPU regression — full verification stack except milestone-only suites.
#
# Layers (docs/HYBRID_ARCH.md, docs/decisions/005-*.md):
#   1. RefVM (python) vs real lean binary      — semantic ground truth
#   2. ALM step graph vs RefVM / real lean     — graph encodes the semantics
#   3. ENV metadata / level / data-driven cid  — WP1/WP2/WP8 encoding layers
#   4. weights+engine vs RefVM                 — scripts/verify_engine_vs_refvm.py
#      (the dense-Python weight tests test_endtoend_corpus / test_engine_vs_runner
#       / test_weights_fidelity are retired per ADR 005; the C++ engine on the
#       sparse .sbin IS the weight-side acceptance channel, WHNF only)
#
# Execution model (measured 2026-09-14, card 004):
#   - Each suite runs as a transient `systemd-run --user` service with
#     PrivateTmp=yes. Required: reference/lean_ref.py writes FIXED /tmp paths
#     (/tmp/vm_oracle_batch.lean, /tmp/vm_check_case.lean, ...) so any two
#     suites sharing the host /tmp clobber each other's oracle files
#     (measured failure: ref_vs_lean "expected 34 results, got 82" when
#     parallel with ref_infer_defeq). PrivateTmp isolates them for free, and
#     the cgroup teardown guarantees no orphaned vm_run/lean children.
#   - Suites run in a bounded parallel pool (REGRESSION_JOBS, default 3).
#     Serial is ~55 min on this box (measured /tmp/004B_reg1.log); the
#     heartbeat budget is <=20 min. Graph eval is single-threaded python.
#   - Memory discipline (AGENTS.md): every guarded suite runs under
#     scripts/run_mem_guarded.py (RSS poll + process-group kill).
#     2026-09-16 lead retest (docs/handoffs/009-L-wheel-audit.md): cgroup
#     MemoryMax alone IS defeatable by swap on this box (200M cap, 2GB
#     bytearray, rc=0 — the old bare "tested" claim survived only because
#     swap absorbed it), but `-p MemoryMax=N -p MemorySwapMax=N` enforces
#     in-group OOM (rc=137). Kernel-level capping is available and AGENTS
#     makes it the first choice; the user-space guard stays the default
#     here because suites want per-suite caps with peak-RSS in one log line.
#   - No long command is piped. Each suite writes $LOG_DIR/<label>.log and
#     <label>.rc under $HOME/logs (outside the repo; the unit's own /tmp is
#     private, so /tmp cannot host them).
#   - REGRESSION_CORES pins CPU affinity INSIDE the unit (the systemd user
#     manager does not inherit the caller's taskset).
#
# Run: OMP_NUM_THREADS=3 REGRESSION_CORES=14-19 bash scripts/run_cpu_regression.sh
# Env knobs: PYTHON, REGRESSION_LOG_DIR, REGRESSION_JOBS, REGRESSION_CORES,
#            SUITE_FILTER (substring).
#
# MILESTONE NOTES (deliberately NOT in this loop, tracked to the exit gate):
#   - tests/test_iota_graph_vs_lean.py: WP3 large env (4440 consts), warmup
#     exceeds 40 min (boot handoff §3.6; recorded NOT-VERIFIED). Milestone
#     exit only, never here.
#   - scripts/verify_engine_vs_refvm.py pow skip was REMOVED after card 008
#     (REGLU_CLAMP 1e6, 2026-09-15): pow now halts at 348 steps like the
#     symbolic evaluator; lead engine rerun 34/34, E regression engine line
#     33/33 was pre-removal. The full 34-case run stays the milestone-exit
#     command: python3 scripts/verify_engine_vs_refvm.py
set -u
cd "$(dirname "$0")/.."

PY="${PYTHON:-python3}"
# systemd transient units inherit the USER MANAGER's env, not the caller's:
# a bare "python3" inside the unit resolved to /usr/bin/python3 (no numpy on
# this box) and killed 10 suites at once (measured 2026-09-14, reg3 attempt 1).
# Pin PY to an absolute path resolved in the caller before embedding it.
case "$PY" in
    /*) ;;
    *) PY="$(command -v "$PY" 2>/dev/null || true)" ;;
esac
if [ -z "$PY" ]; then
    echo "FATAL: cannot resolve python '${PYTHON:-python3}' on PATH" >&2
    exit 2
fi
# Oracle pin (2026-09-20): elan default drifted to 4.34.0 while the verdict
# contract is 4.33.1 (AGENTS acceptance rule 1 evidence base). Suites resolve
# the oracle through reference/lean_ref.py, which honours L4TVM_LEAN.
L4TVM_LEAN="${L4TVM_LEAN:-$HOME/.elan/toolchains/leanprover--lean4---v4.33.1/bin/lean}"
export L4TVM_LEAN
if [ ! -x "$L4TVM_LEAN" ]; then
    echo "FATAL: pinned lean not executable: $L4TVM_LEAN" >&2
    exit 2
fi
"$L4TVM_LEAN" --version
THREADS="${OMP_NUM_THREADS:-3}"
export OMP_NUM_THREADS="$THREADS" MKL_NUM_THREADS="$THREADS"
LOG_DIR="${REGRESSION_LOG_DIR:-$HOME/logs/lean4vm_cpu_regression}"
JOBS="${REGRESSION_JOBS:-3}"
CORES="${REGRESSION_CORES:-}"
GUARD="$PWD/scripts/run_mem_guarded.py"
SBIN="$PWD/model/step_vm_new_sparse.sbin"
mkdir -p "$LOG_DIR"
rm -f "$LOG_DIR"/*.rc "$LOG_DIR"/*.log

# Fields: timeout_secs|rss_cap_mb|label|path
# rss_cap_mb=0 keeps the guard for timeout/killpg/wall+peak reporting only.
# Cap basis: the guard measures the WHOLE process tree (lean oracle batch
# children included). string_graph_vs_lean 5000->6000->7500 (lead, 2026-09-14/15):
# WP6 grew the graph 16444->22367 dims and the legitimate tree peak moved to
# 6090MB (single run rc=0, 30/30+3/3, C5 2026-09-15) — 7500 keeps ~23% margin.
# reducenat_graph_vs_lean peak 2.3GB (measured C4) -> cap 4000.
# defeq_branches_vs_lean peak 2205MB wall 915s (lead memprobe, 2026-09-15
# 22:30, tree incl. lean oracle children) -> cap 3000, timeout 1800.
# Timeouts are ~1.5-2x the 2026-09-14 measured walls (/tmp/004B_reg1.log):
# stepgraph_vs_refvm 421s, stepgraph_vs_lean 362s, stepgraph_infer_defeq
# >1080s (killed mid-run at 53/84 under load, scaled estimate ~1700s -> 2700),
# engine harness ~800s for 33 cases under load.
SUITES=(
    "600|0|ref_vs_lean|tests/test_ref_vs_lean.py"
    "900|0|ref_infer_defeq|tests/test_ref_infer_defeq.py"
    # card 015/011 (a0d18cb + 09-23): stepgraph_vs_refvm 900->1200 — running
    # in the 3-pool it peaked past 900s; the 011 reg hit the old 900 cap
    # mid-corpus (09-23 reg1).  The 900->1200 bump was recorded in a0d18cb
    # but not applied; applied here.
    "1200|4000|stepgraph_vs_refvm|tests/test_stepgraph_vs_refvm.py"
    "1500|4000|stepgraph_vs_lean|tests/test_stepgraph_vs_lean.py"
    "3300|5000|stepgraph_infer_defeq|tests/test_stepgraph_infer_defeq.py"
    "900|4000|check_e2e|tests/test_check_e2e.py"
    # card 016 beat C (2026-10-04, mut2 solo re-run): 1200->2000 — killed twice
    # at the same wall with identical RSS (016C reg in-pool 1200.3s/1930MB;
    # mut2 solo 1200.3s/1930MB, both far under the 4000 cap): legitimate
    # duration, not load — Part A 16/16 green before each kill. 011 solo
    # baseline 1079.9s/2001MB; growth attributed to the card-016 graph
    # (+203 dims). Verify run mut3 (2026-10-04) rc=0: full wall 1814.3s /
    # 2014MB (Part A 16/16 + B 8/8). Lead re-calibration 2026-10-04:
    # 2000->2700 (1814.3 x 1.49, card-015 1.5x format) — 2000 left only ~10%
    # solo margin; re-measure at every graph growth.
    "2700|4000|mutation_reject|tests/test_mutation_reject.py"
    "900|0|olean_export|tests/test_olean_export.py"
    "900|4000|datadriven_env|tests/test_datadriven_env.py"
    "900|4000|datadriven_bool|tests/test_datadriven_bool.py"
    "600|0|level_vs_lean|tests/test_level_vs_lean.py"
    "600|0|level_encoding|tests/test_level_encoding.py"
    "600|0|env_meta|tests/test_env_meta.py"
    "600|0|env_meta_import|tests/test_env_meta_import.py"
    "900|4000|kernel_oracle|tests/test_kernel_oracle.py"
    "1500|6500|quot_graph_vs_lean|tests/test_quot_graph_vs_lean.py"
    "1500|7500|string_graph_vs_lean|tests/test_string_graph_vs_lean.py"
    # card 011 (2026-09-26, reg2 solo re-run): 1500->2400 — killed twice at the
    # same wall with nearly identical RSS (reg1 in-pool 1500.1s/6069MB; reg2
    # solo 1500.1s/6068MB, both under the 7000 RSS cap): legitimate duration,
    # not load. Kill point = 14/16 section-B cases done. Complete solo run
    # measured 1567.9s / 6067MB (reg2_r2, rc=0, 31+16 cases 0 failures)
    # -> 2400 keeps ~1.5x.
    "2400|7000|reducenat_graph_vs_lean|tests/test_reducenat_graph_vs_lean.py"
    "1800|3000|defeq_branches_vs_lean|tests/test_defeq_branches_vs_lean.py"
    # card 014 M5: cap 1100 makes d6 CONVERGE (True@1012) — dedicated run
    # 468.8s wall / 4694MB peak tree (m5_brec_final.log, guard 6144): the
    # 1200s timeout keeps 2.5x margin and RSS 5000->6000 restored ~21% margin.
    # card 015 (2026-09-21): dims 26023->34392 (+32%) pushed the tree peak to
    # 7288MB (single-run, reg015_rerun/brec_drec_iota_vs_lean.log) — RSS 6000->8000.
    "1200|8000|brec_drec_iota_vs_lean|tests/test_brec_drec_iota_vs_lean.py"
    # card 014 cache layer (P1+P2): M5 measured the full --phase all at the
    # 1100 cap: wall 2138.6s / peak 4742MB (small 977s + d6 arms ~440s +
    # whnf 721s; m5_cache_all.log).  Timeout 1800->2700 (26% margin), RSS
    # 5000->6000 (d6 P1-only arm peak 4737 + oracle children).
    # card 015 (2026-09-21): main-run killed at 6001MB>6000 (reg015/) and the
    # isolated re-run also rc=137 — RSS 6000->8000 (dims +32% growth).
    "2700|8000|defeq_cache_vs_lean|tests/test_defeq_cache_vs_lean.py"
    # card 010 G02 (added at acceptance, 2026-09-20): decl-injection
    # differential (a0 drift guard + carrier idleness + kind/level arms vs
    # live #KDECL oracle). Full set measured 1395.6s (G02) -> 1492.8s (G06)
    # -> 1755.4s / 1981MB (G03, g03_reg): the suite grows one section per
    # beat, so the timeout was raised 2100->2700 at G03 acceptance to keep
    # >1.5x margin; re-measure at every section addition.
    # card 015 (2026-09-21, CLOSED): dims +32% pushed the full run past 2700s
    # (killed mid-g03, beat3_declinject_full.log) and the G04-family peak to
    # 5894MB (beat3_sections_g04.log); section re-runs 86/86 checks + 3 xfail
    # (registered) rc=0.  Cap 2700|4000 -> 5000|7000 (estimated full ~4200s).
    # card 016 (2026-09-26): beat-B dims +203 total pushed the tree peak to
    # 7640MB (full run 106/106+0xfail 3798s, logs/016B/reg4.log, cap 9000);
    # cap-7000 and cap-7500 solo attempts both killed at the same g04-iv
    # window (7003MB/3367s, 7505MB/3217s — peak = traversal value, real need
    # >7505 unknown).  Cap 7000 -> 9200 (7640 x 1.20, card-015 format).
    # card 016 beat C (2026-10-04): full solo run 4888.0s/7629MB rc=0
    # (106/106+0xfail, logs/016C/w5) — 5000s wall left 2.2% margin, and
    # +28.7% vs reg4 3798.0s same-machine same-checks exceeds the dims
    # +203 explanation. Lead: 5000 -> 7200 (4888 x 1.47, card-015 format).
    "7200|9200|decl_injection_vs_lean|tests/test_decl_injection_vs_lean.py"
    "1200|0|engine_vs_refvm|scripts/verify_engine_vs_refvm.py"
)

launch_suite() {
    local tmo="$1" cap="$2" label="$3" path="$4" extra="$5"
    local log="$LOG_DIR/$label.log" rcfile="$LOG_DIR/$label.rc"
    local taskset_pfx=""
    [ -n "$CORES" ] && taskset_pfx="taskset -c $CORES "
    # transient units start with cwd=$HOME — the suites use repo-relative
    # paths, so cd back to the repo root inside the unit.
    # Same non-inheritance applies to OMP/MKL thread caps: pass them
    # explicitly into the unit, the caller's `export` does not reach it.
    systemd-run --user --collect --wait \
        -p PrivateTmp=yes -p TimeoutStartSec=0 -p TimeoutStopSec=15 \
        /bin/bash -c "cd '$PWD' && OMP_NUM_THREADS=$THREADS MKL_NUM_THREADS=$THREADS \
${taskset_pfx}timeout -k 10 $((tmo + 60)) \
$PY $GUARD --max-rss-mb $cap --timeout $tmo -- \
$PY -u '$path' $extra > '$log' 2>&1; echo \$? > '$rcfile'" \
        >/dev/null 2>&1
    [ -f "$rcfile" ] || echo 99 > "$rcfile"
}

for spec in "${SUITES[@]}"; do
    IFS='|' read -r tmo cap label path <<< "$spec"
    if [ -n "${SUITE_FILTER:-}" ] && [[ "$label" != *"$SUITE_FILTER"* ]]; then
        continue
    fi
    extra=""
    if [ "$label" = "engine_vs_refvm" ]; then
        # card 008 (REGLU_CLAMP 1e6): pow halts at 348 steps — the by-name
        # skip added in card 006 is retired; the daily loop now runs all 34.
        stat -c 'sbin-before: %y %s' "$SBIN" > "$LOG_DIR/$label.artifact" 2>/dev/null
    fi
    echo "=== launch $label (timeout ${tmo}s, cap ${cap}MB) -> $LOG_DIR/$label.log ==="
    launch_suite "$tmo" "$cap" "$label" "$path" "$extra" &
    while [ "$(jobs -rp | wc -l)" -ge "$JOBS" ]; do wait -n; done
done
wait

echo
echo "=== results ==="
pass=0; failed=()
for spec in "${SUITES[@]}"; do
    IFS='|' read -r tmo cap label path <<< "$spec"
    [ -f "$LOG_DIR/$label.rc" ] || continue
    rc=$(cat "$LOG_DIR/$label.rc")
    log="$LOG_DIR/$label.log"
    guard=$(grep '\[mem-guard\]' "$log" 2>/dev/null | tail -1)
    status=FAIL
    if [ "$rc" = "0" ]; then
        if [ "$label" = "engine_vs_refvm" ]; then
            # artifact drift check: the harness reads the repo .sbin on every
            # engine launch; a recompile mid-run mixes artifacts.
            m1=$(stat -c '%y %s' "$SBIN" 2>/dev/null)
            m0=$(sed 's/^sbin-before: //' "$LOG_DIR/$label.artifact" 2>/dev/null)
            nfail=$(grep -c '^  FAIL ' "$log" 2>/dev/null || true)
            if [ "$m0" != "$m1" ]; then
                status="FAIL (artifact drift: sbin changed $m0 -> $m1, re-run)"
                rc=90
            elif [ "$nfail" != "0" ]; then
                status="FAIL ($nfail unexpected FAIL lines)"
            else
                status=PASS
            fi
            echo "--- $label: $status  [all 34 cases incl. pow since card 008]"
        else
            status=PASS
        fi
    elif [ "$rc" = "137" ]; then
        status="FAIL (memory guard kill)"
    elif [ "$rc" = "124" ]; then
        status="FAIL (timeout ${tmo}s)"
    fi
    if [ "$status" = PASS ]; then
        pass=$((pass+1))
    elif [ "${status#PASS}" != "$status" ]; then
        pass=$((pass+1))
    else
        failed+=("$label: $status (rc=$rc)")
    fi
    echo "$label: $status  ${guard:-[no guard line: plain-timeout suite]}"
done

echo
echo "=== CPU regression: $pass passed, ${#failed[@]} failed ==="
for f in "${failed[@]:-}"; do [ -n "$f" ] && echo "  FAIL $f"; done
echo "full logs: $LOG_DIR/<label>.log"
[ "${#failed[@]}" -eq 0 ]
