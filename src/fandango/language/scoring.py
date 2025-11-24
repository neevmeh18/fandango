import os
import json
from multiprocessing import Process, Queue
from typing import List, Dict, Optional

from server_permissiveness_check import is_too_permissive
import sys
from server_validation import validate_grammar_with_server, decision_logic
from fandango.language.parse import NonTerminal
from mutations.alternative_removal import AltRemovalFinder
from mutations.plan import MutationPlan


PARSE_TIMEOUT_SECS = 2

def score_map_rank(score_map: Dict[str, Optional[int]]) -> tuple:
    def convert(v):
        return float('inf') if v is None else v

    return tuple(convert(score_map[str(i)]) for i in sorted(score_map.keys(), key=int))

def update_candidate_metadata(entry, round_dir):
    path = os.path.join(round_dir, "candidates.json")
    if os.path.exists(path):
        with open(path, "r") as f:
            try:
                data = json.load(f)
                if not isinstance(data, dict):
                    data = {}
            except json.JSONDecodeError:
                data = {}
    else:
        data = {}

    data[entry["name"]] = entry

    with open(path, "w") as f:
        json.dump(data, f, indent=2)

def parse_with_timeout(grammar, test_input: str, timeout_secs=2) -> Dict[str, Optional[int]]:
    def worker(q):
        try:
            tree = grammar.parse(test_input)
            success = tree is not None
            max_char = grammar._parser._iter_parser.max_position() if not success else None
            q.put({"success": success, "max_char": max_char})
        except Exception as e:
            print(e)
            q.put({"success": False, "max_char": 0})

    q = Queue()
    p = Process(target=worker, args=(q,))
    p.start()
    p.join(timeout_secs)
    if p.is_alive():
        p.terminate()
        p.join()
    return q.get() if not q.empty() else {"success": False, "max_char": 0}


