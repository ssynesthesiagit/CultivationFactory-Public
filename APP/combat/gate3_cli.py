from __future__ import annotations

import argparse
import json
from pathlib import Path

from .gate2_runtime_models import ActionIntent, ReactionDecision
from .gate3_scripted import execute_persistent_script
from .gate3_storage import Gate3Persistence


def _print_state(session) -> None:
    state = session.engine.state
    print(
        f"Match {state.match_id} | round {state.round_number} | actor {state.current_actor_id} "
        f"| version {state.state_version} | terminal={state.terminal_result is not None}"
    )
    for actor in sorted(state.actors.values(), key=lambda row: row.entity_id):
        print(
            f"  {actor.display_name:12} {'ACTIVE' if actor.active else 'OUT':6} "
            f"HP {actor.current_hp}/{actor.maximum_hp} temp {actor.temporary_hp} "
            f"pos ({actor.position.x},{actor.position.y}) move {actor.movement_remaining_ft}"
        )


def _interactive(session) -> int:
    while session.engine.state.terminal_result is None:
        _print_state(session)
        candidates = session.engine.legal_candidates()
        for index, candidate in enumerate(candidates):
            print(
                f"[{index}] {candidate.kind.value} {candidate.display_name} "
                f"targets={list(candidate.target_ids)} options={list(candidate.option_ids)}"
            )
        raw = input("choose index, 'snapshot', 'verify', 'state', or 'quit': ").strip()
        if raw == "quit":
            return 1
        if raw == "state":
            continue
        if raw == "snapshot":
            print(session.explicit_snapshot())
            continue
        if raw == "verify":
            print(json.dumps(session.verify(), indent=2, sort_keys=True))
            continue
        candidate = candidates[int(raw)]
        selected_options: tuple[str, ...] = ()
        if candidate.option_ids:
            selected_options = tuple(
                item.strip()
                for item in input(
                    f"option IDs (offered={list(candidate.option_ids)}): "
                ).split(",")
                if item.strip()
            )
        reactions: list[ReactionDecision] = []
        while input("add reaction decision? [y/N]: ").strip().lower() == "y":
            reactions.append(
                ReactionDecision(
                    checkpoint=input("checkpoint: ").strip(),
                    reactor_id=input("reactor entity ID: ").strip(),
                    reaction_source_id=input("reaction source ID: ").strip(),
                    selection=input("USE or DECLINE: ").strip().upper(),
                    spend=int(input("spend: ").strip() or "0"),
                    option_ids=tuple(
                        item.strip()
                        for item in input("reaction option IDs: ").split(",")
                        if item.strip()
                    ),
                )
            )
        intent = ActionIntent(
            intent_id=f"intent:manual:{session.engine.state.event_sequence + 1}",
            decision_id=candidate.decision_id,
            candidate_id=candidate.candidate_id,
            state_version=candidate.state_version,
            actor_id=candidate.actor_id,
            target_ids=candidate.target_ids,
            destination=candidate.destination,
            option_ids=selected_options,
            reaction_decisions=tuple(reactions),
        )
        session.execute_intent(intent)
    _print_state(session)
    print(json.dumps(session.engine.state.terminal_result.model_dump(mode="json"), sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Tianxia Factory Gate 3 persistent combat CLI"
    )
    parser.add_argument("--source-root", type=Path, default=Path.cwd())
    sub = parser.add_subparsers(dest="command", required=True)

    new = sub.add_parser("new-persistent")
    new.add_argument("--userdata", type=Path, required=True)
    new.add_argument("--seed", required=True)
    new.add_argument("--maximum-rounds", type=int, default=20)
    new.add_argument("--script", type=Path)

    for name in ("resume", "status", "verify", "replay", "snapshot", "export"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--userdata", type=Path, required=True)
        cmd.add_argument("--match-id", required=True)

    listing = sub.add_parser("list-matches")
    listing.add_argument("--userdata", type=Path, required=True)

    args = parser.parse_args()
    persistence = Gate3Persistence(args.source_root, args.userdata)

    if args.command == "new-persistent":
        if args.script:
            session, decisions = execute_persistent_script(
                args.source_root, args.userdata, args.script
            )
            result = {
                "match_id": session.match_id,
                "decision_count": len(decisions),
                "terminal_result": session.engine.state.terminal_result.model_dump(
                    mode="json"
                ),
                "verify": session.verify(),
                "exports": session.export(),
            }
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0
        session = persistence.create_match(
            match_seed=args.seed, maximum_rounds=args.maximum_rounds
        )
        print(session.match_id)
        return _interactive(session)

    if args.command == "list-matches":
        print(json.dumps(persistence.list_matches(), indent=2, sort_keys=True))
        return 0

    session = persistence.load_match(args.match_id)
    if args.command == "resume":
        return _interactive(session)
    if args.command == "status":
        _print_state(session)
        return 0
    if args.command == "verify":
        print(json.dumps(session.verify(), indent=2, sort_keys=True))
        return 0
    if args.command == "replay":
        print(json.dumps(session.replay(), indent=2, sort_keys=True))
        return 0
    if args.command == "snapshot":
        print(session.explicit_snapshot())
        return 0
    if args.command == "export":
        print(json.dumps(session.export(), indent=2, sort_keys=True))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
