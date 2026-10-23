"""Consume Fear, Refine Command resolves on Dread Appetite's failed-save path."""
import json
from pathlib import Path

from tests.cw2_service_support import add_action, seal
from tests.test_r9i_karma_persistence import end_turn
from tests.worker2_support import OWNER, ALLY, FOE, candidate, fixture, reload, settle, turn

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
    assert engine.state.actors[OWNER].resources[ESSENCE] == before + 2
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
    assert reload(tmp_path, mid).state.actors[OWNER].resources[ESSENCE] == before + 2


def test_frightened_target_can_decline_the_additional_effect(tmp_path):
    combat, table, mid = fixture(tmp_path, [DREAD, CONSUME], cl=15, owner_dc=30, bundle_transform=_prepare)
    settle(table, mid, candidate(combat, mid, "Start Fear", target=FOE).candidate_id)
    prompts = settle(table, mid, _dread(combat, mid), decline_after=0)
    assert any(p["context"]["reaction_source_id"] == CHOICE for p in prompts)
    engine = reload(tmp_path, mid)
    assert not any(c.condition_id == "condition:typed.reaction_denied"
                   for c in engine.state.actors[FOE].conditions.values())
    assert engine.state.actors[OWNER].resources[ESSENCE] >= 2


def test_dread_appetite_without_consume_fear_does_not_gain_essence(tmp_path):
    combat, table, mid = fixture(tmp_path, [DREAD], cl=15, owner_dc=30)
    before = reload(tmp_path, mid).state.actors[OWNER].resources[ESSENCE]
    settle(table, mid, _dread(combat, mid))
    assert reload(tmp_path, mid).state.actors[OWNER].resources[ESSENCE] == before + 1


def _prepare_approach(bundles):
    _prepare(bundles)
    add_action(bundles[0], "Push Toward Ally", [
        {"type": "forced_movement", "applies_to": "target", "distance_ft": 5,
         "direction": "away", "evidence": "Push it 5 feet away from you."}
    ])
    add_action(bundles[2], "Self Teleport", [
        {"type": "teleport", "applies_to": "self", "distance_ft": 20,
         "evidence": "Teleport up to 20 feet to an unoccupied space."}
    ], target="SELF")
    seal(bundles[0]); seal(bundles[2])


def test_selected_ally_approach_bar_covers_paths_and_teleports_but_not_forced_movement(tmp_path):
    positions = {OWNER: {"x": 3, "y": 6}, ALLY: {"x": 8, "y": 6}, FOE: {"x": 6, "y": 6}}
    combat, table, mid = fixture(tmp_path, [DREAD, CONSUME], cl=15, owner_dc=30,
                                 bundle_transform=_prepare_approach, positions=positions)
    settle(table, mid, candidate(combat, mid, "Start Fear", target=FOE).candidate_id)
    settle(table, mid, _dread(combat, mid), {
        CHOICE: "no_approach", "choice:needle.consume_fear_ally": ALLY
    })
    engine = reload(tmp_path, mid)
    target = engine.state.actors[FOE]
    bar = next(c for c in target.conditions.values() if c.condition_id == "condition:typed.no_approach")
    assert bar.data["avoid"] == ALLY
    assert bar.expires_on == "END_OF_HOLDER_NEXT_TURN"

    turn(table, mid, FOE)
    engine = reload(tmp_path, mid)
    target = engine.state.actors[FOE]
    moves = engine._movement_candidates(target)
    assert not any((c.destination.x, c.destination.y) == (7, 6) for c in moves)
    assert any((c.destination.x, c.destination.y) == (5, 6) for c in moves)

    # An own teleport toward the selected ally fails; the same actor can teleport toward the caster.
    toward_ally = candidate(combat, mid, "Self Teleport", target=None, at=(7, 6))
    settle(table, mid, toward_ally.candidate_id)
    assert (reload(tmp_path, mid).state.actors[FOE].position.x,
            reload(tmp_path, mid).state.actors[FOE].position.y) == (6, 6)
    toward_caster = candidate(combat, mid, "Self Teleport", target=None, at=(5, 6))
    settle(table, mid, toward_caster.candidate_id)
    assert (reload(tmp_path, mid).state.actors[FOE].position.x,
            reload(tmp_path, mid).state.actors[FOE].position.y) == (5, 6)

    # Forced movement keeps its separate rule and is not blocked by the voluntary bar.
    turn(table, mid, OWNER)
    push = candidate(combat, mid, "Push Toward Ally", target=FOE)
    settle(table, mid, push.candidate_id)
    assert reload(tmp_path, mid).state.actors[FOE].position.x == 6


def test_failed_strength_save_drops_one_exact_held_mundane_object(tmp_path):
    mundane_dagger = {"items": [{"item_id": "tianxia.mortal.weapon.bi_shou",
                                  "name": "Bi Shou (Dagger)", "quantity": 1}]}
    combat, table, mid = fixture(tmp_path, [DREAD, CONSUME], cl=15, owner_dc=30,
                                 foe_kit=mundane_dagger, bundle_transform=_prepare)
    from combat.ext.scoundrel_riders import held_possessions
    engine = reload(tmp_path, mid)
    held = held_possessions(engine, engine.state.actors[FOE])
    assert len(held) == 1
    identity = held[0]["object"]
    settle(table, mid, candidate(combat, mid, "Start Fear", target=FOE).candidate_id)
    settle(table, mid, _dread(combat, mid), {
        CHOICE: "drop_object", "choice:needle.consume_fear_drop": identity
    })
    engine = reload(tmp_path, mid)
    dropped = [condition for condition in engine.state.actors[FOE].conditions.values()
               if (condition.data or {}).get("object_id") == identity
               and (condition.data or {}).get("dropped_at")]
    assert len(dropped) == 1
    assert dropped[0].data["dropped_at"] == engine.state.actors[FOE].position.model_dump(mode="json")
