import itertools
from dataclasses import dataclass
from typing import List, Tuple

from fandango.language.symbols import NonTerminal
from fandango.language.grammar.nodes.alternative import Alternative
from fandango.language.grammar.nodes.non_terminal import NonTerminalNode

from mutations.base import MutationTarget, GrammarMutator, MutationFinder


@dataclass
class AltRemovalTarget(MutationTarget):
    parent_alt: Alternative
    indices_to_remove: Tuple[int]
    rule_symbol: NonTerminal
    grammar_settings: any

    def create_mutator(self, grammar):
        return AltRemovalMutator(self)

    def describe(self):
        return f"alt_removal_{'_'.join(map(str, self.indices_to_remove))}"


class AltRemovalMutator(GrammarMutator):
    def __init__(self, target: AltRemovalTarget):
        self.target = target
        # store nodes to reinsert on revert
        self.removed_nodes: List[Tuple[int, any]] = []
        self.applied = False

    def apply(self):
        if self.applied:
            return
        self.removed_nodes = []
        # delete in descending order to keep indices stable
        for idx in sorted(self.target.indices_to_remove, reverse=True):
            if 0 <= idx < len(self.target.parent_alt.alternatives):
                node = self.target.parent_alt.alternatives[idx]
                self.removed_nodes.append((idx, node))
                del self.target.parent_alt.alternatives[idx]
        # store in ascending order for clean revert
        self.removed_nodes.sort(key=lambda x: x[0])
        self.applied = True

    def revert(self):
        if not self.applied:
            return
        for idx, node in self.removed_nodes:
            self.target.parent_alt.alternatives.insert(idx, node)
        self.removed_nodes = []
        self.applied = False


class AltRemovalFinder(MutationFinder):
    """
    Finds all subsets of removable alternatives in a given rule.
    Excludes the <mutation_...> child, which must always remain.
    """

    def __init__(self, grammar, rule_symbol: NonTerminal, grammar_settings):
        super().__init__(grammar, rule_symbol)
        self.grammar_settings = grammar_settings

    def find_targets(self) -> List[AltRemovalTarget]:
        rule_node = self.grammar[self.target_symbol]
        if not isinstance(rule_node, Alternative):
            return []

        # locate the <mutation_...> child
        mutation_index = None
        for idx, child in enumerate(rule_node.alternatives):
            if isinstance(child, NonTerminalNode) and child.symbol.symbol.startswith("<mutation_"):
                mutation_index = idx
                break

        # indices of removable alts (all except mutation child)
        removable_indices = [
            idx for idx in range(len(rule_node.alternatives))
            if idx != mutation_index
        ]

        targets: List[AltRemovalTarget] = []
        # all non-empty subsets of removable alts
        for r in range(1, len(removable_indices) + 1):
            for combo in itertools.combinations(removable_indices, r):
                targets.append(
                    AltRemovalTarget(
                        parent_alt=rule_node,
                        indices_to_remove=combo,
                        rule_symbol=self.target_symbol,
                        grammar_settings=self.grammar_settings,
                    )
                )

        return targets
