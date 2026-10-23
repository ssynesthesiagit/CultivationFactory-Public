"""Printed enchantments through service sessions, journaled setup and cold replay."""
import json
from contextlib import contextmanager

import pytest

from combat.canonical import canonical_sha256
from combat.ext import effect, hook
from combat.gate2_runtime_models import ActionIntent
from tests.h1_support import ROOT, sheet
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, reload, settle, turn, end_turn

AUTHORITY = json.loads((ROOT / 'authority/Tianxia_Treasure_Weapon_Authority_R1.json').read_text())
ROWS = {r['enchantment_id'].rsplit('.', 1)[-1]: r for r in AUTHORITY['enchantments']}


@effect("test_treasure_native_condition", harmful=True)
def native_condition(ctx, row):
    cid = row["condition_id"]
    data = {}
    if cid == "condition:typed.dream_sleep":
        from combat.ext.dreams_core import SLEEP_RULE
        data["rule"] = dict(SLEEP_RULE)
    ctx.engine._apply_condition(ctx.target, cid, ctx.source, ctx.actor.entity_id,
                               expires_on="UNTIL_REMOVED", data=data)


@effect("test_treasure_concentrate", harmful=True)
def concentrate(ctx, row):
    ctx.engine._start_concentration(ctx.target, ctx.source)


def kit(key):
    keys = key if isinstance(key, (list, tuple)) else [key]
    return {'starting_kit': {'items': [], 'resolved_treasure_weapon': {
        'chassis': {'item_id': 'test.treasure.jian', 'name': 'Test treasure',
                    'damage': '1d8 Slashing', 'properties': ''},
        'refinement_bonus': 20, 'enchantments': [ROWS[k] for k in keys]}}}


def scenario(tmp_path, key, *, kind='Humanoid', setup=None, attacks=1, ally_key=None, foe_hp=1000, concentrate=False,
             foe_mids=(), modes=None, foe_resists_fire=True, foe_primary='Qi'):
    foe = sheet(list(foe_mids), cl=1, primary=foe_primary)
    foe['identity']['creature_types'] = [kind]
    foe['ability_scores_and_statistics']['hit_points']['maximum'] = foe_hp

    def seal(bundles):
        b = bundles[0]
        weapon = next(r for r in b['action_catalog'] if r['display_name'] == 'Test treasure attack')
        weapon['parameters']['typed']['effects'][0]['count'] = attacks
        if not foe_resists_fire:
            bundles[2]['typed_passives'] = [r for r in bundles[2]['typed_passives'] if r.get('block') != 'defense']
            bundles[2].pop('bundle_sha256', None)
            bundles[2]['bundle_sha256'] = canonical_sha256(bundles[2])
        if setup:
            sid = 'action:test.enchantment.setup'
            effects = [{'type': 'test_treasure_native_condition',
                        'condition_id': setup[0] if setup[0].startswith('condition:') else
                                        'condition:typed.' + setup[0]}]
            if concentrate:
                effects.append({'type': 'test_treasure_concentrate'})
            row = {'source_definition_id': sid, 'display_name': 'Set scenario condition', 'owner_id': OWNER,
                   'economy': 'NONE', 'resolution_kind': 'TYPED', 'target_kind': 'HOSTILE_ENTITY', 'range_ft': 60,
                   'costs': [], 'parameters': {'typed': {'source': setup[1],
                       'effects': effects, 'numbers': {},
                       'duration': {'kind': 'instant'}, 'riders': []}}}
            b['action_catalog'].append(row)
            b['actor_template']['action_ids'].append(sid)
        b.pop('bundle_sha256', None)
        b['bundle_sha256'] = canonical_sha256(b)
    combat, table, mid = fixture(tmp_path, [], cl=1, owner_kit=kit(key), foe_sheet=foe,
                                ally_kit=kit(ally_key) if ally_key else None, foe_position={'x': 4, 'y': 6}, ally_position={'x': 3, 'y': 7}, seed='TREASURE-' + str(key), bundle_transform=seal,
                                modes=modes)
    if setup:
        execute(combat, mid, 'Set scenario condition')
        reload(tmp_path, mid)
    return combat, table, mid


