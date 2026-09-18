"""Toy environment + Phase-1 WHNF corpus, shared by the Lean oracle
(reference/oracle.lean, generated) and the reference VM (lean_vm/ref_vm.py).

Constants mirror plain `def`s in oracle.lean exactly. All toy constants are
monomorphic (univ_arity = 0, VM_SPEC §9.2). Corpus terms are closed and
lambda-bound variables are always type-annotated (elaborator would leave
mvars otherwise — probe 2026-08-30).
"""
from __future__ import annotations

from expr.model import (
    BVar, Const, App, Lam, Pi, Let, Sort, LitNat, LZero, LSucc,
    BI_DEFAULT, Proj,
)

NAT = Const("Nat")
BOOL = Const("Bool")
TRUE = Const("True")
P2 = Const("P2")
UNITT = Const("UnitT")


def _sort1():
    return Sort(LSucc(LZero()))


def _sort0():
    return Sort(LZero())   # Prop


def _add(a, b):
    return App(App(Const("Nat.add"), a), b)


def _mul(a, b):
    return App(App(Const("Nat.mul"), a), b)


def _succ(a):
    return App(Const("Nat.succ"), a)


def _pi_nat_nat():
    return Pi("x", BI_DEFAULT, NAT, NAT)


def _pi_nat_nat_nat():
    return Pi("x", BI_DEFAULT, NAT, Pi("y", BI_DEFAULT, NAT, NAT))


def _pi_nat_bool():
    return Pi("x", BI_DEFAULT, NAT, Pi("y", BI_DEFAULT, NAT, BOOL))


def _let_nat(v, body):
    return Let("x", NAT, v, body)


def _pi_p2():
    """P2.mk : Nat → Nat → P2 (0 params, 2 fields)."""
    return Pi("fst", BI_DEFAULT, NAT, Pi("snd", BI_DEFAULT, NAT, P2))


def _pi_p2_nat():
    """P2.fst / P2.snd : P2 → Nat."""
    return Pi("p", BI_DEFAULT, P2, NAT)


def _pi_natrec():
    """Nat.rec : (motive : Nat → Type) → motive 0 →
    ((n : Nat) → motive n → motive (succ n)) → (n : Nat) → motive n.
    Monomorphic toy (motive codomain fixed at Type, universe-polymorphic
    lparams deferred). The iota slice never reads this type, but DEFEQ's
    proof-irrel branch infers a stuck recursor spine against it (P6.5), so
    the de Bruijn indices must be correct: inside `s_ty` the enclosing
    binders are [motive, z] (then n, ih), and the result sits under
    [motive, z, s, n] — so the motive is BVar(2)/BVar(3), not BVar(1)/BVar(2)."""
    m0 = App(BVar(0), Const("Nat.zero"))                       # ctx [motive]
    s_ty = Pi("n", BI_DEFAULT, NAT,
              Pi("ih", BI_DEFAULT, App(BVar(2), BVar(0)),      # ctx [motive,z,n]: m n
                 App(BVar(3), App(Const("Nat.succ"), BVar(1)))))  # ctx [motive,z,n,ih]: m (succ n)
    return Pi("motive", BI_DEFAULT, Pi("x", BI_DEFAULT, NAT, _sort1()),
              Pi("z", BI_DEFAULT, m0,
                 Pi("s", BI_DEFAULT, s_ty,
                    Pi("n", BI_DEFAULT, NAT, App(BVar(3), BVar(0))))))  # ctx [motive,z,s,n]: m n


def _pi_natcaseson():
    """Nat.casesOn : (t : Nat) → (motive : Nat → Type) → motive Nat.zero →
    ((n : Nat) → motive (Nat.succ n)) → motive t.  major_idx=0, nparams=0,
    nmotives=1, nminors=2 (zero, succ); non-recursive (no ih). de Bruijn:
    zero_ty in ctx [motive,t]; succ_ty binds n in ctx [n,zero,motive,t];
    result in ctx [succ,zero,motive,t]."""
    zero_ty = App(BVar(0), Const("Nat.zero"))                       # ctx [motive, t]
    succ_ty = Pi("n", BI_DEFAULT, NAT,
                 App(BVar(2), App(Const("Nat.succ"), BVar(0))))     # ctx [n, zero, motive, t]
    return Pi("t", BI_DEFAULT, NAT,
              Pi("motive", BI_DEFAULT, Pi("x", BI_DEFAULT, NAT, _sort1()),
                 Pi("zero", BI_DEFAULT, zero_ty,
                    Pi("succ", BI_DEFAULT, succ_ty,
                       App(BVar(2), BVar(3))))))                    # ctx [succ,zero,motive,t]: m t


def _pi_p2caseson():
    """P2.casesOn : (t : P2) → (motive : P2 → Type) →
    ((a : Nat) → (b : Nat) → motive (P2.mk a b)) → motive t.  major_idx=0,
    nparams=0, nmotives=1, nminors=1 (single ctor, 2 fields)."""
    alt_ty = Pi("a", BI_DEFAULT, NAT,
                Pi("b", BI_DEFAULT, NAT,
                   App(BVar(2), App(App(Const("P2.mk"), BVar(1)), BVar(0)))))  # ctx [b,a,motive,t]
    return Pi("t", BI_DEFAULT, P2,
              Pi("motive", BI_DEFAULT, Pi("x", BI_DEFAULT, P2, _sort1()),
                 Pi("alt", BI_DEFAULT, alt_ty,
                    App(BVar(1), BVar(2)))))                        # ctx [alt,motive,t]: m t


def _pi_boolcaseson():
    """Bool.casesOn : (t : Bool) → (motive : Bool → Type) → motive Bool.false →
    motive Bool.true → motive t.  major_idx=0, nparams=0, nmotives=1, nminors=2.
    Minor order follows Lean's CONSTRUCTOR DECLARATION order — Bool declares
    `false` before `true`, so the false-case minor comes first (the real-kernel
    oracle confirmed `casesOn true m 7 9` picks the SECOND minor). Both minors
    are 0-field (non-recursive). de Bruijn: false_ty in ctx [motive,t]; true_ty
    in ctx [true,motive,t]; result in ctx [true,false,motive,t]."""
    false_ty = App(BVar(0), Const("Bool.false"))                    # ctx [motive, t]
    true_ty = App(BVar(1), Const("Bool.true"))                      # ctx [true, motive, t]
    return Pi("t", BI_DEFAULT, BOOL,
              Pi("motive", BI_DEFAULT, Pi("x", BI_DEFAULT, BOOL, _sort1()),
                 Pi("false", BI_DEFAULT, false_ty,
                    Pi("true", BI_DEFAULT, true_ty,
                       App(BVar(2), BVar(3))))))                    # ctx [true,false,motive,t]: m t


