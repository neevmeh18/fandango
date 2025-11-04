# File: push.py

import os
import re
import json
from typing import Dict, Optional
from fandango.language.parse import parse
from fandango.language.grammar import (
    NonTerminal, Terminal, NodeVisitor,
    NonTerminalNode, TerminalNode, CharSet,
    Alternative, Concatenation, Repetition, Star, Plus, Option
)
from mutations.plan import MutationPlan
from mutations.insertion import InsertionMutationFinder
from mutations.alternative_insertion import AltInsertionFinder
from mutations.reorder import ReorderMutationFinder
from mutations.repetition import RepetitionMutationFinder
from mutations.replacement import ReplacementMutationFinder
from mutations.altconcat import AltConcatMutationFinder
from scoring import score_grammar
import threading
from multiprocessing import Process, Queue
import multiprocessing

# 🔸 Local Definition of GrammarUnparserVisitor
class GrammarUnparserVisitor(NodeVisitor):
    def __init__(self, grammar, max_depth=5):
        self.grammar = grammar
        self.visited = set()
        self.max_depth = max_depth
        self.depth = 0

    def _safe_visit(self, node):
        self.depth += 1
        if self.depth > self.max_depth:
            result = "..."
        else:
            result = self.visit(node)
        self.depth -= 1
        return result

    def visitAlternative(self, node: Alternative):
        return " | ".join(self._safe_visit(child) for child in node.alternatives)

    def visitConcatenation(self, node: Concatenation):
        return " ".join(self._safe_visit(child) for child in node.nodes)

    def visitRepetition(self, node: Repetition):
        return f"{self._safe_visit(node.node)}{{{node.expr_data_min[0]},{node.expr_data_max[0]}}}"

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
        if node.role or node.recipient:
            role = node.role or ""
            recipient = node.recipient or ""
            symbol = str(node.symbol)[1:-1]
            return f"<{role}:{recipient}:{symbol}>"
        return str(node.symbol)

    def visitTerminalNode(self, node: TerminalNode):
        return str(node.symbol)

    def visitCharSet(self, node: CharSet):
        return f"r'{node.chars}'"


# === Grammar Loader and Extractor ===

