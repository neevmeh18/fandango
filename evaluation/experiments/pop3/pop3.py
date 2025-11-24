import time

from fandango.evolution.algorithm import Fandango, LoggerLevel
from fandango.language.grammar import FuzzingMode
from fandango.language.parse import parse


def main():
    # Parse grammar and constraints
    with open("pop3.fan") as f:
        grammar, constraints = parse(
            f,
            use_stdlib=False,
        )

    time_start = time.time()
    fandango = Fandango(
        grammar=grammar,
        constraints=constraints,
        population_size=100,
        logger_level=LoggerLevel.INFO,
    )

    # Output solutions
    solution_count = 0
    for solution in fandango.generate(mode=FuzzingMode.IO):

        # --- STEP 2: print a readable tree structure ---
        print("\n=== DERIVATION TREE (pretty view) ===")
        print(solution.to_tree())  # built-in method
        print("=== END TREE ===\n")
        # --- STEP 3: list all nonterminals used in this derivation ---
        used_nts = solution.get_non_terminal_symbols()
        print("\n=== NONTERMINALS USED IN THIS SOLUTION ===")
        for nt in used_nts:
            print(nt.name())
        print("=== END NONTERMINALS ===\n")
        # --- STEP 4: show rule expansions for each nonterminal ---
        print("\n=== RULE EXPANSIONS USED ===")

        def show_expansions(node):
            # Only process nonterminals
            if node.is_non_terminal:
                # Build the right-hand side (RHS)
                rhs_parts = []
                for child in node.children:
                    # If it's a terminal, show its spec; if nonterminal, show its name
                    if child.is_terminal:
                        rhs_parts.append(child.symbol.format_as_spec())
                    else:
                        rhs_parts.append(child.symbol.name())
                # Print this rule line
                print(f"{node.symbol.name()} ::= {' '.join(rhs_parts)}")
            # Recurse into children
            for child in node.children:
                show_expansions(child)

        show_expansions(solution)
        print("=== END RULE EXPANSIONS ===\n")
        import json, os

        def collect_rule_signatures(node, signatures=None):
            if signatures is None:
                signatures = []
            if node.is_non_terminal:
                rhs = []
                for child in node.children:
                    # Only include symbol names, not literal bytes/strings
                    rhs.append(child.symbol.name() if not child.is_terminal else child.symbol.format_as_spec())
                rule_sig = f"{node.symbol.name()}::={' '.join(rhs)}"
                signatures.append(rule_sig)
            for child in node.children:
                collect_rule_signatures(child, signatures)
            return signatures

        # collect signatures for this run
        rule_sigs = collect_rule_signatures(solution)

        # save to a file unique per run
        os.makedirs("derivation_logs", exist_ok=True)
        run_id = int(time.time() * 1000)
        path = f"derivation_logs/run_{run_id}.json"
        with open(path, "w") as f:
            json.dump(rule_sigs, f, indent=2)

        print(f"Saved {len(rule_sigs)} rule signatures to {path}")

        print(time.time() - time_start)
        if solution.contains_bytes():
            #print(solution.to_bytes())
            pass
        else:
            #print(solution.to_string())
            pass
        time_start = time.time()
        solution_count += 1
        if solution_count >= 10:
            break
        
        
        


if __name__ == "__main__":
    main()



if __name__ == "__main__":
    main()