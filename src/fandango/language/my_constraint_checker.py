from fandango.constraints.constraint import Constraint
from fandango.language.tree import DerivationTree
from typing import List, Dict, Any


def evaluate_constraints(tree: DerivationTree, constraints: List[Constraint]) -> List[Dict[str, Any]]:
    """
    Evaluate each constraint on the given parse tree and return detailed results.

    :param tree: The parse tree produced by grammar.parse(input)
    :param constraints: A list of constraints parsed from .fan file
    :return: A list of dictionaries, one per constraint evaluation result
    """
    results = []

    for i, constraint in enumerate(constraints):
        try:
            fitness = constraint.fitness(tree)
        except Exception as e:
            results.append({
                "index": i,
                "constraint": str(constraint),
                "status": "error",
                "error": str(e),
                "solved": 0,
                "total": 0,
                "success": False,
                "failing_trees": [],
            })
            continue

        constraint_result = {
            "index": i,
            "constraint": str(constraint),
            "status": "passed" if fitness.success else "failed",
            "solved": fitness.solved,
            "total": fitness.total,
            "success": fitness.success,
            "failing_trees": []
        }

        for ft in fitness.failing_trees:
            tree_info = {
                "tree": str(ft.tree),
                "suggestions": []
            }
            if hasattr(ft, "suggestions") and ft.suggestions:
                tree_info["suggestions"] = [
                    {
                        "operator": op.value,
                        "value": val,
                        "side": side.value
                    }
                    for op, val, side in ft.suggestions
                ]
            constraint_result["failing_trees"].append(tree_info)

        results.append(constraint_result)

    return results
