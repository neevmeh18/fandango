# delete_wrong_alt.py
import itertools
from dataclasses import dataclass
from typing import List, Tuple, Optional, Any, Dict

from fandango.language.symbols import NonTerminal
from fandango.language.grammar.nodes.alternative import Alternative
from fandango.language.grammar.nodes.non_terminal import NonTerminalNode

from mutations.base import MutationTarget, GrammarMutator, MutationFinder

# NOTE:
# parent_alt is typed as Any to accommodate two internal representations:
#  - Alternative (many-rule representation with .alternatives list)
#  - arbitrary node (single-alt rule represented directly by a node object)
# The mutator treats them appropriately.


@dataclass
class DeleteWrongAltsTarget(MutationTarget):
    parent_alt: Any  # Alternative or single-node rule
    indices_to_remove: Tuple[int, ...]
    rule_symbol: NonTerminal
    referencing_parents: Optional[List[Tuple[Alternative, int]]] = None
    grammar_settings: Any = None

    def create_mutator(self, grammar):
        return DeleteWrongAltsMutator(self, grammar)

    def describe(self):
        return f"delete_wrong_alts_{'_'.join(map(str, self.indices_to_remove))}"


class DeleteWrongAltsMutator(GrammarMutator):
    def __init__(self, target: DeleteWrongAltsTarget, grammar):
        self.target = target
        self.grammar = grammar

        # primary removals from target.parent_alt when parent_alt is Alternative:
        # list of (idx, node)
        self.removed_nodes: List[Tuple[int, Any]] = []
        # when deleting references across other parents: list[(parent_alt, (idx,node))]
        self.removed_referencing: List[Tuple[Alternative, Tuple[int, Any]]] = []
        # if rule entry removed from grammar.rules: store (NonTerminal, node)
        self.deleted_rule_entry: Optional[Tuple[NonTerminal, Any]] = None

        # For the single-node (non-Alternative) rule case we may store the original node
        # under deleted_rule_entry (same as above).
        self.applied = False

    def apply(self):
        if self.applied:
            return

        self.removed_nodes = []
        self.removed_referencing = []
        self.deleted_rule_entry = None

        parent = self.target.parent_alt
        rule_deleted = False

        # Primary removals from the target rule (if it's an Alternative)
        if isinstance(parent, Alternative):
            for idx in sorted(self.target.indices_to_remove, reverse=True):
                if 0 <= idx < len(parent.alternatives):
                    node = parent.alternatives[idx]
                    self.removed_nodes.append((idx, node))
                    del parent.alternatives[idx]
            self.removed_nodes.sort(key=lambda x: x[0])

            # If the parent is the grammar RHS and now empty, delete the rule mapping
            rule_node = self.grammar.rules.get(self.target.rule_symbol)
            if rule_node is parent and isinstance(rule_node, Alternative) and len(rule_node.alternatives) == 0:
                self.deleted_rule_entry = (self.target.rule_symbol, rule_node)
                self.grammar.rules.pop(self.target.rule_symbol, None)
                if hasattr(self.grammar, "generators"):
                    self.grammar.generators.pop(self.target.rule_symbol, None)
                rule_deleted = True

        # Single-node RHS case: treat as deleting the whole rule
        else:
            rule_node = self.grammar.rules.get(self.target.rule_symbol)
            node_to_save = rule_node if rule_node is not None else parent
            self.grammar.rules.pop(self.target.rule_symbol, None)
            if hasattr(self.grammar, "generators"):
                self.grammar.generators.pop(self.target.rule_symbol, None)
            self.deleted_rule_entry = (self.target.rule_symbol, node_to_save)
            rule_deleted = True

        # --- Cascade: directly remove referencing alternatives as the finder recorded them ---
        if rule_deleted and self.target.referencing_parents:
            parents_map = {}
            for parent_alt, alt_idx in self.target.referencing_parents:
                parents_map.setdefault(parent_alt, []).append(alt_idx)

            for parent_alt, indices in parents_map.items():
                for idx in sorted(set(indices), reverse=True):
                    # assume index still valid; remove and store for revert
                    if 0 <= idx < len(parent_alt.alternatives):
                        node = parent_alt.alternatives[idx]
                        self.removed_referencing.append((parent_alt, (idx, node)))
                        del parent_alt.alternatives[idx]


        self.applied = True



    def revert(self):
        if not self.applied:
            return

        # Reinsert referencing alternatives first (ascending indices per parent)
        parents_map: Dict[Alternative, List[Tuple[int, Any]]] = {}
        for parent_alt, (idx, node) in self.removed_referencing:
            parents_map.setdefault(parent_alt, []).append((idx, node))

        for parent_alt, items in parents_map.items():
            for idx, node in sorted(items, key=lambda x: x[0]):
                parent_alt.alternatives.insert(idx, node)
        self.removed_referencing = []

        # Reinsert primary removed nodes if parent was an Alternative
        parent = self.target.parent_alt
        if isinstance(parent, Alternative):
            for idx, node in self.removed_nodes:
                parent.alternatives.insert(idx, node)
            self.removed_nodes = []

        # Reinsert deleted rule entry if it was removed
        if self.deleted_rule_entry:
            nt, node = self.deleted_rule_entry
            try:
                self.grammar.rules[nt] = node
            except Exception:
                # best-effort reinsertion; if it fails, we silently continue
                pass
            self.deleted_rule_entry = None

        self.applied = False


