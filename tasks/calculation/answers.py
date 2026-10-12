"""Reading a numeric answer written in plain text, LaTeX or Unicode, and telling whether two
answers are the same number.

An answer is read as one real number. Before reading, it loses dollar signs, `\\(` `\\)` `\\[`
`\\]`, a `\\boxed{}` around it, a leading `x =` naming the unknown, a trailing full stop,
spacing commands, `\\left` and `\\right`, `\\displaystyle`, text in `\\text{}`, `\\mbox{}` or
`\\mathrm{}` (units), degree and percent signs, and commas grouping thousands. What remains is
read as an expression of whole and decimal numbers, π, square and n-th roots (`\\sqrt{}`,
`\\sqrt[n]{}`, `√`, `sqrt()`), fractions (`\\frac`, `\\dfrac`, `\\tfrac`, `/`), products (`\\cdot`,
`\\times`, `×`, `·`, `*`, or a factor written after another that is not a bare number:
`2\\sqrt{3}`, `3π`, `2(1+√5)`), sums, differences, powers (`^`) and parentheses or braces.
Two numbers written side by side, or a bare number before a fraction (`2\\frac{1}{2}`, which
could be a mixed number), cannot be read. Two answers are the same if both can be read and
their values agree to a relative 1e-12, or an absolute 1e-12 near zero.

A delivery gives its answer on a line after `Answer:`, the last such line counting; or else in
its last `\\boxed{}`; or else as its last line, if that line can be read as one number.
"""

import math
import re

_UNICODE = {"−": "-", "×": "*", "·": "*", "÷": "/", "π": r"\pi ", "√": r"\sqrt "}
_DROPPED = re.compile(
    r"\$|\\[()\[\]]|\\left\b|\\right\b|\\displaystyle|\\[,;:! ]|\\q?quad\b|~"
    r"|\^\s*\{?\s*\\circ\s*\}?|\\circ\b|°|\\?%"
)
_UNITS = ("\\text", "\\mbox", "\\mathrm", "\\textrm", "\\operatorname")
_UNKNOWN = re.compile(r"^\s*[A-Za-z]\s*=(?!=)")
_THOUSANDS = re.compile(r"^-?\d{1,3}(?:,\d{3})+(?:\.\d+)?$")
_TOKEN = re.compile(r"\s*(\d+(?:\.\d*)?|\.\d+|\\[A-Za-z]+|[A-Za-z]+|[-+*/^(){}\[\]])")
_FRACTIONS = {r"\frac", r"\dfrac", r"\tfrac"}
_TIMES = {"*", r"\cdot", r"\times"}
_ANSWER = re.compile(r"answer\s*\**\s*:(.*)", re.IGNORECASE)
_BOXED = "\\boxed"


class _Unreadable(Exception):
    pass


def value(answer: str) -> float | None:
    """The number `answer` writes, or None if it cannot be read as one."""
    text = _cleaned(answer)
    if text is None:
        return None
    tokens = _tokens(text)
    if not tokens:
        return None
    try:
        parser = _Parser(tokens)
        number = parser.expression()
        if parser.position != len(tokens):
            return None
    except (_Unreadable, ArithmeticError, ValueError, TypeError):
        return None
    if isinstance(number, complex) or not math.isfinite(number):
        return None
    return float(number)


def same(answer: str, expected: str) -> bool:
    """Whether `answer` and `expected` are read as the same number."""
    given, wanted = value(answer), value(expected)
    if given is None or wanted is None:
        return False
    return math.isclose(given, wanted, rel_tol=1e-12, abs_tol=1e-12)


def extract(delivery: str) -> str | None:
    """The answer a delivery gives: the rest of its last line after `Answer:`, or else the
    content of its last `\\boxed{}`, or else its last line if that reads as one number; None
    if it gives none of these."""
    marked = _ANSWER.findall(delivery)
    if marked:
        return marked[-1].strip().strip("*").strip()
    start = delivery.rfind(_BOXED + "{")
    if start >= 0:
        return _group(delivery, start + len(_BOXED))
    last = delivery.strip().rsplit("\n", 1)[-1].strip()
    return last if value(last) is not None else None


