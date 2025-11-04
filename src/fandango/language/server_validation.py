import os
import sys
import time
import socket
import contextlib
import subprocess
import ast
from pathlib import Path
from typing import Dict, List, Tuple


def wait_for_server(host="127.0.0.1", port=8110, timeout=10) -> bool:
    """Wait until server is accepting connections (used before starting talk)."""
    start = time.time()
    while time.time() - start < timeout:
        with contextlib.suppress(OSError):
            with socket.create_connection((host, port), 0.1):
                return True
        time.sleep(0.1)
    return False


def run_fandango(fan_file: str, port: int = 8110) -> List[str]:
    """
    Run Fandango CLI in talk mode with the given grammar.
    Collect stdout lines, print them (stream style), and return them.
    """
    fan_file = Path(fan_file).resolve()
    cmd = ["fandango", "-v", "talk", "--infinite", "-f", str(fan_file), "--client", str(port)]
    print(f"\n[run_fandango] Running: {' '.join(cmd)}")

    lines: List[str] = []
    try:
        with subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
        ) as proc:
            for line in proc.stdout:
                line = line.strip()
                print("FANDANGO:", line)   # live stream
                lines.append(line)
    except KeyboardInterrupt:
        print("\n[run_fandango] Interrupted by user.")
    except Exception as e:
        print(f"\n[run_fandango] Error: {e}")

    return lines


def parse_nt_log(lines: List[str], symbol: str, mutation_symbol: str) -> Tuple[int, int, int, int]:
    """
    Parse Fandango CLI output lines.
    Look for NT_USED lines (list of nonterminals used) and correlate with server errors.
    """
    symbol_ok = symbol_fail = mutation_ok = mutation_fail = 0

    for idx, line in enumerate(lines):
        if "NT_USED:" in line:
            try:
                nt_list = ast.literal_eval(line.split("NT_USED:")[1].strip())
            except Exception:
                continue
            is_error = False
            # Look ahead in the next few lines for error messages
            j = idx + 1
            while j < len(lines) and "NT_USED:" not in lines[j]:
                if any(err in lines[j] for err in ["-ERR Unknown command", "Timed out while waiting for next message fragment from Server", "Could not parse received message fragments into predicted NonTerminals", "Timed out while waiting for message from remote party"]):
                    is_error = True
                    break
                j += 1

            if mutation_symbol in nt_list:
                # Prioritize mutation over base symbol
                if is_error:
                    print("XXXXXXXXXXXXXXXXXMutation caused server error.")
                    mutation_fail += 1
                else:
                    mutation_ok += 1
            elif symbol in nt_list:
                # Only count base symbol if no mutation was used
                if is_error:
                    print("XXXXXXXXXXXXXXXXXMutation caused server error.")
                    symbol_fail += 1
                else:
                    symbol_ok += 1


    return symbol_ok, symbol_fail, mutation_ok, mutation_fail


def validate_grammar_with_server(
    fan_file: str,
    symbol: str,
    port: int = 8110,
    repetitions: int = 5,
    max_runs: int = 20,
) -> Dict[str, int]:
    """
    Validate a candidate grammar by running it against the server several times.
    Returns aggregated metrics as a dict.
    Runs until mutation is used at least once (or max_runs reached).
    """
    min_mutation_runs = min_symbol_runs = 5

    # Normalize incoming symbol to <NAME> format
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
    runs = 0

    while runs < max_runs:
        runs += 1
        print(f"\n=== Run {runs} ===")
        lines = run_fandango(fan_file, port=port)

        s_ok, s_fail, m_ok, m_fail = parse_nt_log(lines, original_symbol, mutation_symbol)

        symbol_ok_total += s_ok
        symbol_fail_total += s_fail
        mutation_ok_total += m_ok
        mutation_fail_total += m_fail


        if mutation_fail_total > 0:
            print("❌ Grammar rejected (mutation caused server failures).")
            break  # no need to continue if mutation caused failure

        # stop once we have seen mutation usage at least once and reached baseline repetitions
        if (
            (mutation_ok_total + mutation_fail_total) >= min_mutation_runs
            and (symbol_ok_total + symbol_fail_total) >= min_symbol_runs
        ):
            print("✅ Minimum samples collected, stopping early.")
            break

    print("\n=== Aggregated Metrics ===")
    print(f"{original_symbol} present + server OK:   {symbol_ok_total}")
    print(f"{original_symbol} present + server FAIL: {symbol_fail_total}")
    print(f"<mutation> present + server OK:   {mutation_ok_total}")
    print(f"<mutation> present + server FAIL: {mutation_fail_total}")

    return {
        "symbol_ok": symbol_ok_total,
        "symbol_fail": symbol_fail_total,
        "mutation_ok": mutation_ok_total,
        "mutation_fail": mutation_fail_total,
    }


def decision_logic(metrics: Dict[str, int]) -> bool:
    """
    Decide if grammar is acceptable based on collected metrics.
    Returns True if grammar is accepted, False if rejected.
    
    Logic:
      1. If mutation caused failures → reject.
      2. If mutation caused no failures:
         a. If all non-mutation runs are OK → accept.
         b. If any non-mutation run failed → trigger alternative removal.
    """

    mutation_used = metrics["mutation_ok"] + metrics["mutation_fail"] > 0
    symbol_runs = metrics["symbol_ok"] + metrics["symbol_fail"]

    # Case 1: Mutation used and caused a failure
    if metrics["mutation_fail"] > 0:
        return "reject"

    # Case 2: Mutation used and no failures
    if mutation_used:
        if metrics["symbol_fail"] == 0:
            return "accept"
        else:
            return "alt_removal"


    return "inconclusive"  # Mutation never triggered




if __name__ == "__main__":
    # Example usage (replace with your actual candidate + symbol)
    fan_path = "output/best_candidates/round1/<rule>/candidate.fan"
    symbol = "<LIST>"

    metrics = validate_grammar_with_server(fan_path, symbol, port=25110, repetitions=3)
    ok = decision_logic(metrics)
    sys.exit(0 if ok else 1)
