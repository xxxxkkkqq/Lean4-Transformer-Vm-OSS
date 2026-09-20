# 011 — WP7 faithfulness strategy: non-committing arms and absorbed branches

Date: 2026-09-15. Card 007 (WP7, agent D). Status: accepted.

## Context

`is_def_eq_core` (K/type_checker.cpp:1171-1244) mixes two kinds of steps:
verdict-committing dispatches (const/const, proj/proj success, offset, ...)
and *attempts* that only change performance — on failure the kernel falls
through to a later branch. The graph's DEFEQ dispatch is a one-shot
select over mutually exclusive gates; if an attempt gate commits a verdict
the graph can end up False where the kernel would continue and reach True
(this was the A15 bug class: proj/proj and proj-diff pairs committed False
instead of falling through to the :1224 whnf).

Ground truth for every decision here is raw `Kernel.isDefEq` (probe3
channel). Elaborator reducibility attributes (`@[reducible]`/
`@[irreducible]`) do NOT reach kernel hints (verified: R_dbl/I_dbl both
carry hints=Regular in the 4.33.1 olean dump), so hint logic is kernel-
Regular/Opaque/Abbrev only (K/declaration.cpp:24-49).

## Decision

1. **Sink protocol for non-committing attempts** (A15, A17). An attempt
   arm pushes `frame1 = ST(F2=SINK_ID, V2=SD)` (sink above the still-buried
   DEFEQ frame) plus the attempt subframes, and retargets the subframe's
   commit field V2 to the sink position. SINK true → commit through
   `frV2` (the buried DEFEQ frame carries the verdict to the real caller
   via the generic pop_task walk, build_vm :5102). SINK false → re-emit
   the ordinary fallthrough shape (deq_sw0) reading the ORIGINAL pair via
   the oo* fetch at `frV2`. This makes the attempt verdict-neutral by
   construction: its only observable effect is a possible early True.
   Used for: proj/proj children attempt (DE_PRJ=64, kernel :1216-1220) and
   the lazy_delta args fast path (DE_ATT=66, kernel :1034-1043).
2. **A14 reflection commits its FALSE** (kernel :1181-1185). Sound because
   for a Bool-typed pair the rest of the dispatch chain cannot produce
   True unless `t` whnfs to `Bool.true`: Bool is a 2-constructor inductive
   so `eta_struct` declines it (K:896 `is_non_rec_structure`), Bool is not
   a Prop so neither proof-irrelevance (:1201) nor unit_like (:1241) can
   fire, and app/eta arms need both sides non-Const. So the graph's refl
   arm (DE_RFL=65) may commit the whnf-comparison verdict directly.
3. **A26 offset is a plain tail-call**. `is_def_eq_offset`'s succ/succ case
   commits the children's core verdict (K:1080-1082), so replacing the
   frame with DEFEQ(t_arg, s_arg) is faithful; zero/zero lands on deq_lit
   after `reduce_nat` (K:702-733) folds the literal.
4. **A30 try_unfold_proj_app is absorbed, not implemented.** It is a
   single-side whnf shortcut inside `lazy_delta_reduction_step`
   (K:983-990, used :1013/:1020) with the same performance-only charter as
   hints ("the hint only affects performance", K/declaration.h:33; kernel
   comment K:1005-1011). The graph's deq_fall whnfs BOTH sides soft to a
   fixed point and re-dispatches; whnf preserves the defeq equivalence
   class, so every reachable verdict equals the kernel's. Evidence:
   probe1/4 j5 (proj vs literal direct pair) True both sides, plus the
   whole A15 proj corpus. Cost: extra whnf steps on a rare pair shape;
   accepted.
5. **A15/A17 gates are ENV-metadata driven** (acceptance rule 3): succ /
   Bool.true via `_ctor_site` metadata (+legacy fallback); hints via
   `T_ENV_DEFVAL.V1` read from the anchor meta head; `is_delta` via
   `ENV_HDR(cid+1).V2` (value root). On legacy streams (no metadata) the
   A17 gate is identically false, which preserves old behavior exactly.

## Consequences

- New cont ids DE_PRJ=64 / DE_RFL=65 / DE_ATT=66; `g = range(1,67)`; both
  emission lists carry the 2-frame arms.
- KERNEL_COVERAGE marks A30 as absorbed with this ADR as evidence pointer;
  A14/A15/A17/A26 recorded as implemented.
- Any future kernel "attempt" branch (mdata quick, cached failures, ...)
  must use the sink protocol, never commit False on an attempt.
