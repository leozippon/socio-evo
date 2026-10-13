"""Whether a solution writes out the examples of its checks instead of working for any input."""

import ast
import re
from collections.abc import Iterable, Iterator, Sequence

from tasks.coding.sandbox import Check

EXAMPLES = re.compile(r"Example \d+:.*?(?=Example \d+:|Constraints:|$)", re.DOTALL)
"""An example of a statement, up to the next one or the constraints, as LiveCodeBench writes
them."""


def special_cases(solution: str, checks: Sequence[Check], statement: str) -> list[str]:
    """The distinctive values of the examples of `checks` that `solution` writes out as special
    cases, as sorted reprs; empty if it writes none or does not parse.

    Code that special-cases an example tests for its input or answers with its expected value.
    So an argument of a check's call counts where the code compares something with it, lists
    it after `in` or keys a table by it; an expected value counts where the code returns it or
    a table holds it, unless the task's `statement` names it outside its examples, as a game
    names its players. Neither counts within a call of the function under check, as in a
    self-test. Each counts whole, lists and tuples alike, since a value found only within one,
    such as a keyword or a modulus the task prescribes, is one that working code writes too. A
    value is distinctive if it is a string or container of at least two items or a number of
    magnitude 100 or more; an example with no distinctive value, or a value the code keeps in
    a variable before it compares with or returns it, is not seen.
    """
    try:
        tree = ast.parse(solution)
    except SyntaxError:
        return []
    calls = [ast.parse(check.call, mode="eval").body for check in checks]
    checked = {call.func.id for call in calls}
    code = list(_code(tree, checked))
    tested = _written([part for node in code for part in _tested(node)], checked)
    given = _written([part for node in code for part in _given(node)], checked)
    inputs = _values(argument for call in calls for argument in call.args)
    outputs = _values(
        ast.parse(check.expected, mode="eval").body for check in checks if check.expected
    )
    prose = EXAMPLES.sub("", statement)
    found = [value for value in inputs if _keyed(value) in tested] + [
        value for value in outputs if _keyed(value) in given and not _named(value, prose)
    ]
    return sorted({repr(value) for value in found})


def _code(node: ast.AST, checked: set[str]) -> Iterator[ast.AST]:
    """`node` and the nodes within it, but for the calls of the functions `checked`."""
    nodes = [node]
    while nodes:
        node = nodes.pop()
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in checked
        ):
            yield node
            nodes.extend(ast.iter_child_nodes(node))


def _tested(node: ast.AST) -> Iterator[ast.expr]:
    """What `node` tests something for: the operands of an equality, the items written out
    after `in` and the keys of a table."""
    if isinstance(node, ast.Compare):
        operands = [node.left, *node.comparators]
        for op, left, right in zip(node.ops, operands, operands[1:], strict=False):
            if isinstance(op, ast.Eq | ast.NotEq):
                yield from (left, right)
            elif isinstance(op, ast.In | ast.NotIn) and isinstance(
                right, ast.List | ast.Tuple | ast.Set
            ):
                yield from right.elts
    elif isinstance(node, ast.Dict):
        yield from (key for key in node.keys if key is not None)


def _given(node: ast.AST) -> Iterator[ast.expr]:
    """What `node` gives as an answer: the value it returns or the values of a table."""
    if isinstance(node, ast.Return) and node.value is not None:
        yield node.value
    elif isinstance(node, ast.Dict):
        yield from node.values


def _written(parts: list[ast.expr], checked: set[str]) -> list[object]:
    """The distinctive values written within `parts`, lists as tuples."""
    return [_keyed(value) for value in _values(n for part in parts for n in _code(part, checked))]


def _values(nodes: Iterable[ast.AST]) -> list[object]:
    values = []
    for node in nodes:
        if isinstance(node, ast.Constant | ast.UnaryOp | ast.List | ast.Tuple | ast.Set | ast.Dict):
            try:
                value = ast.literal_eval(node)
            except (ValueError, TypeError):
                continue
            if _distinctive(value):
                values.append(value)
    return values


def _keyed(value: object) -> object:
    """`value` with every list a tuple, as a table keyed by an input that is a list writes it."""
    if isinstance(value, list | tuple):
        return tuple(_keyed(item) for item in value)
    return value


def _named(value: object, prose: str) -> bool:
    """Whether `prose` writes `value`, a container with any spacing and either quotes."""
    if isinstance(value, str | int | float):
        return re.search(rf"(?<!\w){re.escape(str(value))}(?!\w)", prose) is not None
    return _flat(repr(value)) in _flat(prose)


def _flat(text: str) -> str:
    return re.sub(r"\s", "", text).replace("'", '"')


def _distinctive(value: object) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int | float | complex):
        return abs(value) >= 100
    return isinstance(value, str | bytes | tuple | list | set | dict) and len(value) >= 2
