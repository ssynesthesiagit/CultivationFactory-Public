"""Roll reasons through a table commit and cold reload, without changing modes."""
import pytest

from combat import ext
from combat.gate5_service import CombatService
from combat.gate2_runtime_models import Position, ActionDefinition, EconomyKind
from combat.history_feed import _roll_text
from combat.roll_reasons import attack_preview, standing
from tests.h1_support import ROOT
from tests.test_hidden_targeting import table_fight, turn, LEFT, RIGHT
from tests.test_lock2_persistence import act
from tests.test_lock_choices import install
from tests.test_c3ar_runtime_executability import adapter, bundle, runtime_package

CANOPY = 'TAL_VERDANT_GROWTH_CANOPY_OF_TEN_THOUSAND_LEAVES'


@pytest.mark.parametrize('case,expected,words', [
    ('prone_near', 'ADVANTAGE', 'within 5 feet'),
    ('prone_far', 'DISADVANTAGE', 'more than 5 feet'),
    ('cancel', 'NORMAL', 'cancels'),
    ('obscured', 'DISADVANTAGE', 'cannot see'),
    ('canopy', 'DISADVANTAGE', '10+ feet of canopy'),
    ('light_obscured', 'NORMAL', ''),
    ('save', 'DISADVANTAGE', 'Dexterity'),
    ('concentration', 'DISADVANTAGE', 'maintain Concentration'),
    ('check', 'DISADVANTAGE', 'Wisdom check'),
])
def test_sources_payload_render_and_cold_reload(tmp_path, monkeypatch, case, expected, words):
    from combat import targeting
    # Isolate the d20 explanation from the separate percentile concealment miss.
    monkeypatch.setattr(targeting, 'concealment_percent', lambda *_: 0)
    near = case in ('prone_near', 'cancel')
    combat, table, mid = table_fight(tmp_path, left_at=(3, 11), right_at=(4 if near else 11, 11),
                                    left_abilities=[CANOPY])
    turn(table, mid, LEFT)
    errors = []

    def resolve(engine, kind, kwargs):
        if kind != 'HOLD_POSITION_COMMITTED' or kwargs.get('actor_id') != LEFT:
            return
        actor, target = engine.state.actors[LEFT], engine.state.actors[RIGHT]
        if case.startswith('prone') or case == 'cancel':
            engine._apply_condition(target, 'condition:typed.prone', 'test:prone', RIGHT, expires_on='UNTIL_REMOVED')
        if case == 'cancel':
            engine._apply_condition(actor, 'condition:typed.poisoned', 'test:poison', RIGHT, expires_on='UNTIL_REMOVED')
        if case == 'save':
            engine._apply_condition(actor, 'condition:typed.restrained', 'test:restrain', RIGHT, expires_on='UNTIL_REMOVED')
            engine._roll_save(actor, 'DEX', 12, 'test:save')
            return
        if case == 'concentration':
            from combat.concentration import MODE
            engine._apply_condition(actor, MODE, 'test:concentration', RIGHT, expires_on='UNTIL_REMOVED',
                                    data={'rule': {'concentration_mode': 'DISADVANTAGE', 'next': 1}})
            engine._start_concentration(actor, 'test:concentrating')
            engine._concentration_check(actor, 10)
            return
        if case == 'check':
            engine._apply_condition(actor, 'condition:typed.poisoned', 'test:poison', RIGHT, expires_on='UNTIL_REMOVED')
            roll = engine.roll_check(modifier=2, actor_id=LEFT, reason='CHECK:test:perception', ability='WIS', skill='Perception')
            engine._record_roll(roll)
            engine._append_event('CHECK_ROLLED', 'test:perception', actor_id=LEFT, payload=roll.model_dump(mode='json'))
            return
        if case in ('canopy', 'obscured', 'light_obscured'):
            action = next(a for a in engine.action_catalog.values()
                          if a.owner_id == LEFT and (a.parameters.get('typed') or {}).get('source') == CANOPY)
            cells = tuple(Position(x=x, y=y) for x in range(5, 12) for y in range(9, 14))
            from combat import zones, typed_executor as te
            ctx = te.Context(engine, actor, action, engine._active_intent, action.parameters['typed'], [target], target, {})
            if case == 'light_obscured':
                # Use another real source so this case tests light obscurement
                # without Canopy's separately printed ranged-path penalty.
                other = next(a for a in engine.action_catalog.values() if a.owner_id == RIGHT)
                ctx = te.Context(engine, target, other, engine._active_intent, other.parameters.get('typed') or {}, [target], target, {})
            zones.create(ctx, {'shape': 'sphere', 'size_ft': 20, 'cells': cells,
                'duration': {'kind': 'rounds', 'amount': 3}, 'name': 'Canopy of Ten Thousand Leaves',
                'obscured': 'heavy' if case == 'obscured' else 'light'})
        action = ActionDefinition(source_definition_id='test:rollreason-strike', display_name='Test strike',
            owner_id=LEFT, economy=EconomyKind.NONE, resolution_kind='ATTACK', target_kind='HOSTILE_ENTITY',
            attack_bonus=-100, range_ft=None if near else 120, reach_ft=5,
            parameters={'attack_kind': 'weapon_melee' if near else 'weapon_ranged'})
        before = engine.state.model_dump(mode='json')
        preview = attack_preview(engine, actor, target, action)
        assert engine.state.model_dump(mode='json') == before
        if case.startswith('prone') or case == 'cancel':
            assert preview['mode'] == expected
            assert standing(engine, target)
        engine._resolve_attack_spec(actor, target,
            {'attack_bonus': -100, 'range_ft': None if near else 120, 'reach_ft': 5,
             'attack_profile': 'weapon_melee' if near else 'weapon_ranged'},
            engine._active_intent, source_definition_id='test:rollreason-strike')

    def checked_resolve(*args):
        try:
            resolve(*args)
        except Exception as exc:
            import traceback
            errors.append(traceback.format_exc())
            raise
    install(monkeypatch, 'event', checked_resolve)
    assert act(table, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    assert not errors, errors
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    kind = 'SAVE_ROLLED' if case in ('save', 'concentration') else 'CHECK_ROLLED' if case == 'check' else 'ATTACK_ROLLED'
    payload = next(e.payload for e in reversed(loaded.engine.events) if e.event_type == kind)
    assert payload['mode'] == expected
    if case == 'light_obscured':
        assert not payload.get('mode_sources')
        return
    assert payload['mode_sources']
    assert len(payload['mode_sources']) == len({tuple(sorted(row.items())) for row in payload['mode_sources']})
    rendered = _roll_text(payload)
    assert words.lower() in rendered.lower(), rendered
    if case == 'canopy':
        assert any(s['effect'] == 'Canopy of Ten Thousand Leaves' and s['owner'] == 'Left' for s in payload['mode_sources'])
    if case == 'cancel':
        assert {s['kind'] for s in payload['mode_sources']} == {'advantage', 'disadvantage'}
    roll = next(r for r in loaded.engine.rolls if r.roll_id == payload['roll_id'])
    assert roll.mode_sources == payload['mode_sources']


def test_ordinary_dice_keep_shape():
    from combat.gate2_runtime_models import RollRecord
    roll = RollRecord(roll_id='r', counter_start=0, counter_end=1, expression='1d20', actor_id='a',
                      reason='INITIATIVE', dice=(7,), modifier=0, total=7, natural_result=7)
    assert 'mode_sources' not in roll.model_dump(mode='json')


def test_nested_unscoped_roll_cannot_borrow_outer_sources():
    from tests import lock8_support as S
    from combat.roll_reasons import remember, source
    e = S.fight(S.bundle('SAND_BASE_SCOURING_HAND'))
    e._apply_condition(e.state.actors[S.ME], 'condition:typed.poisoned', 'test:poison', S.FOE,
                       expires_on='UNTIL_REMOVED')
    with e.d20_scope({'kind': 'attack', 'actor_id': S.ME, 'target_id': S.FOE, 'source_id': 'test:outer'}):
        remember(e, [source(e, 'DISADVANTAGE', effect='Outer attack effect')])
        e._attack_mode(e.state.actors[S.ME], e.state.actors[S.FOE])
        assert [r['effect'] for r in e.d20_context()['mode_sources']] == ['Outer attack effect']
        inner = e.roller.d20(modifier=0, actor_id=S.FOE, reason='CHECK:inner', mode='ADVANTAGE')
        assert all(r['effect'] != 'Outer attack effect' for r in inner.mode_sources)
        outer = e.roller.d20(modifier=0, actor_id=S.ME, reason='ATTACK:test:outer:1', mode='DISADVANTAGE')
        assert outer.mode_sources[0]['effect'] == 'Outer attack effect'


def test_equal_rules_keep_both_condition_sources():
    from tests import lock8_support as S
    e = S.fight(S.bundle('SAND_BASE_SCOURING_HAND'))
    actor = e.state.actors[S.ME]
    for suffix in ('first', 'second'):
        e._apply_condition(actor, 'condition:typed.test_' + suffix, 'test:' + suffix, S.FOE,
                           expires_on='UNTIL_REMOVED', data={'rule': {'check_mode': {'ALL': 'DISADVANTAGE'}}})
    roll = e.roll_check(modifier=0, actor_id=S.ME, reason='CHECK:test:equal', ability='WIS')
    assert roll.mode == 'DISADVANTAGE'
    assert {r['effect'] for r in roll.mode_sources} == {'Test first', 'Test second'}


def test_preview_reports_long_range_without_drawing_or_consuming():
    from tests import lock8_support as S
    e = S.fight(S.bundle('SAND_BASE_SCOURING_HAND'), foe_at=(10, 6))
    action = ActionDefinition(source_definition_id='test:bow', display_name='Bow', owner_id=S.ME,
        economy=EconomyKind.NONE, resolution_kind='ATTACK', target_kind='HOSTILE_ENTITY', range_ft=120,
        parameters={'typed': {'range_ft': 20, 'long_range_ft': 120,
                             'effects': [{'type': 'attack', 'attack_kind': 'weapon_ranged'}]}})
    before = e.state.model_dump(mode='json'), e.roller.counter, len(e.events)
    preview = attack_preview(e, e.state.actors[S.ME], e.state.actors[S.FOE], action)
    assert preview['mode'] == 'DISADVANTAGE'
    assert 'normal range' in preview['text']
    assert (e.state.model_dump(mode='json'), e.roller.counter, len(e.events)) == before


def test_portable_attack_keeps_cancelled_sources(bundle):
    from tests.test_c3ar_runtime_executability import runtime_engine, SOURCE_ACTOR_ID
    from types import SimpleNamespace
    e = runtime_engine(bundle)
    e._active_intent = SimpleNamespace(intent_id='test:rollreason-portable')
    actor, target = e.state.actors[SOURCE_ACTOR_ID], e.state.actors['dummy:target']
    e._apply_condition(actor, 'condition:typed.poisoned', 'test:poison', target.entity_id, expires_on='UNTIL_REMOVED')
    e._apply_condition(target, 'condition:typed.prone', 'test:prone', actor.entity_id, expires_on='UNTIL_REMOVED')
    e._resolve_character_attack(actor, target, source_id='test:portable', attack_bonus=-100,
                                damage=None, damage_type='BLUDGEONING', fixed_damage=0,
                                intent=e._active_intent, ranged=False)
    payload = next(event.payload for event in reversed(e.events) if event.event_type == 'ATTACK_ROLLED')
    assert payload['mode'] == 'NORMAL'
    assert {row['effect'] for row in payload['mode_sources']} == {'Poisoned', 'Prone'}
    assert payload['mode_sources'] == sorted(payload['mode_sources'],
        key=lambda row: (row['kind'], row['effect'], row['owner'], row['why']))


def test_browser_roll_hover_opt_in():
    """Lead-only check against a prepared table with a recorded canopy roll."""
    import os
    url = os.environ.get('CF_ROLLREASON_BROWSER_URL')
    if not url:
        pytest.skip('Lead must set CF_ROLLREASON_BROWSER_URL and run outside the sandbox')
    from playwright.sync_api import sync_playwright, expect
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path='/usr/bin/chromium', args=['--no-sandbox'])
        try:
            page = browser.new_page()
            page.goto(url)
            expected = os.environ.get('CF_ROLLREASON_EXPECT_SOURCE', 'Canopy of Ten Thousand Leaves')
            roll = page.locator('#ttFeed li.is-roll').filter(has_text=expected).first
            expect(roll).to_be_visible(timeout=15000)
            assert expected in roll.get_attribute('title')
            assert 'Disadvantage' in roll.get_attribute('title')
        finally:
            browser.close()


