from dataclasses import dataclass
from typing import List, Optional, Union
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
class InsertionTarget(MutationTarget):
    parent: any  # Concatenation
    insert_position: int
    symbol: any  # NonTerminal or string literal
    target_symbol: NonTerminal
    grammar_settings: any
    is_literal: bool = False
    alt_index: Optional[int] = None
    insertion_mode: str = "alt"  # "alt" = new alternative (round 1), "concat" = inline (round >= 2)

    def create_mutator(self, grammar):
        if self.is_literal:
            return LiteralInsertionMutator(self, grammar)
        else:
            return NonterminalInsertionMutator(self, grammar)


class InsertionMutationFinder(NodeVisitor):
    def __init__(self, grammar, target_symbol: NonTerminal, insert_symbol, grammar_settings, insertion_mode: str = "alt"):
        self.targets: List[InsertionTarget] = []
        self.grammar = grammar
        self.target_symbol = target_symbol
        self.insert_symbol = insert_symbol
        self.grammar_settings = grammar_settings
        self.insertion_mode = insertion_mode
        self._wrapped_alts = set()

    def find_targets(self):
        self.visit(self.grammar[self.target_symbol])
        return self.targets

    def visit(self, node):
        # If the rule's top-level body is a bare leaf, wrap it into a Concatenation so we can treat uniformly.
        if isinstance(node, (NonTerminalNode, TerminalNode, CharSet)):
            if not isinstance(self.grammar[self.target_symbol], Concatenation):
                concat = Concatenation([node], self.grammar_settings, id=f"wrap_{uuid.uuid4().hex}")
                self.grammar[self.target_symbol] = concat
                self._handle_concatenation(concat)
        else:
            super().visit(node)

    def visitConcatenation(self, node: Concatenation, alt_index=None):
        self._handle_concatenation(node, alt_index)
        for child in node.children():
            self.visit(child)

    def _handle_concatenation(self, node: Concatenation, alt_index=None):
        # allow insertion at every position (including before first and after last)
        for i in range(len(node.nodes) + 1):
            self.targets.append(InsertionTarget(
                parent=node,
                insert_position=i,
                symbol=self.insert_symbol,
                target_symbol=self.target_symbol,
                grammar_settings=self.grammar_settings,
                is_literal=isinstance(self.insert_symbol, str),
                alt_index=alt_index,
                insertion_mode=self.insertion_mode,
            ))

    def visitAlternative(self, node: Alternative):
        for i, alt in enumerate(node.alternatives):
            if not isinstance(alt, Concatenation):
                concat = Concatenation([alt], self.grammar_settings, id=f"altwrap_{uuid.uuid4().hex}")
                node.alternatives[i] = concat
                alt = concat
            for pos in range(len(alt.nodes) + 1):
                self.targets.append(InsertionTarget(
                    parent=alt,
                    insert_position=pos,
                    symbol=self.insert_symbol,
                    target_symbol=self.target_symbol,
                    grammar_settings=self.grammar_settings,
                    is_literal=isinstance(self.insert_symbol, str),
                    alt_index=i,
                    insertion_mode=self.insertion_mode,
                ))

    def visitChildren(self, node):
        for child in node.children():
            self.visit(child)


