import itertools
import copy
from dataclasses import dataclass
from typing import List
from fandango.language.symbols import NonTerminal, Terminal
from fandango.language.grammar.nodes.non_terminal import NonTerminalNode
from fandango.language.grammar.nodes.terminal import TerminalNode
from fandango.language.grammar.nodes.char_set import CharSet
from fandango.language.grammar.nodes.concatenation import Concatenation
from fandango.language.grammar.nodes.alternative import Alternative
from fandango.language.grammar.node_visitors.node_visitor import NodeVisitor
from mutations.base import MutationTarget, GrammarMutator, MutationFinder

@dataclass
class AltConcatTarget(MutationTarget):
    alt_node: Alternative
    original_alternatives: List
    symbol: NonTerminal

    def create_mutator(self, grammar):
        return AltConcatMutator(self, grammar)


class AltConcatMutationFinder(NodeVisitor):
    def __init__(self, grammar, target_symbol: NonTerminal):
        super().__init__()
        self.grammar = grammar
        self.target_symbol = target_symbol

    def find_targets(self) -> List[AltConcatTarget]:
        self.targets: List[AltConcatTarget] = []
        self.visit(self.grammar[self.target_symbol])
        return self.targets

    def visitAlternative(self, node: Alternative):
        if len(node.alternatives) >= 2:
            self.targets.append(AltConcatTarget(
                alt_node=node,
                original_alternatives=node.alternatives.copy(),
                symbol=self.target_symbol
            ))
        for child in node.children():
            self.visit(child)

    def visitChildren(self, node):
        for child in node.children():
            self.visit(child)


class AltConcatMutator(GrammarMutator):
    def __init__(self, target: AltConcatTarget, grammar):
        self.target = target
        self.grammar = grammar
        self.new_nodes = []
        self.applied = False

    def apply(self):
        if self.applied:
            return
        original = self.target.original_alternatives
        for r in range(2, len(original) + 1):
            for combo in itertools.permutations(original, r):
                cloned = [copy.deepcopy(n) for n in combo]
                concat = Concatenation(cloned, id="concat_mut")
                self.new_nodes.append(concat)
        self.target.alt_node.alternatives.extend(self.new_nodes)
        self.applied = True

    def revert(self):
        if not self.applied:
            return
        for node in self.new_nodes:
            if node in self.target.alt_node.alternatives:
                self.target.alt_node.alternatives.remove(node)
        self.applied = False