# ── P7.5c brecOn (structural recursion, the target of recursive match/def) ───
# P7.5c-3 (pair-free Route A): NO primitive brecOn iota anywhere. `Nat.brecOn`
# is a @[reducible] def over `Nat.rec` (Meta/Constructions/BRecOn.lean;
# `Nat.drecOn` does not exist in lean 4.33.1 — the source hits are all
# `ndrecOn`). Both VMs get the plain delta value below and reduce it with the
# existing delta/beta/rec-iota machinery — NO P2-proj:
#   Nat.brecOn t motive F := Nat.rec motive (F 0 0)
#                                     (fun k ih => F (succ k) ih) t
# The rec's recursive value `ih` IS the minor's below-arg: real brecOn has
# `below motive (succ k) = motive k` = the recursive value at k, so this is the
# faithful go-chain directly.  (P7.5c-2 encoded below as a P2 pair
# ⟨F n ih, ih⟩ + `.1`; that over-modeling made the STUCK rec-app's infer fail by
# construction — P2.mk's monomorphic Const(Nat) domain vs motive n : Sort 1,
# VM_SPEC §11.16 — the deq_brec_sum_stuck divergence.  Pair-free removes it.)
# `Nat.below` remains a separate faithful rec-over-Nat def (P2-pair, below);
# it is no longer referenced by brecOn's value but stays a registered const.
# (P7.5c-1b shipped a primitive dispatch of the derived iota rules instead;
# retired here — one source of truth, no dual maintenance.)
def _pi_natbelow():
    """Nat.below : (motive : Nat → Type) → Nat → Type (monomorphic stand-in for
    the universe-polymorphic `Sort (max 1 u)`; the toy env is monomorphic and
    the corpus uses motive = fun _ => Nat, so below t : Type)."""
    motive_dom = Pi("x", BI_DEFAULT, NAT, _sort1())
    return Pi("motive", BI_DEFAULT, motive_dom,
              Pi("t", BI_DEFAULT, NAT, _sort1()))


def _below_value():
    """Delta value of Nat.below — the faithful rec-over-Nat def (binders
    motive, t). Real: `Nat.rec PUnit (fun n n_ih => motive n ×' n_ih) t`
    (PUnit → UnitT.mk, ×' → P2.mk). The rec motive degenerates to
    `fun _ => Sort 1` (real `Sort (max 1 u)`) — never type-checked: whnf/iota
    never validates motive domains and infer never deltas below."""
    mot = Lam("x", BI_DEFAULT, NAT, _sort1())
    # s body ctx [ih, n, t, motive]: motive=idx3, n=idx1, ih=idx0.
    # Real: `fun n n_ih => motive n ×' n_ih` with n_ih : motive' n where the
    # rec motive is the degenerate `fun _ => Sort (max 1 u)` — so the ih
    # binder's domain annotation is the CLOSED Sort(1), NOT a below-app. A
    # below-app annotation would make the lam-compare's domain check recurse
    # s-vs-s through below's own value forever (is_def_eq_binding checks
    # domains first, type_checker.cpp L785; the toy mirrors it).
    s = Lam("n", BI_DEFAULT, NAT,
            Lam("ih", BI_DEFAULT, _sort1(),
                App(App(Const("P2.mk"), App(BVar(3), BVar(1))), BVar(0))))
    motive_dom = Pi("x", BI_DEFAULT, NAT, _sort1())
    return Lam("motive", BI_DEFAULT, motive_dom,
               Lam("t", BI_DEFAULT, NAT,
                   App(App(App(App(Const("Nat.rec"), mot),
                               Const("UnitT.mk")), s), BVar(0))))


def _brec_value():
    """Delta value of Nat.brecOn — binders (t, motive, F) matching the
    _pi_natbrecOn outer order / the _brecOn_nat spine.  PAIR-FREE encoding
    (P7.5c-3): brecOn t motive F = Nat.rec motive (F 0 0)
    (fun k ih => F (succ k) ih) t.  The rec's recursive value ih IS the
    below-arg — real brecOn has `below motive (succ k) = motive k` = the
    recursive value at k, so this matches real semantics directly.  The old
    P2-pair ⟨F n ih, ih⟩ + .1 over-modeled below as a structure and made the
    STUCK rec-app's infer fail by construction (P2.mk's monomorphic Const(Nat)
    domain vs motive n : Sort 1, VM_SPEC §11.16) → the deq_brec_sum_stuck
    divergence.  At the base the minor's below-arg is PUnit in real lean; the
    toy sidestep types it Nat and the corpus minors ignore it at t=0 (casesOn
    zero-branch), so F 0 0 is the faithful value."""
    # body ctx [F, motive, t]: F=idx0, motive=idx1, t=idx2.
    mot = BVar(1)  # motive : Nat → Sort 1 (the rec motive)
    # Z = F 0 0 (below-arg dummy 0; the minor ignores it at t=0).
    z = App(App(BVar(0), Const("Nat.zero")), Const("Nat.zero"))
    # S body ctx [ih, k, F, motive, t]: F=idx2, k=idx1, ih=idx0.
    s = Lam("k", BI_DEFAULT, NAT,
            Lam("ih", BI_DEFAULT, NAT,
                App(App(BVar(2), _succ(BVar(1))), BVar(0))))
    return Lam("t", BI_DEFAULT, NAT,
               Lam("motive", BI_DEFAULT, Pi("x", BI_DEFAULT, NAT, _sort1()),
                   Lam("F", BI_DEFAULT, NAT,
                       App(App(App(App(Const("Nat.rec"), mot), z), s),
                           BVar(2)))))


