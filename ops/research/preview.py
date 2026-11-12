"""Export exact initial prompts and tool schemas without models, Docker or a running town.

python -m ops.research.preview --output docs/research-preview
All temporary agent files and world state are removed on exit.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from dataclasses import asdict
from pathlib import Path

from agent.directory import AgentDirectory
from agent.files import SPECS
from agent.runtime import COMPACT
from experiments.config import load_experiment
from simulation.config import PROJECT_ROOT
from world.clock import ManualClock
from world.events import Idle, Work
from world.research import NoTasks
from world.world import World


def export(output: Path) -> None:
    config = load_experiment(PROJECT_ROOT / "experiments/configs/research.yaml")
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="research-preview-") as directory:
        root = Path(directory)
        for resident in config.residents:
            AgentDirectory.create(
                root / "agents" / resident.name, background=resident.background_path.read_text()
            )
        world = World(config.town, root, NoTasks(), clock=ManualClock())
        world.research.initialize(world)
        index = [
            "# Research prompt preview",
            "",
            "Generated from the initial research configuration, without running an experiment.",
            "",
            "## Exact initial system prompts",
            "",
        ]
        index += [f"- [{r.name}]({r.name}.system.md)" for r in world.residents.values()]
        index += [
            "",
            "## Shared material",
            "",
            "- [Common commission](commission.txt)",
            "- [Research help](research-help.txt)",
            "- [Tools by resident and location](tools.md)",
            "- [Exact tool schemas](tools.json)",
            "",
        ]
        (output / "README.md").write_text("\n".join(index))
        for r in world.residents.values():
            prompt = AgentDirectory(r.agent_dir).system_prompt(r.port.rules())
            (output / f"{r.name}.system.md").write_text(prompt)
        (output / "commission.txt").write_text(world.residents["Mei"].port.held[0].text + "\n")
        (output / "research-help.txt").write_text(world.rules.help("research") + "\n")
        cases = {}
        world.clock.set(world.forced_wake)
        for r in world.residents.values():
            cases[r.name] = {}
            for label, place, event in (
                ("awake_at_home", r.home, Idle()),
                ("idle_at_office", config.town.workplace("office").id, Idle()),
                ("working_at_office", config.town.workplace("office").id, Work()),
                ("own_workplace", r.occupation.workplace, Idle()),
            ):
                r.place, r.base = place, event
                cases[r.name][label] = [asdict(s) for s in (*SPECS, COMPACT, *r.port.tool_specs())]
        declarations, availability = {}, {}
        for name, scenes in cases.items():
            availability[name] = {}
            for scene, specs in scenes.items():
                keys = []
                for s in specs:
                    key = s["name"]
                    if key in declarations and declarations[key] != s:
                        key += "__" + name
                    declarations[key] = s
                    keys.append(key)
                availability[name][scene] = keys
        (output / "tools.json").write_text(
            json.dumps(
                {"declarations": declarations, "availability": availability},
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        )
        rows = [
            "# Resident tool availability",
            "",
            "Generated from actual runtime tool declarations. All cases are awake; "
            "no phone has been bought. Private files and compact remain available. "
            "Movement, sleep, illness, possessions and conversations change availability.",
            "",
        ]
        for name, scenes in cases.items():
            rows += [f"## {name}", ""]
            for scene, specs in scenes.items():
                rows += [f"**{scene}**", "", ", ".join(f"`{s['name']}`" for s in specs), ""]
        (output / "tools.md").write_text("\n".join(rows))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    export(parser.parse_args().output)