class DeleteWrongAltsFinder(MutationFinder):
    """
    Find targets for deleting wrong alternatives.

    This finder handles both:
      - rules represented by Alternative nodes (with .alternatives list)
      - rules represented by a single node (not wrapped in Alternative)
    """
    def __init__(self, grammar, rule_symbol: NonTerminal, grammar_settings):
        super().__init__(grammar, rule_symbol)
        self.grammar_settings = grammar_settings

    def _alt_contains_reference(self, alt_node, target_symbol: NonTerminal) -> bool:
        stack = [alt_node]
        seen = set()

        while stack:
            node = stack.pop()
            if id(node) in seen:
                continue
            seen.add(id(node))

            # Direct match
            if isinstance(node, NonTerminalNode):
                if node.symbol == target_symbol:
                    return True

            # Traverse the AST structure only
            try:
                children = node.children()
            except Exception:
                children = []
            if children:
                stack.extend(children)
        return False


    def _find_references_to_rule(self, rule_symbol: NonTerminal) -> List[Tuple[Alternative, int]]:
        """
        Return list of (parent_alternative_node, alt_index) pairs where the alternative
        contains a NonTerminal referencing rule_symbol.
        """

        refs: List[Tuple[Alternative, int]] = []
        for sym, node in self.grammar.rules.items():
            if not isinstance(node, Alternative):
                # If a rule is not an Alternative, it cannot contain alternatives referencing
                # other rules (it's a single-node rule). We still keep scanning other rules.
                continue
            for alt_idx, alt_child in enumerate(node.alternatives):
                if self._alt_contains_reference(alt_child, rule_symbol):
                    refs.append((node, alt_idx))
        return refs

    def find_targets(self) -> List[DeleteWrongAltsTarget]:
        # retrieve the RHS node for this rule
        try:
            rule_node = self.grammar[self.target_symbol]
        except KeyError:
            return []

        targets: List[DeleteWrongAltsTarget] = []
        # --- CASE A: rule has multiple alternatives ---
        if isinstance(rule_node, Alternative):

            # find mutation alternative index (exclude it)
            mutation_index = None
            for idx, child in enumerate(rule_node.alternatives):
                if isinstance(child, NonTerminalNode):
                    # correct check: use name() or format_as_spec()
                    if child.symbol.name().startswith("<mutation_"):
                        mutation_index = idx
                        break

            removable_indices = [
                idx for idx in range(len(rule_node.alternatives))
                if idx != mutation_index
            ]

            # create targets for removing 1..N alternatives
            for r in range(1, len(removable_indices) + 1):
                for combo in itertools.combinations(removable_indices, r):

                    remaining = len(rule_node.alternatives) - len(combo)
                    if remaining == 0:
                        # rule would be deleted entirely -> find referencing parents
                        refs = self._find_references_to_rule(self.target_symbol)
                    else:
                        refs = None

                    targets.append(
                        DeleteWrongAltsTarget(
                            parent_alt=rule_node,
                            indices_to_remove=combo,
                            rule_symbol=self.target_symbol,
                            referencing_parents=refs,
                            grammar_settings=self.grammar_settings
                        )
                    )

            return targets

        # --- CASE B: rule is single-alt: entire rule is the only alternative ---

        refs = self._find_references_to_rule(self.target_symbol)

        targets.append(
            DeleteWrongAltsTarget(
                parent_alt=rule_node,      # RHS node itself
                indices_to_remove=(0,),    # removing the one implicit alternative
                rule_symbol=self.target_symbol,
                referencing_parents=refs,
                grammar_settings=self.grammar_settings,
            )
        )
        return targets

