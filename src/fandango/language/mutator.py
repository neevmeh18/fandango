import os
import re
import json
from typing import Dict, Optional, List, Tuple, Any

# === Fandango imports (new paths) ===
from fandango.language.parse import parse
from fandango.language.push_trial import run_and_mutate
from fandango.language.symbols import NonTerminal, Terminal
from fandango.language.grammar.node_visitors.node_visitor import NodeVisitor
from fandango.language.grammar.nodes.alternative import Alternative
from fandango.language.grammar.nodes.concatenation import Concatenation
from fandango.language.grammar.nodes.repetition import Repetition, Star, Plus, Option
from fandango.language.grammar.nodes.non_terminal import NonTerminalNode
from fandango.language.grammar.nodes.terminal import TerminalNode
from fandango.language.grammar.nodes.char_set import CharSet

# === your project imports (unchanged) ===
from fault_localiser import compute_fault_localisation
from mutations.plan import MutationPlan
from mutations.insertion import InsertionMutationFinder
from mutations.alternative_insertion import AltInsertionFinder
from mutations.reorder import ReorderMutationFinder
from mutations.repetition import RepetitionMutationFinder
from mutations.replacement import ReplacementMutationFinder
from mutations.removal import RemovalMutationFinder
# from mutations.altconcat import AltConcatMutationFinder   # kept commented as in your old file
from scoring import score_grammar
import uuid


class GrammarUnparserVisitor(NodeVisitor):
    """
    Unparses a grammar tree into a spec string, with explicit
    visit methods for each node type and safe depth handling.
    """

    def __init__(self, grammar, max_depth: int = 5):
        self.grammar = grammar
        self.max_depth = max_depth
        self.depth = 0

    def _safe_visit(self, node):
        """Visit with depth control to avoid infinite recursion."""
        self.depth += 1
        if self.depth > self.max_depth:
            result = "..."
        else:
            result = self.visit(node)
        self.depth -= 1
        return result

    # === Node handlers ===

    def visitAlternative(self, node: Alternative):
        return " | ".join(self._safe_visit(child) for child in node.alternatives)

    def visitConcatenation(self, node: Concatenation):
        return " ".join(self._safe_visit(child) for child in node.nodes)

    def visitRepetition(self, node: Repetition):
        # fall back to node’s own repr if needed
        return node.format_as_spec()

    def visitStar(self, node: Star):
        inner = self._safe_visit(node.node)
        if isinstance(node.node, (Alternative, Concatenation)):
            inner = f"({inner})"
        return f"{inner}*"

    def visitPlus(self, node: Plus):
        inner = self._safe_visit(node.node)
        if isinstance(node.node, (Alternative, Concatenation)):
            inner = f"({inner})"
        return f"{inner}+"

    def visitOption(self, node: Option):
        return f"{self._safe_visit(node.node)}?"

    def visitNonTerminalNode(self, node: NonTerminalNode):
        if node.sender or node.recipient:
            sender = node.sender or ""
            recipient = node.recipient or ""
            symbol = node.symbol.symbol[1:-1]
            return f"<{sender}:{symbol}>"
        return str(node.symbol.symbol)

    def visitTerminalNode(self, node: TerminalNode):
        return node.symbol.format_as_spec()

    def visitCharSet(self, node: CharSet):
        return f"r'{node.chars}'"



# === Grammar Loader and Extractor ===

def load_fan_grammar(path):
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()

    try:
        grammar, _ = parse(text, parties=["Client", "Server"])
        assert grammar is not None
        return grammar
    
    except Exception as e:
        print(f"❌ Parse failed: {e}")
    

