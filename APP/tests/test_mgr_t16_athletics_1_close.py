"""Assigned Close Quarters rows through table transactions and cold reload."""
import pytest
from combat import ext
from combat.gate2_runtime_models import ActionDefinition, EconomyKind
from combat.typed_executor import Context, run_effects
from tests.auto8f1_table_support import fixture, OWNER, FOE, SECOND, move_candidate_id, candidate_id, reload_identical
from tests.athletics_table_support import add_action

CQ = 'TAL_ATHLETICS_CLOSE_QUARTERS_TRAINING'


@ext.effect('test_t16_lift_foe')
def lift_foe(ctx, eff):
    from combat.falling import displace
    displace(ctx.engine, ctx.engine.state.actors[FOE], 1, ctx.source, intent=ctx.intent)


@ext.effect('test_t16_other_cover')
def other_cover_effect(ctx, eff):
    ctx.engine._apply_condition(ctx.actor, 'condition:test.t16.other_cover', ctx.source, ctx.actor.entity_id,
                                expires_on=None, data={'cover': 2})


@ext.hook('directional_cover')
def other_cover(engine, attacker, target, context):
    if any(c.condition_id == 'condition:test.t16.other_cover' for c in target.conditions.values()):
        return 2


@ext.effect('test_t16_outside_attack')
def outside_attack(ctx, eff):
    other = ctx.engine.state.actors[SECOND]
    typed = {'source': 'action:test.t16.outside', 'numbers': {'cl': 5, 'pb': 3},
             'weapon': {'properties': 'Metallic'}, 'effects': [], 'riders': []}
    action = ActionDefinition(source_definition_id=typed['source'], display_name='Outside attack', owner_id=SECOND,
        economy=EconomyKind.NONE, resolution_kind='TYPED', target_kind='HOSTILE_ENTITY')
    target = ctx.engine.state.actors[eff.get('target', OWNER)]
    sub = Context(ctx.engine, other, action, ctx.intent, typed, [target], target)
    run_effects(sub, [{'type': 'attack', 'attack_kind': 'weapon_melee', 'attack_bonus': 10,
                      'reach_ft': 30, 'count': eff.get('count', 1),
                      'on_miss': eff.get('on_miss', []),
                      'on_hit': [{'type': 'damage', 'flat': 3, 'damage_types': ['bludgeoning']}]}])


def game(tmp_path, *, win=True, owned=True, size='Medium', transfer=False, airborne=False,
         talents_by_actor=None, bundle_transform=None):
    def prepare(bs):
        for b in bs:
            who = b['actor_id']
            b.setdefault('skills', {})['Acrobatics'] = 100 if who == OWNER and win else -100
            b['skills']['Athletics'] = (-100 if win else 100) if who != OWNER else 0
            if who == FOE:
                b['actor_template']['size_category'] = size
            if transfer and who in (OWNER, FOE):
                b['actor_template']['armor_class'] = 20 if who == OWNER else 1
            if airborne and who in (OWNER, FOE):
                b['actor_template']['fly_speed_ft'] = 30
            if who == OWNER:
                for kind in ('weapon_melee', 'light', 'unarmed', 'natural'):
                    add_action(b, 'Test '+kind, [{'type': 'attack', 'attack_kind': 'weapon_melee' if kind == 'light' else kind, 'attack_bonus': 100,
                        'reach_ft': 5, 'on_hit': []}])
                    if kind == 'light':
                        b['action_catalog'][-1]['parameters']['typed']['weapon'] = {'properties': 'Light'}
                    b['action_catalog'][-1]['target_kind'] = 'HOSTILE_ENTITY'
                    b['action_catalog'][-1]['reach_ft'] = 5
                add_action(b, 'Outside attack', [{'type': 'test_t16_outside_attack'}])
                add_action(b, 'Outside foe attack', [{'type': 'test_t16_outside_attack', 'target': FOE}])
                add_action(b, 'Lift foe', [{'type': 'test_t16_lift_foe'}])
                add_action(b, 'Add independent cover', [{'type': 'test_t16_other_cover'}])
        if bundle_transform:
            bundle_transform(bs)
    return fixture(tmp_path, [CQ] if owned else [], seed='T16-CQ-'+tmp_path.name, bundle_transform=prepare,
        places={OWNER: {'x': 3, 'y': 6}, FOE: {'x': 4, 'y': 6}, SECOND: {'x': 3, 'y': 8}},
        ask_actors=(FOE,), talents_by_actor=talents_by_actor)


def enter(g, chooser=None):
    g['commit'](move_candidate_id(g['menu'](), 4, 6), chooser)
    reload_identical(g['combat'], g['match_id'], g['userdata'])