def score_grammar(
    grammar,
    test_inputs: List[str],
    previous_scores: Dict[str, Optional[int]],
    name: str, #name of the file
    unparser,
    mutation: str,
    rule_name,
    round_num: int = 1,
    best_score_yet = {},
    mutation_rule: Optional[str] = None,
    nonterminals = set(),
    grammar_settings = None,
) -> int:
    
    cand_dir = os.path.join("output", f"round{round_num}", rule_name.name(), "candidates")
    os.makedirs(cand_dir, exist_ok=True)
    full_name = os.path.join(cand_dir, name)
    

    grammar._build_parser()
    score_map: Dict[str, Optional[int]] = {}
    improved_inputs = {}
    total_score = 0

    for idx, test in enumerate(test_inputs):
        result = parse_with_timeout(grammar, test)
        if result["success"]:
            score_map[str(idx)] = None
            if str(idx) in previous_scores and previous_scores[str(idx)] is not None:
                improved_inputs[idx] = None
        else:
            pos = result["max_char"]
            score_map[str(idx)] = pos
            prev = previous_scores.get(str(idx), 0)
            if prev is not None and pos > prev:
                improved_inputs[idx] = pos
                total_score += pos



    if not improved_inputs:
       #print("No improvements, skipping save.")
       return 0
    
    if not isinstance(best_score_yet, dict):
        best_score_yet = {}

    if best_score_yet != {} and score_map_rank(score_map) < score_map_rank(best_score_yet):
        #print("Worse than best score yet, skipping save.")
        return 0
    
    print(score_map, best_score_yet)
    if nonterminals:
        nonterminals = {nt.format_as_spec() for nt in nonterminals}

    with open(full_name, "w", encoding="utf-8") as f:
        for nt, rule in grammar.rules.items():
            name_nt = nt.name()
            if name_nt in nonterminals or "mutation" in name_nt:
                f.write(f"{name_nt} ::= {unparser.visit(rule)}\n")

        # ✅ Always append your Python code at end
        f.write("\n# ---- Auto-Generated Python Footer ----\n")
        f.write("fandango_is_client = True\n\n")
        f.write("class Client(ConnectParty):\n")
        f.write("    def __init__(self):\n")
        f.write("        super().__init__(\n")
        f.write("            ownership=Ownership.FANDANGO_PARTY if fandango_is_client else Ownership.EXTERNAL_PARTY,\n")
        f.write("            endpoint_type=EndpointType.CONNECT,\n")
        f.write("            uri=\"tcp://localhost:25110\"\n")
        f.write("        )\n")
        f.write("        self.start()\n\n")
        f.write("class Server(ConnectParty):\n")
        f.write("    def __init__(self):\n")
        f.write("        super().__init__(\n")
        f.write("            ownership=Ownership.EXTERNAL_PARTY if fandango_is_client else Ownership.FANDANGO_PARTY,\n")
        f.write("            endpoint_type=EndpointType.OPEN,\n")
        f.write("            uri=\"tcp://localhost:25110\"\n")
        f.write("        )\n")
        f.write("        self.start()\n")


    round_dir = os.path.join("output", f"round{round_num}")
    update_candidate_metadata({
        "name": name,
        "mutation": mutation,
        "score": total_score,
        "score_map": score_map,
        "improved_inputs": list(improved_inputs.keys()),
        "rule_name": rule_name.name(),
        "mutation_rule": mutation_rule,   # can be None for subsequent rounds; populated in round 1 when hoisted
    }, round_dir)

    print(f"✅ Saved {name} with score {total_score} (improved: {list(improved_inputs)})")


    best_dir = os.path.join("output", "best_candidates", f"round{round_num}", f"{rule_name.name()}")
    os.makedirs(best_dir, exist_ok=True)
   

    # 🔁 Save to best_candidates if perfect
    if all(v is None for v in score_map.values()):

        try:
            metrics = validate_grammar_with_server(full_name, rule_name.name(), port=25110, repetitions=3)
        except Exception as e:
            metrics = {}
            print("fonud this problem", e)
        decision = decision_logic(metrics)
        if decision == "reject":
            print("❌ Candidate rejected: too permissive on client side.")
            return 0  
        
        elif decision == "alt_removal":
            print("⚠️ Candidate requires alternative removal mutation.")
            alternative_removal(grammar,rule_name,full_name,test_inputs,unparser,grammar_settings,nonterminals,round_num)
            return 0
        
        elif decision == "inconclusive":
            print("❓ Candidate inconclusive: mutation never triggered.")
            return 0


        if is_too_permissive(grammar, parse_with_timeout):
            print("❌ Candidate rejected: too permissive on server side.")
            return 0

        best_dir = os.path.join("output", "best_candidates", f"round{round_num}", rule_name.name())
        os.makedirs(cand_dir, exist_ok=True)
        best_path = os.path.join(best_dir, name)

        with open(best_path, "w", encoding="utf-8") as f:
            for nt, rule in grammar.rules.items():
                name_nt = nt.name()
                if name_nt in nonterminals or "mutation" in name_nt:
                    f.write(f"{name_nt} ::= {unparser.visit(rule)}\n")

                # ✅ Always append your Python code at end
            f.write("\n# ---- Auto-Generated Python Footer ----\n")
            f.write("fandango_is_client = True\n\n")
            f.write("class Client(ConnectParty):\n")
            f.write("    def __init__(self):\n")
            f.write("        super().__init__(\n")
            f.write("            ownership=Ownership.FANDANGO_PARTY if fandango_is_client else Ownership.EXTERNAL_PARTY,\n")
            f.write("            endpoint_type=EndpointType.CONNECT,\n")
            f.write("            uri=\"tcp://localhost:25110\"\n")
            f.write("        )\n")
            f.write("        self.start()\n\n")
            f.write("class Server(ConnectParty):\n")
            f.write("    def __init__(self):\n")
            f.write("        super().__init__(\n")
            f.write("            ownership=Ownership.EXTERNAL_PARTY if fandango_is_client else Ownership.FANDANGO_PARTY,\n")
            f.write("            endpoint_type=EndpointType.OPEN,\n")
            f.write("            uri=\"tcp://localhost:25110\"\n")
            f.write("        )\n")
            f.write("        self.start()\n")

        #sys.exit(0)



