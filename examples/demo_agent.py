#!/usr/bin/env python3
"""
Demo agent: a tiny RPG character builder powered by lambda-Tool.

This script showcases lambda-Tool as a safe intermediate language for
composing real Python tool calls. Every tool executor does genuine
computation -- dice rolls, math, timestamp generation, file I/O --
and the lambda-Tool type checker verifies the composition is safe
BEFORE any tool runs.

Features demonstrated:
  - Multiple tool declarations with different effect annotations
  - traverse: batch tool calls over a list (roll dice for each stat)
  - fold: aggregate results (compute total modifier)
  - Conditional logic (classify character power level)
  - Record construction and field projection
  - Error handling via match Ok/Err

Usage:
    python3 examples/demo_agent.py
"""

from __future__ import annotations

import math
import os
import random
import sys
import time

# Allow running from project root without installing the package
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lambda_tool import LambdaTool, LambdaToolError


# ---------------------------------------------------------------------------
# Tool executors: real Python functions that do real work
# ---------------------------------------------------------------------------

def roll_dice(arg: dict) -> dict:
    """Roll dice using standard RPG notation. Takes {sides, count}, returns {rolls, total}."""
    sides = arg["sides"]
    count = arg["count"]
    rolls = [random.randint(1, sides) for _ in range(count)]
    total = sum(rolls)
    print(f"    [roll_dice] {count}d{sides} => {rolls} (total: {total})")
    return {"rolls": rolls, "total": total}


def stat_modifier(arg: dict) -> dict:
    """Compute the D&D-style ability modifier for a stat score."""
    score = arg["score"]
    mod = math.floor((score - 10) / 2)
    print(f"    [stat_modifier] score {score} => modifier {mod:+d}")
    return {"modifier": mod}


def timestamp(arg: dict) -> dict:
    """Return the current Unix timestamp and a human-readable string."""
    now = time.time()
    human = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now))
    print(f"    [timestamp] {human}")
    return {"unix": int(now), "human": human}


def write_log(arg: dict) -> dict:
    """Append a line to a log file. Returns the number of bytes written."""
    message = arg["message"]
    log_path = os.path.join(os.path.dirname(__file__), "agent_log.txt")
    with open(log_path, "a") as f:
        n = f.write(message + "\n")
    print(f"    [write_log] wrote {n} bytes to {os.path.basename(log_path)}")
    return {"bytes_written": n}


EXECUTORS = {
    "roll_dice": roll_dice,
    "stat_modifier": stat_modifier,
    "timestamp": timestamp,
    "write_log": write_log,
}


# ---------------------------------------------------------------------------
# lambda-Tool programs: what an LLM would generate
# ---------------------------------------------------------------------------

PROGRAM_ROLL_STATS = r"""
tool roll_dice: {sides: Int, count: Int} -{Read}-> {total: Int};
tool stat_modifier: {score: Int} -{Read}-> {modifier: Int};

let stats = ["STR", "DEX", "CON", "INT", "WIS", "CHA"] in

match traverse (fn name: String =>
    exec tool roll_dice {sides = 6, count = 3}
) stats {
  Ok(rolls) =>
    let scores = map (fn r: {total: Int} => r.total) rolls in
    match traverse (fn s: Int =>
        exec tool stat_modifier {score = s}
    ) scores {
      Ok(mods) =>
        let modifiers = map (fn m: {modifier: Int} => m.modifier) mods in
        let total_mod = fold (fn acc: Int => fn m: Int => acc + m) 0 modifiers in
        {scores = scores, modifiers = modifiers, total_modifier = total_mod},
      Err(e) => {scores = []: Int, modifiers = []: Int, total_modifier = 0}
    },
  Err(e) => {scores = []: Int, modifiers = []: Int, total_modifier = 0}
}
"""

def make_classify_program(total_mod: int) -> str:
    """Build the classification program with the total modifier inlined.

    We encode the value as a let-binding to avoid parser issues with
    negative literal substitution (lambda-Tool has no negative literals;
    negation is expressed as `0 - n`).
    """
    if total_mod >= 0:
        mod_expr = str(total_mod)
    else:
        mod_expr = f"(0 - {abs(total_mod)})"

    return f"""
tool timestamp: {{}} -{{Read}}-> {{unix: Int, human: String}};
tool write_log: {{message: String}} -{{Write}}-> {{bytes_written: Int}};

let total_mod = {mod_expr} in
match exec tool timestamp {{}} {{
  Ok(ts) =>
    let power = if total_mod > 5
                then "legendary"
                else if total_mod > 0
                then "capable"
                else if total_mod > (0 - 5)
                then "average"
                else "cursed" in
    let log_msg = "Character created at " in
    match exec tool write_log {{message = log_msg}} {{
      Ok(w) => {{power_level = power, created_at = ts.human, log_bytes = w.bytes_written}},
      Err(e) => {{power_level = power, created_at = ts.human, log_bytes = 0}}
    }},
  Err(e) => {{power_level = "unknown", created_at = "unknown", log_bytes = 0}}
}}
"""


