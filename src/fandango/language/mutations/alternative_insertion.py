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
class AltInsertionTarget(MutationTarget):
    alt_node: Alternative
    insert_node: any  # Either NonTerminalNode, TerminalNode, or CharSet
    rule_symbol: NonTerminal
    grammar_settings: any   # 👈 added

    def create_mutator(self, grammar):
        return AltInsertionMutator(self)


class AltInsertionFinder(MutationFinder):
    def __init__(self, grammar, rule_symbol: NonTerminal, insert_value, grammar_settings):
        super().__init__(grammar, rule_symbol)
        self.targets: List[AltInsertionTarget] = []
        self.grammar_settings = grammar_settings

        if isinstance(insert_value, NonTerminal):
            self.insert_node = NonTerminalNode(insert_value, grammar_settings)
        elif isinstance(insert_value, str):
            if insert_value.startswith("r'") or insert_value.startswith("r\""):
                self.insert_node = CharSet(insert_value[2:-1], grammar_settings)
            else:
                self.insert_node = TerminalNode(Terminal(insert_value.strip('"')), grammar_settings)
        else:
            raise ValueError(f"Unsupported insert_value: {insert_value}")

    def find_targets(self):
        self._visit(self.grammar[self.target_symbol])
        return self.targets

    def _visit(self, node):
        if node is self.grammar[self.target_symbol] and not isinstance(node, Alternative):
            # Wrap top-level rule in Alternative if not already
            alt = Alternative([node], self.grammar_settings, id="alt_wrap")
            self.grammar[self.target_symbol] = alt

            if not self._is_self_recursive(self.insert_node):
                self.targets.append(
                    AltInsertionTarget(alt, self.insert_node, self.target_symbol, self.grammar_settings)
                )
            for child in alt.children():
                self._visit(child)

        elif isinstance(node, Alternative):
            if not self._is_self_recursive(self.insert_node):
                self.targets.append(
                    AltInsertionTarget(node, self.insert_node, self.target_symbol, self.grammar_settings)
                )
            for child in node.children():
                self._visit(child)

        elif hasattr(node, 'children'):
            for child in node.children():
                self._visit(child)

    def _is_self_recursive(self, insert_node):
        return (
            isinstance(insert_node, NonTerminalNode)
            and insert_node.symbol == self.target_symbol
        )


class AltInsertionMutator(GrammarMutator):
    def __init__(self, target: AltInsertionTarget):
        self.target = target
        self.applied = False
        self._copy_node = None

    def apply(self):
        if self.applied:
            return
        self._copy_node = self._clone_node(self.target.insert_node)
        self.target.alt_node.alternatives.append(self._copy_node)
        self.applied = True

    def revert(self):
        if not self.applied:
            return
        if self._copy_node in self.target.alt_node.alternatives:
            self.target.alt_node.alternatives.remove(self._copy_node)
        self.applied = False

    def _clone_node(self, node):
        if isinstance(node, NonTerminalNode):
            return NonTerminalNode(node.symbol, self.target.grammar_settings)
        elif isinstance(node, TerminalNode):
            return TerminalNode(node.symbol, self.target.grammar_settings)
        elif isinstance(node, CharSet):
            return CharSet(node.chars, self.target.grammar_settings)
        else:
            raise ValueError(f"Unsupported node type for cloning: {type(node)}")
