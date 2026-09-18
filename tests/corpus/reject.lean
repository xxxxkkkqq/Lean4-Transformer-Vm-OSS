-- End-to-end acceptance corpus for the Lean kernel VM (docs/DESIGN.md §2).
--
-- This file must be accepted by the real Lean 4 compiler (exit 0). The same
-- elaborated declarations + environment are then exported (reference/
-- olean_export.dump_env / import_env_meta), encoded to tokens and run through
-- the VM's CHECK task; the VM's accept/reject verdicts must match.
--
-- No string literals (VM_SPEC §14: not yet implemented). Check-target
-- declarations are single-line `def`/`theorem` so the test can parse them for
-- the real-lean per-declaration oracle; support declarations may be multiline.
--
-- `tests/corpus/reject.lean` is this file with exactly one mutated value.

-- ── support: custom recursive inductive + its recursor ──────────────────────
inductive CovTree where
  | leaf : CovTree
  | node : CovTree -> CovTree -> CovTree

-- ── support: toy-mirrored structures (P2 projections, UnitT subsingleton) ───
structure P2 where mk :: (fst : Nat) (snd : Nat)
structure UnitT : Type where

-- ── support: plain defs (delta), a universe-polymorphic def ─────────────────
def Cov_two : Nat := Nat.succ (Nat.succ Nat.zero)
def Cov_three : Nat := Nat.succ Cov_two

universe u
def Cov_id {α : Type u} (a : α) : α := a

-- ── support: match-compiled functions (casesOn / recursor) ──────────────────
def Cov_bool (b : Bool) : Nat :=
  match b with
  | true => Cov_two
  | false => Cov_three

def Cov_wsum (t : CovTree) : Nat :=
  match t with
  | .leaf => Nat.zero
  | .node l r => Nat.succ (Nat.add (Cov_wsum l) (Cov_wsum r))

-- ── check targets: zeta / delta / infer ─────────────────────────────────────
def Cov_zeta : Nat := Bool.true
def Cov_def_delta : Nat := Cov_two
def Cov_def_fn : Nat -> Nat := fun (x : Nat) => Nat.succ x
def Cov_def_proj : Nat := P2.fst (P2.mk Cov_two Cov_three)
def Cov_def_match : Nat := Cov_bool Bool.true

-- ── check targets: beta / delta / Nat arithmetic / recursors / casesOn ──────
theorem Cov_beta : (fun (x : Nat) => Nat.succ x) Cov_two = Nat.succ Cov_two := rfl
theorem Cov_delta : Cov_two = Nat.succ (Nat.succ Nat.zero) := rfl
theorem Cov_add : Nat.add Cov_two Cov_three = Nat.succ (Nat.succ (Nat.succ (Nat.succ (Nat.succ Nat.zero)))) := rfl
theorem Cov_mul : Nat.mul Cov_two Cov_three = Nat.succ (Nat.succ (Nat.succ (Nat.succ (Nat.succ (Nat.succ Nat.zero))))) := rfl
theorem Cov_nat_rec : Nat.rec (motive := fun (_ : Nat) => Nat) Nat.zero (fun (_ : Nat) (ih : Nat) => Nat.succ ih) Cov_three = Cov_three := rfl
theorem Cov_tree_rec : CovTree.rec (motive := fun (_ : CovTree) => Nat) Cov_two (fun (_ _ : CovTree) (_ _ : Nat) => Nat.succ Nat.zero) (CovTree.node CovTree.leaf CovTree.leaf) = Nat.succ Nat.zero := rfl
theorem Cov_wsum_node : Cov_wsum (CovTree.node CovTree.leaf CovTree.leaf) = Nat.succ Nat.zero := rfl
theorem Cov_cases_zero : Nat.casesOn (motive := fun (_ : Nat) => Nat) Nat.zero Cov_two (fun (_ : Nat) => Nat.zero) = Cov_two := rfl
theorem Cov_cases_succ : Nat.casesOn (motive := fun (_ : Nat) => Nat) Cov_three Cov_two (fun (n : Nat) => n) = Cov_two := rfl
theorem Cov_bool_true : Cov_bool Bool.true = Cov_two := rfl

-- ── check targets: projections / structural eta ─────────────────────────────
theorem Cov_proj_fst : P2.fst (P2.mk Cov_two Cov_three) = Cov_two := rfl
theorem Cov_proj_snd : P2.snd (P2.mk Cov_two Cov_three) = Cov_three := rfl
theorem Cov_eta : (fun (p : P2) => P2.mk (P2.fst p) (P2.snd p)) = (fun (p : P2) => p) := rfl

-- ── check targets: unit-like subsingleton / proof irrelevance ───────────────
-- Both rules fire under binders on distinct fvars (closed axiom applications
-- are not defeq for the elaborator); these lambda forms are the toy corpus's
-- deq_unit_like / proof-irrel shape.
theorem Cov_unit_like : (fun (x : UnitT) (y : UnitT) => x) = (fun (x : UnitT) (y : UnitT) => y) := rfl
theorem Cov_proof_irrel : (fun (p1 : True) (p2 : True) => p1) = (fun (p1 : True) (p2 : True) => p2) := rfl

-- ── check targets: universe-polymorphic constants ───────────────────────────
theorem Cov_poly_nat : Cov_id Cov_two = Cov_two := rfl
theorem Cov_poly_type : Cov_id Nat = Nat := rfl
