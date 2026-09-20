# 012 — WP7-G5/G10: axiom-shape advance and the anchor-F2 safety gate

Date: 2026-09-15. Card 007 (WP7, agent D2, continuation of agent D).
Status: accepted.

## Context

The CHECK channel (D's §16.2, `CK_G0/CK_G1`) modelled `check_constant_val`
+ `ensure_sort` + value-infer + defeq as one fixed chain. Two add-paths
from K/environment.cpp disagreed with that shape:

- **add_axiom** (K/environment.cpp:152-158) runs *only* `check_constant_val`
  — no value at all (`axiom_val` has no value field, K/declaration.h).
  The chain forced a dummy value root, so `axiom a : Nat → Nat` was
  classified declTypeMismatch by the value-defeq arm while the real
  4.33.1 kernel accepts it (live probe: OK).
- **infer_constant** (K/type_checker.cpp:110-117) throws
  `kernel_exception`(.other) when a *safe*-mode type_checker infers a
  constant whose definition is unsafe or partial. Nothing in the graph
  gated on safety.

4.33.1 ground truth (live oracle, `~/.elan/bin/lean`):
`unsafe def T_uns := 5` stores defnInfo safety=0 isUnsafe=1 — dump-visible,
and `def g := T_uns` throws "invalid declaration, it uses unsafe
declaration 'T_uns'". But an elaborated `partial def` is **not** stored as
safety=partial: 4.33.1's `addAndCompilePartial` (toolchain
Lean/Elab/PreDefinition/Main.lean:20-37) rewrites it to
`DefKind.opaque` with an inhabitant value, and the only safety=partial
constant is the generated code-gen shadow `T_part._unsafe_rec`
(Basic.lean:280-296; suffix per Compiler/Old.lean:47-48, mkUnsafeRecName).
Probing the plain name is accepted (opaque carries no safety); probing the
shadow throws "safe declaration must not contain partial declaration
'T_part._unsafe_rec'". A raw `.defnDecl { safety := .partial }` whose value
references a partial constant throws **identically** — the throw depends on
the *referenced* constant's safety and the checker's mode (type_checker
default = safe, K/type_checker.h:125-128), never on the adding
declaration's own safety, and never on delta/whnf (the throw site is
infer_constant only).

## Decision

1. **G5: value-root-0 = declaration without value.** The CHECK kickoff
   copies the ENV_HDR value root into the frame `X` field; `X == 0` is the
   structural "no value" convention (axiom shape). After `CK_G1`'s
   ensure_sort success the chain branches: `X ≥ 1` → old value-infer
   relaunch (hard INFER, E2=1); `X == 0` → **advance** the chain to the
   next anchor (re-arming `ck_kick` through `D_c = frV2`, `A_c = nbX`), or
   accept-halt at chain end (`ax_done` joins the halt-verdict merge at
   build_vm :5806). No name/cid test anywhere (acceptance rule 3); the
   dummy-value arm is gone. Convention recorded in ENV_FORMAT §2.3.
2. **G10: encoder-precomputed anchor F2.** A bit-test of the flags field
   (IS_UNSAFE | IS_PARTIAL) is not expressible as an in-cycle select (no
   bitwise ops in the unrolled program), so the encoder writes
   `T_ENV_META.F2 = 1` iff the dump-derived safety is unsafe or partial
   (expr/tokens.py anchor write; ENV_FORMAT §2.3). The graph reads the
   anchor F2 in the INFER const arm: `safety_i = ph1 ∧ is_const ∧ F2==1`
   converts the reference into `bad_i` (reject accumulator) with new code
   **7**; `const_i` (normal const inference) is masked off on the same
   term. The gate fires on INFER only — delta/whnf paths never see it,
   matching the kernel throw site. Legacy streams carry F2=0: the gate is
   inert there by *data absence*, documented, not by a name branch; meta
   differential cases are flagged `meta_only`.
3. **Differential corpus rides the 4.33.1 reality.** `g10_partial_use`
   references `T_part._unsafe_rec` (raw name quote), not the opaque
   user-level name; `g10_partial_plain_ok` pins that referencing the
   elaborated `partial def` name ACCEPTS (kernel and graph agree, legacy
   stream); `g10_safe_control` pins the closed gate. The expected kernel
   message strings are whatever the live binary prints (recorded above),
   never preseeded verdicts.

## Consequences

- Graph grows +31 dims / +2 lookups (24914/2878 vs D's scratch 24883/2876);
  reject_code select chain gains one arm (7 > 6 > 5 > 4 > 1 priority).
- Engine vm.cpp untouched: reject_code stays a Python-driver channel.
- Safety flags for a real module now *can* ride the dump→const_meta path
  (`T_part._unsafe_rec` proves the loop closes on generated names), so a
  future card can gate the same bits in ref_vm/whnf if the kernel ever
  checks elsewhere — it does not (4.33.1 grep: single throw site).
