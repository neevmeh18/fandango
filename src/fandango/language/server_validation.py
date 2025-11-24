#!/usr/bin/env python3
import os
import sys
import time
import socket
import contextlib
import json
from pathlib import Path
from typing import Dict, List

from fandango.language.parse import parse
from fandango.evolution.algorithm import Fandango, LoggerLevel
from fandango.language.grammar import FuzzingMode


# parse once, outside the runs loop
def load_parsed_grammar(fan_file: str):
    fan_path = Path(fan_file).resolve()
    print(f"[load_parsed_grammar] Parsing grammar from {fan_path}")
    with open(fan_path, "r") as f:
        grammar, constraints = parse(f, use_stdlib=False)
    print("[load_parsed_grammar] Parsed grammar (reuse this for multiple Fandango instances).")
    return grammar, constraints

# --- Solution inspection (kept and slightly hardened) ---
def parse_solution_result(solution, server_text_lines, symbol: str, mutation_symbol: str):
    """
    Inspect a single DerivationTree solution and server text lines and return:
        (symbol_ok, symbol_fail, mutation_ok, mutation_fail)
    where each value is 0 or 1 depending on whether the symbol/mutation appeared
    and whether the server produced an error for this run.
    """
    # normalize
    if not symbol.startswith("<"):
        symbol = f"<{symbol}>"
    original_symbol = symbol

    if not mutation_symbol.startswith("<"):
        mutation_symbol = f"<{mutation_symbol}>"

    # 1) What nonterminals were used in this solution?
    try:
        nts = set(nt.name() for nt in solution.get_non_terminal_symbols())
    except Exception:
        # fallback: best-effort from string
        try:
            s = solution.to_tree() if hasattr(solution, "to_tree") else str(solution)
            nts = set()
            # simple heuristic: collect substrings like '<NAME>'
            cur = None
            token = ""
            for ch in s:
                if ch == "<":
                    token = "<"
                    cur = True
                elif ch == ">" and cur:
                    token += ">"
                    nts.add(token)
                    token = ""
                    cur = False
                elif cur:
                    token += ch
            # conservative: if heuristic fails produce empty set
        except Exception:
            nts = set()

    # 2) Decide if server reported an error in the run.
    error_indicators = [
        "-ERR Unknown command",
        "Timed out while waiting for next message fragment from Server",
        "Could not parse received message fragments into predicted NonTerminals",
        "Timed out while waiting for message from remote party",
    ]

    # If server_text_lines provided, join and search; otherwise use solution.to_string()
    joined_text = ""
    if server_text_lines:
        joined_text = "\n".join(server_text_lines)
    else:
        try:
            joined_text = solution.to_string()
        except Exception:
            joined_text = str(solution)

    is_error = any(ind in joined_text for ind in error_indicators)

    # 3) Determine counts (0/1) for this single solution
    symbol_ok = symbol_fail = mutation_ok = mutation_fail = 0

    if mutation_symbol in nts:
        if is_error:
            mutation_fail = 1
        else:
            mutation_ok = 1
    elif original_symbol in nts:
        if is_error:
            symbol_fail = 1
        else:
            symbol_ok = 1

    return symbol_ok, symbol_fail, mutation_ok, mutation_fail

def attribute_from_rule_sigs(rule_sigs, original_symbol, mutation_symbol, is_error, totals):
    """
    rule_sigs: list[str] like "<LIST>::= 'LIST' <space> <message_number>"
    is_error: bool - whether this run produced a server error
    totals: dict-like with keys 'symbol_ok','symbol_fail','mutation_ok','mutation_fail'
    """
    # Normalize prefixes we're looking for
    orig_prefix = f"{original_symbol}::="
    mut_prefix = f"{mutation_symbol}::="

    mutation_present = any(rs.startswith(mut_prefix) for rs in rule_sigs)
    original_present = any(rs.startswith(orig_prefix) for rs in rule_sigs)

    if mutation_present:
        if is_error:
            totals["mutation_fail"] += 1
            print("[attribute] mutation present and server error -> mutation_fail += 1")
        else:
            totals["mutation_ok"] += 1
            print("[attribute] mutation present and server OK -> mutation_ok += 1")
        return "mutation"
    elif original_present:
        if is_error:
            totals["symbol_fail"] += 1
            print("[attribute] original symbol present and server error -> symbol_fail += 1")
        else:
            totals["symbol_ok"] += 1
            print("[attribute] original symbol present and server OK -> symbol_ok += 1")
        return "original"
    else:
        print("[attribute] Neither mutation nor original symbol found in rule_sigs.")
        return "none"



def collect_rule_signatures(node, signatures=None):
    if signatures is None:
        signatures = []
    if node.is_non_terminal:
        rhs = []
        for child in node.children:
            rhs.append(child.symbol.name() if not child.is_terminal else child.symbol.format_as_spec())
        rule_sig = f"{node.symbol.name()}::={' '.join(rhs)}"
        signatures.append(rule_sig)
    for child in node.children:
        collect_rule_signatures(child, signatures)
    return signatures


