from __future__ import annotations

import argparse
import json
from pathlib import Path

from .canonical import canonical_sha256
from .gate4_context import build_decision_context
from .gate4_controller import LocalDeterministicController
from .gate4_persistence import Gate4Persistence
from .gate4_policy import PolicyLibrary
from .gate4_runner import Gate4AutonomousRunner


def _result(session, decisions=None):
    return {
        "schema": "TianxiaGate4CLIResult.v1",
        "match_id": session.match_id,
        "decision_count": len(decisions or ()),
        "terminal_result": (
            session.engine.state.terminal_result.model_dump(mode="json")
            if session.engine.state.terminal_result is not None
            else None
        ),
        "verify": session.verify(),
        "controller_decisions_sha256": (
            canonical_sha256(decisions) if decisions is not None else None
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Tianxia Factory Gate 4 modular local-controller CLI"
    )
    parser.add_argument("--source-root", type=Path, default=Path.cwd())
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("autonomous-run")
    run.add_argument("--userdata", type=Path, required=True)
    run.add_argument("--seed", required=True)
    run.add_argument("--maximum-rounds", type=int, default=20)

    resume = sub.add_parser("resume-local")
    resume.add_argument("--userdata", type=Path, required=True)
    resume.add_argument("--match-id", required=True)
    resume.add_argument("--max-decisions", type=int, default=1000)

    verify = sub.add_parser("verify")
    verify.add_argument("--userdata", type=Path, required=True)
    verify.add_argument("--match-id", required=True)

    context = sub.add_parser("context")
    context.add_argument("--userdata", type=Path, required=True)
    context.add_argument("--match-id", required=True)

    args = parser.parse_args()
    if args.command == "autonomous-run":
        session, decisions = Gate4AutonomousRunner(
            args.source_root, args.userdata
        ).run(match_seed=args.seed, maximum_rounds=args.maximum_rounds)
        print(json.dumps(_result(session, decisions), indent=2, sort_keys=True))
        return 0

    persistence = Gate4Persistence(args.source_root, args.userdata)
    session = persistence.load_match(args.match_id, recover=True)
    if args.command == "verify":
        print(json.dumps(session.verify(), indent=2, sort_keys=True))
        return 0
    if args.command == "context":
        actor_id = session.engine.legal_candidates()[0].actor_id
        policy, _ = PolicyLibrary(args.source_root).for_actor(actor_id)
        context_value = build_decision_context(session.engine, policy)
        print(json.dumps(context_value.model_dump(mode="json", by_alias=True), indent=2, sort_keys=True))
        return 0
    if args.command == "resume-local":
        controller = LocalDeterministicController()
        policies = PolicyLibrary(args.source_root)
        decisions = []
        for _ in range(args.max_decisions):
            if session.engine.state.terminal_result is not None:
                break
            actor_id = session.engine.legal_candidates()[0].actor_id
            policy, _ = policies.for_actor(actor_id)
            context_value = build_decision_context(session.engine, policy)
            choice = controller.choose_primary_action(context_value)
            session.execute_controller_choice(
                choice, controller=controller, policy_library=policies
            )
            decisions.append(choice.record.model_dump(mode="json", by_alias=True))
        if session.engine.state.terminal_result is None:
            raise RuntimeError("CONTROLLER_NO_PROGRESS_DETECTED")
        print(json.dumps(_result(session, decisions), indent=2, sort_keys=True))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