def execute(combat, mid, name='Test treasure attack', target=FOE):
    c = candidate(combat, mid, name, target=target)
    combat._load_session(mid).mechanical.execute_intent(ActionIntent(
        intent_id='intent:treasure:' + c.candidate_id, decision_id=c.decision_id,
        candidate_id=c.candidate_id, state_version=c.state_version,
        actor_id=combat._load_session(mid).engine.state.current_actor_id,
        target_ids=c.target_ids, destination=c.destination))


def packets(engine, kind):
    return [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED'
            and e.actor_id == OWNER and str(e.payload.get('damage_type', '')).upper() == kind]


def damage_roll(engine, packet):
    return next(e.payload for e in reversed(engine.events)
                if e.sequence < packet.sequence and e.event_type == 'DAMAGE_ROLLED' and e.actor_id == OWNER)


def test_frost_stacks_caps_and_expires_at_bearers_next_turn(tmp_path):
    combat, table, mid = scenario(tmp_path, 'frost_meridian_inscription', attacks=5)
    execute(combat, mid)
    engine = reload(tmp_path, mid)
    penalties = [m for m in engine.state.actors[FOE].modifiers.values()
                 if m.target_field == 'speed_ft']
    assert len(penalties) == 1
    assert penalties[0].value == -15
    assert penalties[0].source_actor_id == OWNER
    values = [e.payload.get('value') for e in engine.events if e.event_type == 'MODIFIER_APPLIED'
              and e.payload.get('target_field') == 'speed_ft']
    assert values[:3] == [-5, -10, -15]
    assert all(v == -15 for v in values[3:])
    end_turn(table, mid)
    turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    assert not any(m.source_definition_id.startswith('treasure:frost:')
                   for m in engine.state.actors[FOE].modifiers.values())


@pytest.mark.parametrize('kind,extra', [('Humanoid', 1), ('Undead', 2), ('Fiend', 2), ('Beast', 1),
                                      ('Aberration', 2), ('Celestial', 2), ('Elemental', 2), ('Fey', 2)])
def test_spirit_striking_uses_printed_creature_kinds(tmp_path, kind, extra):
    combat, _, mid = scenario(tmp_path, 'spirit_striking_inscription', kind=kind)
    execute(combat, mid)
    engine = reload(tmp_path, mid)
    damage = packets(engine, 'PSYCHIC')
    assert len(damage) == 1
    rolled = damage_roll(engine, damage[0])
    assert len(rolled['dice']) == extra * (2 if rolled.get('critical') else 1)
    assert all(1 <= die <= 8 for die in rolled['dice'])


@pytest.mark.parametrize('setup,bonus', [(None, False), (('charmed', 'scenario:charm'), True),
    (('frightened', 'scenario:fear'), True), (('unconscious', 'scenario:sleep'), True),
    (('scenario_dream_mark', 'DREAMS_BASE_DREAM_SEED'), True),
    (('dream_sleep', 'DREAMS_BASE_DREAM_SEED'), True),
    (('scenario_dream_mark', 'scenario:other'), False),
    (('condition:core.frightened', 'scenario:native-fear'), True),
    (('condition:typed.suppressed.charmed', 'DREAMS_BASE_DREAM_SEED'), False)])
