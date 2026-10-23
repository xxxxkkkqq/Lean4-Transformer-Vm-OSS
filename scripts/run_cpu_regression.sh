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
#            SUITE_FILTER (substring), REGRESSION_SBIN, MATHLIB_SBIN.
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
SBIN="${REGRESSION_SBIN:-$PWD/model/step_vm_new_sparse.sbin}"
# The mathlib closure suite's engine legs judge (type, value, kind) triples
# against the CURRENT graph, so they need the current validation sbin — the
# REGRESSION_SBIN default above is the 2026-09-18 release artifact (dims
# 25,990), which predates the card-022 arms and cannot carry those verdicts.
MATHLIB_SBIN="${MATHLIB_SBIN:-$PWD/model/step_vm_022b_scratch.sbin}"
mkdir -p "$LOG_DIR"
rm -f "$LOG_DIR"/*.rc "$LOG_DIR"/*.log

# 26 suites below (the mathlib closure differential runs as three closure
# segments, see its entry).
# Fields: timeout_secs|rss_cap_mb|label|path|env
# env is an OPTIONAL prefix of shell assignments (no spaces in values) handed
# to the suite command, e.g. MC_CLOSURES=Quot_liftOn_mk — the transient unit
# gets it inside the `bash -c` line, not through this shell's export.
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
    # card 020 reg calibration (2026-10-13/14): pool kill at 1200.1s under
    # neighbor training load (020/reg); solo true wall 1476.7s / 588MB rc=0
    # (020/reg_solo, 37/37) -> 1200->2000 (1476.7 x 1.35).
    # card 021 reg calibration (2026-10-15): post-fix pool (021 sbin,
    # ~/logs/lean4vm_cpu_regression) measured 1875.3s under the 2000 cap —
    # 7% margin, below the ~1.4x discipline -> 2000->2600 (1875.3 x 1.39).
    "2600|4000|stepgraph_vs_refvm|tests/test_stepgraph_vs_refvm.py"
    # card 021 reg calibration (2026-10-15): post-fix pool killed at the wall
    # cap (1500.2s/1543MB); solo true wall 1180.6s/1540MB rc=0 (34/34,
    # ~/logs/021/reg_solo) -> 1500->1800 (1180.6 x 1.53).
    "1800|4000|stepgraph_vs_lean|tests/test_stepgraph_vs_lean.py"
    # card 018 B3 (2026-10-12, lead re-calibration): 3300->4500 — 016-era
    # solo wall 3106.9s; under concurrent neighbor GPU-training load the 018
    # graph killed at 3300s with 78/84 rows all PASS 0 FAIL (legit slow, not
    # a hang), verify rerun stepgraph3 rc=0 full wall 3420.9s/565MB
    # (84/84).  4500 = 3420.9 x 1.31; re-measure at every graph growth.
    # card 021 reg calibration (2026-10-15): post-fix pool ran 4323.0s under
    # the 4500 cap — 4% margin; solo rerun truth 3755.4s/735MB rc=0 (84/84,
    # ~/logs/021/stepgraph_021c.log) -> 4500->6100 (4323.0 x 1.41).
    "6100|5000|stepgraph_infer_defeq|tests/test_stepgraph_infer_defeq.py"
    # card 021 reg calibration (2026-10-15): post-fix pool 771.9s under the
    # 900 cap (1.17 margin; 016C pool was 770.9s — stable, not growing) ->
    # 900->1100 (771.9 x 1.43).
    "1100|4000|check_e2e|tests/test_check_e2e.py"
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
    # card 021 reg calibration (2026-10-15): post-fix pool 873.4s under the
    # 900 cap — 3% margin; solo 729.0s rc=0 (~/logs/021/reg_solo) ->
    # 900->1300 (873.4 x 1.49).
    "1300|0|olean_export|tests/test_olean_export.py"
    "900|4000|datadriven_env|tests/test_datadriven_env.py"
    "900|4000|datadriven_bool|tests/test_datadriven_bool.py"
    "600|0|level_vs_lean|tests/test_level_vs_lean.py"
    "600|0|level_encoding|tests/test_level_encoding.py"
    "600|0|env_meta|tests/test_env_meta.py"
    "600|0|env_meta_import|tests/test_env_meta_import.py"
    "900|4000|kernel_oracle|tests/test_kernel_oracle.py"
    # card 021 reg calibration (2026-10-15): post-fix pool killed on RSS
    # (6789MB > 6500 at 237.7s, still climbing); solo true peak 7927MB /
    # 474.5s rc=0 (7/7 corpus, ~/logs/021/reg_solo) -> RSS 6500->11000
    # (7927 x 1.39); wall 1500 has 3.2x over the solo truth, stays.
    "1500|11000|quot_graph_vs_lean|tests/test_quot_graph_vs_lean.py"
    # card 021 reg calibration (2026-10-15): post-fix pool measured
    # 1279.8s/6677MB under the 1500|7500 caps — 1.17 wall / 1.12 RSS margin
    # (016C was 948.6s/4482MB; growth tracks the 021 dims +9k) ->
    # 1500->1800 (1279.8 x 1.41), 7500->10000 (6677 x 1.50).
    "1800|10000|string_graph_vs_lean|tests/test_string_graph_vs_lean.py"
    # card 011 (2026-09-26, reg2 solo re-run): 1500->2400 — killed twice at the
    # same wall with nearly identical RSS (reg1 in-pool 1500.1s/6069MB; reg2
    # solo 1500.1s/6068MB, both under the 7000 RSS cap): legitimate duration,
    # not load. Kill point = 14/16 section-B cases done. Complete solo run
    # measured 1567.9s / 6067MB (reg2_r2, rc=0, 31+16 cases 0 failures)
    # -> 2400 keeps ~1.5x.
    # card 021 reg calibration (2026-10-15): post-fix pool 2034.1s under the
    # 2400 cap — 1.18 margin (solo 016C-era 1567.9s -> 1659.4s; growth tracks
    # the 021 dims) -> 2400->2900 (2034.1 x 1.43).  RSS 2496 vs 7000 stays.
    "2900|7000|reducenat_graph_vs_lean|tests/test_reducenat_graph_vs_lean.py"
    # card 021 reg calibration (2026-10-15): post-fix pool 1781.6s under the
    # 1800 cap — 1% margin; solo 1586.0s/1655MB rc=0 (48 rows ALL OK,
    # ~/logs/021/reg_solo) -> 1800->2300 (1586.0 x 1.45).
    "2300|3000|defeq_branches_vs_lean|tests/test_defeq_branches_vs_lean.py"
    # card 014 M5: cap 1100 makes d6 CONVERGE (True@1012) — dedicated run
    # 468.8s wall / 4694MB peak tree (m5_brec_final.log, guard 6144): the
    # 1200s timeout keeps 2.5x margin and RSS 5000->6000 restored ~21% margin.
    # card 015 (2026-09-21): dims 26023->34392 (+32%) pushed the tree peak to
    # 7288MB (single-run, reg015_rerun/brec_drec_iota_vs_lean.log) — RSS 6000->8000.
    # card 012 beat-2 (2026-10-04, P1 numpy history backend default): two
    # deterministic wall kills at the same point (12p2 verify 1200.8s/7814MB,
    # quiet re-test 1200.7s/7813MB, both under the 8000 RSS cap; A/B/D
    # sections all PASS, only section C censored) vs list-era 016C solo
    # 1072.9s/7352MB — legitimate duration under the numpy default, not load.
    # Cap 1200 -> 1800. Lead true-wall run (brec1800, 2026-10-04): rc=0,
    # 1387.2s / 7813MB, 0 divergences — +29.3% vs list era, accepted trade
    # for the 7x memory win (6134 -> 840MB peak, VM_SPEC §19); fork
    # materialization (list(_HistStore) per-entry tuples vs list pointer
    # copy) registered as the follow-up optimization candidate. 1800 = 1.30x.
    # card 020 reg calibration (2026-10-13/14): graph dims 012-era ~33k ->
    # 020 49.3k (+50%) pushed RSS past every cap tried — pool 8022MB@388s,
    # solo 8009@414s (cap 8000), 9003@695s (cap 9000).  True peak measured
    # under cap 11000: rc=0, 1277.0s / 10575MB, 0 divergences (020/reg_solo
    # recalib2).  RSS 8000->12000 (10575 x 1.135); wall 1800 stays
    # (1277.0 x 1.41).  Re-measure at every graph growth.
    # card 021 reg calibration (2026-10-15): post-fix pool killed on RSS
    # (12003MB > 12000 at 1108.8s, RSS still climbing — same escalation as
    # 020); solo true peak 12485MB / 1622.7s rc=0 (0 divergences,
    # ~/logs/021/reg_solo) -> RSS 12000->17000 (12485 x 1.36), wall
    # 1800->2300 (1622.7 x 1.42).  Re-measure at every graph growth.
    "2300|17000|brec_drec_iota_vs_lean|tests/test_brec_drec_iota_vs_lean.py"
    # card 014 cache layer (P1+P2): M5 measured the full --phase all at the
    # 1100 cap: wall 2138.6s / peak 4742MB (small 977s + d6 arms ~440s +
    # whnf 721s; m5_cache_all.log).  Timeout 1800->2700 (26% margin), RSS
    # 5000->6000 (d6 P1-only arm peak 4737 + oracle children).
    # card 015 (2026-09-21): main-run killed at 6001MB>6000 (reg015/) and the
    # isolated re-run also rc=137 — RSS 6000->8000 (dims +32% growth).
    # card 020 reg calibration (2026-10-13/14): same dims-growth RSS
    # escalation — pool 8018MB@2008s, solo 8015@2342s (cap 8000), 9006@2393s
    # (cap 9000).  True peak measured under cap 11000: rc=0, 2505.4s /
    # 10565MB, ALL OK (020/reg_solo recalib3).  Timeout 2700->3600
    # (2505.4 x 1.44, card-015 1.5x format); RSS 8000->12000 (10565 x 1.135).
    # card 021 reg calibration (2026-10-15): post-fix pool killed on RSS
    # (12023MB > 12000 at 2625.3s); solo true peak 12983MB / 2338.4s rc=0
    # (ALL OK, ~/logs/021/reg_solo) -> RSS 12000->18000 (12983 x 1.39);
    # wall 3600 keeps 1.54x over the solo truth, stays.
    "3600|18000|defeq_cache_vs_lean|tests/test_defeq_cache_vs_lean.py"
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
    # card 021 reg calibration (2026-10-15): post-fix pool killed at the wall
    # cap (7200.5s, RSS only 1859MB — the numpy history backend collapsed the
    # old 9200 RSS pressure); solo rerun truth 7823.3s / 1869MB rc=0
    # (149/149 checks + 1 xfail, ~/logs/021/decl_full_e.log, bs1/bs2 rows
    # included) -> 7200->11000 (7823.3 x 1.41); RSS 9200 stays.
    "11000|9200|decl_injection_vs_lean|tests/test_decl_injection_vs_lean.py"
    # card 012 M-C (added at delivery 2026-10-15): mathlib-closure declaration
    # check differential, 35 rows x 4 channels (mc_oracle / InjectionEnv+
    # run_check / RefVM.check / vm_run check mode) on per-case minimal envs +
    # a full-closure engine leg for the Quot closure.  Requires the M-A closure
    # artifacts under ~/logs/012I/closures/ (fails loudly if absent).
    # Split per closure (card 025): one entry cannot hold the wall any more —
    # after card 023 the engine channel runs accept rows to a verdict
    # (q_acc_thm 824.1s minimal / 901.1s full closure on the 022b sbin,
    # ~/logs/022B3/b7_engine_qaccthm{,_full}_probe.log) and graph accept rows
    # are ~200-700s, so 35 rows extrapolate to 4-6.5h and a single cap both
    # blows the wall budget and hides "one row got slower".  35 rows =
    # 16 Quot + 11 Vector3 + 8 Nat; each segment rebuilds its closure env.
    # Caps = measured segment wall x 1.4 (solo segmented pass, JOBS=1, 022b
    # sbin, ~/logs/022B3/b8_reg/): quot 5092.2s/2333MB -> 7100|3200
    # (x1.39/x1.37), vector3 559.3s/1584MB -> 780|2200 (x1.39/x1.39),
    # nat 206.3s/1939MB -> 280|2700 (x1.36/x1.39).  Solo, so the first in-pool
    # run is the contention check; re-measure at every graph growth.
    # 2026-10-23 first in-pool run (card 022 beat 4b, task-10,
    # ~/logs/lean4vm_cpu_regression): the x1.4 solo caps did not survive the
    # pool.  vector3 and nat both hit the WALL cap with 0 FAIL (vector3 killed
    # inside row 10/11 at v_lvl_maxuu, nat inside row 7/8 at n_lvl_succ; peak
    # RSS 1558/2200 and 1939/2700, i.e. far from the RSS caps).  Same-run pool
    # inflation on quot: 5971.3s vs 5092.2 solo = x1.17.  Caps re-derived as
    # solo x 2.0 to cover pool inflation: vector3 559.3 -> 1100, nat 206.3 ->
    # 700; RSS caps unchanged; quot 7100 already holds (5971.3s in-pool).
    # Solo reruns under the new caps: ~/logs/022B3/b9_solo_{vector3,nat}/.
    "7100|3200|mathlib_quot|tests/test_mathlib_closure_vs_lean.py|MC_CLOSURES=Quot_liftOn_mk MC_SBIN=$MATHLIB_SBIN"
    "1100|2200|mathlib_vector3|tests/test_mathlib_closure_vs_lean.py|MC_CLOSURES=Vector3_cons_fz MC_SBIN=$MATHLIB_SBIN"
    "700|2700|mathlib_nat|tests/test_mathlib_closure_vs_lean.py|MC_CLOSURES=Nat_testBit_land MC_SBIN=$MATHLIB_SBIN"
    "1200|0|engine_vs_refvm|scripts/verify_engine_vs_refvm.py"
)

launch_suite() {
    local tmo="$1" cap="$2" label="$3" path="$4" extra="$5" envs="$6"
    local log="$LOG_DIR/$label.log" rcfile="$LOG_DIR/$label.rc"
    local taskset_pfx=""
    [ -n "$CORES" ] && taskset_pfx="taskset -c $CORES "
    # transient units start with cwd=$HOME — the suites use repo-relative
    # paths, so cd back to the repo root inside the unit.
    # Same non-inheritance applies to OMP/MKL thread caps: pass them
    # explicitly into the unit, the caller's `export` does not reach it.
    # Per-suite env assignments ride in the same way, through `env` (the guard
    # execs the command list directly, so a bare `VAR=x cmd` prefix is argv[0],
    # not an assignment): word-split inside the unit, no spaces in values.
    systemd-run --user --collect --wait \
        -p PrivateTmp=yes -p TimeoutStartSec=0 -p TimeoutStopSec=15 \
        /bin/bash -c "cd '$PWD' && OMP_NUM_THREADS=$THREADS MKL_NUM_THREADS=$THREADS \
${taskset_pfx}timeout -k 10 $((tmo + 60)) \
$PY $GUARD --max-rss-mb $cap --timeout $tmo -- \
${envs:+env $envs }$PY -u '$path' $extra > '$log' 2>&1; echo \$? > '$rcfile'" \
        >/dev/null 2>&1
    [ -f "$rcfile" ] || echo 99 > "$rcfile"
}

for spec in "${SUITES[@]}"; do
    IFS='|' read -r tmo cap label path envs <<< "$spec"
    if [ -n "${SUITE_FILTER:-}" ] && [[ "$label" != *"$SUITE_FILTER"* ]]; then
        continue
    fi
    extra=""
    if [ "$label" = "engine_vs_refvm" ]; then
        # card 008 (REGLU_CLAMP 1e6): pow halts at 348 steps — the by-name
        # skip added in card 006 is retired; the daily loop now runs all 34.
        stat -c 'sbin-before: %y %s' "$SBIN" > "$LOG_DIR/$label.artifact" 2>/dev/null
    fi
    echo "=== launch $label (timeout ${tmo}s, cap ${cap}MB${envs:+, env: $envs}) -> $LOG_DIR/$label.log ==="
    launch_suite "$tmo" "$cap" "$label" "$path" "$extra" "${envs:-}" &
    while [ "$(jobs -rp | wc -l)" -ge "$JOBS" ]; do wait -n; done
done
wait

echo
echo "=== results ==="
pass=0; failed=()
for spec in "${SUITES[@]}"; do
    IFS='|' read -r tmo cap label path envs <<< "$spec"
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
