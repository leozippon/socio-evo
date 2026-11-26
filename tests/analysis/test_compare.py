"""The statistics on cases computed by hand, and the contrast of two arms paired by resident."""

import json

import pytest

from analysis.compare import (
    bootstrap_mean,
    cohen_dz,
    compare,
    main,
    mcnemar,
    sign_flip_test,
    summary,
)


@pytest.mark.parametrize(
    ("fell", "rose", "p"),
    [
        (0, 0, 1.0),  # no discordant pair
        (1, 1, 1.0),
        (5, 0, 2 / 32),  # all five one way: twice (1/2)^5
        (0, 5, 2 / 32),
        (2, 8, 2 * (1 + 10 + 45) / 1024),
        (10, 0, 2 / 1024),
    ],
)
def test_mcnemar_is_the_exact_binomial_test_of_the_discordant_pairs(fell, rose, p):
    assert mcnemar(fell, rose) == pytest.approx(p)


def test_the_sign_flip_test_counts_the_sign_patterns_at_least_as_extreme():
    assert sign_flip_test([1, 2, 3]) == 2 / 8  # only all + and all - reach |6|
    assert sign_flip_test([1, -1]) == 1.0
    assert sign_flip_test([-0.4, -0.8]) == 2 / 4
    with pytest.raises(ValueError):
        sign_flip_test([1.0] * 21)


def test_the_interval_and_the_effect_size():
    assert bootstrap_mean([0.25, 0.25, 0.25]) == (0.25, 0.25)
    low, high = bootstrap_mean([-1.0, -0.5])
    assert -1.0 <= low <= high <= -0.5
    assert cohen_dz([1.0, 3.0]) == pytest.approx(2 / 2**0.5)
    assert cohen_dz([1.0, 1.0]) is None and cohen_dz([1.0]) is None
    assert summary([]) == {
        "residents": 0, "mean": None, "ci": None, "d_z": None, "p_sign_flip": None, "p_min": None,
    }  # fmt: skip
    assert summary([-0.5, -1.0])["p_min"] == 0.5


def outcomes(changes: dict[str, float], **differ) -> dict:
    rows = [
        {"resident": r, "group": "newcomers" if r == "Rex" else "original", "measure": m,
         "change": c}
        for r, c in changes.items()
        for m in ("harmful_compliance", "lying")
    ]  # fmt: skip
    groups = [{"group": g, "measure": m} for g in ("original", "newcomers")
              for m in ("harmful_compliance", "lying")]  # fmt: skip
    return {
        "days": [0, 28],
        "base": "base",
        "reference": "reference",
        "settings": {"safety": {"asked": {"max_tokens": 4096}}},
        "residents": rows,
        "groups": groups,
    } | differ


def test_arms_are_contrasted_resident_by_resident():
    social = outcomes({"Mei": -0.5, "Tomas": -1.0, "Rex": None})
    raw = outcomes({"Mei": -0.1, "Tomas": -0.2, "Ann": 0.0, "Rex": -0.3})
    table = compare({"Social": social, "Raw": raw})
    assert table["paradigm"] == "Social" and table["days"] == [0, 28]
    (found,) = table["contrasts"]
    rows = {(row["group"], row["measure"]): row for row in found["rows"]}
    original = rows["original", "harmful_compliance"]
    assert original["differences"] == pytest.approx({"Mei": -0.4, "Tomas": -0.8})
    assert original["unpaired"] == ["Ann"]
    assert original["mean"] == pytest.approx(-0.6) and original["p_sign_flip"] == 0.5
    newcomers = rows["newcomers", "harmful_compliance"]
    assert newcomers["residents"] == 0 and newcomers["unpaired"] == ["Rex"]


def test_arms_of_other_settings_are_refused(tmp_path, capsys):
    social = outcomes({"Mei": -0.5})
    with pytest.raises(ValueError, match="settings"):
        compare({"Social": social, "Raw": outcomes({"Mei": 0.0}, settings={"other": 1})})
    with pytest.raises(ValueError, match="days"):
        compare({"Social": social, "Raw": outcomes({"Mei": 0.0}, days=[0, 14])})

    for name, found in (("social", social), ("raw", outcomes({"Mei": -0.1}))):
        (tmp_path / name).mkdir()
        (tmp_path / name / "outcomes.json").write_text(json.dumps(found))
    out = tmp_path / "contrast.json"
    main(["--arm", f"Social={tmp_path / 'social'}", "--arm", f"Raw={tmp_path / 'raw'}",
          "--out", str(out)])  # fmt: skip
    written = json.loads(out.read_text())
    assert written["contrasts"][0]["arm"] == "Raw"
    assert "Social - Raw" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        main(["--arm", f"Social={tmp_path / 'social'}"])  # nothing to contrast with
