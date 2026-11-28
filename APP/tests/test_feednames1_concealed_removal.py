"""A committed, expired declaration stays private in the table and Battle History feeds."""
import json

from combat import senses
from combat.fact_consent_admission import CONDITION
from combat.gate5_service import CombatService
from combat.journal_feed import journal_since
from combat.private_information import event_audience
from combat.tabletop_service import TabletopService
from tests.active_defense_table_support import A, B, acquired_combat, advance, finish
from tests.h1_support import ROOT


def test_readiness_expiry_keeps_its_receipt_out_of_public_feeds(tmp_path, monkeypatch):
    def unlocated(real):
        def check(engine, viewer, seen, **options):
            if viewer.entity_id == A and seen.entity_id == B:
                return False
            return real(engine, viewer, seen, **options)
        return check

    # B can see and attack A, but A must answer the readiness question.
    monkeypatch.setattr(senses, "perceives", unlocated(senses.perceives))
    monkeypatch.setattr(senses, "pinpoints", unlocated(senses.pinpoints))
    table, mid = acquired_combat(tmp_path, monkeypatch)
    advance(table, mid, B)

    def choose(prompt):
        if "fact_admission.shield_readiness" in prompt["context"]["reaction_source_id"]:
            return ["unaware"]
        return None

    prompts = finish(table, mid, choose)
    engine = table.combat._load_session(mid).engine
    declarations = [
        row for row in engine.state.actors[A].conditions.values()
        if row.condition_id == CONDITION and json.loads(row.data["record"])["kind"] == "shield_readiness"
    ]
    assert len(declarations) == 1, (declarations, prompts)
    declaration = declarations[0]
    assert declaration.expires_on == "START_OF_SELF_NEXT_TURN"
    value = json.loads(declaration.data["record"])["value"]
    label = declaration.data["label"]
    assert value == "unaware" and label, declaration.data
    # Start polling after the declaration's commit so we check only its expiry.
    after = engine.state.event_sequence
    advance(table, mid, A)

    events, _, _, _ = journal_since(table.combat._match_dir(mid), after)
    removals = [
        event for event in events
        if event["event_type"] == "CONDITION_REMOVED"
        and event["payload"].get("instance_id") == declaration.instance_id
    ]
    assert len(removals) == 1, events
    removal = removals[0]
    payload = removal["payload"]
    assert payload.get("checkpoint") == "START_OF_TURN", removal
    assert payload.get("concealed") is True, removal
    assert payload.get("gate3_condition_before") == declaration.model_dump(mode="json"), removal

    def assert_public_feed(reader, view):
        response = reader.events(mid, after)
        rows = response["events"]
        assert any(row["event_type"] == "TURN_STARTED" and row["actor_id"] == A for row in rows), response
        leaks = [row for row in rows if row["event_sequence"] == removal["sequence"]]
        assert not leaks, (view, leaks)
        response_json = json.dumps(response)
        assert value not in response_json and label not in response_json, (view, response_json)

    assert_public_feed(table, "table")
    cold = CombatService(ROOT, tmp_path)
    reloaded = cold._load_session(mid).engine
    assert declaration.instance_id not in reloaded.state.actors[A].conditions
    assert_public_feed(TabletopService(cold, tmp_path), "reloaded table")
    # The prose renderer also skips this row; assert the audience independently.
    assert event_audience(reloaded, removal) == frozenset({A}), removal

    history_rows = [row for boundary in cold.history(mid)["boundaries"] for row in boundary["feed"]]
    leaks = [row for row in history_rows if row["event_sequence"] == removal["sequence"] or label in row["summary"]]
    assert not leaks, leaks