def load_fan_grammar(path):
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    try:
        grammar, _ = parse(text,)
        assert grammar is not None
    except Exception as e:
        print(f"❌ Parse failed: {e}")
    return grammar

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
    max_candidates: int = None,
    round_num = 2, 
    best_score_yet = {}
):
    rule  = NonTerminal("<mutation>")
    if round_num > 3:
        return 
    
    symbol = rule.symbol
    round_dir = f"output/{rule.symbol}/round{round_num-1}"
    candidates_dir = os.path.join(round_dir, "candidates")
    metadata_path = os.path.join(round_dir, "candidates.json")

    if not os.path.exists(metadata_path):
        print(f"⚠️ No candidates.json found in {round_dir}.")
        return

    with open(metadata_path, "r") as f:
        metadata = json.load(f)

    candidate_files = sorted(metadata.keys())


    ##this code snippet finds the best score for each input (takes into account both max_character as well as success denoted by None)
    best_rank = (-1, float("-inf"))

    for entry in metadata.values():
        score_map = entry.get("score_map", {})
        rank = score_map_rank(score_map)

        if rank > best_rank:
            best_score_yet = score_map
            best_rank = rank

    for filename in candidate_files:
        meta = metadata[filename]
        fan_file = os.path.join(candidates_dir, f"{filename}.fan")

        print(f"\n🔄 Re-mutating: {fan_file}")

        # Load grammar
        grammar = load_fan_grammar(fan_file)  # Your parse function here
        previous_scores = meta.get("score_map", {})
        earlier_mutation = meta.get("mutation", "")
        # === Strategy: simple follow-up insertion ===
        if (
            grammar is not None and
            score_map_rank(previous_scores) >= score_map_rank(best_score_yet) and
            not all(v is None for v in previous_scores.values())
        ):
            print("This is the best", best_score_yet)
            for insert_symbol in nonterminals:
                #print("trying nonterminal insertions...")
                finder = InsertionMutationFinder(grammar, rule, insert_symbol)
                for idx, target in enumerate(finder.find_targets()):
                    mutator = target.create_mutator(grammar)
                    plan = MutationPlan([mutator])
                    plan.apply_all()
                    try:
                        mutation_id = mutator.describe().replace("<", "").replace(">", "")
                        score_grammar(grammar, test_inputs, previous_scores, f"{earlier_mutation}+{mutation_id}", unparser, mutator.describe(), symbol,round_num, best_score_yet=best_score_yet)
                    except Exception as e:
                        print("This is the exception", e)
                    plan.revert_all()
            
            for literal in literals:
                #("trying literal insertions...")
                finder = InsertionMutationFinder(grammar, rule, literal)
                for idx, target in enumerate(finder.find_targets()):
                    target.is_literal = True
                    mutator = target.create_mutator(grammar)
                    plan = MutationPlan([mutator])
                    plan.apply_all()
                    score_grammar(grammar, test_inputs, previous_scores, f"{earlier_mutation}+insertion_lit_{rule.symbol}_{idx}", unparser, mutator.describe(),symbol, round_num, best_score_yet=best_score_yet)
                    plan.revert_all()

            
            # === ALTERNATIVE INSERTION
            for val in nonterminals + literals:
                finder = AltInsertionFinder(grammar, rule, val)
                for idx, target in enumerate(finder.find_targets()):
                    mutator = target.create_mutator(grammar)
                    plan = MutationPlan([mutator])
                    plan.apply_all()
                    score_grammar(grammar, test_inputs, previous_scores, f"{earlier_mutation}+alt_insertion_{rule.symbol}_{idx}", unparser, mutator.describe(), symbol,round_num, best_score_yet)
                    plan.revert_all()

            # === REPETITION STAR
            rep_finder = RepetitionMutationFinder(grammar, rule)
            for idx, target in enumerate(rep_finder.find_targets()):
                mutator = target.create_mutator(grammar)
                plan = MutationPlan([mutator])
                plan.apply_all()
                score_grammar(grammar, test_inputs, previous_scores, f"{earlier_mutation}+repetition_star_{rule.symbol}_{idx}", unparser, mutator.describe(), symbol,round_num, best_score_yet)
                plan.revert_all()

            # === REPETITION PLUS
            rep_finder = RepetitionMutationFinder(grammar, rule)
            for idx, target in enumerate(rep_finder.find_targets()):
                mutator = target.create_mutator(grammar, use_plus=True)
                plan = MutationPlan([mutator])
                plan.apply_all()
                score_grammar(grammar, test_inputs, previous_scores, f"{earlier_mutation}+repetition_plus_{rule.symbol}_{idx}", unparser, mutator.describe(), symbol,round_num, best_score_yet)
                plan.revert_all()

            # === REORDERING
            reorder_finder = ReorderMutationFinder(grammar, rule)
            for idx, target in enumerate(reorder_finder.find_targets()):
                mutator = target.create_mutator(grammar)
                plan = MutationPlan([mutator])
                plan.apply_all()
                score_grammar(grammar, test_inputs, previous_scores, f"{earlier_mutation}+reorder_{rule.symbol}_{idx}", unparser, mutator.describe(),symbol,round_num, best_score_yet)
                plan.revert_all()


            

    return mutate_candidate_grammars(candidates_dir=candidates_dir, rule=rule, nonterminals=nonterminals, literals=literals, test_inputs=test_inputs, unparser=unparser, max_candidates=max_candidates, round_num=round_num + 1, best_score_yet=best_score_yet)    

# === Per-Rule Mutation Function ===