# ---------------------------------------------------------------------------
# Main demo
# ---------------------------------------------------------------------------

def main():
    random.seed()  # true randomness

    lt = LambdaTool()
    stat_names = ["STR", "DEX", "CON", "INT", "WIS", "CHA"]

    print("=" * 60)
    print("  lambda-Tool Demo: RPG Character Builder")
    print("=" * 60)
    print()

    # --- Step 1: Type-check the stat rolling program ---
    print("[1] Type-checking stat roller...")
    try:
        tc = lt.typecheck(PROGRAM_ROLL_STATS)
        print(f"    Type: {tc.type}")
        print(f"    Effects: {tc.effects}")
        print()
    except LambdaToolError as e:
        print(f"    TYPE ERROR: {e}")
        sys.exit(1)

    # --- Step 2: Execute it with real dice rolls ---
    print("[2] Rolling stats (3d6 per ability)...")
    result = lt.run(PROGRAM_ROLL_STATS, executors=EXECUTORS)
    print()

    scores = result.value["scores"]
    modifiers = result.value["modifiers"]
    total_mod = result.value["total_modifier"]

    print("    +-------+-------+------+")
    print("    | Stat  | Score | Mod  |")
    print("    +-------+-------+------+")
    for name, score, mod in zip(stat_names, scores, modifiers):
        mod_str = f"{mod:+d}"
        print(f"    | {name:<5s} | {score:>5d} | {mod_str:>4s} |")
    print("    +-------+-------+------+")
    print(f"    Total modifier sum: {total_mod:+d}")
    print()

    # --- Step 3: Classify and log ---
    # Build the classification program with the total modifier inlined.
    # (In a real agent, the LLM would generate this with the value baked in.)
    classify_code = make_classify_program(total_mod)

    print("[3] Type-checking classifier...")
    try:
        tc2 = lt.typecheck(classify_code)
        print(f"    Type: {tc2.type}")
        print(f"    Effects: {tc2.effects}")
        print()
    except LambdaToolError as e:
        print(f"    TYPE ERROR: {e}")
        sys.exit(1)

    print("[4] Classifying character and writing log...")
    result2 = lt.run(classify_code, executors=EXECUTORS)
    print()

    power = result2.value["power_level"]
    created = result2.value["created_at"]
    log_bytes = result2.value["log_bytes"]

    print(f"    Power level : {power}")
    print(f"    Created at  : {created}")
    print(f"    Log written : {log_bytes} bytes")
    print()

    # --- Step 4: Demonstrate a type error being caught ---
    print("[5] Demonstrating type safety...")
    bad_code = r"""
    tool roll_dice: {sides: Int, count: Int} -{Read}-> {total: Int};
    exec tool roll_dice {sides = 6, count = 3}
    """
    try:
        lt.typecheck(bad_code)
        print("    (should not reach here)")
    except LambdaToolError as e:
        # The raw error includes OCaml AST details; show a clean summary
        err = e.errors[0]
        print(f"    Caught! The type checker rejected bare `exec` without match.")
        if "Unhandled Result" in err:
            print(f"    Reason: tool results MUST be pattern-matched (Ok/Err).")
        else:
            print(f"    Raw: {err}")
    print()

    # --- Step 5: Show effect tracking ---
    print("[6] Demonstrating effect tracking...")
    read_only_code = r"""
    tool roll_dice: {sides: Int, count: Int} -{Read}-> {total: Int};
    match exec tool roll_dice {sides = 20, count = 1} {
      Ok(r) => r.total,
      Err(e) => 0
    }
    """
    tc3 = lt.typecheck(read_only_code)
    print(f"    Read-only program effects: {tc3.effects}")

    mixed_code = r"""
    tool roll_dice: {sides: Int, count: Int} -{Read}-> {total: Int};
    tool write_log: {message: String} -{Write}-> {bytes_written: Int};
    match exec tool roll_dice {sides = 20, count = 1} {
      Ok(r) => match exec tool write_log {message = "rolled"} {
        Ok(w) => r.total,
        Err(e) => 0
      },
      Err(e) => 0
    }
    """
    tc4 = lt.typecheck(mixed_code)
    print(f"    Read+Write program effects: {tc4.effects}")
    print()

    print("=" * 60)
    print("  Done! All programs type-checked and executed safely.")
    print("=" * 60)

    # Clean up the log file
    log_path = os.path.join(os.path.dirname(__file__), "agent_log.txt")
    if os.path.exists(log_path):
        with open(log_path) as f:
            print(f"\n  Log file contents: {f.read().strip()!r}")
        os.unlink(log_path)


if __name__ == "__main__":
    main()