def _pi_natbrecOn():
    """Nat.brecOn : (t : Nat) → (motive : Nat → Type) →
    ((t' : Nat) → Nat.below motive t' → motive t') → motive t.  major_idx=0
    (t first, like casesOn); motive explicit (toy-env style).  Two invariants
    (P7.5c-1b differential finds): (1) the outer binder order MUST match the
    spine the builders emit — _brecOn_nat applies t first — otherwise the
    proof-irrel chain's infer of a stuck spine checks the major (Nat) against
    the motive's Pi domain; (2) F_ty binds its own t' (as in real lean's
    `F : (t : Nat) → Nat.below motive t → motive t`) — an F_ty that only takes
    `bh` desyncs the F-arg type compare (Nat vs below-app) and the stuck pair
    falls through the whole chain to False."""
    motive_dom = Pi("x", BI_DEFAULT, NAT, _sort1())
    # F_ty under ctx [motive]:  (t' : Nat) → (bh : Nat) → motive t'.
    # Real lean annotates bh : Nat.below motive t'; the toy keeps bh : Nat —
    # see the SIDESTEP note under F_ty below (distinct-marker limitation of the
    # F-arg type check, unchanged by P7.5c-2's faithful below value).
    F_ty = Pi("t2", BI_DEFAULT, NAT,
              Pi("bh", BI_DEFAULT, NAT,
                 App(BVar(2), BVar(1))))                            # ctx [bh,t',motive]: m t'
    # bh : NAT stays a SIDESTEP even in P7.5c-2 (below now carries the faithful
    # rec value): the F-arg type check compares the minor's inferred bh-domain
    # against F_ty's with the two t' binders instantiated by DISTINCT markers
    # (the same limitation P7.5c-1b found with opaque below) — a below-app
    # domain would delta to a rec-app stuck on those distinct markers and
    # reject. NAT on BOTH sides keeps the compare closed; annotations are never
    # sort-checked, so the whnf/defeq verdicts are unaffected.
    # Result codomain: `motive t` — ctx [F, motive, t] so fn=motive (idx1),
    # arg=t (idx2).  P7.5c-1b differential find: App(BVar(1), BVar(0)) encoded
    # `motive F`; run-1 (spine infer) never derefs the lazy cod so the 4 iota
    # cases stayed green, but the stuck case's proof-irrel chain INFERs the cod
    # closure → `(fun _ => Nat) minor` → infer(minor's type)=PICLO vs dom=Nat
    # → stuck pair → reject 4.  The RefVM masked this: _proof_irrel is
    # try/except-wrapped, so its cod-infer threw and fell through to the spine
    # compare (same verdict by luck).
    return Pi("t", BI_DEFAULT, NAT,
              Pi("motive", BI_DEFAULT, motive_dom,
                 Pi("F", BI_DEFAULT, F_ty,
                    App(BVar(1), BVar(2)))))                        # ctx [F,motive,t]: m t


# ── Toy environment ─────────────────────────────────────────────────────────
# (name, type, value) in dependency order; constructors have no value.

TOY_CONSTS = [
    ("Nat",        _sort1(),      None),
    ("Bool",       _sort1(),      None),
    ("Bool.true",  BOOL,          None),
    ("Bool.false", BOOL,          None),
    ("Nat.zero",   NAT,           None),
    ("Nat.succ",   _pi_nat_nat(), None),
    ("Nat.pred",   _pi_nat_nat(), None),
    ("Nat.add",    _pi_nat_nat_nat(), None),
    ("Nat.sub",    _pi_nat_nat_nat(), None),
    ("Nat.mul",    _pi_nat_nat_nat(), None),
    ("Nat.pow",    _pi_nat_nat_nat(), None),
    ("Nat.div",    _pi_nat_nat_nat(), None),
    ("Nat.mod",    _pi_nat_nat_nat(), None),
    ("Nat.beq",    _pi_nat_bool(), None),
    ("Nat.ble",    _pi_nat_bool(), None),
    # Prop + True: proof-irrelevance supply (M3); True.intro is its sole
    # ctor (True = non-rec structure with 0 fields → also unit-like)
    ("True",       _sort0(),      None),
    ("True.intro", TRUE,          None),
    # Non-rec structure with fields (eta-struct + proj supply, M3):
    #   structure Prod2 (α β : Type) : Type where mk :: (fst : α) (snd : β)
    # Monomorphic toy: α=β=Nat baked into the type (univ_arity 0, §9.2).
    ("P2",         _sort1(),      None),
    ("P2.mk",      _pi_p2(),      None),
    ("P2.fst",     _pi_p2_nat(),  Lam("p", BI_DEFAULT, P2, Proj("P2", 0, BVar(0)))),
    ("P2.snd",     _pi_p2_nat(),  Lam("p", BI_DEFAULT, P2, Proj("P2", 1, BVar(0)))),
    ("T_dbl",  _pi_nat_nat(), Lam("x", BI_DEFAULT, NAT, _add(BVar(0), BVar(0)))),
    ("T_inc",  _pi_nat_nat(), Lam("x", BI_DEFAULT, NAT, _succ(BVar(0)))),
    ("T_two",  NAT,  _succ(_succ(Const("Nat.zero")))),
    ("T_four", NAT,  _mul(Const("T_two"), Const("T_two"))),
    ("T_ten",  NAT,  _add(Const("T_four"), _add(Const("T_four"), Const("T_two")))),
    ("T_pair", P2,   App(App(Const("P2.mk"), Const("T_two")),
                         App(Const("Nat.succ"), Const("T_two")))),
    # Recursor (iota slice): Nat.rec → cid 27. The graph's export cids start
    # at len(TOY_CONSTS), so appending here cannot collide.
    ("Nat.rec",    _pi_natrec(),  None),
    # P7 unit_like supply: a non-rec structure in Type with a single 0-field
    # constructor (cid 28/29 — appended after Nat.rec so the hardcoded graph
    # cids CID_REC=27 / CID_P2MK=18 stay put). Unlike True (a Prop, masked by
    # proof-irrelevance), UnitT : Type is NOT a Prop, so is_def_eq_unit_like
    # (kernel L1159) is the rule that decides two stuck UnitT terms.
    ("UnitT",      _sort1(),      None),
    ("UnitT.mk",   UNITT,         None),
    # P7.2 casesOn recursors (cid 30/31 — appended after UnitT.mk so the
    # hardcoded graph cids stay put). Non-recursive case analysis: what every
    # `match`/`induction` compiles to. major_idx=0, motive at 1, minors at 2+.
    ("Nat.casesOn", _pi_natcaseson(), None),
    ("P2.casesOn",  _pi_p2caseson(),  None),
    # P7.5b-4 Bool.casesOn (cid 32): if-then-else / `decide` (2 zero-field
    # minors). Appended after P2.casesOn so the hardcoded graph cids stay put.
    ("Bool.casesOn", _pi_boolcaseson(), None),
    # P7.5c brecOn (cid 33/34): structural recursion (recursive match/def target).
    # P7.5c-2 Route A: BOTH consts carry the faithful def-over-rec delta values
    # (see _below_value/_brec_value) — no primitive brecOn iota in either VM;
    # iota = delta + beta + rec-iota + P2-proj (P2 ↔ PProd, UnitT.mk ↔
    # PUnit.unit). Appended after Bool.casesOn so the hardcoded graph cids stay
    # put.  The F_ty/bh : NAT sidestep (see _pi_natbrecOn) survives: the F-arg
    # type check instantiates the paired t' binders with DISTINCT markers, so a
    # below-app domain there still can't compare (P7.5c-1b differential find).
    ("Nat.below",  _pi_natbelow(),  _below_value()),
    ("Nat.brecOn", _pi_natbrecOn(), _brec_value()),
]

TOY_CTORS = {"Nat.zero", "Nat.succ", "Bool.true", "Bool.false", "True.intro",
             "P2.mk", "UnitT.mk"}