def validate_grammar_with_server(
    fan_file: str,
    symbol: str,
    port: int = 8110,
    repetitions: int = 10,
    population_size: int = 20,
    logger_level: LoggerLevel = LoggerLevel.INFO,
    save_traces_dir: str = "derivation_logs",
) -> Dict[str, int]:
    """
    Validate a candidate grammar by running it against the server using a single
    in-process Fandango instance and consuming up to `population_size` solutions
    from its generator.

    Returns aggregated metrics as a dict:
      { "symbol_ok", "symbol_fail", "mutation_ok", "mutation_fail" }
    """
    try:
        grammar, constraints = load_parsed_grammar(fan_file)
    except Exception as e:
        print("[validate] ERROR parsing grammar:", e)
        return {
            "symbol_ok": 0,
            "symbol_fail": 0,
            "mutation_ok": 0,
            "mutation_fail": 0,
        }
    # normalize symbol formats
    if not symbol.startswith("<"):
        symbol = f"<{symbol}>"

    if symbol.startswith("<mutation_"):
        base = symbol[len("<mutation_"):-1]  # remove "<mutation_" and trailing ">"
        original_symbol = f"<{base}>"
    else:
        base = symbol.strip("<>")
        original_symbol = symbol

    mutation_symbol = f"<mutation_{base}>"

    symbol_ok_total = symbol_fail_total = mutation_ok_total = mutation_fail_total = 0

    # the minimum number of observed runs to accept early
    min_mutation_runs = min_symbol_runs = 5

    # create a single Fandango instance (this is the corrected logic)
    try:
        fandango = Fandango(
        grammar=grammar,
        constraints=constraints,
        population_size=20,   
        logger_level=LoggerLevel.INFO,
    )
    except Exception as e:
        print(f"[validate] ERROR creating Fandango instance: {e}")
        return {
            "symbol_ok": symbol_ok_total,
            "symbol_fail": symbol_fail_total,
            "mutation_ok": mutation_ok_total,
            "mutation_fail": mutation_fail_total,
        }

    # prepare the generator once and iterate through it up to population_size times
    try:
        gen_iter = fandango.generate(mode=FuzzingMode.IO)
    except Exception as e:
        print(f"[validate] ERROR starting generation: {e}")
        # try to attribute to instrumented state if available
        last_failure = getattr(fandango, "_last_failure", None)
        last_tree = getattr(fandango, "_last_history_tree", None)
        if last_tree is not None:
            try:
                nts = set(nt.name() for nt in last_tree.get_non_terminal_symbols())
            except Exception:
                nts = set()
            if mutation_symbol in nts:
                mutation_fail_total += 1
            elif original_symbol in nts:
                symbol_fail_total += 1
        elif last_failure is not None:
            print(f"[validate] Fandango reported failure info: {last_failure}")
        return {
            "symbol_ok": symbol_ok_total,
            "symbol_fail": symbol_fail_total,
            "mutation_ok": mutation_ok_total,
            "mutation_fail": mutation_fail_total,
        }

    iterator = iter(gen_iter)
    solutions_collected = 0

    os.makedirs(save_traces_dir, exist_ok=True)

    while solutions_collected < population_size:
        try:
            solution = next(iterator)
        except StopIteration:
            # generator naturally finished early
            print("[validate] Generation finished (StopIteration).")
            break
        except Exception as gen_exc:
            print(f"[validate] Generation iterator raised an exception: {gen_exc}")

            # attempt to get a partial history tree exposed by Fandango (instrumented)
            last_tree = getattr(fandango, "_last_history_tree", None)

            if last_tree is not None:
                try:
                    rule_sigs = collect_rule_signatures(last_tree)
                except Exception:
                    rule_sigs = []

                # save partial trace for inspection
                try:
                    rec_id = int(time.time() * 1000)
                    rec_path = f"{save_traces_dir}/partial_{rec_id}.json"
                    with open(rec_path, "w") as rf:
                        json.dump(rule_sigs, rf, indent=2)
                    print(f"[validate] Saved partial rule_sigs to {rec_path}")
                except Exception as e:
                    print(f"[validate] Warning: could not save partial rule_sigs: {e}")

                # we consider generator exception a server-side error for attribution purposes
                totals = {
                    "symbol_ok": symbol_ok_total,
                    "symbol_fail": symbol_fail_total,
                    "mutation_ok": mutation_ok_total,
                    "mutation_fail": mutation_fail_total,
                }
                attribute_from_rule_sigs(rule_sigs, original_symbol, mutation_symbol, is_error=True, totals=totals)

                # write totals back to outer variables
                symbol_ok_total = totals["symbol_ok"]
                symbol_fail_total = totals["symbol_fail"]
                mutation_ok_total = totals["mutation_ok"]
                mutation_fail_total = totals["mutation_fail"]

            else:
                print("[validate] No partial tree available to attribute generator exception (no action taken).")

            # Stop iterating on generator exception
            break
        # process the yielded solution
        solutions_collected += 1
        print(f"\n[validate] Processing solution #{solutions_collected}")

        try:
            rule_sigs = collect_rule_signatures(solution)
            run_id = int(time.time() * 1000)
            path = f"{save_traces_dir}/run_{run_id}.json"
            with open(path, "w") as f:
                json.dump(rule_sigs, f, indent=2)
            print(f"[validate] Saved {len(rule_sigs)} rule signatures to {path}")
        except Exception as e:
            print(f"[validate] Warning: failed to save derivation trace: {e}")
            rule_sigs = []

        # Build textual lines for lightweight error detection
        txt_lines = str(solution).splitlines()
        for ln in txt_lines:
            print("FANDANGO_MSG:", ln)

        # determine if server reported an error in this run (same indicators as before)
        error_indicators = [
            "-ERR Unknown command",
            "Timed out while waiting for next message fragment from Server",
            "Could not parse received message fragments into predicted NonTerminals",
            "Timed out while waiting for message from remote party"
        ]
        joined_text = "\n".join(txt_lines)
        is_error = any(ind in joined_text for ind in error_indicators)

        # Attribute using rule_sigs (mutation preferred)
        totals = {
            "symbol_ok": symbol_ok_total,
            "symbol_fail": symbol_fail_total,
            "mutation_ok": mutation_ok_total,
            "mutation_fail": mutation_fail_total,
        }
        attribute_from_rule_sigs(rule_sigs, original_symbol, mutation_symbol, is_error=is_error, totals=totals)
        # write back totals
        symbol_ok_total = totals["symbol_ok"]
        symbol_fail_total = totals["symbol_fail"]
        mutation_ok_total = totals["mutation_ok"]
        mutation_fail_total = totals["mutation_fail"]

        # Stop early if mutation caused any failure (matching original behavior)
        if mutation_fail_total > 0:
            print("❌ Grammar rejected (mutation caused server failures).")
            break

        # stop once we have seen mutation usage at least once and reached baseline repetitions
        if (
            (mutation_ok_total + mutation_fail_total) >= min_mutation_runs
            and (symbol_ok_total + symbol_fail_total) >= min_symbol_runs
        ):
            print("✅ Minimum samples collected, stopping early.")
            break

    # final aggregated metrics printout
    print("\n=== Aggregated Metrics ===")
    print(f"{original_symbol} present + server OK:   {symbol_ok_total}")
    print(f"{original_symbol} present + server FAIL: {symbol_fail_total}")
    print(f"{mutation_symbol} present + server OK:   {mutation_ok_total}")
    print(f"{mutation_symbol} present + server FAIL: {mutation_fail_total}")

    spec_env_global, _ = grammar.get_spec_env()
    io_cls = spec_env_global["FandangoIO"]
    io_instance = io_cls.instance()
    io_instance.reset_parties()

    return {
        "symbol_ok": symbol_ok_total,
        "symbol_fail": symbol_fail_total,
        "mutation_ok": mutation_ok_total,
        "mutation_fail": mutation_fail_total,
    }

    



