"""Recipient-dependent primary damage and actual cover suppliers at the table."""
import pytest

from combat import ext
from combat.gate2_runtime_models import ActionDefinition, EconomyKind
from combat.typed_executor import Context, run_effects
from combat.ext.death_riders import GRAVE_MARK, MARK_DAMAGE_RULE
from tests.auto8f1_table_support import OWNER, FOE, SECOND, fixture, candidate_id, move_candidate_id, reload_identical
from tests.test_a2_athletics_second_pass import add_action
from tests.test_mgr_t16_athletics_1_close import game, enter, CQ
from tests.test_mgr_t16_athletics_1_review_fixes import original_roll


@ext.effect('test_t16_fx2_mark')
def mark(ctx, eff):
    target = ctx.engine.state.actors[eff['target']]
    ctx.engine._apply_condition(target, GRAVE_MARK + '.' + SECOND,
        'TAL_DEATH_MARK_FOR_THE_GRAVE', SECOND, expires_on=None, data={})


@ext.effect('test_t16_fx2_necrotic')
def necrotic(ctx, eff):
    attacker, target = (ctx.engine.state.actors[who] for who in (eff.get('attacker', SECOND), OWNER))
    typed = {'source': 'action:test.t16.fx2.necrotic', 'numbers': {'cl': 5, 'pb': 3}}
    action = ActionDefinition(source_definition_id=typed['source'], display_name='Necrotic test attack',
        owner_id=attacker.entity_id, economy=EconomyKind.NONE, resolution_kind='TYPED', target_kind='HOSTILE_ENTITY')
    child = Context(ctx.engine, attacker, action, ctx.intent, typed, [target], target)
    run_effects(child, [{'type': 'attack', 'attack_kind': 'spell_ranged', 'attack_bonus': 10,
        'range_ft': 30, 'count': eff.get('count', 2),
        'on_hit': [{'type': 'damage', 'dice': {'count': 1, 'sides': 4}, 'flat': 3, 'damage_types': ['necrotic']}]}])


@pytest.mark.parametrize('marked', [OWNER, FOE])
def test_primary_bonus_eligibility_and_turn_gate_follow_recipient(tmp_path, monkeypatch, marked):
    def prepare(bs):
        owner = next(b for b in bs if b['actor_id'] == OWNER)
        add_action(owner, 'Mark test creature', [{'type': 'test_t16_fx2_mark', 'target': marked}])
        add_action(owner, 'Two necrotic attacks', [{'type': 'test_t16_fx2_necrotic'}])
    g = game(tmp_path, transfer=True, talents_by_actor={SECOND: ['TAL_DEATH_MARK_FOR_THE_GRAVE']},
             bundle_transform=prepare)
    enter(g)
    g['commit'](candidate_id(g['menu'](), 'Mark test creature'))
    reload_identical(g['combat'], g['match_id'], g['userdata'])
    owner_hp_before = g['reload_owner']().current_hp
    original_roll(monkeypatch)
    g['commit'](candidate_id(g['menu'](), 'Two necrotic attacks'))
    engine = g['stored_engine']()
    foe, owner, attacker = (engine.state.actors[who] for who in (FOE, OWNER, SECOND))
    assert len([e for e in engine.events if e.payload.get('attack_redirected')]) == 2
    from combat.ext.passive_rows import row_of
    pb = row_of(engine, SECOND, 'auto22_death', 'grave_mark')['pb']
    damage = [e.payload for e in engine.events if e.event_type == 'DAMAGE_ROLLED'
              and e.source_definition_id == 'action:test.t16.fx2.necrotic']
    assert [r['modifier'] for r in damage] == [3 + (pb if marked == FOE else 0), 3]
    assert foe.maximum_hp - foe.current_hp == sum(r['total'] for r in damage)
    assert owner.current_hp == owner_hp_before
    assert any(MARK_DAMAGE_RULE in key for key in attacker.turn_flags) == (marked == FOE)
    rolls = [e for e in engine.events if e.event_type == 'ATTACK_ROLLED' and e.actor_id == SECOND]
    assert len(rolls) == 2 and all(e.target_ids == (OWNER,) for e in rolls)
    reload_identical(g['combat'], g['match_id'], g['userdata'])


def test_transfer_selects_huge_cover_supplier_over_first_medium_contact(tmp_path, monkeypatch):
    from combat.gate2_runtime_content import AN
    from combat.gate2_engine import Gate2Engine
    from combat.dynamic_size import shape
    from combat.ext.athletics import close_cover, close_contact
    # Factory fixtures retain historical 1x1 base footprint authority. Supply
    # native Large/Huge geometry at the query seam, consistently on reload;
    # this tests partial contacts without temporary-growth placement rules.
    original_footprint = Gate2Engine._footprint
    def footprint(engine, actor):
        who = actor if isinstance(actor, str) else actor.entity_id
        base = original_footprint(engine, actor)
        return shape(base, {OWNER: 'Large', SECOND: 'Huge'}[who]) if who in (OWNER, SECOND) else base
    monkeypatch.setattr(Gate2Engine, '_footprint', footprint)
    def prepare(bs):
        for b in bs:
            b.setdefault('skills', {})['Acrobatics'] = 100 if b['actor_id'] == OWNER else -100
            b['skills']['Athletics'] = -100
            if b['actor_id'] == OWNER:
                b['actor_template'].update(size_category='Large', armor_class=20)
                add_action(b, 'Outside attack', [{'type': 'test_t16_fx2_necrotic', 'attacker': AN, 'count': 1}])
    # Large owner enters two disjoint contacts: Medium FOE first by id,
    # then Huge SECOND. The stock fighter AN attacks from outside both.
    def sizes(bs):
        prepare(bs)
        next(b for b in bs if b['actor_id'] == SECOND)['actor_template'].update(size_category='Huge', armor_class=1)
    g = fixture(tmp_path, [CQ], seed='T16-FX2-multi', bundle_transform=sizes,
        places={OWNER: {'x': 2, 'y': 6}, FOE: {'x': 4, 'y': 6}, SECOND: {'x': 5, 'y': 6}},
        legacy_foes={AN: {'x': 3, 'y': 10}})
    g['commit'](move_candidate_id(g['menu'](), 4, 6))
    reload_identical(g['combat'], g['match_id'], g['userdata'])
    engine = g['stored_engine']()
    owner, medium, huge, outside = (engine.state.actors[who] for who in (OWNER, FOE, SECOND, AN))
    assert FOE < SECOND
    assert close_contact(engine, owner, medium) and close_contact(engine, owner, huge)
    assert not set(engine._actor_volume(medium)) & set(engine._actor_volume(huge))
    assert close_cover(engine, outside, owner, {}) == 5
    from combat.gate2_rolls import DeterministicRollAuthority as Roller
    raw = Roller.raw_d20
    def roll(self, **kwargs):
        result = raw(self, **kwargs)
        if kwargs['actor_id'] == AN and kwargs['reason'].startswith('ATTACK:'):
            return result.model_copy(update={'natural_result': 10, 'dice': (10,), 'total': 20})
        return result
    monkeypatch.setattr(Roller, 'raw_d20', roll)
    g['commit'](candidate_id(g['menu'](), 'Outside attack'))
    engine = g['stored_engine']()
    transfers = [e for e in engine.events if e.payload.get('attack_redirected')]
    assert len(transfers) == 1 and transfers[0].target_ids == (SECOND,)
    assert engine.state.actors[FOE].current_hp == medium.current_hp
    assert engine.state.actors[SECOND].current_hp < huge.current_hp
    reload_identical(g['combat'], g['match_id'], g['userdata'])
