"""Source declarations on the public TableFact transport.

Clinical cases use these public adapters. TableFact remains the only recorded
GM command/schema: registered source validators own declaration semantics.
The optional metadata snapshot carries the same canonical TableFact into a
later journey; it is not a second independently editable fact store.
"""
import json

PREFIX = "condition:table.fact."


def snapshot_facts(conditions):
    """Decode canonical TableFacts from live or serialized encounter metadata."""
    from .table_facts import TableFact
    result = []
    for condition in (conditions.values() if isinstance(conditions, dict) else conditions or ()):
        if isinstance(condition, str):
            condition = json.loads(condition)
        data = condition.get("data", {}) if isinstance(condition, dict) else condition.data
        if data.get("table_fact_json"):
            result.append(TableFact.model_validate_json(data["table_fact_json"]))
    return result


def records(conditions, kind):
    """Read source records from a canonical encounter snapshot."""
    return [f.declaration["record"] for f in snapshot_facts(conditions)
            if f.active and f.declaration and f.declaration["kind"] == kind]


def validate(engine, subject, declaration):
    from .ext import run_strict
    if not isinstance(declaration, dict) or set(declaration) != {"kind", "record"} or not isinstance(declaration["kind"], str):
        raise ValueError("A source declaration needs a registered type and its complete record.")
    replies = run_strict("scene_fact_validate", engine, subject, declaration["kind"], declaration["record"])
    if len(replies) != 1 or replies[0] != declaration["record"]:
        raise ValueError("That scene fact has no matching source validator.")


def command_intent(engine, request, *, expected_state_version):
    from .table_facts import command_intent as table_intent
    if not isinstance(request, dict) or set(request) != {"subject", "kind", "record"}:
        raise ValueError("A scene fact needs a creature, registered type and source declaration.")
    target = engine.state.actors.get(request["subject"])
    if target is None:
        raise ValueError("Choose a creature present in this fight.")
    declaration = {"kind": request["kind"], "record": request["record"]}
    validate(engine, target.entity_id, declaration)
    return table_intent(engine, {
        "record_id": request["kind"] + ":" + target.entity_id + ":" + request["record"]["id"],
        "subject_id": target.entity_id, "subject_name": target.display_name, "subject_kind": "creature",
        "position": target.position.model_dump(mode="json"), "source_reference": request["record"]["source_note"],
        "witness_ids": [], "horizon": "until_corrected", "valid_through_round": None,
        "active": True, "answers": {}, "declaration": declaration,
    }, expected_state_version)


def private_event_view(document):
    """Redact only private TableFact metadata, preserving unrelated event facts."""
    def redact(value):
        if isinstance(value, list):
            return [redact(v) for v in value]
        if isinstance(value, str) and PREFIX in value:
            try:
                return json.dumps(redact(json.loads(value)), sort_keys=True)
            except ValueError:
                return value
        if not isinstance(value, dict):
            return value
        result = {k: redact(v) for k, v in value.items()}
        if "table_fact_json" in value:
            result.pop("table_fact_json", None)
            result["label"] = "GM scene declaration (private)"
        return result
    return redact(document)