# Lean-side definitions (must match TOY_CONSTS values exactly)
TOY_LEAN_DEFS = """\
def T_dbl : Nat → Nat := fun (x : Nat) => Nat.add x x
def T_inc : Nat → Nat := fun (x : Nat) => Nat.succ x
def T_two : Nat := Nat.succ (Nat.succ Nat.zero)
def T_four : Nat := Nat.mul T_two T_two
def T_ten : Nat := Nat.add T_four (Nat.add T_four T_two)
structure P2 where mk :: (fst : Nat) (snd : Nat)
structure UnitT : Type where
def T_pair : P2 := P2.mk T_two (Nat.succ T_two)
"""


# ── Corpus: closed WHNF cases ────────────────────────────────────────────────
# (case id, lean source, our Expr to encode)

CORPUS = [
    ("succ_zero", "Nat.succ Nat.zero", _succ(Const("Nat.zero"))),
    ("add_lits", "Nat.add 3 5", _add(LitNat(3), LitNat(5))),
    ("big_mul", "Nat.mul 123456789 987654321",
     _mul(LitNat(123456789), LitNat(987654321))),
    ("beta_add", "(fun (x : Nat) => Nat.add x x) 7",
     App(Lam("x", BI_DEFAULT, NAT, _add(BVar(0), BVar(0))), LitNat(7))),
    ("zeta", "(let x : Nat := 3; Nat.add x x)",
     _let_nat(LitNat(3), _add(BVar(0), BVar(0)))),
    ("sub_trunc", "Nat.sub 3 5",
     App(App(Const("Nat.sub"), LitNat(3)), LitNat(5))),
    ("div", "Nat.div 17 5", App(App(Const("Nat.div"), LitNat(17)), LitNat(5))),
    ("mod", "Nat.mod 17 5", App(App(Const("Nat.mod"), LitNat(17)), LitNat(5))),
    ("div_zero", "Nat.div 5 0", App(App(Const("Nat.div"), LitNat(5)), LitNat(0))),
    ("mod_zero", "Nat.mod 5 0", App(App(Const("Nat.mod"), LitNat(5)), LitNat(0))),
    ("pow", "Nat.pow 2 10", App(App(Const("Nat.pow"), LitNat(2)), LitNat(10))),
    ("pred", "Nat.pred 4", App(Const("Nat.pred"), LitNat(4))),
    ("pred_zero", "Nat.pred 0", App(Const("Nat.pred"), LitNat(0))),
    ("beq_true", "Nat.beq 3 3", App(App(Const("Nat.beq"), LitNat(3)), LitNat(3))),
    ("beq_false", "Nat.beq 3 5", App(App(Const("Nat.beq"), LitNat(3)), LitNat(5))),
    ("ble_true", "Nat.ble 3 5", App(App(Const("Nat.ble"), LitNat(3)), LitNat(5))),
    ("ble_false", "Nat.ble 5 3", App(App(Const("Nat.ble"), LitNat(5)), LitNat(3))),
    ("head_stuck_succ", "Nat.succ", Const("Nat.succ")),
    ("head_stuck_nat", "Nat", Const("Nat")),
    ("zero_stuck", "Nat.zero", Const("Nat.zero")),
    ("bool_stuck", "Bool.true", Const("Bool.true")),
    ("delta_beta", "T_dbl 21", App(Const("T_dbl"), LitNat(21))),
    ("delta_chain", "T_four", Const("T_four")),
    ("delta_two", "T_two", Const("T_two")),
    ("delta_lam", "T_dbl", Const("T_dbl")),
    ("delta_lam_app", "T_inc 41", App(Const("T_inc"), LitNat(41))),
    ("mixed", "Nat.add (T_dbl 5) T_four",
     _add(App(Const("T_dbl"), LitNat(5)), Const("T_four"))),
    ("hof", "(fun (f : Nat → Nat) => f (f Nat.zero)) T_dbl",
     App(Lam("f", BI_DEFAULT, _pi_nat_nat(),
             App(BVar(0), App(BVar(0), Const("Nat.zero")))),
         Const("T_dbl"))),
    ("deep_beta",
     "(fun (x : Nat) => fun (y : Nat) => Nat.add x (Nat.add y y)) 1 2",
     App(App(Lam("x", BI_DEFAULT, NAT,
                 Lam("y", BI_DEFAULT, NAT,
                     _add(BVar(1), _add(BVar(0), BVar(0))))),
             LitNat(1)), LitNat(2))),
    ("let_delta", "(let x : Nat := T_four; Nat.mul x x)",
     _let_nat(Const("T_four"), _mul(BVar(0), BVar(0)))),
    ("succ_delta", "Nat.succ T_four", _succ(Const("T_four"))),
    ("big_add", "Nat.add 12345678901234567890 1",
     _add(LitNat(12345678901234567890), LitNat(1))),
    ("partial_add", "Nat.add T_two",
     App(Const("Nat.add"), Const("T_two"))),
    ("partial_succ_zero", "Nat.succ Nat.zero", _succ(Const("Nat.zero"))),
]

# ── Phase-5 M1 corpus: DEFEQ pairs + INFER terms ─────────────────────────────
# DEFEQ: (case id, lean lhs, lean rhs, our lhs Expr, our rhs Expr)
# INFER: (case id, lean source, our Expr to encode)
# Oracle = #ORACLE_DEFEQ a =?= b / #ORACLE_INFER e (reference/lean_ref.py).
# M1 subset: closed terms over the toy env, no Prop / proof irrelevance, no
# eta, monomorphic (univ_arity 0).

# iota slice (Phase 6 P6.4): Nat.rec applied to a monomorphic motive
# (fun _ => Nat). motive/z/s/major as in the kernel's major_idx=3 spine.
# The motive is `fun (_ : Nat) => Nat` (binder domain Nat, body Nat) — its
# TYPE is `Nat -> Sort 1`, matching Nat.rec's motive domain in _pi_natrec.
# (P6.5: the earlier encoding used the motive's type as the binder domain,
# making it ill-typed; the stuck cases' proof-irrel infer then threw, which
# the RefVM swallowed via try/except but the graph could not.)
_REC_MOT = Lam("x", BI_DEFAULT, NAT, NAT)


def _rec(z, s, maj):
    return App(App(App(App(Const("Nat.rec"), _REC_MOT), z), s), maj)


_REC_SUCC = Lam("n", BI_DEFAULT, NAT,
                Lam("ih", BI_DEFAULT, NAT, _succ(BVar(0))))
_REC_ADD2 = Lam("n", BI_DEFAULT, NAT,
                Lam("ih", BI_DEFAULT, NAT, _add(BVar(0), LitNat(2))))
_REC_K = Lam("k", BI_DEFAULT, NAT, Lam("ih", BI_DEFAULT, NAT, BVar(1)))

# P7.2 casesOn (non-recursive case analysis). motive := fun _ => Nat; minors
# carry no ih. spine = [t, motive, alt0, alt1...] (major_idx=0).
_CASE_MOT_P2 = Lam("x", BI_DEFAULT, P2, NAT)


def _caseson_nat(t, z, s):
    return App(App(App(App(Const("Nat.casesOn"), t), _REC_MOT), z), s)


