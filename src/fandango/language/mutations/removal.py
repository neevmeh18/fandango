# removal.py
from dataclasses import dataclass
from typing import List, Tuple
import itertools
import uuid

from fandango.language.symbols import NonTerminal, Terminal
from fandango.language.grammar.nodes.non_terminal import NonTerminalNode
from fandango.language.grammar.nodes.terminal import TerminalNode
from fandango.language.grammar.nodes.char_set import CharSet
from fandango.language.grammar.nodes.concatenation import Concatenation
from fandango.language.grammar.nodes.alternative import Alternative
from fandango.language.grammar.node_visitors.node_visitor import NodeVisitor

from mutations.base import MutationTarget, GrammarMutator, MutationFinder

@dataclass
class RemovalTarget(MutationTarget):
    parent: any                # Concatenation
    indices_to_remove: Tuple[int, ...]
    target_symbol: NonTerminal
    grammar_settings: any
    alt_index: int = None      # which alternative index if parent is inside an Alternative

    def create_mutator(self, grammar):
        return RemovalMutator(self, grammar)


class RemovalMutationFinder(NodeVisitor):
    """
    Finds all valid removal targets inside concatenations for the specified rule.
    For a concatenation with N symbols we produce every non-empty subset of indices
    except the full set (we do not remove the entire concatenation).
    Single-symbol concatenations yield no targets (can't remove the only symbol).
    """
    def __init__(self, grammar, target_symbol: NonTerminal, grammar_settings):
        super().__init__()
        self.grammar = grammar
        self.target_symbol = target_symbol
        self.grammar_settings = grammar_settings
        self.targets: List[RemovalTarget] = []
        self._seen = set()

    def find_targets(self):
        # Ensure top-level bare leaves are wrapped like insertion.py does
        root = self.grammar[self.target_symbol]
        if isinstance(root, (NonTerminalNode, TerminalNode, CharSet)):
            # wrap single leaf into Concatenation so handling is uniform
            concat = Concatenation([root], self.grammar_settings, id=f"wrap_{uuid.uuid4().hex}")
            self.grammar[self.target_symbol] = concat
        self.visit(self.grammar[self.target_symbol])
        return self.targets

    def visitConcatenation(self, node: Concatenation, alt_index=None):
        # avoid repeated visits
        key = (id(node), alt_index)
        if key in self._seen:
            return
        self._seen.add(key)

        length = len(node.nodes)
        # only consider concatenations with 2 or more nodes (we cannot remove the only node)
        if length >= 2:
            # generate all non-empty proper subsets of indices
            indices = list(range(length))
            for r in range(1, length):  # r from 1 to length-1 (exclude full removal)
                for combo in itertools.combinations(indices, r):
                    self.targets.append(RemovalTarget(
                        parent=node,
                        indices_to_remove=tuple(sorted(combo)),
                        target_symbol=self.target_symbol,
                        grammar_settings=self.grammar_settings,
                        alt_index=alt_index
                    ))

        # continue traversal
        for i, child in enumerate(node.children()):
            # if child is concatenation/alternative it will be handled by visit*
            self.visit(child)

    def visitAlternative(self, node: Alternative):
        # make sure each alternative is a Concatenation (wrap singletons)
        for i, alt in enumerate(node.alternatives):
            if not isinstance(alt, Concatenation):
                concat = Concatenation([alt], self.grammar_settings, id=f"altwrap_{uuid.uuid4().hex}")
                node.alternatives[i] = concat
                alt = concat
            # find removal targets inside this concatenation, providing the alt index
            self.visitConcatenation(alt, alt_index=i)

    def visitChildren(self, node):
        for child in node.children():
            self.visit(child)


class RemovalMutator(GrammarMutator):
    def __init__(self, target: RemovalTarget, grammar):
        self.target = target
        self.grammar = grammar
        self.applied = False
        self._original_nodes = None
        self._original_rule = None

    def describe(self) -> str:
        return f"Remove(indices={self.target.indices_to_remove})@{self.target.target_symbol.name()}"

    def apply(self):
        if self.applied:
            return

        parent = self.target.parent
        # defensive copy of original nodes for revert
        self._original_nodes = list(parent.nodes)

        # compute new nodes by dropping the indices in indices_to_remove
        to_drop = set(self.target.indices_to_remove)
        new_nodes = [n for i, n in enumerate(self._original_nodes) if i not in to_drop]

        # apply
        parent.nodes = new_nodes

        self.applied = True

    def revert(self):
        if not self.applied:
            return
        if self._original_nodes is not None:
            self.target.parent.nodes = list(self._original_nodes)
        self.applied = False
