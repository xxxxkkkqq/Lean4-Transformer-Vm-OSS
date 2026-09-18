/* LD_PRELOAD shim: report 3 CPUs to sysconf(_SC_NPROCESSORS_{ONLN,CONF}).
 *
 * Why: lake 4.33 sizes its job pool from nproc and ignores CPU affinity
 * (observed: taskset -c 14-19 still ran 20 lean workers; the unbounded
 * build peaked ~19GB and OOM-crashed the desktop client 2026-09-16
 * ~04:14). There is no -j knob. sysconf() interposition caps lake's
 * concurrency at 3 without touching scheduler semantics (deps stay
 * safe, no cross-process races). Verified: 4 procs / 3.3GB aggregate.
 *
 * Launch (machine discipline):
 *   gcc -shared -fPIC -o /tmp/nproc3.so scripts/lake_nproc_shim.c -ldl
 *   setsid nohup env LD_PRELOAD=/tmp/nproc3.so OMP_NUM_THREADS=2 \
 *     taskset -c 14-19 ~/.elan/bin/lake build > "$HOME/logs/012I/build5.log" 2>&1 < /dev/null &
 *
 * Do NOT "optimize" per-module `lake build X.lean:o` loops: lake expands a
 * src-path target into its whole closed dependency build with internal
 * nproc-wide parallelism (measured: 3 pool slots -> 24 concurrent workers),
 * and parallel lake invocations race on shared imports.
 *
 * UNTESTED ALTERNATIVES (audit 2026-09-16, docs/handoffs/009-L-wheel-audit.md):
 * - `LEAN_NUM_THREADS=3` (Lean runtime src/runtime/object.cpp:1083-1088 reads
 *   it at the same site that falls back to the core count we spoof here) —
 *   may cap lake job width without any shim. Run one controlled comparison
 *   on the next rebuild; keep shim or delete it based on measured width.
 * - `lake exe cache get` (mathlib lakefile.lean:114-115): skips local
 *   compilation entirely for stock tags. This shim is only for builds the
 *   cache does not serve.
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <unistd.h>

long sysconf(int name) {
  static long (*real)(int) = 0;
  if (!real) real = dlsym(RTLD_NEXT, "sysconf");
  if (name == _SC_NPROCESSORS_ONLN || name == _SC_NPROCESSORS_CONF) return 3;
  return real(name);
}