def extract_literals_and_nonterminals(fan_file_path):
    non_terminals = set()
    with open(fan_file_path, 'r') as f:
        text = f.read()
        for line in text.splitlines():
            if "::=" in line:
                lhs = line.split("::=")[0].strip()
                non_terminals.add(NonTerminal(lhs))

    strings = re.findall(r'"([^"\\]*(?:\\.[^"\\]*)*)"', text)
    regexes = re.findall(r"r['\"]([^'\"]*)['\"]", text)
    literals = strings + [f"r'{r}'" for r in regexes]
    return list(non_terminals), literals

# === Ranking the score maps of the grammar candidates ===
def score_map_rank(score_map: Dict[str, Optional[int]]) -> tuple:
    def convert(v):
        return float('inf') if v is None else v

    # Sort keys to ensure consistent order
    return tuple(convert(score_map[str(i)]) for i in sorted(score_map.keys(), key=int))

# === Check against overfitting ===
def check_overfit(grammar, dir):
    if not os.path.exists(dir):
        print(f"❌ Directory does not exist: {dir}")
        return

    for filename in os.listdir(dir):
        if not filename.endswith(".fan"):
            continue

        fan_path = os.path.join(dir, filename)
        
        grammar = load_fan_grammar(fan_path)



    return 

# === Subsequent mutations ===
def mutate_candidate_grammars(
    candidates_dir: str,
    rule: NonTerminal,
    nonterminals: list,
    literals: list,
    test_inputs: list,
    unparser,
    grammar_settings,
    max_candidates: int = None,
    round_num: int = 2,
    best_score_yet: Dict[str, Optional[int]] = {},
):
    """
    Subsequent mutation rounds:
    - Only mutate the <mutation_...> rule created in round 1.
    - Mutations are applied directly (no hoisting).
    - Results are scored and saved under output/roundN/<mutation_rule>/candidates.
    """
    if round_num > 3:
        return

    round_dir = os.path.join("output", f"round{round_num-1}")
    metadata_path = os.path.join(round_dir, "candidates.json")

    if not os.path.exists(metadata_path):
        print(f"⚠️ No candidates.json found in {round_dir}.")
        return

    with open(metadata_path, "r") as f:
        metadata = json.load(f)

    candidate_files = sorted(metadata.keys())

    best_dir = os.path.join("output", "best_candidates", f"round{round_num-1}")
    no_perfect_found = (
        not os.path.exists(best_dir) or
        all(len(files) == 0 for _, _, files in os.walk(best_dir))
    )

    if no_perfect_found:
        print(f"⚠️ No perfect grammars found in round {round_num}. Using 2nd-best imperfect score.")

    # --- find best imperfect score so far ---
    best_score_yet = None

    # collect all imperfect scores
    imperfect_scores = []
    for entry in metadata.values():
        score_map = entry.get("score_map", {})
        if all(v is None for v in score_map.values()):
            continue
        rank = score_map_rank(score_map)
        imperfect_scores.append((rank, score_map))

    if not imperfect_scores:
        print("⚠️ Only perfect grammars found — no imperfect best to mutate.")
        best_scores = []
    else:
        # sort by rank, descending (higher = better)
        imperfect_scores.sort(key=lambda x: x[0], reverse=True)

        if no_perfect_found:  # <-- define based on previous round metadata
            if len(imperfect_scores) > 1:
                # take the 2nd best
                best_score_yet = imperfect_scores[1][1]
                print(f"🏆 Using 2nd best imperfect score (to avoid overfitting): {best_score_yet}")
            else:
                # only one imperfect score, fallback
                best_score_yet = imperfect_scores[0][1]
                print(f"🏆 Only one imperfect score available: {best_score_yet}")
        else:
            # normal case: take best
            best_score_yet = imperfect_scores[0][1]
            print(f"🏆 Best imperfect score so far: {best_score_yet} with rank {imperfect_scores[0][0]}")



    for filename in candidate_files:
        meta = metadata[filename]
        rule_name = meta.get("rule_name")

        # construct path using stored origin rule name (this was saved by score_grammar)
        fan_file = os.path.join(round_dir, rule_name, "candidates", filename)
        if not os.path.exists(fan_file):
            print(f"⚠️ Candidate file not found: {fan_file}")
            continue

        grammar = load_fan_grammar(fan_file)
        if grammar is None:
            continue

        previous_scores = meta.get("score_map", {})
        earlier_mutation = meta.get("name", "")

        if all(v is None for v in previous_scores.values()):
            continue

        # if we found at least one imperfect candidate, keep only top ones
        if best_score_yet is not None:
            if score_map_rank(previous_scores) < score_map_rank(best_score_yet):
                continue
            print(f"\n🔄 Re-mutating: {fan_file}")
            
            # Prefer the explicit mutation_rule from metadata (populated for round-1 hoisted cases)
            mutation_rule_name = meta.get("mutation_rule")

            if mutation_rule_name:
                # Use the exact NonTerminal name recorded in metadata
                target_rule = NonTerminal(mutation_rule_name)
                if target_rule not in grammar.rules:
                    # defensive fallback: still attempt to find it in grammar.rules
                    print(f"⚠️ mutation_rule {mutation_rule_name} not found inside parsed grammar; falling back to searching grammar.")
                    mutation_rule_name = None

            if not mutation_rule_name:
                # If metadata didn't contain mutation_rule, find any rule that starts with "<mutation"
                mutation_candidates = [nt for nt in grammar.rules if nt.name().startswith("<mutation")]
                if not mutation_candidates:
                    print("⚠️ No <mutation_...> rule found in candidate, skipping.")
                    continue
                target_rule = sorted(mutation_candidates, key=lambda nt: nt.name())[-1]


            nonterminals, _ = extract_literals_and_nonterminals(fan_file)


            def run_mutation(mutator, name):
                plan = MutationPlan([mutator])
                print("\n=== Trying mutation:", mutator.describe(), "===")

                plan.apply_all()

                print("Grammar AFTER apply_all:")
                #for nt, rule_node in grammar.rules.items():
                #   print(f"{nt.name()} ::= {unparser.visit(rule_node)}")
                try:
                    print("i am running subsequent mutations of type", mutator.describe())
                    score_grammar(
                        grammar,
                        test_inputs,
                        previous_scores,
                        name,                # just the filename
                        unparser,
                        mutator.describe(),
                        target_rule,         # this drives output/<round>/<mutation_rule>/
                        round_num,
                        nonterminals = nonterminals,
                        grammar_settings = grammar_settings
                    )
                except Exception as e:
                    print("❌ Subsequent mutation failed:", e)
                finally:
                    plan.revert_all()
        
            # === INSERTION (NonTerminal) ===
            for insert_symbol in nonterminals:
                finder = InsertionMutationFinder(grammar, target_rule, insert_symbol, grammar_settings, insertion_mode="concat")
                for idx, target in enumerate(finder.find_targets()):
                    mutator = target.create_mutator(grammar)
                    name = f"{earlier_mutation}+insertion_{insert_symbol.symbol}_{idx}.fan"
                    run_mutation(mutator, name)

            # === INSERTION (Literal) ===
            for literal in literals:
                finder = InsertionMutationFinder(grammar, target_rule, literal, grammar_settings, insertion_mode="concat")
                for idx, target in enumerate(finder.find_targets()):
                    target.is_literal = True
                    mutator = target.create_mutator(grammar)
                    name = f"{earlier_mutation}+insertion_{literal}_{idx}.fan"
                    run_mutation(mutator, name)

            # === ALTERNATIVE INSERTION ===
            for val in nonterminals + literals:
                val_symbol = val.name() if isinstance(val, NonTerminal) else val
                finder = AltInsertionFinder(grammar, target_rule, val, grammar_settings)
                for idx, target in enumerate(finder.find_targets()):
                    mutator = target.create_mutator(grammar)
                    name = f"{earlier_mutation}+alt_insertion_{val_symbol}_{idx}.fan"
                    run_mutation(mutator, name)

            
            # === REORDER ===
            reorder_finder = ReorderMutationFinder(grammar, target_rule, grammar_settings, reorder_mode="replace")
            for idx, target in enumerate(reorder_finder.find_targets()):
                mutator = target.create_mutator(grammar)
                name = f"{earlier_mutation}+reorder_{idx}.fan"
                run_mutation(mutator, name)

            # === REMOVAL ===
            rem_finder = RemovalMutationFinder(grammar, target_rule, grammar_settings, removal_mode="concat")
            for idx, target in enumerate(rem_finder.find_targets()):
                mutator = target.create_mutator(grammar)
                name = f"{earlier_mutation}+removal_{idx}.fan"
                run_mutation(mutator, name)


            # === REPETITION STAR ===
            rep_finder = RepetitionMutationFinder(grammar, target_rule, grammar_settings)
            for idx, target in enumerate(rep_finder.find_targets()):
                mutator = target.create_mutator(grammar)
                name = f"{earlier_mutation}+repetition_star_{idx}.fan"
                run_mutation(mutator, name)

            """
            # === REPETITION PLUS ===
            for idx, target in enumerate(rep_finder.find_targets()):
                mutator = target.create_mutator(grammar, use_plus=True)
                name = f"{earlier_mutation}+repetition_plus_{idx}.fan"
                run_mutation(mutator, name)
            """
            # === REPLACEMENT ===
            replacements = nonterminals + literals
            rep_finder = ReplacementMutationFinder(grammar, target_rule, replacements, grammar_settings, replacement_mode="replace")
            for idx, target in enumerate(rep_finder.find_targets()):
                for rj, repl in enumerate(replacements):
                    val_symbol = repl.name() if isinstance(repl, NonTerminal) else repl
                    mutator = target.create_mutator(grammar, repl)
                    name = f"{earlier_mutation}+replacement_{val_symbol}_{idx}.fan"
                    run_mutation(mutator, name)


    print("Done with", round_num)

    # --- recurse to next round ---
    return mutate_candidate_grammars(
        candidates_dir=candidates_dir,
        rule=rule,
        nonterminals=nonterminals,
        literals=literals,
        test_inputs=test_inputs,
        unparser=unparser,
        grammar_settings=grammar_settings,
        max_candidates=max_candidates,
        round_num=round_num + 1,
        best_score_yet=best_score_yet,
    )


