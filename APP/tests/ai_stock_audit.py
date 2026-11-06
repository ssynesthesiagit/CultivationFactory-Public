"""Offline stock diagnostics used by the capture wrapper and AI tier inspector.

Candidate IDs identify menu receipts, not combat decisions: a lazy area root and
its concrete square can resolve the same action. Compare the committed intent,
including its chosen aim/path/options, plus actual reaction selections instead.
This never changes the strict stock equality verdict or grants stock acceptance.
"""
import json
import os
from itertools import zip_longest
from pathlib import Path


def stock_evidence_dir(basetemp):
    """Shared capture/inspector directory, with the queue's existing overrides.

    Callers pass the pytest session basetemp, not a capture arm's scratch path.
    An arm lives at <basetemp>/<test case>/<base|head>.
    """
    return Path(os.environ.get("CF_STOCK_EVIDENCE") or os.environ.get("CF_STOCK_EVIDENCE_DIR")
                or os.environ.get("CF_STOCK_EVIDENCE_ROOT")
                or (Path(os.environ["TMPDIR"]) / "stock" if os.environ.get("TMPDIR")
                    else Path(basetemp) / "stock"))


def write_decision_evidence(scratch, seed, decisions):
    """Capture-side sidecar writer; also usable with synthetic public fixtures."""
    scratch = Path(scratch)
    evidence = stock_evidence_dir(scratch.parent.parent)
    evidence.mkdir(parents=True, exist_ok=True)
    path = evidence / f"{seed}-{scratch.name}-decisions.json"
    path.write_text(json.dumps(decisions, sort_keys=True) + "\n")
    return path


def journal_decisions(mechanical, controller):
    """Join durable PREPARE bindings and controller selections to each COMMIT."""
    prepared = {r["transaction_id"]: r for r in mechanical if r["record_type"] == "PREPARE"}
    reactions = {r["transaction_id"]: r["reaction_decision_records"]
                 for r in controller if r["record_type"] == "CONTROLLER_COMMIT"}
    result = []
    for commit in mechanical:
        if commit["record_type"] != "COMMIT":
            continue
        tid = commit["transaction_id"]
        prepare = prepared[tid]
        intent = prepare["intent"]
        binding = prepare["candidate_binding"]
        # Every rule-affecting intent field survives, including movement mode,
        # explicit paths, object/condition choices and embedded reactions.
        primary = {k: v for k, v in intent.items() if k not in {
            "intent_id", "decision_id", "candidate_id", "state_version",
            "destination", "placement_destination"}}
        primary.update(kind=binding["kind"], source_definition_id=binding["source_definition_id"],
                       destination=intent.get("placement_destination") or intent.get("destination"))
        result.append({"primary": primary, "reactions": [
            {"selected_reaction": r["selected_reaction"], "selected_option_ids": r["selected_option_ids"]}
            for r in reactions[tid]]})
    return result


def outcomes(events):
    """All rules events, not a whitelist that silently misses new event kinds.

    Only persistence snapshots and accepted menu receipt IDs are excluded.
    Transaction/intent IDs depend on the menu receipt and aren't rules results.
    Roll records are compared separately without any projection.
    """
    result = []
    for event in events:
        payload = {k: v for k, v in event.get("payload", {}).items() if not k.startswith("gate3_")}
        if event["event_type"] == "INTENT_ACCEPTED":
            payload.pop("candidate_id", None)
        result.append({**{k: event[k] for k in (
            "sequence", "state_version", "event_type", "actor_id", "source_definition_id", "target_ids")},
            "payload": payload})
    return result


def first_difference_step(left, right):
    """One-based first difference, including an unmatched trailing transaction."""
    return next((i for i, (a, b) in enumerate(zip_longest(left, right), 1) if a != b), None)


def compare_capture(seed, base, head, base_decisions, head_decisions):
    """Classify the first divergence; never equate different AI trajectories."""
    for capture, decisions in ((base, base_decisions), (head, head_decisions)):
        assert capture["steps"] == len(capture["events"]) == len(capture["rolls"]) == len(decisions)
    choice = first_difference_step(base_decisions, head_decisions)
    before = [{"events": outcomes(e), "rolls": r} for e, r in zip(base["events"], base["rolls"])]
    after = [{"events": outcomes(e), "rolls": r} for e, r in zip(head["events"], head["rolls"])]
    outcome = first_difference_step(before, after)
    report = {"seed": seed, "steps": [base["steps"], head["steps"]],
        "zones": [base["zones"], head["zones"]], "summons": [base["summons"], head["summons"]],
        "terminal": [base["state"]["terminal_result"], head["state"]["terminal_result"]],
        "first_choice_step": choice, "first_menu_step": first_difference_step(base["choices"], head["choices"]),
        "first_outcome_step": outcome}
    if choice is not None:
        report.update(base_choice=base_decisions[choice - 1] if choice <= len(base_decisions) else None,
                      head_choice=head_decisions[choice - 1] if choice <= len(head_decisions) else None)
    if outcome is not None:
        report.update(base_outcomes=before[outcome - 1] if outcome <= len(before) else None,
                      head_outcomes=after[outcome - 1] if outcome <= len(after) else None)
    report["rules_equal_before_choice"] = outcome is None or (choice is not None and outcome >= choice)
    return report
