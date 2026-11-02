"""Native evidence for the supported part of Tamer Package, not whole-row closure.

The roster pick below is deliberately NOT a training/acquisition receipt. The
source refers to an absent CR-cap table; training, release, contested control
and Awakening remain unresolved and are recorded in the packet report.
"""

from combat import summons
from tests.worker2_support import OWNER, ALLY, FOE, fixture, reload, settle


PACKAGE = "BEASTMASTERY_BASE_TAMER_PACKAGE"
TEMPORARY_TAMER = "TAL_BEASTMASTERY_BEAST_TAMER"


def test_represented_tame_beast_has_free_turn_after_table_commit_and_reload(tmp_path):
    # The existing roster producer recognizes the talent, not the package.
    # This checks delivery for an already represented beast only.
    combat, table, mid = fixture(
        tmp_path, [PACKAGE, TEMPORARY_TAMER],
        owner_plan={"beasts": ["wolf"], "mount": ""}, seed="T14-TAMER-COMMAND")
    engine = reload(tmp_path, mid)
    beast = next(b for b in summons.owned_by(engine, OWNER)
                 if b.summon["source"] == "tamer")
    assert beast.summon["command"] == "free"
    assert beast.summon["owner"] == OWNER
    assert not summons.owned_by(engine, ALLY)
    assert not summons.owned_by(engine, FOE)
    assert not any(".command." in a.source_definition_id
                   for a in engine.action_catalog.values() if a.owner_id == OWNER)
    before = engine.state.actors[OWNER]
    assert before.action_available and before.bonus_action_available
    settle(table, mid, table.state(mid)["menu"]["end_turn"])
    restored = reload(tmp_path, mid)
    assert restored.state.current_actor_id == beast.entity_id
    assert restored.state.actors[beast.entity_id].action_available
    assert restored.state.actors[beast.entity_id].summon == beast.summon
    assert not any(c.condition_id == "condition:core.dodge"
                   for c in restored.state.actors[beast.entity_id].conditions.values())


def test_unowned_roster_pick_does_not_create_a_tame_beast(tmp_path):
    # No sphere/package/talent and no injected tame provenance. A raw creature
    # pick must not itself give an unrelated character a Beastmastery creature.
    _, table, mid = fixture(
        tmp_path, [], owner_plan={"beasts": ["wolf"], "mount": ""},
        seed="T14-TAMER-UNOWNED")
    assert not summons.owned_by(reload(tmp_path, mid), OWNER)
    settle(table, mid, table.state(mid)["menu"]["end_turn"])
    assert not summons.owned_by(reload(tmp_path, mid), OWNER)