def test_enter_stop_fight_and_move_through_shared_hostile_space(tmp_path):
    g = game(tmp_path)
    enter(g)
    actor = g['reload_owner']()
    assert (actor.position.x, actor.position.y) == (4, 6)
    assert any(c.data.get('target_id') == FOE for c in actor.conditions.values())
    g['commit'](candidate_id(g['menu'](), 'Test unarmed'))
    g['commit'](move_candidate_id(g['menu'](), 5, 6))
    assert not any(c.condition_id == 'condition:typed.close_quarters_shared' for c in g['reload_owner']().conditions.values())
    reload_identical(g['combat'], g['match_id'], g['userdata'])


@pytest.mark.parametrize('skill', ['athletics', 'acrobatics'])
def test_entry_uses_dex_acrobatics_and_defender_chooses_skill(tmp_path, skill):
    g = game(tmp_path)
    seen = []
    def choose(p, c):
        seen.append((p['context']['reactor_id'], [o['id'] for o in c['options']]))
        return [skill] if skill in [o['id'] for o in c['options']] else [c['options'][0]['id']]
    enter(g, choose)
    assert any(who == FOE and set(opts) == {'athletics', 'acrobatics'} for who, opts in seen)
    check = next(e for e in g['stored_engine']().events if e.event_type == 'CHECK_ROLLED' and e.source_definition_id == CQ)
    assert check.payload['actor']['mode'] == 'NORMAL'
    assert check.payload['success']


@pytest.mark.parametrize('use', [False, True])
def test_failed_entry_stays_previous_space_and_optional_oa(tmp_path, use):
    g = game(tmp_path, win=False)
    def choose(p, c):
        ids = [o['id'] for o in c['options']]
        return (['use'] if use else []) if ids == ['use'] else ['athletics']
    enter(g, choose)
    actor = g['reload_owner']()
    assert (actor.position.x, actor.position.y) == (3, 6)
    foe = g['stored_engine']().state.actors[FOE]
    assert foe.reaction_available is not use
    attacks = [e for e in g['stored_engine']().events if e.event_type == 'ATTACK_ROLLED' and e.actor_id == FOE]
    assert bool(attacks) is use


@pytest.mark.parametrize('kind,mode', [('weapon_melee', 'DISADVANTAGE'), ('light', 'NORMAL'), ('unarmed', 'NORMAL'), ('natural', 'NORMAL')])
def test_shared_space_attacks_have_three_printed_weapon_exemptions(tmp_path, kind, mode):
    g = game(tmp_path)
    enter(g)
    g['commit'](candidate_id(g['menu'](), 'Test '+kind))
    event = [e for e in g['stored_engine']().events if e.event_type == 'ATTACK_ROLLED'][-1]
    assert event.payload['mode'] == mode
    reload_identical(g['combat'], g['match_id'], g['userdata'])


@pytest.mark.parametrize('size,own,foe', [('Medium', 2, 2), ('Large', 5, 0), ('Small', 0, 5)])
def test_same_size_mutual_and_different_size_asymmetric_cover(tmp_path, size, own, foe):
    g = game(tmp_path, size=size)
    enter(g)
    engine = g['stored_engine']()
    from combat.ext.athletics import close_cover
    assert close_cover(engine, engine.state.actors[SECOND], engine.state.actors[OWNER], {}) == own
    assert close_cover(engine, engine.state.actors[SECOND], engine.state.actors[FOE], {}) == foe
    assert close_cover(engine, engine.state.actors[FOE], engine.state.actors[OWNER], {}) is None
    g['commit'](candidate_id(g['menu'](), 'Outside attack'))
    event = [e for e in g['stored_engine']().events if e.event_type == 'ATTACK_ROLLED' and e.actor_id == SECOND][-1]
    assert event.payload['cover_bonus'] == own
    g['commit'](candidate_id(g['menu'](), 'Outside foe attack'))
    event = [e for e in g['stored_engine']().events if e.event_type == 'ATTACK_ROLLED' and e.actor_id == SECOND][-1]
    assert event.payload['cover_bonus'] == foe
    reload_identical(g['combat'], g['match_id'], g['userdata'])