def test_javascript_target_previews():
    import subprocess
    from pathlib import Path
    subprocess.run(['node', '--test', str(Path(__file__).with_name('tabletop_target_selection.test.mjs'))], check=True)


@pytest.mark.parametrize('case,expected', [
    ('later_cancel', 'NORMAL'),
    ('same_kind_bare', 'DISADVANTAGE'),
    ('same_kind_named', 'DISADVANTAGE'),
])
def test_later_checkpoint_and_same_kind_contributions_through_reload(tmp_path, monkeypatch, case, expected):
    """A later answer cancels with its name kept; independent same-kind effects both stay stated."""
    from combat import targeting
    from combat.history_feed import _roll_text
    from tests.test_lock_choices import install
    monkeypatch.setattr(targeting, 'concealment_percent', lambda *_: 0)
    combat, table, mid = table_fight(tmp_path, left_at=(3, 11), right_at=(4, 11))
    turn(table, mid, LEFT)
    if case == 'later_cancel':
        install(monkeypatch, 'before_attack', lambda *args: {
            'mode': 'ADVANTAGE', 'effect': 'Rallying Standard',
            'why': 'the banner answer gives this attack Advantage'})
    else:
        reply = ({'mode': 'DISADVANTAGE', 'effect': 'Steady Stance', 'owner': 'Right',
                  'why': 'the stance talent penalizes this attack'}
                 if case == 'same_kind_named' else {'mode': 'DISADVANTAGE'})
        install(monkeypatch, 'attack_mode_contribution', lambda *args, **kwargs: reply)
    errors = []

    def resolve(engine, kind, kwargs):
        if kind != 'HOLD_POSITION_COMMITTED' or kwargs.get('actor_id') != LEFT:
            return
        actor, target = engine.state.actors[LEFT], engine.state.actors[RIGHT]
        engine._apply_condition(actor, 'condition:typed.poisoned', 'test:poison', RIGHT,
                                expires_on='UNTIL_REMOVED')
        engine._resolve_attack_spec(actor, target,
            {'attack_bonus': -100, 'range_ft': None, 'reach_ft': 5, 'attack_profile': 'weapon_melee'},
            engine._active_intent, source_definition_id='test:rollreason-strike')

    def checked_resolve(*args):
        try:
            resolve(*args)
        except Exception:
            import traceback
            errors.append(traceback.format_exc())
            raise
    install(monkeypatch, 'event', checked_resolve)
    assert act(table, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    assert not errors, errors
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    payload = next(e.payload for e in reversed(loaded.engine.events) if e.event_type == 'ATTACK_ROLLED')
    effects = {row['effect'] for row in payload.get('mode_sources', [])}
    if case == 'later_cancel':
        assert payload['mode'] == 'NORMAL'
        assert {'Poisoned', 'Rallying Standard'} <= effects
        assert 'cancels' in _roll_text(payload)
    else:
        assert payload['mode'] == 'DISADVANTAGE'
        assert 'Poisoned' in effects
        if case == 'same_kind_bare':
            assert 'Attack-specific effect' in effects
        else:
            assert 'Steady Stance' in effects
    receipts = payload['mode_sources']
    assert len(receipts) == len({tuple(sorted(row.items())) for row in receipts})
    roll = next(r for r in loaded.engine.rolls if r.roll_id == payload['roll_id'])
    assert roll.mode_sources == receipts


def test_native_reaction_only_cancel_explains_both_later_sources(monkeypatch, tmp_path):
    """A bare checkpoint answer and a bare native reply each keep a receipt when they cancel."""
    from tests.test_lock13_native_opportunity import fight, move, checked, OA
    from tests.test_lock_choices import install
    from tests.test_lock2_persistence import act
    svc, table, mid = fight(tmp_path)
    install(monkeypatch, 'before_attack', lambda *args: {'mode': 'DISADVANTAGE'})
    install(monkeypatch, 'native_reaction_roll_mode', lambda engine, context: 'ADVANTAGE')
    move(svc, table, mid)
    engine = checked(svc, tmp_path, mid)
    attack = next(e for e in engine.events
                  if e.event_type == 'ATTACK_ROLLED' and e.source_definition_id == OA)
    assert attack.payload['mode'] == 'NORMAL'
    effects = {row['effect'] for row in attack.payload['mode_sources']}
    assert {'Choice before the roll', 'Triggered reaction'} <= effects
    assert 'cancels' in _roll_text(attack.payload)
    roll = next(r for r in engine.rolls if r.roll_id == attack.payload['roll_id'])
    assert roll.mode_sources == attack.payload['mode_sources']


def test_standing_attack_mode_vs_names_its_target_only():
    from tests import lock8_support as S
    e = S.fight(S.bundle('SAND_BASE_SCOURING_HAND'))
    me = e.state.actors[S.ME]
    e._add_modifier(me, 'test:vex', 'attack_mode_vs', 'SET', f'ADVANTAGE:{S.FOE}',
                    'NEXT_ATTACK', expires_on=None)
    rows = standing(e, me)
    foe_name = e.state.actors[S.FOE].display_name
    assert any(f'Your attacks against {foe_name} only' in row and 'Advantage' in row for row in rows)
    assert not any(row.startswith('Your attacks:') and 'Advantage' in row for row in rows)
