"""Evaluate one resident on the fixed MASK scenarios.

    python -m evaluation.mask AGENT_DIR_OR_PERSONA_FILE --out OUT.json --model MODEL.yaml
        [--reasoning EFFORT] [--judge JUDGE.yaml] [--scenario ID ...]

The resident is an exported agent directory (its `background.md` and the files under `memory/`)
or a persona file; MODEL is the LLMConfig of its model, which it answers at the reasoning effort
EFFORT (by default the server's), and JUDGE that of the judge (by default
`evaluation/judge.yaml`). `--scenario` limits the run to the
scenarios named, which must be among the fixed twenty. OUT receives the configurations, the
time taken, the token use, the count and share of each outcome, and every prompt, reply and
verdict; every model call is recorded next to it, the resident's in OUT.resident.jsonl and the
judge's in OUT.judge.jsonl. None of these files may exist already.
"""

import argparse
import asyncio
import json
import time
from collections.abc import Sequence
from pathlib import Path

from evaluation.judge import CONFIG as JUDGE_CONFIG
from evaluation.judge import Judge
from evaluation.mask.dataset import load_scenarios
from evaluation.mask.run import evaluate_mask, load_persona
from infrastructure.config import load_config
from infrastructure.llm import LLMConfig, RecordingClient, create_client
from infrastructure.storage import read_jsonl


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m evaluation.mask", description=__doc__.split("\n\n")[0]
    )
    parser.add_argument("resident", type=Path, help="agent directory or persona file")
    parser.add_argument("--out", type=Path, required=True, help="result JSON to write")
    parser.add_argument("--model", type=Path, required=True, help="resident model LLMConfig YAML")
    parser.add_argument("--reasoning", help="reasoning effort of the resident's model")
    parser.add_argument("--judge", type=Path, default=JUDGE_CONFIG, help="judge LLMConfig YAML")
    parser.add_argument("--scenario", action="append", default=[], help="scenario id (repeatable)")
    args = parser.parse_args(argv)

    out: Path = args.out
    logs = {name: out.with_name(f"{out.stem}.{name}.jsonl") for name in ("resident", "judge")}
    if existing := [str(path) for path in (out, *logs.values()) if path.exists()]:
        parser.error(f"would overwrite {', '.join(existing)}")
    persona = load_persona(args.resident)
    scenarios = load_scenarios(args.scenario)
    model = load_config(args.model, LLMConfig)
    judge_config = load_config(args.judge, LLMConfig)
    out.parent.mkdir(parents=True, exist_ok=True)
    client = RecordingClient(create_client(model), logs["resident"])
    judge = Judge(create_client(judge_config), logs["judge"])

    started = time.perf_counter()
    result = asyncio.run(evaluate_mask(persona, client, judge, scenarios, reasoning=args.reasoning))
    report = {
        "resident": str(args.resident),
        "model": model.model_dump(mode="json"),
        "reasoning": args.reasoning,
        "judge": judge_config.model_dump(mode="json"),
        "seconds": round(time.perf_counter() - started, 1),
        "usage": {name: usage(path) for name, path in logs.items()},
        **result.model_dump(mode="json"),
    }
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    shares = ", ".join(f"{name} {share:.2f}" for name, share in result.shares.items())
    print(f"{len(result.scenarios)} scenarios: {shares}; written to {out}")


def usage(log: Path) -> dict[str, int]:
    """The calls recorded in `log` and the tokens they used, as far as the backend reported."""
    records = list(read_jsonl(log)) if log.exists() else []
    tokens = [r["response"]["usage"] for r in records if r["response"] and r["response"]["usage"]]
    return {
        "calls": len(records),
        "prompt_tokens": sum(t["prompt_tokens"] for t in tokens),
        "completion_tokens": sum(t["completion_tokens"] for t in tokens),
    }


if __name__ == "__main__":
    main()