def alternative_removal(
    grammar,
    rule_name,
    full_name,
    test_inputs,
    unparser,
    grammar_settings,
    nonterminals,
    round_num=2,
):
    """
    Push-phase: try removing alternatives from rule_name.
    For each removal combination:
      - apply mutation
      - re-check all test inputs (must still be perfect)
      - if still perfect -> run server validation
      - if validation accepts -> save grammar to best_candidates
      - revert grammar afterwards
    Returns True if a fixed grammar was found & saved, else False.
    """
    base_name = full_name[:-4] if full_name.endswith(".fan") else full_name
    base_dir = os.path.dirname(full_name)
    finder = AltRemovalFinder(grammar, rule_name, grammar_settings)
    targets = finder.find_targets()

    trials = 0

    for idx, target in enumerate(targets):
        mutator = target.create_mutator(grammar)
        plan = MutationPlan([mutator])

        try:
            print(f"\n[AltRemoval] Trial #{trials}: {target.describe()}")
            plan.apply_all()

            # === Check if grammar is still perfect ===
            grammar._build_parser()
            all_passed = True
            for i, test in enumerate(test_inputs):
                result = parse_with_timeout(grammar, test)
                if not result["success"]:
                    all_passed = False
                    break

            if not all_passed:
                print("[AltRemoval] ❌ Removal broke a test case, rejecting.")
                plan.revert_all()
                continue

            new_name = f"{os.path.basename(base_name)}+{target.describe()}.fan"
            new_full_name = os.path.join(base_dir, new_name)

            with open(new_full_name, "w", encoding="utf-8") as f:
                for nt, rule in grammar.rules.items():
                    name_nt = nt.name()
                    if name_nt in nonterminals or "mutation" in name_nt:
                        f.write(f"{name_nt} ::= {unparser.visit(rule)}\n")

            print(f"[AltRemoval] Saved candidate {new_full_name}")


            metrics = validate_grammar_with_server(
                new_full_name,
                rule_name.name(),
                port=25110,
                repetitions=3,
            )
            decision = decision_logic(metrics, "alt_removal")

            if decision == "accept":
                # Copy candidate into best_candidates
                best_dir = os.path.join("output", "best_candidates", f"round{round_num}", rule_name.name())
                os.makedirs(best_dir, exist_ok=True)
                best_path = os.path.join(best_dir, new_name)

                with open(best_path, "w", encoding="utf-8") as f:
                    for nt, rule in grammar.rules.items():
                        name_nt = nt.name()
                        if name_nt in nonterminals or "mutation" in name_nt:
                            f.write(f"{name_nt} ::= {unparser.visit(rule)}\n")

                     # ✅ Always append your Python code at end
                    f.write("\n# ---- Auto-Generated Python Footer ----\n")
                    f.write("fandango_is_client = True\n\n")
                    f.write("class Client(ConnectParty):\n")
                    f.write("    def __init__(self):\n")
                    f.write("        super().__init__(\n")
                    f.write("            ownership=Ownership.FANDANGO_PARTY if fandango_is_client else Ownership.EXTERNAL_PARTY,\n")
                    f.write("            endpoint_type=EndpointType.CONNECT,\n")
                    f.write("            uri=\"tcp://localhost:25110\"\n")
                    f.write("        )\n")
                    f.write("        self.start()\n\n")
                    f.write("class Server(ConnectParty):\n")
                    f.write("    def __init__(self):\n")
                    f.write("        super().__init__(\n")
                    f.write("            ownership=Ownership.EXTERNAL_PARTY if fandango_is_client else Ownership.FANDANGO_PARTY,\n")
                    f.write("            endpoint_type=EndpointType.OPEN,\n")
                    f.write("            uri=\"tcp://localhost:25110\"\n")
                    f.write("        )\n")
                    f.write("        self.start()\n")

                print(f"[AltRemoval] ✅ Grammar fixed and saved: {best_path}")
                plan.revert_all()
                return True  # stop after first fix

            else:
                print("[AltRemoval] ❌ Server validation failed, rejecting removal.")
                plan.revert_all()

        except Exception as e:
            print(f"[AltRemoval] ❌ Error in trial {idx}: {e}")
            try:
                plan.revert_all()
            except Exception:
                pass

    return False