def test_cover_caused_miss_transfers_original_roll_through_table(tmp_path, monkeypatch):
    g = game(tmp_path, transfer=True)
    enter(g)
    from combat.gate2_rolls import DeterministicRollAuthority as Roller
    raw = Roller.raw_d20
    draws = []
    ac = g['reload_owner']().armor_class
    def roll(self, **kwargs):
        result = raw(self, **kwargs)
        if kwargs['reason'].startswith('ATTACK:') and kwargs['actor_id'] == SECOND:
            draws.append(result.roll_id)
            return result.model_copy(update={'natural_result': 10, 'dice': (10,), 'total': ac})
        return result
    monkeypatch.setattr(Roller, 'raw_d20', roll)
    g['commit'](candidate_id(g['menu'](), 'Outside attack'))
    engine = g['stored_engine']()
    transfers = [e for e in engine.events if e.event_type == 'PASSIVE_TRIGGERED' and e.payload.get('attack_redirected')]
    assert len(transfers) == 1 and transfers[0].target_ids == (FOE,)
    # Preview/commit/replay draw the same deterministic id; a second attack die
    # would create a second distinct id and a second committed attack event.
    assert len(set(draws)) == 1 and transfers[0].payload['roll_id'] == draws[0]
    assert len([e for e in engine.events if e.event_type == 'ATTACK_ROLLED' and e.actor_id == SECOND]) == 1
    # This synthetic weapon uses the native fallback weapon die (1d4) + 3.
    # Its damage must reach the new recipient, never the covered original.
    assert 4 <= engine.state.actors[FOE].maximum_hp - engine.state.actors[FOE].current_hp <= 7
    assert engine.state.actors[OWNER].current_hp == engine.state.actors[OWNER].maximum_hp
    reload_identical(g['combat'], g['match_id'], g['userdata'])


def test_nonowner_has_no_occupied_destination(tmp_path):
    g = game(tmp_path, owned=False)
    with pytest.raises(AssertionError):
        move_candidate_id(g['menu'](), 4, 6)


def test_equal_independent_cover_does_not_transfer_a_miss(tmp_path, monkeypatch):
    g = game(tmp_path, transfer=True)
    enter(g)
    g['commit'](candidate_id(g['menu'](), 'Add independent cover'))
    from combat.gate2_rolls import DeterministicRollAuthority as Roller
    raw = Roller.raw_d20
    def roll(self, **kwargs):
        result = raw(self, **kwargs)
        return result.model_copy(update={'natural_result': 10, 'dice': (10,), 'total': 20}) if kwargs['actor_id'] == SECOND and kwargs['reason'].startswith('ATTACK:') else result
    monkeypatch.setattr(Roller, 'raw_d20', roll)
    g['commit'](candidate_id(g['menu'](), 'Outside attack'))
    engine = g['stored_engine']()
    assert not any(e.payload.get('attack_redirected') for e in engine.events)
    assert engine.state.actors[FOE].current_hp == engine.state.actors[FOE].maximum_hp
    reload_identical(g['combat'], g['match_id'], g['userdata'])


def test_shared_space_survives_turn_boundaries_and_cold_reload(tmp_path):
    g = game(tmp_path)
    enter(g)
    for _ in range(3):
        g['commit'](g['menu']()['end_turn'])
    actor = g['reload_owner']()
    assert (actor.position.x, actor.position.y) == (4, 6)
    assert any(c.condition_id == 'condition:typed.close_quarters_shared' for c in actor.conditions.values())
    reload_identical(g['combat'], g['match_id'], g['userdata'])


def test_shared_space_entry_remains_reachable_for_airborne_native_routes(tmp_path):
    g = game(tmp_path, airborne=True)
    g['commit'](candidate_id(g['menu'](), 'Lift foe'))
    move = next(row for row in g['menu']()['moves'] if row['destination'] == {'x': 4, 'y': 6, 'z': 1})
    g['commit'](move['candidate_id'])
    assert g['reload_owner']().position.z == 1
    assert any(c.condition_id == 'condition:typed.close_quarters_shared' for c in g['reload_owner']().conditions.values())
    reload_identical(g['combat'], g['match_id'], g['userdata'])


@pytest.mark.parametrize('defender_ai', [False, True])
def test_defender_chooses_on_ai_movers_turn_or_automatically_for_ai(tmp_path, defender_ai):
    from combat.gate4_adapters import ManualControllerAdapter
    from tests.worker2_support import settle
    g = game(tmp_path)
    combat = g['combat']
    cid = move_candidate_id(g['menu'](), 4, 6)
    combat.set_controller_mode(g['match_id'], actor_id=OWNER, controller_mode='LOCAL_AUTO')
    if defender_ai:
        combat.set_controller_mode(g['match_id'], actor_id=FOE, controller_mode='LOCAL_AUTO')
    real = combat.controller
    combat.controller = ManualControllerAdapter(lambda context: (cid, ()),
        reaction_chooser=lambda context: real.choose_reaction(context).decision)
    prompts = settle(g['table'], g['match_id'], cid, choices={}, auto=True)
    assert bool(prompts) is not defender_ai
    assert g['reload_owner']().position.x == 4
    reload_identical(combat, g['match_id'], g['userdata'])
