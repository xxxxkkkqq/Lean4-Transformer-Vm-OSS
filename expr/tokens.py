"""Token-stream encoding per docs/VM_SPEC.md v1.

Stream = list of 5-field tokens (K, V0, V1, V2, X). Positions are stream
indices (0-based); 0 is a legal position (ENV starts there), so NULL is
represented by None on the Python side and by the "absent field" convention
in the spec (V1=0 for "no level args" is disambiguated by kind, not by 0=1).

Token-kind constants here extend expr/model.py's K_* constants; all numbers
are mirrored in VM_SPEC §2-§7.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from expr.model import (
    BVar, FVar, MVar, Sort, Const, App, Lam, Pi, Let, LitNat, LitStr,
    MData, Proj, Expr, Level,
    LZero, LSucc, LMax, LIMax, LParam, LMVar,
    K_BVAR, K_FVAR, K_MVAR, K_SORT, K_CONST, K_APP, K_LAM, K_PI, K_LET,
    K_LIT, K_MDATA, K_PROJ,
    KL_ZERO, KL_SUCC, KL_MAX, KL_IMAX, KL_PARAM, KL_MVAR,
    BI_DEFAULT, LIT_NAT, LIT_STR,
)

# ── Non-expr token kinds (VM_SPEC §2-§7) ────────────────────────────────────

T_LIT_DIG = 13     # Nat digit-chain digit (V0 = 0..9, V2 = chain head)
# Digit-chain layout (stride 2): digit k of a chain with head H lives at
# position H+2+2k. Machine-emitted chains interleave one STATE token per
# micro-step, so digits are never contiguous; encoder/ref chains emit an
# explicit NULL gap token to match the same stride (VM_SPEC §5).
T_LIT_BYTE = 40    # string-literal byte-chain element (WP5-E1, VM_SPEC §14):
                   #   V0 = byte 0..255, V2 = the K_LIT head.  Byte i of a
                   #   chain with head H lives at H+2+2i with a NULL gap at
                   #   H+1+2i — the SAME stride as T_LIT_DIG, so the graph's
                   #   stride-2 chain loops (D_LITL) are kind-agnostic and
                   #   compare byte chains for free.
T_NAME = 21        # name-table entry (V0 = nid, V1 = parent nid, 0 = root)
T_ENV = 22         # ENV_HDR (V0=cid, V1=type root, V2=value root, X=flags)
T_ENV_META = 23    # ENV_META anchor (V0=univ_arity, V1=constant_info_kind,
                   #   V2=meta_head, X=flags bitfield; see ENV_FORMAT §2.3)
T_PEND = 30        # pending arg (Krivine stack; V0=arg, V2=prev, X=env head)
T_LINK = 31        # environment link (V0=value, V1=depth, V2=prev link, X=captured env)
T_FRAME = 32       # frame (V0=task, V1=focus, V2=caller, X=phase)
T_STATE = 33       # machine state (A..F fields; see VM_SPEC §10.1)
T_PI_CLO = 34      # machine-emitted Pi type whose two halves are closures:
                   # V0 = domain root, V1 = body root, X = domain env,
                   # E2 = body env (INFER of Lam pushes one; a plain K_PI at
                   # env e is equivalent to (V0,e),(V1,link(marker,e))).
T_DEFCACHE = 41    # card 014 P1: is_def_eq POSITIVE cache entry (kernel
                   # m_success, K/type_checker.cpp:960/:972, written by the
                   # is_def_eq wrapper :1249-1252). Emitted on the raw slot
                   # when a DEFEQ frame completes True:
                   #   V0 = t_pos (attention key), V1 = t_env,
                   #   V2 = s_pos, X = s_env. Never a frame (k != T_FRAME),
                   #   never reachable from D; read only by the DEFEQ
                   #   dispatch probe (VM_SPEC §18).
T_DEFFAIL = 42     # card 014 P1b: is_def_eq FAILURE cache entry (kernel
                   # m_failure, K/type_checker.cpp:941/:953, written ONLY at
                   # the lazy_delta same-constant args-differ point :1042 —
                   # the graph's DE_ATT FALSE beat. Same field layout as
                   # T_DEFCACHE; queried by the A17 (deq_hargs) arm before
                   # retrying the args comparison (:1034 failed_before).
T_WHNFCACHE = 43   # card 014 P2: whnf memo entry (kernel m_whnf,
                   # K/type_checker.cpp:753-757 query, inserts at :763/:766/
                   # :772 AFTER the whnf loop completes). Emitted on the raw
                   # slot when a TASK_WHNF frame delivers to its caller:
                   #   V0 = focus pos (attention key), V1 = focus env,
                   #   V2 = soft flag (frame E2), X = result pos,
                   #   E2 = result env. Never a frame, never reachable from
                   #   D; read only by the WHNF dispatch probe (VM_SPEC §18).
T_OUT_VAL = 201    # task result (V0 = result pos)
T_ACCEPT = 202
T_REJECT = 203     # V0 = error code (VM_SPEC §7.4)
T_HALT = 204

# ── ENV metadata token kinds (ENV_FORMAT §2.2; free slots 24-29, 35-38) ─────
T_ENV_DEFVAL = 24    # Definition (V0=cid V1=hints_kind V2=hints_height X=safety
                     #   E2=all_list_head F2=next_meta)
T_ENV_SIMPLEVAL = 25 # Axiom/Theorem/Opaque (V0=cid V1=is_unsafe V2=all_head)
T_ENV_INDVAL = 26    # Inductive scalars (V0=cid V1=nparams V2=nindices X=nnested)
T_ENV_CTORVAL = 27   # Constructor (V0=cid V1=induct_cid V2=cidx X=nparams E2=nfields)
T_ENV_RECVAL = 28    # Recursor scalars (V0=cid V1=nparams V2=nindices X=nmotives
                     #   E2=nminors)
T_ENV_RULE = 29      # recursor rule (V0=rec_cid V1=ctor_cid V2=nfields
                     #   X=rhs_root_pos F2=next_rule)
T_ENV_LIST = 35      # name-list node (V0=owner_cid V1=nid V2=role X=next_node)
T_ENV_QUOTVAL = 36   # Quot (V0=cid V1=quot_kind)
T_ENV_INDEXTRA = 37  # Inductive list heads (V0=cid V1=all_head V2=ctors_head)
T_ENV_RECEXTRA = 38  # Recursor list/rule heads (V0=cid V1=all_head V2=rules_head)
T_ENV_UNIVPARAMS = 39  # per-cid lparams name-chain head (WP2, VM_SPEC §12.1):
                       #   V0=cid, V1=first T_ENV_LIST(role=2) node, F2=next_meta
# K_CONST.E2 (WP2b D13/D14, VM_SPEC §12.7): root of the *instantiated* declared
# type at a polymorphic use site, i.e. instantiate_type_lparams(info, ls)
# (K/instantiate.cpp:248-254) with each declaration lparam replaced by the
# positional use-site level (instantiate, K/level.cpp:317-340). 0 means the use
# site is monomorphic / param-free and the shared ENV_HDR type root applies.

# constant_info_kind values (declaration.h:426)
CK_AXIOM = 0
CK_DEFINITION = 1
CK_THEOREM = 2
CK_OPAQUE = 3
CK_QUOT = 4
CK_INDUCTIVE = 5
CK_CONSTRUCTOR = 6
CK_RECURSOR = 7

# T_ENV_META flags bitfield (ENV_FORMAT §2.3; low bits 0-3 alias ENV_F_*)
ENV_F_IS_QUOT = 16
ENV_F_IS_UNSAFE = 32
ENV_F_IS_REC = 64
ENV_F_IS_REFLEXIVE = 128
ENV_F_IS_K = 256
ENV_F_IS_PARTIAL = 512

# T_ENV_LIST role
ENV_LIST_ALL = 0
ENV_LIST_CTORS = 1
ENV_LIST_UNIVPARAMS = 2   # ordered const lparams names (WP2, VM_SPEC §12.1)

HINTS_HEIGHT_MAX = 4095    # §6 TBD#1: faithful for heights <= 4095; Encoder
                           # saturates above (no v1 encoding defined)

# T_ENV flags
ENV_F_HAS_VALUE = 1
ENV_F_IS_CTOR = 2
ENV_F_IS_INDUCTIVE = 4
ENV_F_IS_RECURSOR = 8

# tasks (VM_SPEC §7; numbers match lean_vm/build_vm.py)
TASK_WHNF = 1      # whnf control frame (delivery vs halt; E2=1 = soft)
TASK_NAT = 2
TASK_WALK = 3
TASK_ST = 5        # storage/continuation frame (F2 = continuation id)
TASK_INFER = 6
TASK_DEFEQ = 7
TASK_LEVEL = 8     # level-tree int scan (acc in X)
TASK_CHECK = 9

# Nat operations (identified by constant name)
NAT_OPS = {
    "Nat.succ": "succ", "Nat.pred": "pred", "Nat.add": "add",
    "Nat.sub": "sub", "Nat.mul": "mul", "Nat.pow": "pow",
    "Nat.div": "div", "Nat.mod": "mod",
    "Nat.beq": "beq", "Nat.ble": "ble",
}
NAT_OP_ARITY = {"succ": 1, "pred": 1, "add": 2, "sub": 2, "mul": 2,
                "pow": 2, "div": 2, "mod": 2, "beq": 2, "ble": 2}
NAT_OP_CODES = {"Nat.succ": 1, "Nat.pred": 2, "Nat.add": 3, "Nat.sub": 4,
                "Nat.mul": 5, "Nat.pow": 6, "Nat.div": 7, "Nat.mod": 8,
                "Nat.beq": 9, "Nat.ble": 10,
                # 11 = Nat.recursor dispatch (graph ENV_HDR.X only; NOT in
                # NAT_OPS/NAT_OP_ARITY — the RefVM iota gate reads cids
                # directly, P6.4/P6.5)
                "Nat.rec": 11,
                # 12 = casesOn dispatch (P7.5b graph iota; RefVM reads cids
                # via self.caseson, so this opcode is graph-ENV_HDR only).
                "Nat.casesOn": 12,
                # 13 = P2.casesOn dispatch (P7.5b-3: 3-entry spine, 1 minor,
                # 2-field ctor). Separate opcode from Nat (different arity).
                "P2.casesOn": 13,
                # 14 = Bool.casesOn dispatch (P7.5b-4: 4-entry spine, 2
                # zero-field minors [false, true] — if-then-else / decide).
                "Bool.casesOn": 14,
                # 20-25 = WP6-F reduce_nat ops (K/type_checker.cpp:702-733).
                # Graph-side nat ops; deliberately NOT in NAT_OPS/NAT_OP_ARITY:
                # the frozen RefVM must not grow a second implementation
                # (AGENTS file-ownership), so its dispatch declines these cids
                # and the differential verdicts come from the oracle.  20+
                # because 15 collides with NAT-frame.V1's OP_IOTA space and
                # 16-19 are the ENV_HDR-only Bool/String id tags.
                "Nat.gcd": 20, "Nat.land": 21, "Nat.lor": 22, "Nat.xor": 23,
                "Nat.shiftLeft": 24, "Nat.shiftRight": 25}
                # 15 was the P7.5c-1b Nat.brecOn dispatch opcode — RETIRED in
                # P7.5c-2 (Route A): Nat.brecOn/Nat.below are plain value
                # consts reduced by delta + rec-iota + proj in both VMs.

# ENV_HDR.X codes for the Bool constructors (WP8-H5).  These are NOT nat ops:
# the tag only gives build_vm.py a name-keyed, order-independent handle on the
# cid, exactly like Nat.succ's OP_SUCC above.  The beq/ble machine synthesizes
# a Bool literal and must emit the *real* Bool.true / Bool.false cid (its V0 is
# compared against environment cids by the WNF's Bool.casesOn classifier and by
# defeq), which the old hardcoded CID_TRUE=2 / CID_FALSE=3 could not guarantee
# under a name-sorted environment.  build_vm's natop gate treats eX >= 11 as a
# non-firing opcode (both arities are 0), so a tagged ctor still whnf's as a
# stuck 0-field constructor.
CTOR_ID_CODES = {"Bool.true": 16, "Bool.false": 17}

# ENV_HDR.X codes for the string-literal reduction handles (WP5, VM_SPEC §14.3).
# Again NOT nat ops: the tag only gives build_vm.py a name-keyed,
# order-independent handle on the cid (same pattern as CTOR_ID_CODES).
# string_lit_to_constructor (K/inductive.cpp:1368-1380) synthesizes a
# `String.ofList` application and a literal infers to `String`
# (K/type_checker.cpp:315-321); the graph discovers these two cids from the
# ENV_HDR.X scan and declines (literal X=0, no ofList arm) when either is
# absent.  15 is retired (P7.5c-1b brecOn); 18/19 are free — see ENV_FORMAT §2.2.
STR_ID_CODES = {"String.ofList": 18, "String": 19}

# Names the encode-time shadow expansion of a string literal is built from
# (K/inductive.cpp:1368-1380; g_list_cons_char / g_string_mk).  All five must
# be present in the environment or the expansion is declined (K_LIT.X = 0).
STRING_EXPAND_NAMES = ("String.ofList", "List.cons", "List.nil",
                       "Char.ofNat", "Char")

LIT_STR_MAX_BYTES = 4095   # byte-chain length cap (VM_SPEC §14.2; mirrors the
                           # HINTS_HEIGHT_MAX convention — literals in this
                           # corpus are far shorter; raising keeps the stride-2
                           # chain inside the unrolled-loop budget)


def utf8_codepoints(data: bytes) -> list[int]:
    """Lean's LENIENT UTF-8 decoder, verbatim from runtime utf8_decode /
    next_utf8 (src/runtime/utf8.cpp:148-221), which string_lit_to_constructor
    applies (K/inductive.cpp:1368-1380).  A multi-byte sequence is accepted
    only with the right lead-byte pattern, enough trailing bytes (``i + k <
    size``, strictly), and an in-range result (2-byte: ``r >= 0x80``; 3-byte:
    ``r >= 0x800`` and outside the surrogate range; 4-byte: ``0x10000 <= r <=
    0x10FFFF``).  An invalid byte decodes to itself and advances by one."""
    out: list[int] = []
    i, size = 0, len(data)
    while i < size:
        c = data[i]
        if (c & 0x80) == 0:
            out.append(c); i += 1; continue
        if (c & 0xE0) == 0xC0 and i + 1 < size:
            r = ((c & 0x1F) << 6) | (data[i + 1] & 0x3F)
            if r >= 0x80:
                out.append(r); i += 2; continue
        if (c & 0xF0) == 0xE0 and i + 2 < size:
            r = (((c & 0x0F) << 12) | ((data[i + 1] & 0x3F) << 6)
                 | (data[i + 2] & 0x3F))
            if r >= 0x800 and (r < 0xD800 or r > 0xDFFF):
                out.append(r); i += 3; continue
        if (c & 0xF8) == 0xF0 and i + 3 < size:
            r = (((c & 0x07) << 18) | ((data[i + 1] & 0x3F) << 12)
                 | ((data[i + 2] & 0x3F) << 6) | (data[i + 3] & 0x3F))
            if 0x10000 <= r <= 0x10FFFF:
                out.append(r); i += 4; continue
        out.append(c); i += 1
    return out


def string_expansion(value: str) -> Expr:
    """The exact kernel ``string_lit_to_constructor`` tree
    (K/inductive.cpp:1368-1380): a right fold over the lenient-decoded UTF-8
    codepoints, ``App(Const("String.ofList"), L)`` with
    ``L = List.cons.{0} Char (Char.ofNat c) (...)`` ending in
    ``List.nil.{0} Char`` (empty string -> bare nil).  The encoder emits this
    as a SHADOW subtree behind the literal and points ``K_LIT.X`` at its root
    (VM_SPEC §14); reduction consumes it with one pointer hop."""
    nil = App(Const("List.nil", (LZero(),)), Const("Char"))
    l = nil
    for cp in reversed(utf8_codepoints(value.encode("utf-8", "surrogatepass"))):
        l = App(App(App(Const("List.cons", (LZero(),)), Const("Char")),
                    App(Const("Char.ofNat"), LitNat(cp))), l)
    return App(Const("String.ofList"), l)


def _digit_chain(value: int) -> list[int]:
    """Little-endian decimal digits of a non-negative int (canonical: no
    leading zeros; value 0 -> [0])."""
    if value == 0:
        return [0]
    out = []
    while value:
        out.append(value % 10)
        value //= 10
    return out


@dataclass
class StreamBundle:
    """A token stream plus its tables."""
    stream: list[tuple[int, int, int, int, int]] = field(default_factory=list)
    name_ids: dict[str, int] = field(default_factory=dict)      # name -> nid
    id_names: dict[int, str] = field(default_factory=dict)      # nid -> name
    cids: dict[str, int] = field(default_factory=dict)          # const -> cid
    cid_names: dict[int, str] = field(default_factory=dict)
    const_type_pos: dict[int, int] = field(default_factory=dict)  # cid -> type root
    const_value_pos: dict[int, int] = field(default_factory=dict) # cid -> value root (or -1)
    const_univ_arity: dict[int, int] = field(default_factory=dict)
    # Ordered lparams name-ids per cid (WP2, VM_SPEC §12.1): the declaration-side
    # names that runtime instantiation (D10/D14) maps onto use-site levels.
    const_lparams: dict[int, tuple[int, ...]] = field(default_factory=dict)
    const_has_value: dict[int, bool] = field(default_factory=dict)
    const_is_ctor: dict[int, bool] = field(default_factory=dict)
    # ENV metadata (ENV_FORMAT §2): anchor block position n+1..2n, per-cid kind
    # and flags, and the head of the specialized token chain (0 = none).
    n_consts: int = 0
    const_kind: dict[int, int] = field(default_factory=dict)
    const_flags: dict[int, int] = field(default_factory=dict)
    const_meta_pos: dict[int, int] = field(default_factory=dict)
    const_meta_head: dict[int, int] = field(default_factory=dict)

    def push(self, K, V0=0, V1=0, V2=0, X=0, E2=0, F2=0) -> int:
        self.stream.append((K, V0, V1, V2, X, E2, F2))
        return len(self.stream) - 1

    def env_anchor(self, cid: int) -> int:
        """Position of the T_ENV_META anchor for a constant id (ENV_FORMAT
        §2.7: contiguous anchor block at n+1..2n, anchor(cid) = n+1+cid).
        Falls back to reading n_consts from T_NULL.V0 when this bundle was
        not built by Encoder (n_consts unset)."""
        n = self.n_consts
        if n == 0 and self.stream:
            n = self.stream[0][1]
        return n + 1 + cid

    def nid(self, name: str) -> int:
        if name not in self.name_ids:
            i = len(self.name_ids) + 1
            self.name_ids[name] = i
            self.id_names[i] = name
            self.push(T_NAME, V0=i)
        return self.name_ids[name]



class Encoder:
    """Encodes a toy environment (constant list) and proof terms into a
    StreamBundle per VM_SPEC §3-§5.

    Optional ``const_meta`` (ENV_FORMAT §2) is a ``{cid: dict}`` mapping that
    carries the real kernel declaration metadata. Each dict uses the §2.4
    field names:

      kind        constant_info_kind 0..7 (§1.1) — required to emit metadata
      lparams     ordered LevelParam names (VM_SPEC §12.1). When present this
                  drives T_ENV_META.V0 = len(lparams) and emits a
                  T_ENV_UNIVPARAMS(K=39) + T_ENV_LIST(role=2) chain.
      univ_arity  T_ENV_META.V0 (default 0; v1 toy is monomorphic, §9.2).
                  Ignored when ``lparams`` is given; if both are supplied and
                  disagree the encoder raises (VM_SPEC §12.1 invariant).
      is_unsafe   Axiom/Opaque/Inductive/Constructor/Recursor (§2.4)
      hints, height, safety        Definition (hints 0..2 / height / safety 0..2)
      all         list[Name]       Definition/Axiom/Theorem/Opaque/Inductive/Recursor
      nparams, nindices, nnested, is_rec, is_reflexive   Inductive
      ctors       list[Name]       Inductive constructor order
      induct, cidx, nfields        Constructor (induct = name, resolved to cid)
      nmotives, nminors, is_k      Recursor
      rules       [{ctor, nfields, rhs}]                   Recursor rules (decl order)
      quot_kind   0..3             Quot

    Omitting ``const_meta`` (the default) preserves the previous behaviour:
    only the T_ENV header block and empty T_ENV_META anchors (V0=0, no
    specialized tokens) are emitted.
    """

    def __init__(self, consts: list[tuple[str, Expr, Optional[Expr]]],
                 is_ctor: Optional[dict[str, bool]] = None,
                 const_meta: Optional[dict[int, dict]] = None):
        self.b = StreamBundle()
        self.is_ctor = dict(is_ctor) if isinstance(is_ctor, dict) else {}
        self.const_meta = dict(const_meta) if const_meta else {}
        # cid -> declared type Expr, used to emit the instantiated declared
        # type (K_CONST.E2) at polymorphic use sites (WP2b, VM_SPEC §12.7).
        self._const_type_expr: dict[int, Expr] = {
            cid: ty for cid, (_n, ty, _v) in enumerate(consts)}
        self._specializing: set[int] = set()   # D14 emission cycle guard
        n = len(consts)
        self.b.n_consts = n
        # pass 1: NULL token at position 0 (queries keyed 0 match it; all
        # consumers gate on position >= 1), then the ENV_HDR block.
        # Layout (VM_SPEC §3 + ENV_FORMAT §2.7):
        #   pos 0            T_NULL (V0 = n_consts)
        #   pos 1..n         T_ENV header block (cid+1 addressing unchanged)
        #   pos n+1..2n      T_ENV_META anchor block (anchor(cid)=n+1+cid)
        #   pos 2n+1..       NAME table
        #   then type/value trees, rule rhs trees, specialized metadata,
        #   rule chains, list nodes, proof/workspace (appended later).
        # The header block must come first (query = cid+1); names must NOT
        # precede it (an earlier version pushed names first and the pass-2
        # header rewrite clobbered them; the X opcode field was lost,
        # 2026-08-30).
        self.b.push(0, V0=n)                # T_NULL, V0 = n_consts
        for cid, (name, ty, val) in enumerate(consts):
            self.b.cids[name] = cid
            self.b.cid_names[cid] = name
            self.b.push(T_ENV, V0=cid, V1=0, V2=0,
                        X=NAT_OP_CODES.get(
                            name, CTOR_ID_CODES.get(
                                name, STR_ID_CODES.get(name, 0))))
        for cid in range(n):
            self.b.push(T_ENV_META, V0=0)   # anchors, patched in _emit_metadata
            self.b.const_meta_pos[cid] = self.b.env_anchor(cid)
        # pass 2: register all names (contiguous NAME table after the anchor
        # block) so tree encoding finds them pre-registered
        for name, ty, val in consts:
            self.b.nid(name)
            self._collect_names(ty)
            if val is not None:
                self._collect_names(val)
        for cid in sorted(self.const_meta):
            self._collect_meta_names(self.const_meta[cid])
        # pass 3: encode type/value trees, then point the headers at them
        for cid, (name, ty, val) in enumerate(consts):
            tpos = self._enc_expr(ty, cid + 1)
            vpos = self._enc_expr(val, cid + 1) if val is not None else 0
            hdr = cid + 1
            X = self.b.stream[hdr][4]
            self.b.stream[hdr] = (T_ENV, cid, tpos, vpos, X, 0, 0)
            self.b.const_type_pos[cid] = tpos
            self.b.const_value_pos[cid] = vpos
            self.b.const_univ_arity[cid] = self._univ_arity(cid)
            # VM_SPEC §12.1: ordered lparams names as nids (declaration side);
            # the T_ENV_UNIVPARAMS chain is emitted in _emit_metadata from the
            # same list, so the two views cannot drift.
            self.b.const_lparams[cid] = tuple(
                self.b.nid(nm) for nm in
                ((self.const_meta.get(cid) or {}).get("lparams") or []))
            self.b.const_has_value[cid] = val is not None
            self.b.const_is_ctor[cid] = self.is_ctor.get(name, False)
        # rule rhs trees (ENV_FORMAT §2.6): appended with the env trees so
        # rule X=rhs_root_pos points backwards into the stream.
        self._rule_rhs_roots: dict[int, list[int]] = {}
        for cid in sorted(self.const_meta):
            m = self.const_meta[cid]
            roots = []
            for r in (m.get("rules") or []):
                rhs = r.get("rhs")
                roots.append(self._enc_expr(rhs, None) if rhs is not None else 0)
            self._rule_rhs_roots[cid] = roots
        # specialized metadata tokens + rule chains + list nodes
        self._emit_metadata(consts)

    def _univ_arity(self, cid: int) -> int:
        """Declared universe-parameter count for cid (T_ENV_META.V0,
        VM_SPEC §12.1). The ordered ``lparams`` names are the source of truth;
        a bare ``univ_arity`` count is accepted for backward compatibility
        (WP1 toy metadata / monomorphic constants) and must agree with
        ``len(lparams)`` when both are supplied."""
        m = self.const_meta.get(cid) or {}
        lp = m.get("lparams")
        if lp is None:
            return int(m.get("univ_arity", 0))
        lp = list(lp)
        if m.get("univ_arity") is not None and int(m["univ_arity"]) != len(lp):
            raise ValueError(
                f"cid {cid}: univ_arity {m['univ_arity']} != "
                f"len(lparams) {len(lp)} (VM_SPEC §12.1)")
        return len(lp)

    @staticmethod
    def _meta_flags(kind: int, m: dict) -> int:
        """T_ENV_META.X bitfield (ENV_FORMAT §2.3)."""
        f = 0
        if kind in (CK_DEFINITION, CK_THEOREM, CK_OPAQUE):
            f |= ENV_F_HAS_VALUE
        if kind == CK_CONSTRUCTOR:
            f |= ENV_F_IS_CTOR
        if kind == CK_INDUCTIVE:
            f |= ENV_F_IS_INDUCTIVE
        if kind == CK_RECURSOR:
            f |= ENV_F_IS_RECURSOR
        if kind == CK_QUOT:
            f |= ENV_F_IS_QUOT
        safety = int(m.get("safety", 1))
        unsafe = bool(m.get("is_unsafe", False)) or (
            kind == CK_DEFINITION and safety == 0)
        if unsafe:
            f |= ENV_F_IS_UNSAFE
        if kind == CK_DEFINITION and safety == 2:
            f |= ENV_F_IS_PARTIAL
        if kind == CK_INDUCTIVE:
            if m.get("is_rec"):
                f |= ENV_F_IS_REC
            if m.get("is_reflexive"):
                f |= ENV_F_IS_REFLEXIVE
        if kind == CK_RECURSOR and m.get("is_k"):
            f |= ENV_F_IS_K
        return f

    def _collect_meta_names(self, m: dict):
        for key in ("all", "ctors", "lparams"):
            for nm in (m.get(key) or []):
                self.b.nid(nm)
        if m.get("induct"):
            self.b.nid(m["induct"])
        for r in (m.get("rules") or []):
            self.b.nid(r["ctor"])
            rhs = r.get("rhs")
            if rhs is not None:
                self._collect_names(rhs)

    def _emit_metadata(self, consts):
        """Emit the specialized metadata region per ENV_FORMAT §2.4-§2.7:
        scalar/extra tokens (24-28, 36-38), then rule chains (29), then list
        nodes (35). Forward references (list/rule heads) are patched after
        the referenced tokens exist."""
        b = self.b
        pending: list[tuple[int, int, str, int]] = []  # (pos, field_idx, ref, cid)
        rules_head: dict[int, int] = {}
        list_head: dict[tuple[str, int], int] = {}
        for cid in range(len(consts)):
            name = b.cid_names[cid]
            m = self.const_meta.get(cid)
            kind = int(m["kind"]) if m and m.get("kind") is not None else None
            lparams = list(m.get("lparams") or []) if m else []
            if kind is None and not lparams:
                # no metadata: keep the old empty T_ENV_META (V0=0,V1=V2=X=0)
                b.const_kind[cid] = 0
                b.const_flags[cid] = 0
                b.const_meta_head[cid] = 0
                continue
            flags = self._meta_flags(kind, m) if kind is not None else 0
            head = 0
            if kind is None:
                # lparams-only metadata (no ConstantInfo kind supplied):
                # the univparams chain still hangs off the anchor.
                pass
            elif kind == CK_DEFINITION:
                hints = int(m.get("hints", 0))
                height = int(m.get("height", 0))
                if height > HINTS_HEIGHT_MAX:
                    # TBD/§6.1: saturate. Toy/real heights are tiny (<4096);
                    # >4095 is out of the v1 addressable range and has no
                    # defined encoding. Keep kind=Regular and clamp.
                    height = HINTS_HEIGHT_MAX
                safety = int(m.get("safety", 1))
                pos = b.push(T_ENV_DEFVAL, cid, hints, height, safety, 0, 0)
                pending.append((pos, 5, "all", cid))       # E2 = all_head
                head = pos
            elif kind in (CK_AXIOM, CK_THEOREM, CK_OPAQUE):
                pos = b.push(T_ENV_SIMPLEVAL, cid,
                             1 if m.get("is_unsafe") else 0, 0, 0, 0, 0)
                pending.append((pos, 3, "all", cid))       # V2 = all_head
                head = pos
            elif kind == CK_INDUCTIVE:
                np = int(m.get("nparams", 0)); ni = int(m.get("nindices", 0))
                nn = int(m.get("nnested", 0))
                pos = b.push(T_ENV_INDVAL, cid, np, ni, nn, 0, 0)
                extra = b.push(T_ENV_INDEXTRA, cid, 0, 0, 0, 0, 0)
                b.stream[pos] = (T_ENV_INDVAL, cid, np, ni, nn, 0, extra)
                pending.append((extra, 2, "all", cid))     # V1 = all_head
                pending.append((extra, 3, "ctors", cid))   # V2 = ctors_head
                head = pos
            elif kind == CK_CONSTRUCTOR:
                induct_cid = b.cids[m["induct"]]
                pos = b.push(T_ENV_CTORVAL, cid, induct_cid,
                             int(m.get("cidx", 0)), int(m.get("nparams", 0)),
                             int(m.get("nfields", 0)), 0)
                head = pos
            elif kind == CK_RECURSOR:
                np = int(m.get("nparams", 0)); ni = int(m.get("nindices", 0))
                nm = int(m.get("nmotives", 0)); nmin = int(m.get("nminors", 0))
                pos = b.push(T_ENV_RECVAL, cid, np, ni, nm, nmin, 0)
                extra = b.push(T_ENV_RECEXTRA, cid, 0, 0, 0, 0, 0)
                b.stream[pos] = (T_ENV_RECVAL, cid, np, ni, nm, nmin, extra)
                pending.append((extra, 2, "all", cid))     # V1 = all_head
                pending.append((extra, 3, "rules", cid))   # V2 = rules_head
                head = pos
            elif kind == CK_QUOT:
                pos = b.push(T_ENV_QUOTVAL, cid,
                             int(m.get("quot_kind", 0)), 0, 0, 0, 0)
                head = pos
            else:
                raise ValueError(f"cid {cid} ({name}): bad constant_info_kind {kind}")
            # WP2 (VM_SPEC §12.1): the ordered lparams names ride a
            # T_ENV_UNIVPARAMS(K=39) token appended to the per-cid meta chain,
            # carrying a T_ENV_LIST(role=2) name chain. T_ENV_META.V0 is the
            # count and must equal the chain length (_univ_arity enforces it).
            if lparams:
                upos = b.push(T_ENV_UNIVPARAMS, cid, 0, 0, 0, 0, 0)
                lhead = self._emit_list(cid, lparams, ENV_LIST_UNIVPARAMS)
                b.stream[upos] = (T_ENV_UNIVPARAMS, cid, lhead, 0, 0, 0, 0)
                head = self._chain_append(head, upos)
            anchor = b.env_anchor(cid)
            # WP7-G10 (K/type_checker.cpp:110-117): anchor.F2 = 1 iff a
            # safe-mode checker must reject REFERENCES to this constant
            # (declaration is unsafe, or definition safety == partial).
            # A precise bit-test on the X flags is not available in one
            # in-cycle select (bit 5 vs the >=64 bits of recursive ctors),
            # so the encoder precomputes the disjunction here (ENV_FORMAT
            # §2.3).  Streams without metadata keep F2=0 → graph gate inert.
            use_reject = 1 if (flags & (ENV_F_IS_UNSAFE | ENV_F_IS_PARTIAL)) else 0
            b.stream[anchor] = (T_ENV_META, self._univ_arity(cid),
                                kind if kind is not None else 0, head, flags,
                                0, use_reject)
            b.const_kind[cid] = kind if kind is not None else 0
            b.const_flags[cid] = flags
            b.const_meta_head[cid] = head
        # rule chains (29), decl order, linked through F2
        for cid in range(len(consts)):
            m = self.const_meta.get(cid)
            if not m or int(m.get("kind", -1)) != CK_RECURSOR:
                continue
            roots = self._rule_rhs_roots.get(cid, [])
            poss = []
            for i, r in enumerate(m.get("rules") or []):
                poss.append(b.push(T_ENV_RULE, cid, b.cids[r["ctor"]],
                                   int(r.get("nfields", 0)),
                                   roots[i] if i < len(roots) else 0, 0, 0))
            for i, p in enumerate(poss):
                nxt = poss[i + 1] if i + 1 < len(poss) else 0
                t = b.stream[p]
                b.stream[p] = (t[0], t[1], t[2], t[3], t[4], t[5], nxt)
            rules_head[cid] = poss[0] if poss else 0
        # list nodes (35): all (role 0) then ctors (role 1) per owner cid
        for cid in range(len(consts)):
            m = self.const_meta.get(cid)
            if not m:
                continue
            if m.get("all") is not None:
                list_head[("all", cid)] = self._emit_list(cid, m["all"], ENV_LIST_ALL)
            if int(m.get("kind", -1)) == CK_INDUCTIVE and m.get("ctors") is not None:
                list_head[("ctors", cid)] = self._emit_list(
                    cid, m["ctors"], ENV_LIST_CTORS)
        # patch forward references
        for pos, field, ref, cid in pending:
            h = rules_head.get(cid, 0) if ref == "rules" else \
                list_head.get((ref, cid), 0)
            t = b.stream[pos]
            b.stream[pos] = t[:field] + (h,) + t[field + 1:]

    def _emit_list(self, owner_cid: int, names, role: int) -> int:
        """Emit a T_ENV_LIST chain; returns the head position (0 if empty)."""
        b = self.b
        poss = []
        for nm in names:
            poss.append(b.push(T_ENV_LIST, owner_cid, b.nid(nm), role, 0, 0, 0))
        for i, p in enumerate(poss):
            nxt = poss[i + 1] if i + 1 < len(poss) else 0
            t = b.stream[p]
            b.stream[p] = (t[0], t[1], t[2], t[3], nxt, t[5], t[6])
        return poss[0] if poss else 0

    def _chain_append(self, head: int, pos: int) -> int:
        """Append ``pos`` to the end of an F2 meta chain whose head is
        ``head``; returns the (possibly new) head. The per-cid meta chain
        is singly linked through F2 (ENV_FORMAT §2.4)."""
        if not head:
            return pos
        p = head
        seen = set()
        while True:
            if p in seen:
                raise ValueError(f"meta chain cycle at {p}")
            seen.add(p)
            t = self.b.stream[p]
            if t[6] == 0:
                self.b.stream[p] = t[:6] + (pos,)
                return head
            p = t[6]

    # -- name collection -----------------------------------------------------
    def _collect_names(self, e):
        if isinstance(e, (FVar, MVar)):
            self.b.nid(e.name)
        elif isinstance(e, Proj):
            self.b.nid(e.sname)
        elif isinstance(e, Const):
            self.b.nid(e.name)
            for l in e.levels:
                self._collect_level_names(l)
        elif isinstance(e, App):
            self._collect_names(e.fn); self._collect_names(e.arg)
        elif isinstance(e, (Lam, Pi)):
            self._collect_names(e.domain); self._collect_names(e.body)
        elif isinstance(e, Let):
            self._collect_names(e.domain); self._collect_names(e.value)
            self._collect_names(e.body)
        elif isinstance(e, (MData,)):
            self._collect_names(e.child)
        elif isinstance(e, Sort):
            # universe param names live in Sort levels (VM_SPEC §12.1); they
            # must be registered before tree encoding so the NAME table stays
            # in its contiguous region.
            self._collect_level_names(e.level)
        # BVar/Lit*: no names

    def _collect_level_names(self, l):
        if isinstance(l, (LParam, LMVar)):
            self.b.nid(l.name)
        elif isinstance(l, LSucc):
            self._collect_level_names(l.l)
        elif isinstance(l, (LMax, LIMax)):
            self._collect_level_names(l.a); self._collect_level_names(l.b)

    @staticmethod
    def _level_has_param(l: Level) -> bool:
        """Kernel has_param (K/level.cpp:262-278) on the Python model."""
        if isinstance(l, LParam):
            return True
        if isinstance(l, (LZero, LMVar)):
            return False
        if isinstance(l, LSucc):
            return Encoder._level_has_param(l.l)
        return (Encoder._level_has_param(l.a)
                or Encoder._level_has_param(l.b))

    @classmethod
    def _expr_has_param_univ(cls, e: Expr) -> bool:
        """Kernel has_param_univ (K/instantiate.cpp:233,238-239): does the
        expression contain a universe parameter? Mirrors the kernel's
        short-circuit so no chain is emitted for param-free types."""
        if isinstance(e, Sort):
            return cls._level_has_param(e.level)
        if isinstance(e, Const):
            return any(cls._level_has_param(l) for l in e.levels)
        if isinstance(e, App):
            return cls._expr_has_param_univ(e.fn) or \
                cls._expr_has_param_univ(e.arg)
        if isinstance(e, (Lam, Pi)):
            return cls._expr_has_param_univ(e.domain) or \
                cls._expr_has_param_univ(e.body)
        if isinstance(e, Let):
            return (cls._expr_has_param_univ(e.domain)
                    or cls._expr_has_param_univ(e.value)
                    or cls._expr_has_param_univ(e.body))
        if isinstance(e, MData):
            return cls._expr_has_param_univ(e.child)
        if isinstance(e, Proj):
            return cls._expr_has_param_univ(e.child)
        return False                              # BVar/FVar/MVar/Lit

    @staticmethod
    def _inst_level(l: Level, mp: dict) -> Level:
        """D10 instantiate on one level (K/level.cpp:317-340): replace LParam
        by the positional use-site level; other nodes recurse and are rebuilt
        only when a child changed (kernel's update_succ/update_max)."""
        if isinstance(l, LParam):
            return mp.get(l.name, l)
        if isinstance(l, (LZero, LMVar)):
            return l
        if isinstance(l, LSucc):
            c = Encoder._inst_level(l.l, mp)
            return l if c is l.l else LSucc(c)
        if isinstance(l, LMax):
            a = Encoder._inst_level(l.a, mp)
            b = Encoder._inst_level(l.b, mp)
            return l if (a is l.a and b is l.b) else LMax(a, b)
        # LIMax
        a = Encoder._inst_level(l.a, mp)
        b = Encoder._inst_level(l.b, mp)
        return l if (a is l.a and b is l.b) else LIMax(a, b)

    @classmethod
    def _inst_expr(cls, e: Expr, mp: dict) -> Expr:
        """D13 instantiate_lparams (K/instantiate.cpp:232-246): replace only
        Sort levels and Constant level args; other nodes recurse and are
        rebuilt only if a child changed. Param-free subtrees are shared
        (kernel short-circuit, K/instantiate.cpp:233,238-239)."""
        if not cls._expr_has_param_univ(e):
            return e
        if isinstance(e, Sort):
            nl = cls._inst_level(e.level, mp)
            return e if nl is e.level else Sort(nl)
        if isinstance(e, Const):
            nl = tuple(cls._inst_level(x, mp) for x in e.levels)
            return e if nl == e.levels else Const(e.name, nl)
        if isinstance(e, App):
            f = cls._inst_expr(e.fn, mp)
            a = cls._inst_expr(e.arg, mp)
            return e if (f is e.fn and a is e.arg) else App(f, a)
        if isinstance(e, (Lam, Pi)):
            d = cls._inst_expr(e.domain, mp)
            b = cls._inst_expr(e.body, mp)
            return e if (d is e.domain and b is e.body) else \
                type(e)(e.name, e.binfo, d, b)
        if isinstance(e, Let):
            d = cls._inst_expr(e.domain, mp)
            v = cls._inst_expr(e.value, mp)
            b = cls._inst_expr(e.body, mp)
            return e if (d is e.domain and v is e.value and b is e.body) else \
                Let(e.name, d, v, b, nondep=e.nondep)
        if isinstance(e, MData):
            c = cls._inst_expr(e.child, mp)
            return e if c is e.child else MData(c)
        if isinstance(e, Proj):
            c = cls._inst_expr(e.child, mp)
            return e if c is e.child else Proj(e.sname, e.idx, c)
        return e

    def _specialize_type(self, cid: int, levels) -> int:
        """D14 instantiate_type_lparams (K/instantiate.cpp:248-254): encode
        the declared type of ``cid`` with its lparams replaced by the
        positional use-site ``levels``, and return the encoded root (0 if no
        substitution applies). The kernel pairs ``info.get_lparams()`` with
        the const's level args positionally; a param-free type short-circuits
        (K/instantiate.cpp:238-240). ``_specializing`` breaks any degenerate
        self-reference so a malformed type cannot recurse forever."""
        m = self.const_meta.get(cid)
        lps = list((m or {}).get("lparams") or [])
        ty = self._const_type_expr.get(cid)
        if not lps or ty is None or len(lps) != len(levels):
            return 0
        if len(set(lps)) != len(lps) or cid in self._specializing:
            return 0
        if not self._expr_has_param_univ(ty):
            return 0
        mp = {lps[i]: levels[i] for i in range(len(lps))}
        inst = self._inst_expr(ty, mp)
        if inst is ty:
            return 0
        self._specializing.add(cid)
        try:
            return self._enc_expr(inst, None)
        finally:
            self._specializing.discard(cid)

    # -- encoding ------------------------------------------------------------
    def encode_term(self, e: Expr) -> int:
        """Append an expression tree after the ENV region; returns its root
        position."""
        return self._enc_expr(e, None)

    def _enc_expr(self, e: Expr, parent: Optional[int]) -> int:
        b = self.b
        if isinstance(e, BVar):
            return b.push(K_BVAR, V0=e.idx, V2=_p(parent))
        if isinstance(e, FVar):
            return b.push(K_FVAR, V0=b.nid(e.name), V2=_p(parent))
        if isinstance(e, MVar):
            return b.push(K_MVAR, V0=b.nid(e.name), V2=_p(parent))
        if isinstance(e, Sort):
            spos = b.push(K_SORT, V0=0, V2=_p(parent))
            lpos = self._enc_level(e.level, parent_pos=None)
            _fix_parent(b.stream, lpos, spos)
            t = b.stream[spos]
            b.stream[spos] = (t[0], lpos) + tuple(t[2:])
            return spos
        if isinstance(e, Const):
            cid = b.cids[e.name]
            # WP2b (VM_SPEC §12.7): at a polymorphic use site, emit the
            # instantiated declared type once and point K_CONST.E2 at it. The
            # graph's CONST infer selects E2 (kernel infer_constant returns
            # instantiate_type_lparams, K/type_checker.cpp:101-123).
            spec = 0
            if e.levels:
                spec = self._specialize_type(cid, e.levels)
            cpos = b.push(K_CONST, V0=cid, V2=_p(parent))
            if e.levels:
                roots = [self._enc_level(l, parent_pos=cpos) for l in e.levels]
                for i, r in enumerate(roots):
                    nxt = roots[i + 1] if i + 1 < len(roots) else 0
                    t = b.stream[r]
                    b.stream[r] = (t[0], t[1], t[2], t[3], nxt) + tuple(t[5:])
                b.stream[cpos] = (K_CONST, cid, roots[0], _p(parent), 0,
                                  spec, 0)
            elif spec:
                b.stream[cpos] = (K_CONST, cid, 0, _p(parent), 0, spec, 0)
            return cpos
        if isinstance(e, App):
            fpos = self._enc_expr(e.fn, None)
            apos = self._enc_expr(e.arg, None)
            pos = b.push(K_APP, V0=fpos, V1=apos, V2=_p(parent))
            _fix_parent(b.stream, fpos, pos)
            _fix_parent(b.stream, apos, pos)
            return pos
        if isinstance(e, (Lam, Pi)):
            K = K_LAM if isinstance(e, Lam) else K_PI
            dpos = self._enc_expr(e.domain, None)
            bpos = self._enc_expr(e.body, None)
            pos = b.push(K, V0=dpos, V1=bpos, V2=_p(parent), X=e.binfo)
            _fix_parent(b.stream, dpos, pos)
            _fix_parent(b.stream, bpos, pos)
            return pos
        if isinstance(e, Let):
            tpos = self._enc_expr(e.domain, None)
            vpos = self._enc_expr(e.value, None)
            bpos = self._enc_expr(e.body, None)
            pos = b.push(K_LET, V0=tpos, V1=vpos, V2=_p(parent), X=bpos)
            _fix_parent(b.stream, tpos, pos)
            _fix_parent(b.stream, vpos, pos)
            _fix_parent(b.stream, bpos, pos)
            return pos
        if isinstance(e, LitNat):
            digits = _digit_chain(e.value)
            head = b.push(K_LIT, V0=len(digits), V1=LIT_NAT, V2=_p(parent))
            for d in digits:
                b.push(0)                      # stride-2 gap (VM_SPEC §5)
                b.push(T_LIT_DIG, V0=d, V2=head)
            return head
        if isinstance(e, LitStr):
            # WP5-E1 (VM_SPEC §14): the literal's UTF-8 bytes live IN the tree
            # as a stride-2 byte chain (identical layout to the Nat digit
            # chain, so the graph's D_LITL loop compares it for free), and
            # head.X points at the encode-time shadow of the kernel's
            # string_lit_to_constructor expansion (K/inductive.cpp:1368-1380).
            # X = 0 declines the expansion (names absent from this env); the
            # literal then only supports whnf-stuck and byte-chain equality.
            data = e.value.encode("utf-8", "surrogatepass")
            n = len(data)
            if n > LIT_STR_MAX_BYTES:
                raise NotImplementedError(
                    f"string literal of {n} bytes exceeds the {LIT_STR_MAX_BYTES}"
                    " -byte v1 encoding cap (VM_SPEC §14.2)")
            head = b.push(K_LIT, V0=n, V1=LIT_STR, V2=_p(parent))
            for byte in data:
                b.push(0)                      # stride-2 gap (VM_SPEC §5)
                b.push(T_LIT_BYTE, V0=byte, V2=head)
            if all(nm in b.cids for nm in STRING_EXPAND_NAMES):
                xpos = self._enc_expr(string_expansion(e.value), None)
                t = b.stream[head]
                b.stream[head] = (t[0], t[1], t[2], t[3], xpos, t[5], t[6])
            return head
        if isinstance(e, MData):
            cpos = self._enc_expr(e.child, None)
            pos = b.push(K_MDATA, V0=cpos, V2=_p(parent))
            _fix_parent(b.stream, cpos, pos)
            return pos
        if isinstance(e, Proj):
            cpos = self._enc_expr(e.child, None)
            pos = b.push(K_PROJ, V0=b.nid(e.sname), V1=e.idx, V2=_p(parent),
                         X=cpos)
            _fix_parent(b.stream, cpos, pos)
            return pos
        raise TypeError(type(e))

    def _enc_level(self, l: Level, parent_pos: Optional[int]) -> int:
        b = self.b
        if isinstance(l, LZero):
            return b.push(KL_ZERO, V2=_p(parent_pos))
        if isinstance(l, LSucc):
            c = self._enc_level(l.l, None)
            pos = b.push(KL_SUCC, V0=c, V2=_p(parent_pos))
            _fix_parent(b.stream, c, pos)
            return pos
        if isinstance(l, (LMax, LIMax)):
            K = KL_MAX if isinstance(l, LMax) else KL_IMAX
            a = self._enc_level(l.a, None)
            c = self._enc_level(l.b, None)
            pos = b.push(K, V0=a, V1=c, V2=_p(parent_pos))
            _fix_parent(b.stream, a, pos)
            _fix_parent(b.stream, c, pos)
            return pos
        if isinstance(l, LParam):
            return b.push(KL_PARAM, V0=b.nid(l.name), V2=_p(parent_pos))
        if isinstance(l, LMVar):
            return b.push(KL_MVAR, V0=b.nid(l.name), V2=_p(parent_pos))
        raise TypeError(type(l))


def _p(parent: Optional[int]) -> int:
    return parent if parent is not None else 0


def _fix_parent(stream, child: int, parent: int):
    t = stream[child]
    if t[3] == 0:
        stream[child] = (t[0], t[1], t[2], parent) + tuple(t[4:])


# ── Decoding ────────────────────────────────────────────────────────────────

def decode_expr(b: StreamBundle, pos: int, depth: int = 0) -> Expr:
    """Reconstruct an Expr from the stream (de Bruijn decode). Closed terms
    only: bvar indices above the current binder depth indicate an encoding
    bug."""
    K, V0, V1, V2, X = b.stream[pos][:5]
    if K == K_BVAR:
        return BVar(V0)
    if K == K_FVAR:
        return FVar(b.id_names[V0])
    if K == K_MVAR:
        return MVar(b.id_names[V0])
    if K == K_SORT:
        return Sort(decode_level(b, V0))
    if K == K_CONST:
        levels = []
        r = V1
        while r:
            levels.append(decode_level(b, r))
            r = b.stream[r][4]   # sibling chain in X
        return Const(b.cid_names[V0], tuple(levels))
    if K == K_APP:
        return App(decode_expr(b, V0, depth), decode_expr(b, V1, depth))
    if K == K_LAM:
        return Lam("", X, decode_expr(b, V0, depth),
                   decode_expr(b, V1, depth + 1))
    if K == K_PI:
        return Pi("", X, decode_expr(b, V0, depth),
                  decode_expr(b, V1, depth + 1))
    if K == K_LET:
        return Let("", decode_expr(b, V0, depth), decode_expr(b, V1, depth),
                   decode_expr(b, X, depth + 1))
    if K == K_LIT:
        if V1 == LIT_NAT:
            n = V0
            value = 0
            for i in range(n):
                d = b.stream[pos + 2 + 2 * i][1]
                value += d * (10 ** i)
            return LitNat(value)
        if V1 == LIT_STR:
            # WP5-E1: byte i of the literal's UTF-8 data lives at
            # pos+2+2i (T_LIT_BYTE token, VM_SPEC §14.1).
            data = bytes(b.stream[pos + 2 + 2 * i][1] for i in range(V0))
            return LitStr(data.decode("utf-8", "surrogatepass"))
        raise ValueError(f"unknown literal kind {V1} at {pos}")
    if K == K_MDATA:
        return MData(decode_expr(b, V0, depth))
    if K == K_PROJ:
        return Proj(b.id_names[V0], V1, decode_expr(b, X, depth))
    if K == T_LIT_DIG:
        raise ValueError(f"digit token at {pos} outside a chain")
    raise ValueError(f"unknown token kind {K} at {pos}")


def decode_closure(b: StreamBundle, pos: int, env: int = 0,
                   depth: int = 0) -> Expr:
    """Decode a closure (result position + link-chain environment):
    BVar(i) with i < depth is locally bound; i >= depth resolves through
    the LINK chain (i - depth steps back from env)."""
    K, V0, V1, V2, X = b.stream[pos][:5]
    if K == K_BVAR:
        if V0 < depth:
            return BVar(V0)
        cur = env
        steps = V0 - depth
        for _ in range(steps):
            cur = b.stream[cur][3]
            if not cur:
                raise ValueError(f"decode_closure: bvar {V0} beyond env")
        link = b.stream[cur]
        return decode_closure(b, link[1], link[4], 0)
    if K == K_APP:
        return App(decode_closure(b, V0, env, depth),
                   decode_closure(b, V1, env, depth))
    if K == K_LAM:
        return Lam("", X, decode_closure(b, V0, env, depth),
                   decode_closure(b, V1, env, depth + 1))
    if K == K_PI:
        return Pi("", X, decode_closure(b, V0, env, depth),
                  decode_closure(b, V1, env, depth + 1))
    if K == K_MDATA:
        return MData(decode_closure(b, V0, env, depth))
    if K == T_PI_CLO:
        # machine-emitted Pi type: X = domain env, E2 = body env
        return Pi("", 0, decode_closure(b, V0, X, depth),
                  decode_closure(b, V1, b.stream[pos][5], depth + 1))
    if K == K_LET:
        return Let("", decode_closure(b, V0, env, depth),
                   decode_closure(b, V1, env, depth),
                   decode_closure(b, X, env, depth + 1))
    # everything else has no bvar-bearing children affected by env
    return decode_expr(b, pos, depth)


def decode_level(b: StreamBundle, pos: int) -> Level:
    K, V0, V1, V2, X = b.stream[pos][:5]
    if K == KL_ZERO:
        return LZero()
    if K == KL_SUCC:
        return LSucc(decode_level(b, V0))
    if K == KL_MAX:
        return LMax(decode_level(b, V0), decode_level(b, V1))
    if K == KL_IMAX:
        return LIMax(decode_level(b, V0), decode_level(b, V1))
    if K == KL_PARAM:
        return LParam(b.id_names[V0])
    if K == KL_MVAR:
        return LMVar(b.id_names[V0])
    raise ValueError(f"unknown level kind {K} at {pos}")


# ── ENV metadata decoding (ENV_FORMAT §5.1) ─────────────────────────────────

def _decode_list(b: StreamBundle, head: int) -> list[str]:
    """Follow a T_ENV_LIST chain (V1=nid, X=next_node); return names in order."""
    out: list[str] = []
    p = head
    seen = set()
    while p:
        if p in seen:
            raise ValueError(f"T_ENV_LIST cycle at {p}")
        seen.add(p)
        K, V0, V1, V2, X, E2, F2 = b.stream[p]
        if K != T_ENV_LIST:
            raise ValueError(f"expected T_ENV_LIST at {p}, got K={K}")
        out.append(b.id_names[V1])
        p = X
    return out


def _decode_rules(b: StreamBundle, head: int) -> list[dict]:
    """Follow a T_ENV_RULE chain (F2=next_rule); includes decoded rhs Expr."""
    out: list[dict] = []
    p = head
    seen = set()
    while p:
        if p in seen:
            raise ValueError(f"T_ENV_RULE cycle at {p}")
        seen.add(p)
        K, V0, V1, V2, X, E2, F2 = b.stream[p]
        if K != T_ENV_RULE:
            raise ValueError(f"expected T_ENV_RULE at {p}, got K={K}")
        out.append({
            "rec_cid": V0,
            "ctor": b.cid_names.get(V1),
            "ctor_cid": V1,
            "nfields": V2,
            "rhs_root": X,
            "rhs": decode_expr(b, X) if X else None,
        })
        p = F2
    return out


def decode_env_meta(b: StreamBundle, cid: int) -> dict:
    """Read anchor(cid) (T_ENV_META) and follow the F2 specialized-token
    chain, returning the ENV_FORMAT §2.4 fields as a dict. Absent fields are
    left at None/[] so the caller can compare per kind.

    Keys: cid, name, anchor, univ_arity, kind, flags, meta_head, has_value,
    is_ctor, is_inductive, is_recursor, is_quot, is_unsafe, is_rec,
    is_reflexive, is_k, is_partial; kind-specific: hints_kind, hints_height,
    safety, all, nparams, nindices, nnested, ctors, induct, cidx, nfields,
    nmotives, nminors, major_idx, rules, quot_kind.
    """
    anchor = b.env_anchor(cid)
    if anchor >= len(b.stream):
        raise ValueError(f"cid {cid}: anchor {anchor} out of range")
    t = b.stream[anchor]
    if t[0] != T_ENV_META:
        raise ValueError(f"cid {cid}: anchor {anchor} is K={t[0]}, not T_ENV_META")
    _K, univ_arity, kind, head, flags, _E2, _F2 = t
    out: dict = {
        "cid": cid, "name": b.cid_names.get(cid), "anchor": anchor,
        "univ_arity": univ_arity, "kind": kind, "flags": flags,
        "meta_head": head,
        "has_value": bool(flags & ENV_F_HAS_VALUE),
        "is_ctor": bool(flags & ENV_F_IS_CTOR),
        "is_inductive": bool(flags & ENV_F_IS_INDUCTIVE),
        "is_recursor": bool(flags & ENV_F_IS_RECURSOR),
        "is_quot": bool(flags & ENV_F_IS_QUOT),
        "is_unsafe": bool(flags & ENV_F_IS_UNSAFE),
        "is_rec": bool(flags & ENV_F_IS_REC),
        "is_reflexive": bool(flags & ENV_F_IS_REFLEXIVE),
        "is_k": bool(flags & ENV_F_IS_K),
        "is_partial": bool(flags & ENV_F_IS_PARTIAL),
        "hints_kind": None, "hints_height": None, "safety": None,
        "all": [], "nparams": None, "nindices": None, "nnested": None,
        "ctors": [], "induct": None, "cidx": None, "nfields": None,
        "nmotives": None, "nminors": None, "major_idx": None,
        "rules": [], "quot_kind": None, "lparams": [],
    }
    p = head
    seen = set()
    while p:
        if p in seen:
            raise ValueError(f"cid {cid}: meta chain cycle at {p}")
        seen.add(p)
        K, V0, V1, V2, X, E2, F2 = b.stream[p]
        if K == T_ENV_DEFVAL:
            out["hints_kind"] = V1
            out["hints_height"] = V2
            out["safety"] = X
            out["all"] = _decode_list(b, E2)
        elif K == T_ENV_SIMPLEVAL:
            out["is_unsafe"] = bool(V1)
            out["all"] = _decode_list(b, V2)
        elif K == T_ENV_INDVAL:
            out["nparams"] = V1
            out["nindices"] = V2
            out["nnested"] = X
        elif K == T_ENV_CTORVAL:
            out["induct"] = b.cid_names.get(V1)
            out["cidx"] = V2
            out["nparams"] = X
            out["nfields"] = E2
        elif K == T_ENV_RECVAL:
            out["nparams"] = V1
            out["nindices"] = V2
            out["nmotives"] = X
            out["nminors"] = E2
            out["major_idx"] = V1 + V2 + X + E2
        elif K == T_ENV_QUOTVAL:
            out["quot_kind"] = V1
        elif K == T_ENV_INDEXTRA:
            out["all"] = _decode_list(b, V1)
            out["ctors"] = _decode_list(b, V2)
        elif K == T_ENV_RECEXTRA:
            out["all"] = _decode_list(b, V1)
            out["rules"] = _decode_rules(b, V2)
        elif K == T_ENV_UNIVPARAMS:
            # V1 = head of a T_ENV_LIST(role=2) chain of ordered lparams names
            if V1 and b.stream[V1][3] != ENV_LIST_UNIVPARAMS:
                raise ValueError(
                    f"cid {cid}: univparams list at {V1} has role "
                    f"{b.stream[V1][3]}, expected {ENV_LIST_UNIVPARAMS}")
            out["lparams"] = _decode_list(b, V1)
        else:
            raise ValueError(f"cid {cid}: unexpected meta token K={K} at {p}")
        p = F2
    if out["univ_arity"] != len(out["lparams"]):
        raise ValueError(
            f"cid {cid}: univ_arity {out['univ_arity']} != lparams chain "
            f"length {len(out['lparams'])} (VM_SPEC §12.1)")
    return out