def _hoist_last_alt_as_new_rule(grammar, target_rule: NonTerminal, grammar_settings) -> Optional[NonTerminal]:
    """
    Move the *last* alternative of target_rule into a fresh nonterminal and
    replace it with a NonTerminalNode to that rule. Returns the created NT (or None).
    """
    rule_node = grammar.rules[target_rule]
    if not isinstance(rule_node, Alternative) or not rule_node.alternatives:
        return None

    # Take the last alternative (assumed to be the one just added by the mutator)
    last_alt = rule_node.alternatives[-1]
    new_nt = NonTerminal(f"<mutation_{target_rule.symbol[1:-1]}>")

    # Define the new rule and replace the alt with a NonTerminalNode
    grammar.rules[new_nt] = last_alt
    rule_node.alternatives[-1] = NonTerminalNode(new_nt, grammar_settings)
    return new_nt

# === Actual mutation for first round ===
def apply_mutation(grammar, rule, mutator, test_inputs, previous_scores, label, unparser, symbol, grammar_settings, nonterminals):
    """
    Wrapper for round-1 mutations:
    - apply mutation
    - hoist the newly-added alternative to a fresh <...__mutation_k> rule
    - score
    - revert mutation and clean up the fresh rule
    """

    plan = MutationPlan([mutator])

    # Save the original alternatives for full revert
    rule_before = grammar.rules[rule]
    if isinstance(rule_before, Alternative):
        original_alternatives = list(rule_before.alternatives)
    else:
        original_alternatives = None

    plan.apply_all()
    created_nt = None

    try:
        rule_after = grammar.rules[rule]
        if isinstance(rule_after, Alternative):
            after_count = len(rule_after.alternatives)
            before_count = len(original_alternatives) if original_alternatives is not None else 1

            # Only hoist if a new alternative was indeed added by this mutator
            if after_count == before_count + 1:
                created_nt = _hoist_last_alt_as_new_rule(grammar, rule, grammar_settings)

        score_grammar(grammar, test_inputs, previous_scores, label, unparser, mutator.describe(), symbol, round_num=1, mutation_rule=(created_nt.name() if created_nt is not None else None), nonterminals=nonterminals, grammar_settings=grammar_settings)
        
    except Exception as e:
        print("Mutation not possible !! ", e)

    finally:
        if original_alternatives is not None and isinstance(grammar.rules[rule], Alternative):
            # case A: restore exact original alts
            grammar.rules[rule].alternatives = original_alternatives
        else:
            # case B: rule was not an Alternative originally
            grammar.rules[rule] = rule_before

        if created_nt is not None and created_nt in grammar.rules:
            del grammar.rules[created_nt]



