"""Consume Fear, Refine Command resolves on Dread Appetite's failed-save path."""
import json
from pathlib import Path

from tests.cw2_service_support import add_action, seal
from tests.test_r9i_karma_persistence import end_turn
from tests.worker2_support import OWNER, FOE, candidate, fixture, reload, settle, turn

DREAD = "TAL_DAEMONIC_CULTIVATION_DREAD_APPETITE"
CONSUME = "TAL_DAEMONIC_CULTIVATION_CONSUME_FEAR_REFINE_COMMAND"
ESSENCE = "resource:named.devoured_essence"
CHOICE = "choice:needle.consume_fear"


def _prepare(bundles):
    add_action(bundles[0], "Start Fear", [
        {"type": "condition", "applies_to": "target", "condition": "frightened",
         "expires_on": "UNTIL_REMOVED"}
    ])
    seal(bundles[0])


def _assert_rebuilt_authority():
    authority = json.loads((Path(__file__).parents[1] / "authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_text())
    record = authority["mechanics"][CONSUME]
    assert record["source"]["text_sha256"] == "3bc927c349ca80abd334bce4792de127487a09f34109e6a652e82999b557774d"
    assert record["min_cl"] == 5
    assert record["riders"] == []
    assert record["modifier"]["when"] == "failed_save"
    assert record["modifier"]["effects"] == [{"type": "rider_consume_fear"}]


def _dread(combat, mid):
    return candidate(combat, mid, "Dread Appetite: Frighten", target=FOE).candidate_id


def test_failed_dread_appetite_grants_essence_and_only_prior_fear_opens_choice(tmp_path):
    _assert_rebuilt_authority()
    combat, table, mid = fixture(tmp_path, [DREAD, CONSUME], cl=15, owner_dc=30, bundle_transform=_prepare)
    before = reload(tmp_path, mid).state.actors[OWNER].resources[ESSENCE]
    settle(table, mid, candidate(combat, mid, "Start Fear", target=FOE).candidate_id)
    prompts = settle(table, mid, _dread(combat, mid), {CHOICE: "deny_reactions"})
    assert any(p["context"]["reaction_source_id"] == CHOICE for p in prompts)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[ESSENCE] == before + 1
    denied = [c for c in engine.state.actors[FOE].conditions.values()
              if c.condition_id == "condition:typed.reaction_denied"]
    assert denied and denied[0].expires_on == "END_OF_SOURCE_NEXT_TURN"
    save = next(e for e in reversed(engine.events) if e.event_type == "SAVE_ROLLED" and e.actor_id == FOE)
    assert save.payload["total"] < save.payload["dc"]
    end_turn(table, mid)
    turn(table, mid, OWNER)
    assert any(c.condition_id == "condition:typed.reaction_denied"
               for c in reload(tmp_path, mid).state.actors[FOE].conditions.values())
    end_turn(table, mid)
    assert not any(c.condition_id == "condition:typed.reaction_denied"
                   for c in reload(tmp_path, mid).state.actors[FOE].conditions.values())


def test_unfrightened_failed_save_gains_essence_without_additional_choice(tmp_path):
    combat, table, mid = fixture(tmp_path, [DREAD, CONSUME], cl=15, owner_dc=30)
    before = reload(tmp_path, mid).state.actors[OWNER].resources[ESSENCE]
    prompts = settle(table, mid, _dread(combat, mid))
    assert not any(p["context"]["reaction_source_id"] == CHOICE for p in prompts)
    assert reload(tmp_path, mid).state.actors[OWNER].resources[ESSENCE] == before + 1


def test_dread_appetite_without_consume_fear_does_not_gain_essence(tmp_path):
    combat, table, mid = fixture(tmp_path, [DREAD], cl=15, owner_dc=30)
    before = reload(tmp_path, mid).state.actors[OWNER].resources[ESSENCE]
    settle(table, mid, _dread(combat, mid))
    assert reload(tmp_path, mid).state.actors[OWNER].resources[ESSENCE] == before
