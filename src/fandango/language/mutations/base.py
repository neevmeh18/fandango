from abc import ABC, abstractmethod

class GrammarMutator(ABC):
    @abstractmethod
    def apply(self):
        pass

    @abstractmethod
    def revert(self):
        pass

    def describe(self) -> str:
        return self.__class__.__name__


class MutationTarget:
    def create_mutator(self, grammar) -> GrammarMutator:
        raise NotImplementedError()


class MutationFinder(ABC):
    def __init__(self, grammar, target_symbol):
        self.grammar = grammar
        self.target_symbol = target_symbol

    @abstractmethod
    def find_targets(self):
        pass