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

from lean_kernel.alm_graph import (
    InputDimension, Expression, ProgramGraph, reset_graph,
    persist, reglu, _one_dim, _position_dim, _all_dims, _all_lookups,
)
from lean_kernel.alm_p2 import fetch_by_position
from lean_vm.primitives import (
    _kind_eq_raw, _select, _geq_expr, _eq_expr,
)

from expr.model import (
    K_BVAR, K_FVAR, K_MVAR, K_SORT, K_CONST, K_APP, K_LAM, K_PI, K_LET,
    K_LIT, K_MDATA, K_PROJ, LIT_NAT,
    KL_ZERO, KL_SUCC,
)
from expr.tokens import (
    T_FRAME, T_PEND, T_LINK, T_PI_CLO,
    TASK_WHNF, TASK_INFER, TASK_DEFEQ, TASK_LEVEL,
)

TASK_WALK = 3
TASK_NAT = 2
TASK_ST = 5

# nat op codes (expr/tokens.py NAT_OP_CODES)
OP_SUCC, OP_PRED, OP_ADD, OP_SUB = 1, 2, 3, 4
OP_MUL, OP_POW, OP_DIV, OP_MOD = 5, 6, 7, 8
OP_BEQ, OP_BLE = 9, 10

# toy-env constant ids (Encoder assigns cids by TOY_CONSTS order); the step
# graph needs them to emit Bool results and to read Nat.zero args.
CID_TRUE, CID_FALSE, CID_ZERO = 2, 3, 4
CID_NAT, CID_SUCC = 0, 5
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
 BV_ID) = range(32, 55)                     # bvar marker bid compare


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
    c1V0 = fetch_by_position([v0_], v1pos)[0]
    g1V0 = fetch_by_position([v0_], v1pos + One * 2 + SB * 2)[0]
    g2V0 = fetch_by_position([v0_], SA + One * 2 + SB * 2)[0]
    is_z1 = reglu(_kind_eq_raw(c1K, K_CONST, One),
                  _kind_eq_raw(c1V0, CID_ZERO, One))
    is_lit1 = _kind_eq_raw(c1K, K_LIT, One)
    n1 = _select(is_lit1, c1V0, One)   # zero-const: 1 digit (value 0)
    is_z2 = reglu(_kind_eq_raw(fK, K_CONST, One),
                  _kind_eq_raw(fV0, CID_ZERO, One))
    is_lit2 = _kind_eq_raw(fK, K_LIT, One)
    n2 = _select(is_lit2, fV0, One)   # zero-const: 1 digit (value 0)
    # C-head (acc / R / Q) and F-head (output chain) fields
    nC = fetch_by_position([v0_], SC)[0]
    aCC = fetch_by_position([v0_], SC + One * 2 + SB * 2)[0]
    nF = fetch_by_position([v0_], SF)[0]
    xF = fetch_by_position([x_], SF)[0]
    iF = Expression({fetch_by_position([v2_], SF)[0]: 1})  # row index i
    b0raw = fetch_by_position([v0_], SA + One * 2)[0]   # b chain digit 0
    bkJ = fetch_by_position([v0_], SA + One * 2 + SB * 2)[0]  # A digit at k
    # mul/pow cell: multiplier side (m) and addend side (x) chains
    m_head = _select(is_pow_o, frV2, nbV1)    # pow: frame V2 = round acc
    mL = fetch_by_position([v0_], m_head)[0]
    m_i_raw = fetch_by_position([v0_], m_head + One * 2 + iF * 2)[0]
    # pow: a = ST'.V1, with ST' pos threaded through the row head X field;
    # mul: b = A directly
    pow_st = fetch_by_position([x_], SF)[0]            # row head X = ST' pos
    pow_a = fetch_by_position([v1_], pow_st)[0]        # ST'.V1 = a chain head
    pow_a_V0 = fetch_by_position([v0_], pow_a)[0]
    pow_a_K = fetch_by_position([k_], pow_a)[0]
    is_za = reglu(_kind_eq_raw(pow_a_K, K_CONST, One),
                  _kind_eq_raw(pow_a_V0, CID_ZERO, One))
    is_la = _kind_eq_raw(pow_a_K, K_LIT, One)
    n_a = _select(is_la, pow_a_V0, One)
    caller_c = _select(arity2c, ncV2, frV2)   # arity-2: 2-hop / arity-1: direct
    x_head = _select(is_pow_o, pow_a, SA)     # pow: a (ST'.V1); mul: b (A)
    x_n = _select(is_pow_o, n_a, n2)
    xJ = fetch_by_position([v0_], x_head + One * 2 + (SB - iF) * 2)[0]

    has_frame = _geq_expr(SD, One)
    is_walk_frame = reglu(_kind_eq_raw(frV0, TASK_WALK, One), has_frame)
    is_st_frame = reglu(_kind_eq_raw(frV0, TASK_ST, One), has_frame)
    is_nat_frame = reglu(_kind_eq_raw(frV0, TASK_NAT, One), has_frame)
    is_compute = reglu(is_nat_frame, _geq_expr(frX, 3))
    # Phase 5 M2 task frames + the continuation protocol: a result in (A,B)
    # with E=1 is delivered through ST frames carrying a continuation id in
    # F2 (CONT mode); TASK frames (WHNF/INFER/DEFEQ/LEVEL) are popped.
    is_infer_frame = reglu(_kind_eq_raw(frV0, TASK_INFER, One), has_frame)
    is_defeq_frame = reglu(_kind_eq_raw(frV0, TASK_DEFEQ, One), has_frame)
    is_whnf_frame = reglu(_kind_eq_raw(frV0, TASK_WHNF, One), has_frame)
    is_level_frame = reglu(_kind_eq_raw(frV0, TASK_LEVEL, One), has_frame)
    is_task_frame = (is_infer_frame + is_defeq_frame + is_whnf_frame
                     + is_level_frame)
    ret_pending = reglu(_eq_expr(SE, One), One - is_walk_frame - is_compute)
    cont_mode = reglu(ret_pending, reglu(is_st_frame, _geq_expr(frF2, One)))
    resume_mode = reglu(One - ret_pending,
                        reglu(is_st_frame, _geq_expr(frF2, One)))
    st2_mode = cont_mode + resume_mode
    main_mode = (One - is_walk_frame - is_compute - is_infer_frame
                 - is_defeq_frame - is_level_frame - st2_mode)
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
    op_arity2 = reglu(_geq_expr(eX, OP_ADD), One - _geq_expr(eX, 11))
    has2 = _geq_expr(pV2, One)
    fire2 = reglu(reglu(natop, op_arity2), reglu(pend_nonempty, has2))
    fire1 = reglu(reglu(natop, op_arity1), pend_nonempty)

    const_stuck = reglu(is_const, One - const_delta - fire1 - fire2)

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
    dn1 = reglu(complete, reglu(is_nat_frame, _eq_expr(frX, One)))

    c1 = POS + One
    c2 = POS + One * 2
    c3 = POS + One * 3
    # M3 eta: a step may emit raw + link1 + link2 + frame (4 tokens), so the
    # frame lands at POS+4. Slot addressing is positional (emission order
    # raw,pend,link,link2,litdig,frame,frame2).
    c4 = POS + One * 4

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
    # closure. Parent is the ST carrying that cont id.
    par_bv = reglu(_kind_eq_raw(nbV0, TASK_ST, One),
                   _kind_eq_raw(nbF2, D_BV2, One)
                   + _kind_eq_raw(nbF2, D_BV3, One))
    mk_dq = reglu(walk_done, reglu(fE2, par_bv))
    mk_stuck = reglu(walk_done, reglu(fE2, reglu(One - par_infdq, One - par_bv)))
    A_walk = _select(wf_soft, nbV1,
            _select(walk_fail, fV2,
            _select(mk_dq, SA,
            _select(mk_stuck, SE,
            _select(walk_more, fV2,
                    fV0)))))                   # hop: next link / done: value
    B_walk = _select(wf_soft, nbX,
            _select(walk_fail, SB,
            _select(mk_dq, SB,
            _select(mk_stuck, SB,
                    fX))))
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
    A_d12, B_d12, C_d12, D_d12 = frV1, frX, Zero, c1
    E_d12, F_d12 = Zero, Zero

    # d23 (arg2 delivered) — per-op entry. At d23: D=ST', frV1 = v1 pos,
    # nbV1 = op; A = v_done = the b-side chain head.
    opg3d = _kind_eq_raw(nbV1, OP_ADD, One)
    opg4d = _kind_eq_raw(nbV1, OP_SUB, One)
    is_addsub_d = opg3d + opg4d
    is_mul_d = _kind_eq_raw(nbV1, OP_MUL, One)
    is_pow_d = _kind_eq_raw(nbV1, OP_POW, One)
    is_divmod_d = _kind_eq_raw(nbV1, OP_DIV, One) + _kind_eq_raw(nbV1, OP_MOD, One)
    n1_d23raw = fetch_by_position([v0_], frV1)[0]
    c1K_d23 = fetch_by_position([k_], frV1)[0]
    is_z1_d23 = reglu(_kind_eq_raw(c1K_d23, K_CONST, One),
                      _kind_eq_raw(n1_d23raw, CID_ZERO, One))
    is_lit1_d23 = _kind_eq_raw(c1K_d23, K_LIT, One)
    n1_d23 = _select(is_lit1_d23, n1_d23raw, One)
    n2_d23 = n2                                # A = v_done = b-side head
    b0_d23 = b0raw
    is_bzero_d = reglu(_eq_expr(n2_d23, One), _eq_expr(b0_d23, Zero))
    d23_work = reglu(d23, One - reglu(is_divmod_d, is_bzero_d))
    d23_bz_div = reglu(d23, reglu(is_divmod_d, reglu(is_bzero_d,
                                                      _kind_eq_raw(nbV1, OP_DIV, One))))
    d23_bz_mod = reglu(d23, reglu(is_divmod_d, reglu(is_bzero_d,
                                                     _kind_eq_raw(nbV1, OP_MOD, One))))
    # head V0 per op: add: max(n1,n2)+1; sub: n1; mul: n2+1; pow: 1;
    # div/mod: Q = [0] chain head
    n_out_d23 = _select(opg3d, _select(_geq_expr(n1_d23, n2_d23), n1_d23, n2_d23) + One,
               _select(opg4d, n1_d23,
               _select(is_mul_d, n2_d23 + One,
                       One)))
    A_d23 = _select(d23_bz_div, c1,
            _select(d23_bz_mod, frV1,
                    v_done))
    B_d23 = Zero
    C_d23 = _select(reglu(d23, reglu(is_divmod_d, One - is_bzero_d)), frV1, Zero)
    D_d23 = _select(d23_bz_div + d23_bz_mod, nbV2, c1)
    E_d23 = Zero
    F_d23 = _select(d23_work, c2, Zero)

    # dn1 (arity-1 delivered): push NAT(op, caller, 3); head for succ/pred
    n1_dn1raw = fV0
    is_z1_dn1 = reglu(_kind_eq_raw(fK, K_CONST, One),
                      _kind_eq_raw(fV0, CID_ZERO, One))
    is_lit1_dn1 = _kind_eq_raw(fK, K_LIT, One)
    n1_dn1 = _select(is_lit1_dn1, n1_dn1raw, One)
    n_out_dn1 = _select(_kind_eq_raw(frV1, OP_SUCC, One), n1_dn1 + One, n1_dn1)
    A_dn1, B_dn1, C_dn1, D_dn1 = v_done, Zero, Zero, c1
    E_dn1 = _select(_kind_eq_raw(frV1, OP_SUCC, One), Zero, One)  # pred: borrow
    F_dn1 = _select(_kind_eq_raw(frV1, OP_SUCC, One)
                    + _kind_eq_raw(frV1, OP_PRED, One), c2, Zero)

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
    done_bor = _geq_expr(SB + One, n1)
    done_beq = _select(_geq_expr(_geq_expr(SB + One, mx) + _geq_expr(mis, One),
                                 One), One, Zero)
    done_ble = _geq_expr(SB + One, mx)
    done_s = _select(addfam, done_add,
             _select(borrowfam, done_bor,
             _select(opg9, done_beq, done_ble)))
    underflow = reglu(borrowfam, reglu(done_s, c_b))
    bool_cond = _select(opg9, _eq_expr(mis, Zero),
                        One - _eq_expr(E_ble, One * 2))
    const_cid = _select(bool_cond, Expression({_one_dim: CID_TRUE}),
                        Expression({_one_dim: CID_FALSE}))
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
    A_c2, B_c2, C_c2, D_c2c = SF, Zero, Zero, ncV2
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
    nQ5 = fetch_by_position([v0_], xF)[0]     # R'.X = Q head -> its len
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
        Zero)
    D_comp = sel(
        ph3s, _select(done_s, caller_c, D_s),
        ph3c, sel(done_row,
                  sel(mul_done, D_c2c, pow_rdone, D_c3c, D_c1c),
                  D_c0),
        ph4g, sel(div_done, ncV2, sub_setup, D_4s, D_4n),
        ph5g, sel(done5, D_5d, D_5n),
        ph6g, sel(done6, D_6d, D_6n),
        ph10g, sel(done10, sel(is_bzero10, D_10z, D_10g), D_10n),
        ph13g, sel(done13, D_13d, D_13n),
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
        Zero)

    # compute emission flags/payloads
    em_litdig_c = (reglu(ph3s, addfam + borrowfam)
                   - reglu(ph3s, reglu(done_s, reglu(borrowfam, underflow)))
                   + reglu(ph3c, One)
                   + reglu(ph5g, One) + reglu(ph6g, One)
                   + reglu(ph13g, One - reglu(done13, neg13)))
    dig_V0_c = _select(ph3s, _select(reglu(done_s, underflow), Zero, dig_out),
               _select(ph3c, dig_cell,
               _select(ph5g, dig5,
               _select(ph6g, dig6,
               _select(ph13g, dig13, Zero)))))
    em_frame_c = (reglu(ph4g, sub_setup) + reglu(ph5g, done5)
                  + reglu(ph6g, done6) + reglu(ph10g, pow_go)
                  + reglu(ph3c, pow_rdone) + reglu(ph13g, done13))
    frame_V1_c = frV1
    frame_V2_c = _select(reglu(ph4g, sub_setup), frV2,
                _select(reglu(ph5g, done5), SF,
                _select(reglu(ph6g, done6), xF,
                _select(reglu(ph10g, pow_go), SF,
                _select(reglu(ph3c, pow_rdone), SF,
                        xF)))))
    frame_X_c = _select(reglu(ph4g, sub_setup), One * 5,
                _select(reglu(ph5g, done5), One * 6,
                _select(reglu(ph6g, done6), One * 4,
                _select(reglu(ph10g, pow_go), One * 3,
                _select(reglu(ph3c, pow_rdone), One * 13,
                        One * 10)))))
    em_lithead_c = (reglu(ph4g, sub_setup) + reglu(ph5g, done5)
                    + reglu(ph10g, pow_go)
                    + reglu(ph3c, reglu(done_row, row_cont + pow_rdone))
                    + reglu(ph3s, reglu(done_s, reglu(borrowfam, underflow)))
                    + reglu(ph13g, b13u))
    head_V0_c = _select(reglu(ph4g, sub_setup), head4_V0,
                _select(reglu(ph5g, done5), head5_V0,
                _select(reglu(ph10g, pow_go), head10_V0,
                _select(reglu(ph3c, reglu(done_row, row_cont + pow_rdone)),
                _select(pow_rdone, n2, head_row_V0),
                        Zero))))
    head_V2_c = _select(reglu(ph3c, reglu(done_row, row_cont)), i1, Zero)
    head_X_c = _select(reglu(ph4g, sub_setup), SF,
               _select(reglu(ph5g, done5), frV2,
               _select(reglu(ph10g, pow_go), frV2,
               _select(reglu(ph3c, reglu(done_row, row_cont + pow_rdone)), xF,
                       Zero))))
    em_const_c = reglu(ph3s, reglu(done_s, opg9 + opg10))

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
              _select(em_frame_c, frame_V1_c,
                      frV1)))))))))
    frame_V2 = _select(proj_setup, frV2,
              _select(walk_more, frV2,
              _select(em_frame_bvar, SD,
              _select(fire2, c2,
              _select(fire1, SD,
              _select(d12, c2,
              _select(d23_work, SD,
              _select(dn1, frV2,
              _select(em_frame_c, frame_V2_c,
                      frV2)))))))))
    frame_X = _select(proj_setup, SB,
              _select(walk_more, frX - One,
              _select(em_frame_bvar, fV0,
              _select(fire2, qX,
              _select(fire1, One,
              _select(d12, e_done,
              _select(d23_work, _select(is_pow_d, One * 10,
                                _select(is_divmod_d, One * 4, One * 3)),
              _select(dn1, One * 3,
              _select(em_frame_c, frame_X_c,
                      One * 3)))))))))
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
    tV0 = fetch_by_position([v0_], frV1)[0]
    tV1 = fetch_by_position([v1_], frV1)[0]
    tXf = fetch_by_position([x_], frV1)[0]
    tE2f = fetch_by_position([e2_], frV1)[0]
    sK = fetch_by_position([k_], frE2)[0]      # DEFEQ s side (frame E2)
    sV0 = fetch_by_position([v0_], frE2)[0]
    sV1 = fetch_by_position([v1_], frE2)[0]
    sXf = fetch_by_position([x_], frE2)[0]
    sE2f = fetch_by_position([e2_], frE2)[0]
    oV1, oX, oE2, oF2 = fetch_by_position([v1_, x_, e2_, f2_], frX)
    oV0 = fetch_by_position([v0_], oV1)[0]
    oK = fetch_by_position([k_], oV1)[0]       # orig t token kind
    oBd = fetch_by_position([v1_], oV1)[0]     # orig t body / level root
    oBdE = fetch_by_position([e2_], oV1)[0]    # orig t T_PI_CLO body env
    sBd = fetch_by_position([v1_], oE2)[0]     # orig s body
    sBdE = fetch_by_position([e2_], oE2)[0]
    sDom = fetch_by_position([v0_], oE2)[0]
    ooV1, ooX = fetch_by_position([v1_, x_], frV2)   # orig t pos / env
    ooE2, ooF2 = fetch_by_position([e2_, f2_], frV2)  # orig s pos / env
    ooK = fetch_by_position([k_], nbV1)[0]     # nt kind (D_SW3)
    sk3 = fetch_by_position([k_], SA)[0]       # ns kind (D_SW3)
    paV0, paV2, paX = fetch_by_position([v0_, v2_, x_], frE2)  # infer args
    sfV0 = fetch_by_position([v0_], SF)[0]     # s-pend arg (spine peel)
    sfV2 = fetch_by_position([v2_], SF)[0]
    sfX = fetch_by_position([x_], SF)[0]
    dqV0 = fetch_by_position([v1_], frV2)[0]          # orig t pos
    dqE2 = fetch_by_position([e2_], frV2)[0]          # orig s pos
    tidx = fetch_by_position([v0_], dqV0)[0]   # BVar indices
    sidx = fetch_by_position([v0_], dqE2)[0]
    # ── Phase 5 M3: proj-reduction peel (I_PROJ continuation reads the
    # whnf'd child in SA; the proj token sits at frV1, its idx in V1). The
    # child must be a fully applied 2-field P2.mk spine App(App(Const(18),a),b)
    # — the only non-rec structure in the toy env (TOY_STRUCTS). field =
    # idx==0 ? a (inner/fst) : b (outer/snd); else the proj re-sticks.
    pr_cK = fetch_by_position([k_], SA)[0]            # child whnf kind
    pr_oV0 = fetch_by_position([v0_], SA)[0]         # inner App pos
    pr_oV1 = fetch_by_position([v1_], SA)[0]         # outer arg (snd)
    pr_iK = fetch_by_position([k_], pr_oV0)[0]
    pr_iV0 = fetch_by_position([v0_], pr_oV0)[0]     # ctor pos
    pr_iV1 = fetch_by_position([v1_], pr_oV0)[0]     # inner arg (fst)
    pr_mK = fetch_by_position([k_], pr_iV0)[0]
    pr_mCid = fetch_by_position([v0_], pr_iV0)[0]
    pr_idx = fetch_by_position([v1_], frV1)[0]       # proj token V1 (field idx)
    pr_full = reglu(reglu(reglu(
                _kind_eq_raw(pr_cK, K_APP, One),
                _kind_eq_raw(pr_iK, K_APP, One)),
                _kind_eq_raw(pr_mK, K_CONST, One)),
                _eq_expr(pr_mCid, Expression({_one_dim: CID_P2MK})))
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

    g = {n: gid(n) for n in range(1, 55)}
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
    fr1_F2 = _select(cg[I_PI], Expression({_one_dim: I_ARG}), fr1_F2)
    fr2_task = _select(cg[I_PI], Expression({_one_dim: TASK_INFER}), fr2_task)
    fr2_V2 = _select(cg[I_PI], c1, fr2_V2)
    fr2_E2 = _select(cg[I_PI], One, fr2_E2)
    D_c = _select(cg[I_PI], c2, D_c)

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

    # I_CHK: verdict in A. False → reject (ERR_TYPE). True: substitute the
    # arg into the pi body (LINK) and continue with the next arg or deliver.
    i_chk_fail = reglu(cg[I_CHK], One - _geq_expr(SA, One))
    rej_c = reglu(i_chk_fail, One)
    rej_code_c = reglu(i_chk_fail, One)
    i_more = _geq_expr(paV2, One)
    link1_V0 = _select(cg[I_CHK], paV0, link1_V0)
    link1_D = _select(cg[I_CHK], ldepth(body_env), link1_D)
    link1_P = _select(cg[I_CHK], body_env, link1_P)
    link1_E = _select(cg[I_CHK], paX, link1_E)
    link1_F = _select(cg[I_CHK], Zero, link1_F)
    em_link1_c = cg[I_CHK]
    A_c = _select(cg[I_CHK], tV1, A_c)          # body pos
    B_c = _select(cg[I_CHK], c1, B_c)           # new f_type env = link
    C_c = _select(cg[I_CHK], Zero, C_c)
    F_c = _select(cg[I_CHK], Zero, F_c)
    fr1_V1 = _select(cg[I_CHK], tV1, fr1_V1)
    fr1_X = _select(cg[I_CHK], c1, fr1_X)
    fr1_E2 = _select(cg[I_CHK], _select(i_more, paV2, Zero), fr1_E2)
    fr1_F2 = _select(cg[I_CHK], Expression({_one_dim: I_PI}), fr1_F2)
    fr2_V2 = _select(cg[I_CHK], c2, fr2_V2)
    E_c = _select(cg[I_CHK], _select(i_more, Zero, One), E_c)
    D_c = _select(cg[I_CHK], _select(i_more, c3, frV2), D_c)

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
    em_link1_c = em_link1_c + cg[I_LAMSORT]
    fr1_V1 = _select(cg[I_LAMSORT], frV1, fr1_V1)
    fr1_X = _select(cg[I_LAMSORT], frX, fr1_X)
    fr1_E2 = _select(cg[I_LAMSORT], frE2, fr1_E2)
    fr1_F2 = _select(cg[I_LAMSORT], Expression({_one_dim: I_LAMBODY}), fr1_F2)
    fr2_task = _select(cg[I_LAMSORT], Expression({_one_dim: TASK_INFER}),
                       fr2_task)
    fr2_V2 = _select(cg[I_LAMSORT], c2, fr2_V2)
    fr2_E2 = _select(cg[I_LAMSORT], One, fr2_E2)
    A_c = _select(cg[I_LAMSORT], frE2, A_c)     # body pos
    B_c = _select(cg[I_LAMSORT], c1, B_c)       # marker env
    C_c = _select(cg[I_LAMSORT], Zero, C_c)
    F_c = _select(cg[I_LAMSORT], Zero, F_c)
    E_c = _select(cg[I_LAMSORT], Zero, E_c)
    D_c = _select(cg[I_LAMSORT], c3, D_c)

    # I_LAMBODY: body type in (A,B); emit T_PI_CLO(lam dom, body type).
    em_raw_c = cg[I_LAMBODY]
    raw_K_c = _select(cg[I_LAMBODY], Expression({_one_dim: T_PI_CLO}), raw_K_c)
    raw_V0_c = _select(cg[I_LAMBODY], frV1, raw_V0_c)
    raw_V1_c = _select(cg[I_LAMBODY], SA, raw_V1_c)
    raw_X_c = _select(cg[I_LAMBODY], frX, raw_X_c)
    raw_E2_c = _select(cg[I_LAMBODY], SB, raw_E2_c)
    A_c = _select(cg[I_LAMBODY], c1, A_c)
    B_c = _select(cg[I_LAMBODY], Zero, B_c)
    E_c = _select(cg[I_LAMBODY], One, E_c)
    D_c = _select(cg[I_LAMBODY], frV2, D_c)

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
    lvl2_root = _select(_kind_eq_raw(fK, K_SORT, One), fV0, SA)
    i_p2_bad = reglu(cg[I_PIS2], One - _kind_eq_raw(fK, K_SORT, One)
                     - _eq_expr(fK, One)
                     - _eq_expr(fK, One * 2))
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

    # I_PIL2: l2 in A, l1 in ST.V1; imax, then emit Sort(level) chain.
    imax_l = _select(_geq_expr(frV1, SA), frV1, SA)
    lvl_out = _select(_geq_expr(frV1, One), imax_l, SA)
    em_raw_c = em_raw_c + cg[I_PIL2]
    raw_K_c = _select(cg[I_PIL2], Expression({_one_dim: KL_ZERO}), raw_K_c)
    fr1_task = _select(cg[I_PIL2], Expression({_one_dim: TASK_INFER}), fr1_task)
    fr1_V1 = _select(cg[I_PIL2], lvl_out, fr1_V1)
    fr1_V2 = _select(cg[I_PIL2], frV2, fr1_V2)
    fr1_E2 = _select(cg[I_PIL2], One * 2, fr1_E2)
    A_c = _select(cg[I_PIL2], Zero, A_c)
    B_c = _select(cg[I_PIL2], c1, B_c)          # KL_ZERO pos
    C_c = _select(cg[I_PIL2], Zero, C_c)
    F_c = _select(cg[I_PIL2], Zero, F_c)
    E_c = _select(cg[I_PIL2], Zero, E_c)
    D_c = _select(cg[I_PIL2], c2, D_c)

    # I_SORTEM: level int in A (from LEVEL); emit Sort(level+1) chain.
    em_raw_c = em_raw_c + cg[I_SORTEM]
    raw_K_c = _select(cg[I_SORTEM], Expression({_one_dim: KL_ZERO}), raw_K_c)
    fr1_task = _select(cg[I_SORTEM], Expression({_one_dim: TASK_INFER}),
                       fr1_task)
    fr1_V1 = _select(cg[I_SORTEM], SA + One, fr1_V1)
    fr1_V2 = _select(cg[I_SORTEM], frV2, fr1_V2)
    fr1_E2 = _select(cg[I_SORTEM], One * 2, fr1_E2)
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
    A_c = _select(cg[I_LETD], let_body, A_c)         # body
    B_c = _select(cg[I_LETD], c1, B_c)
    C_c = _select(cg[I_LETD], Zero, C_c)
    F_c = _select(cg[I_LETD], Zero, F_c)
    E_c = _select(cg[I_LETD], Zero, E_c)
    D_c = _select(cg[I_LETD], c3, D_c)               # focus = the INFER frame

    # ── DEFEQ dispatch (task frame; pair in V1/X, E2/F2) ────────────────────
    # every dispatch gate is mode-gated: these expressions read frame/term
    # fields that are meaningless outside the DEFEQ frame mode
    deq_gate = is_defeq_frame
    deq_same = reglu(reglu(_eq_expr(frV1, frE2), _eq_expr(frX, frF2)), deq_gate)
    deq_const = reglu(reglu(reglu(_kind_eq_raw(tK, K_CONST, One),
                                  _kind_eq_raw(sK, K_CONST, One)),
                            _eq_expr(tV0, sV0)), deq_gate)
    deq_sort = reglu(reglu(_kind_eq_raw(tK, K_SORT, One),
                           _kind_eq_raw(sK, K_SORT, One)), deq_gate)
    deq_lit = reglu(reglu(reglu(_kind_eq_raw(tK, K_LIT, One),
                                _kind_eq_raw(sK, K_LIT, One)),
                          reglu(_eq_expr(tV1, Zero), _eq_expr(sV1, Zero))),
                    deq_gate)
    is_bvar_t = _kind_eq_raw(tK, K_BVAR, One)
    deq_bvar = reglu(reglu(is_bvar_t, _kind_eq_raw(sK, K_BVAR, One)), deq_gate)
    deq_mdata = reglu(reglu(_kind_eq_raw(tK, K_MDATA, One),
                            _kind_eq_raw(sK, K_MDATA, One)), deq_gate)
    deq_tpc = reglu(reglu(_kind_eq_raw(tK, T_PI_CLO, One),
                          _kind_eq_raw(sK, T_PI_CLO, One)), deq_gate)
    # PROJ/PROJ (M3): same structure+idx → compare children lazily (kernel
    # is_def_eq_core); differing sname/idx → verdict False. Without this the
    # pair would soft-whnf to two stuck projs and the stuck chain would try
    # infer_proj (outside the graph's infer subset → reject).
    deq_proj = reglu(reglu(_kind_eq_raw(tK, K_PROJ, One),
                           _kind_eq_raw(sK, K_PROJ, One)), deq_gate)
    proj_same = reglu(deq_proj, reglu(_eq_expr(tV0, sV0), _eq_expr(tV1, sV1)))
    proj_diff = deq_proj - proj_same
    bind_k = reglu(reglu(_kind_eq_raw(tK, K_LAM, One) + _kind_eq_raw(tK, K_PI, One),
                         _eq_expr(tK, sK)), deq_gate)
    pi_kind_t = _kind_eq_raw(tK, K_PI, One) + _kind_eq_raw(tK, T_PI_CLO, One)
    pi_kind_s = _kind_eq_raw(sK, K_PI, One) + _kind_eq_raw(sK, T_PI_CLO, One)
    deq_xpi = reglu(reglu(pi_kind_t, reglu(pi_kind_s, One - _eq_expr(tK, sK))),
                    deq_gate)
    deq_fall = reglu(One, deq_gate)
    for _gate in (deq_same, deq_const, deq_sort, deq_lit, deq_bvar,
                  deq_mdata, deq_tpc, deq_proj, bind_k, deq_xpi):
        deq_fall = reglu(deq_fall, One - _gate)

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
    # const/const same cid → True
    A_d = _select(deq_const, One, A_d)
    B_d = _select(deq_const, Zero, B_d)
    E_d = _select(deq_const, One, E_d)
    D_d = _select(deq_const, frV2, D_d)
    # sort/sort: scan both level trees
    fr1_V1_d = _select(deq_sort, sV0, fr1_V1_d)      # s root for D_SORT2
    fr1_F2_d = _select(deq_sort, Expression({_one_dim: D_SORT2}), fr1_F2_d)
    fr2_task_d = _select(deq_sort, Expression({_one_dim: TASK_LEVEL}), fr2_task_d)
    fr2_V2_d = _select(deq_sort, c1, fr2_V2_d)
    fr2_X_d = _select(deq_sort, Zero, fr2_X_d)
    A_d = _select(deq_sort, tV0, A_d)                # t level root
    B_d = _select(deq_sort, Zero, B_d)
    E_d = _select(deq_sort, Zero, E_d)
    D_d = _select(deq_sort, c2, D_d)
    # lit/lit: lockstep digit compare (loop via ST.E2 = k)
    fr1_V1_d = _select(deq_lit, frE2, fr1_V1_d)      # s chain head
    fr1_E2_d = _select(deq_lit, Zero, fr1_E2_d)      # k = 0
    fr1_F2_d = _select(deq_lit, Expression({_one_dim: D_LITL}), fr1_F2_d)
    A_d = _select(deq_lit, frV1, A_d)                # t chain head
    B_d = _select(deq_lit, Zero, B_d)
    E_d = _select(deq_lit, Zero, E_d)
    D_d = _select(deq_lit, c1, D_d)
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
    # PROJ/PROJ: differing sname/idx → verdict False; same → tail-call the
    # children pair (kernel compares proj children lazily).
    A_d = _select(proj_diff, Zero, A_d)
    B_d = _select(proj_diff, Zero, B_d)
    E_d = _select(proj_diff, One, E_d)
    D_d = _select(proj_diff, frV2, D_d)
    fr1_task_d = _select(proj_same, Expression({_one_dim: TASK_DEFEQ}), fr1_task_d)
    fr1_V1_d = _select(proj_same, tXf, fr1_V1_d)       # t proj child
    fr1_X_d = _select(proj_same, frX, fr1_X_d)
    fr1_E2_d = _select(proj_same, sXf, fr1_E2_d)       # s proj child
    fr1_F2_d = _select(proj_same, frF2, fr1_F2_d)
    D_d = _select(proj_same, c1, D_d)
    E_d = _select(proj_same, Zero, E_d)
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
    fr1_V1_d = _select(deq_fall, frE2, fr1_V1_d)
    fr1_X_d = _select(deq_fall, frF2, fr1_X_d)
    fr1_V2_d = _select(deq_fall, SD, fr1_V2_d)       # orig frame pos
    fr1_F2_d = _select(deq_fall, Expression({_one_dim: D_SW2}), fr1_F2_d)
    fr2_task_d = _select(deq_fall, Expression({_one_dim: TASK_WHNF}), fr2_task_d)
    fr2_V1_d = _select(deq_fall, frV1, fr2_V1_d)
    fr2_X_d = _select(deq_fall, frX, fr2_X_d)
    fr2_E2_d = _select(deq_fall, One, fr2_E2_d)
    fr2_V2_d = _select(deq_fall, c1, fr2_V2_d)
    A_d = _select(deq_fall, frV1, A_d)
    B_d = _select(deq_fall, frX, B_d)
    C_d = _select(deq_fall, Zero, C_d)
    F_d = _select(deq_fall, Zero, F_d)
    E_d = _select(deq_fall, Zero, E_d)
    D_d = _select(deq_fall, c2, D_d)

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
    bv_ltV = fetch_by_position([v0_], frV1)[0]   # t link value pos
    bv_ltE = fetch_by_position([x_], frV1)[0]    # t link value env
    bv_lsF = fetch_by_position([e2_], SA)[0]     # s link flag
    bv_lsB = fetch_by_position([f2_], SA)[0]     # s link bid
    bv_lsV = fetch_by_position([v0_], SA)[0]     # s link value pos
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
    em_link1_c = em_link1_c + xpig
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
    C_c = _select(cg[PI_TY], Zero, C_c)
    F_c = _select(cg[PI_TY], Zero, F_c)
    E_c = _select(cg[PI_TY], Zero, E_c)
    D_c = _select(cg[PI_TY], c2, D_c)
    # PI_LVL: ty_sort in (A,B); t_ty in (frV1,frX). is_prop ⇔ ty_sort is a
    # K_SORT whose level root is KL_ZERO (level 0; the toy env's only Prop).
    pl_sk = fetch_by_position([k_], SA)[0]
    pl_lv = fetch_by_position([v0_], SA)[0]
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
    et_dompos = fetch_by_position([v0_], SA)[0]
    et_domenv = _select(et_kpi, SB, fetch_by_position([x_], SA)[0])
    et_fpos = _select(frV1, ooV1, ooE2)                     # lam side
    et_fdom = fetch_by_position([v0_], et_fpos)[0]
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
    et_Mdom = fetch_by_position([v0_], et_Mpos)[0]
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
        inner = fetch_by_position([v0_], p)[0]
        ik = fetch_by_position([k_], inner)[0]
        ctor = fetch_by_position([v0_], inner)[0]
        ck = fetch_by_position([k_], ctor)[0]
        ccid = fetch_by_position([v0_], ctor)[0]
        return reglu(reglu(reglu(_kind_eq_raw(k, K_APP, One),
                                 _kind_eq_raw(ik, K_APP, One)),
                           _kind_eq_raw(ck, K_CONST, One)),
                     _eq_expr(ccid, Expression({_one_dim: CID_P2MK})))
    es_sctor = es_full_ctor(ooE2)
    es_tctor = es_full_ctor(ooV1)
    es_app = reglu(cg[ST_ES], es_sctor + es_tctor)
    es_no = reglu(cg[ST_ES], One - es_sctor - es_tctor)
    es_ctor_pos = _select(es_sctor, ooE2, ooV1)
    es_ctor_env = _select(es_sctor, ooF2, ooX)
    es_t_pos = _select(es_sctor, ooV1, ooE2)
    es_t_env = _select(es_sctor, ooX, ooF2)
    es_inner = fetch_by_position([v1_], fetch_by_position([v0_], es_ctor_pos)[0])[0]
    es_outer = fetch_by_position([v1_], es_ctor_pos)[0]
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
    # ST_ES not applicable → verdict False to caller.
    A_c = _select(es_no, Zero, A_c)
    B_c = _select(es_no, Zero, B_c)
    C_c = _select(es_no, Zero, C_c)
    F_c = _select(es_no, Zero, F_c)
    E_c = _select(es_no, One, E_c)
    D_c = _select(es_no, frV2, D_c)
    # ES_T: t_ty in (A,B); orient=frV1, caller=frV2. The ctor side is a fully
    # applied 0-param structure, so s_ty is statically Const(ind) — no infer
    # (the graph's INFER subset rejects infer(Proj), and the ctor's args are
    # projections). Emit Const(CID_P2) raw + defeq(t_ty, s_ty) (ES_DOM).
    raw_K_c = _select(cg[ES_T], Expression({_one_dim: K_CONST}), raw_K_c)
    raw_V0_c = _select(cg[ES_T], Expression({_one_dim: CID_P2}), raw_V0_c)
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
    raw_V0_c = _select(es_domok, Expression({_one_dim: NID_P2}), raw_V0_c)
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
    raw_V0_c = _select(es_next0, Expression({_one_dim: NID_P2}), raw_V0_c)
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
    # env (frX). Either way the result goes to frV2 (the whnf caller).
    pr_field = _select(_eq_expr(pr_idx, Zero), pr_iV1, pr_oV1)
    A_c = _select(cg[I_PROJ], _select(pr_full, pr_field, frV1), A_c)
    B_c = _select(cg[I_PROJ], _select(pr_full, SB, frX), B_c)
    C_c = _select(cg[I_PROJ], Zero, C_c)
    F_c = _select(cg[I_PROJ], Zero, F_c)
    E_c = _select(cg[I_PROJ], One, E_c)
    D_c = _select(cg[I_PROJ], frV2, D_c)

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
    n1l = fetch_by_position([v0_], SA)[0]
    n2l = fetch_by_position([v0_], frV1)[0]
    mxl = _select(_geq_expr(n1l, n2l), n1l, n2l)
    klt1 = _geq_expr(n1l, frE2 + One)                # k < n1
    klt2 = _geq_expr(n2l, frE2 + One)
    dig1 = _select(klt1, fetch_by_position([v0_], SA + One * 2 + frE2 + frE2)[0],
                   Zero)
    dig2 = _select(klt2, fetch_by_position([v0_], frV1 + One * 2 + frE2 + frE2)[0],
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
    E_r = _select(sp_both, fetch_by_position([v0_], SE)[0], E_r)  # s fn
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
    spa_tV0 = fetch_by_position([v0_], frV1)[0]
    spa_tX = fetch_by_position([x_], frV1)[0]
    spa_tV2 = fetch_by_position([v2_], frV1)[0]
    spa_sV0 = fetch_by_position([v0_], frX)[0]
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
    rej_c = reglu(ncc_fail, One)
    rej_code_c = reglu(ncc_fail, One)
    nz_t = One - _geq_expr(frX, One)                 # t lit == 0 (zero ctor)
    nz_s = One - _geq_expr(frE2, One)
    zlit = _value_eq_n(fetch_by_position([v0_], frX)[0],
                       fetch_by_position([v0_], frX + One * 2)[0])
    zlit2 = _value_eq_n(fetch_by_position([v0_], frE2)[0],
                        fetch_by_position([v0_], frE2 + One * 2)[0])
    ncc_tt = reglu(ncc, reglu(_geq_expr(frX, One), _geq_expr(frE2, One)))
    ncc_zz = reglu(ncc, reglu(nz_t, nz_s))
    ncc_tz = reglu(ncc, reglu(_geq_expr(frX, One), nz_s))
    ncc_zt = reglu(ncc, reglu(nz_t, _geq_expr(frE2, One)))
    ncc_ok = reglu(ncc_zz, One) + reglu(ncc_tz, zlit) \
        + reglu(ncc_zt, zlit2)
    ncc_bad = reglu(ncc_tz, One - zlit) + reglu(ncc_zt, One - zlit2)
    rej_c = rej_c + reglu(ncc_fail, One) + reglu(ncc_bad, One)
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

    # ── INFER frame dispatch (task=6; focus = (A,B), phase in E2) ───────────
    A_i = SA
    B_i = SB
    C_i = SC
    D_i = SD
    E_i = SE
    F_i = SF
    fr1_task_i, fr1_V1_i, fr1_V2_i, fr1_X_i, fr1_E2_i, fr1_F2_i = \
        Expression({_one_dim: TASK_ST}), Zero, frV2, Zero, Zero, Zero
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
    fr1_V2_i = _select(peel_end, frV2, fr1_V2_i)
    fr1_E2_i = _select(peel_end, c1, fr1_E2_i)       # args chain head
    fr1_F2_i = _select(peel_end, Expression({_one_dim: I_FN}), fr1_F2_i)
    fr2_task_i = _select(peel_end, Expression({_one_dim: TASK_INFER}),
                         fr2_task_i)
    fr2_V2_i = _select(peel_end, c2, fr2_V2_i)
    fr2_E2_i = _select(peel_end, One, fr2_E2_i)      # INFER phase 1
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
    A_i = _select(let_i, fV1, A_i)                   # value
    D_i = _select(let_i, c2, D_i)
    # CONST: type = ENV_HDR.V1
    const_i = reglu(ph1, is_const)
    A_i = _select(const_i, eV1, A_i)
    B_i = _select(const_i, Zero, B_i)
    E_i = _select(const_i, One, E_i)
    D_i = _select(const_i, frV2, D_i)
    # LIT: emit Const(Nat)
    lit_i = reglu(ph1, _kind_eq_raw(fK, K_LIT, One))
    em_raw_i = em_raw_i + lit_i
    raw_K_i = _select(lit_i, Expression({_one_dim: K_CONST}), raw_K_i)
    A_i = _select(lit_i, c1, A_i)
    B_i = _select(lit_i, Zero, B_i)
    E_i = _select(lit_i, One, E_i)
    D_i = _select(lit_i, frV2, D_i)
    # SORT: scan the level tree, then emit Sort(level+1)
    sort_i = reglu(ph1, _kind_eq_raw(fK, K_SORT, One))
    fr1_F2_i = _select(sort_i, Expression({_one_dim: I_SORTEM}), fr1_F2_i)
    fr2_task_i = _select(sort_i, Expression({_one_dim: TASK_LEVEL}), fr2_task_i)
    fr2_V2_i = _select(sort_i, c1, fr2_V2_i)
    fr2_X_i = _select(sort_i, Zero, fr2_X_i)
    A_i = _select(sort_i, fV0, A_i)                  # level root
    B_i = _select(sort_i, Zero, B_i)
    E_i = _select(sort_i, Zero, E_i)
    D_i = _select(sort_i, c2, D_i)
    # BVAR: walk the chain (re-dispatch or marker delivery on return)
    bvar_i = reglu(ph1, is_bvar)
    fr2_task_i = _select(bvar_i, Expression({_one_dim: TASK_WALK}), fr2_task_i)
    fr2_V2_i = _select(bvar_i, SD, fr2_V2_i)         # back to this frame
    fr2_X_i = _select(bvar_i, fV0, fr2_X_i)          # bvar index
    A_i = _select(bvar_i, SB, A_i)                   # chain head
    D_i = _select(bvar_i, c1, D_i)
    # unsupported kind in term position
    bad_i = reglu(ph1, One - is_app - is_lam - is_const - is_let - bvar_i
                  - pi_i - lit_i - sort_i)
    rej_i = bad_i
    rej_code_i = reglu(bad_i, One * 4)

    # ── LEVEL frame dispatch (task=8; node = A, acc in X) ───────────────────
    lvl_zero = reglu(is_level_frame, _eq_expr(fK, One))       # KL_ZERO = 1
    lvl_succ = reglu(is_level_frame, _eq_expr(fK, One * 2))   # KL_SUCC = 2
    lvl_bad = reglu(is_level_frame, One - lvl_zero - lvl_succ)
    rej_l = lvl_bad
    rej_code_l = reglu(lvl_bad, One * 4)
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
    valid1 = _kind_eq_raw(tK, K_LIT, One) \
        + reglu(_kind_eq_raw(tK, K_CONST, One), _eq_expr(tV0, CID_ZERO))
    valid2 = _kind_eq_raw(fK, K_LIT, One) \
        + reglu(_kind_eq_raw(fK, K_CONST, One), _eq_expr(fV0, CID_ZERO))
    natbad2 = reglu(d23, One - reglu(valid1, valid2))
    natbad1 = reglu(dn1, One - valid2)
    # a walk that sticks at a binder marker delivers focus=bvar with E=1 to
    # the parent frame; when that parent is a nat-op control frame (arg not
    # a literal) the kernel _soft_whnf contract applies: soft → deliver the
    # ORIGINAL closure, hard → reject (same as natbad1/2, focus is a bvar).
    stuck_nat = reglu(ret_pending, reglu(is_nat_frame, _eq_expr(frX, One)))
    stuck_st0 = reglu(ret_pending,
                      reglu(is_st_frame, One - _geq_expr(frF2, One)))
    stuck_ret = reglu(stuck_nat + stuck_st0, is_bvar)
    natbad = reglu(natbad2 + natbad1 + stuck_ret, One)
    # soft-w pos: d23/stuck-on-ST are two hops up (ST->NAT->WHNF: nbV2),
    # natbad1/stuck-on-NAT one hop (NAT->WHNF: frV2)
    wpos = _select(natbad2, nbV2,
            _select(natbad1, frV2,
            _select(stuck_ret, _select(is_nat_frame, frV2, nbV2), frV2)))
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
    fnC6 = fetch_by_position([v0_], fV0)[0]
    nc_step = reglu(nc_app, reglu(_kind_eq_raw(fnK6, K_CONST, One),
                                  _eq_expr(fnC6, CID_SUCC)))
    nc_zero = reglu(nc_loop, reglu(_kind_eq_raw(fK, K_CONST, One),
                                   _eq_expr(fV0, CID_ZERO)))
    nc_lit = reglu(nc_loop, _kind_eq_raw(fK, K_LIT, One))
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
                 _select(whnf_deliver, A_done,
                         A_main))))))))
    B_main_all = _select(proj_setup, SB,
                 _select(fire2, B_fire2,
                 _select(fire1, B_fire1,
                 _select(d12, B_d12,
                 _select(nat_soft, B_ns,
                 _select(d23, B_d23,
                 _select(dn1, B_dn1,
                 _select(whnf_deliver, SB,
                         B_main))))))))
    C_main_all = _select(proj_setup, Zero,
                 _select(fire2, C_fire2,
                 _select(fire1, C_fire1,
                 _select(d12, C_d12,
                 _select(nat_soft, C_ns,
                 _select(d23, C_d23,
                 _select(dn1, C_dn1,
                 _select(whnf_deliver, SC,
                         C_main))))))))
    D_main_all = _select(proj_setup, c2,
                 _select(fire2, D_fire2,
                 _select(fire1, D_fire1,
                 _select(d12, D_d12,
                 _select(nat_soft, D_ns,
                 _select(d23, D_d23,
                 _select(dn1, D_dn1,
                 _select(whnf_deliver, frV2,
                         D_main))))))))
    E_main_all = _select(proj_setup, Zero,
                 _select(fire2, E_fire2,
                 _select(fire1, E_fire1,
                 _select(d12, E_d12,
                 _select(nat_soft, E_ns,
                 _select(d23, E_d23,
                 _select(dn1, E_dn1,
                 _select(whnf_deliver, One,
                         E_main))))))))
    F_main_all = _select(proj_setup, Zero,
                 _select(fire2, F_fire2,
                 _select(fire1, F_fire1,
                 _select(d12, F_d12,
                 _select(nat_soft, F_ns,
                 _select(d23, F_d23,
                 _select(dn1, F_dn1,
                 _select(whnf_deliver, SF,
                         F_main))))))))

    # pop-task: E=1 under a TASK frame → drop the frame, keep the result
    A2 = _select(is_walk_frame, A_walk,
         _select(is_compute, A_comp,
         _select(cont_mode, A_c,
         _select(pop_task, SA,
         _select(is_infer_frame, A_i,
         _select(is_defeq_frame, A_d,
         _select(is_level_frame, A_l,
         _select(resume_mode, A_r, A_main_all))))))))
    B2 = _select(is_walk_frame, B_walk,
         _select(is_compute, B_comp,
         _select(cont_mode, B_c,
         _select(pop_task, SB,
         _select(is_infer_frame, B_i,
         _select(is_defeq_frame, B_d,
         _select(is_level_frame, B_l,
         _select(resume_mode, B_r, B_main_all))))))))
    C2 = _select(is_walk_frame, C_walk,
         _select(is_compute, C_comp,
         _select(cont_mode, C_c,
         _select(pop_task, SC,
         _select(is_infer_frame, C_i,
         _select(is_defeq_frame, C_d,
         _select(is_level_frame, C_l,
         _select(resume_mode, C_r, C_main_all))))))))
    D2 = _select(is_walk_frame, D_walk,
         _select(is_compute, D_comp,
         _select(cont_mode, D_c,
         _select(pop_task, frV2,
         _select(is_infer_frame, D_i,
         _select(is_defeq_frame, D_d,
         _select(is_level_frame, D_l,
         _select(resume_mode, D_r, D_main_all))))))))
    E2 = _select(is_walk_frame, E_walk,
         _select(is_compute, E_comp,
         _select(cont_mode, E_c,
         _select(pop_task, SE,
         _select(is_infer_frame, E_i,
         _select(is_defeq_frame, E_d,
         _select(is_level_frame, E_l,
         _select(resume_mode, E_r, E_main_all))))))))
    F2 = _select(is_walk_frame, F_walk,
         _select(is_compute, F_comp,
         _select(cont_mode, F_c,
         _select(pop_task, SF,
         _select(is_infer_frame, F_i,
         _select(is_defeq_frame, F_d,
         _select(is_level_frame, F_l,
         _select(resume_mode, F_r, F_main_all))))))))

    halt = halt + reglu(ret_pending, One - has_frame)

    # ── emission merge ──────────────────────────────────────────────────────
    # M2 frame emissions
    m2_chk = reglu(cg[I_CHK], i_more)
    em_frame_m2 = (cg[I_FN] + cg[I_PI] + cg[I_ARG] + m2_chk + cg[I_LAMDOM]
                   + cg[I_LAMSORT] + cg[I_PIDOM] + cg[I_PIS1] + cg[I_PIL1]
                   + cg[I_PIS2] + cg[I_PIL2] + cg[I_SORTEM] + cg[I_LETV]
                   + cg[I_LETD] + cg[D_SORT2] + cg[D_BV2] + bv_nb + cg[D_SW2]
                   + spa_next
                   + sw_loop + sw_pi + bv_d
                   + cg[PI_T] + cg[PI_TY] + cg[PI_LVL] + cg[PI_D] + cg[ST_SP]
                   + et_app + et_fall + cg[ETA_T] + et_spi + et_domok
                   + cg[ETA_LINK] + cg[ETA_LNK2]
                   + es_app + cg[ES_T] + es_domok + es_next0
                   + lit_cont + sp_both + sp_fin2 + nc_step + nct_done + ncs_done + nc_fail
                   + em_more + peel_end + lam_i + pi_i + let_i + sort_i
                   + deq_sort + deq_lit + deq_bvar + deq_mdata + deq_tpc
                   + bind_k + deq_xpi + deq_fall + lvl_succ)
    em_frame2_m2 = (cg[I_FN] + cg[I_PI] + cg[I_ARG] + m2_chk + cg[I_LAMDOM]
                    + cg[I_LAMSORT] + cg[I_PIDOM] + cg[I_PIS1] + cg[I_PIL1]
                    + cg[I_PIS2] + cg[I_LETV] + cg[I_LETD] + cg[D_SORT2] + cg[D_BIND2]
                    + cg[D_TPC2] + cg[D_BV2] + cg[D_XPI2] + cg[D_SW2] + spa_next
                    + sp_fin2
                    + peel_end + lam_i + pi_i + let_i + bvar_i + sort_i
                    + deq_sort + deq_bvar + deq_tpc + bind_k + deq_xpi
                    + deq_fall
                    + cg[PI_T] + cg[PI_TY] + pl_prop
                    + et_app + cg[ETA_T] + et_spi
                    + es_app + cg[ES_T] + es_domok + es_next0)

    def m2_merge(c_addr, r_addr, i_addr, d_addr, l_addr, l_expr, base):
        """Pick an emission payload across the disjoint M2 modes."""
        return _select(cont_mode, c_addr,
               _select(resume_mode, r_addr,
               _select(is_infer_frame, i_addr,
               _select(is_defeq_frame, d_addr,
               _select(lvl_succ, l_addr, base)))))

    frame_task = m2_merge(fr1_task, fr1_task_r, fr1_task_i, fr1_task_d,
                          fr1_task_l, None, frame_task)
    frame_V1 = m2_merge(fr1_V1, fr1_V1_r, fr1_V1_i, fr1_V1_d, Zero,
                        None, frame_V1)
    frame_V2 = m2_merge(fr1_V2, fr1_V2_r, fr1_V2_i, fr1_V2_d, fr1_V2_l,
                        None, frame_V2)
    frame_X = m2_merge(fr1_X, fr1_X_r, fr1_X_i, fr1_X_d, fr1_X_l,
                       None, frame_X)
    frame_E2 = m2_merge(fr1_E2, fr1_E2_r, fr1_E2_i, fr1_E2_d, Zero,
                        None, Zero)
    frame_F2 = m2_merge(fr1_F2, fr1_F2_r, fr1_F2_i, fr1_F2_d, Zero,
                        None, reglu(proj_setup, Expression({_one_dim: I_PROJ})))
    frame2_task = m2_merge(fr2_task, fr2_task_r, fr2_task_i, fr2_task_d,
                           Zero, None, frame2_task)
    frame2_V1 = m2_merge(fr2_V1, fr2_V1_r, fr2_V1_i, fr2_V1_d, Zero,
                         None, frame2_V1)
    frame2_V2 = m2_merge(fr2_V2, fr2_V2_r, fr2_V2_i, fr2_V2_d, Zero,
                         None, frame2_V2)
    frame2_X = m2_merge(fr2_X, fr2_X_r, fr2_X_i, fr2_X_d, Zero,
                        None, frame2_X)
    frame2_E2 = m2_merge(fr2_E2, fr2_E2_r, fr2_E2_i, fr2_E2_d, Zero,
                         None, reglu(proj_setup, One))
    frame2_F2 = m2_merge(fr2_F2, fr2_F2_r, fr2_F2_i, fr2_F2_d, Zero,
                         None, Zero)

    # links: M2 payloads win when an M2 link fires
    m2_l1 = em_link1_c + em_link1_d
    m2_l2 = em_link2_c + em_link2_d
    link_V0 = _select(m2_l1, link1_V0, link_V0)
    link_V1 = _select(m2_l1, link1_D, link_V1)
    link_prev = _select(m2_l1, link1_P, link_prev)
    link_env = _select(m2_l1, link1_E, link_env)
    link_flag = reglu(link1_F, m2_l1)
    link_F2 = reglu(link1_F2, m2_l1)            # M3 binder identity on link1
    link2_V0 = _select(m2_l2, link2_V0, Zero)
    link2_V1 = _select(m2_l2, link2_D, Zero)
    link2_prev = _select(m2_l2, link2_P, Zero)
    link2_env = _select(m2_l2, link2_E, Zero)
    link2_flag = reglu(link2_F, m2_l2)
    link2_F2m = reglu(link2_F2, m2_l2)          # M3 binder identity on link2
    em_link = em_link + m2_l1
    em_link2 = m2_l2

    # raw slot (position POS+1 when present)
    em_raw = em_raw_c + em_raw_r + em_raw_i
    raw_K = _select(cont_mode, raw_K_c,
            _select(resume_mode, raw_K_r, raw_K_i))
    raw_V0 = _select(cont_mode, raw_V0_c,
            _select(resume_mode, raw_V0_r, raw_V0_i))
    raw_V1 = raw_V1_c
    raw_V2 = raw_V2_r
    raw_X = _select(cont_mode, raw_X_c, raw_X_r)
    raw_E2 = raw_E2_c

    # pend: infer peel shares the main-mode payloads (fV1/SC/SB)
    em_pend = em_pend + em_pend_r + em_pend_i

    em_frame = (walk_more - walk_fail + em_frame_bvar + fire1 + fire2
                + d12 + d23_work + dn1 + em_frame_c + em_frame_m2 + proj_setup)
    em_frame2 = fire2 + d12 + em_frame2_m2 + proj_setup

    reject = rej_c + rej_r + rej_i + rej_l + rej_n
    reject_code = _select(bad_i + lvl_bad, One * 4, One)

    # head/gap/dig/const emission merge (main + compute)
    head_V0 = _select(d23_work, n_out_d23,
              _select(dn1, n_out_dn1,
              _select(d23_bz_div, One,
              _select(reglu(ph13g, b13u), One,
                      head_V0_c))))
    head_V2 = _select(d23_work + dn1 + d23_bz_div, Zero, head_V2_c)
    head_X = _select(d23_work + dn1 + d23_bz_div, Zero, head_X_c)
    em_lithead = (reglu(d23_work, One) + reglu(dn1, One) + reglu(d23_bz_div, One)
                  + em_lithead_c)
    em_gap = (reglu(d23, is_pow_d) + reglu(d23_bz_div, One)
              + reglu(ph13g, b13u)
              + reglu(d23, reglu(is_divmod_d, One - is_bzero_d))
              + reglu(is_compute, reglu(done_s, reglu(borrowfam, underflow))))
    # litdig (before frame/head): every real digit step; litdig2 (after
    # head+gap): the fresh-chain digits (underflow, pow/div entry)
    em_litdig = em_litdig_c
    em_litdig2 = reglu(d23, reglu(is_pow_d + is_divmod_d, One - is_bzero_d)) \
        + reglu(d23_bz_div, One) + reglu(ph13g, b13u) \
        + reglu(is_compute, reglu(done_s, reglu(borrowfam, underflow)))
    dig2_V0 = reglu(d23, is_pow_d)
    dig_V0 = dig_V0_c
    em_const = em_const_c

    outputs = {
        "done": out(halt, "o_done"),
        "result_pos": out(A_done, "o_result_pos"),
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