def _apply_score_first_round_with_hoist(grammar, rule, mutator, test_inputs, previous_scores, label, unparser, symbol):
    """
    Wrapper for round-1 mutations:
    - apply mutation
    - hoist the newly-added alternative to a fresh <...__mutation_k> rule
    - score
    - revert mutation and clean up the fresh rule
    """
    plan = MutationPlan([mutator])

    # Count alternatives before apply() so we can confirm a new one appeared
    rule_before = grammar.rules[rule]
    before_count = len(rule_before.alternatives) if isinstance(rule_before, Alternative) else 1

    plan.apply_all()
    created_nt = None
    try:
        rule_after = grammar.rules[rule]
        if isinstance(rule_after, Alternative):
            after_count = len(rule_after.alternatives)
            # Only hoist if a new alternative was indeed added by this mutator
            if after_count == before_count + 1:
                created_nt = _hoist_last_alt_as_new_rule(grammar, rule)

        score_grammar(grammar, test_inputs, previous_scores, label, unparser, mutator.describe(), symbol, round_num=1)
    finally:
        # revert the mutator (this will pop the NonTerminalNode alternative we added)
        plan.revert_all()
        # remove the temporary rule if we created one
        if created_nt is not None and created_nt in grammar.rules:
            del grammar.rules[created_nt]

def _hoist_last_alt_as_new_rule(grammar, target_rule: NonTerminal) -> Optional[NonTerminal]:
    """
    Move the *last* alternative of target_rule into a fresh nonterminal and
    replace it with a NonTerminalNode to that rule. Returns the created NT (or None).
    """
    rule_node = grammar.rules[target_rule]
    if not isinstance(rule_node, Alternative) or not rule_node.alternatives:
        return None

    # Take the last alternative (assumed to be the one just added by the mutator)
    last_alt = rule_node.alternatives[-1]
    new_nt = NonTerminal(f"<mutation>")

    # Define the new rule and replace the alt with a NonTerminalNode
    grammar.rules[new_nt] = last_alt
    rule_node.alternatives[-1] = NonTerminalNode(new_nt)
    return new_nt

