#!/usr/bin/env python3
"""Memory-guarded command runner for the CPU regression.

AGENTS.md machine discipline: pure-Python differential evaluation has
already killed the host session once (quot graph eval hit 10.8GB RSS ->
global OOM, 2026-09-14 03:03). `ulimit -v` is useless with torch
(torch over-reserves virtual memory), so the cap must be enforced by
polling real RSS and killing the process group. This script is that
enforcement: run a command, watch its process tree's RSS, and kill
everything if the cap is crossed.

Usage:
  run_mem_guarded.py [--max-rss-mb N] [--timeout SECS] -- <cmd> [args...]

--max-rss-mb 0 disables the RSS check but keeps the other two guarantees:
the child runs in its own process group (timeout kills the whole tree, no
orphaned engine subprocesses) and wall/peak RSS are reported.

Exit codes:
  child rc            — child finished (including its own timeout/signal)
  137 + message       — guard killed the child for exceeding --max-rss-mb
  124                 — guard killed the child for exceeding --timeout

Peak RSS of the tree is always printed to stderr on exit.
"""
from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time


def _descendants(root: int) -> list[int]:
    """pid -> [children] map built from /proc/*/stat (comm may contain
    spaces/parens, so split off the parenthesized field from the right)."""
    children: dict[int, list[int]] = {}
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        pid = int(entry)
        try:
            with open(f"/proc/{pid}/stat") as f:
                data = f.read()
            rest = data[data.rindex(")") + 2:]        # after ") STATE"
            fields = rest.split()
            ppid = int(fields[1])                      # STATE ppid ...
            children.setdefault(ppid, []).append(pid)
        except (OSError, ValueError):
            continue                                    # vanished/perm
    out, stack = [], [root]
    while stack:
        p = stack.pop()
        out.append(p)
        stack.extend(children.get(p, []))
    return out


def _tree_rss_kb(root: int) -> int:
    total = 0
    for pid in _descendants(root):
        try:
            with open(f"/proc/{pid}/status") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        total += int(line.split()[1])
                        break
        except OSError:
            continue
    return total


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-rss-mb", type=int, default=6000)
    ap.add_argument("--timeout", type=float, default=0.0,
                    help="0 disables the guard-side timeout")
    args, cmd = ap.parse_known_args(sys.argv[1:])
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    if not cmd:
        ap.error("no command after --")

    proc = subprocess.Popen(cmd, start_new_session=True)
    cap_kb = args.max_rss_mb * 1024 if args.max_rss_mb > 0 else None
    peak_kb = 0
    killed_for = None
    t0 = time.monotonic()
    try:
        while proc.poll() is None:
            rss = _tree_rss_kb(proc.pid)
            if rss > peak_kb:
                peak_kb = rss
            if cap_kb and rss > cap_kb:
                killed_for = f"RSS {rss // 1024}MB > cap {args.max_rss_mb}MB"
                break
            if args.timeout and time.monotonic() - t0 > args.timeout:
                killed_for = f"wall {time.monotonic() - t0:.0f}s > timeout"
                break
            time.sleep(0.5)
    except KeyboardInterrupt:
        killed_for = "keyboard interrupt"
    if killed_for:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            proc.kill()
    proc.wait()
    dt = time.monotonic() - t0
    print(f"[mem-guard] wall {dt:.1f}s peak RSS {peak_kb // 1024}MB "
          f"rc={proc.returncode}" + (f" KILLED: {killed_for}" if killed_for
                                     else ""),
          file=sys.stderr, flush=True)
    if killed_for and killed_for.startswith("RSS"):
        return 137
    if killed_for and killed_for.startswith("wall"):
        return 124
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
