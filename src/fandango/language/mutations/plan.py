from typing import List
from mutations.base import GrammarMutator

class MutationPlan:
    def __init__(self, mutators: List[GrammarMutator] = None):
        self.mutators: List[GrammarMutator] = mutators or []

    def add(self, mutator: GrammarMutator):
        self.mutators.append(mutator)

    def apply_all(self):
        for m in self.mutators:
            m.apply()

    def revert_all(self):
        for m in reversed(self.mutators):
            m.revert()