def test_dream_piercing_checks_hit_state_and_dreams_provenance(tmp_path, setup, bonus):
    combat, _, mid = scenario(tmp_path, 'dream_piercing_inscription', setup=setup)
    execute(combat, mid)
    engine = reload(tmp_path, mid)
    assert bool(packets(engine, 'PSYCHIC')) is bonus
    if setup and setup[0] == 'dream_sleep':
        delivered = [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED' and e.actor_id == OWNER]
        assert delivered[0].payload['damage_type'] == 'PSYCHIC'
    assert not any(e.event_type == 'GM_RIDER' for e in engine.events)


@pytest.mark.parametrize('keys', [
    ['flame_vein_inscription', 'dream_piercing_inscription'],
    ['dream_piercing_inscription', 'flame_vein_inscription'],
])
def test_dream_piercing_damage_precedes_damage_caused_saves(tmp_path, keys):
    combat, _, mid = scenario(tmp_path, keys, setup=('charmed', 'scenario:charm'), concentrate=True)
    execute(combat, mid)
    engine = reload(tmp_path, mid)
    psychic = packets(engine, 'PSYCHIC')
    saves = [e for e in engine.events if e.event_type == 'SAVE_ROLLED'
             and e.source_definition_id == 'system:combat.concentration']
    assert len(psychic) == 1 and saves
    assert psychic[0].sequence < saves[0].sequence


def test_changed_printed_text_falls_back_visibly():
    from combat.factory_compiler import _enchantment_on_hit
    row = {**ROWS['spirit_striking_inscription'], 'text': 'A different printed rule.'}
    assert _enchantment_on_hit([row])[0]['type'] == 'rider'


def test_flame_bonus_action_toggle_survives_cold_reload(tmp_path):
    combat, table, mid = scenario(tmp_path, 'flame_vein_inscription')
    execute(combat, mid, 'Extinguish Test treasure', target=OWNER)
    engine = reload(tmp_path, mid)
    assert not engine.state.actors[OWNER].bonus_action_available
    execute(combat, mid)
    engine = reload(tmp_path, mid)
    assert not packets(engine, 'FIRE')
    end_turn(table, mid)
    turn(table, mid, OWNER)
    execute(combat, mid, 'Ignite Test treasure', target=OWNER)
    reload(tmp_path, mid)
    execute(combat, mid)
    engine = reload(tmp_path, mid)
    assert len(packets(engine, 'FIRE')) == 1


@pytest.mark.parametrize('keys', [
    ['flame_vein_inscription', 'dream_piercing_inscription'],
    ['dream_piercing_inscription', 'flame_vein_inscription'],
])
def test_combined_enchantments_use_hit_time_dream_eligibility(tmp_path, keys):
    combat, _, mid = scenario(tmp_path, keys, setup=('dream_sleep', 'DREAMS_BASE_DREAM_SEED'))
    execute(combat, mid)
    engine = reload(tmp_path, mid)
    assert len(packets(engine, 'FIRE')) == 1
    assert len(packets(engine, 'PSYCHIC')) == 1


def test_combined_enchantments_finish_attached_damage_after_lethal_bonus(tmp_path):
    combat, _, mid = scenario(tmp_path,
        ['spirit_striking_inscription', 'flame_vein_inscription'], kind='Undead', foe_hp=1)
    execute(combat, mid)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[FOE].current_hp == 0
    assert len(packets(engine, 'PSYCHIC')) == 1
    assert len(packets(engine, 'FIRE')) == 1


def test_flame_status_and_log_name_item_and_explain_damage_and_duration(tmp_path):
    combat, _, mid = scenario(tmp_path, 'flame_vein_inscription')
    execute(combat, mid, 'Extinguish Test treasure', target=OWNER)
    engine = reload(tmp_path, mid)
    condition = next(c for c in engine.state.actors[OWNER].conditions.values()
                     if c.condition_id.startswith('condition:typed.treasure_flame_off.'))
    label = condition.data['label']
    assert 'Test treasure' in label
    assert '1d4 fire damage' in label
    assert 'Bonus Action' in label and 'until you ignite it' in label
    log = next(e.payload['log'] for e in reversed(engine.events)
               if e.event_type == 'PASSIVE_TRIGGERED' and 'extinguish' in e.payload.get('log', '').lower())
    assert 'Test treasure' in log and '1d4 fire damage' in log and 'Bonus Action' in log


def test_frost_cap_is_shared_across_bearers(tmp_path):
    combat, table, mid = scenario(tmp_path, 'frost_meridian_inscription', attacks=5,
                                  ally_key='frost_meridian_inscription')
    execute(combat, mid)
    engine = reload(tmp_path, mid)
    assert sum(int(m.value) for m in engine.state.actors[FOE].modifiers.values()
               if m.target_field == 'speed_ft') == -15
    end_turn(table, mid)
    turn(table, mid, ALLY)
    execute(combat, mid)
    engine = reload(tmp_path, mid)
    assert sum(int(m.value) for m in engine.state.actors[FOE].modifiers.values()
               if m.target_field == 'speed_ft') == -15


@pytest.mark.parametrize('key,kind', [('frost_meridian_inscription', 'COLD'),
    ('flame_vein_inscription', 'FIRE'), ('spirit_striking_inscription', 'PSYCHIC')])
def test_lethal_weapon_hits_still_deliver_enchantment_damage(tmp_path, key, kind):
    combat, _, mid = scenario(tmp_path, key, foe_hp=1, attacks=5)
    execute(combat, mid)
    engine = reload(tmp_path, mid)
    assert len(packets(engine, kind)) == 1
    assert engine.state.actors[FOE].current_hp == 0


def test_flame_state_is_specific_to_each_physical_weapon(tmp_path):
    combat, table, mid = scenario(tmp_path, 'flame_vein_inscription', ally_key='flame_vein_inscription')
    execute(combat, mid, 'Extinguish Test treasure', target=OWNER)
    reload(tmp_path, mid)
    end_turn(table, mid)
    turn(table, mid, ALLY)
    execute(combat, mid)
    engine = reload(tmp_path, mid)
    assert any(e.event_type == 'DAMAGE_COMMITTED' and e.actor_id == ALLY
               and e.payload.get('damage_type') == 'FIRE' for e in engine.events)
    end_turn(table, mid)
    turn(table, mid, OWNER)
    execute(combat, mid)
    engine = reload(tmp_path, mid)
    assert not packets(engine, 'FIRE')


@hook("damage_dealt")
def observe_treasure_damage_notification(ctx, subject, amount):
    observed = getattr(ctx.engine, "_test_treasure_damage_notifications", None)
    if observed is not None and ctx.actor.entity_id == OWNER:
        observed.append((subject.entity_id, amount))


def test_attached_bonus_notifies_actual_damage_once(tmp_path):
    combat, table, mid = scenario(tmp_path, 'spirit_striking_inscription', kind='Undead')
    loaded = combat._load_session(mid)
    engine = loaded.engine
    engine._test_treasure_damage_notifications = []
    c = next(c for c in engine.legal_candidates()
             if engine.action_catalog.get(c.source_definition_id) is not None
             and engine.action_catalog[c.source_definition_id].display_name == 'Test treasure attack'
             and c.target_ids == (FOE,))
    # Keep the observed live instance: CombatService reads a fresh session
    # on each _load_session, so the ordinary convenience helper would replace it.
    loaded.mechanical.execute_intent(ActionIntent(
        intent_id='intent:treasure:notification', decision_id=c.decision_id,
        candidate_id=c.candidate_id, state_version=c.state_version,
        actor_id=OWNER, target_ids=c.target_ids, destination=c.destination))
    actual = sum(int(e.payload.get('hp_damage') or 0) +
                 int(e.payload.get('temporary_hp_absorbed') or 0)
                 for e in engine.events if e.event_type == 'DAMAGE_COMMITTED'
                 and e.actor_id == OWNER and FOE in e.target_ids)
    assert actual > 0
    assert engine._test_treasure_damage_notifications == [(FOE, actual)]
    reload(tmp_path, mid)



JIGOKU_HELL_TEMPERED = 'tianxia.subpath.body.jigoku.feature.hell_tempered'


@pytest.mark.parametrize('attacker_mode,defender_mode', [
    ('MANUAL', 'MANUAL'),       # player attack, player-controlled Eat-the-Flame defender
    ('LOCAL_AUTO', 'MANUAL'),   # AI attack on a player-controlled defender
    ('MANUAL', 'LOCAL_AUTO'),   # player attack, AI defender decides automatically
])
def test_flame_vein_slashing_hit_still_offers_eat_the_flame_for_fire_damage(tmp_path, attacker_mode, defender_mode):
    modes = {OWNER: attacker_mode, ALLY: 'MANUAL', FOE: defender_mode}
    combat, table, mid = scenario(tmp_path, 'flame_vein_inscription', foe_mids=[JIGOKU_HELL_TEMPERED], modes=modes,
                                  foe_resists_fire=False, foe_primary='Stamina')
    before = combat._load_session(mid).engine.state.actors[FOE].resources['resource:core.stamina']
    c = candidate(combat, mid, 'Test treasure attack', target=FOE)
    prompts = settle(table, mid, c.candidate_id, {'choice:needle.eat_the_flame': 'eat'}, auto=attacker_mode == 'LOCAL_AUTO')
    engine = reload(tmp_path, mid)
    fire = packets(engine, 'FIRE')
    assert len(fire) == 1 and fire[0].payload['hp_damage'] >= 1
    eat_offers = [p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.eat_the_flame']
    foe = engine.state.actors[FOE]
    if defender_mode == 'MANUAL':
        assert len(eat_offers) == 1
    assert foe.temporary_hp == min(fire[0].payload['hp_damage'], 2 * foe.proficiency_bonus)
    assert before - foe.resources['resource:core.stamina'] == 1


# A general subscriber sees an effect by its own row and its recipient. It knows
# nothing about treasure weapons, so these two hooks stand in for any other
# plug-in that wants to refuse an effect or wrap its delivery.
DENIED_TYPES: set = set()
SCOPED_TYPES: set = set()
SCOPE_DELIVERIES: list = []


@hook("effect_allowed")
def deny_requested_effect_type(ctx, row):
    """False refuses one named effect type and nothing else; None has no opinion."""
    return False if row.get("type") in DENIED_TYPES else None


@hook("effect_resolution_scope")
def wrap_requested_effect_type(ctx, row):
    if row.get("type") not in SCOPED_TYPES:
        return None
    return record_delivery_inside_scope(ctx, row)


@contextmanager
def record_delivery_inside_scope(ctx, row):
    """Report which damage this effect actually landed while the scope was open."""
    events = ctx.engine.events
    first = len(events)
    yield
    SCOPE_DELIVERIES.append((row["type"], [
        e for e in events[first:] if e.event_type == 'DAMAGE_COMMITTED' and e.actor_id == OWNER]))


@pytest.fixture
def effect_contract():
    """Arm the general subscribers for one test; they stay inert otherwise."""
    yield
    DENIED_TYPES.clear()
    SCOPED_TYPES.clear()
    SCOPE_DELIVERIES.clear()


def test_permission_contract_refuses_the_pre_primary_bonus(tmp_path, effect_contract):
    """A refusal the general contract returns must stop the attached packet."""
    DENIED_TYPES.add('treasure_spirit_damage')
    combat, table, mid = scenario(tmp_path, 'spirit_striking_inscription', kind='Undead')
    execute(combat, mid)
    engine = reload(tmp_path, mid)
    assert not packets(engine, 'PSYCHIC')
    # The weapon's own damage still lands, so this is a refusal and not a miss.
    assert packets(engine, 'SLASHING')
    assert engine.state.actors[FOE].current_hp < 1000


def test_effect_resolution_scope_wraps_the_pre_primary_delivery(tmp_path, effect_contract):
    """A scope published for the original row must enclose the attached packet."""
    SCOPED_TYPES.add('treasure_spirit_damage')
    combat, table, mid = scenario(tmp_path, 'spirit_striking_inscription', kind='Undead')
    execute(combat, mid)
    engine = reload(tmp_path, mid)
    assert packets(engine, 'PSYCHIC')
    inside = [delivered for kind, delivered in SCOPE_DELIVERIES if kind == 'treasure_spirit_damage']
    assert inside, 'the effect never received a resolution scope'
    # The psychic packet was committed while that scope was open, not after it.
    assert any(str(e.payload.get('damage_type', '')).upper() == 'PSYCHIC' for e in inside[0])
