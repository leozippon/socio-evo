import pytest

from tasks.calculation.answers import extract, same, value

SAME = [
    ("\\frac{1}{2}", "0.5"),
    ("1/2", "\\dfrac{1}{2}"),
    ("-\\frac{1}{3}", "-1/3"),
    ("2\\sqrt{3}", "\\sqrt{12}"),
    ("2√3", "2 \\sqrt 3"),
    ("\\frac{3\\pi}{4}", "3π/4"),
    ("\\frac{1+\\sqrt{5}}{2}", "(1+sqrt(5))/2"),
    ("\\sqrt[3]{-8}", "-2"),
    ("1.5 \\times 10^{3}", "1500"),
    ("\\left(\\frac{1}{2}\\right)^{2}", "2^{-2}"),
    ("x = 5", "5."),
    ("$\\boxed{5}$", "5"),
    ("1,000", "1{,}000"),
    ("1000", "1,000"),
    ("60^{\\circ}", "60°"),
    ("20\\%", "20"),
    ("12 \\text{ cm}", "12"),
]
DIFFERENT = [("1/3", "0.333"), ("\\sqrt{2}", "1.4142"), ("5", "-5"), ("2", "3")]
UNREADABLE = [
    "2:1",
    "(1, 2)",
    "2, 3",
    "2 \\text{ or } 3",
    "2\\frac{1}{2}",
    "2 3",
    "n+1",
    "e",
    "\\sqrt{-1}",
    "1/0",
    "12 cm",
    "\\text{A}",
    "",
]


@pytest.mark.parametrize(("answer", "expected"), SAME)
def test_the_same_number_written_in_other_forms_is_the_same_answer(answer, expected):
    assert same(answer, expected) and same(expected, answer)


@pytest.mark.parametrize(("answer", "expected"), DIFFERENT)
def test_a_different_number_or_an_approximation_is_another_answer(answer, expected):
    assert not same(answer, expected)


@pytest.mark.parametrize("answer", UNREADABLE)
def test_what_is_not_one_number_cannot_be_read_and_matches_nothing(answer):
    assert value(answer) is None
    assert not same(answer, answer)


def test_the_answer_is_on_the_last_line_marked_as_such_or_else_in_the_last_box():
    assert extract("Answer: 3\nOn second thought, 4.\n**Answer:** $4$") == "$4$"
    assert extract("so \\boxed{\\frac{1}{2}} or rather \\boxed{\\frac{1}{3}}.") == "\\frac{1}{3}"
    assert extract("I am fairly sure it is 7.") is None
    assert extract("Adding up, 10 + 8 = 18.\n\n18\n") == "18"
    assert extract("Adding up:\n10 + 8 = 18") is None
