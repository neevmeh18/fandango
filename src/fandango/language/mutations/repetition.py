from dataclasses import dataclass
from fandango.language.symbols import NonTerminal, Terminal
from fandango.language.grammar.nodes.non_terminal import NonTerminalNode
from fandango.language.grammar.nodes.terminal import TerminalNode
from fandango.language.grammar.nodes.char_set import CharSet
from fandango.language.grammar.nodes.concatenation import Concatenation
from fandango.language.grammar.nodes.alternative import Alternative
from fandango.language.grammar.node_visitors.node_visitor import NodeVisitor
from fandango.language.grammar.nodes.repetition import Plus, Repetition, Star
from mutations.base import MutationTarget, GrammarMutator, MutationFinder


@dataclass
class RepetitionTarget(MutationTarget):
    parent: any
    index: int
    original: any
    symbol: NonTerminal
    grammar_settings: any   # 👈 added
    is_existing_repetition: bool = False

    def create_mutator(self, grammar, use_plus=False):
        return RepetitionMutator(self, grammar, use_plus=use_plus)


class RepetitionMutationFinder(NodeVisitor):
    def __init__(self, grammar, target_symbol: NonTerminal, grammar_settings):
        super().__init__()
        self.grammar = grammar
        self.target_symbol = target_symbol
        self.grammar_settings = grammar_settings
        self.targets: list[RepetitionTarget] = []
        self._seen = set()

    def find_targets(self):
        self.visit(self.grammar[self.target_symbol])
        return self.targets

    def visitAlternative(self, node: Alternative):
        for i, child in enumerate(node.alternatives):
            self.targets.append(RepetitionTarget(
                parent=node,
                index=i,
                original=child,
                symbol=self.target_symbol,
                grammar_settings=self.grammar_settings,
                is_existing_repetition=isinstance(child, Repetition)
            ))
            self.visit(child)

    def visitConcatenation(self, node: Concatenation):
        for i, child in enumerate(node.nodes):
            key = (id(node), i)
            if key in self._seen:
                continue
            self._seen.add(key)

            if isinstance(child, (TerminalNode, NonTerminalNode)):
                self.targets.append(RepetitionTarget(
                    parent=node,
                    index=i,
                    original=child,
                    symbol=self.target_symbol,
                    grammar_settings=self.grammar_settings,
                    is_existing_repetition=False
                ))
            elif isinstance(child, Repetition):
                self.targets.append(RepetitionTarget(
                    parent=node,
                    index=i,
                    original=child,
                    symbol=self.target_symbol,
                    grammar_settings=self.grammar_settings,
                    is_existing_repetition=True
                ))

            self.visit(child)

    def visitChildren(self, node):
        for i, child in enumerate(node.children()):
            self.visit(child)

        if node is self.grammar[self.target_symbol]:
            self.targets.append(RepetitionTarget(
                parent=None,
                index=None,
                original=node,
                symbol=self.target_symbol,
                grammar_settings=self.grammar_settings,
                is_existing_repetition=False
            ))


class RepetitionMutator(GrammarMutator):
    def __init__(self, target: RepetitionTarget, grammar, use_plus=False):
        self.target = target
        self.grammar = grammar
        self.use_plus = use_plus
        self.applied = False
        self.original_top_level = None
        self.original_child = None

    def apply(self):
        if self.applied:
            return

        repetition_cls = Plus if self.use_plus else Star
        rule_node = self.grammar[self.target.symbol]
        new_node = repetition_cls(
            self.target.original,
            self.target.grammar_settings,
            id=f"{getattr(rule_node, 'id', 'top')}_{repetition_cls.__name__.lower()}"
        )

        if self.target.parent is None:
            self.original_top_level = self.grammar[self.target.symbol]
            self.grammar[self.target.symbol] = new_node
        else:
            if isinstance(self.target.parent, Concatenation):
                self.original_child = self.target.parent.nodes[self.target.index]
                self.target.parent.nodes[self.target.index] = new_node
            elif isinstance(self.target.parent, Alternative):
                self.original_child = self.target.parent.alternatives[self.target.index]
                self.target.parent.alternatives[self.target.index] = new_node

        self.applied = True

    def revert(self):
        if not self.applied:
            return

        if self.target.parent is None:
            self.grammar[self.target.symbol] = self.original_top_level
        else:
            if isinstance(self.target.parent, Concatenation):
                self.target.parent.nodes[self.target.index] = self.original_child
            elif isinstance(self.target.parent, Alternative):
                self.target.parent.alternatives[self.target.index] = self.original_child

        self.applied = False