def decision_logic(metrics: Dict[str, int], mode="normal") -> str:
    """
    Decide if grammar is acceptable based on collected metrics.
    Returns one of: "accept", "reject", "alt_removal", "inconclusive"

    Logic:
      1. If mutation caused failures → "reject".
      2. If mutation used and no failures:
         a. If all non-mutation runs are OK → "accept".
         b. Else → "alt_removal".
      3. If mutation never triggered → "inconclusive".
    """
    mutation_used = (metrics.get("mutation_ok", 0) + metrics.get("mutation_fail", 0)) > 0
    symbol_runs = metrics.get("symbol_ok", 0) + metrics.get("symbol_fail", 0)

    if metrics.get("mutation_fail", 0) > 0:
        return "reject"

    if mutation_used:
        if symbol_runs == 0 and mode != "alt_removal":
            return "alt_removal" #if symbol not needed remove it
        if metrics.get("symbol_fail", 0) == 0:
            return "accept"
        else:
            return "alt_removal"

    return "inconclusive"


if __name__ == "__main__":
    fan_path = "output/best_candidates/round1/<rule>/candidate.fan"
    symbol = "<LIST>"


    population_size = 20
    repetitions = 3  
    metrics = validate_grammar_with_server(fan_path, symbol, port=25110, repetitions=repetitions, population_size=population_size)
    decision = decision_logic(metrics)

    print(f"[main] decision: {decision}")
    
    # exit 0 only for accept; non-zero otherwise
    sys.exit(0 if decision == "accept" else 1)
