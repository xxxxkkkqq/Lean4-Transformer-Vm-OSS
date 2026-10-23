"""Card 012 M-C oracle channel: checked re-add of closure constants and
mutations against a bulk-loaded (unchecked) closure environment.

The MC oracle template derives from the M-A RT_TEMPLATE
(scripts/export_mathlib_closure.py): the whole closure is loaded with
addDeclWithoutChecking (the proven M-A channel), then each MCCASE line —
a DUMPCONST-style json the harness built (a renamed const for the ACCEPT
class, or a type/value/level mutation for the reject classes) — is built
into a Declaration and added with the CHECKED Kernel.Environment.addDecl.
The verdict class (Lean.Kernel.Exception constructor name) is printed per
case; expectations are always the live oracle's, never hand-set.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.export_mathlib_closure import RT_TEMPLATE

LEAK = os.environ.get("L4TVM_LEAN")
LEAN = LEAK or str(Path.home() / ".elan" / "toolchains"
                   / "leanprover--lean4---v4.33.1" / "bin" / "lean")


def mc_template() -> str:
    """RT_TEMPLATE with the re-dump tail replaced by the checked-add case
    loop.  The parse/build/bulk-add machinery is reused verbatim."""
    body = RT_TEMPLATE
    marker = "  -- re-dump every original name"
    i = body.index(marker)
    head = body[:i]
    tail = '''  -- M-C checked-add phase: every MCCASE line carries a case id and a
  -- DUMPCONST-style json (kind axiom/def/thm).  The declaration is built
  -- with the same mkDecl and added with the CHECKED addDecl — the kernel
  -- re-validates the whole (type, value) pair against this environment.
  let some casesPath ← IO.getEnv "MC_CASES"
    | throw (IO.userError "MC_CASES not set")
  let ctxt ← IO.FS.readFile casesPath
  for line in ctxt.splitOn "\\n" do
    if "MCCASE ".isPrefixOf line then
      let rest := (line.drop 7).toString
      let sp := rest.splitOn " "
      let cid := sp.getD 0 ""
      let js := (rest.drop (cid.length + 1)).toString
      match Json.parse js with
      | .ok j =>
        let decl ← liftE (mkDecl j)
        match Kernel.Environment.addDecl kenv ({} : Options) decl with
        | .ok _ => IO.println s!"MCCASE {cid} OK"
        | .error ex =>
          let cls := match ex with
            | .other m => s!"other:{m}"
            | .unknownConstant _ n => s!"unknownConstant {n}"
            | .alreadyDeclared _ n => s!"alreadyDeclared {n}"
            | .declHasMVars _ n _ => s!"declHasMVars {n}"
            | .declHasFVars _ n _ => s!"declHasFVars {n}"
            | .declTypeMismatch _ _ _ => "declTypeMismatch"
            | .funExpected .. => "funExpected"
            | .typeExpected .. => "typeExpected"
            | .letTypeMismatch .. => "letTypeMismatch"
            | .exprTypeMismatch .. => "exprTypeMismatch"
            | .appTypeMismatch .. => "appTypeMismatch"
            | .thmTypeIsNotProp _ _ _ => "thmTypeIsNotProp"
            | .invalidProj _ _ _ => "invalidProj"
            | _ => "other"
          IO.println s!"MCCASE {cid} {cls}"
      | .error e => IO.println s!"MCCASE {cid} BADJSON {e}"
  IO.println s!"MC-OK"
'''
    return head + tail


def run_mc_oracle(closure_jsonl: Path, cases_path: Path,
                  out_path: Path, cwd: Path | None = None) -> dict[str, str]:
    """Build the MC oracle file and run it; return {case_id: class}."""
    tpl = mc_template()
    mc_lean = out_path.parent / "mc_oracle.lean"
    mc_lean.write_text(tpl)
    env = dict(os.environ)
    env["RT_IN"] = str(closure_jsonl)
    env["RT_OUT"] = str(out_path)  # unused after the tail splice; the
    #                      template head still reads it
    env["MC_CASES"] = str(cases_path)
    r = subprocess.run([LEAN, "--run", str(mc_lean)], capture_output=True,
                       text=True, timeout=1800, cwd=cwd, env=env)
    if r.returncode != 0:
        raise RuntimeError(f"MC oracle lean failed:\n{r.stderr[-4000:]}")
    out: dict[str, str] = {}
    for line in r.stdout.splitlines():
        if line.startswith("MCCASE "):
            parts = line.split(" ", 2)
            out[parts[1]] = parts[2] if len(parts) > 2 else "?"
    return out