# === First round mutations controller with all different types ===
def first_round_mutations(grammar, rule, nonterminals, literals, test_inputs, previous_scores, unparser, grammar_settings):
    print(f"\n🔍 Running mutations for rule: {rule.name()}")
    # === REPLACEMENT
    replacements = nonterminals + literals

    rep_finder = ReplacementMutationFinder(grammar, rule, replacements, grammar_settings)
    for idx, target in enumerate(rep_finder.find_targets()):
        for rj, repl in enumerate(replacements):
            val_symbol = repl.name() if isinstance(repl, NonTerminal) else repl
            mutator = target.create_mutator(grammar, repl)
            output_dir = os.path.join(f"replacement_{val_symbol}_{idx}.fan")
            apply_mutation(
                grammar, rule, mutator, test_inputs, previous_scores, output_dir, unparser, rule, grammar_settings, nonterminals
            )
    # === INSERTION (NonTerminal)
    for insert_symbol in nonterminals:
        finder = InsertionMutationFinder(grammar, rule, insert_symbol, grammar_settings)
        for idx, target in enumerate(finder.find_targets()):
            mutator = target.create_mutator(grammar)
            output_dir = os.path.join(f"insertion_{insert_symbol.symbol}_{idx}.fan")
            apply_mutation(
                grammar, rule, mutator, test_inputs, previous_scores, output_dir, unparser, rule, grammar_settings, nonterminals
            )


    # === INSERTION (Literal)
    for literal in literals:
        finder = InsertionMutationFinder(grammar, rule, literal, grammar_settings)
        for idx, target in enumerate(finder.find_targets()):
            target.is_literal = True
            mutator = target.create_mutator(grammar)
            output_dir = os.path.join(f"insertion_{literal}_{idx}.fan")
            apply_mutation(
                grammar, rule, mutator, test_inputs, previous_scores, output_dir, unparser, rule, grammar_settings, nonterminals
            )

    """
    #=== ALTCONCAT
    alt_concat_finder = AltConcatMutationFinder(grammar, rule)
    for idx, target in enumerate(alt_concat_finder.find_targets()):
        mutator = target.create_mutator(grammar)
        plan = MutationPlan([mutator])
        plan.apply_all()
        score_grammar(grammar, test_inputs, previous_scores, f"alt_concat_{rule.symbol}_{idx}", unparser, mutator.describe())
        plan.revert_all()

    """
    # === ALTERNATIVE INSERTION
    for val in nonterminals + literals:
        val_symbol = val.name() if isinstance(val, NonTerminal) else val
        finder = AltInsertionFinder(grammar, rule, val, grammar_settings)
        for idx, target in enumerate(finder.find_targets()):
            mutator = target.create_mutator(grammar)
            output_dir = os.path.join(f"alt_insertion_{val_symbol}_{idx}.fan")
            apply_mutation(
                grammar, rule, mutator, test_inputs, previous_scores, output_dir, unparser, rule, grammar_settings, nonterminals
            )

    

    # === REORDER
    reorder_finder = ReorderMutationFinder(grammar, rule, grammar_settings)
    for idx, target in enumerate(reorder_finder.find_targets()):
        mutator = target.create_mutator(grammar)
        output_dir = os.path.join(f"reorder_{idx}.fan")
        apply_mutation(
                grammar, rule, mutator, test_inputs, previous_scores, output_dir, unparser, rule, grammar_settings, nonterminals
            )

    # === REMOVAL ===

    rem_finder = RemovalMutationFinder(grammar, rule, grammar_settings, removal_mode="alt")
    for idx, target in enumerate(rem_finder.find_targets()):
        mutator = target.create_mutator(grammar)
        output_dir = os.path.join(f"removal_{idx}.fan")
        apply_mutation(
            grammar, rule, mutator, test_inputs, previous_scores, output_dir,
            unparser, rule, grammar_settings, nonterminals
        )



    """
    # === REPETITION PLUS
    rep_finder = RepetitionMutationFinder(grammar, rule, grammar_settings)
    for idx, target in enumerate(rep_finder.find_targets()):
        mutator = target.create_mutator(grammar, use_plus=True)
        output_dir = os.path.join(f"repetition_plus_{idx}.fan")
        apply_mutation(
                grammar, rule, mutator, test_inputs, previous_scores, output_dir, unparser, rule, grammar_settings
            )

    # === REPETITION STAR
    rep_finder = RepetitionMutationFinder(grammar, rule, grammar_settings)
    for idx, target in enumerate(rep_finder.find_targets()):
        mutator = target.create_mutator(grammar)
        output_dir = os.path.join(f"repetition_star_{idx}.fan")
        apply_mutation(
                grammar, rule, mutator, test_inputs, previous_scores, output_dir, unparser, rule, grammar_settings, nonterminals
            )

    """
    

    
