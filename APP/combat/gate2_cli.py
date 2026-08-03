from __future__ import annotations

import argparse
import json
from pathlib import Path

from .gate2_engine import Gate2Engine
from .gate2_runtime_models import ActionIntent, CandidateKind, ReactionDecision
from .gate2_scripted import execute_script, load_script, write_script_outputs


def _print_state(engine: Gate2Engine) -> None:
    print(f"Round {engine.state.round_number} | active: {engine.state.current_actor_id} | version {engine.state.state_version}")
    for actor in sorted(engine.state.actors.values(), key=lambda row: row.entity_id):
        print(
            f"  {actor.display_name:12} {'ACTIVE' if actor.active else 'OUT':6} "
            f"HP {actor.current_hp}/{actor.maximum_hp} temp {actor.temporary_hp} "
            f"pos ({actor.position.x},{actor.position.y}) move {actor.movement_remaining_ft} "
            f"resources {actor.resources}"
        )


def _interactive(root: Path, seed: str, output: Path) -> int:
    engine = Gate2Engine(root, match_seed=seed)
    while engine.state.terminal_result is None:
        _print_state(engine)
        candidates = engine.legal_candidates()
        for index, candidate in enumerate(candidates):
            target = ",".join(candidate.target_ids) or "-"
            dest = f"({candidate.destination.x},{candidate.destination.y})" if candidate.destination else "-"
            print(f"[{index}] {candidate.kind.value} {candidate.display_name} target={target} dest={dest} options={list(candidate.option_ids)}")
        raw = input("choose index, 'state', or 'quit': ").strip()
        if raw == "quit":
            return 1
        if raw == "state":
            continue
        candidate = candidates[int(raw)]
        selected_options: tuple[str, ...] = ()
        if candidate.option_ids:
            raw_options = input(f"option IDs (comma-separated, offered={list(candidate.option_ids)}, blank=none): ").strip()
            selected_options = tuple(part.strip() for part in raw_options.split(",") if part.strip())
        reaction_decisions: list[ReactionDecision] = []
        # The CLI keeps reactions explicit and bounded. The operator may add exact
        # reaction decisions before committing the selected engine candidate.
        while input("add reaction decision? [y/N]: ").strip().lower() == "y":
            checkpoint = input("checkpoint: ").strip()
            reactor = input("reactor entity ID: ").strip()
            source = input("reaction source ID: ").strip()
            selection = input("USE or DECLINE: ").strip().upper()
            spend = int(input("spend (0 if none): ").strip() or "0")
            options = tuple(part.strip() for part in input("reaction option IDs (comma-separated): ").split(",") if part.strip())
            reaction_decisions.append(ReactionDecision(checkpoint=checkpoint, reactor_id=reactor, reaction_source_id=source, selection=selection, spend=spend, option_ids=options))
        intent = ActionIntent(
            intent_id=f"intent:manual:{engine.state.event_sequence + 1}",
            decision_id=candidate.decision_id,
            candidate_id=candidate.candidate_id,
            state_version=candidate.state_version,
            actor_id=candidate.actor_id,
            target_ids=candidate.target_ids,
            destination=candidate.destination,
            option_ids=selected_options,
            reaction_decisions=tuple(reaction_decisions),
        )
        engine.execute_intent(intent)
    output.mkdir(parents=True, exist_ok=True)
    export = engine.export()
    (output / "Gate2_Manual_Final_State.json").write_text(json.dumps(export.final_state, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    (output / "Gate2_Manual_Final_Event_Log.json").write_text(json.dumps({"events":[e.model_dump(mode="json") for e in export.events]}, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    print(engine.state.terminal_result.model_dump_json())
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Tianxia Factory Gate 2 manual deterministic fight driver")
    parser.add_argument("--source-root", type=Path, default=Path.cwd())
    parser.add_argument("--seed", default="TIANXIA-GATE2-MANUAL-0001")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--script", type=Path)
    args = parser.parse_args()
    if args.script:
        script = load_script(args.script)
        engine, decisions = execute_script(args.source_root, script)
        write_script_outputs(args.output, script, engine, decisions)
        print(json.dumps(engine.state.terminal_result.model_dump(mode="json"), sort_keys=True))
        return 0
    return _interactive(args.source_root, args.seed, args.output)


if __name__ == "__main__":
    raise SystemExit(main())
