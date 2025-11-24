#!/usr/bin/env python3

import copy
import os
import sys
import time
import json
import ast
import re
from pathlib import Path
from collections import defaultdict
from typing import Dict, Set, Any, List, Tuple, Optional

from fandango.language.grammar.node_visitors.node_visitor import NodeVisitor
from fandango.language.grammar.nodes.alternative import Alternative
from fandango.language.grammar.nodes.char_set import CharSet
from fandango.language.grammar.nodes.concatenation import Concatenation
from fandango.language.grammar.nodes.non_terminal import NonTerminalNode
from fandango.language.grammar.nodes.repetition import Plus, Repetition, Star, Option
from fandango.language.grammar.nodes.terminal import TerminalNode
from fandango.language.mutations.delete_wrong_alt import DeleteWrongAltsFinder
from fandango.language.mutations.plan import MutationPlan
from fandango.language.parse import parse
from fandango.evolution.algorithm import Fandango, LoggerLevel
from fandango.language.grammar import FuzzingMode
from fandango.language.symbols.non_terminal import NonTerminal
from mutations.alternative_removal import AltRemovalFinder

FAN_FILE = "list_grammar.fan"   
OUT_MUTATED_DIR = "mutated_fans"
N_RUNS = 10                     
POPULATION_SIZE = 20
MAX_MUTATIONS = 50              
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
def extract_nt_stack(tree):
    """
    Return list of NonTerminal symbols from the derivation tree,
    ordered from last (deepest) to first (root).
    """
    nts = []
    for node in tree.flatten():            # preorder: parent → children
        if node.is_non_terminal:
            nts.append(node.symbol)
    return list(reversed(nts))             # last → first

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

def load_parsed_grammar(fan_file: str):
    fan_path = Path(fan_file).resolve()

    with open(fan_path, "r") as f:
        grammar, constraints = parse(f, use_stdlib=False)
    print("[load_parsed_grammar] Parsed grammar from", fan_file)
    return grammar, constraints

def run_and_mutate(fan_file: str, n_runs: int, population_size: int) -> Any:

    
    try:
        grammar, constraints = load_parsed_grammar(fan_file)
    except Exception as e:
        print("[validate] ERROR parsing grammar:", e)

    unparser = GrammarUnparserVisitor(grammar=grammar)
    nonterminals, literals = extract_literals_and_nonterminals(FAN_FILE)


    fandango = Fandango(
        grammar=grammar,
        constraints=constraints,
        population_size=population_size,   
        logger_level=LoggerLevel.INFO)
     
    try:
        gen_iter = fandango.generate(mode=FuzzingMode.IO)
    except Exception as e:
        print(f"[validate] ERROR starting generation: {e}")

    iterator = iter(gen_iter)
    solutions_collected = 0

    while solutions_collected < population_size:
        try:
            solution = next(iterator)

        except StopIteration:
            print("[validate] Generation finished (StopIteration).")
            break
        except Exception as gen_exc:

            spec_env_global, _ = grammar.get_spec_env()
            io_cls = spec_env_global["FandangoIO"]
            io_instance = io_cls.instance()
            io_instance.reset_parties()
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
                    rec_path = f"derivation_logs/partial_{rec_id}.json"
                    with open(rec_path, "w") as rf:
                        json.dump(rule_sigs, rf, indent=2)
                    print(f"[validate] Saved partial rule_sigs to {rec_path}")
                except Exception as e:
                    print(f"[validate] Warning: could not save partial rule_sigs: {e}")

                nt_stack = extract_nt_stack(last_tree)

                result = False
                for nt in nt_stack:
                    result = delete_wrong_alts(
                        grammar,
                        nt,
                        fan_file,
                        unparser,
                        [],
                        nonterminals,
                        round_num=0,
                        constraints=constraints
                    )
                    if result:
                        break

                print(result)


            else:
                print("[validate] No partial tree available to attribute generator exception (no action taken).")

            # Stop iterating on generator exception
            break

        # process the yielded solution
        solutions_collected += 1
        print(f"\n[validate] Processing solution #{solutions_collected}")


def delete_wrong_alts(
    grammar,
    rule_name,
    full_name,
    unparser,
    grammar_settings,
    nonterminals,
    round_num,
    constraints=[],
):
    """
    Try delete-wrong-alts mutations for rule_name:
      - enumerate targets via DeleteWrongAltsFinder
      - for each: apply, rebuild parser, run test_inputs, if all pass -> server validation
      - if server accepts -> save candidate to best_candidates and return True
      - always revert before moving to next target
    """
    base_name = full_name[:-4] if full_name.endswith(".fan") else full_name
    base_dir = "./output/push_trials"
    os.makedirs(base_dir, exist_ok=True)
    finder = DeleteWrongAltsFinder(grammar, rule_name, grammar_settings)
    targets = finder.find_targets()
    trials = 0

    for idx, target in enumerate(targets):
        mutator = target.create_mutator(grammar)
        plan = MutationPlan([mutator])
        error_flag = False
        try:
            print(f"\n[DeleteWrongAlts] Trial #{trials}: {target.describe()}")
            plan.apply_all()

            new_name = f"{os.path.basename(base_name)}+{target.describe()}.fan"
            new_full_name = os.path.join(base_dir, new_name)

            with open(new_full_name, "w", encoding="utf-8") as f:
                for nt, rule in grammar.rules.items():
                    name_nt = nt.name()
                    print(name_nt)
                    f.write(f"{name_nt} ::= {unparser.visit(rule)}\n")

            print(f"[DeleteWrongAlts] Saved candidate {new_full_name}")

            fandango = Fandango(
                grammar=grammar,
                constraints=constraints,
                population_size=20,   
                logger_level=LoggerLevel.INFO)
            
            try:
                gen_iter = fandango.generate(mode=FuzzingMode.IO)
            except Exception as e:
                print(f"[validate] ERROR starting generation: {e}")

            iterator = iter(gen_iter)
            solutions_collected = 0

            while solutions_collected < 20:
                try:
                    solution = next(iterator)

                except StopIteration:
                    print("[validate] Generation finished (StopIteration).")
                    break
                except Exception as gen_exc:
                    error_flag = True
                    print(f"[validate] Generation iterator raised an exception: {gen_exc}")

                solutions_collected += 1
                print(f"\n[validate] Processing solution #{solutions_collected}")


            if error_flag == False:
                best_dir = os.path.join("output", "final_candidates", f"round{round_num}", rule_name.name())
                os.makedirs(best_dir, exist_ok=True)
                best_path = os.path.join(best_dir, new_name)

                with open(best_path, "w", encoding="utf-8") as f:
                    for nt, rule in grammar.rules.items():
                        name_nt = nt.name()
                        f.write(f"{name_nt} ::= {unparser.visit(rule)}\n")

                    # keep same Python footer as your other pipeline files
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

                print(f"[DeleteWrongAlts] ✅ Grammar fixed and saved: {best_path}")
                plan.revert_all()
                return True  # stop after first accepted fix
            else:
                print("[DeleteWrongAlts] ❌ Server validation failed, rejecting removal.")
                plan.revert_all()

        except Exception as e:
            print(f"[DeleteWrongAlts] ❌ Error in trial {idx}: {e}")
            try:
                plan.revert_all()
            except Exception:
                pass


    return False
          

if __name__ == "__main__":
    out = run_and_mutate(FAN_FILE, n_runs=N_RUNS, population_size=POPULATION_SIZE)
    print("Final output:", out)



