from dataclasses import dataclass
from itertools import permutations
from fandango.language.symbols import NonTerminal
from fandango.language.grammar.nodes.non_terminal import NonTerminalNode
from fandango.language.grammar.nodes.terminal import TerminalNode
from fandango.language.grammar.nodes.char_set import CharSet
from fandango.language.grammar.nodes.concatenation import Concatenation
from fandango.language.grammar.nodes.alternative import Alternative
from fandango.language.grammar.node_visitors.node_visitor import NodeVisitor
from mutations.base import MutationTarget, GrammarMutator, MutationFinder


@dataclass
class ReorderTarget(MutationTarget):
    node: Concatenation
    original_order: list
    permutation: list
    rule_symbol: any
    grammar_settings: any
    reorder_mode: str = "alt"  # "alt" (round 1) → add as new alternative
                               # "replace" (round ≥2) → replace original

    def create_mutator(self, grammar):
        return ReorderMutator(self, grammar)


class ReorderMutationFinder(MutationFinder):
    def __init__(self, grammar, target_symbol: NonTerminal, grammar_settings, reorder_mode: str = "alt"):
        super().__init__(grammar, target_symbol)
        self.grammar_settings = grammar_settings
        self.reorder_mode = reorder_mode
        self.targets = []

    def find_targets(self):
        self.targets = []
        self._visit(self.grammar[self.target_symbol])
        return self.targets

    def _visit(self, node):
        if isinstance(node, Concatenation):
            original_order = list(node.nodes)
            for perm in permutations(range(len(original_order))):
                if list(perm) != list(range(len(original_order))):
                    self.targets.append(ReorderTarget(
                        node=node,
                        original_order=original_order,
                        permutation=list(perm),
                        rule_symbol=self.target_symbol,
                        grammar_settings=self.grammar_settings,
                        reorder_mode=self.reorder_mode
                    ))
        if hasattr(node, 'children'):
            for child in node.children():
                self._visit(child)


class ReorderMutator(GrammarMutator):
    def __init__(self, target: ReorderTarget, grammar):
        self.target = target
        self.grammar = grammar
        self.applied = False
        self._mutated_concat = None
        self._original_rule = None

    def describe(self) -> str:
        return f"Reorder@{self.target.rule_symbol.name()}"

    def apply(self):
        if self.applied:
            return

        reordered = [self.target.original_order[i] for i in self.target.permutation]
        self._mutated_concat = Concatenation(reordered, self.target.grammar_settings, id="mutated")

        original_rule = self.grammar.rules[self.target.rule_symbol]
        self._original_rule = original_rule

        if self.target.reorder_mode == "replace":
            # Replace the body directly
            self.grammar.rules[self.target.rule_symbol] = self._mutated_concat
        else:
            # Round-1 style: add as new alternative
            if isinstance(original_rule, Alternative):
                original_rule.alternatives.append(self._mutated_concat)
            else:
                self.grammar.rules[self.target.rule_symbol] = Alternative(
                    [original_rule, self._mutated_concat],
                    self.target.grammar_settings,
                    id="mutated"
                )

        self.applied = True

    def revert(self):
        if not self.applied:
            return

        if self.target.reorder_mode == "replace":
            # restore original body
            self.grammar.rules[self.target.rule_symbol] = self._original_rule
        else:
            rule = self.grammar.rules[self.target.rule_symbol]
            if isinstance(self._original_rule, Alternative):
                if isinstance(rule, Alternative) and self._mutated_concat in rule.alternatives:
                    rule.alternatives.remove(self._mutated_concat)
            else:
                # original wasn't an Alternative: restore it fully
                self.grammar.rules[self.target.rule_symbol] = self._original_rule

        self.applied = False
