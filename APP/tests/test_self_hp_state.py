"""Ashura Furnace: three clauses gated on "while you are below half your maximum Hit Points" (combat/ext/self_hp_state.py)."""
from types import SimpleNamespace

from combat import motion, pressure
from combat.ext import self_hp_state
from tests.test_a2_foundations3 import add_action
from tests.worker2_support import OWNER, FOE, candidate, fixture, reload, settle, turn

INSIGHT = 'insight.ashura-furnace'


def _setup(tmp_path, insights=(INSIGHT,)):
    def delivery(bundles):
        bundles[2]['actor_template']['armor_class'] = 1
        add_action(bundles[2], 'Wound', [{'type': 'attack', 'attack_kind': 'weapon', 'on_hit': [
            {'type': 'damage', 'flat': 27, 'damage_types': ['force'], 'applies_to': 'target'}]}], bonus=100, economy='NONE')
        add_action(bundles[2], 'Deep wound', [{'type': 'attack', 'attack_kind': 'weapon', 'on_hit': [
            {'type': 'damage', 'flat': 30, 'damage_types': ['force'], 'applies_to': 'target'}]}], bonus=100, economy='NONE')
        add_action(bundles[2], 'Fright', [{'type': 'save', 'ability': 'WIS', 'dc': 40, 'save_categories': ['frightened'],
                   'on_fail': [{'type': 'condition', 'condition': 'frightened', 'applies_to': 'target'}], 'on_success': []}],
                   dc=40, economy='NONE')
    return fixture(tmp_path, [], seed='NEXT5', owner_insights=insights, bundle_transform=delivery,
                   foe_position={'x': 4, 'y': 6}, ally_position={'x': 3, 'y': 7})


def _hurt(combat, table, mid, name):
    """The foe's hit costs the owner one more than its flat damage: 'Wound' leaves 30/60 (exactly half), 'Deep wound' fewer."""
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, name, target=OWNER).candidate_id)


def _strike(combat, table, tmp_path, mid):
    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, 'Unarmed Strike', target=FOE).candidate_id)
    return [(e.payload['damage_type'], e.payload['hp_damage']) for e in reload(tmp_path, mid).events
            if e.event_type == 'DAMAGE_COMMITTED' and e.actor_id == OWNER]


def test_exactly_half_is_not_below_half(tmp_path):
    combat, table, mid = _setup(tmp_path)
    _hurt(combat, table, mid, 'Wound')
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].current_hp * 2 == engine.state.actors[OWNER].maximum_hp
    assert [kind for kind, _ in _strike(combat, table, tmp_path, mid)] == ['BLUDGEONING']


def test_at_full_health_an_unarmed_hit_has_no_extra_damage(tmp_path):
    combat, table, mid = _setup(tmp_path)
    assert [kind for kind, _ in _strike(combat, table, tmp_path, mid)] == ['BLUDGEONING']


def test_below_half_one_unarmed_hit_adds_proficiency_bonus_fire_damage(tmp_path):
    combat, table, mid = _setup(tmp_path)
    _hurt(combat, table, mid, 'Deep wound')
    turn(table, mid, OWNER)
    assert reload(tmp_path, mid).state.actors[OWNER].current_hp * 2 < 60
    settle(table, mid, candidate(combat, mid, 'Unarmed Strike', target=FOE).candidate_id)
    hits = [(e.payload['damage_type'], e.payload['hp_damage']) for e in reload(tmp_path, mid).events
            if e.event_type == 'DAMAGE_COMMITTED' and e.actor_id == OWNER]
    assert [kind for kind, _ in hits] == ['BLUDGEONING', 'FIRE'] and hits[1][1] == 4


def test_without_the_insight_nothing_is_added(tmp_path):
    combat, table, mid = _setup(tmp_path, insights=())
    _hurt(combat, table, mid, 'Deep wound')
    assert [kind for kind, _ in _strike(combat, table, tmp_path, mid)] == ['BLUDGEONING']


def _dice(tmp_path, mid):
    return [len(e.payload['dice']) for e in reload(tmp_path, mid).events if e.event_type == 'SAVE_ROLLED' and e.actor_id == OWNER]


def test_advantage_on_saves_against_frightened_only_below_half(tmp_path):
    combat, table, mid = _setup(tmp_path)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Fright', target=OWNER).candidate_id)
    settle(table, mid, candidate(combat, mid, 'Deep wound', target=OWNER).candidate_id)
    settle(table, mid, candidate(combat, mid, 'Fright', target=OWNER).candidate_id)
    assert _dice(tmp_path, mid) == [1, 2]


def test_state_helper_and_the_ground_and_save_gates(tmp_path):
    combat, table, mid = _setup(tmp_path)
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    owner.maximum_hp = 60
    for hp, below, bloodied in ((60, False, False), (31, False, False), (30, False, True), (29, True, True), (1, True, True)):
        owner.current_hp = hp
        assert self_hp_state.holds(owner, 'below_half') is below and self_hp_state.holds(owner, 'bloodied') is bloodied
        assert motion.ignores_difficult(engine, owner) is below
        assert pressure.save_advantage(engine, owner, 'WIS', {'frightened'}) is below
        assert pressure.save_advantage(engine, owner, 'WIS', {'poisoned'}) is False
    assert self_hp_state.holds(owner, None) and not self_hp_state.holds(owner, 'unknown_state')
    assert not self_hp_state.holds(SimpleNamespace(active=False, current_hp=1, maximum_hp=60), 'below_half')


RIDER = 'choice:needle.owner_damage_type.insight_ashura_furnace'


def test_the_owner_picks_the_fire_or_necrotic_type_of_each_hit(tmp_path):
    """Review finding 2: "chosen for that hit" is the owner's pick, asked on their own turn, not a silent best-landing pick."""
    combat, table, mid = _setup(tmp_path)
    _hurt(combat, table, mid, 'Deep wound')
    turn(table, mid, OWNER)
    prompts = settle(table, mid, candidate(combat, mid, 'Unarmed Strike', target=FOE).candidate_id, choices={RIDER: ['NECROTIC']})
    assert [p['context']['reaction_source_id'] for p in prompts] == [RIDER], prompts
    assert {option['id'] for option in prompts[0]['choice']['options']} == {'FIRE', 'NECROTIC'}, prompts[0]['choice']
    hits = [(e.payload['damage_type'], e.payload['hp_damage']) for e in reload(tmp_path, mid).events
            if e.event_type == 'DAMAGE_COMMITTED' and e.actor_id == OWNER]
    assert [kind for kind, _ in hits] == ['BLUDGEONING', 'NECROTIC'], hits


def test_the_ashura_reviewed_riders_leave_no_forbidden_insight_text_for_the_gm(tmp_path):
    """Review finding 1: the Forbidden Insight text is run by the fight, so the generated authority must not hand it to the GM."""
    import json
    from pathlib import Path
    app = Path(__file__).resolve().parents[1]
    reviewed = json.loads((app / "authority/typed_mechanics/reviewed_final.d/next5_ashura.json").read_text())
    generated = json.loads((app / "authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_text())
    riders = generated["mechanics"][INSIGHT]["riders"]
    assert riders, "Keep the remaining manual rules for the Source CL rider"
    assert not any("Forbidden Insight" in rider or "Unarmed" in rider for rider in riders), riders
    assert not any("Forbidden Insight" in rider for rider in reviewed["mechanics"][INSIGHT]["riders"])