class NonterminalInsertionMutator(GrammarMutator):
    def __init__(self, target: InsertionTarget, grammar):
        self.target = target
        self.grammar = grammar
        self.applied = False
        self._original_rule = None
        self._mutated = None

    def describe(self) -> str:
        return f"Insert({self.target.symbol.name()})@{self.target.target_symbol.name()}"

    def apply(self):
        if self.applied:
            return

        new_node = NonTerminalNode(self.target.symbol, self.target.grammar_settings)
        self._original_rule = self.grammar.rules[self.target.target_symbol]

        if self.target.insertion_mode == "concat":
            # Inline insertion (modify parent nodes)
            new_nodes = list(self.target.parent.nodes)
            new_nodes.insert(self.target.insert_position, new_node)
            self.target.parent.nodes = new_nodes
        else:
            # Alternative insertion: create a mutated Concatenation and either append or wrap
            new_nodes = list(self.target.parent.nodes)
            new_nodes.insert(self.target.insert_position, new_node)
            self._mutated = Concatenation(new_nodes, self.target.grammar_settings, id=f"mut_{uuid.uuid4().hex}")

            if isinstance(self._original_rule, Alternative):
                self._original_rule.alternatives.append(self._mutated)
            else:
                self.grammar.rules[self.target.target_symbol] = Alternative(
                    [self._original_rule, self._mutated], self.target.grammar_settings, id=f"mutated_{self.target.target_symbol.name()}_{uuid.uuid4().hex}"
                )

        self.applied = True

    def revert(self):
        if not self.applied:
            return

        if self.target.insertion_mode == "concat":
            # remove the inserted node at the same position
            # defensive: ensure index still valid
            if 0 <= self.target.insert_position < len(self.target.parent.nodes):
                # if parent was mutated elsewhere this may differ; we try to remove the node we inserted by searching
                # for a NonTerminalNode with the same symbol at or after insert_position
                try:
                    candidate = self.target.parent.nodes[self.target.insert_position]
                    if isinstance(candidate, NonTerminalNode) and candidate.symbol == self.target.symbol:
                        self.target.parent.nodes.pop(self.target.insert_position)
                    else:
                        # fallback: try to remove first matching node
                        for i, n in enumerate(self.target.parent.nodes):
                            if isinstance(n, NonTerminalNode) and n.symbol == self.target.symbol:
                                self.target.parent.nodes.pop(i)
                                break
                except Exception:
                    pass
        else:
            # alt mode: either remove the specific mutated node, or restore the original rule
            rule = self.grammar.rules[self.target.target_symbol]
            if isinstance(self._original_rule, Alternative):
                if isinstance(rule, Alternative) and self._mutated in rule.alternatives:
                    rule.alternatives.remove(self._mutated)
            else:
                # restore original non-Alternative rule
                self.grammar.rules[self.target.target_symbol] = self._original_rule

        self.applied = False


class LiteralInsertionMutator(GrammarMutator):
    def __init__(self, target: InsertionTarget, grammar):
        self.target = target
        self.grammar = grammar
        self.applied = False
        self._original_rule = None
        self._mutated = None

    def describe(self) -> str:
        return f"Insert({self.target.symbol})@{self.target.target_symbol.name()}"

    def apply(self):
        if self.applied:
            return

        lit = self.target.symbol
        if isinstance(lit, str) and ((lit.startswith("r\"") and lit.endswith("\"")) or (lit.startswith("r'") and lit.endswith("'"))):
            new_node = CharSet(lit[2:-1], self.target.grammar_settings)
        else:
            new_node = TerminalNode(Terminal(lit), self.target.grammar_settings)

        self._original_rule = self.grammar.rules[self.target.target_symbol]

        if self.target.insertion_mode == "concat":
            new_nodes = list(self.target.parent.nodes)
            new_nodes.insert(self.target.insert_position, new_node)
            self.target.parent.nodes = new_nodes
        else:
            new_nodes = list(self.target.parent.nodes)
            new_nodes.insert(self.target.insert_position, new_node)
            self._mutated = Concatenation(new_nodes, self.target.grammar_settings, id=f"mut_{uuid.uuid4().hex}")

            if isinstance(self._original_rule, Alternative):
                self._original_rule.alternatives.append(self._mutated)
            else:
                self.grammar.rules[self.target.target_symbol] = Alternative(
                    [self._original_rule, self._mutated], self.target.grammar_settings, id=f"mutated_{self.target.target_symbol.name()}_{uuid.uuid4().hex}"
                )

        self.applied = True

    def revert(self):
        if not self.applied:
            return

        if self.target.insertion_mode == "concat":
            if 0 <= self.target.insert_position < len(self.target.parent.nodes):
                candidate = self.target.parent.nodes[self.target.insert_position]
                if isinstance(candidate, (TerminalNode, CharSet)):
                    self.target.parent.nodes.pop(self.target.insert_position)
                else:
                    # fallback: remove first matching terminal/charset
                    for i, n in enumerate(self.target.parent.nodes):
                        if isinstance(n, (TerminalNode, CharSet)) and getattr(n, 'value', None) == self.target.symbol:
                            self.target.parent.nodes.pop(i)
                            break
        else:
            rule = self.grammar.rules[self.target.target_symbol]
            if isinstance(self._original_rule, Alternative):
                if isinstance(rule, Alternative) and self._mutated in rule.alternatives:
                    rule.alternatives.remove(self._mutated)
            else:
                self.grammar.rules[self.target.target_symbol] = self._original_rule

        self.applied = False
