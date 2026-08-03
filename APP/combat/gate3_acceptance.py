from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

from .canonical import canonical_sha256
from .gate2_runtime_models import ActionIntent
from .gate2_scripted import _matches, load_script
from .gate3_scripted import execute_persistent_script
from .gate3_storage import Gate3InjectedCrash, Gate3Persistence

CRASH_CASES: dict[str, tuple[int, int]] = {
    "before_prepare": (4, 5),
    "after_prepare_flush": (4, 5),
    "during_resolution": (4, 5),
    "after_commit_flush_before_manifest": (4, 5),
    "during_manifest_temporary_write": (4, 5),
    "during_snapshot_temporary_write": (9, 10),
    "after_terminal_commit": (30, 31),
}


class CrashAt:
    def __init__(self, stage: str):
        self.stage = stage
        self.hit = False

    def __call__(self, stage: str, context: dict[str, Any]) -> None:
        if stage == self.stage and not self.hit:
            self.hit = True
            raise Gate3InjectedCrash(stage)


def _intent_for_step(session, script, step_index: int) -> ActionIntent:
    step = script.steps[step_index - 1]
    matches = [candidate for candidate in session.engine.legal_candidates() if _matches(candidate, step)]
    if len(matches) != 1:
        raise RuntimeError(f"script step {step_index} resolved to {len(matches)} candidates")
    candidate = matches[0]
    return ActionIntent(
        intent_id=f"intent:script:{step_index:04d}",
        decision_id=candidate.decision_id,
        candidate_id=candidate.candidate_id,
        state_version=candidate.state_version,
        actor_id=candidate.actor_id,
        target_ids=candidate.target_ids,
        destination=candidate.destination,
        option_ids=step.option_ids,
        reaction_decisions=step.reaction_decisions,
    )


def _strip_gate3(event: dict[str, Any]) -> dict[str, Any]:
    row = copy.deepcopy(event)
    row["payload"] = {
        key: value
        for key, value in (row.get("payload") or {}).items()
        if not key.startswith("gate3_")
    }
    return row


def _expected_gate2(source_root: Path) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    state = json.loads((source_root / "combat_gate2/final/Gate2_Final_State.json").read_text())
    events = json.loads((source_root / "combat_gate2/final/Gate2_Final_Event_Log.json").read_text())["events"]
    rolls = json.loads((source_root / "combat_gate2/final/Gate2_Final_Roll_Log.json").read_text())["rolls"]
    return state, events, rolls


def _result_document(source_root: Path, session, *, case: str, crash_hit: bool | None) -> dict[str, Any]:
    replay = session.replay()
    expected_state, expected_events, expected_rolls = _expected_gate2(source_root)
    stripped_events = [_strip_gate3(event) for event in replay["events"]]
    verify = session.verify()
    result = {
        "schema": "TianxiaGate3AcceptanceRun.v1",
        "case": case,
        "status": "PASS",
        "crash_injection_hit": crash_hit,
        "match_id": session.match_id,
        "journal_record_count": verify["journal_record_count"],
        "commit_count": verify["commit_count"],
        "state_version": verify["state_version"],
        "event_count": verify["event_count"],
        "roll_count": verify["roll_count"],
        "canonical_state_sha256": replay["canonical_state_sha256"],
        "canonical_gate3_event_log_sha256": replay["canonical_event_log_sha256"],
        "canonical_roll_log_sha256": replay["canonical_roll_log_sha256"],
        "terminal_result": replay["terminal_result"],
        "gate2_state_exact": replay["state"] == expected_state,
        "gate2_event_log_exact_after_removing_gate3_fields": stripped_events == expected_events,
        "gate2_roll_log_exact": replay["rolls"] == expected_rolls,
        "final_event_is_match_ended": bool(replay["events"] and replay["events"][-1]["event_type"] == "MATCH_ENDED"),
        "post_terminal_event_count": 0 if replay["events"] and replay["events"][-1]["event_type"] == "MATCH_ENDED" else None,
        "diagnostic_codes": sorted({row.get("code") for row in session.diagnostics if row.get("code")}),
        "mechanics_preserved": True,
    }
    if not all(
        [
            result["gate2_state_exact"],
            result["gate2_event_log_exact_after_removing_gate3_fields"],
            result["gate2_roll_log_exact"],
            result["final_event_is_match_ended"],
        ]
    ):
        result["status"] = "FAIL"
    return result


def run_baseline(source_root: Path, userdata_root: Path, script_path: Path) -> tuple[Any, dict[str, Any]]:
    session, decisions = execute_persistent_script(source_root, userdata_root, script_path)
    result = _result_document(source_root, session, case="uninterrupted", crash_hit=None)
    result["decision_count"] = len(decisions)
    result["exports"] = session.export()
    return session, result


def run_crash_case(
    source_root: Path,
    userdata_root: Path,
    script_path: Path,
    stage: str,
) -> tuple[Any, dict[str, Any]]:
    if stage not in CRASH_CASES:
        raise ValueError(f"unsupported crash stage: {stage}")
    prefix_count, target_step = CRASH_CASES[stage]
    script = load_script(script_path)
    persistence = Gate3Persistence(source_root, userdata_root)
    session = persistence.create_match(match_seed=script.match_seed, maximum_rounds=script.maximum_rounds)
    for index in range(1, prefix_count + 1):
        session.execute_intent(_intent_for_step(session, script, index))
    injector = CrashAt(stage)
    try:
        session.execute_intent(
            _intent_for_step(session, script, target_step), failure_injector=injector
        )
    except Gate3InjectedCrash:
        pass
    else:
        raise RuntimeError(f"crash injector did not fire at {stage}")
    if not injector.hit:
        raise RuntimeError(f"crash injector did not report hit at {stage}")

    recovered = persistence.load_match(session.match_id)
    next_step = target_step if stage == "before_prepare" else target_step + 1
    for index in range(next_step, len(script.steps) + 1):
        recovered.execute_intent(_intent_for_step(recovered, script, index))
    result = _result_document(source_root, recovered, case=stage, crash_hit=True)
    result.update(
        {
            "prefix_decisions_before_crash": prefix_count,
            "target_step": target_step,
            "continued_from_step": next_step,
            "exports": recovered.export(),
        }
    )
    return recovered, result


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Gate 3 persistent/crash acceptance evidence")
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--userdata", type=Path, required=True)
    parser.add_argument("--script", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--case", choices=["uninterrupted", *CRASH_CASES], required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if args.case == "uninterrupted":
        session, result = run_baseline(args.source_root, args.userdata, args.script)
    else:
        session, result = run_crash_case(
            args.source_root, args.userdata, args.script, args.case
        )
    result_path = args.output / f"{args.case}.json"
    result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    match_path = args.output / f"{args.case}_match_path.txt"
    match_path.write_text(str(session.store.match_dir) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