def _caseson_p2(t, alt):
    return App(App(App(Const("P2.casesOn"), t), _CASE_MOT_P2), alt)


_CASE_MOT_BOOL = Lam("x", BI_DEFAULT, BOOL, NAT)


def _caseson_bool(t, ta, fa):
    return App(App(App(App(Const("Bool.casesOn"), t), _CASE_MOT_BOOL), ta), fa)


# P7.5c brecOn (structural recursion). spine = [t, motive, F] (major_idx=0,
# motive = fun _ => Nat). F = fun (t : Nat) => fun (_ : Nat) => body; body in
# ctx [bh, t] (BVar 0 = bh, 1 = t). The bh annotation is the F_ty/NAT sidestep
# (see _pi_natbrecOn): under the faithful below value a below-app annotation
# would delta to a marker-stuck rec-app and fail the F-arg type check. The
# minor consumes bh directly (the recursive F value; pair-free, P7.5c-3).
def _brecOn_nat(t, F):
    return App(App(App(Const("Nat.brecOn"), t), _REC_MOT), F)


def _brec_minor(body):
    return Lam("t", BI_DEFAULT, NAT,
               Lam("bh", BI_DEFAULT, NAT, body))


def _brec_sum_minor():
    """F = fun t bh => Nat.casesOn t 0 (fun n => bh + Nat.succ n) — a
    genuinely recursive minor: bh = the below-arg = the recursive F value
    (pair-free encoding, P7.5c-3; real brecOn passes below motive t = the
    recursive value directly). F 0=0, F 1=1, F 2=3, F 3=6."""
    return _brec_minor(
        _caseson_nat(BVar(1), LitNat(0),
                     Lam("n", BI_DEFAULT, NAT,
                         _add(BVar(1), _succ(BVar(0))))))