def run_mutations_on_rule(grammar, rule: NonTerminal, nonterminals, literals, test_inputs, previous_scores, output_dir, unparser):
    print(f"\n🔍 Running mutations for rule: {rule}")
    symbol = rule.symbol
    print(previous_scores)
    # === INSERTION (NonTerminal)
    for insert_symbol in nonterminals:
        finder = InsertionMutationFinder(grammar, rule, insert_symbol)
        for idx, target in enumerate(finder.find_targets()):
            mutator = target.create_mutator(grammar)
            _apply_score_first_round_with_hoist(
                grammar, rule, mutator, test_inputs, previous_scores,
                f"insertion_{rule.symbol}_{idx}", unparser, symbol
            )


    # === INSERTION (Literal)
    for literal in literals:
        finder = InsertionMutationFinder(grammar, rule, literal)
        for idx, target in enumerate(finder.find_targets()):
            target.is_literal = True
            mutator = target.create_mutator(grammar)
            _apply_score_first_round_with_hoist(
                grammar, rule, mutator, test_inputs, previous_scores,
                f"insertion_{rule.symbol}_{idx}", unparser, symbol
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
        finder = AltInsertionFinder(grammar, rule, val)
        for idx, target in enumerate(finder.find_targets()):
            mutator = target.create_mutator(grammar)
            _apply_score_first_round_with_hoist(
                grammar, rule, mutator, test_inputs, previous_scores,
                f"insertion_{rule.symbol}_{idx}", unparser, symbol
            )


    # === REORDERING
    reorder_finder = ReorderMutationFinder(grammar, rule)
    for idx, target in enumerate(reorder_finder.find_targets()):
        mutator = target.create_mutator(grammar)
        _apply_score_first_round_with_hoist(
            grammar, rule, mutator, test_inputs, previous_scores,
            f"insertion_{rule.symbol}_{idx}", unparser, symbol
        )


    # === REPETITION STAR
    rep_finder = RepetitionMutationFinder(grammar, rule)
    for idx, target in enumerate(rep_finder.find_targets()):
        mutator = target.create_mutator(grammar)
        _apply_score_first_round_with_hoist(
            grammar, rule, mutator, test_inputs, previous_scores,
            f"insertion_{rule.symbol}_{idx}", unparser, symbol
        )


    # === REPETITION PLUS
    rep_finder = RepetitionMutationFinder(grammar, rule)
    for idx, target in enumerate(rep_finder.find_targets()):
        mutator = target.create_mutator(grammar, use_plus=True)
        _apply_score_first_round_with_hoist(
            grammar, rule, mutator, test_inputs, previous_scores,
            f"insertion_{rule.symbol}_{idx}", unparser, symbol
        )


    # === REPLACEMENT
    replacements = nonterminals + literals
    rep_finder = ReplacementMutationFinder(grammar, rule, replacements)
    for idx, target in enumerate(rep_finder.find_targets()):
        for rj, repl in enumerate(replacements):
            try:
                mutator = target.create_mutator(grammar, repl)
                _apply_score_first_round_with_hoist(
                    grammar, rule, mutator, test_inputs, previous_scores,
                    f"insertion_{rule.symbol}_{idx}", unparser, symbol
                )

            except Exception as e:
                print(f"⚠️ Skipped replacement: {repl} due to {e}")
                continue


# === Main Driver ===

def main():
    fan_file = "list_grammar.fan"
    grammar = load_fan_grammar(fan_file)
    nonterminals, literals = extract_literals_and_nonterminals(fan_file)
    test_inputs = [

# 1. Successful login, LIST with multi-line response, QUIT with +OK <text>
"+OK POP3 server ready\r\nUSER debug@localdomain.test\r\n+OK\r\nPASS NEWpass123\r\n+OK Logged in\r\nLIST\r\n+OK Scan listing follows\r\n1 120\r\n2 456\r\n.\r\nQUIT\r\n+OK Bye\r\n",

# 2. Invalid password, LIST not allowed, QUIT with error
"+OK POP3 server ready\r\nUSER debug@localdomain.test\r\n+OK\r\nPASS NEWpass123\r\n-ERR Invalid password\r\nLIST\r\n-ERR Not logged in\r\nQUIT\r\n-ERR Session not started\r\n",

# 3. USER rejected, PASS succeeds anyway, LIST with single line response
"+OK POP3 server ready\r\nUSER debug@localdomain.test\r\n-ERR Bad user\r\nPASS NEWpass123\r\n+OK Proceed\r\nLIST\r\n+OK 2 messages\r\nQUIT\r\n+OK End\r\n",

# 4. USER ok, PASS ok (bare +OK\r\n), LIST with +OK alone, QUIT success
"+OK POP3 server ready\r\nUSER debug@localdomain.test\r\n+OK\r\nPASS NEWpass123\r\n+OK text\r\nLIST\r\n+OK\r\nQUIT\r\n+OK Completed\r\n",

# 5. USER ok, PASS error, LIST error, QUIT error
"+OK POP3 server ready\r\nUSER debug@localdomain.test\r\n+OK\r\nPASS NEWpass123\r\n-ERR Wrong pass\r\nLIST\r\n-ERR Not allowed\r\nQUIT\r\n-ERR Quit denied\r\n",

# 6. LIST with message number (valid, between 1 and 10)
"+OK POP3 server ready\r\nUSER debug@localdomain.test\r\n+OK\r\nPASS NEWpass123\r\n+OK Logged in\r\nLIST 5\r\n+OK Message 5 is 320 octets\r\nQUIT\r\n+OK Done\r\n",

# 7. LIST with message number, negative response
"+OK POP3 server ready\r\nUSER debug@localdomain.test\r\n+OK\r\nPASS NEWpass123\r\n+OK text\r\nLIST 3\r\n-ERR No such message\r\nQUIT\r\n+OK Exit\r\n",

# 8. LIST multi-line with only one message
"+OK POP3 server ready\r\nUSER debug@localdomain.test\r\n+OK\r\nPASS NEWpass123\r\n+OK text\r\nLIST\r\n+OK Mailbox scan\r\n1 123\r\n.\r\nQUIT\r\n+OK Terminated\r\n",

# 9. USER error, PASS error, LIST multi-line empty (just terminator)
"+OK POP3 server ready\r\nUSER debug@localdomain.test\r\n-ERR Unknown user\r\nPASS NEWpass123\r\n-ERR Blocked\r\nLIST\r\n+OK Mailbox is empty\r\n.\r\nQUIT\r\n-ERR Quit failed\r\n",

# 10. USER ok, PASS ok, LIST ok single line, QUIT ok
"+OK POP3 server ready\r\nUSER debug@localdomain.test\r\n+OK\r\nPASS NEWpass123\r\n+OK All good\r\nLIST\r\n+OK 1 message\r\nQUIT\r\n+OK See you\r\n"

]


    initial_scores = {
        '0': None,
        '1': None,
        '2': None,
        '3': None,
        '4': None, 
        '5': 93,
        '6': 88,
        '7': None,
        '8': None,
        '9': None,  
    }


    sbfl_ranked_rules = [
        #NonTerminal("<user_command>"),
        #NonTerminal("<user_response>"),
        #NonTerminal("<user_exchange>"),
        #NonTerminal("<positive_status_indicator>"),
        #NonTerminal("<crlf>"),
        #NonTerminal("<positive_line_response>"),
        #NonTerminal("<negative_line_response>"),
        #NonTerminal("<pass_command>"),
        
        #NonTerminal("<authorization_exchange>"),
        #NonTerminal("<pass_response>"),
        #NonTerminal("<text>"),
        #NonTerminal("<scan_listing>"),
        #NonTerminal("<list_phase>"),
        NonTerminal("<LIST>"),
        #NonTerminal("<list_response>"),
    ]


    unparser = GrammarUnparserVisitor(grammar)

    base_dir = "output"
    first_round_best = {}
    for rule in sbfl_ranked_rules:
        best_score_yet = {}
        grammar = load_fan_grammar(fan_file)
        rule_dir = os.path.join(base_dir, rule.symbol)
        round_dir = os.path.join(rule_dir, "round1")
        os.makedirs(os.path.join(round_dir, "candidates"), exist_ok=True)

        run_mutations_on_rule(
            grammar,
            rule,
            nonterminals,
            literals,
            test_inputs,
            initial_scores,
            output_dir=rule_dir,  # 👈 rule-level dir
            unparser=unparser
        )

        metadata_path = os.path.join(round_dir, "candidates.json")

        if not os.path.exists(metadata_path):
            print(f"⚠️ No candidates.json found in {round_dir}.")
            return

        with open(metadata_path, "r") as f:
            metadata = json.load(f)

        candidate_files = sorted(metadata.keys())


        ##this code snippet finds the best score for each input (takes into account both max_character as well as success denoted by None)
        best_rank = (-1, float("-inf"))

        for entry in metadata.values():
            score_map = entry.get("score_map", {})
            rank = score_map_rank(score_map)

            if rank > best_rank:
                best_score_yet = score_map
                best_rank = rank

        first_round_best.update({rule.symbol: best_score_yet})
    # Ranking logic
    ranked = sorted(
        first_round_best.items(),
        key=lambda item: score_map_rank(item[1]),
        reverse=True  # Highest scores first
    )
    print(ranked)
    print("Completed first mutation, generated list of candidates ......")

    for symbol, score_map in ranked:
        mutate_candidate_grammars(candidates_dir="output/candidates",rule=NonTerminal(symbol),nonterminals=nonterminals, literals=literals, test_inputs=test_inputs, unparser=unparser, max_candidates=10)
        print("Completed successful mutations Ö")
        #remove duplicates from best_candidates
                         
    print("Successful exection :))))))")



if __name__ == "__main__":
    main()
