#!/usr/bin/env bash
# Capped Mathlib rebuild = one full `lake build` under the sysconf shim.
# Rationale + measurements: scripts/lake_nproc_shim.c header.
# Machine-discipline wrapper (cores 14-19):
#   setsid nohup bash scripts/build_mathlib_capped.sh \
#     > "$HOME/logs/012I/build5.log" 2>&1 < /dev/null &
# Watchdog (AGENTS discipline): wrap this launcher via scripts/run_mem_guarded.py
# (whole process TREE of this pgid; never aggregate `ps -C lean,lake` machine-wide
# — that counts other sessions' lean procs, e.g. agent oracle calls, and kills them).
set -u
SHIM=/tmp/nproc3.so
[ -f "$SHIM" ] || gcc -shared -fPIC -o "$SHIM" "$(dirname "$0")/lake_nproc_shim.c" -ldl
cd /home/xkq/mathlib_src || exit 1
exec env LD_PRELOAD="$SHIM" OMP_NUM_THREADS=2 taskset -c 14-19 "${LAKE:-$HOME/.elan/bin/lake}" build