DEFEQ_CORPUS = [
    ("deq_same", "T_two", "T_two", Const("T_two"), Const("T_two")),
    ("deq_delta", "T_four", "4", Const("T_four"), LitNat(4)),
    ("deq_beta", "(fun (x : Nat) => Nat.succ x) 3", "4",
     App(Lam("x", BI_DEFAULT, NAT, _succ(BVar(0))), LitNat(3)), LitNat(4)),
    ("deq_zeta", "(let x : Nat := T_two; Nat.succ x)", "3",
     _let_nat(Const("T_two"), _succ(BVar(0))), LitNat(3)),
    ("deq_natop", "Nat.add 3 5", "8",
     _add(LitNat(3), LitNat(5)), LitNat(8)),
    ("deq_natop_no", "Nat.add 3 5", "9",
     _add(LitNat(3), LitNat(5)), LitNat(9)),
    ("deq_mul_comm", "Nat.mul 123456789 987654321",
     "Nat.mul 987654321 123456789",
     _mul(LitNat(123456789), LitNat(987654321)),
     _mul(LitNat(987654321), LitNat(123456789))),
    ("deq_lam_alpha", "(fun (x : Nat) => x)", "(fun (y : Nat) => y)",
     Lam("x", BI_DEFAULT, NAT, BVar(0)), Lam("y", BI_DEFAULT, NAT, BVar(0))),
    ("deq_lam_no", "(fun (x : Nat) => Nat.succ x)", "(fun (x : Nat) => x)",
     Lam("x", BI_DEFAULT, NAT, _succ(BVar(0))),
     Lam("x", BI_DEFAULT, NAT, BVar(0))),
    ("deq_lam_dom_no", "(fun (x : Nat) => x)", "(fun (x : Bool) => x)",
     Lam("x", BI_DEFAULT, NAT, BVar(0)), Lam("x", BI_DEFAULT, BOOL, BVar(0))),
    ("deq_pi_no", "(Nat → Bool)", "(Nat → Nat)",
     Pi("x", BI_DEFAULT, NAT, BOOL), Pi("x", BI_DEFAULT, NAT, NAT)),
    ("deq_mixed", "T_dbl 21", "42",
     App(Const("T_dbl"), LitNat(21)), LitNat(42)),
    ("deq_delta_lam", "T_dbl", "(fun (x : Nat) => Nat.add x x)",
     Const("T_dbl"), Lam("x", BI_DEFAULT, NAT, _add(BVar(0), BVar(0)))),
    ("deq_stuck_args", "Nat.succ T_two", "Nat.succ 2",
     _succ(Const("T_two")), _succ(LitNat(2))),
    ("deq_stuck_args_no", "Nat.succ T_two", "Nat.succ 3",
     _succ(Const("T_two")), _succ(LitNat(3))),
    ("deq_bool_no", "Bool.true", "Bool.false",
     Const("Bool.true"), Const("Bool.false")),
    ("deq_sort", "Type", "Type", _sort1(), _sort1()),
    ("deq_sort_no", "Type", "Nat", _sort1(), NAT),
    ("deq_zero_lit", "Nat.zero", "0", Const("Nat.zero"), LitNat(0)),
    ("deq_succ_zero_lit", "Nat.succ Nat.zero", "1",
     _succ(Const("Nat.zero")), LitNat(1)),
    ("deq_big", "123456789 * 987654321", "121932631112635269",
     _mul(LitNat(123456789), LitNat(987654321)),
     LitNat(121932631112635269)),
    # ── M3: binder/fvar identity, proof irrelevance, eta, structural eta ────
    ("deq_fvar_same", "(fun (x : Nat) (y : Nat) => x)",
     "(fun (a : Nat) (b : Nat) => a)",
     Lam("x", BI_DEFAULT, NAT, Lam("y", BI_DEFAULT, NAT, BVar(1))),
     Lam("a", BI_DEFAULT, NAT, Lam("b", BI_DEFAULT, NAT, BVar(1)))),
    ("deq_fvar_swap_no", "(fun (x : Nat) (y : Nat) => x)",
     "(fun (a : Nat) (b : Nat) => b)",
     Lam("x", BI_DEFAULT, NAT, Lam("y", BI_DEFAULT, NAT, BVar(1))),
     Lam("a", BI_DEFAULT, NAT, Lam("b", BI_DEFAULT, NAT, BVar(0)))),
    ("deq_irrel", "(fun (p : True) => p)", "(fun (p : True) => True.intro)",
     Lam("p", BI_DEFAULT, TRUE, BVar(0)),
     Lam("p", BI_DEFAULT, TRUE, Const("True.intro"))),
    ("deq_irrel_two", "(fun (p : True) (q : True) => p)",
     "(fun (p : True) (q : True) => q)",
     Lam("p", BI_DEFAULT, TRUE, Lam("q", BI_DEFAULT, TRUE, BVar(1))),
     Lam("p", BI_DEFAULT, TRUE, Lam("q", BI_DEFAULT, TRUE, BVar(0)))),
    ("deq_irrel_no", "(fun (p : Bool) (q : Bool) => p)",
     "(fun (p : Bool) (q : Bool) => q)",
     Lam("p", BI_DEFAULT, BOOL, Lam("q", BI_DEFAULT, BOOL, BVar(1))),
     Lam("p", BI_DEFAULT, BOOL, Lam("q", BI_DEFAULT, BOOL, BVar(0)))),
    ("deq_irrel_cross", "True.intro",
     "(fun (p : True) (q : True) => q) True.intro True.intro",
     Const("True.intro"),
     App(App(Lam("p", BI_DEFAULT, TRUE, Lam("q", BI_DEFAULT, TRUE, BVar(0))),
             Const("True.intro")), Const("True.intro"))),
    ("deq_eta", "Nat.succ", "(fun (x : Nat) => Nat.succ x)",
     Const("Nat.succ"), Lam("x", BI_DEFAULT, NAT, _succ(BVar(0)))),
    ("deq_eta_no", "Nat.succ", "(fun (x : Nat) => Nat.pred x)",
     Const("Nat.succ"), Lam("x", BI_DEFAULT, NAT, App(Const("Nat.pred"), BVar(0)))),
    ("deq_eta_dom_no", "Nat.succ", "(fun (x : Bool) => Nat.succ 1)",
     Const("Nat.succ"), Lam("x", BI_DEFAULT, BOOL, _succ(LitNat(1)))),
    ("deq_eta_lam", "(fun (f : Nat → Nat) => f)",
     "(fun (f : Nat → Nat) (y : Nat) => f y)",
     Lam("f", BI_DEFAULT, _pi_nat_nat(), BVar(0)),
     Lam("f", BI_DEFAULT, _pi_nat_nat(),
         Lam("y", BI_DEFAULT, NAT, App(BVar(1), BVar(0))))),
    # Phase 6 guard: stuck fvar-headed applications must spine-peel and
    # compare the arg pair (the pre-P6 graph delivered the whnf head only
    # and wrongly said True).
    ("deq_fvar_args", "(fun (f : Nat → Nat) => f 1)",
     "(fun (f : Nat → Nat) => f 2)",
     Lam("f", BI_DEFAULT, _pi_nat_nat(), App(BVar(0), LitNat(1))),
     Lam("f", BI_DEFAULT, _pi_nat_nat(), App(BVar(0), LitNat(2)))),
    ("deq_eta_struct", "(fun (p : P2) => p)",
     "(fun (p : P2) => P2.mk p.1 p.2)",
     Lam("p", BI_DEFAULT, P2, BVar(0)),
     Lam("p", BI_DEFAULT, P2,
         App(App(Const("P2.mk"), Proj("P2", 0, BVar(0))),
             Proj("P2", 1, BVar(0))))),
    ("deq_eta_struct_no", "(fun (p : P2) => p)",
     "(fun (p : P2) => P2.mk p.2 p.1)",
     Lam("p", BI_DEFAULT, P2, BVar(0)),
     Lam("p", BI_DEFAULT, P2,
         App(App(Const("P2.mk"), Proj("P2", 1, BVar(0))),
             Proj("P2", 0, BVar(0))))),
    ("deq_eta_struct_val", "T_pair", "P2.mk T_pair.1 T_pair.2",
     Const("T_pair"),
     App(App(Const("P2.mk"), Proj("P2", 0, Const("T_pair"))),
         Proj("P2", 1, Const("T_pair")))),
    ("deq_proj", "(T_pair.1)", "T_two",
     Proj("P2", 0, Const("T_pair")), Const("T_two")),
    ("deq_proj_no", "(T_pair.2)", "T_two",
     Proj("P2", 1, Const("T_pair")), Const("T_two")),
    ("deq_proj_fn", "P2.fst T_pair", "T_two",
     App(Const("P2.fst"), Const("T_pair")), Const("T_two")),
    # ── Phase 6 P6.4: iota (Nat.rec reduce_recursor, inductive.h L77) ───────
    ("deq_rec_lit",
     "Nat.rec (motive := fun _ => Nat) 0 (fun n ih => Nat.succ ih) 5", "5",
     _rec(LitNat(0), _REC_SUCC, LitNat(5)), LitNat(5)),
    ("deq_rec_no",
     "Nat.rec (motive := fun _ => Nat) 0 (fun n ih => Nat.succ ih) 5", "4",
     _rec(LitNat(0), _REC_SUCC, LitNat(5)), LitNat(4)),
    ("deq_rec_zero",
     "Nat.rec (motive := fun _ => Nat) 7 (fun n ih => Nat.succ ih) 0", "7",
     _rec(LitNat(7), _REC_SUCC, LitNat(0)), LitNat(7)),
    ("deq_rec_add",
     "Nat.rec (motive := fun _ => Nat) 0 (fun n ih => Nat.add ih 2) 3", "6",
     _rec(LitNat(0), _REC_ADD2, LitNat(3)), LitNat(6)),
    ("deq_rec_succ_spine",
     "Nat.rec (motive := fun _ => Nat) 0 (fun n ih => Nat.succ ih) "
     "(Nat.succ (Nat.succ Nat.zero))", "2",
     _rec(LitNat(0), _REC_SUCC, _succ(_succ(Const("Nat.zero")))), LitNat(2)),
    ("deq_rec_stuck",
     "(fun (n : Nat) => Nat.rec (motive := fun _ => Nat) 0 "
     "(fun k ih => k) n)",
     "(fun (n : Nat) => Nat.rec (motive := fun _ => Nat) 0 "
     "(fun k ih => k) n)",
     Lam("n", BI_DEFAULT, NAT, _rec(LitNat(0), _REC_K, BVar(0))),
     Lam("n", BI_DEFAULT, NAT, _rec(LitNat(0), _REC_K, BVar(0)))),
    ("deq_rec_stuck_no",
     "(fun (n : Nat) => Nat.rec (motive := fun _ => Nat) 0 "
     "(fun k ih => k) n)",
     "(fun (n : Nat) => Nat.rec (motive := fun _ => Nat) 1 "
     "(fun k ih => k) n)",
     Lam("n", BI_DEFAULT, NAT, _rec(LitNat(0), _REC_K, BVar(0))),
     Lam("n", BI_DEFAULT, NAT, _rec(LitNat(1), _REC_K, BVar(0)))),
    # ── P7: is_def_eq_unit_like (kernel L1159). Two DISTINCT stuck fvars of a
    # single-0-field-constructor structure in Type are defeq (subsingleton).
    # proof-irrel can't fire (UnitT : Type, not Prop), app/eta/eta-struct
    # can't fire (bare fvars) → unit_like is the deciding rule. The `_no`
    # twin uses P2 (2 fields) so unit_like declines and the pair stays stuck.
    ("deq_unit_like",
     "(fun (x : UnitT) (y : UnitT) => x)",
     "(fun (x : UnitT) (y : UnitT) => y)",
     Lam("x", BI_DEFAULT, UNITT, Lam("y", BI_DEFAULT, UNITT, BVar(1))),
     Lam("x", BI_DEFAULT, UNITT, Lam("y", BI_DEFAULT, UNITT, BVar(0)))),
    ("deq_unit_like_no",
     "(fun (x : P2) (y : P2) => x)",
     "(fun (x : P2) (y : P2) => y)",
     Lam("x", BI_DEFAULT, P2, Lam("y", BI_DEFAULT, P2, BVar(1))),
     Lam("x", BI_DEFAULT, P2, Lam("y", BI_DEFAULT, P2, BVar(0)))),
    # ── P7.2: casesOn reduce_recursor (inductive.h L77, non-recursive). ──────
    ("deq_caseson_succ",
     "Nat.casesOn (motive := fun _ => Nat) 3 (0:Nat) (fun n => n)", "2",
     _caseson_nat(LitNat(3), LitNat(0), Lam("n", BI_DEFAULT, NAT, BVar(0))),
     LitNat(2)),
    ("deq_caseson_zero",
     "Nat.casesOn (motive := fun _ => Nat) 0 (7:Nat) (fun n => n)", "7",
     _caseson_nat(LitNat(0), LitNat(7), Lam("n", BI_DEFAULT, NAT, BVar(0))),
     LitNat(7)),
    ("deq_caseson_succ2",
     "Nat.casesOn (motive := fun _ => Nat) 5 (0:Nat) (fun n => Nat.succ n)", "5",
     _caseson_nat(LitNat(5), LitNat(0),
                  Lam("n", BI_DEFAULT, NAT, _succ(BVar(0)))), LitNat(5)),
    ("deq_caseson_p2",
     "P2.casesOn (motive := fun _ => Nat) (P2.mk 3 4) (fun a b => Nat.add a b)",
     "7",
     _caseson_p2(App(App(Const("P2.mk"), LitNat(3)), LitNat(4)),
                 Lam("a", BI_DEFAULT, NAT,
                     Lam("b", BI_DEFAULT, NAT, _add(BVar(1), BVar(0))))),
     LitNat(7)),
    ("deq_caseson_no",
     "Nat.casesOn (motive := fun _ => Nat) 3 (0:Nat) (fun n => n)", "3",
     _caseson_nat(LitNat(3), LitNat(0), Lam("n", BI_DEFAULT, NAT, BVar(0))),
     LitNat(3)),
    ("deq_caseson_stuck",
     "(fun (n : Nat) => Nat.casesOn (motive := fun _ => Nat) n (0:Nat) (fun k => k))",
     "(fun (n : Nat) => Nat.casesOn (motive := fun _ => Nat) n (0:Nat) (fun k => k))",
     Lam("n", BI_DEFAULT, NAT,
         _caseson_nat(BVar(0), LitNat(0), Lam("k", BI_DEFAULT, NAT, BVar(0)))),
     Lam("n", BI_DEFAULT, NAT,
         _caseson_nat(BVar(0), LitNat(0), Lam("k", BI_DEFAULT, NAT, BVar(0))))),
    ("deq_caseson_stuck_no",
     "(fun (n : Nat) => Nat.casesOn (motive := fun _ => Nat) n (0:Nat) (fun k => k))",
     "(fun (n : Nat) => Nat.casesOn (motive := fun _ => Nat) n (1:Nat) (fun k => k))",
     Lam("n", BI_DEFAULT, NAT,
         _caseson_nat(BVar(0), LitNat(0), Lam("k", BI_DEFAULT, NAT, BVar(0)))),
     Lam("n", BI_DEFAULT, NAT,
         _caseson_nat(BVar(0), LitNat(1), Lam("k", BI_DEFAULT, NAT, BVar(0))))),
    # ── P7.5b-4: Bool.casesOn (if-then-else / decide), 2 zero-field minors.
    # Lean declares Bool.false BEFORE Bool.true, so the spine minors are
    # [false-case, true-case]: `casesOn true m 7 9` → 9, `casesOn false m 7 9` → 7.
    ("deq_boolcaseson_true",
     "Bool.casesOn (motive := fun _ => Nat) Bool.true (7:Nat) (9:Nat)", "9",
     _caseson_bool(Const("Bool.true"), LitNat(7), LitNat(9)), LitNat(9)),
    ("deq_boolcaseson_false",
     "Bool.casesOn (motive := fun _ => Nat) Bool.false (7:Nat) (9:Nat)", "7",
     _caseson_bool(Const("Bool.false"), LitNat(7), LitNat(9)), LitNat(7)),
    ("deq_boolcaseson_no",
     "Bool.casesOn (motive := fun _ => Nat) Bool.true (7:Nat) (9:Nat)", "7",
     _caseson_bool(Const("Bool.true"), LitNat(7), LitNat(9)), LitNat(7)),
    ("deq_boolcaseson_stuck",
     "(fun (b : Bool) => Bool.casesOn (motive := fun _ => Nat) b (7:Nat) (9:Nat))",
     "(fun (b : Bool) => Bool.casesOn (motive := fun _ => Nat) b (7:Nat) (9:Nat))",
     Lam("b", BI_DEFAULT, BOOL,
         _caseson_bool(BVar(0), LitNat(7), LitNat(9))),
     Lam("b", BI_DEFAULT, BOOL,
         _caseson_bool(BVar(0), LitNat(7), LitNat(9)))),
    # ── P7.5c-1: Nat.brecOn zero/succ dispatch (minors ignore `below`) ────────
    ("deq_brec_zero",
     "Nat.brecOn (motive := fun _ => Nat) 0 (fun t _ => t)", "0",
     _brecOn_nat(LitNat(0), _brec_minor(BVar(1))), LitNat(0)),
    ("deq_brec_succ",
     "Nat.brecOn (motive := fun _ => Nat) 3 (fun t _ => t)", "3",
     _brecOn_nat(LitNat(3), _brec_minor(BVar(1))), LitNat(3)),
    ("deq_brec_const",
     "Nat.brecOn (motive := fun _ => Nat) 5 (fun _ _ => 7)", "7",
     _brecOn_nat(LitNat(5), _brec_minor(LitNat(7))), LitNat(7)),
    ("deq_brec_no",
     "Nat.brecOn (motive := fun _ => Nat) 3 (fun t _ => t)", "4",
     _brecOn_nat(LitNat(3), _brec_minor(BVar(1))), LitNat(4)),
    ("deq_brec_stuck",
     "(fun (n : Nat) => Nat.brecOn (motive := fun _ => Nat) n (fun t _ => t))",
     "(fun (n : Nat) => Nat.brecOn (motive := fun _ => Nat) n (fun t _ => t))",
     Lam("n", BI_DEFAULT, NAT, _brecOn_nat(BVar(0), _brec_minor(BVar(1)))),
     Lam("n", BI_DEFAULT, NAT, _brecOn_nat(BVar(0), _brec_minor(BVar(1))))),
    # ── P7.5c-3: pair-free delta-over-rec brecOn; a RECURSIVE minor (bh = the
    # recursive F value, passed directly by the rec's ih). F 0=0, F 1=1, F 2=3,
    # F 3=6.  NOTE: these two SUM cases still have NO faithful real-Lean mirror
    # — the toy keeps bh : Nat (the ↓/go-chain sidestep, see _pi_natbrecOn) and
    # reads the recursive value as bh, but real Nat.brecOn binds
    # bh : Nat.below motive t, which is stuck (not defeq to Nat inside the
    # casesOn branch), so neither bh nor bh.1 elaborates. They are therefore
    # graph-vs-RefVM only and skipped in the lean oracle (LEAN_NO_MIRROR in
    # tests/test_ref_infer_defeq.py).  The mirror strings below keep `bh.1`
    # purely to document that failed elaboration.
    ("deq_brec_sum",
     "Nat.brecOn (motive := fun _ => Nat) 3 "
     "(fun t bh => Nat.casesOn (motive := fun _ => Nat) t (0:Nat) "
     "(fun n => Nat.add bh.1 (Nat.succ n)))", "6",
     _brecOn_nat(LitNat(3), _brec_sum_minor()), LitNat(6)),
    ("deq_brec_sum_stuck",
     "(fun (n : Nat) => Nat.brecOn (motive := fun _ => Nat) n "
     "(fun t bh => Nat.casesOn (motive := fun _ => Nat) t (0:Nat) "
     "(fun k => Nat.add bh.1 (Nat.succ k))))",
     "(fun (n : Nat) => Nat.brecOn (motive := fun _ => Nat) n "
     "(fun t bh => Nat.casesOn (motive := fun _ => Nat) t (0:Nat) "
     "(fun k => Nat.add bh.1 (Nat.succ k))))",
     Lam("n", BI_DEFAULT, NAT, _brecOn_nat(BVar(0), _brec_sum_minor())),
     Lam("n", BI_DEFAULT, NAT, _brecOn_nat(BVar(0), _brec_sum_minor()))),
]

