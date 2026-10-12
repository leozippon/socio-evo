import hashlib
import json
from collections import Counter

import pytest

from infrastructure.llm.structured import TRUNCATED
from tasks import bank
from tasks.bank import Difficulty, Entry, Result, Sample, Trade, measured_difficulty, town


def result(*attempts: tuple[bool, float], cut_off: int = 0) -> Result:
    samples = [
        Sample(visible=visible, quality=quality, special_cased=False)
        for visible, quality in attempts
    ]
    return Result(
        bank="pool",
        samples=samples,
        errors=(f"StructuredOutputError: last error: {TRUNCATED}",) * cut_off,
    )


def test_difficulty_follows_the_first_attempts_and_the_label_only_among_solved_tasks():
    perfect, defective, failed = (True, 1.0), (True, 0.9), (False, 0.0)
    cases = [
        (result(perfect, perfect, perfect), Difficulty.EASY, Difficulty.EASY),
        (result(perfect, perfect, perfect), Difficulty.HARD, Difficulty.MEDIUM),
        (result(perfect, defective, perfect), Difficulty.EASY, Difficulty.MEDIUM),
        (result(perfect, failed, perfect), Difficulty.EASY, Difficulty.HARD),
        (result(perfect, perfect, cut_off=1), Difficulty.EASY, Difficulty.EASY),
        (result(failed, failed, cut_off=1), Difficulty.EASY, Difficulty.UNSOLVED),
    ]
    for measured, label, difficulty in cases:
        assert measured_difficulty(measured, label) is difficulty
    once = {"once": result(perfect), "twice": result(perfect, perfect)}
    labels = {"once": Difficulty.EASY, "twice": Difficulty.HARD, "never": Difficulty.EASY}
    assert bank.measured(labels, once) == {"twice": Difficulty.MEDIUM}


def test_the_town_takes_the_pool_in_the_mix_with_every_unsolved_task_in_the_hard_tier():
    counts = {Difficulty.EASY: 9, Difficulty.MEDIUM: 5, Difficulty.HARD: 7, Difficulty.UNSOLVED: 4}
    pool = {
        f"{difficulty}-{n}": ({}, Entry(difficulty=difficulty, measured=True))
        for difficulty, count in counts.items()
        for n in range(count)
    }
    chosen = town(pool)
    assert Counter(entry.difficulty for _, entry in chosen.values()) == {
        Difficulty.EASY: 5,
        Difficulty.MEDIUM: 5,
        Difficulty.UNSOLVED: 4,
        Difficulty.HARD: 1,
    }
    assert town(dict(reversed(pool.items()))) == chosen
    unsolved_only = {name: item for name, item in pool.items() if not name.startswith("hard")}
    assert Counter(e.difficulty for _, e in town(unsolved_only).values())[Difficulty.UNSOLVED] == 4
    with pytest.raises(ValueError, match="no hard task"):
        town({name: item for name, item in unsolved_only.items() if "unsolved" not in name})


def test_an_index_records_its_trade_and_one_written_before_trades_is_programming(tmp_path):
    (tmp_path / bank.INDEX).write_text(json.dumps({"tasks": {}}), encoding="utf-8")
    assert bank.trade_of(tmp_path) is Trade.PROGRAMMING
    (tmp_path / bank.INDEX).write_text(json.dumps({"trade": "queries", "tasks": {}}))
    assert bank.trade_of(tmp_path) is Trade.QUERIES
    (tmp_path / bank.INDEX).write_text(json.dumps({"trade": "poetry", "tasks": {}}))
    with pytest.raises(ValueError):
        bank.trade_of(tmp_path)


def test_a_download_that_does_not_match_its_pinned_digest_leaves_nothing(tmp_path, monkeypatch):
    served = tmp_path / "mirror" / "datasets" / "org" / "set" / "resolve" / "rev" / "data"
    served.mkdir(parents=True)
    (served / "rows.jsonl").write_bytes(b'{"a": 1}\n')
    monkeypatch.setenv("HF_ENDPOINT", (tmp_path / "mirror").as_uri())
    monkeypatch.delenv("HF_TOKEN", raising=False)
    digest = hashlib.sha256(b'{"a": 1}\n').hexdigest()
    raw = tmp_path / "raw"
    with pytest.raises(ValueError, match="not the pinned"):
        bank.download(raw, "org/set", "rev", {"data/rows.jsonl": "0" * 64})
    assert list(raw.iterdir()) == []
    bank.download(raw, "org/set", "rev", {"data/rows.jsonl": digest})
    assert (raw / "rows.jsonl").read_bytes() == b'{"a": 1}\n'
