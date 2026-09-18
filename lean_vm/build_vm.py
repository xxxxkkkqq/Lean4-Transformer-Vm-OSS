"""Phase 2: the single ALM step graph (VM_SPEC §10).

One graph computes ONE machine micro-step: it reads the current STATE token
fields at the last sequence position, fetches 1-4 history tokens by
position, and produces the next STATE fields plus emission flags. All
loops (bvar chain walks, nat digit carries, argument evaluation) are
amortized into autoregressive time by the driver (lean_vm/step_driver.py).

State layout (§10.1): A=focus, B=env head (digit index k in nat compute),
C=pend head, D=frame head, E=aux (carry/borrow/cmp state), F=spine root
(main) / output chain head (nat compute).

Control lives in the frame stack (append-only; "updating" a frame = push a
new one and point D at it):
  T_FRAME task=3 WALK     V1=cur link, V2=caller, X=remaining hops
  T_FRAME task=2 NAT      V1=op code, V2=caller / phase payload, X=phase
  T_FRAME task=5 ST       storage: V1=stored pos, V2=next frame, X=stored env
NAT phases (X): 1/2 = waiting for arg1/arg2, 3 = digit loop (simple ops and
mul/pow cells), 4 = div compare, 5 = div R-b loop, 6 = div Q++ loop,
10 = pow controller, 13 = pow b-1 loop.

Arity-2 protocol: fire D=[ST(arg2), NAT(op, caller, 1)]; arg1 done
D=[ST'(arg1 value), NAT(op, caller, 2)]; arg2 done pushes the op's working
frame and emits the output chain head (F = its position). Done steps pop D
to the caller and put the result in A; the NEXT step's completion logic
delivers it uniformly (D head ST / NAT phase 1 = waiting), so nested nat
ops need no dedicated return path. Arity-1 ops (succ/pred) skip ST.

M3 digit algorithms (all per-digit micro-steps, constant graph depth):
  mul: acc' = acc + a_i*b*10^i shift-add; cell (i,j):
       acc'[j] = accC[j] + a_i*b_{j-i} + carry; row = one a digit.
  pow: rounds acc *= a while b != 0 (controller phase 10), cell as mul with
       b-side = a and multiplier-side = the round's acc (frame V2), then
       b := b-1 (dec phase 13).
  div/mod: while R >= b (compare phase 4): R := R-b (phase 5), Q := Q+1
       (phase 6); div result Q, mod result R. b=0: div -> [0], mod -> a
       (kernel calibration).
ST'-to-caller threading across multi-frame ops: chain heads carry it in X
(Q'/b' heads), row indices in V2 (acc heads); caller resolution stays a
constant 2-hop fetch (D -> ST' -> NAT' -> caller).
"""
from __future__ import annotations

import os

from lean_kernel.alm_graph import (
    InputDimension, Expression, ProgramGraph, reset_graph,
    persist, reglu, _one_dim, _position_dim, _inv_log_pos_dim,
    _all_dims, _all_lookups, _to_expr, LookUp, LATEST_ALPHA, BIG,
)
from lean_kernel.alm_p2 import fetch_by_position
from lean_vm.primitives import (
    _kind_eq_raw, _select, _geq_expr, _eq_expr,
)

from expr.model import (
    K_BVAR, K_FVAR, K_MVAR, K_SORT, K_CONST, K_APP, K_LAM, K_PI, K_LET,
    K_LIT, K_MDATA, K_PROJ, LIT_NAT,
    KL_ZERO, KL_SUCC, KL_MAX, KL_IMAX, KL_PARAM, KL_MVAR,
)
from expr.tokens import (
    T_FRAME, T_PEND, T_LINK, T_PI_CLO, T_DEFCACHE, T_WHNFCACHE,
    TASK_WHNF, TASK_INFER, TASK_DEFEQ, TASK_LEVEL, TASK_CHECK,
    T_ENV, T_ENV_META, T_ENV_RECVAL, T_ENV_RULE, T_ENV_RECEXTRA,
    T_ENV_CTORVAL, T_ENV_INDVAL, T_ENV_LIST, CK_RECURSOR, CK_QUOT,
    T_ENV_QUOTVAL, T_ENV_DEFVAL, CK_DEFINITION,
    ENV_F_IS_REC,
)

TASK_WALK = 3
TASK_NAT = 2
TASK_ST = 5


def _read_nat_size_env(default: int = 128 * 1024 * 1024) -> int:
    """Replica of kernel `read_nat_size_env` (K/type_checker.cpp:1307-1315):
    unset → default; otherwise strtoull(s, &end, 10) must consume the WHOLE
    string (`end != s && *end == 0`), i.e. optional leading whitespace + sign,
    then only digits, nothing after.  The kernel casts to size_t, so a
    negative literal wraps mod 2**64 — mirrored here.  Read ONCE at graph
    build time and frozen into digit tables (data, not per-constant logic)."""
    s = os.environ.get("LEAN_NAT_MAX_SIZE")
    if s is None:
        return default
    i, n = 0, len(s)
    while i < n and s[i] in " \t\n\v\f\r":
        i += 1
    neg = False
    if i < n and s[i] in "+-":
        neg = s[i] == "-"
        i += 1
    j = i
    while j < n and "0" <= s[j] <= "9":
        j += 1
    if j == i or j != n:
        return default
    v = int(s[i:j]) % (2 ** 64)
    return (-v) % (2 ** 64) if neg else v


# nat op codes (expr/tokens.py NAT_OP_CODES)
OP_SUCC, OP_PRED, OP_ADD, OP_SUB = 1, 2, 3, 4
OP_MUL, OP_POW, OP_DIV, OP_MOD = 5, 6, 7, 8
OP_BEQ, OP_BLE = 9, 10
OP_REC = 11   # Nat.recursor dispatch (ENV_HDR.X; iota P6.5 — not a nat op:
              # NAT_OPS/NAT_OP_ARITY deliberately exclude Nat.rec)
OP_CASESON = 12   # casesOn dispatch (P7.5b graph iota; ENV_HDR.X only)
OP_CASESON_P2 = 13   # P2.casesOn dispatch (P7.5b-3: 3-entry spine, 1 minor)
OP_CASESON_BOOL = 14   # Bool.casesOn dispatch (P7.5b-4: 4-entry spine, 2
                       # zero-field minors — if-then-else / decide)
# WP8-H5: ENV_HDR.X tags on the Bool constructors (expr/tokens.py
# CTOR_ID_CODES), used only to *find* their cids by a name-keyed header scan
# (the same mechanism as Nat.succ's OP_SUCC).  They are not nat ops: eX >= 11
# makes both arities 0 in the natop gate below, so a tagged ctor still whnf's
# as a stuck 0-field constructor.
OP_TRUE, OP_FALSE = 16, 17
# WP5-E3/E4: ENV_HDR.X tags on the two string-reduction handles (expr/tokens.py
# STR_ID_CODES), discovered by the same name-keyed header scan as OP_TRUE/
# OP_FALSE.  "String.ofList" is the head of a literal's shadow expansion (the
# target of kernel try_string_lit_expansion, K/type_checker.cpp:1143-1156);
# "String" is the type of a string literal (kernel infer_lit,
# K/type_checker.cpp:315-321).  Not nat ops: eX >= 11 keeps both arities 0.
OP_OFLIST, OP_STRING = 18, 19
# WP3 general recursor iota (§13): a metadata-driven dispatch code carried in
# NAT-frame.V1.  Unlike OP_REC..OP_CASESON_BOOL (tagged on the TOY constants by
# tokens.py) it is NOT tied to any cid: any constant whose T_ENV_META anchor
# says constant_info_kind == Recursor routes here and the rule table is read
# from T_ENV_RECVAL/T_ENV_RULE.  Reuses the retired P7.5c brecOn opcode 15.
OP_IOTA = 15
# 15 was the P7.5c-1b Nat.brecOn dispatch opcode — RETIRED in P7.5c-2 (Route
# A): Nat.brecOn/Nat.below are plain value consts; the graph's existing const-
# delta gate, rec iota (OP_REC) and P2 proj machinery reduce them.
# WP4 quot: NAT-frame.V1 dispatch for the Quot reducts (K/quot.h:39-70).  Like
# OP_IOTA it is data-driven (identified from T_ENV_QUOTVAL, not a cid); 18 is
# free in the NAT-frame op space (1..15 are nat ops/iota, 16/17 are the
# ENV_HDR.X Bool-ctor tags and never appear as NAT-frame.V1).
OP_QUOT = 18
# WP6-F: reduce_nat ops (K/type_checker.cpp:702-733; oracle-confirmed 4.33.1
# identical).  ENV_HDR.X tags (expr/tokens.py NAT_OP_CODES) AND NAT-frame.V1
# dispatch codes.  20+ because 15 collides with OP_IOTA and 16-19 are used in
# one of the two namespaces.  These are the graph-side completion of the F
# group; the frozen RefVM deliberately does not know them (no delta-reduce).
OP_GCD, OP_LAND, OP_LOR, OP_XOR = 20, 21, 22, 23
OP_SHL, OP_SHR = 24, 25
# 26 = graph-internal infer_lit size guard (never an ENV_HDR.X name tag — no
# constant in any environment carries X=26; see WP6 guard section).
OP_LITCHECK = 26

# toy-env constant ids (Encoder assigns cids by TOY_CONSTS order); the step
# graph needs them to emit Bool results and to read Nat.zero args.
CID_TRUE, CID_FALSE, CID_ZERO = 2, 3, 4
CID_NAT, CID_SUCC = 0, 5
CID_PRED, CID_REC = 6, 27   # Nat.pred (iota succ-rule pred trick) / Nat.rec
                            # (TOY_CONSTS order; iota dispatch, P6.5)
# P2.mk ctor cid (TOY_CONSTS order: P2=17→cid17, P2.mk=18→cid18). The whnf
# proj reduction gates on a full 2-field P2.mk spine (build-time const, NOT a
# runtime table — VM_SPEC §8.1 struct metadata).
CID_P2MK = 18
# Proj tokens carry the structure NAME id in V0 (Encoder._enc_expr: V0=nid(sname));
# structural eta builds Proj(nid("P2"), i, t) to compare fieldwise.
NID_P2 = 18
# P2's structure type is Const(cid 17); a fully-applied 0-param ctor has this
# as its inferred type (structural-eta type check, no infer(Proj) needed).
CID_P2 = 17
# P7 unit_like: UnitT is the toy env's only 0-field structure (cid 28, appended
# after Nat.rec=27 so the hardcoded cids above stay put). is_def_eq_unit_like
# gates on the stuck pair's type head being Const(CID_UNITT) (VM_SPEC §11.9).
CID_UNITT = 28
# P7.5b casesOn: Nat.casesOn is cid 30 (appended after UnitT.mk=29 so the
# hardcoded cids above stay put). The graph dispatches on ENV_HDR.X=OP_CASESON
# (tagged in tokens.py) and needs the cid only to emit the pred/rhs spine.
CID_CASESON_NAT = 30
# P7.5b-3: P2.casesOn is cid 31 (appended after Nat.casesOn=30). 3-entry spine
# [t, motive, alt], single 2-field minor, major = stuck `P2.mk a b` ctor app.
CID_CASESON_P2 = 31
# P7.5b-4: Bool.casesOn is cid 32 (appended after P2.casesOn=31). 4-entry spine
# [t, motive, false-minor, true-minor] — minors follow Lean's ctor declaration
# order (Bool.false before Bool.true). Both minors are 0-field, so the graph
# iota needs no build loop (each rule just selects the minor, like Nat's zero).
CID_CASESON_BOOL = 32
# P7.5c-1b: Nat.below is cid 33, Nat.brecOn is cid 34 (appended after
# Bool.casesOn=32). P7.5c-2: both are plain VALUE consts (toy_env faithful
# def-over-rec delta values) — no CID_BELOW/CID_BREC dispatch machinery.
# continuation ids (ST.F2). Module scope so the WALK section can dispatch on
# the defeq-bvar ids (D_BV2/D_BV3) when delivering a resolved marker.
(I_FN, I_PI, I_ARG, I_CHK, I_LAMDOM, I_LAMSORT, I_LAMBODY, I_PIDOM,
 I_PIS1, I_PIL1, I_PIS2, I_PIL2, I_SORTEM, I_LETV, I_LETD,
 D_SORT2, D_SORT3, D_LITL, D_BIND2, D_TPC2, D_BV2, D_BV3, D_XPI2,
 D_SW2, D_SW3, D_SP1, D_SPA, D_NCT, D_NCS, D_NCC, D_NCD) = range(1, 32)
# ── Phase 5 M3 continuation ids (proof-irrel / eta / eta-struct / proj) ──
# The stuck-pair chain (kernel is_def_eq_core order): proof-irrel →
# both-app spine → nat-ctor → eta → eta-struct → False. Each step reads
# the stuck pair from the buried original DEFEQ frame (oo* = fetch from
# frV2) and delivers its verdict to frV2 (pop_task). Fall-through pushes
# the next step's kickoff ST.
(I_PROJ,                                   # whnf: proj child done
 PI_T, PI_TY, PI_LVL, PI_S, PI_D,          # proof irrelevance
 ST_SP, ST_NC, ST_ET, ST_ES,               # stuck chain step kickoffs
 ETA_T, ETA_S, ETA_DOM, ETA_APP, ETA_LINK, ETA_LNK2, ETA_BODY,
 ES_T, ES_S, ES_DOM, ES_FIELD, ES_NEXT,     # structural eta
 BV_ID,                                     # bvar marker bid compare
 CK_TY, CK_RES,                             # M4.2 check: type / verdict cont
 IP_TY, IP_PEEL,                            # P6.2 infer_proj: whnf / peel
 ST_UL, UL_T, UL_W, UL_CHK, UL_D) = range(32, 64)   # P7 unit_like chain
# WP7-A15 (card 007): sink continuation for the NON-COMMITTING proj/proj
# children attempt (kernel is_def_eq_core K/type_checker.cpp:1216-1220 — on
# children-false the pair must fall through to the expensive-proj whnf_core
# at :1224, never commit False).
DE_PRJ = 64
# WP7-A14: sink for the reflection arm's single-side whnf (kernel
# is_def_eq_core K/type_checker.cpp:1181-1185).
DE_RFL = 65
# WP7-A17: sink for the non-committing lazy_delta args fast path (kernel
# K/type_checker.cpp:1034-1045 — args-equal commits TRUE; args-differ only
# cache a failure and the pair falls through to unfolding both sides).
DE_ATT = 66
# WP7-G1: ensure_sort(declared type) chain (K/type_checker.cpp:62-70):
# infer the declared type, soft-whnf the result, require K_SORT.
CK_G0 = 67
CK_G1 = 68
# ── card 010 G02: TASK_CHECK anchor E2 = declaration-kind carrier ───────────
# Layout is specced in docs/ENV_FORMAT.md §2.8 (single source of truth) and
# written by lean_vm/step_driver.check_e2(); the reader side lives here.  The
# two copies are kept honest by tests/test_decl_injection_vs_lean.py section
# A (drift guard) — moving them into a shared module would mean editing
# expr/tokens.py, which card 010's file-ownership list freezes.
# Kernel basis: environment.cpp:271-284 dispatches add_{axiom,definition,
# theorem,opaque} on the declaration kind and only add_theorem (:192-209)
# runs is_prop, so the kind must reach the graph as data (acceptance rule 3).
CHECK_E2_STRIDE = 8                  # E2 = kind_code + STRIDE * mode_code
CHECK_KIND_UNSPECIFIED = 0           # legacy path: every kind gate stays inert
CHECK_KIND_AXIOM = 1
CHECK_KIND_DEFINITION = 2
CHECK_KIND_THEOREM = 3
CHECK_KIND_OPAQUE = 4
CHECK_MODE_SAFE = 0                  # safe checker (legacy default)
CHECK_MODE_UNSAFE = 1                # graph behaviour: card 010 G03 (G2-unsafe)
# F15 (card 009): soft-chain arg arm.  The kernel infer_only spine
# (K/type_checker.cpp:189-205) walks the Pi bodies WITHOUT the
# arg-vs-domain is_def_eq (:174-188 runs only when !infer_only), so the
# soft (proof-irrel, F2=1) INFER ladder must skip that check: its domain
# side whnfs @Nat.below and re-enters INFER ladders on deeper structures
# every cycle (d6 semantic growth ring, 005 F13-02/F15-01).  I_ARG keeps
# the hard (!infer_only) semantics unchanged; I_ARG_S reuses I_ARG's fail
# channels (A=0 marker, ensure_pi soft delivery) and I_CHK's True success
# path verbatim.
I_ARG_S = 69

# Card 014 (ADR 017): the is_def_eq memo layer. VM014_CACHE=0 removes every
# cache arm at build time (the verdict-invariance control: the two settings
# produce different graphs and are compared case-by-case by
# scripts/probe_014_invariance.py). Default = on.
VM014_CACHE = os.environ.get("VM014_CACHE", "1") != "0"
# Card 014 P2: the whnf memo (kernel m_whnf, K/type_checker.cpp:736-775).
# M6 ROLLBACK (010-M M6-04, ADR 019): the arm is DORMANT by default —
# VM014_WMEMO=0 is the shipped state.  The write side of this memo is not
# sound on the current machine: WHNF frames re-dispatched by spine-walk
# launchers (I_ARG_S/ST-phase2, 010-M M6-03(2)) carry stale V1/X fields
# that do NOT describe the computation the frame actually performs, so
# entries are recorded under mislabeled keys (e.g. (784,0,0)->(783,1603)
# in the WP5 string corpus) and a later entry-shape request for (784,0)
# replays the foreign value and rejects.  Fixing this needs cross-beat
# memory (a launch-frame mark, or a launcher-side entry-shape gate) that
# the frame token layout cannot carry today; the full breach evidence and
# the two candidate designs are banked in ADR 019 for a follow-up card.
# Setting this env to 1 re-enables the DORMANT code path for research —
# do NOT use it on any acceptance path (verdict invariance is broken:
# 010-M M6-02/03, string/check/mutation/olean breach face).
VM014_WMEMO = os.environ.get("VM014_WMEMO", "0") != "0"


def build_step_graph():
    """Builds the micro-step transition graph. Returns (graph, outputs).

    outputs maps names to PersistDimension objects whose values the driver
    reads at the last sequence position:
      done, result_pos                          machine stop
      em_pend/em_link/em_frame/em_frame2        emission flags (0/1)
      em_lithead/em_gap/em_litdig/em_const      emission flags (0/1)
      pend_V0, pend_prev, pend_env              PEND payload
      link_V0, link_V1(depth), link_prev, link_env   LINK payload
      frame_task, frame_V1, frame_V2, frame_X   FRAME payload (slot 1)
      frame2_task, frame2_V1, frame2_V2, frame2_X    FRAME payload (slot 2)
      head_V0, head_V2, head_X                  LIT head emission payload
      dig_V0, const_cid                         LIT_DIG / CONST payload
      A, B, C, D, E, F                          next STATE fields
    Emission order (driver contract): pend, link, frame, frame2, lithead,
    gap, litdig, const, then the STATE token. Branches emit at most four
    tokens and never mix incompatible sets, so emission positions are
    static per branch.
    """
    reset_graph()

    k_ = InputDimension("k")
    v0_ = InputDimension("v0")
    v1_ = InputDimension("v1")
    v2_ = InputDimension("v2")
    x_ = InputDimension("x")
    e2_ = InputDimension("e2")
    f2_ = InputDimension("f2")
    _all_dims.extend([k_, v0_, v1_, v2_, x_, e2_, f2_])

    One = Expression({_one_dim: 1})
    Zero = Expression()
    def _fv0(pos):
        """V0 at a possibly-NULL pointer. Position 0 is the T_NULL
        sentinel and its V0 now holds n_consts (ENV_FORMAT §2.7), so a
        fetch through the NULL pointer must yield 0, not that payload.
        Without this guard the nat-compute chain-length reads (nC/nF...)
        would see n_consts instead of an empty chain."""
        return _select(_geq_expr(pos, One),
                       fetch_by_position([v0_], pos)[0], Zero)
    POS = Expression({_position_dim: 1})

    # STATE token fields live in the payload dims (VM_SPEC §10.1)
    SA = Expression({v0_: 1})
    SB = Expression({v1_: 1})
    SC = Expression({v2_: 1})
    SD = Expression({x_: 1})
    SE = Expression({e2_: 1})
    SF = Expression({f2_: 1})

    def out(expr, name):
        p = persist(expr, name=name)
        return next(iter(p.terms))

    # ── fetches ──────────────────────────────────────────────────────────────
    # token at position SA: the focus (main), current LINK (walk) or the v2
    # chain head (nat compute)
    fK, fV0, fV1, fV2, fX = fetch_by_position([k_, v0_, v1_, v2_, x_], SA)
    # pend top at position SC (valid iff SC >= 1; position 0 is NULL)
    pV0, pV1, pV2, pX = fetch_by_position([v0_, v1_, v2_, x_], SC)
    # second pend (arity-2 nat op arg2)
    qV0, qV2, qX = fetch_by_position([v0_, v2_, x_], pV2)
    # ENV header for const cid: headers occupy positions cid+1 (C-scheme)
    eV0, eV1, eV2, eX = fetch_by_position([v0_, v1_, v2_, x_], fV0 + One)
    # env chain head depth (LINK V1 at position SB; NULL yields 0)
    dV1 = fetch_by_position([v1_], SB)[0]
    # frame head at position SD (valid iff SD >= 1)
    frV0, frV1, frV2, frX = fetch_by_position([v0_, v1_, v2_, x_], SD)
    # frame payload slots 6/7 (Phase 5 M2: ST continuation id, DEFEQ s-side,
    # WHNF soft flag, INFER phase)
    frE2, frF2 = fetch_by_position([e2_, f2_], SD)
    # focus E2 field (T_PI_CLO body env; LINK binder-marker flag on walks)
    fE2 = fetch_by_position([e2_], SA)[0]
    # frame beneath an ST frame (the NAT control frame), and the caller two
    # frames down (arity-2 compute pops D->ST'->NAT'->caller)
    nbV0, nbV1, nbV2, nbX = fetch_by_position([v0_, v1_, v2_, x_], frV2)
    ncV2 = fetch_by_position([v2_], nbV2)[0]
    nbE2 = fetch_by_position([e2_], frV2)[0]   # parent WHNF frame soft flag
    nbF2 = fetch_by_position([f2_], frV2)[0]   # parent ST continuation id
    # P7.5c-2 soft-infer flag as seen through a walk ST's V2.  The soft flag
    # lives ONLY on a TASK_INFER frame (PI_T/PI_TY set F2=1); walk STs under a
    # HARD infer carry V2 = their continuation (not the task frame), so a bare
    # `f2_ @ frV2` there reads the continuation's phase id and would be
    # misread as "soft".  Gate on the V2-target being a TASK_INFER frame so the
    # read is 1 only for a genuine proof-irrel chain and 0 for every hard
    # infer (else a hard run_check value-infer reject is swallowed → m_mk_field).
    soft_flag = reglu(_geq_expr(nbF2, One), _kind_eq_raw(nbV0, TASK_INFER, One))

    # ══ WP8: data-driven constant identity (ENV_FORMAT §2.3-§2.7) ═══════════
    # WP1 metadata anchors live at anchor(cid) = T_NULL.V0 + 1 + cid; each
    # T_ENV_META carries V1=constant_info_kind, V2=meta_head, X=flags, and a
    # Constructor's meta_head is a T_ENV_CTORVAL token (V1=induct_cid,
    # V2=cidx, X=nparams, E2=nfields).  The predicates below identify
    # Nat.zero / Nat.succ / Bool ctors / structures from that data instead of
    # the toy cid order, so a name-sorted (import_env_meta) environment gives
    # the same verdicts (KERNEL_COVERAGE §5, WP8).  Legacy streams built
    # without metadata have all-zero anchors: the predicates then fall back to
    # the toy cids, keeping `import_env` streams working.
    _NSCAN = 96            # unrolled cid-scan bound (envs here are < 96 consts)

    def _anc(cid):
        return _to_expr(fetch_by_position([v0_], Zero)[0]) + One + cid

    def _mhead(cid):
        return fetch_by_position([v2_], _anc(cid))[0]

    def _mkind(cid):
        return fetch_by_position([v1_], _anc(cid))[0]

    def _mflags(cid):
        return fetch_by_position([x_], _anc(cid))[0]

    def _no_meta(cid):
        """1 iff cid carries no WP1 metadata (legacy import_env stream)."""
        return reglu(_eq_expr(_mhead(cid), Zero), _eq_expr(_mkind(cid), Zero))

    def _ctor_bind(cid):
        """(induct_cid, cidx, nfields, is_ctorval) from anchor(cid).V2."""
        h = _mhead(cid)
        return (fetch_by_position([v1_], h)[0],
                fetch_by_position([v2_], h)[0],
                fetch_by_position([e2_], h)[0],
                _kind_eq_raw(fetch_by_position([k_], h)[0], T_ENV_CTORVAL, One))

    def _is_rec_ind(icid):
        """1 iff the inductive icid has the is_rec flag (Nat/CovTree, not
        Bool/P2/UnitT).  Reads anchor(icid).X bit6 (ENV_F_IS_REC)."""
        return _geq_expr(_mflags(icid), One * ENV_F_IS_REC)

    def _ctor_meta(cidx, nf, want_rec):
        """Metadata-only constructor predicate (no cid fallback)."""
        def pred(cid):
            ind, c, n, ok = _ctor_bind(cid)
            p = reglu(reglu(ok, _eq_expr(c, One * cidx)), _eq_expr(n, One * nf))
            return reglu(p, _is_rec_ind(ind) if want_rec
                         else One - _is_rec_ind(ind))
        return pred

    def _ctor_site(cid, pred, fallback):
        """pred(cid) when metadata is present, else cid == toy fallback."""
        return _select(reglu(_no_meta(cid), One),
                       _eq_expr(cid, Expression({_one_dim: fallback})), pred(cid))

    def _is_zero(cid):
        return _ctor_site(cid, _ctor_meta(0, 0, True), CID_ZERO)

    def _is_succ(cid):
        return _ctor_site(cid, _ctor_meta(1, 1, True), CID_SUCC)

    def _is_false(cid):
        return _ctor_site(cid, _ctor_meta(0, 0, False), CID_FALSE)

    def _is_true(cid):
        return _ctor_site(cid, _ctor_meta(1, 0, False), CID_TRUE)

    def _is_struct_ctor2(cid):
        """Non-recursive 0-param 2-field constructor, first ctor (P2.mk shape).
        Reads T_ENV_CTORVAL cidx/nfields (V2/E2) and the owning inductive's
        nparams (T_ENV_INDVAL.V1) + is_rec flag (anchor(induct).X bit6)."""
        ind, c, n, ok = _ctor_bind(cid)
        np = fetch_by_position([v1_], _mhead(ind))[0]
        p = reglu(reglu(reglu(reglu(ok, _eq_expr(c, Zero)),
                              _eq_expr(n, One * 2)),
                        One - _is_rec_ind(ind)), _eq_expr(np, Zero))
        return _select(reglu(_no_meta(cid), One),
                       _eq_expr(cid, Expression({_one_dim: CID_P2MK})), p)

    def _struct_ind(cid):
        """induct_cid of a constructor cid (legacy fallback CID_P2)."""
        return _select(reglu(_no_meta(cid), One),
                       Expression({_one_dim: CID_P2}),
                       fetch_by_position([v1_], _mhead(cid))[0])

    def _struct_nid(cid):
        """Structure name nid from the inductive's INDEXTRA.all list head
        (T_ENV_INDVAL.F2 -> T_ENV_INDEXTRA.V1 -> T_ENV_LIST.V1).  Replaces the
        hardcoded NID_P2 with the Proj token's own sname source (legacy
        fallback NID_P2)."""
        ind = _struct_ind(cid)
        extra = fetch_by_position([f2_], _mhead(ind))[0]
        allh = fetch_by_position([v1_], extra)[0]
        return _select(reglu(_no_meta(cid), One),
                       Expression({_one_dim: NID_P2}),
                       fetch_by_position([v1_], allh)[0])

    def _induct_nid(icid):
        """Name nid of an *inductive* cid (T_ENV_META.V2 -> INDVAL.F2 ->
        INDEXTRA.V1 -> LIST.V1).  Legacy fallback NID_P2."""
        extra = fetch_by_position([f2_], _mhead(icid))[0]
        allh = fetch_by_position([v1_], extra)[0]
        return _select(reglu(_no_meta(icid), One),
                       Expression({_one_dim: NID_P2}),
                       fetch_by_position([v1_], allh)[0])

    def _is_induct(cid, want_rec):
        h = _mhead(cid)
        ok = _kind_eq_raw(fetch_by_position([k_], h)[0], T_ENV_INDVAL, One)
        np = fetch_by_position([v1_], h)[0]
        ni = fetch_by_position([v2_], h)[0]
        p = reglu(reglu(ok, _eq_expr(np, Zero)), _eq_expr(ni, Zero))
        return reglu(p, _is_rec_ind(cid) if want_rec
                     else One - _is_rec_ind(cid))

    def _is_struct_induct(cid):
        """Non-recursive 0-param 0-index *structure* inductive, identified from
        metadata (legacy fallback CID_P2).  Used by the projection-type peel,
        whose ctor Pi-spine source mk_ty is still the one legacy site."""
        return _select(reglu(_no_meta(cid), One),
                       _eq_expr(cid, Expression({_one_dim: CID_P2})),
                       _is_induct(cid, False))

    def _quot_kind(cid):
        """quot_kind of a Quot constant (declaration.h:388: Type=0 Mk=1 Lift=2
        Ind=3), read from the T_ENV_QUOTVAL token at anchor(cid).V2
        (ENV_FORMAT §2.4).  Returns 0 for a non-Quot cid / a legacy no-metadata
        stream, so no hardcoded Quot cid is ever needed.  This is the graph's
        runtime replacement for the kernel's name comparison against
        `Quot.lift` / `Quot.ind` / `Quot.mk` (K/quot.h:45-61)."""
        h = _mhead(cid)
        ok = _kind_eq_raw(fetch_by_position([k_], h)[0], T_ENV_QUOTVAL, One)
        return reglu(ok, fetch_by_position([v1_], h)[0])

    # cid lookup by name-keyed ENV_HDR.X opcode, via a single unrolled scan
    # over the header block (positions cid+1).  Depth is constant: each
    # candidate is an independent term and the result is a linear sum, not a
    # select chain.  One V0/T_NULL read gives n for the in-range mask; one X
    # fetch per candidate feeds every op accumulator (no re-fetch per op).
    _nc = _to_expr(fetch_by_position([v0_], Zero)[0])       # T_NULL.V0 = n
    _inrange = [_geq_expr(_nc, One * (c + 1)) for c in range(_NSCAN)]
    _SCAN_OPS = (OP_SUCC, OP_PRED, OP_REC, OP_TRUE, OP_FALSE,
                 OP_OFLIST, OP_STRING)
    _scan_acc = {op: Zero for op in _SCAN_OPS}
    _scan_cnt = {op: Zero for op in _SCAN_OPS}
    for c in range(_NSCAN):
        # absolute header position cid+1: the lookup query must be the plain
        # constant position (`One * (c + 1)`); `POS + One*c` would set the
        # position coefficient to 1 and read the wrong slot.
        xx = fetch_by_position([x_], One * (c + 1))[0]
        hit = _inrange[c]
        for op in _SCAN_OPS:
            m = reglu(hit, _eq_expr(xx, One * op))
            _scan_acc[op] = _scan_acc[op] + m * c
            _scan_cnt[op] = _scan_cnt[op] + m
    _SUCC_CID = _scan_acc[OP_SUCC]         # Nat.succ (name-keyed X=1)
    _PRED_CID = _scan_acc[OP_PRED]         # Nat.pred (X=2)
    _REC_CID = _scan_acc[OP_REC]           # Nat.rec  (X=11)
    # Existence must come from the match COUNT, not ``cid >= 1``: cid 0 is a
    # valid constant and a name-sorted table can put Nat.pred / Nat.rec there.
    _SUCC_OK = _geq_expr(_scan_cnt[OP_SUCC], One)
    _PRED_OK = _geq_expr(_scan_cnt[OP_PRED], One)
    _REC_OK = _geq_expr(_scan_cnt[OP_REC], One)
    # WP8-H5: the beq/ble machine synthesizes a Bool literal whose V0 must be
    # the real Bool.true / Bool.false cid (it is classified by the metadata
    # predicates _is_true/_is_false in the Bool.casesOn path and compared
    # against Const(Bool.true/false) in defeq).  The cids are found from the
    # name-keyed ENV_HDR.X tags (CTOR_ID_CODES) in the same scan; a stream built
    # before those tags (or without Bool ctors) has count 0 and falls back to
    # the toy cids, keeping legacy streams working.
    _TRUE_CID = _select(_geq_expr(_scan_cnt[OP_TRUE], One),
                        _scan_acc[OP_TRUE],
                        Expression({_one_dim: CID_TRUE}))
    _FALSE_CID = _select(_geq_expr(_scan_cnt[OP_FALSE], One),
                         _scan_acc[OP_FALSE],
                         Expression({_one_dim: CID_FALSE}))
    # WP5 (E3/E4): cids of the two string handles, name-keyed like the Bool
    # ctors.  NO legacy fallback: an environment without "String.ofList"
    # (e.g. a toy env) simply never fires the ofList defeq redirect arm, and
    # one without "String" makes string-literal inference REJECT (the kernel
    # would not type such a term either — it could not even be built).
    _OFLIST_OK = _geq_expr(_scan_cnt[OP_OFLIST], One)
    _OFLIST_CID = _scan_acc[OP_OFLIST]
    _STRING_OK = _geq_expr(_scan_cnt[OP_STRING], One)
    _STRING_CID = _scan_acc[OP_STRING]
    # Nat's cid = the inductive owning the name-tagged Nat.succ ctor (used to
    # build Const(Nat) for a literal's inferred type).  In a legacy stream with
    # no WP1 metadata the owning-inductive read is meaningless, so fall back to
    # the toy CID_NAT explicitly (not through _struct_ind, whose own no-meta
    # fallback is the P2 structure cid).
    _NAT_CID = _select(reglu(_no_meta(_SUCC_CID), One),
                       Expression({_one_dim: CID_NAT}),
                       _select(_SUCC_OK,
                               _struct_ind(_SUCC_CID),
                               Expression({_one_dim: CID_NAT})))
    # WP4: environment::is_quot_initialized() equivalent (K/environment.cpp:66,
    # mark at K/quot.cpp:102) — 1 iff the token environment carries at least one
    # Quot constant (CK_QUOT metadata).  The quot reduction is gated on it, as
    # reduce_recursor gates on env().is_quot_initialized() (K/type_checker.cpp:394).
    _QUOT_INIT = Zero
    for _c in range(_NSCAN):
        _QUOT_INIT = _QUOT_INIT + reglu(
            _inrange[_c],
            _kind_eq_raw(_mkind(_c), CK_QUOT, One))

    def _is_unit_induct(cid):
        """Non-recursive, 0-param/0-index inductive with EXACTLY ONE constructor
        and that constructor has 0 fields — the kernel's unit-like structure
        test (is_non_rec_structure -> get_cnstrs().head -> nfields==0,
        K/type_checker.cpp:1159).  WP1 has no inductive->ctor cid link, so the
        ctor count and the ctor's nfields are read by scanning the per-cid
        T_ENV_CTORVAL tokens (anchor(c).V2 = CTORVAL; V1=induct_cid, E2=nfields):
        count the ctors whose induct_cid == cid and flag any with nfields>0.
        This excludes both Bool (2 ctors) and P2 (1 ctor, nfields=2).  Legacy
        no-metadata streams fall back to the toy cid."""
        cnt, bad = Zero, Zero
        for c in range(_NSCAN):
            h = _mhead(c)
            ok = _kind_eq_raw(fetch_by_position([k_], h)[0], T_ENV_CTORVAL, One)
            ind = fetch_by_position([v1_], h)[0]
            nf = fetch_by_position([e2_], h)[0]
            m = reglu(reglu(ok, _eq_expr(ind, cid)), _inrange[c])
            cnt = cnt + m
            bad = bad + reglu(m, One - _eq_expr(nf, Zero))
        return _select(reglu(_no_meta(cid), One),
                       _eq_expr(cid, Expression({_one_dim: CID_UNITT})),
                       reglu(_is_induct(cid, False),
                             reglu(_eq_expr(cnt, One),
                                   One - _geq_expr(bad, One))))

    # nat op gates from the frame's op code (valid in compute mode)
    opg1 = _kind_eq_raw(frV1, OP_SUCC, One)
    opg2 = _kind_eq_raw(frV1, OP_PRED, One)
    opg3 = _kind_eq_raw(frV1, OP_ADD, One)
    opg4 = _kind_eq_raw(frV1, OP_SUB, One)
    opg5 = _kind_eq_raw(frV1, OP_MUL, One)
    opg6 = _kind_eq_raw(frV1, OP_POW, One)
    opg7 = _kind_eq_raw(frV1, OP_DIV, One)
    opg8 = _kind_eq_raw(frV1, OP_MOD, One)
    opg9 = _kind_eq_raw(frV1, OP_BEQ, One)
    opg10 = _kind_eq_raw(frV1, OP_BLE, One)
    is_pow_o = opg6
    is_mul_o = opg5
    is_mod_o = opg8

    # nat-compute digit fetches (see per-phase sections below)
    arity2c = One - opg1 - opg2               # every op except succ/pred
    v1pos = _select(arity2c, nbV1, SA)        # arity-2: ST'.V1 / arity-1: A
    c1K = fetch_by_position([k_], v1pos)[0]
    c1V0 = _fv0(v1pos)
    # WP5: a nat-op argument must be a NAT literal.  Since E1, string
    # literals share the K_LIT kind (V1=1, V0=byte count, stride-2 byte
    # chain); reading one as a decimal digit chain would violate the
    # kernel's is_nat_expr test (whnf_nat_op_core), so every K_LIT-as-Nat
    # gate below additionally requires V1 == LIT_NAT (0).
    c1V1 = fetch_by_position([v1_], v1pos)[0]
    g1V0 = _fv0(v1pos + One * 2 + SB * 2)
    g2V0 = _fv0(SA + One * 2 + SB * 2)
    is_z1 = reglu(_kind_eq_raw(c1K, K_CONST, One),
                  _is_zero(c1V0))
    is_lit1 = reglu(_kind_eq_raw(c1K, K_LIT, One), _eq_expr(c1V1, Zero))
    n1 = _select(is_lit1, c1V0, One)   # zero-const: 1 digit (value 0)
    is_z2 = reglu(_kind_eq_raw(fK, K_CONST, One),
                  _is_zero(fV0))
    is_lit2 = reglu(_kind_eq_raw(fK, K_LIT, One), _eq_expr(fV1, Zero))
    n2 = _select(is_lit2, fV0, One)   # zero-const: 1 digit (value 0)
    # C-head (acc / R / Q) and F-head (output chain) fields
    nC = _fv0(SC)
    aCC = _fv0(SC + One * 2 + SB * 2)
    nF = _fv0(SF)
    xF = fetch_by_position([x_], SF)[0]
    iF = Expression({fetch_by_position([v2_], SF)[0]: 1})  # row index i
    b0raw = _fv0(SA + One * 2)   # b chain digit 0
    bkJ = _fv0(SA + One * 2 + SB * 2)  # A digit at k
    # mul/pow cell: multiplier side (m) and addend side (x) chains
    m_head = _select(is_pow_o, frV2, nbV1)    # pow: frame V2 = round acc
    mL = _fv0(m_head)
    m_i_raw = _fv0(m_head + One * 2 + iF * 2)
    # pow: a = ST'.V1, with ST' pos threaded through the row head X field;
    # mul: b = A directly
    pow_st = fetch_by_position([x_], SF)[0]            # row head X = ST' pos
    pow_a = fetch_by_position([v1_], pow_st)[0]        # ST'.V1 = a chain head
    pow_a_V0 = _fv0(pow_a)
    pow_a_K = fetch_by_position([k_], pow_a)[0]
    pow_a_V1 = fetch_by_position([v1_], pow_a)[0]
    is_za = reglu(_kind_eq_raw(pow_a_K, K_CONST, One),
                  _is_zero(pow_a_V0))
    is_la = reglu(_kind_eq_raw(pow_a_K, K_LIT, One),
                  _eq_expr(pow_a_V1, Zero))
    n_a = _select(is_la, pow_a_V0, One)
    caller_c = _select(arity2c, ncV2, frV2)   # arity-2: 2-hop / arity-1: direct
    x_head = _select(is_pow_o, pow_a, SA)     # pow: a (ST'.V1); mul: b (A)
    x_n = _select(is_pow_o, n_a, n2)
    xJ = _fv0(x_head + One * 2 + (SB - iF) * 2)

    has_frame = _geq_expr(SD, One)
    is_walk_frame = reglu(_kind_eq_raw(frV0, TASK_WALK, One), has_frame)
    is_st_frame = reglu(_kind_eq_raw(frV0, TASK_ST, One), has_frame)
    is_nat_frame = reglu(_kind_eq_raw(frV0, TASK_NAT, One), has_frame)
    is_compute = reglu(is_nat_frame, _geq_expr(frX, 3))
    # P6.5 iota rhs build loop: a NAT frame with op=OP_REC and X=2 owns the
    # step (excluded from main_mode below, like is_compute).
    is_build = reglu(is_nat_frame, reglu(_eq_expr(frX, One * 2),
                   _kind_eq_raw(frV1, OP_REC, One)))
    # P7.5b casesOn succ-rule build loop: NAT frame, op=OP_CASESON, X=2.
    # Emits `succ_minor (Nat.pred t)` in 3 raw steps (see cs_build below).
    is_cs_build = reglu(is_nat_frame, reglu(_eq_expr(frX, One * 2),
                      _kind_eq_raw(frV1, OP_CASESON, One)))
    # P7.5b-3 P2.casesOn build loop gate: NAT frame, op=OP_CASESON_P2, X=2.
    # Unreachable: p2_succ_r now delivers directly (no X=2 frame is ever
    # pushed), because the loop's flat `alt a b` reification cannot carry the
    # fields' own envs. Wires kept below for graph stability.
    is_cs_build_p2 = reglu(is_nat_frame, reglu(_eq_expr(frX, One * 2),
                         _kind_eq_raw(frV1, OP_CASESON_P2, One)))
    # WP3 general recursor iota build loop: NAT frame, op=OP_IOTA, X=2.
    # Emits one T_PEND per step (the rhs argument chain, §13.2 step 9) then
    # hands the machine a focus=rhs/C=chain spine to beta-reduce.  Unlike the
    # hardcoded OP_REC loop it reads all counts/rules from WP1 metadata.
    iota_build_raw = reglu(is_nat_frame,
                           reglu(_geq_expr(frX, One * 2),
                                 _kind_eq_raw(frV1, OP_IOTA, One)))
    is_iota_build = iota_build_raw
    # Phase 5 M2 task frames + the continuation protocol: a result in (A,B)
    # with E=1 is delivered through ST frames carrying a continuation id in
    # F2 (CONT mode); TASK frames (WHNF/INFER/DEFEQ/LEVEL) are popped.
    is_infer_frame = reglu(_kind_eq_raw(frV0, TASK_INFER, One), has_frame)
    is_defeq_frame = reglu(_kind_eq_raw(frV0, TASK_DEFEQ, One), has_frame)
    is_whnf_frame = reglu(_kind_eq_raw(frV0, TASK_WHNF, One), has_frame)
    is_level_frame = reglu(_kind_eq_raw(frV0, TASK_LEVEL, One), has_frame)
    # Phase 5 M4.2: CHECK anchor frames (kernel `check` driver loop). A CHECK
    # frame is the loop anchor for ONE declaration: V1 = declared type root,
    # X = value root, V2 = next anchor (0 = last). It is NOT a pop_task frame:
    # the kickoff pushes an ST continuation (F2=CK_TY) whose caller chain
    # skips the anchor to the NEXT one, so CK_RES advances by pointing D at
    # the ST's own V2.
    is_check_frame = reglu(_kind_eq_raw(frV0, TASK_CHECK, One), has_frame)
    is_task_frame = (is_infer_frame + is_defeq_frame + is_whnf_frame
                     + is_level_frame)
    ret_pending = reglu(_eq_expr(SE, One),
                        One - is_walk_frame - is_compute - is_iota_build)
    cont_mode = reglu(ret_pending, reglu(is_st_frame, _geq_expr(frF2, One)))
    resume_mode = reglu(One - ret_pending,
                        reglu(is_st_frame, _geq_expr(frF2, One)))
    st2_mode = cont_mode + resume_mode
    main_mode = (One - is_walk_frame - is_compute - is_build - is_cs_build
                 - is_cs_build_p2 - is_iota_build
                 - is_infer_frame
                 - is_defeq_frame - is_level_frame - is_check_frame - st2_mode)
    # CHECK kickoff: D = anchor, no result in flight → start infer(value)
    ck_kick = reglu(is_check_frame, One - ret_pending)
    walk_more = reglu(is_walk_frame, _geq_expr(frX, One))

    # ── kind gates (main mode) ──────────────────────────────────────────────
    is_app = _kind_eq_raw(fK, K_APP, One)
    is_lam = _kind_eq_raw(fK, K_LAM, One)
    is_const = _kind_eq_raw(fK, K_CONST, One)
    is_let = _kind_eq_raw(fK, K_LET, One)
    is_bvar = _kind_eq_raw(fK, K_BVAR, One)
    is_mdata = _kind_eq_raw(fK, K_MDATA, One)
    is_stuck = (_kind_eq_raw(fK, K_SORT, One)
                + _kind_eq_raw(fK, K_FVAR, One)
                + _kind_eq_raw(fK, K_MVAR, One)
                + _kind_eq_raw(fK, K_LIT, One)
                + _kind_eq_raw(fK, K_PI, One)
                + _kind_eq_raw(fK, T_PI_CLO, One))
    # Phase 5 M3: PROJ is no longer a stuck leaf — whnf reduces a fully
    # applied non-rec-structure ctor to the projected field (kernel
    # reduce_proj_core). proj_setup (main mode) whnf's the child, then the
    # I_PROJ continuation extracts the field or re-sticks the proj token.
    is_proj = _kind_eq_raw(fK, K_PROJ, One)
    proj_setup = reglu(is_proj, main_mode)

    pend_nonempty = _geq_expr(SC, One)
    lam_apply = reglu(reglu(is_lam, pend_nonempty), main_mode)
    const_delta = reglu(reglu(is_const, _geq_expr(eV2, One)), main_mode)

    # nat op dispatch (VM_SPEC §10.2): ENV_HDR X = op code (0 = not a nat op)
    natop = reglu(is_const, _geq_expr(eX, One))
    op_arity1 = _kind_eq_raw(eX, OP_SUCC, One) + _kind_eq_raw(eX, OP_PRED, One)
    # WP6-F: 20..25 join the arity-2 set (gcd/land/lor/xor/shiftLeft/
    # shiftRight, K/type_checker.cpp:702-733); 11..19 stay non-firing.
    op_arity2 = (reglu(_geq_expr(eX, OP_ADD), One - _geq_expr(eX, 11))
                 + reglu(_geq_expr(eX, OP_GCD),
                         One - _geq_expr(eX, OP_SHR + One)))
    has2 = _geq_expr(pV2, One)
    fire2 = reglu(reglu(natop, op_arity2), reglu(pend_nonempty, has2))
    fire1 = reglu(reglu(natop, op_arity1), pend_nonempty)

    # ── P6.5 iota: Nat.rec dispatch (kernel inductive_reduce_rec) ───────────
    # ENV_HDR.X = OP_REC gates the recursor const; major_idx=3 means the
    # spine is [.., maj, s, z, m] with m the pend head. The PEND chain is
    # the closure store (append-only, immutable): fire_rec pops the 4
    # entries (C = extras) and starts a sub-whnf of the major premise under
    # a NAT(OP_REC, caller, 1) frame carrying E2 = spine root (§10.2 stuck
    # delivery) and F2 = m entry (the chain to re-read m/z/s/maj from).
    sV0, sX, sV2 = fetch_by_position([v0_, x_, v2_], qV2)
    majV0, majX, majV2 = fetch_by_position([v0_, x_, v2_], sV2)
    recop = reglu(is_const, _kind_eq_raw(eX, OP_REC, One))
    fire_rec = reglu(recop, _geq_expr(sV2, One))   # 4th entry (maj) present

    # ── P7.5b casesOn: Nat.casesOn dispatch (major_idx=0) ───────────────────
    # spine (application order) = [t, motive, zero, succ]; t is applied first
    # → pushed last → the PEND HEAD (SC). Chain via V2: SC=t, t.V2=motive,
    # motive.V2=zero, zero.V2=succ, succ.V2=extras. fire_caseson pops the 4
    # entries and starts a sub-whnf of t under a NAT(OP_CASESON, caller, 1)
    # frame carrying E2 = spine root (§10.2 stuck delivery) and F2 = t entry
    # (the chain to re-read motive/zero/succ from).
    cs_mot = fetch_by_position([v0_, x_, v2_], pV2)          # motive entry
    cs_zero = fetch_by_position([v0_, x_, v2_], cs_mot[2])   # zero entry
    cs_succ = fetch_by_position([v0_, x_, v2_], cs_zero[2])  # succ entry
    csonop = reglu(is_const, _kind_eq_raw(eX, OP_CASESON, One))
    fire_caseson = reglu(csonop, _geq_expr(cs_zero[2], One))  # succ entry present

    # ── P7.5b-3 P2.casesOn dispatch (major_idx=0, 3-entry spine) ─────────────
    # spine = [t, motive, alt]; chain SC=t, t.V2=motive, motive.V2=alt,
    # alt.V2=extras. fire pops the 3 entries, sub-whnfs t under a
    # NAT(OP_CASESON_P2, caller, 1) frame (E2=spine root, F2=t entry).
    p2_mot = fetch_by_position([v0_, x_, v2_], pV2)         # motive entry
    p2_alt = fetch_by_position([v0_, x_, v2_], p2_mot[2])   # alt entry
    csonop_p2 = reglu(is_const, _kind_eq_raw(eX, OP_CASESON_P2, One))
    fire_p2 = reglu(csonop_p2, _geq_expr(p2_mot[2], One))   # alt entry present

    # ── P7.5b-4 Bool.casesOn dispatch (major_idx=0, 4-entry spine) ────────────
    # spine = [t, motive, false, true]; chain SC=t, t.V2=motive,
    # motive.V2=false, false.V2=true, true.V2=extras. fire pops the 4 entries,
    # sub-whnfs t under a NAT(OP_CASESON_BOOL, caller, 1) frame (E2=spine root,
    # F2=t entry). Both minors are 0-field → no build loop (select & continue).
    b_mot = fetch_by_position([v0_, x_, v2_], pV2)          # motive entry
    b_false = fetch_by_position([v0_, x_, v2_], b_mot[2])   # false minor entry
    b_true = fetch_by_position([v0_, x_, v2_], b_false[2])  # true minor entry
    csonop_bool = reglu(is_const, _kind_eq_raw(eX, OP_CASESON_BOOL, One))
    fire_bool = reglu(csonop_bool, _geq_expr(b_false[2], One))  # true entry present

    # ══ WP3 general recursor iota (VM_SPEC §13) ════════════════════════════
    # Data-driven replacement for the per-cid iota dispatch: any constant whose
    # T_ENV_META anchor says constant_info_kind == Recursor is reduced by
    # reading nparams/nindices/nmotives/nminors from T_ENV_RECVAL, matching the
    # major's constructor against the T_ENV_RULE chain, and applying the rule
    # rhs to (params, motives, minors) then the major's fields (kernel
    # inductive_reduce_rec, K/inductive.h:77-121).  No constant id is hardcoded
    # on this path; the binder order/widths come from the metadata stream.
    #
    # Bounds: the micro-step graph unrolls the metadata/rule/spine chain walks
    # to fixed depths (a runtime loop over them would need storage the frame
    # lacks).  Corpus arities are far below these; exceeding them yields the
    # "stuck" spine, never a wrong reduction.
    PMM_MAX, CHAIN_MAX, RULE_MAX, NF_MAX, SPINE_MAX = 8, 16, 16, 4, 12

    def _chain_v2(head, nmax):
        """[head, head.V2, head.V2.V2, …] (length nmax+1); position 0 is the
        NULL sentinel whose V2 is 0, so the walk self-terminates."""
        nodes = [head]
        for _ in range(nmax):
            nodes.append(fetch_by_position([v2_], nodes[-1])[0])
        return nodes

    def _chain_f2(head, nmax):
        """T_ENV_RULE chain: next rule lives in F2 (ENV_FORMAT §2.5)."""
        nodes = [head]
        for _ in range(nmax):
            nodes.append(fetch_by_position([f2_], nodes[-1])[0])
        return nodes

    def _chain_v0(root, nmax):
        nodes = [root]
        for _ in range(nmax):
            nodes.append(fetch_by_position([v0_], nodes[-1])[0])
        return nodes

    def _pick(nodes, idx):
        r = nodes[-1]
        for i in range(len(nodes) - 2, -1, -1):
            r = _select(_eq_expr(idx, One * i), nodes[i], r)
        return r

    def _head_of(root, dmax):
        """get_app_fn: follow V0 while the node is an App."""
        cur = root
        for _ in range(dmax):
            k = fetch_by_position([k_], cur)[0]
            cur = _select(_kind_eq_raw(k, K_APP, One),
                          fetch_by_position([v0_], cur)[0], cur)
        return cur

    def _app_arity(root, dmax):
        """get_app_num_args: number of App layers from `root` following V0,
        capped at dmax.  Used by the quot reduction, where the kernel requires
        `get_app_num_args(mk) == 3` (K/quot.h:61)."""
        cnt = Zero
        cur = root
        for _ in range(dmax):
            k = fetch_by_position([k_], cur)[0]
            ap = _kind_eq_raw(k, K_APP, One)
            cnt = cnt + ap
            cur = _select(ap, fetch_by_position([v0_], cur)[0], cur)
        return cnt

    def _rec_meta(cid):
        """Read the per-cid T_ENV_META anchor (ENV_FORMAT §2.7 layout: pos 0
        holds n_consts, anchor(cid) = n+1+cid) and the T_ENV_RECVAL /
        T_ENV_RECEXTRA fields hanging off it."""
        anc = _to_expr(fetch_by_position([v0_], Zero)[0]) + One + cid
        aK = fetch_by_position([k_], anc)[0]
        aV1 = fetch_by_position([v1_], anc)[0]
        aV2 = fetch_by_position([v2_], anc)[0]
        aX = fetch_by_position([x_], anc)[0]
        rv = aV2                                   # T_ENV_RECVAL head
        rvV1, rvV2, rvX, rvE2 = fetch_by_position([v1_, v2_, x_, e2_], rv)
        extra = fetch_by_position([f2_], rv)[0]    # T_ENV_RECEXTRA
        rules = fetch_by_position([v2_], extra)[0]  # RECEXTRA.V2
        pmm = _to_expr(rvV1) + _to_expr(rvX) + _to_expr(rvE2)   # np+nm+nmin
        return {"anchor_k": aK, "kind": aV1, "flags": aX, "rules": rules,
                "is_k": _geq_expr(aX, One * 256),  # ENV_F_IS_K (recursor
                #                                    # flags < 512, §2.3)
                "pmm": pmm, "majidx": pmm + rvV2}

    # main-mode dispatch gate: const + real Recursor metadata + not a
    # token-tagged Nat-op recursor (Nat.rec keeps its hand-written literal /
    # universe path; §13.7 item 4 documents the nat-literal gap for the
    # generic path).  eX is the T_ENV.X nat-op code (0 for every other const).
    gi_meta = _rec_meta(fV0)
    iotaop = reglu(is_const,
                   reglu(_eq_expr(gi_meta["kind"], One * CK_RECURSOR),
                         _kind_eq_raw(eX, 0, One)))
    gi_pend = _chain_v2(SC, CHAIN_MAX)
    gi_maj_entry = _pick(gi_pend, gi_meta["majidx"])
    gi_maj_v0 = _fv0(gi_maj_entry)
    gi_maj_env = fetch_by_position([x_], gi_maj_entry)[0]
    fire_iota = reglu(reglu(iotaop, _geq_expr(gi_maj_v0, One)),
                      reglu(_geq_expr(One * CHAIN_MAX, gi_meta["majidx"]),
                            _geq_expr(One * PMM_MAX, gi_meta["pmm"])))

    # ══ WP4 quot reduction (K/quot.h:39-70, C5 in KERNEL_COVERAGE) ═══════════
    # reduce_recursor runs quot_reduce_rec FIRST, then inductive_reduce_rec
    # (K/type_checker.cpp:393-407).  The head is a Quot constant, identified by
    # its WP1 metadata (T_ENV_META.V1 == CK_QUOT) and its T_ENV_QUOTVAL quot
    # kind: Lift=2 reduces like `Quot.lift`, Ind=3 like `Quot.ind` (the kernel
    # compares the head NAME against Quot.lift/Quot.ind, K/quot.h:45-53; name
    # equality is not available to the token VM, but the four Quot constants
    # have unique quot kinds, so the kind is equivalent).  Positions are the
    # kernel's fixed constants: Lift mk_pos=5/arg_pos=3, Ind mk_pos=4/arg_pos=3
    # (K/quot.h:46-50).  The machanism:
    #   fire  : sub-whnf args[mk_pos] under NAT(OP_QUOT, caller, 1);
    #   deliver: require its head == Quot.mk with EXACTLY 3 args
    #            (K/quot.h:59-62), then whnf reduces to `f (app_arg mk)` applied
    #            to the post-mk_pos args (`f = args[arg_pos]`, K/quot.h:64-68);
    #   stuck : any other mk result -> quot_reduce_rec returns none, so the
    #           whole application is stuck (this is the observable meaning of
    #           quot_is_stuck, K/quot.h:76-95).
    # f is re-read from the original pend chain saved in the frame (F2), since
    # the mk sub-whnf may clobber the live SC (the M5/V7.5c-M5 lesson).
    qk = _quot_kind(fV0)
    q_is_rec = _eq_expr(qk, One * 2) + _eq_expr(qk, One * 3)   # Lift / Ind
    q_mkpos = _select(_eq_expr(qk, One * 3), One * 4, One * 5)
    q_pend0 = _chain_v2(SC, CHAIN_MAX)
    q_mk_entry = _pick(q_pend0, q_mkpos)
    q_arg_entry = _pick(q_pend0, One * 3)                      # arg_pos = 3
    fire_quot = reglu(reglu(is_const,
                  reglu(_geq_expr(_QUOT_INIT, One),
                  reglu(q_is_rec, _kind_eq_raw(eX, 0, One)))),
                  reglu(_geq_expr(One * CHAIN_MAX, q_mkpos),
                  reglu(_geq_expr(_fv0(q_mk_entry), One),
                        _geq_expr(_fv0(q_arg_entry), One))))

    const_stuck = reglu(is_const, One - const_delta - fire1 - fire2
                        - fire_rec - fire_caseson - fire_p2 - fire_bool
                        - fire_iota - fire_quot)

    # value completion (main mode): stuck leaf / lam with empty pend / stuck
    # const. The spine-root convention (§10.2): with pending args the value
    # is the whole original spine (F), else the focus (A).
    lam_done = reglu(is_lam, One - pend_nonempty)
    complete = reglu(main_mode, is_stuck + lam_done + const_stuck)
    result_spine = reglu(pend_nonempty, _geq_expr(SF, One))
    v_done = _select(result_spine, SF, SA)
    e_done = SB

    # completion targets (the walk-marker halt term is added after the
    # WALK section, where mk_stuck is defined)
    halt = reglu(complete, One - has_frame)
    whnf_deliver = reglu(complete, is_whnf_frame)
    d12 = reglu(complete, reglu(is_st_frame, _eq_expr(nbX, One)))
    d23 = reglu(complete, reglu(is_st_frame, _eq_expr(nbX, 2)))
    dn1 = reglu(complete, reglu(is_nat_frame,
              reglu(_eq_expr(frX, One),
                    One - _kind_eq_raw(frV1, OP_REC, One)
                    - _kind_eq_raw(frV1, OP_CASESON, One)
                    - _kind_eq_raw(frV1, OP_CASESON_P2, One)
                    - _kind_eq_raw(frV1, OP_CASESON_BOOL, One)
                    - _kind_eq_raw(frV1, OP_IOTA, One)
                    - _kind_eq_raw(frV1, OP_QUOT, One))))
    # ── P6.5 iota: major-premise delivery under NAT(OP_REC, ., 1) ───────────
    # rec_dn: maj whnf COMPLETED (E=0) — classify (kernel nat_lit_to_
    # constructor / ctor check): decimal chain [0] or Const(Nat.zero) →
    # zero rule; lit v>0 → succ rule (build); other stuck leaf (Sort/Pi/lam)
    # → the recursor spine is stuck. rec_sd: maj arrived as a STUCK delivery
    # (E=1 — binder marker via mk_stuck, or a soft nat-op fallback) → the
    # whole rec spine is stuck, deliver the saved spine root.
    rec_dn = reglu(complete, reglu(is_nat_frame,
               reglu(_eq_expr(frX, One), _kind_eq_raw(frV1, OP_REC, One))))
    rec_sd = reglu(ret_pending, reglu(is_nat_frame,
               reglu(_eq_expr(frX, One), _kind_eq_raw(frV1, OP_REC, One))))
    # re-read the four closures from the pend chain (frF2 = m entry)
    rmV0 = _fv0(frF2)
    rmX = fetch_by_position([x_], frF2)[0]
    rzEntry = fetch_by_position([v2_], frF2)[0]
    rzV0 = _fv0(rzEntry)
    rzX = fetch_by_position([x_], rzEntry)[0]
    rsEntry = fetch_by_position([v2_], rzEntry)[0]
    rsV0 = _fv0(rsEntry)
    rsX = fetch_by_position([x_], rsEntry)[0]
    rmajEntry = fetch_by_position([v2_], rsEntry)[0]
    rmajV0 = _fv0(rmajEntry)
    rmajX = fetch_by_position([x_], rmajEntry)[0]
    # M5: the extras chain root (maj entry's V2), re-derived from the frame.
    # The major's whnf may run a nat compute that uses the pend as digit
    # scratch (clobbering SC); the iota result must still receive the extras.
    rec_extras = fetch_by_position([v2_], rmajEntry)[0]
    # WP5: NAT.rec/Nat.casesOn on a literal major — only a NAT literal is a
    # zero/succ candidate (kernel inductive_reduce_rec turns a STRING literal
    # into its ofList expansion and fails rule matching against Nat ctors;
    # the string-major reduction is the separate iota_str arm, §14.4).
    is_lit_r = reglu(_kind_eq_raw(fK, K_LIT, One), _eq_expr(fV1, Zero))
    # Padding-safe zero test. The graph's succ/pred compute emits PADDED
    # chains (digit count preserved through pred, e.g. [2,0,0] for 2 and
    # [0,0,0] for 0), so value==0 iff EVERY digit slot is 0. Scan the first
    # four digit slots (corpus bound: values < 10000; a longer chain falls
    # through to the succ rule — documented in VM_SPEC §11.8).
    _dz_r = [_fv0(SA + One * (2 + 2 * i))
             for i in range(4)]
    _nz_r = (reglu(_geq_expr(fV0, One), One - _eq_expr(_dz_r[0], Zero))
             + reglu(_geq_expr(fV0, One * 2), One - _eq_expr(_dz_r[1], Zero))
             + reglu(_geq_expr(fV0, One * 3), One - _eq_expr(_dz_r[2], Zero))
             + reglu(_geq_expr(fV0, One * 4), One - _eq_expr(_dz_r[3], Zero)))
    is_zlit_r = reglu(is_lit_r,
                      reglu(One - _geq_expr(fV0, One * 5),
                            One - _geq_expr(_nz_r, One)))
    is_zconst_r = reglu(_kind_eq_raw(fK, K_CONST, One),
                        _is_zero(fV0))
    zero_r = reglu(rec_dn, is_zlit_r + is_zconst_r)
    # The succ build loop reconstructs the rhs `s (Nat.pred major) (Nat.rec …)`
    # and must emit the real Nat.pred / Nat.rec cids (found by the header-X
    # name-keyed scan); if either is absent from the env the loop declines and
    # the spine stays stuck rather than emitting a bogus hardcoded cid.
    rec_ids_ok = reglu(_REC_OK, _PRED_OK)
    build_r = reglu(reglu(rec_dn, rec_ids_ok),
                    reglu(is_lit_r, One - is_zlit_r))
    stuck_r = reglu(rec_dn, One - zero_r - build_r)

    # ── P7.5b casesOn: major-premise delivery under NAT(OP_CASESON, ., 1) ────
    # Reuses the iota nat classification (is_zlit_r/is_zconst_r/is_lit_r read
    # the completed major in the focus). cs_zero_r → apply the zero minor;
    # everything else (succ-literal, other stuck leaf, or a stuck delivery
    # cs_sd) → the casesOn spine is stuck (deliver the saved spine root). The
    # succ rule (apply succ minor to Nat.pred t) lands in P7.5b increment 2.
    cs_dn = reglu(complete, reglu(is_nat_frame,
              reglu(_eq_expr(frX, One), _kind_eq_raw(frV1, OP_CASESON, One))))
    cs_sd = reglu(ret_pending, reglu(is_nat_frame,
              reglu(_eq_expr(frX, One), _kind_eq_raw(frV1, OP_CASESON, One))))
    # re-read minors from the pend chain (frF2 = t entry; t→motive→zero→succ)
    cs_motE = fetch_by_position([v2_], frF2)[0]          # motive entry
    cs_zeroE = fetch_by_position([v2_], cs_motE)[0]      # zero entry
    cs_succE = fetch_by_position([v2_], cs_zeroE)[0]     # succ entry
    rzV0_c = _fv0(cs_zeroE)       # zero minor pos
    rzX_c = fetch_by_position([x_], cs_zeroE)[0]         # zero minor env
    rsuccV0_c = _fv0(cs_succE)    # succ minor pos
    rsuccX_c = fetch_by_position([x_], cs_succE)[0]      # succ minor env
    cs_extras = fetch_by_position([v2_], cs_succE)[0]    # M5: extras chain root
    rtX_c = fetch_by_position([x_], frF2)[0]             # t (major) env, stuck
    cs_zero_r = reglu(cs_dn, is_zlit_r + is_zconst_r)
    # succ rule: major is a positive nat literal → build `succ_minor (pred t)`
    # (kernel nat_lit_to_constructor / inductive_reduce_casesOn succ branch).
    # Same metadata-driven pred-id gate as the Nat.rec build loop.
    cs_succ_r = reglu(reglu(cs_dn, rec_ids_ok),
                      reglu(is_lit_r, One - is_zlit_r))
    cs_stuck_r = reglu(cs_dn, One - cs_zero_r - cs_succ_r)

    # ── P7.5b-3 P2.casesOn: major delivery under NAT(OP_CASESON_P2, ., 1) ────
    # The major whnf's to a stuck `P2.mk a b` ctor app (focus SA = the outer
    # App). p2_ctor matches that shape (K_APP → K_APP → Const(CID_P2MK)); the
    # single minor `alt` is applied to the 2 fields → build `alt a b`. A
    # non-ctor completed major (or a stuck delivery p2_sd) → spine stuck.
    p2_dn = reglu(complete, reglu(is_nat_frame,
              reglu(_eq_expr(frX, One),
                    _kind_eq_raw(frV1, OP_CASESON_P2, One))))
    p2_sd = reglu(ret_pending, reglu(is_nat_frame,
              reglu(_eq_expr(frX, One),
                    _kind_eq_raw(frV1, OP_CASESON_P2, One))))
    # re-read the alt minor from the pend chain (frF2 = t entry; t→motive→alt)
    p2_motE = fetch_by_position([v2_], frF2)[0]           # motive entry
    p2_altE = fetch_by_position([v2_], p2_motE)[0]        # alt entry
    p2_altV0 = _fv0(p2_altE)       # alt minor pos
    p2_altX = fetch_by_position([x_], p2_altE)[0]         # alt minor env
    p2_extras = fetch_by_position([v2_], p2_altE)[0]      # M5: extras chain root
    p2_rtX = fetch_by_position([x_], frF2)[0]             # t (major) env, stuck
    # ctor-shape match on the completed major. A stuck `P2.mk a b` app's VALUE
    # is the spine root (SF), not the focus head (SA = Const(P2.mk)).
    p2_sfK = fetch_by_position([k_], SF)[0]               # spine-root kind
    p2_inner = _fv0(SF)            # inner App `P2.mk a`
    p2_innerK = fetch_by_position([k_], p2_inner)[0]
    p2_head = _fv0(p2_inner)       # Const(P2.mk)
    p2_headK = fetch_by_position([k_], p2_head)[0]
    p2_headCid = _fv0(p2_head)
    p2_ctor = reglu(reglu(reglu(_kind_eq_raw(p2_sfK, K_APP, One),
                                _kind_eq_raw(p2_innerK, K_APP, One)),
                          _kind_eq_raw(p2_headK, K_CONST, One)),
                    _is_struct_ctor2(p2_headCid))
    p2_a = fetch_by_position([v1_], p2_inner)[0]          # fst field (a)
    p2_b = fetch_by_position([v1_], SF)[0]                # snd field (b)
    p2_succ_r = reglu(p2_dn, p2_ctor)
    p2_stuck_r = reglu(p2_dn, One - p2_ctor)

    # ── P7.5b-4 Bool.casesOn: major delivery under NAT(OP_CASESON_BOOL, ., 1) ─
    # The major whnf's to a stuck 0-field ctor Const (Bool.false / Bool.true).
    # bool_false_r → apply the false minor; bool_true_r → the true minor; any
    # other completed major (or a stuck delivery bool_sd) → spine stuck. No
    # build loop: both minors take 0 fields, so each rule just selects the
    # minor and continues whnf (like Nat's zero rule).
    bool_dn = reglu(complete, reglu(is_nat_frame,
                reglu(_eq_expr(frX, One),
                      _kind_eq_raw(frV1, OP_CASESON_BOOL, One))))
    bool_sd = reglu(ret_pending, reglu(is_nat_frame,
                reglu(_eq_expr(frX, One),
                      _kind_eq_raw(frV1, OP_CASESON_BOOL, One))))
    # re-read the two minors from the pend chain (frF2 = t entry;
    # t→motive→false→true)
    b_motE = fetch_by_position([v2_], frF2)[0]            # motive entry
    b_falseE = fetch_by_position([v2_], b_motE)[0]        # false minor entry
    b_trueE = fetch_by_position([v2_], b_falseE)[0]       # true minor entry
    b_extras = fetch_by_position([v2_], b_trueE)[0]       # M5: extras chain root
    b_falseV0 = _fv0(b_falseE)     # false minor pos
    b_falseX = fetch_by_position([x_], b_falseE)[0]       # false minor env
    b_trueV0 = _fv0(b_trueE)       # true minor pos
    b_trueX = fetch_by_position([x_], b_trueE)[0]         # true minor env
    b_rtX = fetch_by_position([x_], frF2)[0]              # t (major) env, stuck
    # completed major is a 0-field ctor Const: classify by cid (focus fK/fV0)
    b_is_false = reglu(_kind_eq_raw(fK, K_CONST, One), _is_false(fV0))
    b_is_true = reglu(_kind_eq_raw(fK, K_CONST, One), _is_true(fV0))
    bool_false_r = reglu(bool_dn, b_is_false)
    bool_true_r = reglu(bool_dn, b_is_true)
    bool_stuck_r = reglu(bool_dn, One - b_is_false - b_is_true)

    c1 = POS + One
    c2 = POS + One * 2
    c3 = POS + One * 3
    # M3 eta: a step may emit raw + link1 + link2 + frame (4 tokens), so the
    # frame lands at POS+4. Slot addressing is positional (emission order
    # raw,pend,link,link2,litdig,frame,frame2).
    c4 = POS + One * 4

    # ── delivery: the major whnf completed under NAT(OP_IOTA, X=1) ──────────
    iota_dn = reglu(complete, reglu(is_nat_frame,
              reglu(_eq_expr(frX, One), _kind_eq_raw(frV1, OP_IOTA, One))))
    iota_sd = reglu(ret_pending, reglu(is_nat_frame,
              reglu(_eq_expr(frX, One), _kind_eq_raw(frV1, OP_IOTA, One))))
    # cid/caller live in the scratch frame2 (control.V2 -> frame2):
    # nbV1 = cid, nbV2 = caller.  Keeps the control frame's own V2 free
    # to point at the scratch (see fire_iota frame payloads).
    gm = _rec_meta(nbV1)
    # whnf result closure: an application value's root is the spine (SF), a
    # leaf/0-field ctor is the focus (SA) — the machine's own v_done convention
    gi_root = v_done
    gi_head = _head_of(gi_root, SPINE_MAX)
    gi_headK = fetch_by_position([k_], gi_head)[0]
    gi_headCid = _fv0(gi_head)
    gi_head_const = _kind_eq_raw(gi_headK, K_CONST, One)
    # rule match: walk T_ENV_RULE chain, compare V1 (ctor cid) to head cid
    gi_rules = _chain_f2(gm["rules"], RULE_MAX)
    gi_matched = Zero
    for _r in gi_rules[:-1]:
        _rk = fetch_by_position([k_], _r)[0]
        _rc = fetch_by_position([v1_], _r)[0]
        _m = reglu(_geq_expr(_r, One),
                   reglu(_kind_eq_raw(_rk, T_ENV_RULE, One),
                         _eq_expr(_rc, gi_headCid)))
        gi_matched = _select(_m, _r, gi_matched)
    # K shortcut (to_cnstr_when_K): a K type is single-ctor/0-field, so a
    # stuck major that matches no rule still reduces by its unique rule
    # (rule rhs body = the minor).  Faithful for well-typed K majors.
    gi_kshort = reglu(gm["is_k"], One - _geq_expr(gi_matched, One))
    gi_rule = _select(gi_kshort, gm["rules"], gi_matched)
    gi_nf = _select(gi_kshort, Zero,
                    fetch_by_position([v2_], gi_rule)[0])
    gi_rhs = fetch_by_position([x_], gi_rule)[0]
    gi_rule_ok = reglu(_geq_expr(gi_rule, One),
                       _geq_expr(One * NF_MAX, gi_nf))
    # field args (last nf of the ctor spine).  The build loop emits field_i
    # (application order) from chain[nf-1-i].V1 — see the gb_fld comment.
    gi_apps = _chain_v0(gi_root, NF_MAX)
    # B7 nfields validity: rule.nfields must not exceed the ctor spine width.
    # The first NF_MAX V0 hops from the outer App are the candidate fields;
    # each candidate j < nfields must itself be an App.
    gi_fail = Zero
    for _j in range(NF_MAX):
        _need = _geq_expr(gi_nf, One * (_j + 1))
        _isapp = _kind_eq_raw(fetch_by_position([k_], gi_apps[_j])[0],
                              K_APP, One)
        gi_fail = gi_fail + reglu(_need, One - _isapp)
    gi_fields_ok = One - _geq_expr(gi_fail, One)
    # B4 K conversion (to_cnstr_when_K): when is_k, the kernel replaces a
    # non-constructor major with the (unique, 0-field) default constructor
    # app before whnf, so the rule applies even when the whnf'd major's head
    # is NOT a constructor (e.g. Eq.rec on a stuck proof).  The graph's K
    # shortcut selects the unique rule above; relax the head-constructor
    # requirement accordingly.  K rules have nf=0, so gi_fields_ok holds.
    gi_head_ok = _select(gm["is_k"], One, gi_head_const)
    gi_buildable = reglu(gi_head_ok, reglu(gi_rule_ok, gi_fields_ok))
    # ── WP5-E2: string-literal major (K/inductive.h, inductive_reduce_rec) ──
    # `if (is_string_lit(major)) major = whnf(string_lit_to_constructor(major))`
    # — the literal is converted, the conversion is whnf'd, and rule matching
    # continues on the RESULT (the ofByteArray ctor app the weak whnf reaches;
    # the kernel never unfolds utf8Encode/args at this point).  The graph
    # re-pushes the identical (control, scratch) NAT(OP_IOTA, X=1) frame pair
    # with focus = the literal's shadow-expansion root (K_LIT.X, VM_SPEC §14.3)
    # and E=0, i.e. starts a fresh sub-whnf of the expansion under the same
    # control frame; its completion re-enters iota_dn and rule-matches as any
    # constructor application.  A declined literal (X=0: no String.ofList in
    # this env) keeps the stuck behaviour (no reduction, original spine).
    str_major = reglu(reglu(_kind_eq_raw(fK, K_LIT, One),
                            _eq_expr(fV1, One)), _geq_expr(fX, One))
    iota_str_r = reglu(iota_dn, str_major)
    iota_build_r = reglu(iota_dn, reglu(gi_buildable, One - str_major))
    iota_stuck_r = reglu(iota_dn,
                         reglu(One - gi_buildable, One - str_major))
    # total args applied to the rhs = params+motives+minors + fields
    gi_total = gm["pmm"] + gi_nf
    # WP3-extras: the kernel re-applies every spine arg that lives AFTER the
    # major premise to the reduced rhs (K/inductive.h:115-118, inductive_-
    # reduce_rec: `if (rec_args.size() > major_idx + 1) rhs = mk_app(rhs,
    # nextra, rec_args.data() + major_idx + 1)`).  The original chain nodes
    # (each carries its own expr pos + env) are spliced onto the tail of the
    # build loop's emitted chain instead of terminating it; re-derived from
    # the frame-saved chain head (frF2) like the hardcoded arms' rec/cs/p2/
    # b_extras (M5: the major's sub-whnf may clobber the live SC).  A closed
    # recursor spine has gi_extras=0 → bit-identical to the pre-fix behaviour.
    gi_extras = fetch_by_position(
        [v2_], _pick(_chain_v2(frF2, CHAIN_MAX), gm["majidx"]))[0]
    # branch states
    A_fire_iota, B_fire_iota = gi_maj_v0, gi_maj_env
    C_fire_iota, D_fire_iota, E_fire_iota, F_fire_iota = Zero, c1, Zero, SF
    # E2 restart: focus = expansion root, its own env (closed tree; SB is the
    # major's env), empty pend, fresh frame pair (D=c1), run the whnf (E=0).
    A_iota_str, B_iota_str = fX, SB
    C_iota_str, D_iota_str, E_iota_str, F_iota_str = Zero, c1, Zero, SF
    A_iota_stuck = frE2
    B_iota_stuck, C_iota_stuck, D_iota_stuck = SB, Zero, nbV2
    E_iota_stuck, F_iota_stuck = One, SF
    A_iota_sd = frE2
    B_iota_sd, C_iota_sd, D_iota_sd = SB, Zero, nbV2
    E_iota_sd, F_iota_sd = One, SF
    # delivery → build: A=rule rhs, B=nfields, C=major env (feed field args),
    # E=arg index, F=chain head.  Frame gets cid/major_root/prefix_head.
    A_iota_build = gi_rhs
    B_iota_build = gi_nf
    C_iota_build = SB
    D_iota_build, E_iota_build, F_iota_build = c1, Zero, Zero
    # degenerate: rule rhs uses no args (e.g. a 0-field ctor with pmm=0) →
    # hand the rhs straight back to the machine.
    iota_zero_r = reglu(iota_build_r, One - _geq_expr(gi_total, One))
    A_iota_build = _select(iota_zero_r, gi_rhs, A_iota_build)
    # degenerate: no args re-applied, but extras (if any) still ride (K:115-118)
    C_iota_build = _select(iota_zero_r, gi_extras, C_iota_build)
    D_iota_build = _select(iota_zero_r, nbV2, D_iota_build)

    # ── WP4 quot delivery: the mk argument's whnf completed under
    # NAT(OP_QUOT, X=1) (kernel quot_reduce_rec, K/quot.h:39-70) ────────────
    quot_dn = reglu(complete, reglu(is_nat_frame,
              reglu(_eq_expr(frX, One), _kind_eq_raw(frV1, OP_QUOT, One))))
    quot_sd = reglu(ret_pending, reglu(is_nat_frame,
              reglu(_eq_expr(frX, One), _kind_eq_raw(frV1, OP_QUOT, One))))
    # whnf result of args[mk_pos]: root (v_done) + env (SB).  Head must be
    # Const(Quot.mk) — CK_QUOT with quot_kind 1 — applied to EXACTLY 3 args
    # (get_app_num_args(mk) == 3, K/quot.h:61).  `q_root` is the whnf'd mk.
    q_root = v_done
    q_head = _head_of(q_root, SPINE_MAX)
    q_headK = fetch_by_position([k_], q_head)[0]
    q_headCid = _fv0(q_head)
    q_arity = _app_arity(q_root, SPINE_MAX)
    q_is_mk = reglu(reglu(_kind_eq_raw(q_headK, K_CONST, One),
                  _kind_eq_raw(_mkind(q_headCid), CK_QUOT, One)),
                  _eq_expr(_quot_kind(q_headCid), One * 1))
    q_ok = reglu(q_is_mk, _eq_expr(q_arity, One * 3))
    # app_arg(mk) = the outermost App's argument = a (K/quot.h:65).  Its env is
    # the mk closure's env (SB).
    q_a_pos = fetch_by_position([v1_], q_root)[0]
    # f = args[arg_pos] and the post-mk_pos extras, re-read from the original
    # pend chain saved at fire (frame F2 = SC); nbV1 = arg_pos, nbX = mk_pos
    # (scratch frame2), nbV2 = caller.
    q_saved = _chain_v2(frF2, CHAIN_MAX)
    q_argE = _pick(q_saved, nbV1)
    q_mkE = _pick(q_saved, nbX)
    q_f_pos = _fv0(q_argE)
    q_f_env = fetch_by_position([x_], q_argE)[0]
    q_extras = fetch_by_position([v2_], q_mkE)[0]   # args[elim_arity..]
    quot_go = reglu(quot_dn, q_ok)
    quot_stuck_r = reglu(quot_dn, One - q_ok)
    # branch states
    A_fire_quot, B_fire_quot = _fv0(q_mk_entry), fetch_by_position([x_], q_mk_entry)[0]
    C_fire_quot, D_fire_quot, E_fire_quot, F_fire_quot = Zero, c1, Zero, SF
    # quot_go: emit raw App(f, a) at c1 (the stuck-result spine root) and a
    # PEND for `a` at c2 whose V2 = the linked extras; focus = f, so the
    # machine beta-reduces `f` in its OWN env and applies `a` (captured in the
    # PEND with the mk closure env) then the extras.  This is exactly
    # mk_app(f, app_arg(mk)) + the post-elim_arity args (K/quot.h:64-68).
    A_quot_go, B_quot_go = q_f_pos, q_f_env
    C_quot_go, D_quot_go, E_quot_go, F_quot_go = c2, nbV2, Zero, c1
    # stuck: mk is not `Quot.mk` with 3 args (or arrived stuck) -> no
    # reduction; deliver the original quotient spine root (quot_is_stuck /
    # whnf returning e, K/quot.h:59-62, 76-95).
    A_quot_stuck, B_quot_stuck, C_quot_stuck, D_quot_stuck = frE2, SB, Zero, nbV2
    E_quot_stuck, F_quot_stuck = One, SF
    A_quot_sd, B_quot_sd, C_quot_sd, D_quot_sd = frE2, SB, Zero, nbV2
    E_quot_sd, F_quot_sd = One, SF

    # ── build loop: one T_PEND per step; E = global arg index ───────────────
    # Args [0, pmm) come from the saved recursor pend chain (params, motives,
    # minors — indices omitted §13.2 step 9); args [pmm, pmm+nf) are the ctor
    # fields, in application (left-to-right) order, taken from the major ctor
    # spine.  `_chain_v0` walks V0 outward→inward: chain[0] is the outer App
    # whose V1 is the LAST field, so field_i (application order) lives at
    # chain[nf-1-i].V1 — the kernel takes the last nf major args in order
    # (K/inductive.h:113-114, `major_args.data()+nparams_major`).  Emitting
    # with index (nf-1)-(E-pmm) therefore yields application order on the
    # head of the PEND chain.  V2 = next emitted node (POS+3), 0 at the tail.
    gb = _rec_meta(nbV1)
    gb_prefix = _chain_v2(frF2, PMM_MAX)          # prefix head saved at fire
    gb_pref_entry = _pick(gb_prefix, SE)
    gb_is_pref = _geq_expr(gb["pmm"], SE + One)
    gb_apps = _chain_v0(frE2, NF_MAX)             # major_root saved in frame E2
    gb_fld = _pick(gb_apps, (SB - One) - (SE - gb["pmm"]))
    gb_src_pos = _select(gb_is_pref, _fv0(gb_pref_entry),
                         fetch_by_position([v1_], gb_fld)[0])
    gb_src_env = _select(gb_is_pref,
                         fetch_by_position([x_], gb_pref_entry)[0], SC)
    gb_total = gb["pmm"] + SB
    gb_more = _geq_expr(gb_total, SE + One * 2)   # E+1 < total
    gb_node_pos = POS + One
    gi_chain_head = _select(_eq_expr(SE, Zero), gb_node_pos, SF)
    A_iota_b = SA
    B_iota_b = _select(gb_more, SB, Zero)
    C_iota_b = _select(gb_more, SC, gi_chain_head)
    D_iota_b = _select(gb_more, SD, nbV2)
    E_iota_b = _select(gb_more, SE + One, Zero)
    F_iota_b = _select(_eq_expr(SE, Zero), gb_node_pos,
                       _select(gb_more, SF, Zero))
    gi_pend_V0 = gb_src_pos
    gi_pend_env = gb_src_env
    # WP3-extras: last emitted node's V2 = the frame-saved extras chain head
    # (args after the major, K/inductive.h:115-118), not 0 (0 when none).
    gi_pend_prev = _select(gb_more, POS + One * 3, gi_extras)


    # ── emissions (main mode; at most two tokens, at POS+1/POS+2) ───────────
    em_pend = reglu(is_app, main_mode)
    em_link = lam_apply + reglu(is_let, main_mode)
    em_frame_bvar = reglu(is_bvar, main_mode)
    # walk continuation: emit the next WALK frame (multi-hop fix; the old
    # self-pointing-D shortcut never worked and was untested)
    em_frame_walk = walk_more

    # ── new state fields (main mode, M1 default path) ───────────────────────
    A_main = _select(is_app, fV0,
             _select(lam_apply, fV1,
             _select(const_delta, eV2,
             _select(is_let, fX,
             _select(is_mdata, fV0,
             _select(em_frame_bvar, SB,
                     SA))))))                   # bvar: jump to chain head
    B_main = _select(is_app, SB,
             _select(lam_apply, c1,
             _select(const_delta, Zero,
             _select(is_let, c1,
                     SB))))
    C_main = _select(is_app, c1,
             _select(lam_apply, pV2,
             _select(is_let, SC,
                     SC)))
    D_main = _select(em_frame_bvar + em_frame_walk, c1, SD)
    F_main = _select(reglu(is_app, main_mode),
                     _select(pend_nonempty, SF, SA), SF)
    E_main = _select(em_frame_bvar, SA, SE)    # save bvar pos (marker stuck)

    # emission payloads (main default path)
    pend_V0 = fV1                              # APP: arg position
    pend_prev = SC
    pend_env = SB
    link_V0 = _select(is_let, fV1, pV0)        # LET value / LAM arg
    link_V1 = dV1 + _geq_expr(SB, One)         # LINK depth (0-based)
    link_prev = SB
    link_env = _select(is_let, SB, pX)         # LET: current / LAM: captured

    # ── WALK frame micro-step ───────────────────────────────────────────────
    # fetched fields (f*) are the LINK at the state focus; the walk keeps
    # the focus pointing at the current link. Phase 5 M2: the resolved link
    # may be a binder marker (E2=1). Delivery then depends on the parent
    # frame: INFER returns the marker's (V0,X) domain closure; DEFEQ always
    # continues with the resolved pair; WHNF/main sticks at the bvar token
    # (saved in E at bvar setup) — fvar analog. A walk into NULL with hops
    # left is the kernel's ERR_OVERFLOW: soft under a WHNF frame flagged
    # E2=1 (DEFEQ's _soft_whnf), hard reject otherwise.
    walk_done = reglu(is_walk_frame, One - walk_more)
    par_infdq = (_kind_eq_raw(nbV0, TASK_INFER, One)
                 + _kind_eq_raw(nbV0, TASK_DEFEQ, One))
    walk_fail = reglu(walk_more, reglu(_geq_expr(frX, One * 2),
                                       One - _geq_expr(fV2, One)))
    wf_soft = reglu(walk_fail, reglu(_kind_eq_raw(nbV0, TASK_WHNF, One),
                                     nbE2))
    wf_hard = walk_fail - wf_soft
    mk_deliver = reglu(walk_done, reglu(fE2, par_infdq))
    # M3: a DEFEQ bvar walk resolves to a binder marker; the continuation
    # (D_BV2/D_BV3) needs the LINK POSITION (to read its bid), not the domain
    # closure. Parent is the ST carrying that cont id. Phase 6: the flag test
    # is dropped — a walk that resolves to a VALUE link (flag=0, e.g. the eta
    # L link) delivers the link position too; D_BV3's bv_nb branch already
    # knows how to substitute a non-marker side and continue DEFEQ. (Popping
    # instead froze the machine in resume_mode under the ST parent.)
    par_bv = reglu(_kind_eq_raw(nbV0, TASK_ST, One),
                   _kind_eq_raw(nbF2, D_BV2, One)
                   + _kind_eq_raw(nbF2, D_BV3, One))
    mk_dq = reglu(walk_done, par_bv)
    mk_stuck = reglu(walk_done, reglu(fE2, reglu(One - par_infdq, One - par_bv)))
    # M3 stuck marker: the kernel's whnf of a stuck fvar application returns
    # the WHOLE application (head + args), so DEFEQ can spine-peel it. With
    # pending args under a WHNF frame the spine root IS the task's original
    # closure (nbV1, nbX) — the head may have resolved through value links
    # (env changes), but the spine token's env is the one the WHNF frame was
    # pushed with. Without a WHNF parent (top-level halt) fall back to the
    # spine root + the bvar focus env (frF2, carried in the walk frame's free
    # F2 slot). No pending args → the bvar token (SE) under its focus env.
    # (The old head-only delivery with SB clobbered to the last link's
    # captured env made D_SW3's sw_stuck fail and deq_eta_lam loop.)
    ms_sp_whnf = reglu(mk_stuck, reglu(result_spine,
                                       _kind_eq_raw(nbV0, TASK_WHNF, One)))
    A_walk = _select(ms_sp_whnf, nbV1,
            _select(wf_soft, nbV1,
            _select(walk_fail, fV2,
            _select(mk_dq, SA,
            _select(mk_stuck, _select(result_spine, SF, SE),
            _select(walk_more, fV2,
                    fV0))))))                   # hop: next link / done: value
    B_walk = _select(ms_sp_whnf, nbX,
            _select(wf_soft, nbX,
            _select(walk_fail, SB,
            _select(mk_dq, SB,
            _select(mk_stuck, frF2,
                    fX)))))
    C_walk = SC
    D_walk = _select(wf_soft, nbV2,
            _select(walk_fail, c1,
            _select(walk_more, c1,
                    frV2)))                    # push next walk frame / pop
    F_walk = SF
    E_walk = _select(wf_soft, One,
            _select(mk_deliver + mk_stuck + mk_dq, One,
                    SE))
    halt = halt + reglu(mk_stuck, One - _geq_expr(frV2, One))

    # ── nat fire / deliver branches ─────────────────────────────────────────
    # fire2: D=[ST(arg2), NAT(op, caller, 1)], focus=arg1
    A_fire2, B_fire2, C_fire2, D_fire2 = pV0, pX, qV2, c1
    E_fire2, F_fire2 = Zero, Zero
    # fire1: D=[NAT(op, caller, 1)], focus=arg1
    A_fire1, B_fire1, C_fire1, D_fire1 = pV0, pX, pV2, c1
    E_fire1, F_fire1 = Zero, Zero
    # d12 (arg1 delivered): D=[ST'(value), NAT(op, caller, 2)], focus=arg2
    # P7.5c-M5: the extras chain (SC) must SURVIVE the argument sub-whnfs —
    # the kernel applies pending args to the computed literal. The toy corpus
    # only ever fully applies nat ops (extras empty here), so Zero was
    # indistinguishable; real library data (factorial's `succ (pred 6)` major
    # under a casesOn frame with the below-ih extra on the pend) exposed it.
    A_d12, B_d12, C_d12, D_d12 = frV1, frX, SC, c1
    E_d12, F_d12 = Zero, Zero

    # d23 (arg2 delivered) — per-op entry. At d23: D=ST', frV1 = v1 pos,
    # nbV1 = op; A = v_done = the b-side chain head.
    opg3d = _kind_eq_raw(nbV1, OP_ADD, One)
    opg4d = _kind_eq_raw(nbV1, OP_SUB, One)
    is_addsub_d = opg3d + opg4d
    is_mul_d = _kind_eq_raw(nbV1, OP_MUL, One)
    is_pow_d = _kind_eq_raw(nbV1, OP_POW, One)
    is_divmod_d = _kind_eq_raw(nbV1, OP_DIV, One) + _kind_eq_raw(nbV1, OP_MOD, One)
    # WP6-F dispatch (K/type_checker.cpp:702-733).
    is_bitop_d = (_kind_eq_raw(nbV1, OP_LAND, One)
                  + _kind_eq_raw(nbV1, OP_LOR, One)
                  + _kind_eq_raw(nbV1, OP_XOR, One))
    is_shr_d = _kind_eq_raw(nbV1, OP_SHR, One)
    is_shl_d = _kind_eq_raw(nbV1, OP_SHL, One)
    is_gcd_d = _kind_eq_raw(nbV1, OP_GCD, One)
    n1_d23raw = _fv0(frV1)
    c1K_d23 = fetch_by_position([k_], frV1)[0]
    is_z1_d23 = reglu(_kind_eq_raw(c1K_d23, K_CONST, One),
                      _is_zero(n1_d23raw))
    is_lit1_d23 = reglu(_kind_eq_raw(c1K_d23, K_LIT, One),
                        _eq_expr(fetch_by_position([v1_], frV1)[0], Zero))
    n1_d23 = _select(is_lit1_d23, n1_d23raw, One)
    n2_d23 = n2                                # A = v_done = b-side head
    b0_d23 = b0raw
    is_bzero_d = reglu(_eq_expr(n2_d23, One), _eq_expr(b0_d23, Zero))
    d23_work = reglu(d23, One - reglu(is_divmod_d, is_bzero_d))
    d23_bz_div = reglu(d23, reglu(is_divmod_d, reglu(is_bzero_d,
                                                      _kind_eq_raw(nbV1, OP_DIV, One))))
    d23_bz_mod = reglu(d23, reglu(is_divmod_d, reglu(is_bzero_d,
                                                     _kind_eq_raw(nbV1, OP_MOD, One))))
    # WP6-F: bitop entries start the round loop with the p=[1] chain emitted at
    # d23 (head@c2); the r accumulator is VIRTUAL (C=0: every r digit reads as
    # 0 until the first r-add materializes it).  shiftRight emits NO head: its
    # evolving chains live in the frame slots (E2 = a head, F2 = s head; the
    # A field is unused during the loop).  The a-copy/s'-copy chain heads come
    # from the 31/32/33 done steps.
    d23_bitop = reglu(d23_work, is_bitop_d)
    d23_shr = reglu(d23_work, is_shr_d)
    d23_gcd = reglu(d23_work, is_gcd_d)
    d23_shl = reglu(d23_work, is_shl_d)
    # head V0 per op: add: max(n1,n2)+1; sub: n1; mul: n2+1; pow: 1;
    # div/mod: Q = [0] chain head
    n_out_d23 = _select(opg3d, _select(_geq_expr(n1_d23, n2_d23), n1_d23, n2_d23) + One,
               _select(opg4d, n1_d23,
               _select(is_mul_d, n2_d23 + One,
                       One)))
    A_d23 = _select(d23_gcd, Zero,
            _select(d23_bz_div, c1,
            _select(d23_bz_mod, frV1,
                    v_done)))
    B_d23 = Zero
    # P7.5c-M5: non-divmod delivery keeps the enclosing extras on the pend
    # (the computed literal is the focus the extras apply to). The divmod
    # loop repurposes the pend as its accumulator chain (frV1) — unchanged.
    C_d23 = _select(d23_bitop, Zero,
            _select(reglu(d23, reglu(is_divmod_d, One - is_bzero_d)), frV1, SC))
    D_d23 = _select(d23_bz_div + d23_bz_mod, nbV2, c1)
    E_d23 = Zero
    F_d23 = _select(d23_gcd, Zero,
            _select(d23_shr, Zero,
            _select(d23_shl, Zero,
                    _select(d23_work, c2, Zero))))

    # dn1 (arity-1 delivered): push NAT(op, caller, 3); head for succ/pred
    n1_dn1raw = fV0
    is_z1_dn1 = reglu(_kind_eq_raw(fK, K_CONST, One),
                      _is_zero(fV0))
    is_lit1_dn1 = reglu(_kind_eq_raw(fK, K_LIT, One), _eq_expr(fV1, Zero))
    n1_dn1 = _select(is_lit1_dn1, n1_dn1raw, One)
    n_out_dn1 = _select(_kind_eq_raw(frV1, OP_SUCC, One), n1_dn1 + One, n1_dn1)
    A_dn1, B_dn1, C_dn1, D_dn1 = v_done, Zero, SC, c1   # M5: keep extras (SC)
    E_dn1 = _select(_kind_eq_raw(frV1, OP_SUCC, One), Zero, One)  # pred: borrow
    F_dn1 = _select(_kind_eq_raw(frV1, OP_SUCC, One)
                    + _kind_eq_raw(frV1, OP_PRED, One), c2, Zero)

    # ── P6.5 iota branch states ─────────────────────────────────────────────
    # fire_rec: focus = major-premise closure (pend popped to extras); the
    # NAT(OP_REC, caller, 1) frame (slot 1) carries E2 = spine root,
    # F2 = m entry.
    A_fire_rec, B_fire_rec, C_fire_rec, D_fire_rec = majV0, majX, majV2, c1
    E_fire_rec, F_fire_rec = Zero, SF
    # zero rule: pop the NAT frame, continue whnf on the z closure with the
    # extras still on the stack (kernel: extras applied to rhs).
    A_zero_r, B_zero_r, C_zero_r, D_zero_r = rzV0, rzX, rec_extras, frV2
    E_zero_r, F_zero_r = Zero, SF
    # succ rule: rewrite the frame to X=2 (base = c1+1, the first build
    # token; the frame lands at c1) and enter the build loop (B = step ctr).
    A_build_r, B_build_r, C_build_r, D_build_r = SA, Zero, rec_extras, c1
    E_build_r, F_build_r = Zero, SF
    # stuck (maj completed as a non-nat stuck leaf, or arrived stuck E=1):
    # deliver the saved spine root under the maj entry's env (§10.2); the
    # spine already includes the extras, so C drops to 0.
    A_stuck_r, B_stuck_r, C_stuck_r, D_stuck_r = frE2, rmajX, Zero, frV2
    E_stuck_r, F_stuck_r = One, SF
    A_rec_sd, B_rec_sd, C_rec_sd, D_rec_sd = frE2, rmajX, Zero, frV2
    E_rec_sd, F_rec_sd = One, SF

    # ── P7.5b casesOn branch states ──────────────────────────────────────────
    # fire: focus = t (pend head), pop the 4 spine entries (C = succ entry's
    # V2 = extras), push NAT(OP_CASESON, caller, 1) frame (E2=spine root, F2=t
    # entry SC).
    A_fire_cs, B_fire_cs, C_fire_cs, D_fire_cs = pV0, pX, cs_succ[2], c1
    E_fire_cs, F_fire_cs = Zero, SF
    # zero rule: pop the NAT frame, continue whnf on the zero minor with the
    # extras still on the stack (M5: re-derived from the entry chain — the
    # major's sub-whnf may have used the pend as digit scratch).
    A_zero_cs, B_zero_cs, C_zero_cs, D_zero_cs = rzV0_c, rzX_c, cs_extras, frV2
    E_zero_cs, F_zero_cs = Zero, SF
    # stuck (major is a succ-literal [succ rule deferred], a non-nat leaf, or
    # arrived stuck E=1): deliver the saved spine root under t's env (§10.2).
    A_stuck_cs, B_stuck_cs, C_stuck_cs, D_stuck_cs = frE2, rtX_c, Zero, frV2
    E_stuck_cs, F_stuck_cs = One, SF
    A_sd_cs, B_sd_cs, C_sd_cs, D_sd_cs = frE2, rtX_c, Zero, frV2
    E_sd_cs, F_sd_cs = One, SF
    # succ rule: rewrite the frame to X=2 (build frame, base = c1+2) and enter
    # the cs_build loop (B = step ctr); focus stays at the completed major SA.
    A_succ_cs, B_succ_cs, C_succ_cs, D_succ_cs = SA, Zero, cs_extras, c1   # M5: re-derived extras
    E_succ_cs, F_succ_cs = Zero, SF

    # ── P7.5b-3 P2.casesOn branch states ─────────────────────────────────────
    # fire: focus = t (pend head), pop the 3 spine entries (C = alt entry's
    # V2 = extras), push NAT(OP_CASESON_P2, caller, 1) frame (E2=spine root,
    # F2=t entry SC).
    A_fire_p2, B_fire_p2, C_fire_p2, D_fire_p2 = pV0, pX, p2_alt[2], c1
    E_fire_p2, F_fire_p2 = Zero, SF
    # ctor rule: DIRECT delivery. Focus = the alt minor in its home env; the
    # major's field pend entries are already on the C chain (peeled during the
    # major's whnf, each carrying the major's own env) with the dispatch
    # extras hanging off their tail. Beta then binds each field with the env
    # the entry captured — kernel iota applies the ctor's fields to the minor
    # rhs unchanged (K/inductive.h:112-118). Reifying `alt a b` flat under
    # alt's env is only faithful when the fields are env-free literals;
    # brecOn witness fields `P2.mk (f ..) proof` carry loose bvars and under
    # the alt env they mis-resolve into the caller's binder chain.
    A_succ_p2, B_succ_p2, C_succ_p2, D_succ_p2 = p2_altV0, p2_altX, SC, frV2
    E_succ_p2, F_succ_p2 = Zero, SF
    # stuck (major not a P2.mk ctor, or arrived stuck E=1): deliver the saved
    # spine root under t's env (§10.2).
    A_stuck_p2, B_stuck_p2, C_stuck_p2, D_stuck_p2 = frE2, p2_rtX, Zero, frV2
    E_stuck_p2, F_stuck_p2 = One, SF
    A_sd_p2, B_sd_p2, C_sd_p2, D_sd_p2 = frE2, p2_rtX, Zero, frV2
    E_sd_p2, F_sd_p2 = One, SF

    # ── P7.5b-4 Bool.casesOn branch states ───────────────────────────────────
    # fire: focus = t (pend head), pop the 4 spine entries (C = true entry's
    # V2 = extras), push NAT(OP_CASESON_BOOL, caller, 1) frame (E2=spine root,
    # F2=t entry SC).
    A_fire_bool, B_fire_bool, C_fire_bool, D_fire_bool = pV0, pX, b_true[2], c1
    E_fire_bool, F_fire_bool = Zero, SF
    # false / true rules: pop the NAT frame, continue whnf on the selected
    # 0-field minor with the extras still on the stack (no build loop).
    A_false_bool, B_false_bool, C_false_bool, D_false_bool = b_falseV0, b_falseX, b_extras, frV2
    E_false_bool, F_false_bool = Zero, SF
    A_true_bool, B_true_bool, C_true_bool, D_true_bool = b_trueV0, b_trueX, b_extras, frV2
    E_true_bool, F_true_bool = Zero, SF
    # stuck (major not a Bool ctor, or arrived stuck E=1): deliver the saved
    # spine root under t's env (§10.2).
    A_stuck_bool, B_stuck_bool, C_stuck_bool, D_stuck_bool = frE2, b_rtX, Zero, frV2
    E_stuck_bool, F_stuck_bool = One, SF
    A_sd_bool, B_sd_bool, C_sd_bool, D_sd_bool = frE2, b_rtX, Zero, frV2
    E_sd_bool, F_sd_bool = One, SF

    # ── nat compute: shared per-digit values ────────────────────────────────
    d1 = _select(is_z1, Zero,
                 _select(One - _geq_expr(SB, n1), g1V0, Zero))
    d2 = _select(is_z2, Zero,
                 _select(One - _geq_expr(SB, n2), g2V0, Zero))

    # ── phase 3: simple ops (succ/pred/add/sub/beq/ble) ─────────────────────
    simplop = opg1 + opg2 + opg3 + opg4 + opg9 + opg10
    addfam = opg1 + opg3
    borrowfam = opg2 + opg4
    d2c = reglu(opg3, d2) + reglu(opg1, _eq_expr(SB, Zero))
    s_add = d1 + d2c + SE
    c_add = _geq_expr(s_add, One * 10)
    dig_add = s_add - _select(c_add, One * 10, Zero)
    t_b = d1 - reglu(opg4, d2) - SE
    neg_b = _geq_expr(Zero, t_b + One)
    dig_b = _select(neg_b, t_b + One * 10, t_b)
    c_b = neg_b
    mis = SE + (One - _eq_expr(d1, d2))
    lt = _geq_expr(d2, d1 + One)
    gt = _geq_expr(d1, d2 + One)
    E_ble = _select(_eq_expr(lt + gt * 2, Zero), SE, lt + gt * 2)
    E_new = _select(addfam, c_add,
            _select(borrowfam, c_b,
            _select(opg9, mis, E_ble)))
    dig_out = _select(addfam, dig_add, _select(borrowfam, dig_b, Zero))
    mx = _select(_geq_expr(n1, n2), n1, n2)
    n_out_c = _select(opg1, n1 + One, mx + One)
    done_add = reglu(_geq_expr(SB + One, n_out_c), One - c_add)
    done_bor = _geq_expr(SB + One, mx + One)  # borrow chain must run through the
    # longer operand: n1-only stop returned 5-(10^19+1)=4 (pre-WP6 bug; kernel
    # subtracts full values, K:649-651)
    done_beq = _select(_geq_expr(_geq_expr(SB + One, mx) + _geq_expr(mis, One),
                                 One), One, Zero)
    done_ble = _geq_expr(SB + One, mx)
    done_s = _select(addfam, done_add,
             _select(borrowfam, done_bor,
             _select(opg9, done_beq, done_ble)))
    underflow = reglu(borrowfam, reglu(done_s, c_b))
    bool_cond = _select(opg9, _eq_expr(mis, Zero),
                        One - _eq_expr(E_ble, One * 2))
    # WP8-H5: the true/false cid is resolved by the name-keyed header scan
    # (_TRUE_CID / _FALSE_CID) above, not hardcoded — under a name-sorted real
    # environment Bool.true / Bool.false sit at different cids and a literal
    # emitted with the toy cid aborts Bool.casesOn / defeq.  Legacy streams fall
    # back to CID_TRUE / CID_FALSE.
    const_cid = _select(bool_cond, _TRUE_CID, _FALSE_CID)
    # simple done-step state (result into A, pop D to caller)
    A_sdone = _select(addfam, SF,
              _select(borrowfam, _select(underflow, c1, SF),
              c1))                               # beq/ble: emitted const
    # simple not-done digit step
    A_s, B_s, C_s, D_s = SA, SB + One, Zero, SD
    E_s, F_s = E_new, SF

    # ── phase 3: mul/pow cells ──────────────────────────────────────────────
    # cell (i,j): acc'[j] = accC[j] + m_i * x_{j-i} + carry
    #   mul: m = v1 (ST'.V1), x = b (A); pow: m = round acc (frame V2),
    #   x = a (ST'.V1). acc heads carry the row index i in V2.
    cellop = opg5 + opg6
    m_i = _select(reglu(is_mul_o, is_z1), Zero,
          _select(One - _geq_expr(iF, mL), m_i_raw, Zero))
    bidx = SB - iF
    bterm_gate = reglu(_geq_expr(SB, iF), One - _geq_expr(bidx, x_n))
    x_bad = reglu(is_mul_o, is_z2) + reglu(is_pow_o, is_za)
    bterm = _select(x_bad, Zero, _select(bterm_gate, xJ, Zero))
    prod = Zero
    for _m in range(1, 10):
        prod = prod + reglu(m_i, _geq_expr(bterm, _m))
    accj = _select(_geq_expr(SB, nC), Zero, aCC)
    p_cell = accj + prod + SE
    # full base-10 quotient/remainder: p in 0..98, floor(p/10) via thresholds
    q_cell = Zero
    for _q in range(1, 10):
        q_cell = q_cell + _geq_expr(p_cell, One * 10 * _q)
    c_cell = q_cell
    ten_q = Zero
    for _q in range(1, 10):
        ten_q = ten_q + reglu(One * 10, _geq_expr(q_cell, _q))
    dig_cell = p_cell - ten_q
    row_len = _select(_geq_expr(nC, iF + x_n), nC, iF + x_n) + One
    done_row = _geq_expr(SB + One, row_len)
    i1 = iF + One
    row_cont = reglu(done_row, One - _geq_expr(i1, mL))
    mul_done = reglu(is_mul_o, reglu(done_row, _geq_expr(i1, mL)))
    pow_rdone = reglu(is_pow_o, reglu(done_row, _geq_expr(i1, mL)))
    head_row_V0 = _select(_geq_expr(nF, i1 + x_n), nF, i1 + x_n) + One
    # states: not-done / row-continue / mul done / pow round end
    A_c0, B_c0, C_c0, D_c0 = SA, SB + One, SC, SD
    E_c0, F_c0 = c_cell, SF
    A_c1, B_c1, C_c1, D_c1c = SA, Zero, SF, SD
    E_c1, F_c1 = Zero, c2
    A_c2, B_c2, C_c2, D_c2c = SF, Zero, Zero, c2   # WP6-G: mul_done diverts
    # into the X76 strip scan: the final digit sits at c1 and the X=76 frame
    # (V2 = ncV2 caller pop target) at c2; X76's done step then delivers
    # A := SF, D := frV2 — exactly what the old direct delivery did.
    E_c2, F_c2 = Zero, Zero
    A_c3, B_c3, C_c3, D_c3c = SA, Zero, Zero, c2
    E_c3, F_c3 = One, c3                       # dec borrow init

    # ── phase 4: div compare R vs b ─────────────────────────────────────────
    ph3 = _eq_expr(frX, One * 3)
    ph4 = _eq_expr(frX, One * 4)
    dR = _select(is_z1, Zero, _select(_geq_expr(SB, nC), Zero, aCC))
    db4 = _select(is_z2, Zero, _select(_geq_expr(SB, n2), Zero, bkJ))
    lt4 = _geq_expr(db4, dR + One)
    gt4 = _geq_expr(dR, db4 + One)
    E4 = _select(_eq_expr(lt4 + gt4 * 2, Zero), SE, lt4 + gt4 * 2)
    done4 = _geq_expr(SB + One, _select(_geq_expr(nC, n2), nC, n2))
    div_done = reglu(done4, _eq_expr(E4, One))          # R < b
    sub_setup = reglu(done4, One - _eq_expr(E4, One))   # R >= b
    A_4d = _select(is_mod_o, SC, SF)                    # mod -> R, div -> Q
    A_4s, B_4s, C_4s, D_4s = SA, Zero, SC, c1
    E_4s, F_4s = Zero, c2                               # R' head
    A_4n, B_4n, C_4n, D_4n = SA, SB + One, Zero, SD
    E_4n, F_4n = E4, SF
    head4_V0 = nC                                       # R' len = R len

    # ── phase 5: div R := R - b ─────────────────────────────────────────────
    ph5 = _eq_expr(frX, One * 5)
    t5 = dR - db4 - SE
    neg5 = _geq_expr(Zero, t5 + One)
    dig5 = _select(neg5, t5 + One * 10, t5)
    done5 = _geq_expr(SB + One, nC)
    nQ5 = _fv0(xF)     # R'.X = Q head -> its len
    A_5n, B_5n, C_5n, D_5n = SA, SB + One, Zero, SD
    E_5n, F_5n = neg5, SF
    A_5d, B_5d, C_5d, D_5d = SA, Zero, xF, c2  # C <- Q head (R'.X)
    E_5d, F_5d = Zero, c3                      # Q' head
    head5_V0 = nQ5 + One

    # ── phase 6: div Q := Q + 1 ─────────────────────────────────────────────
    ph6 = _eq_expr(frX, One * 6)
    dQ = _select(_geq_expr(SB, nC), Zero, aCC)
    s6 = dQ + reglu(_eq_expr(SB, Zero), One) + SE
    c6 = _geq_expr(s6, One * 10)
    dig6 = s6 - _select(c6, One * 10, Zero)
    done6 = _geq_expr(SB + One, nC + One)
    A_6n, B_6n, C_6n, D_6n = SA, SB + One, Zero, SD
    E_6n, F_6n = c6, SF
    A_6d, B_6d, C_6d, D_6d = SA, Zero, frV2, c2  # C <- R' head (frame V2)
    E_6d, F_6d = Zero, SF

    # ── phase 10: pow controller = digit-sum zero scan of b ────────────────
    # b's chain may carry high-end padding zeros, so "zero" = sum of all
    # n2 digits == 0 (length-independent), not a shape check.
    ph10 = _eq_expr(frX, One * 10)
    E_sum = SE + db4
    done10 = _geq_expr(SB + One, n2)
    is_bzero10 = reglu(done10, _eq_expr(E_sum, Zero))
    pow_go = reglu(done10, One - _eq_expr(E_sum, Zero))
    A_10z, B_10z, C_10z, D_10z = SF, Zero, Zero, ncV2  # b=0: result acc
    E_10z, F_10z = Zero, Zero
    A_10g, B_10g, C_10g, D_10g = SA, Zero, Zero, c1        # round start
    E_10g, F_10g = Zero, c2
    A_10n, B_10n, C_10n, D_10n = SA, SB + One, Zero, SD    # scan continue
    E_10n, F_10n = E_sum, SF
    head10_V0 = x_n + One   # must equal the cell row_len of row 0

    # ── phase 13: pow b := b - 1 ────────────────────────────────────────────
    ph13 = _eq_expr(frX, One * 13)
    t13 = db4 - SE
    neg13 = _geq_expr(Zero, t13 + One)
    dig13 = _select(neg13, t13 + One * 10, t13)
    done13 = _geq_expr(SB + One, n2)
    A_13n, B_13n, C_13n, D_13n = SA, SB + One, Zero, SD
    E_13n, F_13n = neg13, SF
    b13u = reglu(done13, neg13)            # dec underflow: b was zero
    A_13d = _select(b13u, c2, SF)          # underflow: fresh [0] chain head
    B_13d, C_13d = Zero, Zero
    D_13d = _select(b13u, c1, c2)
    E_13d, F_13d = Zero, frV2

    # ══ WP6-F compute loops (K/type_checker.cpp:702-733, oracle-confirmed) ══
    # land/lor/xor (X 21-25): bit round = parity extract (21, emits the fresh
    # r-add head) -> r += bit*p (22) -> p *= 2 (23) -> a //= 2 (24) -> b //= 2
    # (25); loop ends when both halves hit zero (no bit above can contribute).
    # shiftRight (X 31-33): 31 = zero scan of s, 32 = a //= 2 (top-down, one
    # round per unit of s), 33 = s -= 1; ends when s hits zero (result a) or a
    # hits zero (result 0).  A huge s never iterates the 4095-digit dec: the
    # a-side zero test cuts the loop at bitlen(a).
    # Slots: frame E2 = p (bitop) / a (shr); frame F2 = a (bitop) / s (shr);
    # A = b head (bitop); C = r head (bitop, 0 = virtual [0] at entry); F =
    # current pass output head; E = packed carry/flag word; B = digit index.
    # E packing: bitop ph22-25: E = carry + 2*bit (22) or carry + 2*nz (23/24)
    # or carry + 2*nz_b + 4*nz_a (25); shr ph32/33: E = carry + 2*nz.
    def _wz6(H):
        """1 if the nat-argument head token is a K_CONST Nat.zero."""
        return reglu(_kind_eq_raw(fetch_by_position([k_], H)[0], K_CONST, One),
                     _is_zero(_fv0(H)))

    def _nlen6(H):
        return _select(_wz6(H), One, _fv0(H))

    def _ndig6(H, idx):
        return _select(_wz6(H), Zero, _fv0(H + One * 2 + idx * 2))

    def _fl2_6(d):
        return (_geq_expr(d, One * 2) + _geq_expr(d, One * 4)
                + _geq_expr(d, One * 6) + _geq_expr(d, One * 8))

    def _par6(d):
        return d - _fl2_6(d) * 2

    ph21 = _eq_expr(frX, One * 21)
    ph22 = _eq_expr(frX, One * 22)
    ph23 = _eq_expr(frX, One * 23)
    ph24 = _eq_expr(frX, One * 24)
    ph25 = _eq_expr(frX, One * 25)
    ph31 = _eq_expr(frX, One * 31)
    ph32 = _eq_expr(frX, One * 32)
    ph33 = _eq_expr(frX, One * 33)
    is_land_o = _kind_eq_raw(frV1, OP_LAND, One)
    is_lor_o = _kind_eq_raw(frV1, OP_LOR, One)
    is_xor_o = _kind_eq_raw(frV1, OP_XOR, One)
    is_bitop_f = is_land_o + is_lor_o + is_xor_o

    # ── X21: parity extract + r-head emit ──
    la6 = _par6(_ndig6(frF2, Zero))          # a digit 0 (frame F2)
    lb6 = _par6(_ndig6(SA, Zero))            # b digit 0 (A field)
    bit6 = _select(is_land_o, reglu(la6, lb6),
            _select(is_lor_o, _select(la6, One, lb6),
                    la6 + lb6 - reglu(la6, lb6) * 2))
    n_r6 = _select(_geq_expr(SC, One), _fv0(SC), One)     # virtual [0] -> 1
    n_p6 = _fv0(frE2)
    L226 = _select(_geq_expr(n_r6, n_p6), n_r6, n_p6) + One
    # r-new head emitted at c2; the first r digit lands on the next step.
    A_21, B_21, C_21, D_21 = SA, Zero, SC, c1
    E_21, F_21 = bit6 * 2, c2

    # ── X22: r := r + bit*p (low->high add) ──
    b22 = _geq_expr(SE, One * 2)             # bit (constant through the pass)
    c22 = SE - b22 * 2
    r22 = _select(reglu(_geq_expr(SC, One), _geq_expr(n_r6, SB + One)),
                  _fv0(SC + One * 2 + SB * 2), Zero)
    p22 = _select(_geq_expr(n_p6, SB + One), _fv0(frE2 + One * 2 + SB * 2), Zero)
    s22 = r22 + _select(b22, p22, Zero) + c22
    cc22 = _geq_expr(s22, One * 10)
    q22 = s22 - cc22 * 10
    done22 = _geq_expr(SB + One, L226)
    # done: frame@c2 (E2 keeps p for pass 23), p'-head@c3
    A_22d, B_22d, C_22d, D_22d = SA, Zero, SF, c2
    E_22d, F_22d = Zero, c3
    A_22, B_22, C_22, D_22 = SA, SB + One, SC, SD
    E_22, F_22 = cc22 + b22 * 2, SF

    # ── X23: p := 2*p (low->high double) ──
    dj23 = _select(_geq_expr(n_p6, SB + One), _fv0(frE2 + One * 2 + SB * 2), Zero)
    t23 = dj23 * 2 + SE
    cc23 = _geq_expr(t23, One * 10)
    q23 = t23 - cc23 * 10
    done23 = _geq_expr(SB + One, n_p6 + One)
    n_a6 = _nlen6(frF2)
    # done: frame@c2 (E2 := SF carries p'), a'-head@c3
    A_23d, B_23d, C_23d, D_23d = SA, Zero, SC, c2
    E_23d, F_23d = Zero, c3
    A_23, B_23, C_23, D_23 = SA, SB + One, SC, SD
    E_23, F_23 = cc23, SF

    # ── X24: a := floor(a/2) (low->high) ──
    # q_i = fl2(d_i) + 5*par(d_{i+1}): halving needs no carry chain, the
    # borrow-in from the digit above is exactly its parity, so the pass runs
    # in emission (append) order like every other loop here.
    nz24p = _geq_expr(SE, One * 2)            # nz-so-far (bit 1)
    dj24 = _ndig6(frF2, SB)
    dj24n = _select(_geq_expr(n_a6, SB + One * 2), _ndig6(frF2, SB + One), Zero)
    q24 = _fl2_6(dj24) + _par6(dj24n) * 5
    nz24 = _geq_expr(nz24p + _geq_expr(q24, One), One)
    E24 = nz24 * 2
    done24 = _geq_expr(SB + One, n_a6)
    n_b6 = _nlen6(SA)
    # done: frame@c2 (F2 := SF carries a'), b'-head@c3, E packs nz_a into bit 2
    A_24d, B_24d, C_24d, D_24d = SA, Zero, SC, c2
    E_24d, F_24d = nz24 * 4, c3
    A_24, B_24, C_24, D_24 = SA, SB + One, SC, SD
    E_24, F_24 = E24, SF

    # ── X25: b := floor(b/2) (low->high); round end / deliver ──
    na25 = _geq_expr(SE, One * 4)             # nz_a (bit 2)
    nb25 = _geq_expr(SE - na25 * 4, One * 2)  # nz_b-so-far (bit 1)
    dj25 = _ndig6(SA, SB)
    dj25n = _select(_geq_expr(n_b6, SB + One * 2), _ndig6(SA, SB + One), Zero)
    q25 = _fl2_6(dj25) + _par6(dj25n) * 5
    nz25 = _geq_expr(nb25 + _geq_expr(q25, One), One)
    E25 = nz25 * 2 + na25 * 4
    done25 = _geq_expr(SB + One, n_b6)
    bothz = One - _geq_expr(E25, One * 2)     # nz_a == 0 and nz_b == 0
    # done+bothz: DELIVER r (A := SC, pop); done+!bothz: frame@c2 -> X21, A := SF
    A_25x, B_25x, C_25x, D_25x = SC, Zero, Zero, caller_c
    E_25x, F_25x = Zero, Zero
    A_25b, B_25b, C_25b, D_25b = SF, Zero, SC, c2
    E_25b, F_25b = Zero, SF
    A_25, B_25, C_25, D_25 = SA, SB + One, SC, SD
    E_25, F_25 = E25, SF

    # ── X31: shiftRight zero-scan of s (sum digits low->high) ──
    n_s6 = _nlen6(frF2)
    ds31 = _ndig6(frF2, SB)
    E31 = SE + ds31
    done31 = _geq_expr(SB + One, n_s6)
    z_s31 = reglu(done31, _eq_expr(E31, Zero))
    # s == 0: DELIVER a (frE2).  else: frame@c1 X32, a'-head@c2
    A_31z, B_31z, C_31z, D_31z = frE2, Zero, SC, caller_c
    E_31z, F_31z = Zero, Zero
    A_31d, B_31d, C_31d, D_31d = SA, Zero, SC, c1
    E_31d, F_31d = Zero, c2
    A_31, B_31, C_31, D_31 = SA, SB + One, SC, SD
    E_31, F_31 = E31, Zero

    # ── X32: a := floor(a/2) (low->high); zero-a exit ──
    # same local halving formula as X24 (q_i = fl2(d_i) + 5*par(d_{i+1})).
    n_a6s = _nlen6(frE2)
    nz32p = _geq_expr(SE, One * 2)            # nz-so-far (bit 1)
    dj32 = _ndig6(frE2, SB)
    dj32n = _select(_geq_expr(n_a6s, SB + One * 2), _ndig6(frE2, SB + One), Zero)
    q32 = _fl2_6(dj32) + _par6(dj32n) * 5
    nz32 = _geq_expr(nz32p + _geq_expr(q32, One), One)
    E32 = nz32 * 2
    done32 = _geq_expr(SB + One, n_a6s)
    z_a32 = reglu(done32, One - nz32)
    # a hit zero mid-loop: result 0 = the just-emitted all-zero chain (SF).
    # else: frame@c2 (E2 := SF carries a'), s'-head@c3, borrow init 1.
    A_32z, B_32z, C_32z, D_32z = SF, Zero, Zero, caller_c
    E_32z, F_32z = Zero, Zero
    A_32d, B_32d, C_32d, D_32d = SA, Zero, SC, c2
    E_32d, F_32d = One, c3
    A_32, B_32, C_32, D_32 = SA, SB + One, SC, SD
    E_32, F_32 = E32, SF

    # ── X33: s := s - 1 (low->high dec); zero-s exit ──
    c33 = SE - _geq_expr(SE, One * 2) * 2
    ds33 = _select(_geq_expr(n_s6, SB + One), _fv0(frF2 + One * 2 + SB * 2), Zero)
    t33 = ds33 - c33
    neg33 = _geq_expr(Zero, t33 + One)
    dig33 = _select(neg33, t33 + One * 10, t33)
    nz33 = _geq_expr(_geq_expr(SE, One * 2) + _geq_expr(dig33, One), One)
    E33 = neg33 + nz33 * 2
    done33 = _geq_expr(SB + One, n_s6)
    z_s33 = reglu(done33, One - nz33)
    # s reached 0: DELIVER a (frame E2).  else: frame@c2 (F2 := SF carries s'),
    # a''-head@c3 -> X32.
    A_33z, B_33z, C_33z, D_33z = frE2, Zero, SC, caller_c
    E_33z, F_33z = Zero, Zero
    A_33d, B_33d, C_33d, D_33d = SA, Zero, SC, c2
    E_33d, F_33d = Zero, c3
    A_33, B_33, C_33, D_33 = SA, SB + One, SC, SD
    E_33, F_33 = E33, SF

    # ══ WP6-G gcd (X 41-57): Stein binary gcd (K:702-733 mpz_gcd equivalent;
    # oracle-confirmed gcd 0 n = n, gcd n 0 = n, gcd 0 0 = 0).  Slots: frame
    # E2 = u head, F2 = v head; A = k (shared 2-power, integer register); the
    # odd-side halving passes X47/X49 reuse the X44/X45 per-digit arithmetic.
    # No size cap: the result is <= min(a, b).
    # (sel is defined again below in the compute-merge section; the gcd
    # payloads need it first — same body, same semantics.)
    def sel(*args):
        """Right-nested _select chain: sel(c1, e1, c2, e2, ..., default)."""
        r = args[-1]
        for i in range(len(args) - 3, -1, -2):
            r = _select(args[i], args[i + 1], r)
        return r

    ph41 = _eq_expr(frX, One * 41)
    ph42 = _eq_expr(frX, One * 42)
    ph43 = _eq_expr(frX, One * 43)
    ph44 = _eq_expr(frX, One * 44)
    ph45 = _eq_expr(frX, One * 45)
    ph46 = _eq_expr(frX, One * 46)
    ph47 = _eq_expr(frX, One * 47)
    ph48 = _eq_expr(frX, One * 48)
    ph49 = _eq_expr(frX, One * 49)
    ph50 = _eq_expr(frX, One * 50)
    ph52 = _eq_expr(frX, One * 52)
    ph53 = _eq_expr(frX, One * 53)
    ph56 = _eq_expr(frX, One * 56)
    ph57 = _eq_expr(frX, One * 57)
    n_u6 = _nlen6(frE2)
    n_v6 = _nlen6(frF2)
    n6c = _select(_geq_expr(n_u6, n_v6), n_u6, n_v6)   # max chain length

    # ── X41/X42: zero scans of u, v (gcd 0 b = b, gcd a 0 = a, gcd 0 0 = 0) ──
    du41 = _ndig6(frE2, SB)
    E41 = SE + du41
    done41 = _geq_expr(SB + One, n_u6)
    z41 = reglu(done41, _eq_expr(E41, Zero))
    # s == 0: DELIVER v (frF2).  else: frame@c1 -> X42
    A_41z, B_41z, C_41z, D_41z = frF2, Zero, SC, caller_c
    E_41z, F_41z = Zero, Zero
    A_41d, B_41d, C_41d, D_41d = SA, Zero, SC, c1
    E_41d, F_41d = Zero, Zero
    A_41, B_41, C_41, D_41 = SA, SB + One, SC, SD
    E_41, F_41 = E41, Zero
    dv42 = _ndig6(frF2, SB)
    E42 = SE + dv42
    done42 = _geq_expr(SB + One, n_v6)
    z42 = reglu(done42, _eq_expr(E42, Zero))
    # v == 0: DELIVER u.  else: frame@c1 -> X43 (both nonzero, enter loop)
    A_42z, B_42z, C_42z, D_42z = frE2, Zero, SC, caller_c
    E_42z, F_42z = Zero, Zero
    A_42d, B_42d, C_42d, D_42d = SA, Zero, SC, c1
    E_42d, F_42d = Zero, Zero
    A_42, B_42, C_42, D_42 = SA, SB + One, SC, SD
    E_42, F_42 = E42, Zero

    # ── X43: both-even gate (k++, then halve u and v once each) ──
    pu43 = _par6(_ndig6(frE2, Zero))
    pv43 = _par6(_ndig6(frF2, Zero))
    # BOTH even (k++ shared factor); the old `1 - pu·pv` read "not both odd" and
    # re-entered the shared-halving for (even,odd) pairs, inflating k.
    ev43 = reglu(One - pu43, One - pv43)
    # even: A=k+1, frame@c1 -> X44, u'-head@c2   odd: frame@c1 -> X46
    A_43e, B_43e, C_43e, D_43e = SA + One, Zero, SC, c1
    E_43e, F_43e = Zero, c2
    A_43o, B_43o, C_43o, D_43o = SA, Zero, SC, c1
    E_43o, F_43o = Zero, Zero

    # ── X44/X45: one halving pass each on u, v (shared-factor stripping) ──
    # X47 (u) and X49 (v) reuse the same per-digit arithmetic (names q44/q45).
    nz44p = _geq_expr(SE, One * 2)
    dj44 = _ndig6(frE2, SB)
    dj44n = _select(_geq_expr(n_u6, SB + One * 2), _ndig6(frE2, SB + One), Zero)
    q44 = _fl2_6(dj44) + _par6(dj44n) * 5
    nz44 = _geq_expr(nz44p + _geq_expr(q44, One), One)
    done44 = _geq_expr(SB + One, n_u6)
    # done: frame@c2 (E2 := SF), v'-head@c3 -> X45
    A_44d, B_44d, C_44d, D_44d = SA, Zero, SC, c2
    E_44d, F_44d = Zero, c3
    A_44, B_44, C_44, D_44 = SA, SB + One, SC, SD
    E_44, F_44 = nz44 * 2, SF
    nz45p = _geq_expr(SE, One * 2)
    dj45 = _ndig6(frF2, SB)
    dj45n = _select(_geq_expr(n_v6, SB + One * 2), _ndig6(frF2, SB + One), Zero)
    q45 = _fl2_6(dj45) + _par6(dj45n) * 5
    nz45 = _geq_expr(nz45p + _geq_expr(q45, One), One)
    done45 = _geq_expr(SB + One, n_v6)
    # done: frame@c2 (F2 := SF) -> X43
    A_45d, B_45d, C_45d, D_45d = SA, Zero, SC, c2
    E_45d, F_45d = Zero, Zero
    A_45, B_45, C_45, D_45 = SA, SB + One, SC, SD
    E_45, F_45 = nz45 * 2, SF

    # ── X46/X48: odd-side parity gates (halve u until odd, then v until odd) ──
    pu46 = _par6(_ndig6(frE2, Zero))
    ev46 = One - pu46
    # even: frame@c1 -> X47, u'-head@c2   odd: frame@c1 -> X48
    A_46e, B_46e, C_46e, D_46e = SA, Zero, SC, c1
    E_46e, F_46e = Zero, c2
    A_46o, B_46o, C_46o, D_46o = SA, Zero, SC, c1
    E_46o, F_46o = Zero, Zero
    A_46, B_46, C_46, D_46 = SA, Zero, SC, SD     # unreachable arm (X46 is 1-step)
    E_46, F_46 = Zero, Zero
    done47 = _geq_expr(SB + One, n_u6)
    # X47 done: frame@c2 (E2 := SF) -> X46
    A_47d, B_47d, C_47d, D_47d = SA, Zero, SC, c2
    E_47d, F_47d = Zero, Zero
    A_47, B_47, C_47, D_47 = SA, SB + One, SC, SD
    E_47, F_47 = nz44 * 2, SF
    pv48 = _par6(_ndig6(frF2, Zero))
    ev48 = One - pv48
    A_48e, B_48e, C_48e, D_48e = SA, Zero, SC, c1
    E_48e, F_48e = Zero, c2
    A_48o, B_48o, C_48o, D_48o = SA, Zero, SC, c1
    E_48o, F_48o = Zero, Zero
    done49 = _geq_expr(SB + One, n_v6)
    # X49 done: frame@c2 (F2 := SF) -> X48
    A_49d, B_49d, C_49d, D_49d = SA, Zero, SC, c2
    E_49d, F_49d = Zero, Zero
    A_49, B_49, C_49, D_49 = SA, SB + One, SC, SD
    E_49, F_49 = nz45 * 2, SF

    # ── X50: high->low magnitude compare (E = 0 tie / 1 u<v / 2 u>v) ──
    ic50 = n6c - One - SB
    du50 = _select(_geq_expr(n_u6, ic50 + One), _fv0(frE2 + One * 2 + ic50 * 2), Zero)
    dv50 = _select(_geq_expr(n_v6, ic50 + One), _fv0(frF2 + One * 2 + ic50 * 2), Zero)
    lt50 = _geq_expr(dv50, du50 + One)
    gt50 = _geq_expr(du50, dv50 + One)
    dec50 = _select(_geq_expr(SE, One), SE,
                    _select(lt50, One, _select(gt50, One * 2, Zero)))
    done50 = _geq_expr(SB + One, n6c)
    # done: frame@c1, result-head@c3?? -> X52 (v-=u) if u<v else X53 (u-=v);
    # head V0 = n6c; no digit emitted on the compare steps.
    A_50u, B_50u, C_50u, D_50u = SA, Zero, SC, c1
    E_50u, F_50u = Zero, c2
    A_50v, B_50v, C_50v, D_50v = SA, Zero, SC, c1
    E_50v, F_50v = Zero, c2
    A_50, B_50, C_50, D_50 = SA, SB + One, SC, SD
    E_50, F_50 = dec50, Zero

    # ── X52: v := v - u (borrow, low->high); X53: u := u - v ──
    b52 = SE - _geq_expr(SE, One * 2) * 2
    nz52p = _geq_expr(SE, One * 2)
    du52 = _select(_geq_expr(n_u6, SB + One), _ndig6(frE2, SB), Zero)
    dv52 = _select(_geq_expr(n_v6, SB + One), _ndig6(frF2, SB), Zero)
    t52 = dv52 - du52 - b52
    ng52 = One - _geq_expr(t52, Zero)
    s52 = t52 + ng52 * 10
    nz52 = _geq_expr(nz52p + _geq_expr(s52, One), One)
    E52 = ng52 + nz52 * 2
    done52 = _geq_expr(SB + One, n6c)
    zero52 = reglu(done52, One - nz52)
    # done+nz: frame@c2 (E2 := SF) -> X46; done+zero: frame@c2 -> X56 (u wins)
    A_52d, B_52d, C_52d, D_52d = SA, Zero, SC, c2
    E_52d, F_52d = Zero, Zero
    A_52z, B_52z, C_52z, D_52z = SA, Zero, SC, c2
    E_52z, F_52z = Zero, Zero
    b53 = SE - _geq_expr(SE, One * 2) * 2
    nz53p = _geq_expr(SE, One * 2)
    t53 = du52 - dv52 - b53
    ng53 = One - _geq_expr(t53, Zero)
    s53 = t53 + ng53 * 10
    nz53 = _geq_expr(nz53p + _geq_expr(s53, One), One)
    E53 = ng53 + nz53 * 2
    done53 = _geq_expr(SB + One, n6c)
    zero53 = reglu(done53, One - nz53)
    # done+nz: frame@c2 (E2 := SF) -> X46; done+zero: frame@c2 (E2 := F2, v
    # wins, swapped into the doubling slot) -> X56
    A_53d, B_53d, C_53d, D_53d = SA, Zero, SC, c2
    E_53d, F_53d = Zero, Zero
    A_53z, B_53z, C_53z, D_53z = SA, Zero, SC, c2
    E_53z, F_53z = Zero, Zero
    A_52, B_52, C_52, D_52 = SA, SB + One, SC, SD
    E_52, F_52 = E52, SF
    A_53, B_53, C_53, D_53 = SA, SB + One, SC, SD
    E_53, F_53 = E53, SF

    # ── X56: k gate; X57: one doubling pass of the gcd core (chain in E2) ──
    zero56 = One - _geq_expr(SA, One)
    A_56z, B_56z, C_56z, D_56z = frE2, Zero, SC, caller_c
    E_56z, F_56z = Zero, Zero
    A_56d, B_56d, C_56d, D_56d = SA - One, Zero, SC, c1
    E_56d, F_56d = Zero, c2
    n7 = _fv0(frE2) + One
    dj57 = _select(_geq_expr(n7 - One, SB + One), _fv0(frE2 + One * 2 + SB * 2), Zero)
    t57 = dj57 * 2 + SE
    cc57 = _geq_expr(t57, One * 10)
    q57 = t57 - cc57 * 10
    done57 = _geq_expr(SB + One, n7)
    # done: frame@c2 (E2 := SF) -> X56
    A_57d, B_57d, C_57d, D_57d = SA, Zero, SC, c2
    E_57d, F_57d = Zero, Zero
    A_57, B_57, C_57, D_57 = SA, SB + One, SC, SD
    E_57, F_57 = cc57, SF

    ph41g = reglu(is_compute, ph41)
    ph42g = reglu(is_compute, ph42)
    ph43g = reglu(is_compute, ph43)
    ph44g = reglu(is_compute, ph44)
    ph45g = reglu(is_compute, ph45)
    ph46g = reglu(is_compute, ph46)
    ph47g = reglu(is_compute, ph47)
    ph48g = reglu(is_compute, ph48)
    ph49g = reglu(is_compute, ph49)
    ph50g = reglu(is_compute, ph50)
    ph52g = reglu(is_compute, ph52)
    ph53g = reglu(is_compute, ph53)
    ph56g = reglu(is_compute, ph56)
    ph57g = reglu(is_compute, ph57)
    g41z = reglu(ph41g, z41)
    g41d = reglu(ph41g, reglu(done41, One - z41))
    g42z = reglu(ph42g, z42)
    g42d = reglu(ph42g, reglu(done42, One - z42))
    g43e = reglu(ph43g, ev43)
    g43o = reglu(ph43g, One - ev43)
    g44d = reglu(ph44g, done44)
    g45d = reglu(ph45g, done45)
    g46e = reglu(ph46g, ev46)
    g46o = reglu(ph46g, One - ev46)
    g47d = reglu(ph47g, done47)
    g48e = reglu(ph48g, ev48)
    g48o = reglu(ph48g, One - ev48)
    g49d = reglu(ph49g, done49)
    g50u = reglu(ph50g, reglu(done50, _eq_expr(dec50, One)))
    g50v = reglu(ph50g, reglu(done50, One - _eq_expr(dec50, One)))
    g52z = reglu(ph52g, zero52)
    g52d = reglu(ph52g, reglu(done52, nz52))
    g53z = reglu(ph53g, zero53)
    g53d = reglu(ph53g, reglu(done53, nz53))
    g56z = reglu(ph56g, zero56)
    g56d = reglu(ph56g, One - zero56)
    g57d = reglu(ph57g, done57)
    wp6g_frame = (g41d + g42d + g43e + g43o + g44d + g45d + g46e + g46o
                  + g47d + g48e + g48o + g49d + g50u + g50v + g52d + g52z
                  + g53d + g53z + g56d + g57d)
    wp6g_head = g43e + g44d + g46e + g48e + g50u + g50v + g56d
    wp6g_dig = ph44g + ph45g + ph47g + ph49g + ph52g + ph53g + ph57g
    # pure digit/scan steps (the done arms and 1-step gates are subtracted)
    g41s = ph41g - g41z - g41d
    g42s = ph42g - g42z - g42d
    g44s = ph44g - g44d
    g45s = ph45g - g45d
    g47s = ph47g - g47d
    g49s = ph49g - g49d
    g50s = ph50g - g50u - g50v
    g52s = ph52g - g52z - g52d
    g53s = ph53g - g53z - g53d
    g57s = ph57g - g57d
    wp6g_all = (ph41g + ph42g + ph43g + ph44g + ph45g + ph46g + ph47g
                + ph48g + ph49g + ph50g + ph52g + ph53g + ph56g + ph57g)
    A6 = sel(g41z, A_41z, g42z, A_42z, g43e, A_43e, g56z, A_56z, g56d, A_56d, SA)
    B6 = sel(g41s, SB + One, g42s, SB + One, g44s, SB + One, g45s, SB + One,
             g47s, SB + One, g49s, SB + One, g50s, SB + One, g52s, SB + One,
             g53s, SB + One, g57s, SB + One, Zero)
    D6 = sel(g41s, SD, g42s, SD, g44s, SD, g45s, SD, g47s, SD, g49s, SD,
             g50s, SD, g52s, SD, g53s, SD, g57s, SD,
             g41z, D_41z, g42z, D_42z, g56z, D_56z,
             g41d, c1, g42d, c1, g43e, c1, g43o, c1, g46e, c1, g46o, c1,
             g48e, c1, g48o, c1, g50u, c1, g50v, c1, g56d, c1,
             g44d, c2, g45d, c2, g47d, c2, g49d, c2, g52d, c2, g52z, c2,
             g53d, c2, g53z, c2, g57d, c2, SD)
    E6 = sel(g41s, E41, g42s, E42, g44s, nz44 * 2, g47s, nz44 * 2,
             g45s, nz45 * 2, g49s, nz45 * 2, g50s, dec50, g52s, E52,
             g53s, E53, g57s, cc57, Zero)
    F6 = sel(g44s, SF, g45s, SF, g47s, SF, g49s, SF, g52s, SF, g53s, SF,
             g57s, SF, g43e, c2, g44d, c3, g46e, c2, g48e, c2, g50u, c2,
             g50v, c2, g56d, c2, Zero)
    head6_V0 = _select(g43e + g46e, n_u6,
               _select(g44d + g48e, n_v6,
               _select(g50u + g50v, n6c, _fv0(frE2) + One)))
    # X52 (v:=v−u) result head lives in the F2 slot; X53 (u:=u−v) in E2.  The
    # pre-emitted head from the X50 done arms is filled by the borrow pass.
    frame6_E2 = sel(g44d, SF, g47d, SF, g52d, frE2, g52z, frE2,
                    g53d, SF, g53z, frF2, g57d, SF, frE2)
    frame6_F2 = sel(g45d, SF, g49d, SF, g52d, SF, frF2)
    frame6_X = sel(g41d, One * 42, g42d, One * 43, g43e, One * 44,
                   g43o, One * 46, g44d, One * 45, g45d, One * 43,
                   g46e, One * 47, g46o, One * 48, g47d, One * 46,
                   g48e, One * 49, g48o, One * 50, g49d, One * 48,
                   g50u, One * 52, g50v, One * 53, g52d, One * 46,
                   g52z, One * 56, g53d, One * 46, g53z, One * 56,
                   g56d, One * 57, g57d, One * 56, One * 41)

    # ══ WP6-S shiftLeft (X 61-68): Nat.shiftLeft v k ═══════════════════════
    # Kernel K/type_checker.cpp:677-690: zero v delivers 0; else k =
    # get_count_arg(arg2) (throws for k > 4294967295, K:308-313), then
    # reject when size(v) + k/8 + 1 > g_nat_max_size, result v·2^k.
    # size(v) = 8·limbs ≥ 8·L(D) with L(D) = 1 + floor((D−1)·3321/64000) the
    # limb-count lower bound for a D-digit decimal chain, so
    #   k + 64·L(D) >= 8·MAX   ⇒   CERTAIN reject   (derivation in VM_SPEC).
    # The machine rejects exactly on that (>= includes the tie, matching
    # "size + k/8 + 1 > MAX"); the band where the TRUE limbs exceed L(D)
    # (kernel rejects, machine accepts) produces results of >= MAX bytes —
    # not materializable as a chain here either way; documented exclusion.
    # All guard arithmetic runs on decimal DIGIT chains (lex passes) — k
    # reaches 4294967295 and 8·MAX 1073741824, both past fp32's exact-integer
    # range; digits (0..9), per-digit sums (<30) and 64·L (<= 27264) stay
    # exact.
    # Phases: 61 k digit-count gate (<=9 -> 63; ==10 -> 62; >=11 reject)
    # 62 lex k vs 4294967295  63 v zero-scan (zero -> deliver frE2; else
    # pre-emit m1=k+64·L head, V0=n_k+1)  64 m1 fill pass  65 lex m1 vs
    # 8·MAX (accept only strictly below)  66 Horner-load k into A
    # 67 loop gate (A=0 -> deliver frE2; else A--, pre-emit doubled head)
    # 68 x2 pass (mirrors X57).  Slots: E2 = v/result head, F2 = k head
    # (shr layout), A = k counter, B = cursor, C = extras (untouched),
    # E = carry / lex verdict (0 tie, 1 less, 2 greater), F = active head.
    ph61 = _eq_expr(frX, One * 61)
    ph62 = _eq_expr(frX, One * 62)
    ph63 = _eq_expr(frX, One * 63)
    ph64 = _eq_expr(frX, One * 64)
    ph65 = _eq_expr(frX, One * 65)
    ph66 = _eq_expr(frX, One * 66)
    ph67 = _eq_expr(frX, One * 67)
    ph68 = _eq_expr(frX, One * 68)
    ph61g = reglu(is_compute, ph61)
    ph62g = reglu(is_compute, ph62)
    ph63g = reglu(is_compute, ph63)
    ph64g = reglu(is_compute, ph64)
    ph65g = reglu(is_compute, ph65)
    ph66g = reglu(is_compute, ph66)
    ph67g = reglu(is_compute, ph67)
    ph68g = reglu(is_compute, ph68)

    # LEAN_NAT_MAX_SIZE is read ONCE here (graph build time), mirroring the
    # kernel's initialize_type_checker() contract (K:1320-1321); the value
    # enters the graph only as digit-table DATA, never as a branch.
    _NAT_MAX = _read_nat_size_env()
    _MAX8 = 8 * _NAT_MAX
    _MAX8_DIG = [int(c) for c in str(_MAX8)][::-1]     # low -> high
    _LEN8 = len(_MAX8_DIG)
    _U32_DIG = [int(c) for c in str(4294967295)][::-1]
    _MAX_DIG = [int(c) for c in str(_NAT_MAX)][::-1]   # low -> high
    _LENM = len(_MAX_DIG)
    # Kernel byte-size reject <=> limbs(r) > MAX/8 <=> limbs(r) >= T (K:656-658,
    # 705-710).  limbs >= L(D) (see _limbs6 lower bound) and L is monotone, so
    # an EXACT digit count D_r rejects consistently iff D_r >= _T_DIG:
    # L(D) >= T <=> floor((D-1)*3321/64000) >= T-1 <=> D >= 1+ceil(64000(T-1)/3321).
    _T_LIMB = _NAT_MAX // 8 + 1
    _T_DIG = 1 + (64000 * (_T_LIMB - 1) + 3320) // 3321
    # The graph compares D_r against _T_DIG as an fp32 scalar.  Above 2^24 the
    # exact integer may not be representable; ROUND UP to the next fp32 value
    # so the in-graph threshold is >= the true one (reject set can only shrink,
    # never outside kernel-reject).  For every realizable chain length the two
    # coincide; under a small baked MAX _T_DIG < 2^24 is exact anyway.
    import struct as _struct
    _tf = _T_DIG
    _bits = _struct.unpack('<I', _struct.pack('<f', float(_tf)))[0]
    _rep = _struct.unpack('<f', _struct.pack('<I', _bits))[0]
    while _rep < _tf:
        _bits += 1
        _rep = _struct.unpack('<f', _struct.pack('<I', _bits))[0]
    _T_DIG_CMP = _rep

    def _limbs6(D):
        """L(D) = 1 + floor((D−1)·3321/64000) as one threshold sweep; 425
        terms cover every D a stream can hold (a D-digit chain costs 2D+1
        tokens; fp32 exact for D <= 5108)."""
        dm = (D - One) * 3321
        t = One
        for j in range(1, 426):
            t = t + _geq_expr(dm, One * (64000 * j))
        return t

    # 64·L(D) and its decimal digits (value <= 27264): power-of-10 sweep.
    s64 = _limbs6(n_u6) * 64
    d4_64 = _geq_expr(s64, One * 10000) + _geq_expr(s64, One * 20000)
    r4_64 = s64 - d4_64 * 10000
    d3_64 = sum((_geq_expr(r4_64, One * (j * 1000)) for j in range(1, 10)), Zero)
    r3_64 = r4_64 - d3_64 * 1000
    d2_64 = sum((_geq_expr(r3_64, One * (j * 100)) for j in range(1, 10)), Zero)
    r2_64 = r3_64 - d2_64 * 100
    d1_64 = sum((_geq_expr(r2_64, One * (j * 10)) for j in range(1, 10)), Zero)
    d0_64 = r2_64 - d1_64 * 10
    s64dig = sel(_eq_expr(SB, Zero), d0_64, _eq_expr(SB, One), d1_64,
                 _eq_expr(SB, One * 2), d2_64, _eq_expr(SB, One * 3), d3_64,
                 _eq_expr(SB, One * 4), d4_64, Zero)

    # ── X61: k digit-count gate.  n_v6 = _nlen6(frF2) = digits of k. ──
    g61cap = reglu(ph61g, _geq_expr(n_v6, One * 11))   # > 10 digits: k > cap
    g61l10 = reglu(ph61g, _eq_expr(n_v6, One * 10))
    g61sm = reglu(ph61g, One - _geq_expr(n_v6, One * 10))

    # ── X62: lex k vs 4294967295 (high->low; reject only when GREATER) ──
    ic62 = One * 9 - SB
    dk62 = _ndig6(frF2, ic62)
    dc62 = Zero
    for j in range(10):
        dc62 = _select(_eq_expr(ic62, One * j), One * _U32_DIG[j], dc62)
    lt62 = _geq_expr(dc62, dk62 + One)
    gt62 = _geq_expr(dk62, dc62 + One)
    dec62 = _select(_geq_expr(SE, One), SE,
                    _select(lt62, One, _select(gt62, One * 2, Zero)))
    done62 = _geq_expr(SB + One, One * 10)
    g62r = reglu(ph62g, reglu(done62, _geq_expr(dec62, One * 2)))
    g62a = reglu(ph62g, reglu(done62, One - _geq_expr(dec62, One * 2)))
    g62s = ph62g - g62r - g62a

    # ── X63: zero-scan of v (frE2); nonzero -> pre-emit m1 head ──
    E63 = SE + _ndig6(frE2, SB)
    done63 = _geq_expr(SB + One, n_u6)
    z63 = reglu(done63, _eq_expr(E63, Zero))
    g63z = reglu(ph63g, z63)
    g63d = reglu(ph63g, reglu(done63, One - z63))
    g63s = ph63g - g63z - g63d

    # ── X64: fill m1 = k + 64·L (low->high decimal add, n_k+1 steps) ──
    k64 = _select(_geq_expr(n_v6, SB + One), _ndig6(frF2, SB), Zero)
    t64 = k64 + s64dig + SE
    cc64 = _geq_expr(t64, One * 10)
    q64 = t64 - cc64 * 10
    done64 = _geq_expr(SB + One, n_v6 + One)
    g64d = reglu(ph64g, done64)
    g64s = ph64g - g64d

    # ── X65: lex m1 vs 8·MAX (high->low; ACCEPT only if strictly below) ──
    n65 = _select(_geq_expr(n_v6 + One, One * _LEN8), n_v6 + One, One * _LEN8)
    ic65 = n65 - One - SB
    dm65 = _select(_geq_expr(n_v6 + One, ic65 + One),
                   _fv0(SF + One * 2 + ic65 * 2), Zero)
    dc65 = Zero
    for j in range(_LEN8):
        dc65 = _select(_eq_expr(ic65, One * j), One * _MAX8_DIG[j], dc65)
    lt65 = _geq_expr(dc65, dm65 + One)
    gt65 = _geq_expr(dm65, dc65 + One)
    dec65 = _select(_geq_expr(SE, One), SE,
                    _select(lt65, One, _select(gt65, One * 2, Zero)))
    done65 = _geq_expr(SB + One, n65)
    g65a = reglu(ph65g, reglu(done65, _eq_expr(dec65, One)))
    g65r = reglu(ph65g, reglu(done65, One - _eq_expr(dec65, One)))
    g65s = ph65g - g65a - g65r

    # ── X66: Horner-load k into A (low->high digits) ──
    # ── X66: load k into A (HIGH->low Horner: A' = A·10 + d_top..d_i; a
    # low->high Horner would reverse the digits — 30 → 3 — verified live) ──
    ic66 = n_v6 - One - SB
    A66 = SA * 10 + _ndig6(frF2, ic66)
    done66 = _geq_expr(SB + One, n_v6)
    g66d = reglu(ph66g, done66)
    g66s = ph66g - g66d

    # ── X67: loop gate on the doubling counter ──
    zero67 = _eq_expr(SA, Zero)
    g67z = reglu(ph67g, zero67)
    g67d = reglu(ph67g, One - zero67)

    # ── X68: result := 2·result (low->high double, mirrors X57) ──
    n7s = _fv0(frE2) + One
    dj68 = _select(_geq_expr(n7s - One, SB + One),
                   _fv0(frE2 + One * 2 + SB * 2), Zero)
    t68 = dj68 * 2 + SE
    cc68 = _geq_expr(t68, One * 10)
    q68 = t68 - cc68 * 10
    done68 = _geq_expr(SB + One, n7s)
    g68d = reglu(ph68g, done68)
    g68s = ph68g - g68d

    rej_s = g61cap + g62r + g65r     # kernel-consistent rejects (VM ERR 1)

    A6s = sel(g63z, frE2, g65a, Zero, g66s, A66, g66d, A66, g67z, frE2,
              g67d, SA - One, SA)
    B6s = sel(g62s, SB + One, g63s, SB + One, g64s, SB + One, g65s, SB + One,
              g66s, SB + One, g68s, SB + One, Zero)
    D6s = sel(g61sm, c1, g61l10, c1, g62a, c1, g63z, caller_c, g63d, c1,
              g64d, c2, g65a, c1, g66d, c1, g67z, caller_c, g67d, c1,
              g68d, c2, SD)
    E6s = sel(g61sm, Zero, g61l10, Zero, g62s, dec62, g62a, Zero,
              g63z, Zero, g63d, Zero, g63s, E63, g64s, cc64, g64d, Zero,
              g65s, dec65, g65a, Zero, g66d, Zero, g67z, Zero, g67d, Zero,
              g68s, cc68, g68d, Zero, SE)
    F6s = sel(g63z, Zero, g63d, c2, g67z, Zero, g67d, c2, SF)
    head6s_V0 = _select(g63d, n_v6 + One, _fv0(frE2) + One)
    frame6s_E2 = _select(g68d, SF, frE2)
    frame6s_F2 = frF2
    frame6s_X = sel(g61sm, One * 63, g61l10, One * 62, g62a, One * 63,
                    g63d, One * 64, g64d, One * 65, g65a, One * 66,
                    g66d, One * 67, g67d, One * 68, g68d, One * 67, One * 61)
    wp6s_frame = (g61sm + g61l10 + g62a + g63d + g64d + g65a + g66d
                  + g67d + g68d)
    wp6s_head = g63d + g67d
    wp6s_dig = ph64g + ph68g
    wp6s_all = (ph61g + ph62g + ph63g + ph64g + ph65g + ph66g + ph67g + ph68g)

    # ── WP6 done-step emission gates (frame / head per transition) ──
    g21 = reglu(is_compute, ph21)
    g22d = reglu(is_compute, reglu(ph22, done22))
    g23d = reglu(is_compute, reglu(ph23, done23))
    g24d = reglu(is_compute, reglu(ph24, done24))
    g25x = reglu(is_compute, reglu(ph25, reglu(done25, bothz)))
    g25b = reglu(is_compute, reglu(ph25, reglu(done25, One - bothz)))
    g31z = reglu(is_compute, reglu(ph31, z_s31))
    g31d = reglu(is_compute, reglu(ph31, reglu(done31, One - z_s31)))
    # g32z/g33z MUST carry the phase gate (contrast C's first cut): z_a32/z_s33
    # read the chain heads in frE2/frF2, and on X21-25/X41-57 work frames those
    # slots hold other chains — without reglu(phNN, ·) the zero-scan arm fires
    # on a foreign frame (and drives g32n = ph32g − g32z − g32d negative, which
    # _select extrapolates into the register merge).
    g32z = reglu(is_compute, reglu(ph32, z_a32))
    g32d = reglu(is_compute, reglu(ph32, reglu(done32, nz32)))
    g33z = reglu(is_compute, reglu(ph33, z_s33))
    g33d = reglu(is_compute, reglu(ph33, reglu(done33, nz33)))
    wp6_frame = g21 + g22d + g23d + g24d + g25b + g31d + g32d + g33d
    wp6_head = g21 + g22d + g23d + g24d + g31d + g32d + g33d
    # full per-phase gates (digit steps included) and the not-done complements;
    # the g*done gates are subsets, so these differences stay 0/1.
    ph22g = reglu(is_compute, ph22)
    ph23g = reglu(is_compute, ph23)
    ph24g = reglu(is_compute, ph24)
    ph25g = reglu(is_compute, ph25)
    ph31g = reglu(is_compute, ph31)
    ph32g = reglu(is_compute, ph32)
    ph33g = reglu(is_compute, ph33)
    g22n = ph22g - g22d
    g23n = ph23g - g23d
    g24n = ph24g - g24d
    g25n = ph25g - g25x - g25b
    g31n = ph31g - g31z - g31d
    g32n = ph32g - g32z - g32d
    g33n = ph33g - g33z - g33d

    # ── compute merge ───────────────────────────────────────────────────────
    ph3s = reglu(is_compute, reglu(ph3, simplop))
    ph3c = reglu(is_compute, reglu(ph3, cellop))
    ph4g = reglu(is_compute, ph4)
    ph5g = reglu(is_compute, ph5)
    ph6g = reglu(is_compute, ph6)
    ph10g = reglu(is_compute, ph10)
    ph13g = reglu(is_compute, ph13)

    def sel(*args):
        """Right-nested _select chain: sel(c1, e1, c2, e2, ..., default)."""
        r = args[-1]
        for i in range(len(args) - 3, -1, -2):
            r = _select(args[i], args[i + 1], r)
        return r

    # ══ WP6-F1/F2 size guards: exact-digit strip scan (X76) ═════════════════
    # Kernel checks the COMPUTED result of succ/add/sub/mul (K:656-658,
    # 705-710): reject <=> 8*limbs(r) > MAX <=> limbs(r) >= T.  limbs >= L(D)
    # (_limbs6 lower bound), so with the EXACT result digit count D_r the
    # certain-reject form is D_r >= _T_DIG (=> limbs >= L >= T => bytes > MAX).
    # A head-V0 bound alone is NOT sound in this direction (sub can cancel,
    # mul heads pad +1): machine-reject must stay inside kernel-reject, so we
    # divert the delivery into X76, a high->low scan of the materialized
    # result chain: first nonzero digit at idx = V0-1-SB gives D_r = V0-SB;
    # an all-zero chain exits at SB = V0-1 with D_r = 1 (value 0, bytes 8 <=
    # MAX under the MAX >= 8 assumption — documented in VM_SPEC §WP6-G).
    # pred and sub-underflow deliver 0 / a smaller value the kernel never
    # size-checks, so they are excluded from the divert (scan_go).
    # The divert step (done_s / mul_done) keeps EVERY register arm of the
    # original delivery (A=S F, B=C=E=F=0) except D — it writes the X=76
    # frame at c2 (after the final digit at c1) with the caller pop target
    # (caller_c / ncV2) parked in slot V2; X76's done step then pops
    # D := frV2 exactly like done_s used to.  The scan reads the result chain
    # through the FOCUS register: the divert step already moved the head SF
    # into A and zeroes F, so SA is the chain head on X76.
    scan_go = (reglu(ph3s, reglu(done_s, addfam + reglu(opg4, One - underflow)))
               + mul_done)
    ph76 = _eq_expr(frX, One * 76)
    ph76g = reglu(is_compute, ph76)
    v0_76 = _fv0(SA)
    hit76 = _geq_expr(_ndig6(SA, v0_76 - One - SB), One)
    done76 = SE + reglu(One - SE, _geq_expr(SB, v0_76 - One))
    A76 = SA
    # B freeze on the hit step: done76 fires one step later (SE lag), so an
    # extra +1 there would shift D_r = v0_76 - SB down by one (false accept
    # exactly at the threshold, e.g. a 21-digit result vs _T_DIG=21).
    B76 = _select(done76, Zero, SB + One - reglu(One - SE, hit76))
    E76 = SE + reglu(One - SE, hit76)
    D76 = _select(done76, frV2, SD)
    F76 = Zero
    rej_q = reglu(ph76g, reglu(done76, _geq_expr(v0_76 - SB, One * _T_DIG_CMP)))
    # WP6-F1/F2 operand-side gate (K/type_checker.cpp:315-321): the kernel
    # type-checks literal arguments before any reduce, so an oversized literal
    # operand throws even when the term would compute a small result.  The
    # reduce path never visits operands as infer targets, so enforce it here
    # from the operand chain heads: a nat-literal operand with exact digit
    # count D >= _T_DIG has limbs >= L(D) >= T > MAX/8, i.e. the kernel would
    # throw.  Non-literal (stuck) operands deliver a V0 that is not a digit
    # count, so they are masked out.  Band slack below _T_DIG stays a
    # documented machine-accept (VM_SPEC §WP6-G).
    c2K_d23 = fetch_by_position([k_], SA)[0]
    is_lit2_d23 = reglu(_kind_eq_raw(c2K_d23, K_LIT, One),
                        _eq_expr(fetch_by_position([v1_], SA)[0], Zero))
    rej_o = (reglu(d23, _geq_expr(
                 _select(_geq_expr(_select(is_lit1_d23, n1_d23, Zero),
                                   _select(is_lit2_d23, n2, Zero)),
                         _select(is_lit1_d23, n1_d23, Zero),
                         _select(is_lit2_d23, n2, Zero)),
                 One * _T_DIG_CMP))
             + reglu(dn1, _geq_expr(n1_dn1, One * _T_DIG_CMP)))

    # ══ WP6-F3/F9 pow guards (K:661-675): X71-X75 ══════════════════════════
    # get_count_arg(exp) runs BEFORE the base gate (even base 0/1 with a
    # > UINT32_MAX exponent throws), so X71/X72 mirror shiftLeft's X61/X62
    # count-gate + 10-digit lex on the EXPONENT chain — here held in the
    # FOCUS register (A = v_done at d23; n2 = its digit count).  The pow
    # frame at d23 carries V2 = ST' pos, so the BASE head is nbV1 (V1 of
    # ST' = v1 pos) throughout X71-X73.
    # Then the size check: kernel rejects <=> base > 1 /\ k != 0 /\
    # size(base) > MAX/k; integer equivalence gives size(base)*k > MAX
    # (K:669 comment).  Machine certain form: 8*L(D_a)*k > MAX (L <= limbs).
    # X73 gates base > 1 (Nat.zero const via _wz6; one-digit "0"/"1" via the
    # V0==1 head — chains are canonically encoded, no leading zeros, so the
    # gates are provably 0/1 and exclusive) and pre-emits the product chain
    # p = s*k at c2 with V0 = n2+10 (s = 8*L(D_a) < 10^6 for any
    # materializable base; the +10 pad drains the carry in every case).
    # X74 fills p low->high: t = d*s + carry <= 10s < 10^7 < 2^24 (fp32-exact),
    # decimal-place threshold decomposition for the /10 split.
    # X75 lexes p against the baked MAX digits (strict > rejects; a tie
    # accepts, matching size*k > MAX).  Acceptance continues at X10.
    ph71 = _eq_expr(frX, One * 71)
    ph72 = _eq_expr(frX, One * 72)
    ph73 = _eq_expr(frX, One * 73)
    ph74 = _eq_expr(frX, One * 74)
    ph75 = _eq_expr(frX, One * 75)
    ph71g = reglu(is_compute, ph71)
    ph72g = reglu(is_compute, ph72)
    ph73g = reglu(is_compute, ph73)
    ph74g = reglu(is_compute, ph74)
    ph75g = reglu(is_compute, ph75)
    g71big = reglu(ph71g, _geq_expr(n2, One * 11))     # > 10 digits: > cap
    g71lex = reglu(ph71g, _eq_expr(n2, One * 10))
    g71sm = reglu(ph71g, One - _geq_expr(n2, One * 10))

    ic72 = One * 9 - SB
    dk72 = _ndig6(SA, ic72)
    dc72 = Zero
    for j in range(10):
        dc72 = _select(_eq_expr(ic72, One * j), One * _U32_DIG[j], dc72)
    lt72 = _geq_expr(dc72, dk72 + One)
    gt72 = _geq_expr(dk72, dc72 + One)
    dec72 = _select(_geq_expr(SE, One), SE,
                    _select(lt72, One, _select(gt72, One * 2, Zero)))
    done72 = _geq_expr(SB + One, One * 10)
    g72r = reglu(ph72g, reglu(done72, _geq_expr(dec72, One * 2)))
    g72a = reglu(ph72g, reglu(done72, One - _geq_expr(dec72, One * 2)))
    g72s = ph72g - g72r - g72a

    la73 = _nlen6(nbV1)
    da0 = _ndig6(nbV1, Zero)
    z0a73 = _select(_wz6(nbV1), One,
                    _select(_eq_expr(la73, One), _eq_expr(da0, Zero), Zero))
    o_a73 = reglu(_eq_expr(la73, One), _eq_expr(da0, One))
    gt1_73 = One - z0a73 - o_a73
    s73 = _limbs6(la73) * 8

    d74 = _select(_geq_expr(SB, n2), Zero, _ndig6(SA, SB))
    t74 = reglu(d74, frF2) + SE
    c6_74 = sum((_geq_expr(t74, One * (j * 1000000)) for j in range(1, 10)),
                Zero)
    u6_74 = t74 - c6_74 * 1000000
    c5_74 = sum((_geq_expr(u6_74, One * (j * 100000)) for j in range(1, 10)),
                Zero)
    u5_74 = u6_74 - c5_74 * 100000
    c4_74 = sum((_geq_expr(u5_74, One * (j * 10000)) for j in range(1, 10)),
                Zero)
    u4_74 = u5_74 - c4_74 * 10000
    c3_74 = sum((_geq_expr(u4_74, One * (j * 1000)) for j in range(1, 10)),
                Zero)
    u3_74 = u4_74 - c3_74 * 1000
    c2_74 = sum((_geq_expr(u3_74, One * (j * 100)) for j in range(1, 10)),
                Zero)
    u2_74 = u3_74 - c2_74 * 100
    c1_74 = sum((_geq_expr(u2_74, One * (j * 10)) for j in range(1, 10)),
                Zero)
    dig74 = u2_74 - c1_74 * 10
    car74 = (c1_74 + c2_74 * 10 + c3_74 * 100 + c4_74 * 1000
             + c5_74 * 10000 + c6_74 * 100000)
    done74 = _geq_expr(SB + One, n2 + One * 10)
    g74d = reglu(ph74g, done74)
    g74s = ph74g - g74d

    maxlen75 = _select(_geq_expr(n2 + One * 10, One * _LENM), n2 + One * 10,
                       One * _LENM)
    ic75 = maxlen75 - One - SB
    pd75 = _select(_geq_expr(ic75, n2 + One * 10), Zero,
                   _fv0(frE2 + One * 2 + ic75 * 2))
    md75 = Zero
    for j in range(_LENM):
        md75 = _select(_eq_expr(ic75, One * j), One * _MAX_DIG[j], md75)
    lt75 = _geq_expr(md75, pd75 + One)
    gt75 = _geq_expr(pd75, md75 + One)
    dec75 = _select(_geq_expr(SE, One), SE,
                    _select(lt75, One, _select(gt75, One * 2, Zero)))
    done75 = _geq_expr(SB + One, maxlen75)
    g75r = reglu(ph75g, reglu(done75, _geq_expr(dec75, One * 2)))
    g75a = reglu(ph75g, reglu(done75, One - _geq_expr(dec75, One * 2)))
    g75s = ph75g - g75r - g75a

    rej_p = g71big + g72r + g75r    # kernel-consistent pow guards (VM ERR 1)
    # frame emission gates for the guard phases (X73 is a single-step phase:
    # both exits rewrite the frame; the g71big reject step emits one too —
    # harmless, the driver halts on that step).
    wp6p_frame = (g71big + g71lex + g71sm + g72r + g72a + ph73g
                  + g74d + g75r + g75a)
    wp6p_all = ph71g + ph72g + ph73g + ph74g + ph75g
    head_p_V0 = n2 + One * 10
    frame_p_E2 = _select(ph73g, _select(gt1_73, c2, frE2),
                         _select(ph74g + ph75g, frE2, frE2))
    frame_p_F2 = _select(ph73g, s73, _select(ph74g + ph75g, frF2, frF2))
    frame_p_V2 = frV2
    frame_p_X = sel(g71big, One * 73, g71lex, One * 72, g71sm, One * 73,
                    g72r, One * 73, g72a, One * 73, g72s, One * 72,
                    reglu(ph73g, gt1_73), One * 74,
                    reglu(ph73g, One - gt1_73), One * 10,
                    g74d, One * 75, g75r, One * 10, g75a, One * 10,
                    g75s, One * 75, One * 71)

    A_comp = sel(
        ph3s, _select(done_s, A_sdone, A_s),
        ph3c, sel(done_row,
                  sel(mul_done, A_c2, pow_rdone, A_c3, A_c1),
                  One - done_row, A_c0, A_c1),
        ph4g, sel(div_done, A_4d, sub_setup, A_4s, A_4n),
        ph5g, sel(done5, A_5d, A_5n),
        ph6g, sel(done6, A_6d, A_6n),
        ph10g, sel(done10, sel(is_bzero10, A_10z, A_10g), A_10n),
        ph13g, sel(done13, A_13d, A_13n),
        g21, A_21, g22d, A_22d, g22n, A_22, g23d, A_23d, g23n, A_23,
        g24d, A_24d, g24n, A_24, g25x, A_25x, g25b, A_25b, g25n, A_25,
        g31z, A_31z, g31d, A_31d, g31n, A_31, g32z, A_32z, g32d, A_32d,
        g32n, A_32, g33z, A_33z, g33d, A_33d, g33n, A_33,
        wp6g_all, A6,
        wp6s_all, A6s,
        ph76g, A76,
        SA)
    B_comp = sel(
        ph3s, _select(done_s, Zero, B_s),
        ph3c, sel(done_row,
                  sel(mul_done, Zero, pow_rdone, Zero,
                      row_cont, Zero, Zero),
                  B_c0),
        ph4g, sel(div_done, Zero, sub_setup, Zero, B_4n),
        ph5g, sel(done5, Zero, B_5n),
        ph6g, sel(done6, Zero, B_6n),
        ph10g, sel(done10, Zero, B_10n),
        ph13g, sel(done13, Zero, B_13n),
        g21, B_21, g22d, B_22d, g22n, B_22, g23d, B_23d, g23n, B_23,
        g24d, B_24d, g24n, B_24, g25x, B_25x, g25b, B_25b, g25n, B_25,
        g31z, B_31z, g31d, B_31d, g31n, B_31, g32z, B_32z, g32d, B_32d,
        g32n, B_32, g33z, B_33z, g33d, B_33d, g33n, B_33,
        wp6g_all, B6,
        wp6s_all, B6s,
        ph71g, Zero, ph72g, _select(done72, Zero, SB + One), ph73g, Zero,
        ph74g, _select(done74, Zero, SB + One),
        ph75g, _select(done75, Zero, SB + One), ph76g, B76,
        Zero)
    C_comp = sel(
        ph3s, Zero,
        ph3c, sel(done_row,
                  sel(mul_done, Zero, pow_rdone, Zero, C_c1),
                  C_c0),
        ph4g, sel(div_done, Zero, sub_setup, C_4s, SC),
        ph5g, sel(done5, C_5d, SC),
        ph6g, sel(done6, C_6d, SC),
        ph10g, sel(done10, sel(is_bzero10, Zero, C_10g), C_10n),
        ph13g, sel(done13, C_13d, Zero),
        g21, C_21, g22d, C_22d, g22n, C_22, g23d, C_23d, g23n, C_23,
        g24d, C_24d, g24n, C_24, g25x, C_25x, g25b, C_25b, g25n, C_25,
        g31z, C_31z, g31d, C_31d, g31n, C_31, g32z, C_32z, g32d, C_32d,
        g32n, C_32, g33z, C_33z, g33d, C_33d, g33n, C_33,
        wp6g_all, SC,
        wp6s_all, SC,
        ph71g, Zero, ph72g, Zero, ph73g, _select(gt1_73, SF, Zero), ph74g, SC,
        ph75g, _select(done75, Zero, SC), ph76g, Zero,
        Zero)
    D_comp = sel(
        ph3s, _select(done_s, _select(scan_go, c2, caller_c), D_s),
        ph3c, sel(done_row,
                  sel(mul_done, D_c2c, pow_rdone, D_c3c, D_c1c),
                  D_c0),
        ph4g, sel(div_done, ncV2, sub_setup, D_4s, D_4n),
        ph5g, sel(done5, D_5d, D_5n),
        ph6g, sel(done6, D_6d, D_6n),
        ph10g, sel(done10, sel(is_bzero10, D_10z, D_10g), D_10n),
        ph13g, sel(done13, D_13d, D_13n),
        g21, D_21, g22d, D_22d, g22n, D_22, g23d, D_23d, g23n, D_23,
        g24d, D_24d, g24n, D_24, g25x, D_25x, g25b, D_25b, g25n, D_25,
        g31z, D_31z, g31d, D_31d, g31n, D_31, g32z, D_32z, g32d, D_32d,
        g32n, D_32, g33z, D_33z, g33d, D_33d, g33n, D_33,
        wp6g_all, D6,
        wp6s_all, D6s,
        ph71g, c1, ph72g, _select(done72, c1, SD), ph73g, c1,
        ph74g, _select(done74, c2, SD), ph75g, _select(done75, c1, SD), ph76g, D76,
        Zero)
    E_comp = sel(
        ph3s, _select(done_s, Zero, E_s),
        ph3c, sel(done_row,
                  sel(mul_done, Zero, pow_rdone, E_c3,
                      row_cont, Zero, Zero),
                  E_c0),
        ph4g, sel(div_done, Zero, sub_setup, E_4s, E_4n),
        ph5g, sel(done5, E_5d, E_5n),
        ph6g, sel(done6, E_6d, E_6n),
        ph10g, sel(done10, Zero, E_10n),
        ph13g, sel(done13, E_13d, E_13n),
        g21, E_21, g22d, E_22d, g22n, E_22, g23d, E_23d, g23n, E_23,
        g24d, E_24d, g24n, E_24, g25x, E_25x, g25b, E_25b, g25n, E_25,
        g31z, E_31z, g31d, E_31d, g31n, E_31, g32z, E_32z, g32d, E_32d,
        g32n, E_32, g33z, E_33z, g33d, E_33d, g33n, E_33,
        wp6g_all, E6,
        wp6s_all, E6s,
        ph71g, Zero, ph72g, _select(done72, Zero, dec72), ph73g, Zero,
        ph74g, _select(done74, Zero, car74),
        ph75g, _select(done75, Zero, dec75),
        ph76g, _select(done76, Zero, E76),
        Zero)
    F_comp = sel(
        ph3s, _select(done_s, Zero, F_s),
        ph3c, sel(done_row,
                  sel(mul_done, Zero, pow_rdone, F_c3, F_c1),
                  F_c0),
        ph4g, sel(div_done, Zero, sub_setup, F_4s, F_4n),
        ph5g, sel(done5, F_5d, F_5n),
        ph6g, sel(done6, F_6d, F_6n),
        ph10g, sel(done10, sel(is_bzero10, F_10z, F_10g), F_10n),
        ph13g, sel(done13, F_13d, F_13n),
        g21, F_21, g22d, F_22d, g22n, F_22, g23d, F_23d, g23n, F_23,
        g24d, F_24d, g24n, F_24, g25x, F_25x, g25b, F_25b, g25n, F_25,
        g31z, F_31z, g31d, F_31d, g31n, F_31, g32z, F_32z, g32d, F_32d,
        g32n, F_32, g33z, F_33z, g33d, F_33d, g33n, F_33,
        wp6g_all, F6,
        wp6s_all, F6s,
        ph71g, SF, ph72g, SF, ph73g, _select(gt1_73, c2, SF), ph74g, c2,
        ph75g, _select(done75, SC, SF), ph76g, F76,
        Zero)

    # compute emission flags/payloads
    em_litdig_c = (reglu(ph3s, addfam + borrowfam)
                   - reglu(ph3s, reglu(done_s, reglu(borrowfam, underflow)))
                   + reglu(ph3c, One)
                   + reglu(ph5g, One) + reglu(ph6g, One)
                   + ph22g + ph23g + ph24g + ph25g + ph32g + ph33g + wp6g_dig
                   + wp6s_dig + ph74g
                   + reglu(ph13g, One - reglu(done13, neg13)))
    dig_V0_c = sel(ph44g, q44, ph45g, q45, ph47g, q44, ph49g, q45,
                   ph52g, s52, ph53g, s53, ph57g, q57,
                   ph64g, q64, ph68g, q68,
                   ph74g, dig74,
                   ph22g, q22, ph23g, q23, ph24g, q24, ph25g, q25,
                   ph32g, q32, ph33g, dig33,
                   _select(ph3s, _select(reglu(done_s, underflow), Zero, dig_out),
               _select(ph3c, dig_cell,
               _select(ph5g, dig5,
               _select(ph6g, dig6,
               _select(ph13g, dig13, Zero))))))
    em_frame_c = (reglu(ph4g, sub_setup) + reglu(ph5g, done5)
                  + reglu(ph6g, done6) + reglu(ph10g, pow_go)
                  + reglu(ph3c, pow_rdone) + reglu(ph13g, done13)
                  + wp6_frame + wp6g_frame + wp6s_frame
                  + scan_go + wp6p_frame)
    frame_V1_c = frV1
    frame_E2_c = _select(wp6g_frame, frame6_E2,
                   _select(wp6s_frame, frame6s_E2,
                   _select(ph73g + ph74g + ph75g, frame_p_E2,
                   sel(g21, frE2, g22d, frE2, g23d, SF, g24d, frE2, g25b, frE2,
                       g31d, frE2, g32d, SF, g33d, frE2, One))))
    frame_F2_c = _select(wp6g_frame, frame6_F2,
                   _select(wp6s_frame, frame6s_F2,
                   _select(ph73g + ph74g + ph75g, frame_p_F2,
                   sel(g21, frF2, g22d, frF2, g23d, frF2, g24d, SF, g25b, frF2,
                       g31d, frF2, g32d, frF2, g33d, SF, One))))
    frame_V2_c = _select(wp6_frame + wp6g_frame + wp6s_frame, frV2,
                _select(scan_go, sel(reglu(ph3s, done_s), caller_c, ncV2),
                _select(wp6p_all + ph76g, frV2,
                _select(reglu(ph4g, sub_setup), frV2,
                _select(reglu(ph5g, done5), SF,
                _select(reglu(ph6g, done6), xF,
                _select(reglu(ph10g, pow_go), SF,
                _select(reglu(ph3c, pow_rdone), SF,
                        xF))))))))
    frame_X_c = _select(wp6g_frame, frame6_X,
                    _select(wp6s_frame, frame6s_X,
                    sel(g21, One * 22, g22d, One * 23, g23d, One * 24,
                    g24d, One * 25, g25b, One * 21, g31d, One * 32,
                    g32d, One * 33, g33d, One * 32,
                    _select(scan_go, One * 76,
                    _select(wp6p_all, frame_p_X,
                    _select(ph76g, One * 76,
                _select(reglu(ph4g, sub_setup), One * 5,
                _select(reglu(ph5g, done5), One * 6,
                _select(reglu(ph6g, done6), One * 4,
                _select(reglu(ph10g, pow_go), One * 3,
                _select(reglu(ph3c, pow_rdone), One * 13,
                        One * 10)))))))))))
    em_lithead_c = (reglu(ph4g, sub_setup) + reglu(ph5g, done5)
                    + reglu(ph10g, pow_go)
                    + reglu(ph3c, reglu(done_row, row_cont + pow_rdone))
                    + reglu(ph3s, reglu(done_s, reglu(borrowfam, underflow)))
                    + reglu(ph13g, b13u) + wp6_head + wp6g_head + wp6s_head
                    + reglu(ph73g, gt1_73))
    head_V0_c = _select(wp6g_head, head6_V0,
                    _select(wp6s_head, head6s_V0,
                    _select(reglu(ph73g, gt1_73), head_p_V0,
                    sel(g21, L226, g22d, n_p6 + One, g23d, n_a6, g24d, n_b6,
                    g31d, n_a6s, g32d, n_s6, g33d, n_a6s,
                    _select(reglu(ph4g, sub_setup), head4_V0,
                _select(reglu(ph5g, done5), head5_V0,
                _select(reglu(ph10g, pow_go), head10_V0,
                _select(reglu(ph3c, reglu(done_row, row_cont + pow_rdone)),
                _select(pow_rdone, n2, head_row_V0),
                        Zero))))))))
    head_V2_c = _select(reglu(ph3c, reglu(done_row, row_cont)), i1, Zero)
    head_X_c = _select(reglu(ph4g, sub_setup), SF,
               _select(reglu(ph5g, done5), frV2,
               _select(reglu(ph10g, pow_go), frV2,
               _select(reglu(ph3c, reglu(done_row, row_cont + pow_rdone)), xF,
                       Zero))))
    em_const_c = reglu(ph3s, reglu(done_s, opg9 + opg10))

    # ── P6.5 iota rhs build loop (NAT(OP_REC) frame, X=2) ───────────────────
    # 15 steps (B = step counter) emit rhs = s pred (Nat.rec m z s pred)
    # under the link chain e4 (BVar 0=pred, 1=s, 2=z, 3=m). base = frE2 =
    # first emitted token = c1+2 (the frame token sits at c1 and the driver
    # appends a STATE token (K=33) after EVERY step, so the rec_dn step's
    # STATE occupies c1+1). Steps 2,3 emit link+link2 (3 tokens incl. STATE),
    # all other steps emit raw+STATE (2 tokens):
    # 0: CONST(pred)@b  1: APP(pred,maj)@b+2 = pred  2: e1@b+4, e2@b+5
    # 3: e3@b+7, e4@b+8  4..7: BVAR 0..3@b+10..b+16  8: CONST(rec)@b+18
    # 9..12: APP rec m z s pred@b+20..b+26 = r4@b+26  13: APP(s,pred)@b+28
    # = a1  14: APP(a1,r4)@b+30 = rhs → done (A=b+30, B=e4=b+8). pred =
    # `Nat.pred <maj>` (2 tokens): the pred nat-op computes chain(v-1)
    # lazily inside the next iota round — no digit loop here.
    rec_bdone = reglu(is_build, _eq_expr(SB, One * 14))
    em_raw_rec = reglu(is_build, One - _eq_expr(SB, One * 2)
                       - _eq_expr(SB, One * 3))
    raw_K_rec = sel(
        _eq_expr(SB, Zero), Expression({_one_dim: K_CONST}),
        _geq_expr(SB, One * 4) - _geq_expr(SB, One * 8),
        Expression({_one_dim: K_BVAR}),
        _eq_expr(SB, One * 8), Expression({_one_dim: K_CONST}),
        Expression({_one_dim: K_APP}))
    raw_V0_rec = sel(
        _eq_expr(SB, Zero), _PRED_CID,
        _eq_expr(SB, One), frE2,
        _geq_expr(SB, One * 4) - _geq_expr(SB, One * 8), SB - One * 4,
        _eq_expr(SB, One * 8), _REC_CID,
        _eq_expr(SB, One * 9), frE2 + One * 18,
        _eq_expr(SB, One * 10), frE2 + One * 20,
        _eq_expr(SB, One * 11), frE2 + One * 22,
        _eq_expr(SB, One * 12), frE2 + One * 24,
        _eq_expr(SB, One * 13), frE2 + One * 12,
        _eq_expr(SB, One * 14), frE2 + One * 28,
        Zero)
    raw_V1_rec = sel(
        _eq_expr(SB, One), rmajV0,
        _eq_expr(SB, One * 9), frE2 + One * 16,
        _eq_expr(SB, One * 10), frE2 + One * 14,
        _eq_expr(SB, One * 11), frE2 + One * 12,
        _eq_expr(SB, One * 12), frE2 + One * 10,
        _eq_expr(SB, One * 13), frE2 + One * 10,
        _eq_expr(SB, One * 14), frE2 + One * 26,
        Zero)
    em_link_rec = reglu(is_build, _eq_expr(SB, One * 2) + _eq_expr(SB, One * 3))
    em_link2_rec = em_link_rec
    # link1: e1 (SB2) / e3 (SB3); link2: e2 (SB2) / e4 (SB3)
    link1_V0_rec = _select(_eq_expr(SB, One * 2), rmV0, rsV0)
    link1_E_rec = _select(_eq_expr(SB, One * 2), rmX, rsX)
    link1_P_rec = _select(_eq_expr(SB, One * 2), Zero, frE2 + One * 5)
    link1_D_rec = _select(_eq_expr(SB, One * 2), Zero, One * 2)
    link2_V0_rec = _select(_eq_expr(SB, One * 2), rzV0, frE2 + One * 2)
    link2_E_rec = _select(_eq_expr(SB, One * 2), rzX, rmajX)
    link2_P_rec = _select(_eq_expr(SB, One * 2), frE2 + One * 4, frE2 + One * 7)
    link2_D_rec = _select(_eq_expr(SB, One * 2), One, One * 3)
    A_build = _select(rec_bdone, frE2 + One * 30, SA)
    B_build = _select(rec_bdone, frE2 + One * 8, SB + One)
    C_build = SC
    D_build = _select(rec_bdone, frV2, SD)
    E_build = Zero
    F_build = SF

    # ── P7.5b casesOn succ-rule build loop (3 raw steps, base b = frE2) ──────
    # 0: CONST(pred)@b  1: APP(pred,maj)@b+2 = pred  2: APP(succ,pred)@b+4 =
    # rhs → done (A=b+4, B=succ minor env). pred = `Nat.pred <maj>` (2 tokens):
    # the pred nat-op computes chain(v-1) lazily inside the next round. The
    # succ minor (1 arg, no recursive call) is applied to pred; extras stay on
    # the pend (C=SC) and are applied to the rhs by the machine.
    cs_bdone = reglu(is_cs_build, _eq_expr(SB, One * 3))
    em_raw_cs = reglu(is_cs_build, One - cs_bdone)
    raw_K_cs = sel(
        _eq_expr(SB, Zero), Expression({_one_dim: K_CONST}),
        Expression({_one_dim: K_APP}))
    raw_V0_cs = sel(
        _eq_expr(SB, Zero), _PRED_CID,
        _eq_expr(SB, One), frE2,
        _eq_expr(SB, One * 2), rsuccV0_c,
        Zero)
    raw_V1_cs = sel(
        _eq_expr(SB, One), SA,
        _eq_expr(SB, One * 2), frE2 + One * 2,
        Zero)
    A_cs_build = _select(cs_bdone, frE2 + One * 4, SA)
    B_cs_build = _select(cs_bdone, rsuccX_c, SB + One)
    C_cs_build = SC
    D_cs_build = _select(cs_bdone, frV2, SD)
    E_cs_build = Zero
    F_cs_build = SF

    # ── P7.5b-3 P2.casesOn build loop (2 raw steps, base b = frE2) ───────────
    # UNREACHABLE (see is_cs_build_p2): the flat rhs `APP(alt,a)`/`APP(_,b)`
    # reifies the fields without their captured envs — beta then binds them
    # under the alt env (link_env=pX), which is wrong for fields carrying
    # loose bvars (brecOn witnesses `P2.mk (f ..) proof`). Direct delivery in
    # p2_succ_r hands the machine the field pend entries (C = SC) instead.
    p2_bdone = reglu(is_cs_build_p2, _eq_expr(SB, One * 2))
    em_raw_p2 = reglu(is_cs_build_p2, One - p2_bdone)
    raw_K_p2 = Expression({_one_dim: K_APP})
    raw_V0_p2 = sel(
        _eq_expr(SB, Zero), p2_altV0,
        _eq_expr(SB, One), frE2,
        Zero)
    raw_V1_p2 = sel(
        _eq_expr(SB, Zero), p2_a,
        _eq_expr(SB, One), p2_b,
        Zero)
    A_p2_build = _select(p2_bdone, frE2 + One * 2, SA)
    B_p2_build = _select(p2_bdone, p2_altX, SB + One)
    C_p2_build = SC
    D_p2_build = _select(p2_bdone, frV2, SD)
    E_p2_build = Zero
    F_p2_build = SF

    # ── frame slot payloads ──────────────────────────────────────────────────
    # slot 1 emitters: walk_more / bvar / fire2 / fire1 / d12 / d23 / dn1 /
    # compute frame pushes
    frame_V1 = _select(proj_setup, SA,
              _select(walk_more, fV2,
              _select(em_frame_bvar, SB,
              _select(fire2, qV0,
              _select(fire1, eX,
              _select(d12, v_done,
              _select(d23_work, nbV1,
              _select(dn1, frV1,
              _select(fire_rec, Expression({_one_dim: OP_REC}),
              _select(build_r, Expression({_one_dim: OP_REC}),
              _select(fire_caseson, Expression({_one_dim: OP_CASESON}),
              _select(cs_succ_r, Expression({_one_dim: OP_CASESON}),
              _select(fire_p2, Expression({_one_dim: OP_CASESON_P2}),
              _select(p2_succ_r, Expression({_one_dim: OP_CASESON_P2}),
              _select(fire_bool, Expression({_one_dim: OP_CASESON_BOOL}),
              _select(em_frame_c, frame_V1_c,
                      frV1))))))))))))))))
    frame_V2 = _select(proj_setup, SD,
              _select(walk_more, frV2,
              _select(em_frame_bvar, SD,
              _select(fire2, c2,
              _select(fire1, SD,
              _select(d12, c2,
              _select(d23_work, SD,
              _select(dn1, frV2,
              _select(fire_rec, SD,
              _select(build_r, frV2,
              _select(fire_caseson, SD,
              _select(cs_succ_r, frV2,
              _select(fire_p2, SD,
              _select(p2_succ_r, frV2,
              _select(fire_bool, SD,
              _select(em_frame_c, frame_V2_c,
                      frV2))))))))))))))))
    frame_X = _select(proj_setup, SB,
              _select(walk_more, frX - One,
              _select(em_frame_bvar, fV0,
              _select(fire2, qX,
              _select(fire1, One,
              _select(d12, e_done,
              _select(d23_work, _select(is_pow_d, One * 71,
                                _select(is_divmod_d, One * 4,
                                _select(is_bitop_d, One * 21,
                                _select(is_shr_d, One * 31,
                                _select(is_shl_d, One * 61,
                                _select(is_gcd_d, One * 41, One * 3)))))),
              _select(dn1, One * 3,
              _select(fire_rec, One,
              _select(build_r, One * 2,
              _select(fire_caseson, One,
              _select(cs_succ_r, One * 2,
              _select(fire_p2, One,
              _select(p2_succ_r, One * 2,
              _select(fire_bool, One,
              _select(em_frame_c, frame_X_c,
                      One * 3))))))))))))))))
    frame_task = _select(walk_more + em_frame_bvar, Expression({_one_dim: TASK_WALK}),
                _select(fire2 + d12 + proj_setup, Expression({_one_dim: TASK_ST}),
                        Expression({_one_dim: TASK_NAT})))
    # slot 2 emitters: fire2 / d12 (always a NAT control frame); proj_setup
    # pushes a WHNF(child) frame here instead
    frame2_task = _select(proj_setup, Expression({_one_dim: TASK_WHNF}),
                         Expression({_one_dim: TASK_NAT}))
    frame2_V1 = _select(proj_setup, fX, _select(fire2, eX, nbV1))
    frame2_V2 = _select(proj_setup, c1, _select(fire2, SD, nbV2))
    frame2_X = _select(proj_setup, SB, _select(fire2, One, One * 2))

    # ══ Phase 5 M2: INFER / DEFEQ task frames (VM_SPEC §8, §10) ════════════
    # The ref_vm recursion becomes a frame protocol. Sub-calls push
    # [ST(continuation), TASK-frame]; a finished sub-task sets E=1 with the
    # result in (A,B); TASK frames are popped one per step; ST frames with
    # F2 = continuation id dispatch the CONT tree (E=1) or a loop resume
    # tree (E=0). WHNF sub-tasks reuse the main mode above a WHNF control
    # frame (E2=1 = soft: nat-op/overflow failures deliver the ORIGINAL
    # closure instead of rejecting — kernel _soft_whnf).
    # (continuation-id constants live at module scope, above build_step_graph)

    # extra derefs for the M2 branches
    tK = fetch_by_position([k_], frV1)[0]      # DEFEQ t side (frame V1)
    tV0 = _fv0(frV1)
    tV1 = fetch_by_position([v1_], frV1)[0]
    tXf = fetch_by_position([x_], frV1)[0]
    tE2f = fetch_by_position([e2_], frV1)[0]
    sK = fetch_by_position([k_], frE2)[0]      # DEFEQ s side (frame E2)
    sV0 = _fv0(frE2)
    sV1 = fetch_by_position([v1_], frE2)[0]
    sXf = fetch_by_position([x_], frE2)[0]
    sE2f = fetch_by_position([e2_], frE2)[0]
    oV1, oX, oE2, oF2 = fetch_by_position([v1_, x_, e2_, f2_], frX)
    oV0 = _fv0(oV1)
    oK = fetch_by_position([k_], oV1)[0]       # orig t token kind
    oBd = fetch_by_position([v1_], oV1)[0]     # orig t body / level root
    oBdE = fetch_by_position([e2_], oV1)[0]    # orig t T_PI_CLO body env
    sBd = fetch_by_position([v1_], oE2)[0]     # orig s body
    sBdE = fetch_by_position([e2_], oE2)[0]
    sDom = _fv0(oE2)
    ooV1, ooX = fetch_by_position([v1_, x_], frV2)   # orig t pos / env
    ooE2, ooF2 = fetch_by_position([e2_, f2_], frV2)  # orig s pos / env
    ooK = fetch_by_position([k_], nbV1)[0]     # nt kind (D_SW3)
    sk3 = fetch_by_position([k_], SA)[0]       # ns kind (D_SW3)
    paV0, paV2, paX = fetch_by_position([v0_, v2_, x_], frE2)  # infer args
    sfV0 = _fv0(SF)     # s-pend arg (spine peel)
    sfV2 = fetch_by_position([v2_], SF)[0]
    sfX = fetch_by_position([x_], SF)[0]
    dqV0 = fetch_by_position([v1_], frV2)[0]          # orig t pos
    dqE2 = fetch_by_position([e2_], frV2)[0]          # orig s pos
    tidx = _fv0(dqV0)   # BVar indices
    sidx = _fv0(dqE2)
    # ── Phase 5 M3: proj-reduction peel (I_PROJ continuation reads the
    # whnf'd child in SA; the proj token sits at frV1, its idx in V1). The
    # child must be a fully applied 2-field P2.mk spine App(App(Const(18),a),b)
    # — the only non-rec structure in the toy env (TOY_STRUCTS). field =
    # idx==0 ? a (inner/fst) : b (outer/snd); else the proj re-sticks.
    pr_cK = fetch_by_position([k_], SA)[0]            # child whnf kind
    pr_oV0 = _fv0(SA)         # inner App pos
    pr_oV1 = fetch_by_position([v1_], SA)[0]         # outer arg (snd)
    pr_iK = fetch_by_position([k_], pr_oV0)[0]
    pr_iV0 = _fv0(pr_oV0)     # ctor pos
    pr_iV1 = fetch_by_position([v1_], pr_oV0)[0]     # inner arg (fst)
    pr_mK = fetch_by_position([k_], pr_iV0)[0]
    pr_mCid = _fv0(pr_iV0)
    pr_idx = fetch_by_position([v1_], frV1)[0]       # proj token V1 (field idx)
    pr_sname = fetch_by_position([v0_], frV1)[0]     # proj token V0 (sname nid)
    # Metadata-driven structure match: the child's head is a constructor of a
    # non-recursive inductive with nfields==2, and its inductive NAME (nid)
    # equals the projection's own sname. No hardcoded P2/P2.mk cid.
    pr_full = reglu(reglu(reglu(
                _kind_eq_raw(pr_cK, K_APP, One),
                _kind_eq_raw(pr_iK, K_APP, One)),
                _kind_eq_raw(pr_mK, K_CONST, One)),
                reglu(_is_struct_ctor2(pr_mCid),
                      _eq_expr(_struct_nid(pr_mCid), pr_sname)))
    def _value_eq_n(n, d0):
        """1 if a lit chain with n digits, digit0 = d0, has value 0."""
        return _eq_expr(n, Zero) + reglu(_eq_expr(n, One),
                                         One - _geq_expr(d0, One))

    def ldepth(head):
        """LINK V1 depth for a new link onto chain `head` (0 for NULL)."""
        return _select(_geq_expr(head, One),
                       fetch_by_position([v1_], head)[0] + One, Zero)

    # continuation-id gates
    def gid(n):
        return _kind_eq_raw(frF2, n, One)

    g = {n: gid(n) for n in range(1, 70)}
    # CONT-tree gates must be mode-gated: frF2 on non-ST frames (e.g. the
    # DEFEQ frame's F2 = s_env) can collide with a continuation id.
    cg = {n: reglu(g[n], cont_mode) for n in g}
    # which branch emits links / raw / frames (payload selection keys)
    m2_link = (g[I_LAMSORT] + g[I_PIL1] + g[I_LETD] + g[I_CHK]
               + g[D_BIND2] + g[D_XPI2])
    m2_link = reglu(st2_mode + is_defeq_frame, m2_link)

    # ── CONT tree (E=1, D=ST with F2 = continuation id) ─────────────────────
    # Each branch: A/B = delivered result unless stated; "sN" pushes.
    # Defaults keep the state (used by passthrough-free branches).
    # shared: dom env of a pi-shaped f_type stored at ST (K_PI: f_type env;
    # T_PI_CLO: token X); body env likewise from E2.
    dom_env = _select(_kind_eq_raw(tK, K_PI, One), frX, tXf)
    body_env = _select(_kind_eq_raw(tK, K_PI, One), frX, tE2f)

    A_c = SA
    B_c = SB
    C_c = SC
    D_c = SD
    E_c = SE
    F_c = SF
    fr1_task, fr1_V1, fr1_V2, fr1_X, fr1_E2, fr1_F2 = \
        Expression({_one_dim: TASK_ST}), Zero, frV2, Zero, Zero, frF2
    fr2_task, fr2_V1, fr2_V2, fr2_X, fr2_E2, fr2_F2 = \
        Expression({_one_dim: TASK_WHNF}), SA, SB, Zero, Zero, Zero
    em_link1_c = Zero
    em_link2_c = Zero
    link1_V0, link1_D, link1_P, link1_E, link1_F = Zero, Zero, Zero, Zero, Zero
    link2_V0, link2_D, link2_P, link2_E, link2_F = Zero, Zero, Zero, Zero, Zero
    link1_F2, link2_F2 = Zero, Zero            # M3 binder identity (bid)
    em_raw_c = Zero
    raw_K_c, raw_V0_c, raw_V1_c, raw_V2_c, raw_X_c, raw_E2_c = \
        Zero, Zero, Zero, Zero, Zero, Zero
    rej_c, rej_code_c = Zero, Zero

    # I_FN: f_type in (A,B); stash the arg chain (old ST.E2), ensure_pi
    # via a WHNF sub-task.
    A_c = _select(cg[I_FN], SA, A_c)
    B_c = _select(cg[I_FN], SB, B_c)
    C_c = _select(cg[I_FN], Zero, C_c)
    F_c = _select(cg[I_FN], Zero, F_c)
    E_c = _select(cg[I_FN], Zero, E_c)
    fr1_V1 = _select(cg[I_FN], Zero, fr1_V1)
    fr1_X = _select(cg[I_FN], Zero, fr1_X)
    fr1_E2 = _select(cg[I_FN], frE2, fr1_E2)
    fr1_F2 = _select(cg[I_FN], Expression({_one_dim: I_PI}), fr1_F2)
    fr2_V2 = _select(cg[I_FN], c1, fr2_V2)
    D_c = _select(cg[I_FN], c2, D_c)
    # soft-infer cascade: the fn's type infer failed (A=0 marker landed on
    # this ST) → hand the marker to this infer's own consumer (task.V2).
    i_fn_fail = reglu(cg[I_FN], One - _geq_expr(SA, One))
    A_c = _select(i_fn_fail, Zero, A_c)
    B_c = _select(i_fn_fail, Zero, B_c)
    C_c = _select(i_fn_fail, Zero, C_c)
    F_c = _select(i_fn_fail, Zero, F_c)
    E_c = _select(i_fn_fail, One, E_c)
    D_c = _select(i_fn_fail, fetch_by_position([v2_], frV2)[0], D_c)

    # I_PI: whnf'd f_type in (A,B); peel the pi (dom pair), take arg1 off
    # the chain (ST.E2) and infer it.
    pi_dom = (tV0, dom_env)
    A_c = _select(cg[I_PI], paV0, A_c)
    B_c = _select(cg[I_PI], paX, B_c)
    C_c = _select(cg[I_PI], Zero, C_c)
    F_c = _select(cg[I_PI], Zero, F_c)
    E_c = _select(cg[I_PI], Zero, E_c)
    fr1_V1 = _select(cg[I_PI], SA, fr1_V1)      # f_type pos (old A)
    fr1_X = _select(cg[I_PI], SB, fr1_X)        # f_type env (old B)
    fr1_E2 = _select(cg[I_PI], frE2, fr1_E2)    # args chain
    # soft chains peel to I_ARG_S (kernel infer_only spine: no arg-vs-domain
    # DEFEQ, K/type_checker.cpp:189-205); hard chains keep I_ARG (:174-188).
    fr1_F2 = _select(cg[I_PI],
                     _select(soft_flag, Expression({_one_dim: I_ARG_S}),
                             Expression({_one_dim: I_ARG})), fr1_F2)
    fr2_task = _select(cg[I_PI], Expression({_one_dim: TASK_INFER}), fr2_task)
    fr2_V2 = _select(cg[I_PI], c1, fr2_V2)
    fr2_E2 = _select(cg[I_PI], One, fr2_E2)
    # inherit the soft-infer flag from the task frame (walk STs: V2 = task)
    fr2_F2 = _select(cg[I_PI], soft_flag, fr2_F2)
    D_c = _select(cg[I_PI], c2, D_c)
    # Soft I_PI (kernel infer_only spine, K/type_checker.cpp:189-205): the
    # arg is neither inferred nor domain-checked — it is linked into the
    # codomain env and the spine walks straight to the next Pi body (WHNF
    # sub-task).  The I_ARG_S resume (below the I_CHK block) continues the
    # peel and delivers the whnf'd focus when the args chain runs out.
    # Emission = link(c1) + ST(c2) + WHNF(c3), D=c3 — the I_CHK success shape
    # (only the WHNF target differs: the focus's body, since the ST's V1 is
    # 0 on the first soft I_PI step).  A non-Pi whnf'd f_type is the kernel
    # "function expected" throw -> soft decline (i_pi_soft channel below).
    pi_soft = reglu(cg[I_PI], soft_flag)
    # ensure_pi for the soft spine reads the FOCUS (sk3 = the whnf'd f_type
    # kind), not the ST's V1 (0 on the first soft I_PI step).
    pi_pi_k = _kind_eq_raw(sk3, K_PI, One) + _kind_eq_raw(sk3, T_PI_CLO, One)
    i_pi_bad_pi = reglu(pi_soft, One - pi_pi_k)
    pi_walk = reglu(pi_soft, pi_pi_k)
    pi_bodyP = fetch_by_position([v1_], SA)[0]           # focus f_type body
    pi_bodyE = _select(_kind_eq_raw(sk3, K_PI, One), SB,
                       fetch_by_position([e2_], SA)[0])  # focus f_type body env
    A_c = _select(pi_walk, pi_bodyP, A_c)
    B_c = _select(pi_walk, c1, B_c)
    link1_V0 = _select(pi_walk, paV0, link1_V0)
    link1_D = _select(pi_walk, ldepth(pi_bodyE), link1_D)
    link1_P = _select(pi_walk, pi_bodyE, link1_P)
    link1_E = _select(pi_walk, paX, link1_E)
    link1_F = _select(pi_walk, Zero, link1_F)
    # (em_link1_c for pi_walk is added at the I_CHK block below — that block
    # REASSIGNS em_link1_c and would wipe an earlier +=.)
    fr1_X = _select(pi_walk, c1, fr1_X)                  # codomain env = link
    fr1_E2 = _select(pi_walk, paV2, fr1_E2)              # args chain after arg1
    fr2_task = _select(pi_walk, Expression({_one_dim: TASK_WHNF}), fr2_task)
    fr2_V2 = _select(pi_walk, c2, fr2_V2)                # WHNF delivers to ST@c2
    fr2_E2 = _select(pi_walk, Zero, fr2_E2)              # hard whnf (ensure_pi)
    fr2_F2 = _select(pi_walk, Zero, fr2_F2)
    D_c = _select(pi_walk, c3, D_c)

    # I_ARG: arg type in (A,B); re-derive the domain from ST's f_type and
    # check it (kernel infer_app is_def_eq(arg_type, domain)).
    A_c = _select(cg[I_ARG], SA, A_c)
    B_c = _select(cg[I_ARG], SB, B_c)
    fr1_V1 = _select(cg[I_ARG], frV1, fr1_V1)
    fr1_X = _select(cg[I_ARG], frX, fr1_X)
    fr1_E2 = _select(cg[I_ARG], frE2, fr1_E2)
    fr1_F2 = _select(cg[I_ARG], Expression({_one_dim: I_CHK}), fr1_F2)
    fr2_task = _select(cg[I_ARG], Expression({_one_dim: TASK_DEFEQ}), fr2_task)
    fr2_V1 = _select(cg[I_ARG], SA, fr2_V1)     # t = arg type
    fr2_X = _select(cg[I_ARG], SB, fr2_X)
    fr2_E2 = _select(cg[I_ARG], tV0, fr2_E2)    # s = domain pos
    fr2_F2 = _select(cg[I_ARG], dom_env, fr2_F2)
    fr2_V2 = _select(cg[I_ARG], c1, fr2_V2)
    E_c = _select(cg[I_ARG], Zero, E_c)
    D_c = _select(cg[I_ARG], c2, D_c)
    # soft-infer cascade: the arg's type infer failed (A=0 marker).  Shared
    # with I_ARG_S (the soft arm reuses this fail channel unchanged).
    i_arg_fail = reglu(cg[I_ARG] + cg[I_ARG_S], One - _geq_expr(SA, One))
    A_c = _select(i_arg_fail, Zero, A_c)
    B_c = _select(i_arg_fail, Zero, B_c)
    C_c = _select(i_arg_fail, Zero, C_c)
    F_c = _select(i_arg_fail, Zero, F_c)
    E_c = _select(i_arg_fail, One, E_c)
    D_c = _select(i_arg_fail, fetch_by_position([v2_], frV2)[0], D_c)
    # ensure_pi gate (kernel type_checker::ensure_pi_core → "function
    # expected"): frV1 holds the whnf'd f_type, and the ref's _pi_parts
    # raises ERR_TYPE unless its kind is K_PI/T_PI_CLO. Without this gate a
    # stuck non-Pi f_type (e.g. CONST Nat) makes tV0 a garbage domain (the
    # const's cid) and the launched DEFEQ(arg_type, cid) pair never
    # terminates. Soft (task F2=1): deliver the A=0 marker to the task's
    # consumer — ref _proof_irrel catches the raise inside its try scope.
    i_pi_bad = reglu(cg[I_ARG] + cg[I_ARG_S], One - _kind_eq_raw(tK, K_PI, One)
                     - _kind_eq_raw(tK, T_PI_CLO, One))
    # Soft-spine failures: the I_PI ensure_pi (i_pi_bad_pi) and the I_ARG_S
    # resume's non-Pi focus with args left (kernel "function expected" throw)
    # decline through the shared soft channel (A=0 marker to task.V2).
    i_args_notpi = reglu(cg[I_ARG_S],
                         reglu(_geq_expr(frE2, One), One - pi_pi_k))
    i_pi_soft = reglu(i_pi_bad + i_pi_bad_pi, soft_flag) + i_args_notpi
    A_c = _select(i_pi_soft, Zero, A_c)
    B_c = _select(i_pi_soft, Zero, B_c)
    C_c = _select(i_pi_soft, Zero, C_c)
    F_c = _select(i_pi_soft, Zero, F_c)
    E_c = _select(i_pi_soft, One, E_c)
    D_c = _select(i_pi_soft, fetch_by_position([v2_], frV2)[0], D_c)

    # I_CHK: verdict in A. False → reject (ERR_TYPE) — UNLESS the enclosing
    # TASK_INFER is soft (F2=1: a proof-irrel-chain launch; ref _proof_irrel
    # catches ERR_TYPE/ERR_UNSUPPORTED from the t-side infers → None → the
    # stuck chain declines to its next step). Soft fail: deliver the failure
    # marker A=0 to the task's awaiting consumer (task.V2) instead; walk STs
    # carry V2 = the task frame, so frV2 = task frame and task.V2 = v2_(frV2).
    i_chk_fail = reglu(cg[I_CHK], One - _geq_expr(SA, One))
    i_soft = soft_flag
    i_soft_fail = reglu(i_chk_fail, _geq_expr(i_soft, One))
    rej_c = reglu(i_chk_fail, One - _geq_expr(i_soft, One))
    rej_code_c = reglu(i_chk_fail, One - _geq_expr(i_soft, One))
    # Success path (hard chains only): link the just-checked arg and peel
    # the next Pi.  The soft infer_only spine never reaches I_CHK — it walks
    # through pi_soft / I_ARG_S (above / below).
    i_more = _geq_expr(paV2, One)
    chk_ok = cg[I_CHK]
    link1_V0 = _select(chk_ok, paV0, link1_V0)
    link1_D = _select(chk_ok, ldepth(body_env), link1_D)
    link1_P = _select(chk_ok, body_env, link1_P)
    link1_E = _select(chk_ok, paX, link1_E)
    link1_F = _select(chk_ok, Zero, link1_F)
    em_link1_c = chk_ok + pi_walk   # pi_walk: soft spine's arg link (this is
                                    # the only spot after the pi_soft block)
    A_c = _select(chk_ok, tV1, A_c)          # body pos
    B_c = _select(chk_ok, c1, B_c)           # new f_type env = link
    C_c = _select(chk_ok, Zero, C_c)
    F_c = _select(chk_ok, Zero, F_c)
    fr1_V1 = _select(chk_ok, tV1, fr1_V1)
    fr1_X = _select(chk_ok, c1, fr1_X)
    fr1_E2 = _select(chk_ok, _select(i_more, paV2, Zero), fr1_E2)
    fr1_F2 = _select(chk_ok, Expression({_one_dim: I_PI}), fr1_F2)
    fr2_V2 = _select(chk_ok, c2, fr2_V2)
    E_c = _select(chk_ok, _select(i_more, Zero, One), E_c)
    D_c = _select(chk_ok, _select(i_more, c3, frV2), D_c)
    # soft-infer fail delivery (overrides the success payload above): the
    # A=0 marker pops the whole infer to its consumer; consumer conts turn
    # it into a cascade (or, at PI_TY, the proof-irrel ST_SP decline).
    A_c = _select(i_soft_fail, Zero, A_c)
    B_c = _select(i_soft_fail, Zero, B_c)
    C_c = _select(i_soft_fail, Zero, C_c)
    F_c = _select(i_soft_fail, Zero, F_c)
    E_c = _select(i_soft_fail, One, E_c)
    D_c = _select(i_soft_fail, fetch_by_position([v2_], frV2)[0], D_c)
    # ensure_pi hard part (i_pi_bad, defined in the I_ARG block above):
    # ERR_TYPE reject. Accumulated here because the I_CHK assignment of
    # rej_c above reassigns (not accumulates) and would wipe an earlier
    # contribution.
    rej_c = rej_c + reglu(i_pi_bad, One - i_pi_soft)
    rej_code_c = rej_code_c + reglu(i_pi_bad, One - i_pi_soft)

    # I_ARG_S resume (soft spine; the WHNF'd codomain-so-far landed in
    # (A,B)): args left + Pi focus -> link the NEXT arg (ST.E2 chain HEAD,
    # paV0) onto the FOCUS's body env (pi_bodyE — tV1 would lag one Pi level
    # behind here, since ST.V1 still holds the previous pi) and WHNF the next
    # body — the same emission shape as pi_soft.  Chain EMPTY (frE2=0, not
    # paV2=0 — the head arg must be consumed first) -> the kernel infer_only
    # result IS the whnf'd focus: deliver (A,B) as-is to the soft infer's
    # consumer.  A non-Pi focus with args left declined via i_args_notpi.
    args_more = _geq_expr(frE2, One)
    args_walk = reglu(cg[I_ARG_S], reglu(args_more, pi_pi_k))
    args_done = reglu(cg[I_ARG_S], One - args_more)
    C_c = _select(args_walk, Zero, C_c)
    F_c = _select(args_walk, Zero, F_c)
    E_c = _select(args_walk, Zero, E_c)
    A_c = _select(args_walk, pi_bodyP, A_c)
    B_c = _select(args_walk, c1, B_c)
    link1_V0 = _select(args_walk, paV0, link1_V0)
    link1_D = _select(args_walk, ldepth(pi_bodyE), link1_D)
    link1_P = _select(args_walk, pi_bodyE, link1_P)
    link1_E = _select(args_walk, paX, link1_E)
    link1_F = _select(args_walk, Zero, link1_F)
    em_link1_c = em_link1_c + args_walk
    fr1_V1 = _select(args_walk, SA, fr1_V1)
    fr1_X = _select(args_walk, c1, fr1_X)
    fr1_E2 = _select(args_walk, paV2, fr1_E2)
    fr1_F2 = _select(args_walk, Expression({_one_dim: I_ARG_S}), fr1_F2)
    fr2_task = _select(args_walk, Expression({_one_dim: TASK_WHNF}), fr2_task)
    fr2_V2 = _select(args_walk, c2, fr2_V2)
    fr2_E2 = _select(args_walk, Zero, fr2_E2)
    fr2_F2 = _select(args_walk, Zero, fr2_F2)
    D_c = _select(args_walk, c3, D_c)
    C_c = _select(args_done, Zero, C_c)
    F_c = _select(args_done, Zero, F_c)
    E_c = _select(args_done, One, E_c)
    D_c = _select(args_done, frV2, D_c)

    # I_LAMDOM: domain type in (A,B); ensure_sort via WHNF.
    fr1_V1 = _select(cg[I_LAMDOM], frV1, fr1_V1)
    fr1_X = _select(cg[I_LAMDOM], frX, fr1_X)
    fr1_E2 = _select(cg[I_LAMDOM], frE2, fr1_E2)
    fr1_F2 = _select(cg[I_LAMDOM], Expression({_one_dim: I_LAMSORT}), fr1_F2)
    fr2_V2 = _select(cg[I_LAMDOM], c1, fr2_V2)
    C_c = _select(cg[I_LAMDOM], Zero, C_c)
    F_c = _select(cg[I_LAMDOM], Zero, F_c)
    E_c = _select(cg[I_LAMDOM], Zero, E_c)
    D_c = _select(cg[I_LAMDOM], c2, D_c)
    # soft-infer cascade: the lam domain's type infer failed (A=0 marker).
    i_ldom_fail = reglu(cg[I_LAMDOM], One - _geq_expr(SA, One))
    A_c = _select(i_ldom_fail, Zero, A_c)
    B_c = _select(i_ldom_fail, Zero, B_c)
    C_c = _select(i_ldom_fail, Zero, C_c)
    F_c = _select(i_ldom_fail, Zero, F_c)
    E_c = _select(i_ldom_fail, One, E_c)
    D_c = _select(i_ldom_fail, fetch_by_position([v2_], frV2)[0], D_c)

    # I_LAMSORT: whnf'd domain in (A,B) must be a sort; push the binder
    # marker link and infer the body under it.
    i_ls_bad = reglu(cg[I_LAMSORT], One - _kind_eq_raw(fK, K_SORT, One))
    rej_c = rej_c + reglu(i_ls_bad, One)
    rej_code_c = rej_code_c + reglu(i_ls_bad, One)
    link1_V0 = _select(cg[I_LAMSORT], frV1, link1_V0)
    link1_D = _select(cg[I_LAMSORT], ldepth(frX), link1_D)
    link1_P = _select(cg[I_LAMSORT], frX, link1_P)
    link1_E = _select(cg[I_LAMSORT], frX, link1_E)
    link1_F = _select(cg[I_LAMSORT], One, link1_F)
    # Binder identity: the marker link carries a non-zero bid. D_XPI2 adopts
    # it so a T_PI_CLO's binder and the K_PI side's fresh binder compare as
    # the SAME binder in D_BV3 (kernel is_def_eq_binding pushes one fvar per
    # side, but alpha-equal bodies must resolve their bvars to one identity).
    # bid=0 would read as "distinct" (D_BV3 requires bid>=1), sending an
    # alpha-equal body pair to the stuck chain. The graph descends the two
    # binders in lockstep, so a single shared non-zero bid is enough; de Bruijn
    # depth is carried by the bvar index, which D_BV2 still compares.
    link1_F2 = _select(cg[I_LAMSORT], c1, link1_F2)
    em_link1_c = em_link1_c + cg[I_LAMSORT]
    fr1_V1 = _select(cg[I_LAMSORT], frV1, fr1_V1)
    fr1_X = _select(cg[I_LAMSORT], frX, fr1_X)
    fr1_E2 = _select(cg[I_LAMSORT], frE2, fr1_E2)
    fr1_F2 = _select(cg[I_LAMSORT], Expression({_one_dim: I_LAMBODY}), fr1_F2)
    fr2_task = _select(cg[I_LAMSORT], Expression({_one_dim: TASK_INFER}),
                       fr2_task)
    fr2_V2 = _select(cg[I_LAMSORT], c2, fr2_V2)
    fr2_E2 = _select(cg[I_LAMSORT], One, fr2_E2)
    fr2_F2 = _select(cg[I_LAMSORT], soft_flag, fr2_F2)
    A_c = _select(cg[I_LAMSORT], frE2, A_c)     # body pos
    B_c = _select(cg[I_LAMSORT], c1, B_c)       # marker env
    C_c = _select(cg[I_LAMSORT], Zero, C_c)
    F_c = _select(cg[I_LAMSORT], Zero, F_c)
    E_c = _select(cg[I_LAMSORT], Zero, E_c)
    D_c = _select(cg[I_LAMSORT], c3, D_c)

    # I_LAMBODY: body type in (A,B); emit T_PI_CLO(lam dom, body type).
    # A=0 = the body infer failed soft → cascade the marker (no T_PI_CLO).
    i_lb_fail = reglu(cg[I_LAMBODY], One - _geq_expr(SA, One))
    em_raw_c = _select(i_lb_fail, Zero, cg[I_LAMBODY])
    raw_K_c = _select(cg[I_LAMBODY], Expression({_one_dim: T_PI_CLO}), raw_K_c)
    raw_V0_c = _select(cg[I_LAMBODY], frV1, raw_V0_c)
    raw_V1_c = _select(cg[I_LAMBODY], SA, raw_V1_c)
    raw_X_c = _select(cg[I_LAMBODY], frX, raw_X_c)
    raw_E2_c = _select(cg[I_LAMBODY], SB, raw_E2_c)
    A_c = _select(cg[I_LAMBODY], c1, A_c)
    B_c = _select(cg[I_LAMBODY], Zero, B_c)
    E_c = _select(cg[I_LAMBODY], One, E_c)
    D_c = _select(cg[I_LAMBODY], frV2, D_c)
    A_c = _select(i_lb_fail, Zero, A_c)
    B_c = _select(i_lb_fail, Zero, B_c)
    C_c = _select(i_lb_fail, Zero, C_c)
    F_c = _select(i_lb_fail, Zero, F_c)
    D_c = _select(i_lb_fail, fetch_by_position([v2_], frV2)[0], D_c)

    # I_PIDOM: domain type in (A,B); ensure_sort.
    fr1_V1 = _select(cg[I_PIDOM], frV1, fr1_V1)
    fr1_X = _select(cg[I_PIDOM], frX, fr1_X)
    fr1_E2 = _select(cg[I_PIDOM], frE2, fr1_E2)
    fr1_F2 = _select(cg[I_PIDOM], Expression({_one_dim: I_PIS1}), fr1_F2)
    fr2_V2 = _select(cg[I_PIDOM], c1, fr2_V2)
    C_c = _select(cg[I_PIDOM], Zero, C_c)
    F_c = _select(cg[I_PIDOM], Zero, F_c)
    E_c = _select(cg[I_PIDOM], Zero, E_c)
    D_c = _select(cg[I_PIDOM], c2, D_c)
    # soft-infer cascade: the pi domain's type infer failed (A=0 marker).
    i_pid_fail = reglu(cg[I_PIDOM], One - _geq_expr(SA, One))
    A_c = _select(i_pid_fail, Zero, A_c)
    B_c = _select(i_pid_fail, Zero, B_c)
    C_c = _select(i_pid_fail, Zero, C_c)
    F_c = _select(i_pid_fail, Zero, F_c)
    E_c = _select(i_pid_fail, One, E_c)
    D_c = _select(i_pid_fail, fetch_by_position([v2_], frV2)[0], D_c)

    # I_PIS1: whnf'd domain must be a sort; scan its level tree (LEVEL).
    i_p1_bad = reglu(cg[I_PIS1], One - _kind_eq_raw(fK, K_SORT, One))
    rej_c = rej_c + reglu(i_p1_bad, One)
    rej_code_c = rej_code_c + reglu(i_p1_bad, One)
    fr1_V1 = _select(cg[I_PIS1], frV1, fr1_V1)
    fr1_X = _select(cg[I_PIS1], frX, fr1_X)
    fr1_E2 = _select(cg[I_PIS1], frE2, fr1_E2)
    fr1_F2 = _select(cg[I_PIS1], Expression({_one_dim: I_PIL1}), fr1_F2)
    fr2_task = _select(cg[I_PIS1], Expression({_one_dim: TASK_LEVEL}), fr2_task)
    fr2_V2 = _select(cg[I_PIS1], c1, fr2_V2)
    fr2_X = _select(cg[I_PIS1], Zero, fr2_X)
    A_c = _select(cg[I_PIS1], fV0, A_c)         # level root
    B_c = _select(cg[I_PIS1], Zero, B_c)
    E_c = _select(cg[I_PIS1], Zero, E_c)
    D_c = _select(cg[I_PIS1], c2, D_c)

    # I_PIL1: l1 in A; push the pi marker and infer the body under it.
    link1_V0 = _select(cg[I_PIL1], frV1, link1_V0)
    link1_D = _select(cg[I_PIL1], ldepth(frX), link1_D)
    link1_P = _select(cg[I_PIL1], frX, link1_P)
    link1_E = _select(cg[I_PIL1], frX, link1_E)
    link1_F = _select(cg[I_PIL1], One, link1_F)
    em_link1_c = em_link1_c + cg[I_PIL1]
    fr1_V1 = _select(cg[I_PIL1], SA, fr1_V1)    # l1
    fr1_F2 = _select(cg[I_PIL1], Expression({_one_dim: I_PIS2}), fr1_F2)
    fr2_task = _select(cg[I_PIL1], Expression({_one_dim: TASK_INFER}), fr2_task)
    fr2_V2 = _select(cg[I_PIL1], c2, fr2_V2)
    fr2_E2 = _select(cg[I_PIL1], One, fr2_E2)
    A_c = _select(cg[I_PIL1], frE2, A_c)        # body pos
    B_c = _select(cg[I_PIL1], c1, B_c)
    C_c = _select(cg[I_PIL1], Zero, C_c)
    F_c = _select(cg[I_PIL1], Zero, F_c)
    E_c = _select(cg[I_PIL1], Zero, E_c)
    D_c = _select(cg[I_PIL1], c3, D_c)

    # I_PIS2: body type in (A,B) is a Sort token or a fresh level chain;
    # extract the level root and scan it (l2 = ST.E2-bound LEVEL result).
    # A=0 = the body infer failed soft → cascade the marker (suppress the
    # malformed-sort reject).
    i_p2s_fail = reglu(cg[I_PIS2], One - _geq_expr(SA, One))
    lvl2_root = _select(_kind_eq_raw(fK, K_SORT, One), fV0, SA)
    i_p2_bad = reglu(cg[I_PIS2], One - _kind_eq_raw(fK, K_SORT, One)
                     - _eq_expr(fK, One)
                     - _eq_expr(fK, One * 2))
    i_p2_bad = reglu(i_p2_bad, One - i_p2s_fail)
    rej_c = rej_c + reglu(i_p2_bad, One)
    rej_code_c = rej_code_c + reglu(i_p2_bad, One)
    fr1_V1 = _select(cg[I_PIS2], frV1, fr1_V1)     # keep l1
    fr1_F2 = _select(cg[I_PIS2], Expression({_one_dim: I_PIL2}), fr1_F2)
    fr2_task = _select(cg[I_PIS2], Expression({_one_dim: TASK_LEVEL}), fr2_task)
    fr2_V2 = _select(cg[I_PIS2], c1, fr2_V2)
    fr2_X = _select(cg[I_PIS2], Zero, fr2_X)
    A_c = _select(cg[I_PIS2], lvl2_root, A_c)      # level root
    B_c = _select(cg[I_PIS2], Zero, B_c)
    C_c = _select(cg[I_PIS2], Zero, C_c)
    F_c = _select(cg[I_PIS2], Zero, F_c)
    E_c = _select(cg[I_PIS2], Zero, E_c)
    D_c = _select(cg[I_PIS2], c2, D_c)
    A_c = _select(i_p2s_fail, Zero, A_c)
    B_c = _select(i_p2s_fail, Zero, B_c)
    F_c = _select(i_p2s_fail, Zero, F_c)
    E_c = _select(i_p2s_fail, One, E_c)
    D_c = _select(i_p2s_fail, fetch_by_position([v2_], frV2)[0], D_c)

    # I_PIL2: l2 in A, l1 in ST.V1; imax, then emit Sort(level) chain.
    # kernel mk_imax (K/level.cpp:112-123): is_not_zero(l2) → mk_max(l1,l2);
    # is_zero(l2) → 0 (so `imax u 0 = 0` for ANY u, including explicit u>=1);
    # is_zero(l1)||is_one(l1) → l2; l1==l2 → l1.  On the explicit-int channel
    # is_not_zero(l2)⟺l2>=1 and mk_max is plain max, so the fold is:
    #   l2==0 → 0;  l2>=1 and l1==0 → l2;  l2>=1 and l1>=1 → max(l1,l2).
    # (The old `if l1>=1 then max else l2` gave imax 1 0 = 1, wrong.)
    imax_l = _select(_geq_expr(frV1, SA), frV1, SA)
    lvl_out = _select(_geq_expr(SA, One),
                      _select(_geq_expr(frV1, One), imax_l, SA), Zero)
    em_raw_c = em_raw_c + cg[I_PIL2]
    raw_K_c = _select(cg[I_PIL2], Expression({_one_dim: KL_ZERO}), raw_K_c)
    fr1_task = _select(cg[I_PIL2], Expression({_one_dim: TASK_INFER}), fr1_task)
    fr1_V1 = _select(cg[I_PIL2], lvl_out, fr1_V1)
    fr1_V2 = _select(cg[I_PIL2], frV2, fr1_V2)
    fr1_E2 = _select(cg[I_PIL2], One * 2, fr1_E2)
    # P_EMIT task: F2 = inherited soft flag (NOT the default frF2 cont id)
    fr1_F2 = _select(cg[I_PIL2], soft_flag, fr1_F2)
    A_c = _select(cg[I_PIL2], Zero, A_c)
    B_c = _select(cg[I_PIL2], c1, B_c)          # KL_ZERO pos
    C_c = _select(cg[I_PIL2], Zero, C_c)
    F_c = _select(cg[I_PIL2], Zero, F_c)
    E_c = _select(cg[I_PIL2], Zero, E_c)
    D_c = _select(cg[I_PIL2], c2, D_c)

    # I_SORTEM: emit Sort(mk_succ(level)) over the ORIGINAL symbolic level root.
    # kernel infer_sort (K/type_checker.cpp:345-348): `check_level(sort_level)`
    # when checking, then `r = mk_sort(mk_succ(sort_level(e)))`.  mk_succ
    # (K/level.cpp:78-80) is a RAW constructor: a Param/Max/IMax level is
    # wrapped, never decoded to an explicit integer.  ST.V1 holds the Sort
    # token; its V0 is the level root.  The graph emits one KL_SUCC node over
    # that root, then the P_EMIT phase emits K_SORT over the succ node; the
    # LEVEL int scan is no longer on this path.  (Explicit succ^k(Zero) roots
    # still yield succ^(k+1)(Zero), the same chain as before.)
    sort_root = fetch_by_position([v0_], frV1)[0]
    em_raw_c = em_raw_c + cg[I_SORTEM]
    raw_K_c = _select(cg[I_SORTEM], Expression({_one_dim: KL_SUCC}), raw_K_c)
    raw_V0_c = _select(cg[I_SORTEM], sort_root, raw_V0_c)
    fr1_task = _select(cg[I_SORTEM], Expression({_one_dim: TASK_INFER}),
                       fr1_task)
    fr1_V1 = _select(cg[I_SORTEM], Zero, fr1_V1)   # no further succs to emit
    fr1_V2 = _select(cg[I_SORTEM], frV2, fr1_V2)
    fr1_E2 = _select(cg[I_SORTEM], One * 2, fr1_E2)
    # P_EMIT task: F2 = inherited soft flag (NOT the default frF2 cont id)
    fr1_F2 = _select(cg[I_SORTEM], soft_flag, fr1_F2)
    A_c = _select(cg[I_SORTEM], Zero, A_c)
    B_c = _select(cg[I_SORTEM], c1, B_c)
    C_c = _select(cg[I_SORTEM], Zero, C_c)
    F_c = _select(cg[I_SORTEM], Zero, F_c)
    E_c = _select(cg[I_SORTEM], Zero, E_c)
    D_c = _select(cg[I_SORTEM], c2, D_c)

    # I_LETV: value type in (A,B); defeq against the declared type.
    fr1_V1 = _select(cg[I_LETV], frV1, fr1_V1)
    fr1_X = _select(cg[I_LETV], frX, fr1_X)
    fr1_E2 = _select(cg[I_LETV], frE2, fr1_E2)       # keep the LET token pos
    fr1_F2 = _select(cg[I_LETV], Expression({_one_dim: I_LETD}), fr1_F2)
    fr2_task = _select(cg[I_LETV], Expression({_one_dim: TASK_DEFEQ}), fr2_task)
    fr2_V1 = _select(cg[I_LETV], SA, fr2_V1)
    fr2_X = _select(cg[I_LETV], SB, fr2_X)
    fr2_E2 = _select(cg[I_LETV], frV1, fr2_E2)
    fr2_F2 = _select(cg[I_LETV], frX, fr2_F2)
    fr2_V2 = _select(cg[I_LETV], c1, fr2_V2)
    C_c = _select(cg[I_LETV], Zero, C_c)
    F_c = _select(cg[I_LETV], Zero, F_c)
    E_c = _select(cg[I_LETV], Zero, E_c)
    D_c = _select(cg[I_LETV], c2, D_c)
    # soft-infer cascade: the let value's type infer failed (A=0 marker).
    i_lv_fail = reglu(cg[I_LETV], One - _geq_expr(SA, One))
    A_c = _select(i_lv_fail, Zero, A_c)
    B_c = _select(i_lv_fail, Zero, B_c)
    C_c = _select(i_lv_fail, Zero, C_c)
    F_c = _select(i_lv_fail, Zero, F_c)
    E_c = _select(i_lv_fail, One, E_c)
    D_c = _select(i_lv_fail, fetch_by_position([v2_], frV2)[0], D_c)

    # I_LETD: verdict in A; marker on the declared type, infer the body.
    # ST.E2 carries the LET token pos (stored at the let_i dispatch) so the
    # body pos (LET.X) survives the two intermediate frames.
    i_ld_fail = reglu(cg[I_LETD], One - _geq_expr(SA, One))
    rej_c = rej_c + reglu(i_ld_fail, One)
    rej_code_c = rej_code_c + reglu(i_ld_fail, One)
    let_body = fetch_by_position([x_], frE2)[0]
    link1_V0 = _select(cg[I_LETD], frV1, link1_V0)
    link1_D = _select(cg[I_LETD], ldepth(frX), link1_D)
    link1_P = _select(cg[I_LETD], frX, link1_P)
    link1_E = _select(cg[I_LETD], frX, link1_E)
    link1_F = _select(cg[I_LETD], One, link1_F)
    em_link1_c = em_link1_c + cg[I_LETD]
    fr2_task = _select(cg[I_LETD], Expression({_one_dim: TASK_INFER}), fr2_task)
    fr2_V1 = _select(cg[I_LETD], let_body, fr2_V1)   # LET body
    fr2_X = _select(cg[I_LETD], c1, fr2_X)           # marker env
    fr2_V2 = _select(cg[I_LETD], frV2, fr2_V2)
    fr2_E2 = _select(cg[I_LETD], One, fr2_E2)
    fr2_F2 = _select(cg[I_LETD], soft_flag, fr2_F2)
    A_c = _select(cg[I_LETD], let_body, A_c)         # body
    B_c = _select(cg[I_LETD], c1, B_c)
    C_c = _select(cg[I_LETD], Zero, C_c)
    F_c = _select(cg[I_LETD], Zero, F_c)
    E_c = _select(cg[I_LETD], Zero, E_c)
    D_c = _select(cg[I_LETD], c3, D_c)               # focus = the INFER frame

    # ── symbolic level equality circuit (WP2b D3; sound subset of D4) ───────
    # Structural comparison of two level roots.  kernel operator==
    # (K/level.cpp:125-150): kind mismatch → false; Zero → true; Param/MVar →
    # level_id (nid) equality; Succ → recurse V0.  is_def_eq(level,level)
    # (K/type_checker.cpp:814-820) is is_equivalent (D4 = `l == r || normalize l
    # == normalize r`, K/level.cpp:518-521).  Two graph-side limitations, both
    # SOUND (never accept a false equality, so no unsound accept):
    #   1. D5 normalize (max-arg sorting via is_norm_lt,
    #      K/level.cpp:395-418,454-516) is not reproduced: levels equivalent
    #      only up to max/imax normalization compare unequal → rejected.
    #   2. Max/IMax are NOT structurally recursed: their two children would
    #      make the unrolled circuit branch (2^depth lookups evaluated every
    #      micro-step, which blows up the per-step cost); Max/IMax level pairs
    #      therefore compare unequal unless they are the same closure.  The
    #      graph's checked corpora levels are the unary Zero/Param/Succ chain
    #      (Type u, Type 0/1, Prop), which this handles exactly.
    # Depth/chain caps make deeper trees compare unequal (sound, incomplete).
    LVL_DEPTH = 8
    LVL_CHAIN_DEPTH = 8

    def _lvl_eq(l, r, depth):
        if depth <= 0:
            return Zero
        # Identical closure ⇒ defeq (kernel level is_def_eq is deep
        # structural: lhs == rhs || normalize(lhs) == normalize(rhs),
        # K/level.cpp:517-520).  Levels carry no bvars, so the same env slot
        # IS the same level term.  Without this, a KL_MAX/KL_IMAX node loses
        # even against itself (recursing into both children would double the
        # unrolled circuit per depth — the sound-incomplete note below), so
        # deq_const never fired on max(1,1)-levelled consts: the d6 head pair
        # Nat.rec@{max(1,1)} =?= itself fell into the soft-whnf/proof-irrel
        # ladder, its False unwound into the DE_PRJ re-dispatch and d6/d7
        # stopped halting (005 F13-01/F13-02).
        pos_eq = _eq_expr(l, r)
        lk = fetch_by_position([k_], l)[0]
        rk = fetch_by_position([k_], r)[0]
        same = _eq_expr(lk, rk)
        lv0 = fetch_by_position([v0_], l)[0]
        rv0 = fetch_by_position([v0_], r)[0]
        res = pos_eq + reglu(One - pos_eq,
                             reglu(same, _eq_expr(lk, One * KL_ZERO)))
        res = res + reglu(One - pos_eq,
                          reglu(reglu(same, _eq_expr(lk, One * KL_PARAM)
                                                + _eq_expr(lk, One * KL_MVAR)),
                                _eq_expr(lv0, rv0)))
        res = res + reglu(One - pos_eq,
                          reglu(reglu(same, _eq_expr(lk, One * KL_SUCC)),
                                _lvl_eq(lv0, rv0, depth - 1)))
        return res

    def _lvl_chain_eq(a, b, depth):
        """Const level-arg sibling chains (X-linked, 0 = end) pairwise equal."""
        if depth <= 0:
            return Zero
        a_end = _eq_expr(a, Zero)
        b_end = _eq_expr(b, Zero)
        a_nx = fetch_by_position([x_], a)[0]
        b_nx = fetch_by_position([x_], b)[0]
        step = reglu(One - a_end, reglu(One - b_end,
                       reglu(_lvl_eq(a, b, LVL_DEPTH),
                             _lvl_chain_eq(a_nx, b_nx, depth - 1))))
        return reglu(a_end, b_end) + step

    # ── card 014 P1: is_def_eq positive cache (ADR 017; K/type_checker.cpp) ──
    # Kernel contract: the is_def_eq WRAPPER caches SUCCESS of every True
    # completion (:1247-1252 cache_success :972 on the ENTRY pair, `if (r)`
    # — False never writes).  The query runs at is_def_eq_core entry inside
    # quick_is_def_eq (:834-836): cheap structural check t == s first (the
    # graph's deq_same), positive cache second (the arm here).  Storage: a
    # completed pair is re-emitted on the raw slot as a T_DEFCACHE token,
    # V0 = t_pos (attention key), V1 = t_env, V2 = s_pos, X = s_env
    # (E2 = F2 = 0).  Lookup: exact-match attention over V0 —
    # score = 2q·v0 − v0² − BIG·clear + α·invlog, the square being ONE
    # ReGLU per position (reglu(v0, v0) = v0·ReLU(v0), v0 ≥ 0).  clear
    # restricts candidates to the cache kind; tie-break = latest.  With no
    # entry yet every position is cleared, all cleared scores round to the
    # same −BIG (ulp(1e20) ≫ v0² ≤ 4096² ≈ 2^24), the argmax takes the
    # first position (T_NULL, V0 = n_consts < any term position), and the
    # 4-field verify fails: no sentinel token, empty cache is a deterministic
    # miss.  A shadowed/colliding winner also fails the verify → plain
    # fallthrough = current behavior.  Verdict-safe by construction: the
    # winner can only pass the verify when it IS a T_DEFCACHE entry with the
    # exact (t,s) pair, i.e. a pair the machine already completed True
    # (ADR 017 red line: the cache removes steps, never changes a verdict).
    _v0e = Expression({v0_: 1})
    _v1e = Expression({v1_: 1})
    _v2e = Expression({v2_: 1})
    _xe = Expression({x_: 1})
    _e2e = Expression({e2_: 1})
    _ke = Expression({k_: 1})
    if VM014_CACHE or VM014_WMEMO:
        _v0sq = reglu(_v0e, _v0e)

    def _fetch_by_v0sq(cache_kind, nfields=4):
        """Latest T_<cache_kind> token with V0 == the current frame's V1
        (the DEFEQ t position / the WHNF focus position).  Returns the
        matched token's KIND first, then the stored payload:
        (kind, v0, v1, v2, x[, e2]).

        The kind fetch is the card 014/M6 fix, not decoration: when no
        entry matches, EVERY position is cleared and the −BIG term
        swallows the key term (ulp(1e20) ≫ 2^24), so all positions tie
        and tie_break=latest lands on the NEWEST stream token — the head
        STATE token (kind 33), whose fields (A,B,C,D,E) pass the P2
        field-triple check tautologically on an entry-shape beat
        (SA==frV1 ∧ SB==frX ∧ SC==0 ∧ frame flag==0): the empty cache
        "replayed" (frame pos, ret) as the memo value and livelocked the
        CHECK corpus (010-M M6-02/M6-03, b_inc reject@5 with zero
        entries).  A miss must be STRUCTURALLY current behavior, so the
        hit gate verifies the matched token IS an entry of this arm's
        kind.  This also closes P1's latent same-family hole (its
        4-field check only survived by the C==s_pos / D==s_env mismatch).
        """
        one = Expression({_one_dim: 1})
        # collapse the clear expression into ONE persisted dim before the
        # BIG multiply — multi-term × BIG cancels the key signal (alm_p2:77-86)
        ck = persist(One - _kind_eq_raw(_ke, cache_kind, One))
        fields = [_ke, _v0e, _v1e, _v2e, _xe] + ([_e2e] if nfields == 5 else [])
        lu = LookUp(fields,
                    [Expression({frV1: 2}), one],
                    [_v0e, -_v0sq - ck * BIG
                            + Expression({_inv_log_pos_dim: LATEST_ALPHA})],
                    tie_break="latest")
        _all_lookups.append(lu)
        for d in lu.dims:
            if d not in _all_dims:
                _all_dims.append(d)
        return tuple(lu.dims[:nfields + 1])

    if VM014_CACHE:
        ckind, cv0, cv1, cv2, cvx = _fetch_by_v0sq(T_DEFCACHE)
        # M6: the matched token must actually BE a T_DEFCACHE entry —
        # kind check first (see _fetch_by_v0sq docstring for the
        # empty-cache STATE-token false-hit this closes).
        defeq_cache = reglu(is_defeq_frame,
                            reglu(reglu(reglu(_eq_expr(
                                          ckind,
                                          Expression({_one_dim: T_DEFCACHE})),
                                      _eq_expr(cv0, frV1)),
                                  _eq_expr(cv1, frX)),
                            reglu(_eq_expr(cv2, frE2),
                                  _eq_expr(cvx, frF2))))
    else:
        defeq_cache = Zero

    # ── card 014 P2: whnf memo (kernel m_whnf: query at whnf(e) entry
    # :753-757, insert only AFTER the loop completes :763/:766/:772 —
    # "完成才可查" by write-beat-after, mirroring the kernel ordering).
    # A T_WHNFCACHE entry stores the frame input triple (focus pos, env
    # root, soft flag = frame V1/X/E2, the same triple as the P2 recon
    # probe, /home/xkq/logs/014/whnf_result.json) and the delivered
    # closure (result pos, result env).  The hit replays the delivery:
    # commit shape = whnf_deliver (A=V1-field, B=E2-field, C=SC, D=frV2,
    # E=1, F=SF).  Entry-shape gate (SA==frV1 ∧ SB==frX ∧ ¬ret_pending):
    # a whnf frame's input closure is live in the focus only at ITS FIRST
    # dispatch beat — the memo answers a fresh call (kernel: whnf(e)
    # checks m_whnf on entry, not mid-loop); mid-computation beats miss
    # by design.  A hit that would coincide with a legitimate reject/halt
    # beat is impossible in principle (the entry witnesses a COMPLETED run
    # of the same input) but masked defensively at the halt/reject merge.
    # Miss = current behavior (verdict-safe, ADR 017 red line).
    if VM014_WMEMO:
        wvkind, wv0, wv1, wv2, wvx, wve = _fetch_by_v0sq(T_WHNFCACHE,
                                                         nfields=5)
        # CLEAN-CHAIN entry shape: the replayed delivery carries C=SC and
        # F=SF, so the hit is ONLY sound when the frame owns no live spine
        # chain (launcher set C=0/F=0 — the D_SW2 / de_prj_f / de_att_f
        # soft-whnf launch shape).  A mid-args-walk pop-back beat (the
        # ensure_pi/I_ARG/ul_w launches) re-satisfies SA==frV1 ∧ SB==frX
        # with C≠0; replaying an entry whose C grew during ITS run then
        # hands the caller a stale spine root — the first WMEMO build
        # livelocked d6 exactly there (010-M M4-03② first-run evidence:
        # the trajectory re-keyed (2154,3197,1)→(2154,3091,1) and dups
        # never went to 0 at 720).  Requiring C==0 on the hit keeps
        # caller-visible state identical ONLY for entries whose real run
        # also exited clean — the exit commit preserves C, and the writer
        # was never gated on it until M6(b): the write arm now demands
        # SC==0 ∧ SF==0 at the delivering beat too (see _wc_w), so
        # C@entry == C@exit == 0 holds BY CONSTRUCTION for every
        # memoized computation.  Spine-case completions (chain grew) are
        # simply not memoized — safe misses.
        # M6: the matched token must BE a T_WHNFCACHE entry.  Without this
        # the empty/fully-cleared cache argmax (all scores tie at −BIG,
        # tie_break=latest) lands on the head STATE token of the current
        # beat, whose (v0,v1,v2)=(A,B,C)=(SA,SB,SC) passes the 3-field
        # check tautologically under the entry-shape gates — the CHECK /
        # string / mutation / olean corpora then "replayed" (frame pos,
        # ret-flag) as the whnf value and rejected early (010-M M6-03).
        whnf_cache0 = reglu(is_whnf_frame,
                       reglu(One - ret_pending,
                       reglu(_eq_expr(wvkind,
                                      Expression({_one_dim: T_WHNFCACHE})),
                       reglu(reglu(reglu(_eq_expr(SA, frV1),
                                         _eq_expr(SB, frX)),
                                   _eq_expr(SC, Zero)),
                             reglu(_eq_expr(SF, Zero),
                             reglu(reglu(_eq_expr(wv0, frV1),
                                         _eq_expr(wv1, frX)),
                                   _eq_expr(wv2, frE2)))))))
    else:
        whnf_cache0 = Zero

    # ── DEFEQ dispatch (task frame; pair in V1/X, E2/F2) ────────────────────
    # every dispatch gate is mode-gated: these expressions read frame/term
    # fields that are meaningless outside the DEFEQ frame mode
    # card 014: a cache hit closes every dispatch arm (the kernel's
    # quick_is_def_eq returns True before the core machinery, :836/:1173);
    # the hit itself commits below in deq_same's shape.  Switch-OFF must
    # byte-reproduce the baseline graph: no mask select, no extra dims.
    if VM014_CACHE:
        deq_gate = reglu(is_defeq_frame, One - defeq_cache)
    else:
        deq_gate = is_defeq_frame
    deq_same = reglu(reglu(_eq_expr(frV1, frE2), _eq_expr(frX, frF2)), deq_gate)
    deq_const = reglu(reglu(reglu(reglu(_kind_eq_raw(tK, K_CONST, One),
                                       _kind_eq_raw(sK, K_CONST, One)),
                                  _eq_expr(tV0, sV0)),
                            _lvl_chain_eq(tV1, sV1, LVL_CHAIN_DEPTH)), deq_gate)
    deq_sort = reglu(reglu(_kind_eq_raw(tK, K_SORT, One),
                           _kind_eq_raw(sK, K_SORT, One)), deq_gate)
    deq_lit = reglu(reglu(reglu(_kind_eq_raw(tK, K_LIT, One),
                                _kind_eq_raw(sK, K_LIT, One)),
                          reglu(_eq_expr(tV1, Zero), _eq_expr(sV1, Zero))),
                    deq_gate)
    # ── WP5-E3: STRING literal pairs (K_LIT.V1 == 1) ────────────────────────
    # Kernel: two string literals are equal iff their byte sequences are
    # (nat_lit/string_lit are decided by the app-spine machinery; the kernel
    # never pads a literal).  The graph's D_LITL loop pads the shorter chain
    # with 0 up to max(n1,n2) — safe for canonical decimal digit chains
    # (leading zeros only), WRONG for byte chains ("ab" vs "ab\0").  So the
    # length is decided FIRST: differing V0 (byte counts) → verdict False
    # immediately; equal V0 → launch the same kind-agnostic stride-2 D_LITL
    # compare, every read in-range.
    deq_lit_str = reglu(reglu(reglu(_kind_eq_raw(tK, K_LIT, One),
                                    _kind_eq_raw(sK, K_LIT, One)),
                              reglu(_eq_expr(tV1, One), _eq_expr(sV1, One))),
                        deq_gate)
    deq_lit_str_eq = reglu(deq_lit_str, _eq_expr(tV0, sV0))
    deq_lit_str_ne = deq_lit_str - deq_lit_str_eq
    is_bvar_t = _kind_eq_raw(tK, K_BVAR, One)
    deq_bvar = reglu(reglu(is_bvar_t, _kind_eq_raw(sK, K_BVAR, One)), deq_gate)
    deq_mdata = reglu(reglu(_kind_eq_raw(tK, K_MDATA, One),
                            _kind_eq_raw(sK, K_MDATA, One)), deq_gate)
    deq_tpc = reglu(reglu(_kind_eq_raw(tK, T_PI_CLO, One),
                          _kind_eq_raw(sK, T_PI_CLO, One)), deq_gate)
    # PROJ/PROJ (WP7-A15, K/type_checker.cpp:1216-1227): the kernel's
    # same-sname+idx children attempt (lazy_delta_proj_reduction :1123)
    # COMMITS ONLY ON TRUE; a failing attempt — and a differing sname/idx
    # pair — falls through to the expensive-proj whnf_core at :1224 and the
    # pair is re-dispatched after reduction. The graph models both:
    # proj_same → non-committing DEFEQ attempt + DE_PRJ sink; proj_diff →
    # merged into the soft-whnf fallthrough (deq_sw0).
    deq_proj = reglu(reglu(_kind_eq_raw(tK, K_PROJ, One),
                           _kind_eq_raw(sK, K_PROJ, One)), deq_gate)
    proj_same = reglu(deq_proj, reglu(_eq_expr(tV0, sV0), _eq_expr(tV1, sV1)))
    proj_diff = deq_proj - proj_same
    # A26 (WP7): is_def_eq_offset (K/type_checker.cpp:1076-1085) — the succ
    # case recurses into is_def_eq_core and COMMITS its verdict, so a plain
    # tail-call on the single args is faithful. succ is recognised through
    # the ENV ctor tag (_is_succ: T_ENV_CTORVAL + legacy CID_SUCC fallback),
    # never a literal cid test. The zero/zero side is deq_lit (whnf folds
    # succ(lit) into a literal — reduce_nat, K:702-733). The fn position
    # must be a bare K_CONST: Nat.succ applied exactly once (is_nat_succ
    # matches App(succ_const, arg); over-application is ill-typed).
    a26_fnK_t = fetch_by_position([k_], tV0)[0]
    a26_fnK_s = fetch_by_position([k_], sV0)[0]
    a26_both_app = reglu(_kind_eq_raw(tK, K_APP, One),
                         _kind_eq_raw(sK, K_APP, One))
    a26_fn_const = reglu(_kind_eq_raw(a26_fnK_t, K_CONST, One),
                         _kind_eq_raw(a26_fnK_s, K_CONST, One))
    a26_succ_pair = reglu(_is_succ(_fv0(tV0)), _is_succ(_fv0(sV0)))
    deq_succ = reglu(deq_gate, reglu(a26_both_app,
                                     reglu(a26_fn_const, a26_succ_pair)))
    bind_k = reglu(reglu(_kind_eq_raw(tK, K_LAM, One) + _kind_eq_raw(tK, K_PI, One),
                         _eq_expr(tK, sK)), deq_gate)
    # A14 (WP7): reflection shortcut (K/type_checker.cpp:1181-1185): when s
    # is Bool.true, FULLY reduce t once and compare against true — commit
    # TRUE on a hit; otherwise commit FALSE. The commit-false is faithful:
    # the remaining kernel chain (proof-irrel / app / eta / eta-struct /
    # unit_like) cannot make a Bool-typed pair equal to `true` unless t
    # whnfs to it (Bool is a 2-ctor inductive — no eta-struct, K:896-897;
    # not a Prop — no proof-irrel/unit-like). Bool.true is recognised via
    # the ENV ctor tag (_is_true: name scan + legacy CID_TRUE fallback).
    # Disjoint with deq_const (t also literally true → settled there).
    deq_refl = reglu(reglu(_kind_eq_raw(sK, K_CONST, One),
                           _is_true(sV0)),
                     reglu(reglu(deq_gate, One - deq_const),
                           One - deq_same))
    # A17 (WP7): lazy_delta args fast path (K/type_checker.cpp:1032-1045).
    # Inside lazy_delta_reduction_step's BOTH-DELTA branch, when the two
    # declarations are the same (is_eqp) and Regular-hinted, the kernel
    # compares the level lists (:1037) and then is_def_eq_args on the
    # curried spines (:1038): args-equal COMMITS TRUE (:1039); args-differ
    # only caches the failure and CONTINUES to unfold both sides (:1043).
    # Graph model: non-committing attempt — reuse the stuck-pair peel chain
    # (D_SP1) as a probe whose verdicts route to the DE_ATT sink; sink
    # TRUE commits, sink FALSE re-emits the deq_sw0 fallthrough on the raw
    # pair.  Verdict-neutral by construction (hints are a performance
    # device, K/declaration.h:33): without the gate the pair takes the
    # exact same deq_sw0 route.  ENV-driven: same head cid, head is a
    # K_CONST with an ENV_HDR value (is_delta), hints Regular read from the
    # T_ENV_DEFVAL meta head (no constant names, no cids).
    a17_ht = _head_of(frV1, SPINE_MAX)
    a17_hs = _head_of(frE2, SPINE_MAX)
    a17_cid = _fv0(a17_ht)
    a17_hkt = fetch_by_position([k_], a17_ht)[0]
    a17_hks = fetch_by_position([k_], a17_hs)[0]

    def _hints_regular(cid):
        """1 iff anchor(cid).V2 is a T_ENV_DEFVAL with hints_kind = Regular."""
        h = _mhead(cid)
        return reglu(_kind_eq_raw(fetch_by_position([k_], h)[0],
                                  T_ENV_DEFVAL, One),
                     _eq_expr(fetch_by_position([v1_], h)[0], One + One))
    deq_hargs = reglu(reglu(reglu(
                          reglu(_kind_eq_raw(tK, K_APP, One),
                                _kind_eq_raw(sK, K_APP, One)),
                          reglu(_kind_eq_raw(a17_hkt, K_CONST, One),
                                _kind_eq_raw(a17_hks, K_CONST, One))),
                      reglu(_eq_expr(a17_cid, _fv0(a17_hs)),
                            _geq_expr(fetch_by_position([v2_], One + a17_cid)[0],
                                      One))),
                  reglu(_eq_expr(_mkind(a17_cid), CK_DEFINITION),
                        _hints_regular(a17_cid)))
    # level lists of the two head consts must be defeq (kernel :1037);
    # is_eqp(same cid) means equal lparams, the chains are the args.
    deq_hargs = reglu(deq_hargs, _lvl_chain_eq(
        fetch_by_position([v1_], a17_ht)[0],
        fetch_by_position([v1_], a17_hs)[0], LVL_CHAIN_DEPTH))
    deq_hargs = reglu(deq_hargs, reglu(deq_gate, One - deq_same))
    pi_kind_t = _kind_eq_raw(tK, K_PI, One) + _kind_eq_raw(tK, T_PI_CLO, One)
    pi_kind_s = _kind_eq_raw(sK, K_PI, One) + _kind_eq_raw(sK, T_PI_CLO, One)
    deq_xpi = reglu(reglu(pi_kind_t, reglu(pi_kind_s, One - _eq_expr(tK, sK))),
                    deq_gate)
    deq_fall = reglu(One, deq_gate)
    for _gate in (deq_same, deq_const, deq_sort, deq_lit, deq_lit_str,
                  deq_bvar, deq_mdata, deq_tpc, deq_proj, bind_k, deq_xpi,
                  deq_succ, deq_refl, deq_hargs):
        deq_fall = reglu(deq_fall, One - _gate)
    # WP7-A15: the soft-whnf fallthrough also carries the proj_diff case
    # (kernel falls through :1216 and reaches :1224 whnf_core).
    deq_sw0 = deq_fall + proj_diff

    A_d = SA
    B_d = SB
    C_d = SC
    D_d = SD
    E_d = SE
    F_d = SF
    fr1_task_d, fr1_V1_d, fr1_V2_d, fr1_X_d, fr1_E2_d, fr1_F2_d = \
        Expression({_one_dim: TASK_ST}), Zero, SD, Zero, Zero, Zero
    fr2_task_d, fr2_V1_d, fr2_V2_d, fr2_X_d, fr2_E2_d, fr2_F2_d = \
        Expression({_one_dim: TASK_DEFEQ}), Zero, frV2, Zero, Zero, Zero
    em_link1_d, em_link2_d = Zero, Zero
    link1_V0d, link1_Dd, link1_Pd, link1_Ed, link1_Fd = \
        Zero, Zero, Zero, Zero, Zero
    link2_V0d, link2_Dd, link2_Pd, link2_Ed, link2_Fd = \
        Zero, Zero, Zero, Zero, Zero

    # quick equal: same closure → True
    A_d = _select(deq_same, One, A_d)
    B_d = _select(deq_same, Zero, B_d)
    E_d = _select(deq_same, One, E_d)
    D_d = _select(deq_same, frV2, D_d)
    if VM014_CACHE:
        # card 014 P1: positive-cache hit → True without entering the core
        # machinery (kernel quick_is_def_eq :836 succeeded_before, right
        # after t == s).  Commit shape = deq_same's (A=1, B=0, E=1, D=frV2).
        A_d = _select(defeq_cache, One, A_d)
        B_d = _select(defeq_cache, Zero, B_d)
        E_d = _select(defeq_cache, One, E_d)
        D_d = _select(defeq_cache, frV2, D_d)
    # const/const: same cid AND same level-arg chain (kernel A18
    # is_def_eq_core K/type_checker.cpp:1207-1211: `is_equivalent(levels)`).
    A_d = _select(deq_const, One, A_d)
    B_d = _select(deq_const, Zero, B_d)
    E_d = _select(deq_const, One, E_d)
    D_d = _select(deq_const, frV2, D_d)
    # sort/sort: verdict = _lvl_eq(tV0, sV0) (K/type_checker.cpp:843-844).
    # hoisted: the cache-write arm below fires on this commit only for TRUE.
    _deq_sort_verdict = _lvl_eq(tV0, sV0, LVL_DEPTH)
    A_d = _select(deq_sort, _deq_sort_verdict, A_d)
    B_d = _select(deq_sort, Zero, B_d)
    E_d = _select(deq_sort, One, E_d)
    D_d = _select(deq_sort, frV2, D_d)
    # lit/lit: lockstep digit compare (loop via ST.E2 = k)
    fr1_V1_d = _select(deq_lit, frE2, fr1_V1_d)      # s chain head
    fr1_E2_d = _select(deq_lit, Zero, fr1_E2_d)      # k = 0
    fr1_F2_d = _select(deq_lit, Expression({_one_dim: D_LITL}), fr1_F2_d)
    A_d = _select(deq_lit, frV1, A_d)                # t chain head
    B_d = _select(deq_lit, Zero, B_d)
    E_d = _select(deq_lit, Zero, E_d)
    D_d = _select(deq_lit, c1, D_d)
    # WP5-E3a: string/string.  Different byte counts settle it right here
    # (verdict False — the kernel never pads); equal counts launch the SAME
    # lockstep byte-chain compare (every read is in range because n1 == n2).
    A_d = _select(deq_lit_str_ne, Zero, A_d)
    B_d = _select(deq_lit_str_ne, Zero, B_d)
    E_d = _select(deq_lit_str_ne, One, E_d)
    D_d = _select(deq_lit_str_ne, frV2, D_d)
    fr1_V1_d = _select(deq_lit_str_eq, frE2, fr1_V1_d)
    fr1_E2_d = _select(deq_lit_str_eq, Zero, fr1_E2_d)
    fr1_F2_d = _select(deq_lit_str_eq, Expression({_one_dim: D_LITL}), fr1_F2_d)
    A_d = _select(deq_lit_str_eq, frV1, A_d)
    B_d = _select(deq_lit_str_eq, Zero, B_d)
    E_d = _select(deq_lit_str_eq, Zero, E_d)
    D_d = _select(deq_lit_str_eq, c1, D_d)
    # bvar/bvar: resolve both sides (walks)
    fr1_V1_d = _select(deq_bvar, frE2, fr1_V1_d)
    fr1_X_d = _select(deq_bvar, frF2, fr1_X_d)
    fr1_F2_d = _select(deq_bvar, Expression({_one_dim: D_BV2}), fr1_F2_d)
    fr2_task_d = _select(deq_bvar, Expression({_one_dim: TASK_WALK}), fr2_task_d)
    fr2_V2_d = _select(deq_bvar, c1, fr2_V2_d)
    fr2_X_d = _select(deq_bvar, tV0, fr2_X_d)        # t bvar index
    A_d = _select(deq_bvar, frX, A_d)                # t env chain head
    B_d = _select(deq_bvar, Zero, B_d)
    E_d = _select(deq_bvar, Zero, E_d)
    D_d = _select(deq_bvar, c2, D_d)
    # mdata/mdata: unwrap both (kernel ignores mdata)
    fr1_task_d = _select(deq_mdata, Expression({_one_dim: TASK_DEFEQ}), fr1_task_d)
    fr1_V1_d = _select(deq_mdata, tV0, fr1_V1_d)
    fr1_X_d = _select(deq_mdata, frX, fr1_X_d)
    fr1_E2_d = _select(deq_mdata, sV0, fr1_E2_d)
    fr1_F2_d = _select(deq_mdata, frF2, fr1_F2_d)
    D_d = _select(deq_mdata, c1, D_d)
    E_d = _select(deq_mdata, Zero, E_d)
    # succ/succ (A26): tail-call the args pair — kernel is_def_eq_offset
    # commits the children's core verdict (:1080-1082).
    fr1_task_d = _select(deq_succ, Expression({_one_dim: TASK_DEFEQ}), fr1_task_d)
    fr1_V1_d = _select(deq_succ, tV1, fr1_V1_d)        # t succ arg
    fr1_X_d = _select(deq_succ, frX, fr1_X_d)
    fr1_E2_d = _select(deq_succ, sV1, fr1_E2_d)        # s succ arg
    fr1_F2_d = _select(deq_succ, frF2, fr1_F2_d)
    D_d = _select(deq_succ, c1, D_d)
    E_d = _select(deq_succ, Zero, E_d)
    # reflection (A14): soft-whnf the t side only; the DE_RFL sink compares
    # the reduct against Bool.true and commits the kernel's verdict (:1182).
    fr1_F2_d = _select(deq_refl, Expression({_one_dim: DE_RFL}), fr1_F2_d)
    fr2_task_d = _select(deq_refl, Expression({_one_dim: TASK_WHNF}), fr2_task_d)
    fr2_V1_d = _select(deq_refl, frV1, fr2_V1_d)
    fr2_X_d = _select(deq_refl, frX, fr2_X_d)
    fr2_E2_d = _select(deq_refl, One, fr2_E2_d)       # soft whnf
    fr2_V2_d = _select(deq_refl, c1, fr2_V2_d)
    A_d = _select(deq_refl, frV1, A_d)
    B_d = _select(deq_refl, frX, B_d)
    C_d = _select(deq_refl, Zero, C_d)
    F_d = _select(deq_refl, Zero, F_d)
    E_d = _select(deq_refl, Zero, E_d)
    D_d = _select(deq_refl, c2, D_d)
    # args fast path (A17): frame1 = sink ST(DE_ATT, V2=SD default = this
    # DEFEQ frame); frame2 = peel ST(D_SP1) mirroring ST_SP's both-app
    # kickoff, V2 = c1 so every peel verdict commits INTO THE SINK instead
    # of the caller; the sink re-emits deq_sw0 on a FALSE attempt.
    fr1_F2_d = _select(deq_hargs, Expression({_one_dim: DE_ATT}), fr1_F2_d)
    fr2_task_d = _select(deq_hargs, Expression({_one_dim: TASK_ST}), fr2_task_d)
    fr2_V1_d = _select(deq_hargs, frF2, fr2_V1_d)     # s env
    fr2_F2_d = _select(deq_hargs, Expression({_one_dim: D_SP1}), fr2_F2_d)
    fr2_V2_d = _select(deq_hargs, c1, fr2_V2_d)       # commits → sink
    A_d = _select(deq_hargs, frV1, A_d)               # t spine focus
    B_d = _select(deq_hargs, frX, B_d)                # t env
    E_d = _select(deq_hargs, frE2, E_d)               # s spine focus
    C_d = _select(deq_hargs, Zero, C_d)
    F_d = _select(deq_hargs, Zero, F_d)
    D_d = _select(deq_hargs, c2, D_d)
    # T_PI_CLO/T_PI_CLO: dom then body, each side's own env
    fr1_X_d = _select(deq_tpc, SD, fr1_X_d)
    fr1_F2_d = _select(deq_tpc, Expression({_one_dim: D_TPC2}), fr1_F2_d)
    fr2_V1_d = _select(deq_tpc, tV0, fr2_V1_d)
    fr2_X_d = _select(deq_tpc, tXf, fr2_X_d)
    fr2_E2_d = _select(deq_tpc, sV0, fr2_E2_d)
    fr2_F2_d = _select(deq_tpc, sXf, fr2_F2_d)
    fr2_V2_d = _select(deq_tpc, c1, fr2_V2_d)       # caller = the ST
    D_d = _select(deq_tpc, c2, D_d)
    E_d = _select(deq_tpc, Zero, E_d)
    # PROJ/PROJ (WP7-A15): same sname+idx → NON-COMMITTING children attempt.
    # frame1 = sink ST(F2=DE_PRJ, V2=SD = this DEFEQ frame — the true-commit
    # pass-through and the false re-entry oo* both resolve through it);
    # frame2 = the children DEFEQ (kernel :1219 attempt). proj_diff pairs
    # are emitted by deq_sw0 in the fallthrough block below.
    fr1_F2_d = _select(proj_same, Expression({_one_dim: DE_PRJ}), fr1_F2_d)
    fr2_V1_d = _select(proj_same, tXf, fr2_V1_d)       # t proj child
    fr2_X_d = _select(proj_same, frX, fr2_X_d)
    fr2_E2_d = _select(proj_same, sXf, fr2_E2_d)       # s proj child
    fr2_F2_d = _select(proj_same, frF2, fr2_F2_d)
    fr2_V2_d = _select(proj_same, c1, fr2_V2_d)        # caller = the sink
    A_d = _select(proj_same, tXf, A_d)
    B_d = _select(proj_same, frX, B_d)
    C_d = _select(proj_same, Zero, C_d)
    F_d = _select(proj_same, Zero, F_d)
    E_d = _select(proj_same, Zero, E_d)
    D_d = _select(proj_same, c2, D_d)
    # binding pair (LAM/LAM, PI/PI): domains first, then per-side markers
    fr1_X_d = _select(bind_k, SD, fr1_X_d)
    fr1_F2_d = _select(bind_k, Expression({_one_dim: D_BIND2}), fr1_F2_d)
    fr2_V1_d = _select(bind_k, tV0, fr2_V1_d)
    fr2_X_d = _select(bind_k, frX, fr2_X_d)
    fr2_E2_d = _select(bind_k, sV0, fr2_E2_d)
    fr2_F2_d = _select(bind_k, frF2, fr2_F2_d)
    fr2_V2_d = _select(bind_k, c1, fr2_V2_d)        # caller = the ST
    D_d = _select(bind_k, c2, D_d)
    E_d = _select(bind_k, Zero, E_d)
    # cross-kind pi: dom first (each side's own env via _pi_parts)
    dx_env_t = _select(_kind_eq_raw(tK, K_PI, One), frX, tXf)
    dx_env_s = _select(_kind_eq_raw(sK, K_PI, One), frF2, sXf)
    fr1_X_d = _select(deq_xpi, SD, fr1_X_d)
    fr1_F2_d = _select(deq_xpi, Expression({_one_dim: D_XPI2}), fr1_F2_d)
    fr2_V1_d = _select(deq_xpi, tV0, fr2_V1_d)
    fr2_X_d = _select(deq_xpi, dx_env_t, fr2_X_d)
    fr2_E2_d = _select(deq_xpi, sV0, fr2_E2_d)
    fr2_F2_d = _select(deq_xpi, dx_env_s, fr2_F2_d)
    fr2_V2_d = _select(deq_xpi, c1, fr2_V2_d)       # caller = the ST
    D_d = _select(deq_xpi, c2, D_d)
    E_d = _select(deq_xpi, Zero, E_d)
    # fallthrough: soft-whnf both sides (WHNF frames flagged E2=1)
    fr1_V1_d = _select(deq_sw0, frE2, fr1_V1_d)
    fr1_X_d = _select(deq_sw0, frF2, fr1_X_d)
    fr1_V2_d = _select(deq_sw0, SD, fr1_V2_d)       # orig frame pos
    fr1_F2_d = _select(deq_sw0, Expression({_one_dim: D_SW2}), fr1_F2_d)
    fr2_task_d = _select(deq_sw0, Expression({_one_dim: TASK_WHNF}), fr2_task_d)
    fr2_V1_d = _select(deq_sw0, frV1, fr2_V1_d)
    fr2_X_d = _select(deq_sw0, frX, fr2_X_d)
    fr2_E2_d = _select(deq_sw0, One, fr2_E2_d)
    fr2_V2_d = _select(deq_sw0, c1, fr2_V2_d)
    A_d = _select(deq_sw0, frV1, A_d)
    B_d = _select(deq_sw0, frX, B_d)
    C_d = _select(deq_sw0, Zero, C_d)
    F_d = _select(deq_sw0, Zero, F_d)
    E_d = _select(deq_sw0, Zero, E_d)
    D_d = _select(deq_sw0, c2, D_d)

    # ── CONT branches for DEFEQ sub-results ─────────────────────────────────
    def deliver(v):
        return (v, Zero, One, frV2)

    # D_SORT2: l1 in A; scan s side.
    fr1_V1 = _select(cg[D_SORT2], SA, fr1_V1)         # save l1
    fr1_X = _select(cg[D_SORT2], frV1, fr1_X)         # s level root
    fr1_F2 = _select(cg[D_SORT2], Expression({_one_dim: D_SORT3}), fr1_F2)
    fr2_task = _select(cg[D_SORT2], Expression({_one_dim: TASK_LEVEL}), fr2_task)
    fr2_V2 = _select(cg[D_SORT2], c1, fr2_V2)
    fr2_X = _select(cg[D_SORT2], Zero, fr2_X)
    A_c = _select(cg[D_SORT2], frV1, A_c)
    B_c = _select(cg[D_SORT2], Zero, B_c)
    E_c = _select(cg[D_SORT2], Zero, E_c)
    D_c = _select(cg[D_SORT2], c2, D_c)
    # D_SORT3: l2 in A; verdict = (l1 == l2)
    sort_v = _select(_eq_expr(frV1, SA), One, Zero)
    A_c = _select(cg[D_SORT3], sort_v, A_c)
    B_c = _select(cg[D_SORT3], Zero, B_c)
    E_c = _select(cg[D_SORT3], One, E_c)
    D_c = _select(cg[D_SORT3], frV2, D_c)

    # D_BIND2: dom verdict in A; push per-side markers, compare bodies.
    # (kernel is_def_eq_binding: dom mismatch → verdict False, no throw)
    bind_fail = reglu(cg[D_BIND2], One - _geq_expr(SA, One))
    b2g = cg[D_BIND2] - bind_fail
    A_c = _select(bind_fail, Zero, A_c)
    B_c = _select(bind_fail, Zero, B_c)
    E_c = _select(bind_fail, One, E_c)
    D_c = _select(bind_fail, frV2, D_c)
    link1_V0 = _select(b2g, oV0, link1_V0)
    link1_D = _select(b2g, ldepth(oX), link1_D)
    link1_P = _select(b2g, oX, link1_P)
    link1_E = _select(b2g, oX, link1_E)
    link1_F = _select(b2g, One, link1_F)
    link1_F2 = _select(b2g, c1, link1_F2)     # M3 bid = mt pos (shared)
    em_link1_c = em_link1_c + b2g
    link2_V0 = _select(b2g, sDom, link2_V0)
    link2_D = _select(b2g, ldepth(oF2), link2_D)
    link2_P = _select(b2g, oF2, link2_P)
    link2_E = _select(b2g, oF2, link2_E)
    link2_F = _select(b2g, One, link2_F)
    link2_F2 = _select(b2g, c1, link2_F2)     # M3 bid = mt pos (shared)
    em_link2_c = b2g
    fr2_task = _select(b2g, Expression({_one_dim: TASK_DEFEQ}), fr2_task)
    fr2_V1 = _select(b2g, oBd, fr2_V1)        # t body
    fr2_X = _select(b2g, c1, fr2_X)           # mt
    fr2_E2 = _select(b2g, sBd, fr2_E2)        # s body
    fr2_F2 = _select(b2g, c2, fr2_F2)         # ms
    fr2_V2 = _select(b2g, frV2, fr2_V2)
    D_c = _select(b2g, c3, D_c)
    E_c = _select(b2g, Zero, E_c)

    # D_TPC2: dom verdict in A; compare bodies (each side's own env).
    tpc_fail = reglu(cg[D_TPC2], One - _geq_expr(SA, One))
    tpcg = cg[D_TPC2] - tpc_fail
    A_c = _select(tpc_fail, Zero, A_c)
    B_c = _select(tpc_fail, Zero, B_c)
    E_c = _select(tpc_fail, One, E_c)
    D_c = _select(tpc_fail, frV2, D_c)
    fr2_task = _select(tpcg, Expression({_one_dim: TASK_DEFEQ}), fr2_task)
    fr2_V1 = _select(tpcg, oBd, fr2_V1)
    fr2_X = _select(tpcg, oBdE, fr2_X)
    fr2_E2 = _select(tpcg, sBd, fr2_E2)
    fr2_F2 = _select(tpcg, sBdE, fr2_F2)
    fr2_V2 = _select(tpcg, frV2, fr2_V2)
    D_c = _select(tpcg, c1, D_c)
    E_c = _select(tpcg, Zero, E_c)

    # D_BV2: t resolved in (A,B); walk the s side.
    fr1_V1 = _select(cg[D_BV2], SA, fr1_V1)           # t resolved pos
    fr1_X = _select(cg[D_BV2], SB, fr1_X)             # t resolved env
    fr1_E2 = _select(cg[D_BV2], sidx, fr1_E2)         # s bvar index
    fr1_V2 = _select(cg[D_BV2], frV2, fr1_V2)         # caller
    fr1_F2 = _select(cg[D_BV2], Expression({_one_dim: D_BV3}), fr1_F2)
    fr2_task = _select(cg[D_BV2], Expression({_one_dim: TASK_WALK}), fr2_task)
    fr2_V2 = _select(cg[D_BV2], c1, fr2_V2)
    fr2_X = _select(cg[D_BV2], sidx, fr2_X)
    A_c = _select(cg[D_BV2], frX, A_c)                # s env chain head
    B_c = _select(cg[D_BV2], Zero, B_c)
    E_c = _select(cg[D_BV2], Zero, E_c)
    D_c = _select(cg[D_BV2], c2, D_c)
    # D_BV3: both bvar sides resolved to LINK positions (frV1 = t link,
    # SA = s link). Kernel is_def_eq BVar/BVar: both markers + same bid →
    # True; both markers + distinct bid → stuck pair (chain); otherwise
    # substitute the value link(s) and continue.
    bv_ltF = fetch_by_position([e2_], frV1)[0]   # t link flag
    bv_ltB = fetch_by_position([f2_], frV1)[0]   # t link bid
    bv_ltV = _fv0(frV1)   # t link value pos
    bv_ltE = fetch_by_position([x_], frV1)[0]    # t link value env
    bv_lsF = fetch_by_position([e2_], SA)[0]     # s link flag
    bv_lsB = fetch_by_position([f2_], SA)[0]     # s link bid
    bv_lsV = _fv0(SA)     # s link value pos
    bv_lsE = fetch_by_position([x_], SA)[0]      # s link value env
    bv_both = reglu(bv_ltF, bv_lsF)
    bv_same = reglu(bv_both, reglu(_geq_expr(bv_ltB, One),
                                   _eq_expr(bv_ltB, bv_lsB)))
    bv_diff = reglu(bv_both, One - bv_same)
    bv_s = reglu(cg[D_BV3], bv_same)
    bv_d = reglu(cg[D_BV3], bv_diff)
    bv_nb = reglu(cg[D_BV3], One - bv_both)
    # same bid → True
    A_c = _select(bv_s, One, A_c)
    B_c = _select(bv_s, Zero, B_c)
    E_c = _select(bv_s, One, E_c)
    D_c = _select(bv_s, frV2, D_c)
    # distinct bid → stuck pair → proof-irrel chain (M3 STAGE 2). nt = the
    # original t closure (caller.V1/X — a BVar token; soft-whnf left markers
    # unmoved). PI_T fetches the pair from caller = frV2 (default fr1_V2).
    fr1_F2 = _select(bv_d, Expression({_one_dim: PI_T}), fr1_F2)
    A_c = _select(bv_d, ooV1, A_c)
    B_c = _select(bv_d, ooX, B_c)
    C_c = _select(bv_d, Zero, C_c)
    F_c = _select(bv_d, Zero, F_c)
    E_c = _select(bv_d, One, E_c)
    D_c = _select(bv_d, c1, D_c)
    # not both markers → substitute the value side(s), continue DEFEQ
    nb_tp = _select(bv_ltF, ooV1, bv_ltV)
    nb_te = _select(bv_ltF, ooX, bv_ltE)
    nb_sp = _select(bv_lsF, ooE2, bv_lsV)
    nb_se = _select(bv_lsF, ooF2, bv_lsE)
    fr1_task = _select(bv_nb, Expression({_one_dim: TASK_DEFEQ}), fr1_task)
    fr1_V1 = _select(bv_nb, nb_tp, fr1_V1)
    fr1_X = _select(bv_nb, nb_te, fr1_X)
    fr1_E2 = _select(bv_nb, nb_sp, fr1_E2)
    fr1_F2 = _select(bv_nb, nb_se, fr1_F2)
    fr1_V2 = _select(bv_nb, frV2, fr1_V2)
    D_c = _select(bv_nb, c1, D_c)
    E_c = _select(bv_nb, Zero, E_c)

    # D_XPI2: dom verdict in A; marker on the K_PI side, compare bodies.
    xpi_fail = reglu(cg[D_XPI2], One - _geq_expr(SA, One))
    xpig = cg[D_XPI2] - xpi_fail
    A_c = _select(xpi_fail, Zero, A_c)
    B_c = _select(xpi_fail, Zero, B_c)
    E_c = _select(xpi_fail, One, E_c)
    D_c = _select(xpi_fail, frV2, D_c)
    t_is_pi = _kind_eq_raw(oK, K_PI, One)
    link1_V0 = _select(xpig, _select(t_is_pi, oV0, sDom), link1_V0)
    link1_D = _select(xpig, _select(t_is_pi, ldepth(oX), ldepth(oF2)),
                      link1_D)
    link1_P = _select(xpig, _select(t_is_pi, oX, oF2), link1_P)
    link1_E = _select(xpig, _select(t_is_pi, oX, oF2), link1_E)
    link1_F = _select(xpig, One, link1_F)
    # Adopt the T_PI_CLO side's binder identity so the fresh K_PI marker and
    # the already-inferred marker resolve bvars to the same bid (D_BV3); see
    # the I_LAMSORT bid note. tpc_env is the existing body env of whichever
    # side is the machine-emitted T_PI_CLO (t: oBdE, s: sBdE).
    xpi_tpc_env = _select(t_is_pi, sBdE, oBdE)
    xpi_tpc_flag = fetch_by_position([e2_], xpi_tpc_env)[0]
    xpi_tpc_bid = fetch_by_position([f2_], xpi_tpc_env)[0]
    link1_F2 = _select(xpig,
                       _select(_geq_expr(xpi_tpc_flag, One),
                               xpi_tpc_bid, Zero), link1_F2)
    em_link1_c = em_link1_c + xpig
    fr2_task = _select(xpig, Expression({_one_dim: TASK_DEFEQ}), fr2_task)
    fr2_V1 = _select(xpig, oBd, fr2_V1)
    fr2_X = _select(xpig, _select(t_is_pi, c1, oBdE), fr2_X)
    fr2_E2 = _select(xpig, sBd, fr2_E2)
    fr2_F2 = _select(xpig, _select(t_is_pi, sBdE, c1), fr2_F2)
    fr2_V2 = _select(xpig, frV2, fr2_V2)
    D_c = _select(xpig, c2, D_c)
    E_c = _select(xpig, Zero, E_c)

    # D_SW2: nt in (A,B); soft-whnf the s side.
    fr1_V1 = _select(cg[D_SW2], SA, fr1_V1)           # nt pos
    fr1_X = _select(cg[D_SW2], SB, fr1_X)             # nt env
    fr1_V2 = _select(cg[D_SW2], frV2, fr1_V2)         # ST_a pos
    fr1_F2 = _select(cg[D_SW2], Expression({_one_dim: D_SW3}), fr1_F2)
    fr2_task = _select(cg[D_SW2], Expression({_one_dim: TASK_WHNF}), fr2_task)
    fr2_V1 = _select(cg[D_SW2], frV1, fr2_V1)         # s pos
    fr2_X = _select(cg[D_SW2], frX, fr2_X)            # s env
    fr2_E2 = _select(cg[D_SW2], One, fr2_E2)          # soft
    fr2_V2 = _select(cg[D_SW2], c1, fr2_V2)
    A_c = _select(cg[D_SW2], frV1, A_c)
    B_c = _select(cg[D_SW2], frX, B_c)
    C_c = _select(cg[D_SW2], Zero, C_c)
    F_c = _select(cg[D_SW2], Zero, F_c)
    E_c = _select(cg[D_SW2], Zero, E_c)
    D_c = _select(cg[D_SW2], c2, D_c)

    # D_SW3: ns in (A,B); nt = (frV1, frX); ST_a at frV2; orig at nbV2.
    sw_stuck = reglu(reglu(_eq_expr(frV1, ooV1), _eq_expr(frX, ooX)),
                     reglu(_eq_expr(SA, ooE2), _eq_expr(SB, ooF2)))
    sw3 = cg[D_SW3]
    sw_loop = reglu(sw3, One - sw_stuck)
    # M3 STAGE 2: both stuck → proof-irrelevance chain (kernel is_def_eq_core
    # runs is_def_eq_proof_irrel BEFORE the app-spine / nat-ctor / eta steps).
    # The chain's fall-through (ST_SP) re-does the both-app / nat dispatch.
    sw_pi = reglu(sw3, sw_stuck)
    # loop: continue with the reduced pair
    fr1_task = _select(sw_loop, Expression({_one_dim: TASK_DEFEQ}), fr1_task)
    fr1_V1 = _select(sw_loop, frV1, fr1_V1)
    fr1_X = _select(sw_loop, frX, fr1_X)
    fr1_E2 = _select(sw_loop, SA, fr1_E2)
    fr1_F2 = _select(sw_loop, SB, fr1_F2)
    fr1_V2 = _select(sw_loop, frV2, fr1_V2)
    D_c = _select(sw_loop, c1, D_c)
    E_c = _select(sw_loop, Zero, E_c)
    # both stuck → push PI_T kickoff (single ST frame), focus = nt, E=1 so the
    # next step dispatches PI_T. PI_T fetches the stuck pair from caller=frV2
    # (the buried DEFEQ frame: nt=(V1,X), ns=(E2,F2), sw_stuck ⇒ nt/ns are the
    # original closures — soft-whnf left them unmoved).
    fr1_F2 = _select(sw_pi, Expression({_one_dim: PI_T}), fr1_F2)
    A_c = _select(sw_pi, frV1, A_c)               # nt pos
    B_c = _select(sw_pi, frX, B_c)                # nt env
    C_c = _select(sw_pi, Zero, C_c)
    F_c = _select(sw_pi, Zero, F_c)
    E_c = _select(sw_pi, One, E_c)
    D_c = _select(sw_pi, c1, D_c)

    # DE_PRJ (WP7-A15): sink for the non-committing proj/proj children
    # attempt. The child DEFEQ delivered its verdict in A (E=1 pass).
    # TRUE  → commit through the buried DEFEQ frame (kernel :1219-1220;
    #         pop_task on that frame carries the verdict to its caller).
    # FALSE → the kernel falls through :1224 whnf_core: re-emit the
    #         deq_fall shape reading the ORIGINAL pair from oo* (the buried
    #         DEFEQ frame's fields), exactly as a first-entry fallthrough
    #         (D_SW2 inherits V2; D_SW3's sw_stuck compare and sw_loop
    #         re-dispatch stay valid). A stuck pair lands on the PI chain
    #         and its normal verdict.
    de_prj_t = reglu(cg[DE_PRJ], _geq_expr(SA, One))
    de_prj_f = reglu(cg[DE_PRJ], One - _geq_expr(SA, One))
    A_c = _select(de_prj_t, One, A_c)
    B_c = _select(de_prj_t, Zero, B_c)
    E_c = _select(de_prj_t, One, E_c)
    D_c = _select(de_prj_t, frV2, D_c)
    fr1_V1 = _select(de_prj_f, ooE2, fr1_V1)
    fr1_X = _select(de_prj_f, ooF2, fr1_X)
    fr1_V2 = _select(de_prj_f, frV2, fr1_V2)
    fr1_F2 = _select(de_prj_f, Expression({_one_dim: D_SW2}), fr1_F2)
    fr2_task = _select(de_prj_f, Expression({_one_dim: TASK_WHNF}), fr2_task)
    fr2_V1 = _select(de_prj_f, ooV1, fr2_V1)
    fr2_X = _select(de_prj_f, ooX, fr2_X)
    fr2_E2 = _select(de_prj_f, One, fr2_E2)           # soft whnf
    fr2_V2 = _select(de_prj_f, c1, fr2_V2)
    A_c = _select(de_prj_f, ooV1, A_c)
    B_c = _select(de_prj_f, ooX, B_c)
    C_c = _select(de_prj_f, Zero, C_c)
    F_c = _select(de_prj_f, Zero, F_c)
    E_c = _select(de_prj_f, Zero, E_c)
    D_c = _select(de_prj_f, c2, D_c)

    # DE_RFL (WP7-A14): reflection sink. The soft WHNF delivered nt in (A,B).
    # nt is Bool.true → commit TRUE (kernel :1182-1183); else commit FALSE —
    # faithful because the rest of the kernel chain cannot equate a Bool
    # pair with `true` unless the reduct IS true (see the gate comment).
    rfl_k = fetch_by_position([k_], SA)[0]
    rfl_true = reglu(cg[DE_RFL], _kind_eq_raw(rfl_k, K_CONST, One))
    rfl_true = reglu(rfl_true, _is_true(_fv0(SA)))
    A_c = _select(cg[DE_RFL], rfl_true, A_c)
    B_c = _select(cg[DE_RFL], Zero, B_c)
    E_c = _select(cg[DE_RFL], One, E_c)
    D_c = _select(cg[DE_RFL], frV2, D_c)

    # DE_ATT (WP7-A17): sink for the lazy_delta args attempt. The peel
    # chain committed its accumulated verdict in A (E=1 pass).
    # TRUE  → commit through the buried DEFEQ frame (kernel :1039).
    # FALSE → the kernel cached the failure and CONTINUES to unfold both
    #         sides (:1043): re-emit the deq_sw0 shape on the ORIGINAL pair
    #         read from oo*, exactly as DE_PRJ's fallthrough.
    de_att_t = reglu(cg[DE_ATT], _geq_expr(SA, One))
    de_att_f = reglu(cg[DE_ATT], One - _geq_expr(SA, One))
    A_c = _select(de_att_t, One, A_c)
    B_c = _select(de_att_t, Zero, B_c)
    E_c = _select(de_att_t, One, E_c)
    D_c = _select(de_att_t, frV2, D_c)
    fr1_V1 = _select(de_att_f, ooE2, fr1_V1)
    fr1_X = _select(de_att_f, ooF2, fr1_X)
    fr1_V2 = _select(de_att_f, frV2, fr1_V2)
    fr1_F2 = _select(de_att_f, Expression({_one_dim: D_SW2}), fr1_F2)
    fr2_task = _select(de_att_f, Expression({_one_dim: TASK_WHNF}), fr2_task)
    fr2_V1 = _select(de_att_f, ooV1, fr2_V1)
    fr2_X = _select(de_att_f, ooX, fr2_X)
    fr2_E2 = _select(de_att_f, One, fr2_E2)           # soft whnf
    fr2_V2 = _select(de_att_f, c1, fr2_V2)
    A_c = _select(de_att_f, ooV1, A_c)
    B_c = _select(de_att_f, ooX, B_c)
    C_c = _select(de_att_f, Zero, C_c)
    F_c = _select(de_att_f, Zero, F_c)
    E_c = _select(de_att_f, Zero, E_c)
    D_c = _select(de_att_f, c2, D_c)

    # ── Phase 5 M3: proof-irrelevance chain (kernel is_def_eq_proof_irrel) ──
    # Every step is an ST frame with V2 = caller (the buried DEFEQ frame, so
    # the pair is re-fetched via oo* and the final verdict lands there). The
    # chain: infer nt → t_ty; infer t_ty → ty_sort; is_prop(ty_sort)? if so
    # infer ns → s_ty and defeq(t_ty, s_ty); else fall through to ST_SP.
    # PI_T: focus = nt (A,B). infer nt → t_ty (PI_TY).
    fr1_F2 = _select(cg[PI_T], Expression({_one_dim: PI_TY}), fr1_F2)
    fr2_task = _select(cg[PI_T], Expression({_one_dim: TASK_INFER}), fr2_task)
    fr2_V2 = _select(cg[PI_T], c1, fr2_V2)
    fr2_E2 = _select(cg[PI_T], One, fr2_E2)       # INFER phase P1
    # soft infer (F2=1): ref _proof_irrel wraps infer(t)/infer(t_ty) in
    # try/except VMError(ERR_TYPE, ERR_UNSUPPORTED) → None → decline. A fail
    # inside this task delivers a A=0 marker to the awaiting ST instead of
    # rejecting; the PI_TY cont turns it into the ST_SP fall-through.
    fr2_F2 = _select(cg[PI_T], One, fr2_F2)
    C_c = _select(cg[PI_T], Zero, C_c)
    F_c = _select(cg[PI_T], Zero, F_c)
    E_c = _select(cg[PI_T], Zero, E_c)
    D_c = _select(cg[PI_T], c2, D_c)
    # PI_TY: t_ty in (A,B). infer t_ty → ty_sort (PI_LVL carries t_ty).
    fr1_V1 = _select(cg[PI_TY], SA, fr1_V1)       # t_ty pos
    fr1_X = _select(cg[PI_TY], SB, fr1_X)         # t_ty env
    fr1_F2 = _select(cg[PI_TY], Expression({_one_dim: PI_LVL}), fr1_F2)
    fr2_task = _select(cg[PI_TY], Expression({_one_dim: TASK_INFER}), fr2_task)
    fr2_V2 = _select(cg[PI_TY], c1, fr2_V2)
    fr2_E2 = _select(cg[PI_TY], One, fr2_E2)
    fr2_F2 = _select(cg[PI_TY], One, fr2_F2)      # soft infer (same try scope)
    C_c = _select(cg[PI_TY], Zero, C_c)
    F_c = _select(cg[PI_TY], Zero, F_c)
    E_c = _select(cg[PI_TY], Zero, E_c)
    D_c = _select(cg[PI_TY], c2, D_c)
    # PI_LVL: ty_sort in (A,B); t_ty in (frV1,frX). is_prop ⇔ ty_sort is a
    # K_SORT whose level root is KL_ZERO (level 0; the toy env's only Prop).
    pl_sk = fetch_by_position([k_], SA)[0]
    pl_lv = _fv0(SA)
    pl_lvK = fetch_by_position([k_], pl_lv)[0]
    pl_prop = reglu(cg[PI_LVL], reglu(_kind_eq_raw(pl_sk, K_SORT, One),
                                      _kind_eq_raw(pl_lvK, KL_ZERO, One)))
    pl_fall = reglu(cg[PI_LVL], One - pl_prop)
    # Prop → infer ns → s_ty (PI_D carries t_ty); focus = ns (from caller).
    fr1_V1 = _select(pl_prop, frV1, fr1_V1)       # t_ty pos
    fr1_X = _select(pl_prop, frX, fr1_X)          # t_ty env
    fr1_F2 = _select(pl_prop, Expression({_one_dim: PI_D}), fr1_F2)
    fr2_task = _select(pl_prop, Expression({_one_dim: TASK_INFER}), fr2_task)
    fr2_V1 = _select(pl_prop, ooE2, fr2_V1)       # ns pos
    fr2_X = _select(pl_prop, ooF2, fr2_X)         # ns env
    fr2_V2 = _select(pl_prop, c1, fr2_V2)
    fr2_E2 = _select(pl_prop, One, fr2_E2)
    A_c = _select(pl_prop, ooE2, A_c)             # focus = ns
    B_c = _select(pl_prop, ooF2, B_c)
    C_c = _select(pl_prop, Zero, C_c)
    F_c = _select(pl_prop, Zero, F_c)
    E_c = _select(pl_prop, Zero, E_c)
    D_c = _select(pl_prop, c2, D_c)
    # not Prop → fall through to the stuck-pair chain (ST_SP, single frame).
    fr1_F2 = _select(pl_fall, Expression({_one_dim: ST_SP}), fr1_F2)
    C_c = _select(pl_fall, Zero, C_c)
    F_c = _select(pl_fall, Zero, F_c)
    E_c = _select(pl_fall, One, E_c)
    D_c = _select(pl_fall, c1, D_c)
    # PI_D: s_ty in (A,B); t_ty in (frV1,frX). defeq(t_ty, s_ty) → caller.
    fr1_task = _select(cg[PI_D], Expression({_one_dim: TASK_DEFEQ}), fr1_task)
    fr1_V1 = _select(cg[PI_D], frV1, fr1_V1)      # t_ty pos
    fr1_X = _select(cg[PI_D], frX, fr1_X)         # t_ty env
    fr1_E2 = _select(cg[PI_D], SA, fr1_E2)        # s_ty pos
    fr1_F2 = _select(cg[PI_D], SB, fr1_F2)        # s_ty env
    A_c = _select(cg[PI_D], frV1, A_c)            # focus = t_ty
    B_c = _select(cg[PI_D], frX, B_c)
    C_c = _select(cg[PI_D], Zero, C_c)
    F_c = _select(cg[PI_D], Zero, F_c)
    E_c = _select(cg[PI_D], Zero, E_c)
    D_c = _select(cg[PI_D], c1, D_c)
    # ST_SP: proof-irrel did not apply — kernel stuck-pair order continues:
    # both-app → spine peel (D_SP1); else nat-ctor extract (D_NCT). Pair from
    # caller (oo*); caller = frV2 (default fr1_V2).
    sp_ntK = fetch_by_position([k_], ooV1)[0]
    sp_nsK = fetch_by_position([k_], ooE2)[0]
    sp_both_app = reglu(cg[ST_SP], reglu(_kind_eq_raw(sp_ntK, K_APP, One),
                                         _kind_eq_raw(sp_nsK, K_APP, One)))
    sp_nat = reglu(cg[ST_SP], One - sp_both_app)
    fr1_V1 = _select(sp_both_app, ooF2, fr1_V1)   # s env
    fr1_X = _select(sp_both_app, Zero, fr1_X)     # arity count
    fr1_F2 = _select(sp_both_app, Expression({_one_dim: D_SP1}), fr1_F2)
    A_c = _select(sp_both_app, ooV1, A_c)         # t spine cur
    B_c = _select(sp_both_app, ooX, B_c)          # t env
    E_c = _select(sp_both_app, ooE2, E_c)         # s spine cur
    C_c = _select(sp_both_app, Zero, C_c)
    F_c = _select(sp_both_app, Zero, F_c)
    D_c = _select(sp_both_app, c1, D_c)
    fr1_V1 = _select(sp_nat, ooE2, fr1_V1)        # s spine cur
    fr1_F2 = _select(sp_nat, Expression({_one_dim: D_NCT}), fr1_F2)
    A_c = _select(sp_nat, ooV1, A_c)              # t spine cur
    B_c = _select(sp_nat, Zero, B_c)
    E_c = _select(sp_nat, Zero, E_c)
    C_c = _select(sp_nat, Zero, C_c)
    F_c = _select(sp_nat, Zero, F_c)
    D_c = _select(sp_nat, c1, D_c)

    # ── Phase 5 M3: eta expansion (kernel try_eta_expansion_core) ───────────
    # Reached from ST_SP's nat branch when the heads are not both nat-ctors
    # (nc_fail → ST_ET). Exactly one side is a lambda (the other is not); we
    # compare the lambda against the eta-expansion of the other side:
    #   lam x. body  ≡  g   iff   dom(body-lam) ≡ dom(g)  and
    #   body[x:=M] ≡ (g BVar0)[x:=M2]  where M,L,M2 are the marker/value
    #   links ref_vm._try_eta builds (M2 shares M's binder id). The stuck pair
    #   is re-fetched from the buried DEFEQ caller (oo*); lam_is_t (which side
    #   is the lambda) rides in ST.V1, caller in V2.
    et_ntK = fetch_by_position([k_], ooV1)[0]
    et_nsK = fetch_by_position([k_], ooE2)[0]
    et_lam_t = _kind_eq_raw(et_ntK, K_LAM, One)
    et_lam_s = _kind_eq_raw(et_nsK, K_LAM, One)
    et_xor = et_lam_t + et_lam_s - reglu(et_lam_t, et_lam_s) * 2   # exactly one lam
    et_app = reglu(cg[ST_ET], et_xor)
    et_fall = reglu(cg[ST_ET], One - et_xor)
    et_gpos = _select(et_lam_t, ooE2, ooV1)                  # non-lam side
    et_genv = _select(et_lam_t, ooF2, ooX)
    # ST_ET applicable → infer the non-lam side (ETA_T carries lam_is_t).
    fr1_V1 = _select(et_app, et_lam_t, fr1_V1)
    fr1_F2 = _select(et_app, Expression({_one_dim: ETA_T}), fr1_F2)
    fr2_task = _select(et_app, Expression({_one_dim: TASK_INFER}), fr2_task)
    fr2_V1 = _select(et_app, et_gpos, fr2_V1)
    fr2_X = _select(et_app, et_genv, fr2_X)
    fr2_V2 = _select(et_app, c1, fr2_V2)
    fr2_E2 = _select(et_app, One, fr2_E2)
    A_c = _select(et_app, et_gpos, A_c)
    B_c = _select(et_app, et_genv, B_c)
    C_c = _select(et_app, Zero, C_c)
    F_c = _select(et_app, Zero, F_c)
    E_c = _select(et_app, Zero, E_c)
    D_c = _select(et_app, c2, D_c)
    # ST_ET not applicable (both/none lam) → structural eta (ST_ES).
    fr1_F2 = _select(et_fall, Expression({_one_dim: ST_ES}), fr1_F2)
    C_c = _select(et_fall, Zero, C_c)
    F_c = _select(et_fall, Zero, F_c)
    E_c = _select(et_fall, One, E_c)
    D_c = _select(et_fall, c1, D_c)
    # ETA_T: g_ty in (A,B). whnf it → s_ty (ETA_S).
    fr1_V1 = _select(cg[ETA_T], frV1, fr1_V1)               # lam_is_t
    fr1_F2 = _select(cg[ETA_T], Expression({_one_dim: ETA_S}), fr1_F2)
    fr2_task = _select(cg[ETA_T], Expression({_one_dim: TASK_WHNF}), fr2_task)
    fr2_V1 = _select(cg[ETA_T], SA, fr2_V1)
    fr2_X = _select(cg[ETA_T], SB, fr2_X)
    fr2_V2 = _select(cg[ETA_T], c1, fr2_V2)
    fr2_E2 = _select(cg[ETA_T], One, fr2_E2)
    A_c = _select(cg[ETA_T], SA, A_c)
    B_c = _select(cg[ETA_T], SB, B_c)
    C_c = _select(cg[ETA_T], Zero, C_c)
    F_c = _select(cg[ETA_T], Zero, F_c)
    E_c = _select(cg[ETA_T], Zero, E_c)
    D_c = _select(cg[ETA_T], c2, D_c)
    # ETA_S: s_ty in (A,B); lam_is_t=frV1, caller=frV2. Pi? else ST_ES.
    et_sk = fetch_by_position([k_], SA)[0]
    et_kpi = _kind_eq_raw(et_sk, K_PI, One)
    et_tpc = _kind_eq_raw(et_sk, T_PI_CLO, One)
    et_ispi = et_kpi + et_tpc
    et_sfall = reglu(cg[ETA_S], One - et_ispi)
    et_spi = reglu(cg[ETA_S], et_ispi)
    et_dompos = _fv0(SA)
    et_domenv = _select(et_kpi, SB, fetch_by_position([x_], SA)[0])
    et_fpos = _select(frV1, ooV1, ooE2)                     # lam side
    et_fdom = _fv0(et_fpos)
    et_fdomenv = _select(frV1, ooX, ooF2)
    # not Pi → ST_ES
    fr1_F2 = _select(et_sfall, Expression({_one_dim: ST_ES}), fr1_F2)
    C_c = _select(et_sfall, Zero, C_c)
    F_c = _select(et_sfall, Zero, F_c)
    E_c = _select(et_sfall, One, E_c)
    D_c = _select(et_sfall, c1, D_c)
    # Pi → defeq(lam dom, dom_s) with ETA_DOM continuation (carries lam_is_t,
    # dom_s, caller).
    fr1_V1 = _select(et_spi, frV1, fr1_V1)                  # lam_is_t
    fr1_X = _select(et_spi, et_dompos, fr1_X)
    fr1_E2 = _select(et_spi, et_domenv, fr1_E2)
    fr1_F2 = _select(et_spi, Expression({_one_dim: ETA_DOM}), fr1_F2)
    fr2_task = _select(et_spi, Expression({_one_dim: TASK_DEFEQ}), fr2_task)
    fr2_V1 = _select(et_spi, et_fdom, fr2_V1)
    fr2_X = _select(et_spi, et_fdomenv, fr2_X)
    fr2_E2 = _select(et_spi, et_dompos, fr2_E2)
    fr2_F2 = _select(et_spi, et_domenv, fr2_F2)
    fr2_V2 = _select(et_spi, c1, fr2_V2)
    A_c = _select(et_spi, et_fdom, A_c)
    B_c = _select(et_spi, et_fdomenv, B_c)
    C_c = _select(et_spi, Zero, C_c)
    F_c = _select(et_spi, Zero, F_c)
    E_c = _select(et_spi, Zero, E_c)
    D_c = _select(et_spi, c2, D_c)
    # ETA_DOM: dom verdict in A; lam_is_t=frV1, dom_s=(frX,frE2), caller=frV2.
    # Fail → verdict False to caller. OK → build M,L,bvar0 (one step) then
    # M2,bvar1 (ETA_LINK) then app,defeq-bodies (ETA_LNK2).
    et_domfail = reglu(cg[ETA_DOM], One - _geq_expr(SA, One))
    et_domok = cg[ETA_DOM] - et_domfail
    A_c = _select(et_domfail, Zero, A_c)
    B_c = _select(et_domfail, Zero, B_c)
    E_c = _select(et_domfail, One, E_c)
    D_c = _select(et_domfail, frV2, D_c)
    et_fenv = _select(frV1, ooX, ooF2)
    et_gpos2 = _select(frV1, ooE2, ooV1)
    et_genv2 = _select(frV1, ooF2, ooX)
    # bvar0 raw (K_BVAR, index 0); lam_is_t stashed in its X (unused field).
    raw_K_c = _select(et_domok, Expression({_one_dim: K_BVAR}), raw_K_c)
    raw_V0_c = _select(et_domok, Zero, raw_V0_c)
    raw_X_c = _select(et_domok, frV1, raw_X_c)
    em_raw_c = em_raw_c + et_domok
    # M = link(dom_s, f_env, flag=1, bid=M)
    link1_V0 = _select(et_domok, frX, link1_V0)
    link1_D = _select(et_domok, ldepth(et_fenv), link1_D)
    link1_P = _select(et_domok, et_fenv, link1_P)
    link1_E = _select(et_domok, frE2, link1_E)
    link1_F = _select(et_domok, One, link1_F)
    link1_F2 = _select(et_domok, c2, link1_F2)             # bid = M pos
    em_link1_c = em_link1_c + et_domok
    # L = link(g, f_env, flag=0)
    link2_V0 = _select(et_domok, et_gpos2, link2_V0)
    link2_D = _select(et_domok, ldepth(et_fenv), link2_D)
    link2_P = _select(et_domok, et_fenv, link2_P)
    link2_E = _select(et_domok, et_genv2, link2_E)
    link2_F = _select(et_domok, Zero, link2_F)
    em_link2_c = em_link2_c + et_domok
    # ST(ETA_LINK) at c4: M=c2, L=c3, bvar0=c1, caller=frV2.
    fr1_V1 = _select(et_domok, c2, fr1_V1)
    fr1_X = _select(et_domok, c3, fr1_X)
    fr1_E2 = _select(et_domok, c1, fr1_E2)
    fr1_F2 = _select(et_domok, Expression({_one_dim: ETA_LINK}), fr1_F2)
    C_c = _select(et_domok, Zero, C_c)
    F_c = _select(et_domok, Zero, F_c)
    E_c = _select(et_domok, One, E_c)
    D_c = _select(et_domok, c4, D_c)
    # ETA_LINK: M=frV1, L=frX, bvar0=frE2, caller=frV2. Emit bvar1 + M2.
    et_Mpos = frV1
    et_Lpos = frX
    et_Mdom = _fv0(et_Mpos)
    et_Mdomenv = fetch_by_position([x_], et_Mpos)[0]
    raw_K_c = _select(cg[ETA_LINK], Expression({_one_dim: K_BVAR}), raw_K_c)
    raw_V0_c = _select(cg[ETA_LINK], One, raw_V0_c)        # index 1
    raw_X_c = _select(cg[ETA_LINK], et_Mpos, raw_X_c)      # stash M pos
    em_raw_c = em_raw_c + cg[ETA_LINK]
    link1_V0 = _select(cg[ETA_LINK], et_Mdom, link1_V0)
    link1_D = _select(cg[ETA_LINK], ldepth(et_Lpos), link1_D)
    link1_P = _select(cg[ETA_LINK], et_Lpos, link1_P)
    link1_E = _select(cg[ETA_LINK], et_Mdomenv, link1_E)
    link1_F = _select(cg[ETA_LINK], One, link1_F)
    link1_F2 = _select(cg[ETA_LINK], et_Mpos, link1_F2)    # bid = M
    em_link1_c = em_link1_c + cg[ETA_LINK]
    # ST(ETA_LNK2) at c3: bvar0=frE2, bvar1=c1, M2=c2, caller=frV2.
    fr1_V1 = _select(cg[ETA_LINK], frE2, fr1_V1)
    fr1_X = _select(cg[ETA_LINK], c1, fr1_X)
    fr1_E2 = _select(cg[ETA_LINK], c2, fr1_E2)
    fr1_F2 = _select(cg[ETA_LINK], Expression({_one_dim: ETA_LNK2}), fr1_F2)
    C_c = _select(cg[ETA_LINK], Zero, C_c)
    F_c = _select(cg[ETA_LINK], Zero, F_c)
    E_c = _select(cg[ETA_LINK], One, E_c)
    D_c = _select(cg[ETA_LINK], c3, D_c)
    # ETA_LNK2: bvar0=frV1, bvar1=frX, M2=frE2, caller=frV2. Emit app + DEFEQ.
    et_lam2 = fetch_by_position([x_], frV1)[0]             # lam_is_t (stash)
    et_M2 = fetch_by_position([x_], frX)[0]                 # M pos (stash)
    et_fbody = fetch_by_position([v1_], _select(et_lam2, ooV1, ooE2))[0]
    raw_K_c = _select(cg[ETA_LNK2], Expression({_one_dim: K_APP}), raw_K_c)
    raw_V0_c = _select(cg[ETA_LNK2], frX, raw_V0_c)        # bvar1
    raw_V1_c = _select(cg[ETA_LNK2], frV1, raw_V1_c)       # bvar0
    em_raw_c = em_raw_c + cg[ETA_LNK2]
    fr1_task = _select(cg[ETA_LNK2], Expression({_one_dim: TASK_DEFEQ}), fr1_task)
    fr1_V1 = _select(cg[ETA_LNK2], et_fbody, fr1_V1)
    fr1_X = _select(cg[ETA_LNK2], et_M2, fr1_X)
    fr1_E2 = _select(cg[ETA_LNK2], c1, fr1_E2)             # app pos
    fr1_F2 = _select(cg[ETA_LNK2], frE2, fr1_F2)           # M2 pos
    fr1_V2 = _select(cg[ETA_LNK2], frV2, fr1_V2)
    A_c = _select(cg[ETA_LNK2], et_fbody, A_c)
    B_c = _select(cg[ETA_LNK2], et_M2, B_c)
    C_c = _select(cg[ETA_LNK2], Zero, C_c)
    F_c = _select(cg[ETA_LNK2], Zero, F_c)
    E_c = _select(cg[ETA_LNK2], Zero, E_c)
    D_c = _select(cg[ETA_LNK2], c2, D_c)
    # ── Phase 5 M3 Mechanism D: structural eta (kernel try_eta_struct_core) ─
    # Reached from ST_ET when neither side is a lambda (et_fall). One side is a
    # fully-applied non-rec ctor spine (the only toy structure: P2.mk, 0 params,
    # 2 fields); the other is the projected side t. t ≡ ctor a1..an iff their
    # types are defeq and proj(t,i) ≡ args[nfields-1-i] fieldwise (args are
    # outermost-first). We orient so the ctor side is "s"; if neither side is a
    # full ctor spine → verdict False (matches ref_vm: both orientations None).
    def es_full_ctor(p):
        k = fetch_by_position([k_], p)[0]
        inner = _fv0(p)
        ik = fetch_by_position([k_], inner)[0]
        ctor = _fv0(inner)
        ck = fetch_by_position([k_], ctor)[0]
        ccid = _fv0(ctor)
        return reglu(reglu(reglu(_kind_eq_raw(k, K_APP, One),
                                 _kind_eq_raw(ik, K_APP, One)),
                           _kind_eq_raw(ck, K_CONST, One)),
                     _is_struct_ctor2(ccid))
    es_sctor = es_full_ctor(ooE2)
    es_tctor = es_full_ctor(ooV1)
    es_app = reglu(cg[ST_ES], es_sctor + es_tctor)
    # ── WP5-E3b: kernel try_string_lit_expansion (K/type_checker.cpp:1143-1156)
    # — runs AFTER try_eta_struct (es_app) and BEFORE unit_like (es_no's ST_UL
    # fallthrough).  core(t,s): is_string_lit(t) && is_app(s) &&
    # app_fn(s) == Const("String.ofList") (NO level args — g_string_mk is the
    # bare const, and Expr equality compares them) → the arm's verdict IS
    # final: is_def_eq_core(whnf(string_lit_to_constructor(t)), s).  Both
    # orientations are tried (try_string_lit_expansion, :1152-1156).  In a
    # real environment ofList is a delta-able def, so a well-formed s has
    # already unfolded and this arm is effectively dead — the kernel agrees;
    # the arm only fires when "String.ofList" carries no value (the kernel
    # gets stuck on it identically).  Faithful implementation, documented in
    # VM_SPEC §14.5.
    oo_lit_p = lambda p: reglu(reglu(_kind_eq_raw(fetch_by_position([k_], p)[0],
                                                  K_LIT, One),
                                     _eq_expr(fetch_by_position([v1_], p)[0],
                                              One)),
                               _geq_expr(fetch_by_position([x_], p)[0], One))
    oo_k = lambda p: fetch_by_position([k_], p)[0]
    # the s side: App(...Const("String.ofList")...) with NO level args.
    # _head_of walks the V0 (fn) chain to the spine head position.
    def _oo_oflist(p):
        h = _head_of(p, SPINE_MAX)
        return reglu(_kind_eq_raw(oo_k(p), K_APP, One),
                     reglu(_kind_eq_raw(oo_k(h), K_CONST, One),
                     reglu(_eq_expr(_fv0(h), _OFLIST_CID),
                     reglu(_eq_expr(fetch_by_position([v1_], h)[0], Zero),
                           _OFLIST_OK))))
    es_lit_t = oo_lit_p(ooV1)
    es_lit_s = oo_lit_p(ooE2)
    es_str_ts = reglu(es_lit_t, _oo_oflist(ooE2))
    es_str_st = reglu(es_lit_s, _oo_oflist(ooV1))
    es_str = reglu(cg[ST_ES], es_str_ts + es_str_st)
    es_no = reglu(cg[ST_ES],
                  One - es_sctor - es_tctor - es_str_ts - es_str_st)
    es_ctor_pos = _select(es_sctor, ooE2, ooV1)
    es_ctor_env = _select(es_sctor, ooF2, ooX)
    es_t_pos = _select(es_sctor, ooV1, ooE2)
    es_t_env = _select(es_sctor, ooX, ooF2)
    es_inner = fetch_by_position([v1_], _fv0(es_ctor_pos))[0]
    es_outer = fetch_by_position([v1_], es_ctor_pos)[0]
    # the matched ctor's cid (ctor spine head), for metadata-derived spec:
    # its inductive cid (ES_T's Const(s_ty)) and name nid (Proj sname).
    es_ccid = _fv0(_fv0(_fv0(es_ctor_pos)))
    # ST_ES applicable → infer the projected side t (ES_T carries orient).
    fr1_V1 = _select(es_app, es_sctor, fr1_V1)
    fr1_F2 = _select(es_app, Expression({_one_dim: ES_T}), fr1_F2)
    fr2_task = _select(es_app, Expression({_one_dim: TASK_INFER}), fr2_task)
    fr2_V1 = _select(es_app, es_t_pos, fr2_V1)
    fr2_X = _select(es_app, es_t_env, fr2_X)
    fr2_V2 = _select(es_app, c1, fr2_V2)
    fr2_E2 = _select(es_app, One, fr2_E2)
    A_c = _select(es_app, es_t_pos, A_c)
    B_c = _select(es_app, es_t_env, B_c)
    C_c = _select(es_app, Zero, C_c)
    F_c = _select(es_app, Zero, F_c)
    E_c = _select(es_app, Zero, E_c)
    D_c = _select(es_app, c2, D_c)
    # ST_ES not applicable → continue the stuck chain with unit_like (ST_UL):
    # infer nt's type, whnf it, and check the head is the 0-field structure
    # UnitT (kernel is_def_eq_unit_like, the last rule before false). Focus =
    # nt (from the buried caller); E=1 dispatches ST_UL next.
    fr1_F2 = _select(es_no, Expression({_one_dim: ST_UL}), fr1_F2)
    A_c = _select(es_no, ooV1, A_c)               # nt pos
    B_c = _select(es_no, ooX, B_c)                # nt env
    C_c = _select(es_no, Zero, C_c)
    F_c = _select(es_no, Zero, F_c)
    E_c = _select(es_no, One, E_c)
    D_c = _select(es_no, c1, D_c)
    # es_str: replace the ST frame with a DEFEQ frame for the FINAL verdict
    # `is_def_eq_core(whnf(expansion), ofList-app)` (the kernel matched arm
    # returns its verdict; the caller (V2) stays the buried DEFEQ frame so
    # the verdict propagates exactly like every other chain outcome).
    es_lit_pos = _select(es_str_ts, ooV1, ooE2)
    es_lit_env = _select(es_str_ts, ooX, ooF2)
    es_of_pos = _select(es_str_ts, ooE2, ooV1)
    es_of_env = _select(es_str_ts, ooF2, ooX)
    es_exp = fetch_by_position([x_], es_lit_pos)[0]
    fr1_task = _select(es_str, Expression({_one_dim: TASK_DEFEQ}), fr1_task)
    fr1_V1 = _select(es_str, es_exp, fr1_V1)
    fr1_X = _select(es_str, es_lit_env, fr1_X)
    fr1_E2 = _select(es_str, es_of_pos, fr1_E2)
    fr1_F2 = _select(es_str, es_of_env, fr1_F2)
    fr1_V2 = _select(es_str, frV2, fr1_V2)
    A_c = _select(es_str, es_exp, A_c)
    B_c = _select(es_str, es_lit_env, B_c)
    C_c = _select(es_str, Zero, C_c)
    F_c = _select(es_str, Zero, F_c)
    E_c = _select(es_str, Zero, E_c)
    D_c = _select(es_str, c1, D_c)
    # ES_T: t_ty in (A,B); orient=frV1, caller=frV2. The ctor side is a fully
    # applied 0-param structure, so s_ty is statically Const(ind) — kept even
    # after P6.2 gave INFER a Proj rule (IP_TY/IP_PEEL): the static shortcut is
    # equivalent for P2 and cheaper. Emit Const(CID_P2) raw + defeq(t_ty, s_ty)
    # (ES_DOM).
    raw_K_c = _select(cg[ES_T], Expression({_one_dim: K_CONST}), raw_K_c)
    raw_V0_c = _select(cg[ES_T], _struct_ind(es_ccid), raw_V0_c)
    em_raw_c = em_raw_c + cg[ES_T]
    fr1_V1 = _select(cg[ES_T], frV1, fr1_V1)            # orient
    fr1_F2 = _select(cg[ES_T], Expression({_one_dim: ES_DOM}), fr1_F2)
    fr2_task = _select(cg[ES_T], Expression({_one_dim: TASK_DEFEQ}), fr2_task)
    fr2_V1 = _select(cg[ES_T], SA, fr2_V1)              # t_ty pos
    fr2_X = _select(cg[ES_T], SB, fr2_X)                # t_ty env
    fr2_E2 = _select(cg[ES_T], c1, fr2_E2)              # s_ty = Const(P2)
    fr2_F2 = _select(cg[ES_T], Zero, fr2_F2)
    fr2_V2 = _select(cg[ES_T], c2, fr2_V2)
    A_c = _select(cg[ES_T], SA, A_c)
    B_c = _select(cg[ES_T], SB, B_c)
    C_c = _select(cg[ES_T], Zero, C_c)
    F_c = _select(cg[ES_T], Zero, F_c)
    E_c = _select(cg[ES_T], Zero, E_c)
    D_c = _select(cg[ES_T], c3, D_c)
    # ES_DOM: type verdict in A. Fail → False. OK → field 0: build
    # Proj(nid,0,t) (raw c1) + ST(ES_NEXT,X=0) (c2) + defeq(proj, inner) (c3).
    es_domfail = reglu(cg[ES_DOM], One - _geq_expr(SA, One))
    es_domok = cg[ES_DOM] - es_domfail
    A_c = _select(es_domfail, Zero, A_c)
    B_c = _select(es_domfail, Zero, B_c)
    C_c = _select(es_domfail, Zero, C_c)
    F_c = _select(es_domfail, Zero, F_c)
    E_c = _select(es_domfail, One, E_c)
    D_c = _select(es_domfail, frV2, D_c)
    raw_K_c = _select(es_domok, Expression({_one_dim: K_PROJ}), raw_K_c)
    raw_V0_c = _select(es_domok, _struct_nid(es_ccid), raw_V0_c)
    raw_V1_c = _select(es_domok, Zero, raw_V1_c)
    raw_X_c = _select(es_domok, es_t_pos, raw_X_c)
    em_raw_c = em_raw_c + es_domok
    fr1_task = _select(es_domok, Expression({_one_dim: TASK_ST}), fr1_task)
    fr1_V1 = _select(es_domok, frV1, fr1_V1)
    fr1_X = _select(es_domok, Zero, fr1_X)          # field idx 0
    fr1_V2 = _select(es_domok, frV2, fr1_V2)
    fr1_F2 = _select(es_domok, Expression({_one_dim: ES_NEXT}), fr1_F2)
    fr2_task = _select(es_domok, Expression({_one_dim: TASK_DEFEQ}), fr2_task)
    fr2_V1 = _select(es_domok, c1, fr2_V1)
    fr2_X = _select(es_domok, es_t_env, fr2_X)
    fr2_E2 = _select(es_domok, es_inner, fr2_E2)
    fr2_F2 = _select(es_domok, es_ctor_env, fr2_F2)
    fr2_V2 = _select(es_domok, c2, fr2_V2)
    A_c = _select(es_domok, c1, A_c)
    B_c = _select(es_domok, es_t_env, B_c)
    C_c = _select(es_domok, Zero, C_c)
    F_c = _select(es_domok, Zero, F_c)
    E_c = _select(es_domok, Zero, E_c)
    D_c = _select(es_domok, c3, D_c)
    # ES_NEXT: field verdict in A, idx in frX. Fail → False. idx0 → field 1
    # (Proj(nid,1,t) vs outer). idx1 → True.
    es_nextfail = reglu(cg[ES_NEXT], One - _geq_expr(SA, One))
    es_next0 = reglu(cg[ES_NEXT], reglu(_geq_expr(SA, One), One - _geq_expr(frX, One)))
    es_next1 = reglu(cg[ES_NEXT], reglu(_geq_expr(SA, One), _geq_expr(frX, One)))
    A_c = _select(es_nextfail, Zero, A_c)
    B_c = _select(es_nextfail, Zero, B_c)
    C_c = _select(es_nextfail, Zero, C_c)
    F_c = _select(es_nextfail, Zero, F_c)
    E_c = _select(es_nextfail, One, E_c)
    D_c = _select(es_nextfail, frV2, D_c)
    raw_K_c = _select(es_next0, Expression({_one_dim: K_PROJ}), raw_K_c)
    raw_V0_c = _select(es_next0, _struct_nid(es_ccid), raw_V0_c)
    raw_V1_c = _select(es_next0, One, raw_V1_c)
    raw_X_c = _select(es_next0, es_t_pos, raw_X_c)
    em_raw_c = em_raw_c + es_next0
    fr1_task = _select(es_next0, Expression({_one_dim: TASK_ST}), fr1_task)
    fr1_V1 = _select(es_next0, frV1, fr1_V1)
    fr1_X = _select(es_next0, One, fr1_X)           # field idx 1
    fr1_V2 = _select(es_next0, frV2, fr1_V2)
    fr1_F2 = _select(es_next0, Expression({_one_dim: ES_NEXT}), fr1_F2)
    fr2_task = _select(es_next0, Expression({_one_dim: TASK_DEFEQ}), fr2_task)
    fr2_V1 = _select(es_next0, c1, fr2_V1)
    fr2_X = _select(es_next0, es_t_env, fr2_X)
    fr2_E2 = _select(es_next0, es_outer, fr2_E2)
    fr2_F2 = _select(es_next0, es_ctor_env, fr2_F2)
    fr2_V2 = _select(es_next0, c2, fr2_V2)
    A_c = _select(es_next0, c1, A_c)
    B_c = _select(es_next0, es_t_env, B_c)
    C_c = _select(es_next0, Zero, C_c)
    F_c = _select(es_next0, Zero, F_c)
    E_c = _select(es_next0, Zero, E_c)
    D_c = _select(es_next0, c3, D_c)
    A_c = _select(es_next1, One, A_c)
    B_c = _select(es_next1, Zero, B_c)
    C_c = _select(es_next1, Zero, C_c)
    F_c = _select(es_next1, Zero, F_c)
    E_c = _select(es_next1, One, E_c)
    D_c = _select(es_next1, frV2, D_c)

    # I_PROJ (M3): the proj child whnf'd to (A,B)=(cpos,cenv); the proj token
    # is at frV1 (idx in its V1). If cpos is a full P2.mk spine, deliver the
    # projected field under cenv; else re-stick the proj token under its own
    # env (frX). Either way the result goes to frV2 = the frame the proj's
    # ST was pushed over (P7.5c-2: the old top, NOT its caller — the old
    # frV2-bypass short-circuited TASK_WHNF frames but also skipped the
    # NAT/ST arg frames of an in-flight nat-op argument, stranding the arg2
    # ST; a TASK frame popped by pop_task gives the same "proj ends the
    # whnf" effect without stranding).
    pr_field = _select(_eq_expr(pr_idx, Zero), pr_iV1, pr_oV1)
    # P7.5c-M5: restore the enclosing pend saved in frE2 by proj_setup.  A
    # projection in FUNCTION position — `(P2.fst ih) k` in Nat.choose — must
    # apply its pending args after reducing to the field: the field may be a
    # Lam (beta), a Const/App/BVar (reduce then apply), or a stuck head (form
    # a stuck App spine).  All of those are the ordinary main-mode app
    # machinery, so with a saved pend we continue with E=0.  With no pend the
    # old final-vs-reduce contract stands (frE2 is 0 for every other ST
    # frame's continuation branch here, so this is inert elsewhere).
    pr_pend = frE2
    A_c = _select(cg[I_PROJ], _select(pr_full, pr_field, frV1), A_c)
    B_c = _select(cg[I_PROJ], _select(pr_full, SB, frX), B_c)
    C_c = _select(cg[I_PROJ], pr_pend, C_c)
    F_c = _select(cg[I_PROJ], Zero, F_c)
    # P7.5c-2: the delivery flag E=1 means "FINAL result — do not reduce
    # further" (pop_task / rec_sd / stuck_nat are keyed on it).  A REDUCIBLE
    # field (App/Let/MData/Proj/BVar/value-const) must continue in main mode
    # with E=0: the kernel whnf does NOT end at a projection redex —
    # whnf_core re-enters on the extracted field (K/type_checker.cpp:501-506
    # `r = whnf_core(*m, ...)`) and the whnf loop keeps unfolding the field
    # head (K/type_checker.cpp:759-767 `unfold_definition(t1)`); the frozen
    # reference machine says the same at ref_vm.py:281-296 (K_PROJ `continue`
    # — "returning it raw would end whnf in a non-normal form").  The
    # original P7.5c-2 claim that "a proj reduction ends the whnf" held E=1
    # for TASK_WHNF callers; card 009/F7 disproved that against the 4.33.1
    # binary: `Nat.brecOn mot 2 F2s =?= 3` (oracle True) dead-ended at the
    # raw field `F2s 2 <below-shadow>` — the DEFEQ soft-whnf (D_SW2/D_SW3)
    # saw an identity, entered the stuck chain, and the unit_like arm
    # compared the field's Pi type against Nat, committing a false verdict
    # the kernel never reaches.  D_SW2/D_SW3 need only the STUCK cases to
    # arrive E=1 (restick `Proj(stuck)` / stuck field below), and those go
    # through `One - pr_f_red` unchanged; a genuinely reduced whnf reaching
    # a stuck head is delivered by whnf_deliver (complete under the WHNF
    # frame, E=1) exactly as before.  E=1 also stays for the no-field
    # restick (`One - pr_full`) and for an already-normal field head (Lam /
    # Pi / Sort / Lit / opaque const — pr_f_red = 0 there, so main mode
    # would halt anyway).
    pr_fK = fetch_by_position([k_], pr_field)[0]
    pr_fV0 = _fv0(pr_field)
    pr_fV2 = fetch_by_position([v2_], pr_fV0 + One)[0]  # const field: ENV.V2
    pr_f_stuck = (_kind_eq_raw(pr_fK, K_SORT, One)
                  + _kind_eq_raw(pr_fK, K_FVAR, One)
                  + _kind_eq_raw(pr_fK, K_MVAR, One)
                  + _kind_eq_raw(pr_fK, K_LIT, One)
                  + _kind_eq_raw(pr_fK, K_PI, One)
                  + _kind_eq_raw(pr_fK, T_PI_CLO, One)
                  + _kind_eq_raw(pr_fK, K_LAM, One)
                  + reglu(_kind_eq_raw(pr_fK, K_CONST, One),
                          One - _geq_expr(pr_fV2, One)))
    pr_f_red = One - pr_f_stuck
    E_c = _select(cg[I_PROJ],
                  _select(_geq_expr(pr_pend, One), Zero,
                          _select(pr_full,
                                  _select(pr_f_red, Zero, One),
                                  One)),
                  E_c)
    D_c = _select(cg[I_PROJ], frV2, D_c)
    # ── WP5-E5 (K/type_checker.cpp:421-422) ─────────────────────────────────
    # reduce_proj_core converts a STRING LITERAL child first:
    #   if (is_string_lit(c)) c = whnf(string_lit_to_constructor(c));
    # then the field is read off the resulting constructor application.  The
    # graph replays exactly that: when the whnf'd child (A,B) is a literal
    # with an expansion (K_LIT.V1==1, X>=1), push a fresh
    # [ST(continuation=I_PROJ, proj token, original env/pend/caller),
    #  WHNF(expansion root)] pair (the same shape proj_setup used for the
    # original child) and whnf the shadow expansion.  Its delivery re-enters
    # I_PROJ with the constructor application in hand, where the EXISTING
    # pr_full/_is_struct_ctor2 machinery (String is a 0-param 2-field
    # structure) extracts the field with no further changes.  X==0 (declined
    # expansion) keeps the old re-stick behaviour.
    pr_str = reglu(cg[I_PROJ],
                   reglu(reglu(_kind_eq_raw(fK, K_LIT, One),
                               _eq_expr(fV1, One)), _geq_expr(fX, One)))
    fr1_task = _select(pr_str, Expression({_one_dim: TASK_ST}), fr1_task)
    fr1_V1 = _select(pr_str, frV1, fr1_V1)          # the proj token
    fr1_X = _select(pr_str, frX, fr1_X)             # proj's original env
    fr1_V2 = _select(pr_str, frV2, fr1_V2)          # the delivery caller
    fr1_E2 = _select(pr_str, frE2, fr1_E2)          # the enclosing pend
    fr1_F2 = _select(pr_str, Expression({_one_dim: I_PROJ}), fr1_F2)
    fr2_task = _select(pr_str, Expression({_one_dim: TASK_WHNF}), fr2_task)
    fr2_V1 = _select(pr_str, fX, fr2_V1)           # the expansion root
    fr2_X = _select(pr_str, SB, fr2_X)             # the literal's env
    fr2_V2 = _select(pr_str, c1, fr2_V2)
    A_c = _select(pr_str, fX, A_c)
    B_c = _select(pr_str, SB, B_c)
    C_c = _select(pr_str, Zero, C_c)
    F_c = _select(pr_str, Zero, F_c)
    E_c = _select(pr_str, Zero, E_c)
    D_c = _select(pr_str, c2, D_c)

    # IP_TY (P6.2): child type in (A,B); whnf it (hard), then IP_PEEL.
    # A=0 = the child infer failed soft → cascade the marker.
    i_pty_fail = reglu(cg[IP_TY], One - _geq_expr(SA, One))
    fr1_V1 = _select(cg[IP_TY], frV1, fr1_V1)       # nid (kept for the check)
    fr1_X = _select(cg[IP_TY], frX, fr1_X)          # field idx
    fr1_F2 = _select(cg[IP_TY], Expression({_one_dim: IP_PEEL}), fr1_F2)
    fr2_task = _select(cg[IP_TY], Expression({_one_dim: TASK_WHNF}), fr2_task)
    fr2_V1 = _select(cg[IP_TY], SA, fr2_V1)         # type pos
    fr2_X = _select(cg[IP_TY], SB, fr2_X)           # type env
    fr2_V2 = _select(cg[IP_TY], c1, fr2_V2)
    A_c = _select(cg[IP_TY], SA, A_c)
    B_c = _select(cg[IP_TY], SB, B_c)
    C_c = _select(cg[IP_TY], Zero, C_c)
    F_c = _select(cg[IP_TY], Zero, F_c)
    E_c = _select(cg[IP_TY], Zero, E_c)
    D_c = _select(cg[IP_TY], c2, D_c)
    A_c = _select(i_pty_fail, Zero, A_c)
    B_c = _select(i_pty_fail, Zero, B_c)
    C_c = _select(i_pty_fail, Zero, C_c)
    F_c = _select(i_pty_fail, Zero, F_c)
    E_c = _select(i_pty_fail, One, E_c)
    D_c = _select(i_pty_fail, fetch_by_position([v2_], frV2)[0], D_c)

    # IP_PEEL (P6.2): phase 0 (frE2=0) checks the whnf'd child type is a
    # non-recursive structure inductive (metadata: T_ENV_INDVAL + INDEXTRA) whose
    # name nid matches the projection's sname, then re-enters with focus = the
    # ctor type root (ENV_HDR(CID_P2MK).V1 = Pi spine); phase 1 peels frX Pi's
    # and delivers the field domain (closed tree → env 0). Any mismatch →
    # ERR_TYPE (kernel invalid_proj). Non-dependent fields: no instantiation.
    ip_cid = _fv0(SA)        # child type cid
    ip_p0 = reglu(cg[IP_PEEL], One - _geq_expr(frE2, One))
    ip_ok = reglu(ip_p0, reglu(_kind_eq_raw(fK, K_CONST, One),
              reglu(_is_struct_induct(ip_cid),
                    _eq_expr(_induct_nid(ip_cid), frV1))))
    ip_setup = ip_ok
    ip_p1 = reglu(cg[IP_PEEL], _geq_expr(frE2, One))
    ip_pi = reglu(ip_p1, _kind_eq_raw(fK, K_PI, One))
    ip_deliver = reglu(ip_pi, One - _geq_expr(frX, One))
    ip_more = reglu(ip_pi, _geq_expr(frX, One))
    ip_peelbad = reglu(ip_p1, One - _kind_eq_raw(fK, K_PI, One))
    # infer_proj raise (kernel invalid_proj): hard = ERR_TYPE reject, soft
    # (task F2=1; ref _proof_irrel catches ERR_TYPE from infer(t)) = deliver
    # the A=0 marker to the task's consumer instead.
    ip_bad = (ip_p0 - ip_ok) + ip_peelbad
    ip_soft = soft_flag
    ip_soft_fail = reglu(ip_bad, _geq_expr(ip_soft, One))
    rej_c = rej_c + reglu(ip_bad, One - _geq_expr(ip_soft, One))
    rej_code_c = rej_code_c + reglu(ip_bad, One - _geq_expr(ip_soft, One))
    mk_ty = fetch_by_position([v1_],
                              Expression({_one_dim: CID_P2MK + 1}))[0]
    fr1_E2 = _select(ip_setup, One, fr1_E2)
    fr1_V1 = _select(ip_setup, frV1, fr1_V1)
    fr1_X = _select(ip_setup, frX, fr1_X)
    fr1_F2 = _select(ip_setup, Expression({_one_dim: IP_PEEL}), fr1_F2)
    A_c = _select(ip_setup, mk_ty, A_c)
    B_c = _select(ip_setup, Zero, B_c)
    C_c = _select(ip_setup, Zero, C_c)
    F_c = _select(ip_setup, Zero, F_c)
    E_c = _select(ip_setup, One, E_c)
    D_c = _select(ip_setup, c1, D_c)
    fr1_E2 = _select(ip_more, One, fr1_E2)
    fr1_V1 = _select(ip_more, frV1, fr1_V1)
    fr1_X = _select(ip_more, frX - One, fr1_X)
    fr1_F2 = _select(ip_more, Expression({_one_dim: IP_PEEL}), fr1_F2)
    A_c = _select(ip_more, fV1, A_c)                # Pi body
    B_c = _select(ip_more, Zero, B_c)
    C_c = _select(ip_more, Zero, C_c)
    F_c = _select(ip_more, Zero, F_c)
    E_c = _select(ip_more, One, E_c)
    D_c = _select(ip_more, c1, D_c)
    A_c = _select(ip_deliver, fV0, A_c)             # field domain
    B_c = _select(ip_deliver, Zero, B_c)
    C_c = _select(ip_deliver, Zero, C_c)
    F_c = _select(ip_deliver, Zero, F_c)
    E_c = _select(ip_deliver, One, E_c)
    D_c = _select(ip_deliver, frV2, D_c)
    # soft-infer cascade for the ip_* raises (overrides the phase payloads).
    A_c = _select(ip_soft_fail, Zero, A_c)
    B_c = _select(ip_soft_fail, Zero, B_c)
    C_c = _select(ip_soft_fail, Zero, C_c)
    F_c = _select(ip_soft_fail, Zero, F_c)
    E_c = _select(ip_soft_fail, One, E_c)
    D_c = _select(ip_soft_fail, fetch_by_position([v2_], frV2)[0], D_c)

    # ── Phase 7: unit_like chain (kernel is_def_eq_unit_like, L1159) ─────────
    # ST_ES declined → the last stuck-chain rule before false. infer nt →
    # t_ty; whnf t_ty → t_ty_n; if its head is Const(CID_UNITT) (the toy env's
    # only 0-field structure, in Type so proof-irrel already declined), infer
    # ns → s_ty and defeq(t_ty, s_ty); else verdict False to caller. t_ty is
    # carried in the frame's V1/X across UL_W → UL_CHK → UL_D (mirrors PI_*).
    # ST_UL: focus = nt (A,B). infer nt → t_ty (UL_W).
    fr1_F2 = _select(cg[ST_UL], Expression({_one_dim: UL_W}), fr1_F2)
    fr2_task = _select(cg[ST_UL], Expression({_one_dim: TASK_INFER}), fr2_task)
    fr2_V2 = _select(cg[ST_UL], c1, fr2_V2)
    fr2_E2 = _select(cg[ST_UL], One, fr2_E2)       # INFER phase P1
    # The result-type infer is best-effort: a walk-off/unsupported kind here
    # must DECLINE to the caller (A=0 → not unit-like → verdict False → the
    # stuck chain continues), mirroring ref defeq's infer wrapped in try/
    # except → decline (exactly how PI_T/PI_TY carry it at their launches).
    # E2 is only the INFER phase; the soft bit is F2 (soft_flag).
    fr2_F2 = _select(cg[ST_UL], One, fr2_F2)       # soft infer (try/except)
    C_c = _select(cg[ST_UL], Zero, C_c)
    F_c = _select(cg[ST_UL], Zero, F_c)
    E_c = _select(cg[ST_UL], Zero, E_c)
    D_c = _select(cg[ST_UL], c2, D_c)
    # UL_W: t_ty in (A,B). hard-whnf t_ty → t_ty_n (UL_CHK); carry t_ty in V1/X.
    # Soft-infer decline (t_ty = A=0 failure marker): do NOT whnf the sentinel
    # (it has no WHNF rule — the machine livelocks). Deliver the verdict-False
    # to the caller exactly as ul_no does — ref defeq's infer-raises → not
    # unit-like → continue the stuck chain (same try-scope as PI_TY's marker
    # handling).
    ul_w_ok = reglu(cg[UL_W], _geq_expr(SA, One))
    ul_w_fail = reglu(cg[UL_W], One - _geq_expr(SA, One))
    fr1_V1 = _select(ul_w_ok, SA, fr1_V1)          # t_ty pos
    fr1_X = _select(ul_w_ok, SB, fr1_X)            # t_ty env
    fr1_F2 = _select(ul_w_ok, Expression({_one_dim: UL_CHK}), fr1_F2)
    fr2_task = _select(ul_w_ok, Expression({_one_dim: TASK_WHNF}), fr2_task)
    fr2_V1 = _select(ul_w_ok, SA, fr2_V1)          # t_ty pos
    fr2_X = _select(ul_w_ok, SB, fr2_X)            # t_ty env
    fr2_V2 = _select(ul_w_ok, c1, fr2_V2)
    A_c = _select(ul_w_ok, SA, A_c)
    B_c = _select(ul_w_ok, SB, B_c)
    C_c = _select(ul_w_ok, Zero, C_c)
    F_c = _select(ul_w_ok, Zero, F_c)
    E_c = _select(ul_w_ok, Zero, E_c)
    D_c = _select(ul_w_ok, c2, D_c)
    A_c = _select(ul_w_fail, Zero, A_c)
    B_c = _select(ul_w_fail, Zero, B_c)
    C_c = _select(ul_w_fail, Zero, C_c)
    F_c = _select(ul_w_fail, Zero, F_c)
    E_c = _select(ul_w_fail, One, E_c)
    D_c = _select(ul_w_fail, frV2, D_c)
    # UL_CHK: t_ty_n in (A,B); t_ty in (frV1,frX). unit-like ⇔ head is
    # Const(CID_UNITT) (0-param structure → no arg peel, like the P2 path).
    ul_sk = fetch_by_position([k_], SA)[0]
    ul_cid = _fv0(SA)
    ul_yes = reglu(cg[UL_CHK], reglu(_kind_eq_raw(ul_sk, K_CONST, One),
                     _is_unit_induct(ul_cid)))
    ul_no = reglu(cg[UL_CHK], One - ul_yes)
    # unit-like → infer ns → s_ty (UL_D carries t_ty); focus = ns (from caller).
    fr1_V1 = _select(ul_yes, frV1, fr1_V1)         # t_ty pos
    fr1_X = _select(ul_yes, frX, fr1_X)            # t_ty env
    fr1_F2 = _select(ul_yes, Expression({_one_dim: UL_D}), fr1_F2)
    fr2_task = _select(ul_yes, Expression({_one_dim: TASK_INFER}), fr2_task)
    fr2_V1 = _select(ul_yes, ooE2, fr2_V1)         # ns pos
    fr2_X = _select(ul_yes, ooF2, fr2_X)           # ns env
    fr2_V2 = _select(ul_yes, c1, fr2_V2)
    fr2_E2 = _select(ul_yes, One, fr2_E2)          # INFER phase P1
    fr2_F2 = _select(ul_yes, One, fr2_F2)          # soft infer (same try scope)
    A_c = _select(ul_yes, ooE2, A_c)               # focus = ns
    B_c = _select(ul_yes, ooF2, B_c)
    C_c = _select(ul_yes, Zero, C_c)
    F_c = _select(ul_yes, Zero, F_c)
    E_c = _select(ul_yes, Zero, E_c)
    D_c = _select(ul_yes, c2, D_c)
    # not unit-like → verdict False to caller (the old ST_ES-terminal path).
    A_c = _select(ul_no, Zero, A_c)
    B_c = _select(ul_no, Zero, B_c)
    C_c = _select(ul_no, Zero, C_c)
    F_c = _select(ul_no, Zero, F_c)
    E_c = _select(ul_no, One, E_c)
    D_c = _select(ul_no, frV2, D_c)
    # UL_D: s_ty in (A,B); t_ty in (frV1,frX). defeq(t_ty, s_ty) → caller.
    # Soft-infer decline (s_ty = A=0 marker): not unit-like → verdict False to
    # caller (mirrors ul_no/UL_W decline; do not DEFEQ against the sentinel).
    ul_d_ok = reglu(cg[UL_D], _geq_expr(SA, One))
    ul_d_fail = reglu(cg[UL_D], One - _geq_expr(SA, One))
    fr1_task = _select(ul_d_ok, Expression({_one_dim: TASK_DEFEQ}), fr1_task)
    fr1_V1 = _select(ul_d_ok, frV1, fr1_V1)        # t_ty pos
    fr1_X = _select(ul_d_ok, frX, fr1_X)           # t_ty env
    fr1_E2 = _select(ul_d_ok, SA, fr1_E2)          # s_ty pos
    fr1_F2 = _select(ul_d_ok, SB, fr1_F2)          # s_ty env
    A_c = _select(ul_d_ok, frV1, A_c)              # focus = t_ty
    B_c = _select(ul_d_ok, frX, B_c)
    C_c = _select(ul_d_ok, Zero, C_c)
    F_c = _select(ul_d_ok, Zero, F_c)
    E_c = _select(ul_d_ok, Zero, E_c)
    D_c = _select(ul_d_ok, c1, D_c)
    A_c = _select(ul_d_fail, Zero, A_c)
    B_c = _select(ul_d_fail, Zero, B_c)
    C_c = _select(ul_d_fail, Zero, C_c)
    F_c = _select(ul_d_fail, Zero, F_c)
    E_c = _select(ul_d_fail, One, E_c)
    D_c = _select(ul_d_fail, frV2, D_c)

    # ── resume tree (E=0, D=ST with F2 = loop id) ───────────────────────────
    A_r = SA
    B_r = SB
    C_r = SC
    D_r = SD
    E_r = SE
    F_r = SF
    fr1_task_r, fr1_V1_r, fr1_V2_r, fr1_X_r, fr1_E2_r, fr1_F2_r = \
        Expression({_one_dim: TASK_ST}), Zero, frV2, Zero, Zero, frF2
    fr2_task_r, fr2_V1_r, fr2_V2_r, fr2_X_r, fr2_E2_r, fr2_F2_r = \
        Expression({_one_dim: TASK_WHNF}), SA, c1, SB, One, Zero
    em_raw_r = Zero
    raw_K_r, raw_V0_r, raw_V2_r, raw_X_r = Zero, Zero, Zero, Zero
    em_pend_r = Zero
    pend_V0_r, pend_prev_r, pend_env_r = Zero, Zero, Zero
    rej_r, rej_code_r = Zero, Zero

    # D_LITL / D_NCD: lockstep digit compare, t head = A, s head = ST.V1,
    # k = ST.E2. (ref: _chain_value equality — padding-safe via max bound)
    lit_loop = reglu(resume_mode, g[D_LITL] + g[D_NCD])
    n1l = _fv0(SA)
    n2l = _fv0(frV1)
    mxl = _select(_geq_expr(n1l, n2l), n1l, n2l)
    klt1 = _geq_expr(n1l, frE2 + One)                # k < n1
    klt2 = _geq_expr(n2l, frE2 + One)
    dig1 = _select(klt1, _fv0(SA + One * 2 + frE2 + frE2),
                   Zero)
    dig2 = _select(klt2, _fv0(frV1 + One * 2 + frE2 + frE2),
                   Zero)
    lit_mis = One - _eq_expr(dig1, dig2)
    lit_done = _geq_expr(frE2 + One, mxl)
    lit_fail = reglu(lit_loop, reglu(lit_mis, One))
    lit_ok = reglu(lit_loop, One - lit_mis)
    lit_true = reglu(lit_ok, lit_done)
    lit_cont = reglu(lit_ok, One - lit_done)
    # mismatch delivers verdict False (kernel is_def_eq returns false; the
    # compare loops are only reached from defeq paths)
    A_r = _select(lit_true + lit_fail, _select(lit_true, One, Zero), A_r)
    B_r = _select(lit_true + lit_fail, Zero, B_r)
    E_r = _select(lit_true + lit_fail, One, E_r)
    D_r = _select(lit_true + lit_fail, frV2, D_r)
    fr1_E2_r = _select(lit_cont, frE2 + One, fr1_E2_r)
    fr1_V1_r = _select(lit_cont, frV1, fr1_V1_r)
    D_r = _select(lit_cont, c1, D_r)

    # D_SP1: spine peel loop. A = t cur, E = s cur, B = t env, C/F = the two
    # pend chains, ST: V1 = s env, X = arity, V2 = caller.
    sp_loop = reglu(resume_mode, g[D_SP1])
    tk5 = fetch_by_position([k_], SA)[0]
    sk5 = fetch_by_position([k_], SE)[0]
    sp_ta = _kind_eq_raw(tk5, K_APP, One)
    sp_sa = _kind_eq_raw(sk5, K_APP, One)
    sp_both = reglu(sp_loop, reglu(sp_ta, sp_sa))
    sp_mis = reglu(reglu(sp_ta + sp_sa, One - reglu(sp_ta, sp_sa)), sp_loop)
    sp_end = reglu(sp_loop, One - sp_both - sp_mis)
    # mismatch delivers verdict False (kernel is_def_eq: a stuck app vs a
    # stuck non-app is simply not definitionally equal — no throw)
    A_r = _select(sp_mis, Zero, A_r)
    B_r = _select(sp_mis, Zero, B_r)
    E_r = _select(sp_mis, One, E_r)
    D_r = _select(sp_mis, frV2, D_r)
    # both-app step: peel one arg from each spine
    em_raw_r = sp_both
    raw_K_r = _select(sp_both, Expression({_one_dim: T_PEND}), raw_K_r)
    raw_V0_r = _select(sp_both, fetch_by_position([v1_], SE)[0], raw_V0_r)
    raw_V2_r = _select(sp_both, SF, raw_V2_r)
    raw_X_r = _select(sp_both, frV1, raw_X_r)        # s arg env
    em_pend_r = sp_both
    pend_V0_r = _select(sp_both, fV1, pend_V0_r)     # t arg pos
    pend_prev_r = _select(sp_both, SC, pend_prev_r)
    pend_env_r = _select(sp_both, SB, pend_env_r)
    A_r = _select(sp_both, fV0, A_r)                 # t fn
    E_r = _select(sp_both, _fv0(SE), E_r)  # s fn
    C_r = _select(sp_both, c2, C_r)
    F_r = _select(sp_both, c1, F_r)
    fr1_V1_r = _select(sp_both, frV1, fr1_V1_r)      # s env
    fr1_X_r = _select(sp_both, frX + One, fr1_X_r)   # arity + 1
    fr1_V2_r = _select(sp_both, frV2, fr1_V2_r)
    fr1_F2_r = _select(sp_both, Expression({_one_dim: D_SP1}), fr1_F2_r)
    D_r = _select(sp_both, c3, D_r)
    # peel end: compare the fn pair (args on the two pend chains)
    sp_fin2 = sp_end
    fr1_task_r = _select(sp_fin2, Expression({_one_dim: TASK_ST}), fr1_task_r)
    fr1_V1_r = _select(sp_fin2, SC, fr1_V1_r)        # t pend head
    fr1_X_r = _select(sp_fin2, SF, fr1_X_r)          # s pend head
    fr1_V2_r = _select(sp_fin2, frV2, fr1_V2_r)
    fr1_F2_r = _select(sp_fin2, Expression({_one_dim: D_SPA}), fr1_F2_r)
    fr2_task_r = _select(sp_fin2, Expression({_one_dim: TASK_DEFEQ}), fr2_task_r)
    fr2_V1_r = _select(sp_fin2, SA, fr2_V1_r)        # t fn
    fr2_X_r = _select(sp_fin2, SB, fr2_X_r)
    fr2_E2_r = _select(sp_fin2, SE, fr2_E2_r)        # s fn
    fr2_F2_r = _select(sp_fin2, frV1, fr2_F2_r)      # s env
    fr2_V2_r = _select(sp_fin2, c1, fr2_V2_r)
    C_r = _select(sp_fin2, Zero, C_r)
    F_r = _select(sp_fin2, Zero, F_r)
    E_r = _select(sp_fin2, Zero, E_r)
    D_r = _select(sp_fin2, c2, D_r)

    # D_SPA (delivery): verdict in A; restore the pend chains, compare the
    # next arg pair. ST: V1 = t pend head, X = s pend head, V2 = caller.
    spa_stop = reglu(cg[D_SPA], One - _geq_expr(SA, One))
    A_c = _select(spa_stop, Zero, A_c)
    B_c = _select(spa_stop, Zero, B_c)
    E_c = _select(spa_stop, One, E_c)
    D_c = _select(spa_stop, frV2, D_c)
    spa_tV0 = _fv0(frV1)
    spa_tX = fetch_by_position([x_], frV1)[0]
    spa_tV2 = fetch_by_position([v2_], frV1)[0]
    spa_sV0 = _fv0(frX)
    spa_sX = fetch_by_position([x_], frX)[0]
    spa_sV2 = fetch_by_position([v2_], frX)[0]
    spa_empty = reglu(cg[D_SPA], reglu(_geq_expr(SA, One),
                                      One - _geq_expr(frV1, One)))
    A_c = _select(spa_empty, One, A_c)
    B_c = _select(spa_empty, Zero, B_c)
    E_c = _select(spa_empty, One, E_c)
    D_c = _select(spa_empty, frV2, D_c)
    spa_next = reglu(cg[D_SPA], reglu(_geq_expr(SA, One), _geq_expr(frV1, One)))
    fr1_task = _select(spa_next, Expression({_one_dim: TASK_ST}), fr1_task)
    fr1_V1 = _select(spa_next, spa_tV2, fr1_V1)      # next t pend
    fr1_X = _select(spa_next, spa_sV2, fr1_X)        # next s pend
    fr1_V2 = _select(spa_next, frV2, fr1_V2)
    fr1_F2 = _select(spa_next, Expression({_one_dim: D_SPA}), fr1_F2)
    fr2_task = _select(spa_next, Expression({_one_dim: TASK_DEFEQ}), fr2_task)
    fr2_V1 = _select(spa_next, spa_tV0, fr2_V1)      # t arg
    fr2_X = _select(spa_next, spa_tX, fr2_X)
    fr2_E2 = _select(spa_next, spa_sV0, fr2_E2)      # s arg
    fr2_F2 = _select(spa_next, spa_sX, fr2_F2)
    fr2_V2 = _select(spa_next, c1, fr2_V2)
    C_c = _select(spa_next, Zero, C_c)
    F_c = _select(spa_next, Zero, F_c)
    E_c = _select(spa_next, Zero, E_c)
    D_c = _select(spa_next, c2, D_c)

    # D_NCC: t acc = ST.V1, t lit = ST.X, s acc = A, s lit = ST.E2.
    ncc = cg[D_NCC]
    ncc_fail = reglu(ncc, One - _eq_expr(frV1, SA))
    # ACCUMULATE (not assign): rej_c already carries the earlier CONT-tree
    # rejects (I_CHK / i_ls / i_p1 / i_p2 / i_ld). An assignment here silently
    # dropped them — the M4.3 mutation corpus caught infer_app accepting an
    # ill-typed argument because i_chk_fail's reject was wiped.
    rej_c = rej_c + reglu(ncc_fail, One)
    rej_code_c = rej_code_c + reglu(ncc_fail, One)
    nz_t = One - _geq_expr(frX, One)                 # t lit == 0 (zero ctor)
    nz_s = One - _geq_expr(frE2, One)
    zlit = _value_eq_n(_fv0(frX),
                       _fv0(frX + One * 2))
    zlit2 = _value_eq_n(_fv0(frE2),
                        _fv0(frE2 + One * 2))
    ncc_tt = reglu(ncc, reglu(_geq_expr(frX, One), _geq_expr(frE2, One)))
    ncc_zz = reglu(ncc, reglu(nz_t, nz_s))
    ncc_tz = reglu(ncc, reglu(_geq_expr(frX, One), nz_s))
    ncc_zt = reglu(ncc, reglu(nz_t, _geq_expr(frE2, One)))
    ncc_ok = reglu(ncc_zz, One) + reglu(ncc_tz, zlit) \
        + reglu(ncc_zt, zlit2)
    ncc_bad = reglu(ncc_tz, One - zlit) + reglu(ncc_zt, One - zlit2)
    rej_c = rej_c + reglu(ncc_bad, One)
    A_c = _select(ncc_ok + ncc_fail + ncc_bad,
                  _select(ncc_ok, One, Zero), A_c)
    B_c = _select(ncc_ok + ncc_fail + ncc_bad, Zero, B_c)
    E_c = _select(ncc_ok + ncc_fail + ncc_bad, One, E_c)
    D_c = _select(ncc_ok + ncc_fail + ncc_bad, frV2, D_c)
    # both literals: lockstep digit compare (reuse the lit-loop resume)
    ncc_both = reglu(ncc_tt, One - ncc_ok - ncc_fail - ncc_bad)
    fr1_task = _select(ncc_both, Expression({_one_dim: TASK_ST}), fr1_task)
    fr1_V1 = _select(ncc_both, frE2, fr1_V1)         # s chain head
    fr1_E2 = _select(ncc_both, Zero, fr1_E2)         # k = 0
    fr1_F2 = _select(ncc_both, Expression({_one_dim: D_NCD}), fr1_F2)
    A_c = _select(ncc_both, frX, A_c)                # t chain head
    B_c = _select(ncc_both, Zero, B_c)
    E_c = _select(ncc_both, Zero, E_c)
    D_c = _select(ncc_both, c1, D_c)

    # ── M4.2 CHECK continuations ────────────────────────────────────────────
    # CK_TY: inferred type in (A,B); ST.V1 = declared type root. Compare via
    # a DEFEQ sub-task whose caller is this ST (rewritten to CK_RES). The ST
    # keeps V2 = the NEXT anchor (threaded from the kickoff), so CK_RES
    # advances by popping to frV2 and accepts when frV2 = 0.
    A_c = _select(cg[CK_TY], SA, A_c)
    B_c = _select(cg[CK_TY], SB, B_c)
    fr1_F2 = _select(cg[CK_TY], Expression({_one_dim: CK_RES}), fr1_F2)
    fr2_task = _select(cg[CK_TY], Expression({_one_dim: TASK_DEFEQ}), fr2_task)
    fr2_V1 = _select(cg[CK_TY], SA, fr2_V1)          # t = inferred type
    fr2_X = _select(cg[CK_TY], SB, fr2_X)
    fr2_E2 = _select(cg[CK_TY], frV1, fr2_E2)        # s = declared type
    fr2_F2 = _select(cg[CK_TY], Zero, fr2_F2)
    fr2_V2 = _select(cg[CK_TY], c1, fr2_V2)
    E_c = _select(cg[CK_TY], Zero, E_c)
    D_c = _select(cg[CK_TY], c2, D_c)
    # CK_RES: verdict in A. False → reject ERR_TYPE. True: advance to the
    # next anchor (A = its value root) or ACCEPT (halt) when the chain ends.
    ck_pass = reglu(cg[CK_RES], _geq_expr(SA, One))
    ck_fail = reglu(cg[CK_RES], One - _geq_expr(SA, One))
    ck_next = reglu(ck_pass, _geq_expr(frV2, One))
    ck_accept = reglu(ck_pass, One - _geq_expr(frV2, One))
    rej_c = rej_c + reglu(ck_fail, One)
    rej_code_c = rej_code_c + reglu(ck_fail, One)
    A_c = _select(ck_next, nbX, A_c)                 # next decl's value root
    B_c = _select(ck_next, Zero, B_c)
    C_c = _select(ck_next, Zero, C_c)
    D_c = _select(ck_next, frV2, D_c)                # next CHECK anchor
    E_c = _select(ck_next + ck_accept, Zero, E_c)
    F_c = _select(ck_next, Zero, F_c)

    # ── WP7-G7 / G1: declaration well-formedness in the CHECK channel ──────
    # G7 (K/environment.cpp:87-95, declHasMVars/declHasFVars run BEFORE
    # check_constant_val): a root K_FVAR/K_MVAR token on either the declared
    # type or the value rejects with code 6 ("declaration has free
    # variables", plain kernel_exception → .other class). Root-only is a
    # documented approximation; nested leaks into the infer-path rejects.
    g7_k_t = fetch_by_position([k_], frV1)[0]
    g7_k_v = fetch_by_position([k_], frX)[0]
    g7 = reglu(ck_kick, _kind_eq_raw(g7_k_t, K_FVAR, One)
               + _kind_eq_raw(g7_k_t, K_MVAR, One)
               + _kind_eq_raw(g7_k_v, K_FVAR, One)
               + _kind_eq_raw(g7_k_v, K_MVAR, One))
    rej_c = rej_c + g7
    rej_code_c = rej_code_c + reglu(g7, One * 6)
    # G1 (K/environment.cpp:132 → K/type_checker.cpp:62-70): ensure_sort of
    # the declared type = infer it, soft-whnf the inferred type, require
    # K_SORT; else throw type_expected (reject code 5). The chain replaces
    # the old direct value-infer kickoff: CK_G0 receives the declared
    # type's type (T1), launches the soft whnf; CK_G1 inspects the reduct
    # and then continues with the ORIGINAL kickoff ([ST(CK_TY), INFER(val)]).
    # ST frames carry the decl through V1=type root, X=value root, V2=next.
    ck_g0 = cg[CK_G0]
    fr1_V1 = _select(ck_g0, frV1, fr1_V1)
    fr1_X = _select(ck_g0, frX, fr1_X)
    fr1_V2 = _select(ck_g0, frV2, fr1_V2)
    # card 010 G02: the kind payload must survive the hop from the kickoff's
    # ST to the ST this step pushes, because CK_G1 (the is_prop arm) reads it
    # from the frame at D.  Every other E2 reader is gated on a continuation
    # id the CHECK chain never uses, so the slot is free here.
    fr1_E2 = _select(ck_g0, frE2, fr1_E2)
    fr1_F2 = _select(ck_g0, Expression({_one_dim: CK_G1}), fr1_F2)
    fr2_task = _select(ck_g0, Expression({_one_dim: TASK_WHNF}), fr2_task)
    fr2_V1 = _select(ck_g0, SA, fr2_V1)              # T1 pos
    fr2_X = _select(ck_g0, SB, fr2_X)
    fr2_E2 = _select(ck_g0, One, fr2_E2)             # soft whnf
    fr2_V2 = _select(ck_g0, c1, fr2_V2)
    A_c = _select(ck_g0, SA, A_c)
    B_c = _select(ck_g0, SB, B_c)
    C_c = _select(ck_g0, Zero, C_c)
    F_c = _select(ck_g0, Zero, F_c)
    E_c = _select(ck_g0, Zero, E_c)
    D_c = _select(ck_g0, c2, D_c)
    g1_k = fetch_by_position([k_], SA)[0]
    ck_g1_ok = reglu(cg[CK_G1], _kind_eq_raw(g1_k, K_SORT, One))
    g1_fail = reglu(cg[CK_G1], One - ck_g1_ok)
    rej_c = rej_c + g1_fail
    rej_code_c = rej_code_c + reglu(g1_fail, One * 5)
    # WP7-G3 (K/environment.cpp:200-202): add_theorem runs `is_prop(type)`
    # right AFTER check_constant_val (the ensure_sort arm above, code 5) and
    # BEFORE the value side; false → theorem_type_is_not_prop → reject code 8.
    # is_prop = ensure_sort(infer(e)) ∧ normalizes_to_zero(sort_level)
    # (K/type_checker.cpp:383-389), so the only test missing above is the
    # level-zero one, and it MUST use the same judge as the proof-irrelevance
    # chain's pl_prop (level root kind vs KL_ZERO) — one level judge, not two
    # (ADR 020 B).
    # KNOWN DIVERGENCE (ADR 020 B; asserted in
    # tests/test_decl_injection_vs_lean.py KNOWN_GAPS): the kernel's
    # normalizes_to_zero (K/level.cpp:174-186) also accepts the NON-normalized
    # forms imax(_,0) and max(0,0), which the syntactic root compare rejects →
    # a theorem on such a stored type is a false code-8 reject. Universe
    # normalization = matrix D1/D2 (card 012). Measured scope of the gap: the
    # frontend never STORES an un-normalized level (a source-written
    # `Sort (imax 1 0)` reaches the env as `Sort zero`), and the graph's INFER
    # of a Pi whose body is a Prop already yields a KL_ZERO-root sort like
    # infer_pi's mk_imax folding does (K/type_checker.cpp:163, K/level.cpp:112
    # — differential case thm_arrow), so only env-stored raw levels diverge.
    # Kind is DATA from the anchor E2 slot (ENV_FORMAT §2.8), decoded
    # mode-independently: add_theorem always builds a SAFE checker
    # (K/environment.cpp:196), so is_prop must not depend on the checker mode.
    g3_mode = _geq_expr(frE2, Expression({_one_dim: CHECK_E2_STRIDE}))
    g3_kind = frE2 - reglu(Expression({_one_dim: CHECK_E2_STRIDE}), g3_mode)
    g3_lvK = fetch_by_position([k_], _fv0(SA))[0]
    g3 = reglu(reglu(ck_g1_ok,
                     _eq_expr(g3_kind,
                              Expression({_one_dim: CHECK_KIND_THEOREM}))),
               One - _kind_eq_raw(g3_lvK, KL_ZERO, One))
    rej_c = rej_c + g3
    rej_code_c = rej_code_c + reglu(g3, One * 8)
    # WP7-G5 (K/environment.cpp:152-158, add_axiom → check_constant_val
    # ONLY): an anchor with X = 0 carries no value — axiom_val has no value
    # field (K/declaration.h), so after ensure_sort the declaration is
    # done.  Advance (or accept at chain end) WITHOUT the value-infer /
    # defeq step; a dummy value would misclassify e.g. `axiom a : Nat → Nat`
    # as declTypeMismatch.  This is a structural convention, not a name or
    # cid branch (acceptance rule 3); documented in ENV_FORMAT/VM_SPEC.
    ck_g1_val = reglu(ck_g1_ok, _geq_expr(frX, One))
    ax_go = reglu(ck_g1_ok, reglu(One - _geq_expr(frX, One),
                                  _geq_expr(frV2, One)))
    ax_done = reglu(ck_g1_ok, reglu(One - _geq_expr(frX, One),
                                    One - _geq_expr(frV2, One)))
    fr1_V1 = _select(ck_g1_val, frV1, fr1_V1)         # declared type root
    fr1_V2 = _select(ck_g1_val, frV2, fr1_V2)
    fr1_F2 = _select(ck_g1_val, Expression({_one_dim: CK_TY}), fr1_F2)
    fr2_task = _select(ck_g1_val, Expression({_one_dim: TASK_INFER}), fr2_task)
    fr2_V2 = _select(ck_g1_val, c1, fr2_V2)
    fr2_E2 = _select(ck_g1_val, One, fr2_E2)          # hard infer flag (E2=1)
    A_c = _select(ck_g1_val, frX, A_c)                # value root focus
    B_c = _select(ck_g1_val + ax_go + ax_done, Zero, B_c)
    C_c = _select(ck_g1_val + ax_go + ax_done, Zero, C_c)
    F_c = _select(ck_g1_val + ax_go + ax_done, Zero, F_c)
    E_c = _select(ck_g1_val + ax_go + ax_done, Zero, E_c)
    D_c = _select(ck_g1_val, c2, D_c)
    A_c = _select(ax_go, nbX, A_c)                    # next anchor's value
    D_c = _select(ax_go, frV2, D_c)                   # relaunch ck_kick
    A_c = _select(ax_done, One, A_c)                  # chain-end accept verdict

    # ── CHECK kickoff payloads (merged via m2_merge's ck slot) ──────────────
    # WP7-G1: the kickoff now starts the ensure_sort(declared type) chain
    # (CK_G0); the value-infer relaunches from CK_G1's ok branch. The ST
    # carries the anchor's value root in X (free field on these STs).
    # card 010 G02: E2 rides along (anchor kind payload → ST → CK_G1's arm);
    # with the legacy kinds=None driver call the anchor E2 is 0, so the
    # payload is what it always was.
    fr1_task_k, fr1_V1_k, fr1_V2_k, fr1_X_k, fr1_E2_k, fr1_F2_k = \
        Expression({_one_dim: TASK_ST}), frV1, frV2, frX, frE2, \
        Expression({_one_dim: CK_G0})
    fr2_task_k, fr2_V1_k, fr2_V2_k, fr2_X_k, fr2_E2_k, fr2_F2_k = \
        Expression({_one_dim: TASK_INFER}), Zero, c1, Zero, One, Zero
    A_k, B_k, C_k, D_k, E_k, F_k = frV1, Zero, Zero, c2, Zero, Zero

    # ── INFER frame dispatch (task=6; focus = (A,B), phase in E2) ───────────
    A_i = SA
    B_i = SB
    C_i = SC
    D_i = SD
    E_i = SE
    F_i = SF
    # Walk STs: under a SOFT infer (frF2=1, a proof-irrel-chain launch) the
    # ST's V2 = its TASK_INFER frame (SD) so the A=0 failure marker and the
    # soft-flag read (fetch f2_ frV2 in I_CHK / IP) both land on the task
    # frame, which forwards the decline to PI_TY.  Under a HARD infer (frF2=0,
    # a top-level run_infer) V2 stays the original continuation (frV2): the
    # task-frame repoint would mis-deliver the walk result and reject the
    # lam/proj infer corpus (P7.5c-2 regression: inf_lam_*/inf_proj_*).
    fr1_task_i, fr1_V1_i, fr1_V2_i, fr1_X_i, fr1_E2_i, fr1_F2_i = \
        Expression({_one_dim: TASK_ST}), Zero, \
        _select(_geq_expr(frF2, One), SD, frV2), Zero, Zero, Zero
    fr2_task_i, fr2_V1_i, fr2_V2_i, fr2_X_i, fr2_E2_i, fr2_F2_i = \
        Expression({_one_dim: TASK_WHNF}), SA, SB, Zero, Zero, Zero
    em_pend_i = Zero
    pend_V0_i, pend_prev_i, pend_env_i = Zero, Zero, Zero
    em_raw_i = Zero
    raw_K_i, raw_V0_i = Zero, Zero
    rej_i, rej_code_i = Zero, Zero
    # P_EMIT phase gate is mode-gated: frE2 on non-INFER frames (e.g. the
    # lit-compare ST's digit counter) collides with phase 2
    ph_emit = reglu(is_infer_frame, _eq_expr(frE2, One * 2))
    ph1 = reglu(is_infer_frame, One - ph_emit)
    # P_EMIT: B = chain cur, ST.V1 = remaining succs
    em_more = reglu(ph_emit, _geq_expr(frV1, One))
    em_fin = reglu(ph_emit, One - _geq_expr(frV1, One))
    em_raw_i = ph_emit
    raw_K_i = _select(em_more, Expression({_one_dim: KL_SUCC}),
                      Expression({_one_dim: K_SORT}))
    raw_V0_i = SB
    A_i = _select(em_fin, c1, A_i)
    B_i = _select(em_more, c1, _select(em_fin, Zero, B_i))
    E_i = _select(em_fin, One, E_i)
    D_i = _select(em_fin, frV2, D_i)
    fr1_task_i = _select(em_more, Expression({_one_dim: TASK_INFER}), fr1_task_i)
    fr1_V1_i = _select(em_more, frV1 - One, fr1_V1_i)
    fr1_V2_i = _select(em_more, frV2, fr1_V2_i)
    fr1_E2_i = _select(em_more, One * 2, fr1_E2_i)
    fr1_F2_i = _select(em_more, frF2, fr1_F2_i)      # inherit soft-infer flag
    D_i = _select(em_more, c2, D_i)
    C_i = _select(em_more, Zero, C_i)
    F_i = _select(em_more, Zero, F_i)
    E_i = _select(em_more, Zero, E_i)
    # P1: APP peel (mid / end), LAM, PI, LET, CONST, LIT, SORT, BVAR
    fnK_i = fetch_by_position([k_], fV0)[0]
    peel_more = reglu(ph1, reglu(is_app, _kind_eq_raw(fnK_i, K_APP, One)))
    peel_end = reglu(ph1, reglu(is_app, One - _kind_eq_raw(fnK_i, K_APP, One)))
    em_pend_i = peel_more + peel_end
    pend_V0_i = fV1
    pend_prev_i = SC
    pend_env_i = SB
    A_i = _select(peel_more + peel_end, fV0, A_i)
    C_i = _select(peel_more, c1, C_i)
    C_i = _select(peel_end, Zero, C_i)
    F_i = _select(peel_end, Zero, F_i)
    fr1_E2_i = _select(peel_end, c1, fr1_E2_i)       # args chain head
    fr1_F2_i = _select(peel_end, Expression({_one_dim: I_FN}), fr1_F2_i)
    fr2_task_i = _select(peel_end, Expression({_one_dim: TASK_INFER}),
                         fr2_task_i)
    fr2_V2_i = _select(peel_end, c2, fr2_V2_i)
    fr2_E2_i = _select(peel_end, One, fr2_E2_i)      # INFER phase 1
    fr2_F2_i = _select(peel_end, frF2, fr2_F2_i)     # inherit soft-infer flag
    D_i = _select(peel_end, c3, D_i)
    # LAM: infer the domain (ST keeps lam dom/env/body for T_PI_CLO)
    lam_i = reglu(ph1, is_lam)
    fr1_V1_i = _select(lam_i, fV0, fr1_V1_i)
    fr1_X_i = _select(lam_i, SB, fr1_X_i)
    fr1_E2_i = _select(lam_i, fV1, fr1_E2_i)
    fr1_F2_i = _select(lam_i, Expression({_one_dim: I_LAMDOM}), fr1_F2_i)
    fr2_task_i = _select(lam_i, Expression({_one_dim: TASK_INFER}), fr2_task_i)
    fr2_V2_i = _select(lam_i, c1, fr2_V2_i)
    fr2_E2_i = _select(lam_i, One, fr2_E2_i)
    fr2_F2_i = _select(lam_i, frF2, fr2_F2_i)        # inherit soft-infer flag
    A_i = _select(lam_i, fV0, A_i)                   # domain
    D_i = _select(lam_i, c2, D_i)
    # PI
    pi_i = reglu(ph1, _kind_eq_raw(fK, K_PI, One))
    fr1_V1_i = _select(pi_i, fV0, fr1_V1_i)
    fr1_X_i = _select(pi_i, SB, fr1_X_i)
    fr1_E2_i = _select(pi_i, fV1, fr1_E2_i)
    fr1_F2_i = _select(pi_i, Expression({_one_dim: I_PIDOM}), fr1_F2_i)
    fr2_task_i = _select(pi_i, Expression({_one_dim: TASK_INFER}), fr2_task_i)
    fr2_V2_i = _select(pi_i, c1, fr2_V2_i)
    fr2_E2_i = _select(pi_i, One, fr2_E2_i)
    fr2_F2_i = _select(pi_i, frF2, fr2_F2_i)         # inherit soft-infer flag
    A_i = _select(pi_i, fV0, A_i)
    D_i = _select(pi_i, c2, D_i)
    # LET: infer the value first
    let_i = reglu(ph1, is_let)
    fr1_V1_i = _select(let_i, fV0, fr1_V1_i)         # declared type pos
    fr1_X_i = _select(let_i, SB, fr1_X_i)
    fr1_E2_i = _select(let_i, SA, fr1_E2_i)          # LET token pos (for I_LETD body fetch)
    fr1_F2_i = _select(let_i, Expression({_one_dim: I_LETV}), fr1_F2_i)
    fr2_task_i = _select(let_i, Expression({_one_dim: TASK_INFER}), fr2_task_i)
    fr2_V2_i = _select(let_i, c1, fr2_V2_i)
    fr2_E2_i = _select(let_i, One, fr2_E2_i)
    fr2_F2_i = _select(let_i, frF2, fr2_F2_i)        # inherit soft-infer flag
    A_i = _select(let_i, fV1, A_i)                   # value
    D_i = _select(let_i, c2, D_i)
    # CONST: type = ENV_HDR.V1, or K_CONST.E2 when the Encoder specialized the
    # declared type at this use site. Kernel infer_constant
    # (K/type_checker.cpp:101-123) returns instantiate_type_lparams(info, ls)
    # (D14, K/instantiate.cpp:248-254): each declaration lparam replaced by the
    # use-site level (D10, K/level.cpp:317-340). The Encoder emits that
    # instantiated type tree once per polymorphic use site and stores its root
    # in K_CONST.E2 (VM_SPEC §12.7); the graph selects it here. E2=0 means a
    # monomorphic/param-free use site and the shared declared type is used.
    const_i = reglu(ph1, is_const)
    # WP7-G10 (K/type_checker.cpp:110-117, infer_constant): a SAFE-mode
    # checker throws when a term references a constant whose declaration is
    # unsafe ("it uses unsafe declaration 'n'") or whose definition safety is
    # partial ("safe declaration must not contain partial declaration 'n'").
    # The graph's checker is always safe-mode (kernel default type_checker,
    # K/environment.cpp:152-223).  The disjunction is precomputed by the
    # encoder at anchor(cid).F2 (ENV_FORMAT §2.3); streams without metadata
    # have F2=0 → the gate is inert (legacy behavior preserved).  The throw
    # point is INFER only: whnf/delta unfolding carries no safety check in
    # the kernel (unfoldDefinition at K/type_checker.cpp:555+ never calls
    # infer_constant), so the DEFEQ arms are untouched.
    anc_f2 = fetch_by_position([f2_], _anc(fV0))[0]
    safety_i = reglu(const_i, _geq_expr(anc_f2, One))
    const_i = reglu(const_i, One - _geq_expr(anc_f2, One))
    A_i = _select(const_i, _select(_geq_expr(fE2, One), fE2, eV1), A_i)
    B_i = _select(const_i, Zero, B_i)
    E_i = _select(const_i, One, E_i)
    D_i = _select(const_i, frV2, D_i)
    # LIT: emit Const(Nat)
    lit_i = reglu(ph1, _kind_eq_raw(fK, K_LIT, One))
    # WP5-E4 (K/type_checker.cpp:315-321, infer_lit): a Nat literal infers to
    # Nat, a STRING literal (the E1 K_LIT.V1 == 1 encoding) infers to String.
    # The Nat size-limit half of infer_lit is WP6, untouched.  A string
    # literal in an env without the X=19 "String" tag cannot be typed —
    # it falls through to the unsupported-kind reject/soft-fail channel
    # below (bad_i), mirroring the kernel's impossible-term situation.
    lit_nat_i = reglu(lit_i, _eq_expr(fV1, Zero))
    # WP6-F9 (K/type_checker.cpp:315-321, infer_lit): check_nat_size on the
    # literal's own value.  Exact digit count (V0) + the L(D) >= T form:
    # D >= _T_DIG => limbs >= L >= T => 8*limbs > MAX => kernel throws.
    # Bands below _T_DIG are the documented accept-side slack (VM_SPEC §WP6-G).
    rej_lit = reglu(lit_nat_i, _geq_expr(fV0, One * _T_DIG_CMP))
    lit_ok_i = reglu(reglu(lit_i, _eq_expr(fV1, One)), _STRING_OK)
    lit_infer_i = lit_nat_i + lit_ok_i
    em_raw_i = em_raw_i + lit_infer_i
    raw_K_i = _select(lit_infer_i, Expression({_one_dim: K_CONST}), raw_K_i)
    # V0 must be the Nat cid, NOT SB: under a binder-marker env (deq_fvar_args
    # infers `f 1`'s arg at env=marker) SB leaked the link position into the
    # emitted Const and the I_CHK defeq then inferred a nonexistent const.
    # Top-level literals (env 0 == CID_NAT) masked it pre-P6.  The Nat cid is
    # now metadata-derived from the name-keyed Nat.succ header entry
    # (_NAT_CID); legacy streams fall back to CID_NAT.  The String cid comes
    # from the X=19 header tag (_STRING_CID, VM_SPEC §14.3) — no fallback.
    raw_V0_i = _select(lit_nat_i, _NAT_CID,
              _select(lit_ok_i, _STRING_CID, raw_V0_i))
    A_i = _select(lit_infer_i, c1, A_i)
    B_i = _select(lit_infer_i, Zero, B_i)
    E_i = _select(lit_infer_i, One, E_i)
    D_i = _select(lit_infer_i, frV2, D_i)
    # SORT: infer_sort (K/type_checker.cpp:345-348) = mk_sort(mk_succ(level)).
    # No level scan is needed: I_SORTEM wraps the Sort token's own level root in
    # a raw KL_SUCC (symbolic Param/Max/IMax safe).  The ST "continuation"
    # frame is the only frame pushed (no LEVEL sub-task), so it lands at c1;
    # its V1 carries the Sort token position for I_SORTEM to read V0 from.
    sort_i = reglu(ph1, _kind_eq_raw(fK, K_SORT, One))
    fr1_F2_i = _select(sort_i, Expression({_one_dim: I_SORTEM}), fr1_F2_i)
    fr1_V1_i = _select(sort_i, SA, fr1_V1_i)        # Sort token pos
    A_i = _select(sort_i, SA, A_i)
    B_i = _select(sort_i, SB, B_i)
    E_i = _select(sort_i, One, E_i)                 # resume the ST immediately
    D_i = _select(sort_i, c1, D_i)
    # BVAR: walk the chain (re-dispatch or marker delivery on return)
    bvar_i = reglu(ph1, is_bvar)
    fr2_task_i = _select(bvar_i, Expression({_one_dim: TASK_WALK}), fr2_task_i)
    fr2_V2_i = _select(bvar_i, SD, fr2_V2_i)         # back to this frame
    fr2_X_i = _select(bvar_i, fV0, fr2_X_i)          # bvar index
    A_i = _select(bvar_i, SB, A_i)                   # chain head
    D_i = _select(bvar_i, c1, D_i)
    # PROJ (P6.2 mechanism F): infer the child, whnf its type (IP_TY), then
    # peel the ctor Pi spine to the field domain (IP_PEEL). Kernel infer_proj
    # monomorphic non-rec non-dependent subset — P2 only, build-time gated.
    proj_i = reglu(ph1, is_proj)
    fr1_V1_i = _select(proj_i, fV0, fr1_V1_i)       # proj sname nid
    fr1_X_i = _select(proj_i, fV1, fr1_X_i)         # field idx
    fr1_F2_i = _select(proj_i, Expression({_one_dim: IP_TY}), fr1_F2_i)
    fr2_task_i = _select(proj_i, Expression({_one_dim: TASK_INFER}),
                         fr2_task_i)
    fr2_V2_i = _select(proj_i, c1, fr2_V2_i)
    fr2_E2_i = _select(proj_i, One, fr2_E2_i)
    fr2_F2_i = _select(proj_i, frF2, fr2_F2_i)       # inherit soft-infer flag
    A_i = _select(proj_i, fX, A_i)                  # child
    D_i = _select(proj_i, c2, D_i)
    # unsupported kind in term position  (WP5-E4: only inferable literals are
    # supported — a string literal without the String tag counts as bad)
    # WP7-G10: safety_i joins the bad channel (soft infer → failure marker,
    # hard infer → reject; kernel throws in both the inferType and the
    # check-value position, K/type_checker.cpp:110-117).  The reject CODE
    # stays distinct (7, see the final reject_code select).
    bad_i = reglu(ph1, One - is_app - is_lam - is_const - is_let - bvar_i
                  - pi_i - lit_infer_i - sort_i - proj_i) + safety_i
    # soft infer (task F2=1): unsupported kind → failure marker (A=0) to the
    # awaiting consumer (task.V2), not a reject — ref _proof_irrel catches
    # ERR_UNSUPPORTED from the t-side infers → None → decline.
    bad_soft = reglu(bad_i, _geq_expr(frF2, One))
    rej_i = reglu(bad_i, One - _geq_expr(frF2, One))
    rej_code_i = reglu(rej_i, One * 4)
    A_i = _select(bad_soft, Zero, A_i)
    B_i = _select(bad_soft, Zero, B_i)
    C_i = _select(bad_soft, Zero, C_i)
    F_i = _select(bad_soft, Zero, F_i)
    E_i = _select(bad_soft, One, E_i)
    D_i = _select(bad_soft, frV2, D_i)

    # ── LEVEL frame dispatch (task=8; node = A, acc in X) ───────────────────
    # The graph's level channel is an INTEGER explicit-level counter: X is the
    # number of Succ nodes peeled, Zero returns that count (VM_SPEC §12.2 D9
    # to_explicit; the callers I_PIS1/I_PIS2/I_SORTEM/D_SORT then compute
    # succ/imax/eq as ints). VM_SPEC §12.1's symbolic levels are therefore not
    # representable here: Param/MVar need identity (D3 name equality) and
    # Max/IMax need a two-operand smart constructor (D1/D2) plus the D10/D14
    # instantiation channel. RefVM carries that symbolic channel (WP2); the
    # ALM graph does not yet. The graph's executable data path (import_env,
    # reference/olean_export.py) specializes polymorphic constants to
    # monomorphic and drops their level args, so graph-layer corpora never
    # contain LParam; a raw parametric use site reaching LEVEL is rejected
    # with ERR_UNSUPPORTED (4) rather than silently mis-decoded.
    lvl_zero = reglu(is_level_frame, _eq_expr(fK, One))       # KL_ZERO = 1
    lvl_succ = reglu(is_level_frame, _eq_expr(fK, One * 2))   # KL_SUCC = 2
    lvl_max = reglu(is_level_frame, _eq_expr(fK, One * 3))    # KL_MAX = 3
    lvl_imax = reglu(is_level_frame, _eq_expr(fK, One * 4))   # KL_IMAX = 4
    lvl_param = reglu(is_level_frame, _eq_expr(fK, One * 5))  # KL_PARAM = 5
    lvl_mvar = reglu(is_level_frame, _eq_expr(fK, One * 6))   # KL_MVAR = 6
    # Succ drives the explicit-level continuation; every other kind is out of
    # the integer channel (lvl_max/lvl_imax/lvl_param/lvl_mvar are named so
    # the boundary is explicit instead of a bare complement).
    lvl_bad = reglu(is_level_frame, One - lvl_zero - lvl_succ)
    rej_l = lvl_bad
    rej_code_l = reglu(lvl_bad, One * 4)
    _ = lvl_max + lvl_imax + lvl_param + lvl_mvar    # documented boundary set
    A_l = _select(lvl_succ, fV0, _select(lvl_zero, frX, SA))
    B_l = _select(lvl_zero, Zero, SB)
    C_l = SC
    E_l = _select(lvl_zero, One, SE)
    F_l = SF
    D_l = _select(lvl_succ, c1, _select(lvl_zero, frV2, SD))
    fr1_task_l = Expression({_one_dim: TASK_LEVEL})
    fr1_V2_l = frV2
    fr1_X_l = frX + One

    # ── pop-task (E=1 under a TASK frame): pop one frame, keep the result ───
    pop_task = reglu(ret_pending, is_task_frame)

    # ── nat-op arg validation (soft whnf: kernel is_nat_expr failure) ───────
    # A Nat argument is well-formed iff it is a literal or the nullary Nat
    # constructor, identified from T_ENV_CTORVAL (induct is_rec, cidx 0,
    # nfields 0) rather than the toy cid.
    valid1 = reglu(_kind_eq_raw(tK, K_LIT, One), _eq_expr(tV1, Zero)) \
        + reglu(_kind_eq_raw(tK, K_CONST, One), _is_zero(tV0))
    valid2 = reglu(_kind_eq_raw(fK, K_LIT, One), _eq_expr(fV1, Zero)) \
        + reglu(_kind_eq_raw(fK, K_CONST, One), _is_zero(fV0))
    natbad2 = reglu(d23, One - reglu(valid1, valid2))
    natbad1 = reglu(dn1, One - valid2)
    # a walk that sticks at a binder marker delivers focus=bvar with E=1 to
    # the parent frame; when that parent is a nat-op control frame (arg not
    # a literal) the kernel _soft_whnf contract applies: soft → deliver the
    # ORIGINAL closure, hard → reject (same as natbad1/2, focus is a bvar).
    stuck_nat = reglu(ret_pending, reglu(is_nat_frame,
                  reglu(_eq_expr(frX, One),
                        One - _kind_eq_raw(frV1, OP_REC, One)
                        - _kind_eq_raw(frV1, OP_IOTA, One)
                        - _kind_eq_raw(frV1, OP_QUOT, One))))
    stuck_st0 = reglu(ret_pending,
                      reglu(is_st_frame, One - _geq_expr(frF2, One)))
    stuck_ret = reglu(stuck_nat + stuck_st0, is_bvar)
    natbad = reglu(natbad2 + natbad1 + stuck_ret, One)
    # soft-w pos: d23/stuck-on-ST are two hops up (ST->NAT->WHNF: nbV2),
    # natbad1/stuck-on-NAT one hop (NAT->WHNF: frV2)
    # Nested nat args (e.g. casesOn iota whnffing its `Nat.succ k` major:
    # NAT(succ) -> NAT(caseson) -> WHNF) put the soft WHNF frame TWO hops
    # up; the one-hop read there sees the intermediate NAT frame's E2 (a
    # node pos, not the soft flag) and hard-rejects where the kernel leaves
    # the op stuck.  Climb one more hop when the parent is itself a NAT
    # control frame.
    stuck_nat_nested = reglu(is_nat_frame, _kind_eq_raw(nbV0, TASK_NAT, One))
    wpos = _select(natbad2, nbV2,
            _select(natbad1, frV2,
            _select(stuck_ret, _select(stuck_nat_nested, nbV2,
                         _select(is_nat_frame, frV2, nbV2)), frV2)))
    wV1 = fetch_by_position([v1_], wpos)[0]
    wX = fetch_by_position([x_], wpos)[0]
    wE2 = fetch_by_position([e2_], wpos)[0]
    wV2 = fetch_by_position([v2_], wpos)[0]
    nat_soft = reglu(natbad, _eq_expr(wE2, One))
    nat_hard = reglu(natbad, One - _eq_expr(wE2, One))
    rej_n = nat_hard
    rej_code_n = reglu(nat_hard, One)


    # D_NCT / D_NCS: nat-ctor value extraction. A = cur node; the succ
    # accumulator lives in ST.E2 (state E is the result flag — non-zero
    # accs would flip ret_pending and break the resume loop). ST:
    # D_NCT: V1 = other side's cur, V2 = caller; D_NCS: V1 = t acc,
    # X = t lit, V2 = caller.
    nc_loop = reglu(resume_mode, g[D_NCT] + g[D_NCS])
    nc_app = reglu(nc_loop, _kind_eq_raw(fK, K_APP, One))
    fnK6 = fetch_by_position([k_], fV0)[0]
    fnC6 = _fv0(fV0)
    nc_step = reglu(nc_app, reglu(_kind_eq_raw(fnK6, K_CONST, One),
                                  _is_succ(fnC6)))
    nc_zero = reglu(nc_loop, reglu(_kind_eq_raw(fK, K_CONST, One),
                                   _is_zero(fV0)))
    # WP5: the nat-ctor extraction's literal branch must see a NAT literal.
    # A string literal (V1=1, E1 encoding) is not a Nat value: the kernel's
    # is_def_eq nat branch fires only on Nat-ctor heads, so here the pair
    # falls through (nc_fail) to ST_ET — where the new string arms below
    # (ST_ES, VM_SPEC §14.5) take over.  Without this gate the byte chain
    # would be read as a digit chain and the empty literal (V0=0) would look
    # like the Nat.zero ctor.
    nc_lit = reglu(nc_loop, reglu(_kind_eq_raw(fK, K_LIT, One),
                                  _eq_expr(fV1, Zero)))
    nc_fail = reglu(nc_loop, One - nc_step - nc_zero - nc_lit)
    # extraction failure: the stuck heads are not BOTH nat-constructors → fall
    # through to eta (kernel is_def_eq_core: nat_ctor only when both sides are
    # ctors; otherwise try_eta_expansion / try_eta_struct follow).
    fr1_F2_r = _select(nc_fail, Expression({_one_dim: ST_ET}), fr1_F2_r)
    E_r = _select(nc_fail, One, E_r)               # dispatch ST_ET next step
    D_r = _select(nc_fail, c1, D_r)
    # succ step: descend into the arg, acc+1 (acc in ST.E2)
    A_r = _select(nc_step, fV1, A_r)
    fr1_E2_r = _select(nc_step, frE2 + One, fr1_E2_r)
    fr1_V1_r = _select(nc_step, frV1, fr1_V1_r)
    fr1_V2_r = _select(nc_step, frV2, fr1_V2_r)
    fr1_F2_r = _select(nc_step, frF2, fr1_F2_r)
    D_r = _select(nc_step, c1, D_r)
    # zero/lit done for the t side (D_NCT): stash (acc, lit), extract s
    nct_done = reglu(nc_zero + nc_lit, g[D_NCT])
    fr1_task_r = _select(nct_done, Expression({_one_dim: TASK_ST}), fr1_task_r)
    fr1_V1_r = _select(nct_done, frE2, fr1_V1_r)     # t acc
    fr1_X_r = _select(nct_done, _select(nc_lit, SA, Zero), fr1_X_r)  # t lit
    fr1_E2_r = _select(nct_done, Zero, fr1_E2_r)
    fr1_V2_r = _select(nct_done, frV2, fr1_V2_r)
    fr1_F2_r = _select(nct_done, Expression({_one_dim: D_NCS}), fr1_F2_r)
    A_r = _select(nct_done, frV1, A_r)               # s cur
    B_r = _select(nct_done, Zero, B_r)
    E_r = _select(nct_done, Zero, E_r)
    D_r = _select(nct_done, c1, D_r)
    # s side done (D_NCS): compare (s acc = frE2 now)
    ncs_zero = reglu(nc_zero, g[D_NCS])
    ncs_lit = reglu(nc_lit, g[D_NCS])
    ncs_done = ncs_zero + ncs_lit
    fr1_task_r = _select(ncs_done, Expression({_one_dim: TASK_ST}), fr1_task_r)
    fr1_V1_r = _select(ncs_done, frV1, fr1_V1_r)     # t acc
    fr1_X_r = _select(ncs_done, frX, fr1_X_r)        # t lit
    fr1_E2_r = _select(ncs_done, _select(ncs_lit, SA, Zero), fr1_E2_r)  # s lit
    fr1_V2_r = _select(ncs_done, frV2, fr1_V2_r)
    fr1_F2_r = _select(ncs_done, Expression({_one_dim: D_NCC}), fr1_F2_r)
    A_r = _select(ncs_done, frE2, A_r)               # s acc
    B_r = _select(ncs_done, Zero, B_r)
    E_r = _select(ncs_done, One, E_r)                # D_NCC is a CONT branch
    D_r = _select(ncs_done, c1, D_r)


    # ── mode / branch merge ─────────────────────────────────────────────────
    A_done = _select(result_spine, SF, SA)
    # nat-arg invalid under a WHNF frame: soft → deliver the ORIGINAL
    # closure (kernel _soft_whnf), hard → reject. Inserted before d23/dn1.
    A_ns, B_ns, C_ns, D_ns = wV1, wX, Zero, wV2
    E_ns, F_ns = One, Zero
    A_main_all = _select(proj_setup, fX,
                 _select(fire2, A_fire2,
                 _select(fire1, A_fire1,
                 _select(d12, A_d12,
                 _select(nat_soft, A_ns,
                 _select(d23, A_d23,
                 _select(dn1, A_dn1,
                 _select(fire_rec, A_fire_rec,
                 _select(zero_r, A_zero_r,
                 _select(build_r, A_build_r,
                 _select(stuck_r, A_stuck_r,
                 _select(rec_sd, A_rec_sd,
                 _select(fire_caseson, A_fire_cs,
                 _select(cs_zero_r, A_zero_cs,
                 _select(cs_succ_r, A_succ_cs,
                 _select(cs_stuck_r, A_stuck_cs,
                 _select(cs_sd, A_sd_cs,
                 _select(fire_p2, A_fire_p2,
                 _select(p2_succ_r, A_succ_p2,
                 _select(p2_stuck_r, A_stuck_p2,
                 _select(p2_sd, A_sd_p2,
                 _select(fire_bool, A_fire_bool,
                 _select(bool_false_r, A_false_bool,
                 _select(bool_true_r, A_true_bool,
                 _select(bool_stuck_r, A_stuck_bool,
                 _select(bool_sd, A_sd_bool,
                 _select(whnf_deliver, A_done,
                         A_main)))))))))))))))))))))))))))
    B_main_all = _select(proj_setup, SB,
                 _select(fire2, B_fire2,
                 _select(fire1, B_fire1,
                 _select(d12, B_d12,
                 _select(nat_soft, B_ns,
                 _select(d23, B_d23,
                 _select(dn1, B_dn1,
                 _select(fire_rec, B_fire_rec,
                 _select(zero_r, B_zero_r,
                 _select(build_r, B_build_r,
                 _select(stuck_r, B_stuck_r,
                 _select(rec_sd, B_rec_sd,
                 _select(fire_caseson, B_fire_cs,
                 _select(cs_zero_r, B_zero_cs,
                 _select(cs_succ_r, B_succ_cs,
                 _select(cs_stuck_r, B_stuck_cs,
                 _select(cs_sd, B_sd_cs,
                 _select(fire_p2, B_fire_p2,
                 _select(p2_succ_r, B_succ_p2,
                 _select(p2_stuck_r, B_stuck_p2,
                 _select(p2_sd, B_sd_p2,
                 _select(fire_bool, B_fire_bool,
                 _select(bool_false_r, B_false_bool,
                 _select(bool_true_r, B_true_bool,
                 _select(bool_stuck_r, B_stuck_bool,
                 _select(bool_sd, B_sd_bool,
                 _select(whnf_deliver, SB,
                         B_main)))))))))))))))))))))))))))
    C_main_all = _select(proj_setup, Zero,
                 _select(fire2, C_fire2,
                 _select(fire1, C_fire1,
                 _select(d12, C_d12,
                 _select(nat_soft, C_ns,
                 _select(d23, C_d23,
                 _select(dn1, C_dn1,
                 _select(fire_rec, C_fire_rec,
                 _select(zero_r, C_zero_r,
                 _select(build_r, C_build_r,
                 _select(stuck_r, C_stuck_r,
                 _select(rec_sd, C_rec_sd,
                 _select(fire_caseson, C_fire_cs,
                 _select(cs_zero_r, C_zero_cs,
                 _select(cs_succ_r, C_succ_cs,
                 _select(cs_stuck_r, C_stuck_cs,
                 _select(cs_sd, C_sd_cs,
                 _select(fire_p2, C_fire_p2,
                 _select(p2_succ_r, C_succ_p2,
                 _select(p2_stuck_r, C_stuck_p2,
                 _select(p2_sd, C_sd_p2,
                 _select(fire_bool, C_fire_bool,
                 _select(bool_false_r, C_false_bool,
                 _select(bool_true_r, C_true_bool,
                 _select(bool_stuck_r, C_stuck_bool,
                 _select(bool_sd, C_sd_bool,
                 _select(whnf_deliver, SC,
                         C_main)))))))))))))))))))))))))))
    D_main_all = _select(proj_setup, c2,
                 _select(fire2, D_fire2,
                 _select(fire1, D_fire1,
                 _select(d12, D_d12,
                 _select(nat_soft, D_ns,
                 _select(d23, D_d23,
                 _select(dn1, D_dn1,
                 _select(fire_rec, D_fire_rec,
                 _select(zero_r, D_zero_r,
                 _select(build_r, D_build_r,
                 _select(stuck_r, D_stuck_r,
                 _select(rec_sd, D_rec_sd,
                 _select(fire_caseson, D_fire_cs,
                 _select(cs_zero_r, D_zero_cs,
                 _select(cs_succ_r, D_succ_cs,
                 _select(cs_stuck_r, D_stuck_cs,
                 _select(cs_sd, D_sd_cs,
                 _select(fire_p2, D_fire_p2,
                 _select(p2_succ_r, D_succ_p2,
                 _select(p2_stuck_r, D_stuck_p2,
                 _select(p2_sd, D_sd_p2,
                 _select(fire_bool, D_fire_bool,
                 _select(bool_false_r, D_false_bool,
                 _select(bool_true_r, D_true_bool,
                 _select(bool_stuck_r, D_stuck_bool,
                 _select(bool_sd, D_sd_bool,
                 _select(whnf_deliver, frV2,
                         D_main)))))))))))))))))))))))))))
    E_main_all = _select(proj_setup, Zero,
                 _select(fire2, E_fire2,
                 _select(fire1, E_fire1,
                 _select(d12, E_d12,
                 _select(nat_soft, E_ns,
                 _select(d23, E_d23,
                 _select(dn1, E_dn1,
                 _select(fire_rec, E_fire_rec,
                 _select(zero_r, E_zero_r,
                 _select(build_r, E_build_r,
                 _select(stuck_r, E_stuck_r,
                 _select(rec_sd, E_rec_sd,
                 _select(fire_caseson, E_fire_cs,
                 _select(cs_zero_r, E_zero_cs,
                 _select(cs_succ_r, E_succ_cs,
                 _select(cs_stuck_r, E_stuck_cs,
                 _select(cs_sd, E_sd_cs,
                 _select(fire_p2, E_fire_p2,
                 _select(p2_succ_r, E_succ_p2,
                 _select(p2_stuck_r, E_stuck_p2,
                 _select(p2_sd, E_sd_p2,
                 _select(fire_bool, E_fire_bool,
                 _select(bool_false_r, E_false_bool,
                 _select(bool_true_r, E_true_bool,
                 _select(bool_stuck_r, E_stuck_bool,
                 _select(bool_sd, E_sd_bool,
                 _select(whnf_deliver, One,
                         E_main)))))))))))))))))))))))))))
    F_main_all = _select(proj_setup, Zero,
                 _select(fire2, F_fire2,
                 _select(fire1, F_fire1,
                 _select(d12, F_d12,
                 _select(nat_soft, F_ns,
                 _select(d23, F_d23,
                 _select(dn1, F_dn1,
                 _select(fire_rec, F_fire_rec,
                 _select(zero_r, F_zero_r,
                 _select(build_r, F_build_r,
                 _select(stuck_r, F_stuck_r,
                 _select(rec_sd, F_rec_sd,
                 _select(fire_caseson, F_fire_cs,
                 _select(cs_zero_r, F_zero_cs,
                 _select(cs_succ_r, F_succ_cs,
                 _select(cs_stuck_r, F_stuck_cs,
                 _select(cs_sd, F_sd_cs,
                 _select(fire_p2, F_fire_p2,
                 _select(p2_succ_r, F_succ_p2,
                 _select(p2_stuck_r, F_stuck_p2,
                 _select(p2_sd, F_sd_p2,
                 _select(fire_bool, F_fire_bool,
                 _select(bool_false_r, F_false_bool,
                 _select(bool_true_r, F_true_bool,
                 _select(bool_stuck_r, F_stuck_bool,
                 _select(bool_sd, F_sd_bool,
                 _select(whnf_deliver, SF,
                         F_main)))))))))))))))))))))))))))

    # WP3 general iota branches (mutually exclusive with the hardcoded iota /
    # casesOn branches above, so precedence is irrelevant).
    A_main_all = _select(fire_iota, A_fire_iota,
                 _select(iota_str_r, A_iota_str,
                 _select(iota_stuck_r, A_iota_stuck,
                 _select(iota_build_r, A_iota_build,
                 _select(iota_sd, A_iota_sd, A_main_all)))))
    B_main_all = _select(fire_iota, B_fire_iota,
                 _select(iota_str_r, B_iota_str,
                 _select(iota_stuck_r, B_iota_stuck,
                 _select(iota_build_r, B_iota_build,
                 _select(iota_sd, B_iota_sd, B_main_all)))))
    C_main_all = _select(fire_iota, C_fire_iota,
                 _select(iota_str_r, C_iota_str,
                 _select(iota_stuck_r, C_iota_stuck,
                 _select(iota_build_r, C_iota_build,
                 _select(iota_sd, C_iota_sd, C_main_all)))))
    D_main_all = _select(fire_iota, D_fire_iota,
                 _select(iota_str_r, D_iota_str,
                 _select(iota_stuck_r, D_iota_stuck,
                 _select(iota_build_r, D_iota_build,
                 _select(iota_sd, D_iota_sd, D_main_all)))))
    E_main_all = _select(fire_iota, E_fire_iota,
                 _select(iota_str_r, E_iota_str,
                 _select(iota_stuck_r, E_iota_stuck,
                 _select(iota_build_r, E_iota_build,
                 _select(iota_sd, E_iota_sd, E_main_all)))))
    F_main_all = _select(fire_iota, F_fire_iota,
                 _select(iota_str_r, F_iota_str,
                 _select(iota_stuck_r, F_iota_stuck,
                 _select(iota_build_r, F_iota_build,
                 _select(iota_sd, F_iota_sd, F_main_all)))))

    # WP4 quot branches (disjoint from the iota branches: the head metadata
    # kind is CK_QUOT, never CK_RECURSOR).
    A_main_all = _select(fire_quot, A_fire_quot,
                 _select(quot_stuck_r, A_quot_stuck,
                 _select(quot_go, A_quot_go,
                 _select(quot_sd, A_quot_sd, A_main_all))))
    B_main_all = _select(fire_quot, B_fire_quot,
                 _select(quot_stuck_r, B_quot_stuck,
                 _select(quot_go, B_quot_go,
                 _select(quot_sd, B_quot_sd, B_main_all))))
    C_main_all = _select(fire_quot, C_fire_quot,
                 _select(quot_stuck_r, C_quot_stuck,
                 _select(quot_go, C_quot_go,
                 _select(quot_sd, C_quot_sd, C_main_all))))
    D_main_all = _select(fire_quot, D_fire_quot,
                 _select(quot_stuck_r, D_quot_stuck,
                 _select(quot_go, D_quot_go,
                 _select(quot_sd, D_quot_sd, D_main_all))))
    E_main_all = _select(fire_quot, E_fire_quot,
                 _select(quot_stuck_r, E_quot_stuck,
                 _select(quot_go, E_quot_go,
                 _select(quot_sd, E_quot_sd, E_main_all))))
    F_main_all = _select(fire_quot, F_fire_quot,
                 _select(quot_stuck_r, F_quot_stuck,
                 _select(quot_go, F_quot_go,
                 _select(quot_sd, F_quot_sd, F_main_all))))

    # pop-task: E=1 under a TASK frame → drop the frame, keep the result
    A2 = _select(is_walk_frame, A_walk,
         _select(is_compute, A_comp,
         _select(is_build, A_build,
         _select(is_iota_build, A_iota_b,
         _select(is_cs_build, A_cs_build,
         _select(is_cs_build_p2, A_p2_build,
         _select(cont_mode, A_c,
         _select(pop_task, SA,
         _select(is_infer_frame, A_i,
         _select(is_defeq_frame, A_d,
         _select(is_level_frame, A_l,
         _select(resume_mode, A_r,
         _select(ck_kick, A_k, A_main_all)))))))))))))
    B2 = _select(is_walk_frame, B_walk,
         _select(is_compute, B_comp,
         _select(is_build, B_build,
         _select(is_iota_build, B_iota_b,
         _select(is_cs_build, B_cs_build,
         _select(is_cs_build_p2, B_p2_build,
         _select(cont_mode, B_c,
         _select(pop_task, SB,
         _select(is_infer_frame, B_i,
         _select(is_defeq_frame, B_d,
         _select(is_level_frame, B_l,
         _select(resume_mode, B_r,
         _select(ck_kick, B_k, B_main_all)))))))))))))
    C2 = _select(is_walk_frame, C_walk,
         _select(is_compute, C_comp,
         _select(is_build, C_build,
         _select(is_iota_build, C_iota_b,
         _select(is_cs_build, C_cs_build,
         _select(is_cs_build_p2, C_p2_build,
         _select(cont_mode, C_c,
         _select(pop_task, SC,
         _select(is_infer_frame, C_i,
         _select(is_defeq_frame, C_d,
         _select(is_level_frame, C_l,
         _select(resume_mode, C_r,
         _select(ck_kick, C_k, C_main_all)))))))))))))
    D2 = _select(is_walk_frame, D_walk,
         _select(is_compute, D_comp,
         _select(is_build, D_build,
         _select(is_iota_build, D_iota_b,
         _select(is_cs_build, D_cs_build,
         _select(is_cs_build_p2, D_p2_build,
         _select(cont_mode, D_c,
         _select(pop_task, frV2,
         _select(is_infer_frame, D_i,
         _select(is_defeq_frame, D_d,
         _select(is_level_frame, D_l,
         _select(resume_mode, D_r,
         _select(ck_kick, D_k, D_main_all)))))))))))))
    E2 = _select(is_walk_frame, E_walk,
         _select(is_compute, E_comp,
         _select(is_build, E_build,
         _select(is_iota_build, E_iota_b,
         _select(is_cs_build, E_cs_build,
         _select(is_cs_build_p2, E_p2_build,
         _select(cont_mode, E_c,
         _select(pop_task, SE,
         _select(is_infer_frame, E_i,
         _select(is_defeq_frame, E_d,
         _select(is_level_frame, E_l,
         _select(resume_mode, E_r,
         _select(ck_kick, E_k, E_main_all)))))))))))))
    F2 = _select(is_walk_frame, F_walk,
         _select(is_compute, F_comp,
         _select(is_build, F_build,
         _select(is_iota_build, F_iota_b,
         _select(is_cs_build, F_cs_build,
         _select(is_cs_build_p2, F_p2_build,
         _select(cont_mode, F_c,
         _select(pop_task, SF,
         _select(is_infer_frame, F_i,
         _select(is_defeq_frame, F_d,
         _select(is_level_frame, F_l,
         _select(resume_mode, F_r,
         _select(ck_kick, F_k, F_main_all)))))))))))))

    # ── card 014 P2 hit commit (whnf memo) ───────────────────────────────────
    # Outermost over every mode/arm select: a hit REPLACES this beat's
    # commit with the delivery form (whnf_deliver's shape: result closure,
    # C/F kept, D=caller, E=1).  Co-firing dispatch emitters on a hit beat
    # write DEAD tokens (nothing points at them: the hit commit carries no
    # c1/c2-relative address, every pointer is absolute/register — the
    # M2-03 stride trap cannot fire here, 010-M M4-01 memo).
    # Write gate is VALUE-gated: D2 == the frame's own caller under the
    # WHNF frame == "this beat delivers to the caller" — whnf_deliver and
    # pop-under-whnf both commit D=frV2, and any co-firing push that wins
    # the commit makes D2 ≠ frV2, so no hand-copied busy mask is needed
    # (the defeq P1 arm cannot co-fire: disjoint frame kinds).  Hits do
    # NOT refresh (same key ⇒ same value by determinism; keeps the hit
    # beat emission-free).  Soft-bypass exits (wf_soft / nat_soft jump
    # from the WALK/NAT frame straight to the whnf caller) are NOT
    # captured — the same accounting as the P2 recon probe's pops.
    if VM014_WMEMO:
        # A hit must never swallow a reject: fold ¬reject into the gate.
        # Every rej_* component is frame-mode gated (walk/NAT/ST/INFER/
        # DEFEL/CHECK channels), so under a WHNF-frame beat the sum is 0
        # anyway — this is a belt for the merge point, not a behavior
        # change (010-M M4-01 memo, judgment-safety argument ④).
        _rej_p2 = (rej_c + rej_r + rej_i + rej_l + rej_n + rej_s + rej_q
                   + rej_p + rej_lit + rej_o)
        whnf_cache = reglu(whnf_cache0, One - _geq_expr(_rej_p2, One))
        A2 = _select(whnf_cache, wvx, A2)
        B2 = _select(whnf_cache, wve, B2)
        C2 = _select(whnf_cache, SC, C2)
        D2 = _select(whnf_cache, frV2, D2)
        E2 = _select(whnf_cache, One, E2)
        F2 = _select(whnf_cache, SF, F2)
        # M6 (b): write ONLY AT A PURE EXIT — SC==0 ∧ SF==0 at the
        # delivering beat.  The hit replays C=SC, F=SF of the HIT beat,
        # which its entry gates pin to (0,0); an entry recorded at an
        # exit whose chain was NOT clean would therefore hand a future
        # clean-entry replay a different caller-visible C/F than its own
        # real run produced (010-M M4-01 R1, made concrete by the
        # string ofList breach: reject@336 even after the kind-check
        # fix).  Coverage cost is accepted: chain-growth completions
        # become safe misses (contract completeness > hit rate, ADR 017).
        _wc_w = reglu(is_whnf_frame,
                reglu(_eq_expr(D2, frV2),
                reglu(One - whnf_cache,
                reglu(_eq_expr(SC, Zero), _eq_expr(SF, Zero)))))
        halt = reglu(One - whnf_cache, halt)
    else:
        whnf_cache = Zero
    halt = halt + reglu(ret_pending, One - has_frame) + ck_accept + ax_done

    # ── emission merge ──────────────────────────────────────────────────────
    # M2 frame emissions
    m2_chk = reglu(cg[I_CHK], i_more) + args_walk
    em_frame_m2 = (cg[I_FN] + cg[I_PI] + cg[I_ARG] + m2_chk + cg[I_LAMDOM]
                   + cg[I_LAMSORT] + cg[I_PIDOM] + cg[I_PIS1] + cg[I_PIL1]
                   + cg[I_PIS2] + cg[I_PIL2] + cg[I_SORTEM] + cg[I_LETV]
                   + cg[I_LETD] + cg[D_SORT2] + cg[D_BV2] + bv_nb + cg[D_SW2]
                   + spa_next
                   + sw_loop + sw_pi + bv_d
                   + cg[PI_T] + cg[PI_TY] + cg[PI_LVL] + cg[PI_D] + cg[ST_SP]
                   # F8: `et_sfall` (ETA_S with a non-Pi whnf'd s_ty) mirrors
                   # `et_fall` exactly (both push ST(ST_ES, caller=oo-frame));
                   # it was missing here so the machine set D=c1 while writing
                   # no frame -> D landed on the step's own STATE token ->
                   # period-1 livelock (Lst.below PProd witness chains, 009/F8).
                   + et_app + et_fall + et_sfall + cg[ETA_T] + et_spi + et_domok
                   + cg[ETA_LINK] + cg[ETA_LNK2]
                   + es_app + cg[ES_T] + es_domok + es_next0
                   + lit_cont + sp_both + sp_fin2 + nc_step + nct_done + ncs_done + nc_fail
                   + em_more + peel_end + lam_i + pi_i + let_i + sort_i
                   + deq_lit + deq_lit_str_eq + deq_bvar + deq_mdata + deq_tpc
                   + deq_succ
                   + proj_same + bind_k + deq_xpi + deq_sw0 + lvl_succ
                   + de_prj_f + deq_refl + deq_hargs + de_att_f
                   + ck_g0 + ck_g1_ok
                   + cg[CK_TY] + ck_kick
                   + proj_i + cg[IP_TY] + ip_setup + ip_more
                   # WP5-E5: pr_str re-pushes [ST(I_PROJ), WHNF(expansion)].
                   # WP5-E3b: es_str converts the ST frame into a DEFEQ frame.
                   + pr_str + es_str
                   # P7 unit_like: es_no kicks off ST_UL (fr1); ST_UL/UL_W emit
                   # fr1+fr2 (ST + INFER/WHNF sub-task); ul_yes emits fr1+fr2
                   # (ST + INFER ns); UL_D emits fr1 (DEFEQ). ul_no is a bare
                   # verdict (no frame), like es_nextfail.
                   + es_no + cg[ST_UL] + cg[UL_W] + ul_yes + cg[UL_D])
    em_frame2_m2 = (cg[I_FN] + cg[I_PI] + cg[I_ARG] + m2_chk + cg[I_LAMDOM]
                    + cg[I_LAMSORT] + cg[I_PIDOM] + cg[I_PIS1] + cg[I_PIL1]
                    + cg[I_PIS2] + cg[I_LETV] + cg[I_LETD] + cg[D_SORT2] + cg[D_BIND2]
                    + cg[D_TPC2] + cg[D_BV2] + cg[D_XPI2] + cg[D_SW2] + spa_next
                    + sp_fin2
                    + peel_end + lam_i + pi_i + let_i + bvar_i
                    + deq_bvar + deq_tpc + bind_k + deq_xpi
                    + deq_sw0 + proj_same + de_prj_f + deq_refl
                    + deq_hargs + de_att_f
                    + ck_g0 + ck_g1_ok
                    + cg[PI_T] + cg[PI_TY] + pl_prop
                    + et_app + cg[ETA_T] + et_spi
                    + es_app + cg[ES_T] + es_domok + es_next0
                    + cg[CK_TY] + ck_kick
                    + proj_i + cg[IP_TY]
                    + pr_str
                    + cg[ST_UL] + cg[UL_W] + ul_yes)

    def m2_merge(c_addr, r_addr, i_addr, d_addr, l_addr, k_addr, l_expr, base):
        """Pick an emission payload across the disjoint M2 modes."""
        return _select(cont_mode, c_addr,
               _select(resume_mode, r_addr,
               _select(is_infer_frame, i_addr,
               _select(is_defeq_frame, d_addr,
               _select(lvl_succ, l_addr,
               _select(ck_kick, k_addr, base))))))

    frame_task = m2_merge(fr1_task, fr1_task_r, fr1_task_i, fr1_task_d,
                          fr1_task_l, fr1_task_k, None, frame_task)
    frame_V1 = _select(fire_quot, Expression({_one_dim: OP_QUOT}),
               m2_merge(fr1_V1, fr1_V1_r, fr1_V1_i, fr1_V1_d, Zero,
                        fr1_V1_k, None,
                        _select(fire_iota, One * OP_IOTA,
                        _select(iota_build_r, One * OP_IOTA, frame_V1))))
    frame_V2 = _select(fire_quot, c2,
               m2_merge(fr1_V2, fr1_V2_r, fr1_V2_i, fr1_V2_d, fr1_V2_l,
                        fr1_V2_k, None,
                        _select(fire_iota, c2,
                        # WP5-E2: iota_str_r re-pushes the SAME control frame
                        # (V1=frV1/X=1/E2=frE2/F2=frF2 are the defaults or
                        # below) with the scratch as slot 2 (frame2 defaults
                        # already copy nbV1/nbV2/X=2 from the old pair).
                        _select(iota_str_r, c2,
                        _select(iota_build_r, frV2, frame_V2)))))
    frame_X = _select(fire_quot, One,
              m2_merge(fr1_X, fr1_X_r, fr1_X_i, fr1_X_d, fr1_X_l,
                       fr1_X_k, None,
                       _select(fire_iota, One,
                       _select(iota_str_r, One,
                       _select(iota_build_r, One * 2, frame_X)))))
    # frame_E2 also carries the proj_setup ST's saved enclosing pend (SC):
    # a projection in function position must still apply its pending args
    # after the child sub-whnf (I_PROJ restores it).  proj_setup is main-mode
    # focus=Proj; the iota states below require focus=Const, so they are
    # disjoint and the injection cannot collide.  WP4: fire_quot saves the
    # original quotient spine root here for the stuck delivery.
    frame_E2 = _select(reglu(is_compute, em_frame_c), frame_E2_c,
               _select(d23_bitop, c2,
               _select(d23_gcd, frV1,
               _select(d23_shr + d23_shl, frV1,
               _select(fire_quot, SF,
               m2_merge(fr1_E2, fr1_E2_r, fr1_E2_i, fr1_E2_d, Zero,
                        fr1_E2_k, None,
                        _select(fire_iota, SF,
                        _select(iota_str_r, frE2,
                        _select(iota_build_r, gi_root,
                        _select(fire_rec, SF,
                        _select(fire_caseson, SF,
                        _select(build_r, c1 + One * 2,
                        _select(cs_succ_r, c1 + One * 2,
                        _select(fire_p2, SF,
                        _select(p2_succ_r, c1 + One * 2,
                        _select(fire_bool, SF,
                        _select(p2_succ_r, c1 + One * 2,
                        _select(proj_setup, SC, Zero))))))))))))))))))
    # WALK frames carry the bvar's focus env (env0) in their free F2 slot:
    # em_frame_bvar seeds it with SB, hops copy it forward. mk_stuck reads it
    # as the stuck marker's closure env (see the WALK section). All frF2
    # readers are is_st_frame-gated, so a nonzero WALK F2 cannot misfire.
    # WP4: fire_quot stores the original pend head (SC) so the delivery can
    # re-read f = args[arg_pos] and the extras after the mk sub-whnf (the live
    # SC can be clobbered by a nested nat compute — V7.5c-M5).
    frame_F2 = _select(reglu(is_compute, em_frame_c), frame_F2_c,
               _select(d23_bitop, frV1,
               _select(d23_gcd, v_done,
               _select(d23_shr + d23_shl, v_done,
               _select(fire_quot, SC,
               m2_merge(fr1_F2, fr1_F2_r, fr1_F2_i, fr1_F2_d, Zero,
                        fr1_F2_k, None,
                        _select(fire_iota, SC,
                        _select(iota_str_r, frF2,
                        _select(iota_build_r, frF2,
                        _select(fire_rec, SC,
                        _select(fire_caseson, SC,
                        _select(build_r, frF2,
                        _select(cs_succ_r, frF2,
                        _select(fire_p2, SC,
                        _select(fire_bool, SC,
                        _select(p2_succ_r, frF2,
                        _select(em_frame_bvar, SB,
                        _select(walk_more, frF2,
                                reglu(proj_setup,
                                      Expression({_one_dim: I_PROJ}))))))))))))))))))))
    frame2_task = m2_merge(fr2_task, fr2_task_r, fr2_task_i, fr2_task_d,
                           Zero, fr2_task_k, None, frame2_task)
    frame2_V1 = _select(fire_quot, One * 3,
                m2_merge(fr2_V1, fr2_V1_r, fr2_V1_i, fr2_V1_d, Zero,
                         fr2_V1_k, None,
                         _select(fire_iota, fV0, frame2_V1)))
    frame2_V2 = _select(fire_quot, SD,
                m2_merge(fr2_V2, fr2_V2_r, fr2_V2_i, fr2_V2_d, Zero,
                         fr2_V2_k, None,
                         _select(fire_iota, SD, frame2_V2)))
    frame2_X = _select(fire_quot, q_mkpos,
               m2_merge(fr2_X, fr2_X_r, fr2_X_i, fr2_X_d, Zero,
                        fr2_X_k, None, frame2_X))
    frame2_E2 = m2_merge(fr2_E2, fr2_E2_r, fr2_E2_i, fr2_E2_d, Zero,
                         fr2_E2_k, None, reglu(proj_setup, One))
    frame2_F2 = m2_merge(fr2_F2, fr2_F2_r, fr2_F2_i, fr2_F2_d, Zero,
                         fr2_F2_k, None, Zero)

    # links: M2 payloads win when an M2 link fires; iota build steps 2/3
    # (P6.5) emit the e1..e4 chain through the same slots.
    m2_l1 = em_link1_c + em_link1_d
    m2_l2 = em_link2_c + em_link2_d
    link_V0 = _select(em_link_rec, link1_V0_rec,
              _select(m2_l1, link1_V0, link_V0))
    link_V1 = _select(em_link_rec, link1_D_rec,
              _select(m2_l1, link1_D, link_V1))
    link_prev = _select(em_link_rec, link1_P_rec,
                _select(m2_l1, link1_P, link_prev))
    link_env = _select(em_link_rec, link1_E_rec,
               _select(m2_l1, link1_E, link_env))
    link_flag = reglu(link1_F, m2_l1)
    link_F2 = reglu(link1_F2, m2_l1)            # M3 binder identity on link1
    link2_V0 = _select(em_link2_rec, link2_V0_rec,
               _select(m2_l2, link2_V0, Zero))
    link2_V1 = _select(em_link2_rec, link2_D_rec,
               _select(m2_l2, link2_D, Zero))
    link2_prev = _select(em_link2_rec, link2_P_rec,
                 _select(m2_l2, link2_P, Zero))
    link2_env = _select(em_link2_rec, link2_E_rec,
                _select(m2_l2, link2_E, Zero))
    link2_flag = reglu(link2_F, m2_l2)
    link2_F2m = reglu(link2_F2, m2_l2)          # M3 binder identity on link2
    em_link = em_link + m2_l1 + em_link_rec
    em_link2 = m2_l2 + em_link2_rec

    # raw slot (position POS+1 when present)
    # WP4: the quot_go delivery emits the stuck-result spine root App(f, a)
    # here; the accompanying PEND for `a` lands at POS+2.
    # ── card 014 P1 cache-write arm (ADR 017) ────────────────────────────────
    # Every DEFEQ frame completing TRUE re-emits its entry pair on the raw
    # slot as a T_DEFCACHE token (kernel: the is_def_eq wrapper writes the
    # ENTRY pair after each True core return, :1247-1252; False never
    # writes — `if (r)`).  Two beats, structurally disjoint (ret_pending
    # splits them): ①the dispatch step that commits True directly (deq_same,
    # deq_const, deq_sort-with-True-verdict, or a cache-hit passthrough —
    # the rewrite refreshes latest, benign under key shadowing); ②the pop
    # beat where a verdict computed in a child/sink chain arrives under the
    # DEFEQ frame (SA = verdict).  The raw payload select is the FIRST
    # _select layer: every existing raw emitter is frame-kind-disjoint from
    # is_defeq_frame (cont/resume = ST, em_raw_i = INFER, rec/cs/p2/quot_go
    # = NAT), so no beat double-owns the slot.  Fields: V0 = t_pos (key),
    # V1 = t_env, V2 = s_pos, X = s_env, E2 = raw_E2_c = 0 (its only
    # nonzero gate cg[I_LAMBODY] is a cont-mode beat).
    _raw_emitters = (em_raw_c + em_raw_r + em_raw_i + em_raw_rec + em_raw_cs
                     + em_raw_p2)
    if VM014_CACHE:
        _dc_direct = deq_same + deq_const + defeq_cache + \
            reglu(deq_sort, _deq_sort_verdict)
        # _geq collapse: deq_same and deq_const fire TOGETHER on a
        # same-closure const pair; _select needs a 0/1 condition.
        # BUSY GATE (d6@468 livelock, 010-M M2-03): a raw token on a
        # frame-pushing beat shifts every later slot by +1 and the frame
        # arms address the push by c1=POS+1/c2=POS+2 — deq_same co-fires
        # with kind arms on same-closure LAM/PI pairs (bind_k/fr1@POS+1,
        # fr2@POS+2, D=c2), and the raw beat then lands D on the WRONG
        # token (period-1 stall).  Write only on beats that push nothing:
        # deq_lit_str_ne and deq_sort-False are pure commits and stay out
        # of the busy mask (they also never enter _dc_direct).
        _dc_busy = (deq_lit + deq_lit_str_eq + deq_bvar + deq_mdata
                    + deq_succ + deq_refl + deq_hargs + deq_tpc + proj_same
                    + bind_k + deq_xpi + deq_sw0)
        _dc_w = reglu(reglu(_geq_expr(_dc_direct, One),
                            One - _geq_expr(_dc_busy, One)),
                      One - ret_pending) + \
            reglu(pop_task, reglu(is_defeq_frame, _geq_expr(SA, One)))
        em_raw = _raw_emitters + quot_go + _dc_w
        _t_defcache = Expression({_one_dim: T_DEFCACHE})
        raw_K = _select(_dc_w, _t_defcache,
                _select(quot_go, Expression({_one_dim: K_APP}),
                _select(is_cs_build_p2, raw_K_p2,
                _select(is_cs_build, raw_K_cs,
                _select(is_build, raw_K_rec,
                _select(cont_mode, raw_K_c,
                _select(resume_mode, raw_K_r, raw_K_i)))))))
        raw_V0 = _select(_dc_w, frV1,
                 _select(quot_go, q_f_pos,
                 _select(is_cs_build_p2, raw_V0_p2,
                 _select(is_cs_build, raw_V0_cs,
                 _select(is_build, raw_V0_rec,
                 _select(cont_mode, raw_V0_c,
                 _select(resume_mode, raw_V0_r, raw_V0_i)))))))
        raw_V1 = _select(_dc_w, frX,
                 _select(quot_go, q_a_pos,
                 _select(is_cs_build_p2, raw_V1_p2,
                 _select(is_cs_build, raw_V1_cs,
                 _select(is_build, raw_V1_rec, raw_V1_c)))))
        raw_V2 = _select(_dc_w, frE2, raw_V2_r)
        raw_X = _select(_dc_w, frF2,
                _select(cont_mode, raw_X_c, raw_X_r))
        raw_E2 = raw_E2_c
    else:
        em_raw = _raw_emitters + quot_go
        raw_K = _select(quot_go, Expression({_one_dim: K_APP}),
                _select(is_cs_build_p2, raw_K_p2,
                _select(is_cs_build, raw_K_cs,
                _select(is_build, raw_K_rec,
                _select(cont_mode, raw_K_c,
                _select(resume_mode, raw_K_r, raw_K_i))))))
        raw_V0 = _select(quot_go, q_f_pos,
                 _select(is_cs_build_p2, raw_V0_p2,
                 _select(is_cs_build, raw_V0_cs,
                 _select(is_build, raw_V0_rec,
                 _select(cont_mode, raw_V0_c,
                 _select(resume_mode, raw_V0_r, raw_V0_i))))))
        raw_V1 = _select(quot_go, q_a_pos,
                 _select(is_cs_build_p2, raw_V1_p2,
                 _select(is_cs_build, raw_V1_cs,
                 _select(is_build, raw_V1_rec, raw_V1_c))))
        raw_V2 = raw_V2_r
        raw_X = _select(cont_mode, raw_X_c, raw_X_r)
        raw_E2 = raw_E2_c

    # ── card 014 P2 whnf-memo write arm (raw slot) ────────────────────────
    # _wc_w is value-gated on "this beat delivers to the whnf caller"
    # (D2 == frV2 under is_whnf_frame), structurally disjoint from every
    # other raw owner: P1's _dc_w needs is_defeq_frame, cont/resume need
    # the ST frame, em_raw_i the INFER frame, rec/cs/p2/quot_go the NAT
    # frame — none of those can hold D on a WHNF frame.  Payload: V0 = the
    # input focus pos (attention key), V1 = input env, V2 = soft flag,
    # X/E2 = the DELIVERED closure read off the committed A2/B2 (kernel:
    # m_whnf.insert AFTER the loop, :763/:766/:772).
    if VM014_WMEMO:
        em_raw = em_raw + _wc_w
        _t_whnfcache = Expression({_one_dim: T_WHNFCACHE})
        raw_K = _select(_wc_w, _t_whnfcache, raw_K)
        raw_V0 = _select(_wc_w, frV1, raw_V0)
        raw_V1 = _select(_wc_w, frX, raw_V1)
        raw_V2 = _select(_wc_w, frE2, raw_V2)
        raw_X = _select(_wc_w, A2, raw_X)
        raw_E2 = _select(_wc_w, B2, raw_E2)

    # pend: infer peel shares the main-mode payloads (fV1/SC/SB)
    # WP4 quot_go emits the application argument `a` (with the mk closure env)
    # on top of the already-linked extras chain.
    em_pend = em_pend + em_pend_r + em_pend_i + is_iota_build + quot_go
    pend_V0 = _select(quot_go, q_a_pos, _select(is_iota_build, gi_pend_V0, pend_V0))
    pend_prev = _select(quot_go, q_extras,
                _select(is_iota_build, gi_pend_prev, pend_prev))
    pend_env = _select(quot_go, SB,
               _select(is_iota_build, gi_pend_env, pend_env))

    em_frame = (walk_more - walk_fail + em_frame_bvar + fire1 + fire2
                + d12 + d23_work + dn1 + em_frame_c + em_frame_m2 + proj_setup
                + fire_rec + build_r + fire_caseson + cs_succ_r
                + fire_p2 + fire_bool + fire_iota + iota_build_r
                + iota_str_r + fire_quot)
    em_frame2 = (fire2 + d12 + em_frame2_m2 + proj_setup + fire_iota
                 + iota_str_r + fire_quot)

    reject = rej_c + rej_r + rej_i + rej_l + rej_n + rej_s + rej_q + rej_p + rej_lit + rej_o
    # WP7-G: 6 = decl root fvar/mvar (kernel "declaration has free
    # variables"), 5 = typeExpected (kernel ensure_sort throw), 7 =
    # unsafe/partial constant use in a safe context (kernel infer_constant
    # throw, K/type_checker.cpp:110-117 → .other class). Existing
    # observables unchanged: everything else keeps its old 4/1 value.
    # Card 010 G02 adds 8 = theorem_type_is_not_prop (K/environment.cpp:200-
    # 202), placed directly below 5 because is_prop runs right after
    # ensure_sort in add_theorem.  The two arms are step-exclusive anyway
    # (g1_fail needs !ck_g1_ok, g3 needs ck_g1_ok), and 7 fires on an INFER
    # step the machine only reaches after this arm accepted, so the chain
    # order records the kernel's check order rather than resolving a tie.
    reject_code = _select(safety_i, One * 7,
                  _select(g7, One * 6,
                  _select(g1_fail, One * 5,
                  _select(g3, One * 8,
                  _select(bad_i + lvl_bad, One * 4, One)))))

    # head/gap/dig/const emission merge (main + compute)
    head_V0 = _select(d23_work, n_out_d23,
              _select(dn1, n_out_dn1,
              _select(d23_bz_div, One,
              _select(reglu(ph13g, b13u), One,
                      head_V0_c))))
    head_V2 = _select(d23_work + dn1 + d23_bz_div, Zero, head_V2_c)
    head_X = _select(d23_work + dn1 + d23_bz_div, Zero, head_X_c)
    em_lithead = (reglu(d23_work, One - is_shr_d - is_gcd_d - is_shl_d) + reglu(dn1, One)
                  + reglu(d23_bz_div, One) + em_lithead_c)
    em_gap = (reglu(d23, is_pow_d) + reglu(d23_bz_div, One)
              + reglu(ph13g, b13u)
              + reglu(d23, reglu(is_divmod_d, One - is_bzero_d))
              + reglu(d23, is_bitop_d)
              + reglu(is_compute, reglu(done_s, reglu(borrowfam, underflow))))
    # litdig (before frame/head): every real digit step; litdig2 (after
    # head+gap): the fresh-chain digits (underflow, pow/div entry)
    em_litdig = em_litdig_c
    # pow's [1] acc head is emitted for EVERY exp incl. 0 (nat_pow(x,0)=1,
    # K:674), so its digit must not share divmod's b=0 exclusion (pre-WP6 bug:
    # `pow x 0` delivered a headless-digit chain).
    em_litdig2 = (reglu(d23, is_pow_d)
                  + reglu(d23, reglu(is_divmod_d, One - is_bzero_d))) \
        + reglu(d23_bz_div, One) + reglu(ph13g, b13u) \
        + reglu(d23, is_bitop_d) \
        + reglu(is_compute, reglu(done_s, reglu(borrowfam, underflow)))
    dig2_V0 = reglu(d23, is_pow_d + is_bitop_d)
    dig_V0 = dig_V0_c
    em_const = em_const_c

    # A root halt carrying a verdict (ret_pending: E=1, no caller frame) is
    # a defeq/infer return: the result is A itself, never a spine root.
    # Without this gate the stale pend-chain pointers left in C/F by a nested
    # D_SP1 string peel hijack result_pos through A_done's result_spine
    # select (WP5-E3b: es_str_false reported the PEND token, not 0).
    # The gate MUST stay binary: halt can reach 2 on this channel — a literal
    # INFER delivers its emitted Const(String) at root with E=1, and the stuck
    # focus adds `complete` on top of `ret_pending` (halt = 1+1).  Scaling a
    # non-binary gate would linearly extrapolate _select into 2*SA.
    A_res = _select(reglu(ret_pending, One - has_frame), SA, A_done)

    outputs = {
        "done": out(halt, "o_done"),
        "result_pos": out(A_res, "o_result_pos"),
        "em_pend": out(em_pend, "o_em_pend"),
        "em_link": out(em_link, "o_em_link"),
        "em_frame": out(em_frame, "o_em_frame"),
        "em_frame2": out(em_frame2, "o_em_frame2"),
        "em_lithead": out(em_lithead, "o_em_lithead"),
        "em_gap": out(em_gap, "o_em_gap"),
        "em_litdig": out(em_litdig, "o_em_litdig"),
        "em_const": out(em_const, "o_em_const"),
        "pend_V0": out(pend_V0, "o_pend_v0"),
        "pend_prev": out(pend_prev, "o_pend_prev"),
        "pend_env": out(pend_env, "o_pend_env"),
        "link_V0": out(link_V0, "o_link_v0"),
        "link_V1": out(link_V1, "o_link_v1"),
        "link_prev": out(link_prev, "o_link_prev"),
        "link_env": out(link_env, "o_link_env"),
        "frame_task": out(frame_task, "o_frame_task"),
        "frame_V1": out(frame_V1, "o_frame_v1"),
        "frame_V2": out(frame_V2, "o_frame_v2"),
        "frame_X": out(frame_X, "o_frame_x"),
        "frame2_task": out(frame2_task, "o_frame2_task"),
        "frame2_V1": out(frame2_V1, "o_frame2_v1"),
        "frame2_V2": out(frame2_V2, "o_frame2_v2"),
        "frame2_X": out(frame2_X, "o_frame2_x"),
        "head_V0": out(head_V0, "o_head_v0"),
        "head_V2": out(head_V2, "o_head_v2"),
        "head_X": out(head_X, "o_head_x"),
        "dig_V0": out(dig_V0, "o_dig_v0"),
        "em_litdig2": out(em_litdig2, "o_em_litdig2"),
        "dig2_V0": out(dig2_V0, "o_dig2_v0"),
        "const_cid": out(const_cid, "o_const_cid"),
        "em_raw": out(em_raw, "o_em_raw"),
        "raw_K": out(raw_K, "o_raw_k"),
        "raw_V0": out(raw_V0, "o_raw_v0"),
        "raw_V1": out(raw_V1, "o_raw_v1"),
        "raw_V2": out(raw_V2, "o_raw_v2"),
        "raw_X": out(raw_X, "o_raw_x"),
        "raw_E2": out(raw_E2, "o_raw_e2"),
        "em_link2": out(em_link2, "o_em_link2"),
        "link2_V0": out(link2_V0, "o_link2_v0"),
        "link2_V1": out(link2_V1, "o_link2_v1"),
        "link2_prev": out(link2_prev, "o_link2_prev"),
        "link2_env": out(link2_env, "o_link2_env"),
        "link_flag": out(link_flag, "o_link_flag"),
        "link2_flag": out(link2_flag, "o_link2_flag"),
        "link_F2": out(link_F2, "o_link_f2"),
        "link2_F2": out(link2_F2m, "o_link2_f2"),
        "frame_E2": out(frame_E2, "o_frame_e2"),
        "frame_F2": out(frame_F2, "o_frame_f2"),
        "frame2_E2": out(frame2_E2, "o_frame2_e2"),
        "frame2_F2": out(frame2_F2, "o_frame2_f2"),
        "reject": out(reject, "o_reject"),
        "dbg_complete": out(complete, "o_dbg_complete"),
        "dbg_dn1": out(dn1, "o_dbg_dn1"),
        "dbg_d12": out(d12, "o_dbg_d12"),
        "dbg_d23": out(d23, "o_dbg_d23"),
        "dbg_fire1": out(fire1, "o_dbg_fire1"),
        "dbg_fire2": out(fire2, "o_dbg_fire2"),
        "dbg_main": out(main_mode, "o_dbg_main"),
        "dbg_natsoft": out(nat_soft, "o_dbg_natsoft"),
        "dbg_nathard": out(nat_hard, "o_dbg_nathard"),
        "dbg_frv0": out(frV0, "o_dbg_frv0"),
        "dbg_defeq": out(is_defeq_frame, "o_dbg_defeq"),
        "dbg_st": out(is_st_frame, "o_dbg_st"),
        "dbg_efc": out(em_frame_c, "o_dbg_efc"),
        "dbg_efm2": out(em_frame_m2, "o_dbg_efm2"),
        "dbg_gsum": out(sum(g.values()), "o_dbg_gsum"),

        "dbg_deqfall": out(deq_fall, "o_dbg_deqfall"),
        "reject_code": out(reject_code, "o_reject_code"),
        "A": out(A2, "o_a"),
        "B": out(B2, "o_b"),
        "C": out(C2, "o_c"),
        "D": out(D2, "o_d"),
        "E": out(E2, "o_e"),
        "F": out(F2, "o_f"),
    }

    graph = ProgramGraph(input_tokens={}, output_tokens={})
    graph.all_dims = list(_all_dims)
    graph.all_lookups = list(_all_lookups)
    return graph, outputs