# === Main Driver ===

def main():
    fan_file = "../../../evaluation/neev_eval/faulty_grammars/grammar_fault_4_remove_nonterminal.fan"
    try:
        grammar = load_fan_grammar(fan_file)
    except Exception as e:
        print(f"Cannot load grammar: {e}")
        return
    
    unparser = GrammarUnparserVisitor(grammar)
    grammar_settings = getattr(grammar, "grammar_settings", None)
    nonterminals, literals = extract_literals_and_nonterminals(fan_file)

    test_inputs = [

# 1. USER ok (+OK\r\n), PASS ok (+OK <text>), LIST multi-line (2 entries), QUIT ok (+OK <text>)
"+OK POP3 server ready\r\nUSER debug@localdomain.test\r\n+OK\r\nPASS NEWpass123\r\n+OK Logged in\r\nLIST\r\n+OK Scan listing follows\r\n1 120\r\n2 456\r\n.\r\nQUIT\r\n+OK Bye\r\n",

# 2. USER ok, PASS fail (-ERR ...), LIST rejected, QUIT rejected
"+OK Hello there\r\nUSER debug@localdomain.test\r\n+OK\r\nPASS NEWpass123\r\n-ERR Invalid password\r\nLIST\r\n-ERR Not logged in\r\nQUIT\r\n-ERR Session not started\r\n",

# 3. USER rejected (-ERR ...), PASS ok (+OK <text>), LIST single-line response, QUIT ok
"+OK POP3 server ready\r\nUSER debug@localdomain.test\r\n-ERR Bad user\r\nPASS NEWpass123\r\n+OK Proceed\r\nLIST\r\n+OK 2 messages\r\nQUIT\r\n+OK End\r\n",

# 4. USER ok, PASS ok (+OK <text>), LIST with +OK alone (positive_response_alone), QUIT ok
"+OK POP3 server ready\r\nUSER debug@localdomain.test\r\n+OK\r\nPASS NEWpass123\r\n+OK text\r\nLIST\r\n+OK\r\nQUIT\r\n+OK Completed\r\n",

# 5. USER ok, PASS error (-ERR ...), LIST error, QUIT error
"+OK POP3 server ready\r\nUSER debug@localdomain.test\r\n+OK\r\nPASS NEWpass123\r\n-ERR Wrong pass\r\nLIST\r\n-ERR Not allowed\r\nQUIT\r\n-ERR Quit denied\r\n",

# 6. USER ok, PASS ok, LIST with message number success (LIST 5), QUIT ok
"+OK POP3 server ready\r\nUSER debug@localdomain.test\r\n+OK\r\nPASS NEWpass123\r\n+OK Logged in\r\nLIST 5\r\n+OK Message 5 is 320 octets\r\nQUIT\r\n+OK Done\r\n",

# 7. USER ok, PASS ok, LIST with message number negative response
"+OK POP3 server ready\r\nUSER debug@localdomain.test\r\n+OK\r\nPASS NEWpass123\r\n+OK text\r\nLIST 3\r\n-ERR No such message\r\nQUIT\r\n+OK Exit\r\n",

# 8. USER ok, PASS ok, LIST multi-line with only one entry, QUIT ok
"+OK POP3 server ready\r\nUSER debug@localdomain.test\r\n+OK\r\nPASS NEWpass123\r\n+OK text\r\nLIST\r\n+OK Mailbox scan\r\n1 123\r\n.\r\nQUIT\r\n+OK Terminated\r\n",

# 9. USER error, PASS error, LIST multi-line empty (just terminator), QUIT error
"+OK POP3 server ready\r\nUSER debug@localdomain.test\r\n-ERR Unknown user\r\nPASS NEWpass123\r\n-ERR Blocked\r\nLIST\r\n+OK Mailbox is empty\r\n.\r\nQUIT\r\n-ERR Quit failed\r\n",

# 10. USER ok, PASS ok, LIST ok single-line, QUIT ok
"+OK POP3 server ready\r\nUSER debug@localdomain.test\r\n+OK\r\nPASS NEWpass123\r\n+OK All good\r\nLIST\r\n+OK 1 message\r\nQUIT\r\n+OK See you\r\n"

]

    # call fault localiser and get suspiciousness ranking with intital parsing scores
    sbfl_ranked_rules, initial_scores, error_flag = compute_fault_localisation(
        "../../../evaluation/neev_eval/faulty_grammars/grammar_fault_4_remove_nonterminal.fan",
        port=25110,
        test_inputs=test_inputs,
    )
    print("initial_scores:", initial_scores)


    #iterate on every rule in the ranking and try the first round of mutations - this logic should be changed 
    #i want to try first mutation on every rule with a tied rank and then mutate the rule that was scored highest
    if error_flag:
        if not sbfl_ranked_rules == []:
            for rule in sbfl_ranked_rules:

                #if rule != NonTerminal("<quit_exchange>"):
                #    continue
                
                first_round_mutations(
                    grammar, rule, nonterminals, literals, test_inputs, initial_scores, unparser, grammar_settings
                )
                print("First round mutations are complete")
                mutate_candidate_grammars(
                    candidates_dir="output",
                    rule=rule,
                    nonterminals=nonterminals,
                    literals=literals,
                    test_inputs=test_inputs,
                    unparser=unparser,
                    grammar_settings=grammar_settings,
                    max_candidates=50,
                    round_num=2
                )
        
        print("FINAL PUSH PHASE.....")
        p = run_and_mutate("../../../evaluation/neev_eval/faulty_grammars/grammar_fault_4_remove_nonterminal.fan", 10, 10)

    print("PERFECT GRAMMAR")




if __name__ == "__main__":
    main()
