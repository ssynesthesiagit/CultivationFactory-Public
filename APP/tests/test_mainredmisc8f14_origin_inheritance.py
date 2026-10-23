"""MAINREDMISC8F14: a damage origin is set once, where its packet is created; only a split or shared portion of that
same delivery copies it.

Direct tick and Community sharing each have one regression. The reaction case is the root one: a packet committed
while a recurring tick is in flight is a fresh blow unless it is actually a portion of that delivery, so it must still
answer Ten Thousand Rebounds. The table hands a split portion the origin through ``pending_damage.portion_origin``.
"""

from combat import ext, pending_damage
from combat.ext import force, protection
from tests.test_mainredmisc8rb1_community_ongoing import ALLY, FOE, ME, protect_community, use


def _origins(engine, before, target):
    return [e.payload.get("damage_origin") for e in engine.events[before:]
            if e.event_type == "DAMAGE_COMMITTED" and target in e.target_ids]


def test_direct_tick_carries_its_origin_at_creation():
    engine = protect_community()
    ally = engine.state.actors[ALLY]
    ally.current_hp = 50
    before = len(engine.events)
    # A producer names the origin once, where its packet is created (depth 0), and the payload carries it at delivery.
    engine._commit_damage(ally, 4, "SLASHING", "test:tick", FOE, None, reaction_depth=0, damage_origin="ongoing")
    assert _origins(engine, before, ALLY) == ["ongoing"]


def test_a_reaction_triggered_by_a_tick_is_a_fresh_blow_and_still_answers(tmp_path, monkeypatch):
    """A reaction packet runs while the tick's packet is in flight, but it is not a portion of that delivery: it must
    stay unclassified, and Ten Thousand Rebounds must answer it."""
    from tests.test_riders_lane10 import _rebounds_table

    ongoing = "condition:typed.test_reaction_burn"
    combat, table, mid, send, commit, enemy, second, owner_id, candidate = _rebounds_table(tmp_path)
    engine = combat._load_session(mid).engine
    owner = engine.state.actors[owner_id]
    foe = engine.state.actors[enemy]
    source_id = next(action_id for action_id in engine.action_catalog if enemy in action_id)
    action = engine.action_catalog[source_id]
    force._arm(engine, owner, "")

    engine._apply_condition(owner, ongoing, source_id, foe.entity_id, expires_on="UNTIL_REMOVED",
                            data={"rule": {}, "speed_delta": 0, "numbers": {"save_dc": 10},
                                  "ongoing_effects": [{"type": "damage", "applies_to": "target",
                                                       "dice": {"count": 2, "sides": 8},
                                                       "damage_types": ["slashing"]}]})

    fired = []

    def react(engine, event_type, kwargs):
        payload = kwargs.get("payload") or {}
        if (event_type == "DAMAGE_COMMITTED" and payload.get("damage_origin") == "ongoing"
                and owner.entity_id in (kwargs.get("target_ids") or ()) and not fired):
            fired.append(True)
            # The reaction the tick triggers deals its own physical blow, inside the tick's packet scope.
            engine._commit_damage(owner, 3, "SLASHING", "test:reaction", foe.entity_id, None, reaction_depth=2)

    monkeypatch.setitem(ext._HOOKS, "event", [*ext._HOOKS.get("event", []), react])

    before = len(engine.events)
    foe_hp = foe.current_hp
    ext.run("turn_start", engine, owner)

    packets = [e for e in engine.events[before:]
               if e.event_type == "DAMAGE_COMMITTED" and owner.entity_id in e.target_ids]
    assert [e.payload.get("damage_origin") for e in packets] == ["ongoing", None], \
        "the tick is ongoing and the reaction it triggered is a fresh blow, not a portion of it"
    assert foe.current_hp < foe_hp, "Ten Thousand Rebounds answers the fresh reaction blow"
    assert foe.entity_id in force._armed(engine, owner)["spent"].split(), \
        "and spends that creature's one response"


def test_nested_packet_of_a_fresh_blow_and_a_fresh_instance_stay_unclassified():
    engine = protect_community()
    ally = engine.state.actors[ALLY]
    ally.current_hp = 50
    before = len(engine.events)
    with pending_damage.scope(engine, ally, 4, "SLASHING", "test:blow", FOE):
        engine._commit_damage(ally, 3, "SLASHING", "test:blow", FOE, None, reaction_depth=2)
    engine._commit_damage(ally, 2, "SLASHING", "test:blow", FOE, None, reaction_depth=0)
    assert _origins(engine, before, ALLY) == [None, None], "a fresh blow and its portions are not ongoing"


def test_community_portion_of_a_recurring_tick_stays_ongoing_with_no_per_hop_forwarding():
    engine = protect_community()
    me, ally = engine.state.actors[ME], engine.state.actors[ALLY]
    use(engine, "Aegis: Armored Aegis (Persistent)", target=ALLY)
    me.action_available = True
    use(engine, "Aegis: Armored Aegis (Persistent)", target=ME)
    ally.current_hp = 10
    before = len(engine.events)
    with pending_damage.scope(engine, ally, 16, "SLASHING", "test:tick", FOE, damage_origin="ongoing"):
        assert protection.community(engine, ally, 16, "test:tick", FOE) == 8
    moved = _origins(engine, before, ME)
    assert moved and all(origin == "ongoing" for origin in moved), "the moved part inherits the tick's origin"
