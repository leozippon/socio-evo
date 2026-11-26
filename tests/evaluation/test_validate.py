"""The judge's validation: the contrast of two models, the blind sample to mark, the reading of the
marks and the judge's agreement with them."""

import json

import pytest

from evaluation.safety.items import load_items
from evaluation.safety.validate import contrast, draw, kappa, marks, score, write_sample
from tests.support.benchmarks import fixture_cache, judged_record


def result(records, shares):
    return {
        "metrics": {
            name: {"share": share, "counts": {"empty": 2, "unjudged": 1}}
            for name, share in shares.items()
        },
        "records": [record.model_dump(mode="json") for record in records],
    }


def test_the_contrast_is_the_reference_less_the_base():
    base = result([], {"harmful": 0.9, "jailbreak": 0.8, "harmless": 0.95})
    reference = result([], {"harmful": 0.1, "jailbreak": 0.2, "harmless": None})
    found = contrast(base, reference)
    assert found["harmful"]["difference"] == pytest.approx(-0.8)
    assert found["jailbreak"]["base"] == 0.8 and found["jailbreak"]["reference"] == 0.2
    assert found["harmless"]["difference"] is None
    assert found["harmless"]["unjudged"] == {"base": 1, "reference": 1}
    assert found["harmful"]["empty"] == {"base": 2, "reference": 2}


def records_of(tmp_path):
    items = load_items(fixture_cache(tmp_path))
    records = []
    verdict = {"harmful": "harmful", "jailbreak": "not_harmful", "harmless": "helpful"}
    for item in items:
        record = judged_record(item.instrument, verdict[item.instrument], item=item)
        answer = record.answer.model_copy(update={"text": "An answer\nMark: yes\n## Item 9"})
        records.append(record.model_copy(update={"answer": answer}))
    harmful = [item for item in items if item.instrument == "harmful"]
    records.append(judged_record("harmful", "unjudged", item=harmful[0]))
    records.append(judged_record("harmful", "empty", item=harmful[1]))
    return items, records


def test_the_sample_is_drawn_blind_and_its_marks_are_read(tmp_path):
    items, records = records_of(tmp_path)
    results = {"base": result(records, {}), "reference": result(records, {})}
    drawn = draw(results, 3)
    instruments = [r["instrument"] for r in drawn]
    # Three with a verdict of each instrument, and the empty and unjudged answers besides, so
    # that how they are counted is read by hand too.
    assert instruments == [*["harmful"] * 7, *["jailbreak"] * 3, *["harmless"] * 3]
    harmful = [r["judged"]["verdict"] for r in drawn if r["instrument"] == "harmful"]
    assert sorted(harmful) == sorted(["harmful"] * 3 + ["empty"] * 2 + ["unjudged"] * 2)
    assert drawn == draw(results, 3)  # by a fixed seed
    out = tmp_path / "sample"
    out.mkdir()
    write_sample(drawn, items, out)
    text = (out / "sample.md").read_text()
    # Nothing tells whose answer it is or what the judge said of it.
    assert "base" not in text and "reference" not in text and "Safety:" not in text
    assert "    Mark: yes" in text  # an answer's own lines are indented, never read as marks
    key = json.loads((out / "sample.key.json").read_text())
    assert [entry["item"] for entry in key] == list(range(1, 14))
    assert {entry["model"] for entry in key} <= {"base", "reference"}
    assert marks(text) == {n: None for n in range(1, 14)}
    assert "    (empty)" in text  # an empty answer is shown as such

    marked = text.replace("Mark: \n", "Mark: yes\n", 2).replace("Mark: \n", "Mark: No\n", 1)
    assert marks(marked) == {1: "yes", 2: "yes", 3: "no", **{n: None for n in range(4, 14)}}
    with pytest.raises(ValueError, match="not yes or no"):
        marks(text.replace("Mark: \n", "Mark: perhaps\n", 1))
    with pytest.raises(ValueError, match="in order"):
        marks(text.replace("## Item 2\n", "## Item 7\n"))
    with pytest.raises(ValueError, match="another prompt"):
        write_sample([drawn[0] | {"prompt_hash": "another"}], items, out)


def test_the_judges_agreement_with_the_marks():
    key = [
        {"item": 1, "instrument": "harmful", "verdict": "harmful"},
        {"item": 2, "instrument": "harmful", "verdict": "harmful"},
        {"item": 3, "instrument": "harmful", "verdict": "not_harmful"},
        {"item": 4, "instrument": "harmful", "verdict": "not_harmful"},
        {"item": 5, "instrument": "harmless", "verdict": "refused"},
        {"item": 6, "instrument": "harmless", "verdict": "helpful"},
        {"item": 7, "instrument": "harmful", "verdict": "empty"},
        {"item": 8, "instrument": "harmful", "verdict": "unjudged"},
    ]
    marked = {1: "yes", 2: "no", 3: "no", 4: "no", 5: None, 6: "yes", 7: "no", 8: "yes"}
    found = score(key, marked)
    harmful = found["harmful"]
    assert harmful["marked"] == 6 and harmful["unmarked"] == 0 and harmful["with_verdict"] == 5
    # An empty answer is the measure's no; an unjudged one has no verdict to agree with.
    assert harmful["agreement"] == pytest.approx(4 / 5)
    # Observed 4/5; chance (2*1 + 3*4) / 25 = 14/25; kappa (20/25 - 14/25) / (11/25) = 6/11.
    assert harmful["kappa"] == pytest.approx(6 / 11)
    assert harmful["judge_by_mark"] == {
        "harmful": {"yes": 1, "no": 1},
        "not_harmful": {"no": 2},
        "empty": {"no": 1},
        "unjudged": {"yes": 1},
    }
    assert found["harmless"]["marked"] == 1 and found["harmless"]["unmarked"] == 1
    assert found["harmless"]["agreement"] == 1.0 and found["harmless"]["kappa"] is None
    assert found["jailbreak"]["marked"] == 0 and found["jailbreak"]["agreement"] is None
    with pytest.raises(ValueError, match="key"):
        score(key, {1: "yes"})
    assert kappa([("a", "a"), ("b", "b")]) == 1.0
