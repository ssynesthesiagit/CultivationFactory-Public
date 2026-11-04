"""Read the Vessel's native creature admission; whole-row delivery stays open.

The strict expected failure records the missing native check/choice path. It is
not automation credit: implementing that path must remove the marker and add
the rest of the whole-clause tests, including private GM-authored facts.
"""
import hashlib
import json

import pytest

from combat.factory_compiler import compile_character
from tests.h1_support import ROOT, sheet
from tests.h48_table_support import (
    OWNER, FOE, fixture, assert_reload_verify_replay,
)

SOURCE = "IMBUEMENT_BASE_READ_THE_VESSEL"


def options(table, match_id):
    return [option for group in table.state(match_id)["menu"]["actions"]
            for option in group["options"] if option["label"].startswith("Read the Vessel")]


def test_source_and_automatic_sphere_grant():
    text = json.loads((ROOT / "authority/typed_mechanics/rules_text.json").read_text())[SOURCE]
    assert hashlib.sha256(text.encode()).hexdigest() == "32b73ca0eaaff2f3ad27b1a1129ab2fc3cb351784ff1b70cdafc0808b433037e"
    document = sheet([SOURCE])
    document["spheres_and_talents"]["learned_talent_record_ids"] = []
    bundle = compile_character(document, actor_id=OWNER)
    reads = [a for a in bundle["action_catalog"]
             if a["parameters"].get("typed", {}).get("source") == SOURCE]
    assert len(reads) == 1
    assert reads[0]["target_kind"] == "ANY_CREATURE"
    assert reads[0]["economy"] == "ACTION"
    assert reads[0]["range_ft"] == 30
    assert reads[0]["costs"] == []
    assert not any(a["parameters"].get("typed", {}).get("source") == SOURCE
                   for a in compile_character(sheet([]), actor_id=FOE)["action_catalog"])


def test_enemy_study_is_reachable_commits_and_cold_reloads(tmp_path):
    combat, table, match_id, _send, commit = fixture(tmp_path, [SOURCE], seed="read-vessel-enemy")
    enemy = next((o for o in options(table, match_id) if o.get("target_ids") == [FOE]), None)
    assert enemy is not None, "Read the Vessel must admit an enemy, not just allies"
    session = combat._load_session(match_id)
    before = dict(session.engine.state.actors[OWNER].resources)
    first = len(session.engine.events)
    assert commit(enemy["candidate_id"])["status"] == "COMMITTED"
    session = combat._load_session(match_id)
    owner = session.engine.state.actors[OWNER]
    assert owner.resources == before
    assert not owner.action_available
    reminders = [e for e in session.engine.events[first:] if e.event_type == "GM_RIDER"
                 and SOURCE in str(e.source_definition_id)]
    assert reminders and all(e.target_ids == (FOE,) for e in reminders)
    # These are reminders, not learned facts. Record native evidence without
    # treating the commit or successful reload as a completed information check.
    print("READ_VESSEL_NATIVE_EVENTS", [e.event_type for e in session.engine.events[first:]])
    assert_reload_verify_replay(combat, match_id, tmp_path)
    for _ in range(10):
        menu = table.state(match_id)["menu"]
        if menu["actor_id"] == FOE:
            assert options(table, match_id) == [], "a non-owner must not gain this Study action"
            break
        commit(menu["end_turn"])
    else:
        raise AssertionError("foe turn never reached")


@pytest.mark.xfail(strict=True, reason="Whole row open: no native GM-DC/check and two-fact choice path")
def test_whole_row_requires_native_check_selection_before_commit(tmp_path):
    _combat, table, match_id, send, _commit = fixture(tmp_path, [SOURCE], seed="read-vessel-check-gap")
    target = next(o for o in options(table, match_id) if o.get("target_ids") == [FOE])
    result = send(target["candidate_id"])
    assert result["status"] == "REACTION_REQUIRED", (
        "Study committed without choosing a permitted check or obtaining the GM's DC; "
        "a rules reminder is not information-check delivery"
    )
