import random
from pathlib import Path

# --- Parameters ---
NUM_FAULTS_PER_TYPE = 5
MUTATION_TYPES = ["remove_nonterminal", "replace_nonterminal", "add_symbol", "reorder_symbols"]

# --- Helpers ---
def parse_rules(grammar_text):
    rules = {}
    for line in grammar_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "::=" in line:
            lhs, rhs = line.split("::=", 1)
            lhs = lhs.strip(" <>")
            alts = [alt.strip().split() for alt in rhs.split("|")]
            rules[lhs] = alts
    return rules

def serialize_rules(rules):
    lines = []
    for lhs, alts in rules.items():
        rhs_str = " | ".join([" ".join(alt) for alt in alts])
        lines.append(f"<{lhs}> ::= {rhs_str}")
    return "\n".join(lines)

def get_nonterminals(rules):
    nts = set()
    for lhs, alts in rules.items():
        nts.add(f"<{lhs}>")
        for alt in alts:
            for sym in alt:
                if sym.startswith("<") and sym.endswith(">"):
                    nts.add(sym)
    return list(nts)

def get_symbols(rules):
    syms = set()
    for lhs, alts in rules.items():
        syms.add(f"<{lhs}>")
        for alt in alts:
            for sym in alt:
                syms.add(sym)
    return list(syms)

# --- Mutations ---
def mutate_remove_nonterminal(rules):
    rules_copy = {lhs: [alt[:] for alt in alts] for lhs, alts in rules.items()}
    candidates = [(lhs, i, j)
                  for lhs, alts in rules_copy.items()
                  for i, alt in enumerate(alts)
                  for j, sym in enumerate(alt)
                  if sym.startswith("<") and sym.endswith(">") and len(alt) > 1]
    if not candidates:
        return None, None
    lhs, i, j = random.choice(candidates)
    removed = rules_copy[lhs][i][j]
    del rules_copy[lhs][i][j]
    return rules_copy, f"Removed {removed} from rule <{lhs}>"

def mutate_replace_nonterminal(rules):
    rules_copy = {lhs: [alt[:] for alt in alts] for lhs, alts in rules.items()}
    nts = get_nonterminals(rules_copy)
    candidates = [(lhs, i, j)
                  for lhs, alts in rules_copy.items()
                  for i, alt in enumerate(alts)
                  for j, sym in enumerate(alt)
                  if sym.startswith("<") and sym.endswith(">")]
    if not candidates:
        return None, None
    lhs, i, j = random.choice(candidates)
    old = rules_copy[lhs][i][j]
    new = random.choice([nt for nt in nts if nt != old])
    rules_copy[lhs][i][j] = new
    return rules_copy, f"Replaced {old} with {new} in rule <{lhs}>"

def mutate_add_symbol(rules):
    rules_copy = {lhs: [alt[:] for alt in alts] for lhs, alts in rules.items()}
    syms = get_symbols(rules_copy)
    candidates = [(lhs, i) for lhs, alts in rules_copy.items() for i, _ in enumerate(alts)]
    if not candidates:
        return None, None
    lhs, i = random.choice(candidates)
    alt = rules_copy[lhs][i]
    new_sym = random.choice(syms)
    pos = random.randint(0, len(alt))
    alt.insert(pos, new_sym)
    return rules_copy, f"Inserted {new_sym} into rule <{lhs}>"

def mutate_reorder_symbols(rules):
    rules_copy = {lhs: [alt[:] for alt in alts] for lhs, alts in rules.items()}
    candidates = [(lhs, i) for lhs, alts in rules_copy.items() for i, alt in enumerate(alts) if len(alt) > 1]
    if not candidates:
        return None, None
    lhs, i = random.choice(candidates)
    alt = rules_copy[lhs][i]
    random.shuffle(alt)
    return rules_copy, f"Reordered symbols in rule <{lhs}>"

# --- Main function ---
def create_faulty_grammars(grammar_text, out_dir):
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    rules = parse_rules(grammar_text)

    log_lines = []
    mutation_funcs = {
        "remove_nonterminal": mutate_remove_nonterminal,
        "replace_nonterminal": mutate_replace_nonterminal,
        "add_symbol": mutate_add_symbol,
        "reorder_symbols": mutate_reorder_symbols
    }

    counter = 0
    for mut_type in MUTATION_TYPES:
        func = mutation_funcs[mut_type]
        for _ in range(NUM_FAULTS_PER_TYPE):
            mutated, desc = func(rules)
            if mutated is None:
                continue
            counter += 1
            mutated_text = serialize_rules(mutated)
            fname = Path(out_dir) / f"grammar_fault_{counter}_{mut_type}.fan"
            with open(fname, "w") as f:
                f.write(mutated_text)
            log_lines.append(f"{fname.name}: {desc}")

    with open(Path(out_dir) / "mutation_log.txt", "w") as f:
        f.write("\n".join(log_lines) + "\n")

    return log_lines

# Example usage
if __name__ == "__main__":
    input_file = "list_grammar/list_grammar_correct.fan"
    with open(input_file) as f:
        grammar_text = f.read()
    logs = create_faulty_grammars(grammar_text, "faulty_grammars")
    print("\n".join(logs))
# This script generates faulty grammars by applying various mutations to a correct grammar. It saves the mutated grammars and logs the mutations made.