def _cleaned(answer: str) -> str | None:
    text = answer.strip()
    for unicode, latex in _UNICODE.items():
        text = text.replace(unicode, latex)
    text = _unwrapped(text, _BOXED, keep=True)
    for command in _UNITS:
        text = _unwrapped(text, command, keep=False)
    if text is None:
        return None
    text = _DROPPED.sub(" ", text.replace("{,}", ","))
    text = _UNKNOWN.sub("", text).strip().rstrip(".").strip()
    if _THOUSANDS.match(text):
        text = text.replace(",", "")
    return text


def _unwrapped(text: str | None, command: str, *, keep: bool) -> str | None:
    """`text` with each `command{...}` replaced by its content, or removed; None if a brace
    is not closed."""
    while text is not None and (start := text.find(command + "{")) >= 0:
        content = _group(text, start + len(command))
        if content is None:
            return None
        end = start + len(command) + len(content) + 2
        text = text[:start] + (f" {content} " if keep else " ") + text[end:]
    return text


def _group(text: str, opening: int) -> str | None:
    """The content of the brace group opening at `opening`, or None if it is not closed."""
    depth = 0
    for position in range(opening, len(text)):
        if text[position] == "{":
            depth += 1
        elif text[position] == "}":
            depth -= 1
            if depth == 0:
                return text[opening + 1 : position]
    return None


def _tokens(text: str) -> list[str] | None:
    tokens, position = [], 0
    while position < len(text):
        if text[position:].strip() == "":
            break
        match = _TOKEN.match(text, position)
        if match is None:
            return None
        tokens.append(match[1])
        position = match.end()
    return tokens


def _number(token: str) -> bool:
    return token[0].isdigit() or token[0] == "."


class _Parser:
    """A recursive-descent reader of the tokens of an answer into its value."""

    def __init__(self, tokens: list[str]) -> None:
        self.tokens = tokens
        self.position = 0

    def peek(self) -> str | None:
        return self.tokens[self.position] if self.position < len(self.tokens) else None

    def take(self, expected: str | None = None) -> str:
        token = self.peek()
        if token is None or (expected is not None and token != expected):
            raise _Unreadable(token)
        self.position += 1
        return token

    def expression(self) -> float:
        total = self.term()
        while self.peek() in ("+", "-"):
            total = total + self.term() if self.take() == "+" else total - self.term()
        return total

    def term(self) -> float:
        product = self.unary()
        while True:
            token = self.peek()
            if token in _TIMES or token == "/":
                self.take()
                factor = self.unary()
                product = product * factor if token != "/" else product / factor
            elif token is not None and self.starts_factor(token):
                if _number(self.tokens[self.position - 1]) and token in _FRACTIONS:
                    raise _Unreadable(token)
                product *= self.power()
            else:
                return product

    def starts_factor(self, token: str) -> bool:
        """Whether `token` begins a factor written after another without a sign."""
        return token in ("(", "{", r"\pi", "pi", r"\sqrt", "sqrt") or token in _FRACTIONS

    def unary(self) -> float:
        if self.peek() == "-":
            self.take()
            return -self.unary()
        if self.peek() == "+":
            self.take()
            return self.unary()
        return self.power()

    def power(self) -> float:
        base = self.atom()
        if self.peek() != "^":
            return base
        self.take()
        sign = 1.0
        if self.peek() == "-":
            self.take()
            sign = -1.0
        return base ** (sign * self.atom())

    def atom(self) -> float:
        token = self.take()
        if _number(token):
            return float(token)
        if token in (r"\pi", "pi"):
            return math.pi
        if token in ("(", "{"):
            inner = self.expression()
            self.take(")" if token == "(" else "}")
            return inner
        if token in _FRACTIONS:
            numerator = self.braced()
            return numerator / self.braced()
        if token == r"\sqrt":
            degree = 2.0
            if self.peek() == "[":
                self.take()
                degree = self.expression()
                self.take("]")
            radicand = self.braced() if self.peek() == "{" else self.atom()
            return _root(radicand, degree)
        if token == "sqrt":
            return _root(self.atom(), 2.0)
        raise _Unreadable(token)

    def braced(self) -> float:
        self.take("{")
        inner = self.expression()
        self.take("}")
        return inner


def _root(radicand: float, degree: float) -> float:
    if radicand >= 0:
        return radicand ** (1 / degree)
    if degree.is_integer() and int(degree) % 2:
        return -((-radicand) ** (1 / degree))
    raise ValueError("an even root of a negative number")