# non-rec structures: inductive name → (ctor name, nparams, nfields);
# feeds RefVM/StepGraph proj reduction + try_eta_struct (M3), and
# is_def_eq_unit_like (P7: nfields==0 → subsingleton).
TOY_STRUCTS = {"P2": ("P2.mk", 0, 2), "UnitT": ("UnitT.mk", 0, 0)}

INFER_CORPUS = [
    ("inf_zero", "Nat.zero", Const("Nat.zero")),
    ("inf_lit", "5", LitNat(5)),
    ("inf_succ", "Nat.succ", Const("Nat.succ")),
    ("inf_add_partial", "Nat.add T_two",
     App(Const("Nat.add"), Const("T_two"))),
    ("inf_app", "T_dbl 21", App(Const("T_dbl"), LitNat(21))),
    ("inf_lam_id", "(fun (x : Nat) => x)",
     Lam("x", BI_DEFAULT, NAT, BVar(0))),
    ("inf_lam_add", "(fun (x : Nat) => Nat.add x x)",
     Lam("x", BI_DEFAULT, NAT, _add(BVar(0), BVar(0)))),
    ("inf_lam_nested", "(fun (x : Nat) (y : Nat) => Nat.add x y)",
     Lam("x", BI_DEFAULT, NAT,
         Lam("y", BI_DEFAULT, NAT, _add(BVar(1), BVar(0))))),
    ("inf_lam_hof", "(fun (f : Nat → Nat) => f Nat.zero)",
     Lam("f", BI_DEFAULT, _pi_nat_nat(),
         App(BVar(0), Const("Nat.zero")))),
    ("inf_pi", "(Nat → Bool)", Pi("x", BI_DEFAULT, NAT, BOOL)),
    ("inf_pi_chain", "(Nat → Nat → Bool)",
     Pi("x", BI_DEFAULT, NAT, Pi("y", BI_DEFAULT, NAT, BOOL))),
    ("inf_let", "(let x : Nat := T_two; Nat.succ x)",
     _let_nat(Const("T_two"), _succ(BVar(0)))),
    ("inf_sort", "Type", _sort1()),
    ("inf_nat", "Nat", NAT),
    ("inf_hof_app", "(fun (f : Nat → Nat) => f (f Nat.zero)) T_dbl",
     App(Lam("f", BI_DEFAULT, _pi_nat_nat(),
             App(BVar(0), App(BVar(0), Const("Nat.zero")))), Const("T_dbl"))),
    ("inf_beq_partial", "Nat.beq 3", App(Const("Nat.beq"), LitNat(3))),
    # Phase 6 P6.2: infer_proj (kernel type_checker.cpp L247, monomorphic
    # non-rec non-dependent subset — P2). `.1`/`.2` elaborate to P2.fst/snd
    # in lean; the oracle only compares the inferred TYPE, so the encoding
    # may use Proj tokens directly.
    ("inf_proj_fst", "(fun (p : P2) => p.1)",
     Lam("p", BI_DEFAULT, P2, Proj("P2", 0, BVar(0)))),
    ("inf_proj_snd", "(fun (p : P2) => p.2)",
     Lam("p", BI_DEFAULT, P2, Proj("P2", 1, BVar(0)))),
    ("inf_proj_mk", "(P2.mk 2 3).1",
     Proj("P2", 0, App(App(Const("P2.mk"), LitNat(2)), LitNat(3)))),
]


# ── WP3 prerequisite: real-lean-derived declaration metadata ─────────────────
# The graph's data-driven iota path (VM_SPEC §13) reads the WP1 metadata tokens
# (T_ENV_RECVAL/T_ENV_RULE/T_ENV_CTORVAL/…) off the stream, so the toy
# environment must be encodable WITH real const_meta. Values are never
# hand-written: they come straight from `dump_env(TOY_LEAN_DEFS, roots)` via
# reference.olean_export.const_meta_for, exactly as tests/test_env_meta.py
# builds them. Imported lazily because olean_export imports this module.

_TOY_CONST_META_CACHE: dict | None = None


def toy_const_meta() -> dict[int, dict]:
    """cid → Encoder ``const_meta`` entry for every TOY_CONSTS constant,
    derived from the real lean 4.33.1 binary (cached)."""
    global _TOY_CONST_META_CACHE
    if _TOY_CONST_META_CACHE is None:
        from reference.olean_export import dump_env, const_meta_for
        roots = [name for name, _, _ in TOY_CONSTS]
        dump = dump_env(TOY_LEAN_DEFS, roots)
        _TOY_CONST_META_CACHE = const_meta_for(TOY_CONSTS, dump)
    return dict(_TOY_CONST_META_CACHE)
