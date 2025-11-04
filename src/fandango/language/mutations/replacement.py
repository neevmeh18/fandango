from dataclasses import dataclass
from typing import List, Optional, Union
from fandango.language.symbols import NonTerminal, Terminal
from fandango.language.grammar.nodes.non_terminal import NonTerminalNode
from fandango.language.grammar.nodes.terminal import TerminalNode
from fandango.language.grammar.nodes.char_set import CharSet
from fandango.language.grammar.nodes.concatenation import Concatenation
from fandango.language.grammar.nodes.alternative import Alternative
from fandango.language.grammar.node_visitors.node_visitor import NodeVisitor
from mutations.base import MutationTarget, GrammarMutator, MutationFinder


@dataclass
class ReplacementTarget(MutationTarget):
    parent: Optional[Union[Alternative, Concatenation]]
    index: Optional[int]
    original: Union[NonTerminalNode, TerminalNode, CharSet]
    rule_symbol: NonTerminal
    grammar_settings: any
    replacement_mode: str = "alt"

    def create_mutator(self, grammar, replacement):
        return ReplacementMutator(self, replacement, grammar)


class ReplacementMutationFinder(MutationFinder):
    """
    Collector of candidate replacement targets.

    IMPORTANT CHANGE (minimal):
      - Only produce targets where the *parent is a Concatenation* (i.e. the node
        is part of a concatenation). We *do not* produce targets for:
         * alternatives that are leaf nodes (e.g. a single NonTerminalNode in an Alternative)
         * whole-rule leaves (parent is None)
      Rationale: replacing a single isolated symbol (not inside a concatenation)
      is redundant with an alt-insert and often produces duplicated mutations
      (or nested Alternatives). Skip them to avoid identical/duplicate mutations.
    """
    def __init__(self, grammar, rule_symbol: NonTerminal, replacements: List[Union[NonTerminal, str]], grammar_settings, replacement_mode: str = "alt"):
        super().__init__(grammar, rule_symbol)
        self.replacements = replacements
        self.targets: List[ReplacementTarget] = []
        self._visited = set()
        self.grammar_settings = grammar_settings
        self.replacement_mode = replacement_mode

    def find_targets(self):
        self._visit(self.grammar[self.target_symbol])
        return self.targets

    def _visit(self, node):
        node_id = id(node)
        if node_id in self._visited:
            return
        self._visited.add(node_id)

        # --- If this is an Alternative, inspect its alternatives.
        # We *only* create replacement targets for nodes that live inside a Concatenation.
        if isinstance(node, Alternative):
            for alt in node.alternatives:
                if isinstance(alt, Concatenation):
                    # alt is a concatenation: add targets for each node inside it
                    for i, child in enumerate(alt.nodes):
                        if isinstance(child, (NonTerminalNode, TerminalNode, CharSet)):
                            self.targets.append(
                                ReplacementTarget(
                                    alt,
                                    i,
                                    child,
                                    self.target_symbol,
                                    self.grammar_settings,
                                    replacement_mode=self.replacement_mode,
                                )
                            )
                        # recurse into child for deeper structures
                        self._visit(child)
                else:
                    # alt is just a single leaf (NonTerminalNode/TerminalNode/CharSet)
                    # skip creating a replacement target here (redundant with alt-insert),
                    # but still recurse in case the leaf has children.
                    self._visit(alt)


        # --- If this is a Concatenation, create targets for children (allowed)
        elif isinstance(node, Concatenation):
            for i, child in enumerate(node.nodes):
                if isinstance(child, (NonTerminalNode, TerminalNode, CharSet)):
                    self.targets.append(
                        ReplacementTarget(node, i, child, self.target_symbol, self.grammar_settings, replacement_mode=self.replacement_mode)
                    )
                self._visit(child)

        elif isinstance(node, (NonTerminalNode, TerminalNode, CharSet)):
            # If this node is the *entire rule body* (parent is None), skip in both alt and replace modes
            if node is self.grammar[self.target_symbol]:
                return


        # --- Generic recursion for other node types
        elif hasattr(node, 'children'):
            for child in node.children():
                self._visit(child)


class ReplacementMutator(GrammarMutator):
    def __init__(self, target: ReplacementTarget, replacement, grammar):
        self.target = target
        self.replacement = replacement
        self.grammar = grammar
        self.applied = False
        self._replacement_node = self._build_node(replacement)
        self._original_rule = None
        self._mutated_added = None

    def _build_node(self, replacement):
        if isinstance(replacement, NonTerminal):
            return NonTerminalNode(replacement, self.target.grammar_settings)
        elif isinstance(replacement, str):
            if (replacement.startswith('r"') and replacement.endswith('"')) or (
                replacement.startswith("r'") and replacement.endswith("'")
            ):
                return CharSet(replacement[2:-1], self.target.grammar_settings)
            return TerminalNode(Terminal(replacement), self.target.grammar_settings)
        raise ValueError(f"Unsupported replacement type: {replacement}")

    def describe(self) -> str:
        return f"Replace@{self.target.rule_symbol.name()}"

    def apply(self):
        if self.applied:
            return

        original_rule = self.grammar.rules[self.target.rule_symbol]
        self._original_rule = original_rule

        # Build the mutated version
        if self.target.parent is None:
            # (Finder no longer emits these targets in normal operation)
            mutated = self._replacement_node
        elif isinstance(self.target.parent, Concatenation):
            new_nodes = list(self.target.parent.nodes)
            new_nodes[self.target.index] = self._replacement_node
            mutated = Concatenation(new_nodes, self.target.grammar_settings, id=getattr(self.target.parent, "id", None))
        elif isinstance(self.target.parent, Alternative):
            # Defensive: if a target with Alternative parent is ever created elsewhere,
            # we should treat the mutated object as the single child (not as an Alternative).
            mutated = self._replacement_node
        else:
            raise TypeError(f"Unsupported parent type: {type(self.target.parent)}")

        # remember what we appended so revert can remove the exact instance
        self._mutated_added = mutated

        if self.target.replacement_mode == "replace":
            # Only meaningful if part of a concatenation or larger structure
            if isinstance(self.target.parent, Concatenation):
                self.grammar.rules[self.target.rule_symbol] = mutated
            else:
                return
        else:
            # Round-1 style: add as new alternative (non-destructive)
            if isinstance(original_rule, Alternative):
                original_rule.alternatives.append(mutated)
            else:
                # wrap original + mutated into a new Alternative
                self.grammar.rules[self.target.rule_symbol] = Alternative(
                    [original_rule, mutated], self.target.grammar_settings, id="mutated_rule"
                )

        self.applied = True

    def revert(self):
        if not self.applied:
            return

        if self.target.replacement_mode == "replace":
            # restore original
            self.grammar.rules[self.target.rule_symbol] = self._original_rule
        else:
            rule = self.grammar.rules[self.target.rule_symbol]
            if isinstance(rule, Alternative):
                # remove the exact mutated object we added (safer than pop)
                try:
                    if self._mutated_added is not None:
                        rule.alternatives.remove(self._mutated_added)
                except ValueError:
                    # mutated object not found (someone else changed the list) — ignore
                    pass

                # If original wasn't an Alternative and we've reduced back to one alternative,
                # restore the original node (keep grammar shape consistent)
                if len(rule.alternatives) == 1 and not isinstance(self._original_rule, Alternative):
                    self.grammar.rules[self.target.rule_symbol] = rule.alternatives[0]
            else:
                # Unexpected: fallback to full restore
                self.grammar.rules[self.target.rule_symbol] = self._original_rule

        self.applied = False
