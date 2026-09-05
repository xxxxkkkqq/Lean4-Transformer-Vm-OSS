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
]

TOY_CTORS = {"Nat.zero", "Nat.succ", "Bool.true", "Bool.false", "True.intro",
             "P2.mk"}

# Lean-side definitions (must match TOY_CONSTS values exactly)
TOY_LEAN_DEFS = """\
def T_dbl : Nat → Nat := fun (x : Nat) => Nat.add x x
def T_inc : Nat → Nat := fun (x : Nat) => Nat.succ x
def T_two : Nat := Nat.succ (Nat.succ Nat.zero)
def T_four : Nat := Nat.mul T_two T_two
def T_ten : Nat := Nat.add T_four (Nat.add T_four T_two)
structure P2 where mk :: (fst : Nat) (snd : Nat)
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
]

# non-rec structures: inductive name → (ctor name, nparams, nfields);
# feeds RefVM/StepGraph proj reduction + try_eta_struct (M3)
TOY_STRUCTS = {"P2": ("P2.mk", 0, 2)}

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
]
