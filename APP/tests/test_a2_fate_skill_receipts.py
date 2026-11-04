"""Single-use self-Help across real producers, table commit and cold replay.

Sealed free actions supply scenes and repeat checks without changing economy or
live state. Test-only setup effects call public evented scene/bond helpers;
production roll producers and service/session methods are never replaced.
"""
import pytest
from combat import ext
from combat.factory_compiler import compile_character
from combat.ext import fate_riders as F
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests import worker2_support as S
from tests.cw2_service_support import add_action
from tests.h1_support import ROOT, sheet
from tests.test_r9i_choices import action, resolve, finish_turn
from tests.test_r9i_karma_persistence import act

EYE = 'TAL_THE_HIDDEN_EYE_BASE_SPHERE_FEATURES'
SWEEP = 'TAL_THE_HIDDEN_EYE_THOUSAND_LANTERN_SWEEP'
DIAGNOSIS = 'TAL_IRON_FIST_EIGHT_GATE_DIAGNOSIS'


def setup_effects(monkeypatch):
    from combat.ext import placed, mounts
    from combat.gate2_runtime_models import Position
    ext.effects()
    def scene(ctx, row):
        foe = ctx.engine.state.actors[S.FOE]
        if row.get('hidden'):
            ctx.engine._apply_condition(foe, 'condition:typed.hidden', ctx.source, foe.entity_id,
                expires_on='UNTIL_REMOVED', data={'stealth_total': 100})
        if row.get('muffled'):
            placed.place(ctx.engine, foe, source=ctx.source, tag='practice_sound', cells=foe.position,
                name='Quiet practice area', inside=[{'id': 'practice_sound', 'name': 'Quiet practice area', 'muffles': True}])
            from combat import zones
            zones.sync_inside(ctx.engine, ctx.source)
        for x in (6, 7):
            placed.place(ctx.engine, foe, source=ctx.source, tag='trap', cells=Position(x=x, y=6),
                name='Concealed practice trap', numbers={'save_dc': 100})
    def bond(ctx, row):
        from combat import dynamic_size
        for creature in (ctx.actor, ctx.engine.state.actors[S.FOE]):
            dynamic_size.apply_growth(ctx.engine, creature, 'Large', ctx.source,
                source_actor_id=ctx.actor.entity_id, expires_on='UNTIL_REMOVED')
        dynamic_size.sync(ctx.engine, ctx.source)
        rider = ctx.engine.state.actors[S.ALLY]
        from combat.ext.needle import step_to
        step_to(ctx.engine, rider, ctx.actor.position, ctx.source)
        mounts.bind(ctx.engine, rider, ctx.actor)
    def check(ctx, row):
        from combat.ext.escape_checks import resolve_escape_check
        resolve_escape_check(ctx, {'bonus': 10}, 100, [],
            check_ability=row['ability'], check_skill=row['skill'], escape_hooks=False)
    monkeypatch.setitem(ext._EFFECTS, 'test_receipt_check', check)
    monkeypatch.setitem(ext._EFFECTS, 'test_receipt_scene', scene)
    monkeypatch.setitem(ext._EFFECTS, 'test_receipt_bond', bond)


@pytest.fixture(autouse=True)
def registered_receipt_setups(monkeypatch):
    setup_effects(monkeypatch)


def helped(tmp_path, skill, talents=(), prepare=None):
    talents = [F.LANTERN_ID, *talents]
    document = sheet(talents, cl=15)
    foe_document = sheet([], cl=15)
    document['ability_scores_and_statistics']['skills'] = [
        {'skill': name, 'bonus': 10, 'proficiency_multiplier': 1}
        for name in ('Investigation', 'Perception', 'Medicine', 'Athletics', 'Acrobatics')]
    document['ability_scores_and_statistics']['primary_resource']['maximum'] = 100
    bundle = compile_character(document, actor_id=S.OWNER, reaction_plan={'ask': True})
    def transform(bundles):
        ability = {'Investigation': 'INT', 'Perception': 'WIS', 'Medicine': 'WIS',
                   'Athletics': 'STR', 'Acrobatics': 'DEX'}[skill]
        add_action(bundles[0], 'Another matching check', [{'type': 'test_receipt_check',
            'ability': ability, 'skill': skill}], target='SELF')
        if prepare:
            prepare(bundles)
    combat, table, mid = S.fixture(tmp_path, talents, owner_bundle=bundle, foe_sheet=foe_document,
        foe_position={'x': 6, 'y': 6}, ally_position={'x': 8, 'y': 6}, bundle_transform=transform)
    resolve(lambda answers: act(table, mid, action(table, mid, 'Lone Lantern Auspice', S.OWNER), answers), {})
    finish_turn(table, mid)
    S.turn(table, mid, S.OWNER)
    resolve(lambda answers: act(table, mid, action(table, mid, 'Help yourself'), answers),
            {'choice:needle.lantern_help': [skill]})
    before = S.reload(tmp_path, mid)
    assert not F._held(before.state.actors[S.OWNER], F.LANTERN_HELP)[0].data['used']
    return combat, table, mid, before


def assert_consumed_then_repeat(tmp_path, mid, skill, expiry, *, repeat=True):
    loaded = S.reload(tmp_path, mid)
    held = F._held(loaded.state.actors[S.OWNER], F.LANTERN_HELP)[0]
    assert held.data['used'] is True and held.data['rule'] == {}
    assert held.expires_on == expiry
    label = f"Lone Lantern Help: {skill} check benefit used; no other creature's Help until the start of your next turn."
    assert held.data['label'] == label
    cold = CombatService(ROOT, tmp_path)
    table = TabletopService(cold, tmp_path)
    owner = next(row for row in cold.presentation(mid)['actors'] if row['entity_id'] == S.OWNER)
    pill = next(row for row in owner['conditions'] if row['condition_id'] == F.LANTERN_HELP)
    assert pill['display_name'] == label
    consumed = [row for boundary in cold.history(mid)['boundaries'] for row in boundary['feed']
        if row['event_type'] == 'CONDITION_APPLIED' and row['raw']['payload'].get('condition_id') == F.LANTERN_HELP
        and row['raw']['payload'].get('gate3_condition_after', {}).get('data', {}).get('used')]
    assert len(consumed) == 1 and label in consumed[0]['summary'] and 'Advantage' not in consumed[0]['summary']
    from combat.ext.help_policy import allowed
    assert not allowed(loaded, loaded.state.actors[S.ALLY], loaded.state.actors[S.OWNER])
    if not repeat:
        return
    resolve(lambda answers: act(table, mid, action(table, mid, 'Another matching check', S.OWNER), answers), {})
    again = S.reload(tmp_path, mid)
    check = next(e for e in reversed(again.events) if e.event_type == 'CHECK_ROLLED')
    assert check.payload['actor']['mode'] == 'NORMAL'
    assert F._held(again.state.actors[S.OWNER], F.LANTERN_HELP)[0].data['used'] is True


@pytest.mark.parametrize('skill', ['Investigation', 'Perception'])
def test_analyze_emits_selected_skill_and_spends_self_help_once(tmp_path, skill):
    combat, table, mid, before = helped(tmp_path, skill, [EYE])
    expiry = F._held(before.state.actors[S.OWNER], F.LANTERN_HELP)[0].expires_on
    prompts = S.settle(table, mid, action(table, mid, 'Analyze', S.FOE),
        picks={'choice:needle.eye_approach': skill})
    assert any(p['context']['reaction_source_id'] == 'choice:needle.eye_approach' for p in prompts)
    loaded = S.reload(tmp_path, mid)
    event = next(e for e in reversed(loaded.events) if e.event_type == 'CHECK_ROLLED')
    assert event.payload['actor']['mode'] == 'ADVANTAGE'
    assert_consumed_then_repeat(tmp_path, mid, skill, expiry)
    assert event.payload['skill'].casefold() == skill.casefold()


@pytest.mark.parametrize('muffled', [False, True])
def test_sweep_spends_help_once_and_keeps_one_shared_draw_for_all_views(tmp_path, monkeypatch, muffled):
    def prepare(bundles):
        add_action(bundles[0], 'Set search scene', [{'type': 'test_receipt_scene', 'hidden': True, 'muffled': muffled}], target='SELF')
    combat, table, mid, before = helped(tmp_path, 'Perception', [SWEEP], prepare)
    expiry = F._held(before.state.actors[S.OWNER], F.LANTERN_HELP)[0].expires_on
    S.settle(table, mid, action(table, mid, 'Set search scene'), picks={})
    before = S.reload(tmp_path, mid)
    S.settle(table, mid, action(table, mid, 'Thousand-Lantern Sweep'), picks={})
    loaded = S.reload(tmp_path, mid)
    receipts = [e for e in loaded.events[len(before.events):] if e.event_type == 'CHECK_ROLLED']
    assert len(receipts) == 4  # own, creature and two trap views
    rolls = [e.payload['actor'] for e in receipts]
    assert rolls[0]['mode'] == 'ADVANTAGE'
    assert rolls[1]['mode'] == ('NORMAL' if muffled else 'ADVANTAGE')
    assert len({r['counter_start'] for r in rolls}) == 1
    assert all(r['dice'] == rolls[0]['dice'] for r in rolls)
    assert loaded.roller.counter == before.roller.counter + 2
    assert all(e.payload['skill'] == 'Perception' for e in receipts)
    applied = [e for e in loaded.events[len(before.events):] if e.event_type == 'CONDITION_APPLIED'
               and e.payload.get('condition_id') == F.LANTERN_HELP and e.payload.get('gate3_condition_after', {}).get('data', {}).get('used')]
    assert len(applied) == 1
    assert_consumed_then_repeat(tmp_path, mid, 'Perception', expiry)


@pytest.mark.parametrize('skill', ['Medicine', 'Investigation'])
def test_diagnosis_emits_skill_separately_from_display_label(tmp_path, skill):
    combat, table, mid, before = helped(tmp_path, skill, [DIAGNOSIS])
    expiry = F._held(before.state.actors[S.OWNER], F.LANTERN_HELP)[0].expires_on
    label = 'Wisdom (Medicine)' if skill == 'Medicine' else 'Intelligence (Investigation)'
    choices = {'choice:needle.iron_fist.Eight-Gate Diagnosis creature': S.FOE,
               'choice:needle.iron_fist.Eight-Gate Diagnosis check': label,
               'choice:needle.iron_fist.Eight-Gate Diagnosis information': ['Bloodied', 'Weakest physical save']}
    S.settle(table, mid, action(table, mid, 'Eight-Gate Diagnosis'), picks=choices)
    loaded = S.reload(tmp_path, mid)
    receipt = next(e for e in reversed(loaded.events) if e.event_type == 'CHECK_ROLLED')
    assert receipt.payload['actor']['mode'] == 'ADVANTAGE'
    assert_consumed_then_repeat(tmp_path, mid, skill, expiry)
    assert receipt.payload['skill'] == skill


def test_trap_search_emits_perception_for_shared_trap_receipts(tmp_path, monkeypatch):
    def prepare(bundles):
        add_action(bundles[0], 'Set search scene', [{'type': 'test_receipt_scene'}], target='SELF')
        add_action(bundles[0], 'Trap Search', [{'type': 'search', 'bonus': 10}], target='SELF')
    combat, table, mid, before = helped(tmp_path, 'Perception', (), prepare)
    expiry = F._held(before.state.actors[S.OWNER], F.LANTERN_HELP)[0].expires_on
    S.settle(table, mid, action(table, mid, 'Set search scene'), picks={})
    before = S.reload(tmp_path, mid)
    S.settle(table, mid, action(table, mid, 'Trap Search'), picks={})
    loaded = S.reload(tmp_path, mid)
    receipts = [e for e in loaded.events[len(before.events):] if e.event_type == 'CHECK_ROLLED']
    assert len(receipts) == 2
    assert all(e.payload['actor']['mode'] == 'ADVANTAGE' and e.payload['skill'] == 'Perception' for e in receipts)
    assert len({e.payload['actor']['counter_start'] for e in receipts}) == 1
    assert_consumed_then_repeat(tmp_path, mid, 'Perception', expiry)


@pytest.mark.parametrize('explicit', [True, False])
@pytest.mark.parametrize('producer', ['shared', 'net'])
@pytest.mark.parametrize('skill', ['Athletics', 'Acrobatics'])
def test_escape_receipts_consume_actual_skill_modes(tmp_path, producer, skill, explicit):
    ability = 'STR' if skill == 'Athletics' else 'DEX'
    def prepare(bundles):
        condition = 'grappled' if producer == 'shared' else 'netted'
        data = {'escape_dc': 100, 'dc': 100}
        add_action(bundles[0], 'Set hold', [{'type': 'condition', 'condition': condition,
            'applies_to': 'self', 'condition_data': data}], target='SELF', typed={'duration': {'kind': 'until_removed'}})
        add_action(bundles[0], 'Explicit escape', [{'type': 'escape_grapple' if producer == 'shared' else 'trap_escape',
            'bonus': 10, **({'check_ability': ability, 'check_skill': skill} if explicit else {})}], target='SELF')
    combat, table, mid, before = helped(tmp_path, skill, (), prepare)
    expiry = F._held(before.state.actors[S.OWNER], F.LANTERN_HELP)[0].expires_on
    S.settle(table, mid, action(table, mid, 'Set hold'), picks={})
    S.settle(table, mid, action(table, mid, 'Explicit escape'), picks={})
    loaded = S.reload(tmp_path, mid)
    receipt = next(e for e in reversed(loaded.events) if e.event_type == 'CHECK_ROLLED')
    assert receipt.payload['actor']['mode'] == 'ADVANTAGE'
    assert_consumed_then_repeat(tmp_path, mid, skill, expiry)
    assert receipt.payload['skill'] == (skill if explicit else None)
    if not explicit:
        assert receipt.payload['mode_skills'] == ['Athletics', 'Acrobatics']


def test_overrun_receipt_names_mounts_athletics(tmp_path, monkeypatch):
    def prepare(bundles):
        add_action(bundles[0], 'Set riding bond', [{'type': 'test_receipt_bond'}], target='SELF')
        add_action(bundles[1], 'Practice Overrun', [{'type': 'mount_overrun'}], target='HOSTILE_ENTITY')
    combat, table, mid, before = helped(tmp_path, 'Athletics', (), prepare)
    expiry = F._held(before.state.actors[S.OWNER], F.LANTERN_HELP)[0].expires_on
    S.settle(table, mid, action(table, mid, 'Set riding bond'), picks={})
    finish_turn(table, mid)
    S.turn(table, mid, S.ALLY)
    S.settle(table, mid, action(table, mid, 'Practice Overrun', S.FOE), picks={})
    loaded = S.reload(tmp_path, mid)
    receipt = next(e for e in reversed(loaded.events) if e.event_type == 'CHECK_ROLLED')
    assert receipt.payload['actor']['actor_id'] == S.OWNER
    assert receipt.payload['actor']['mode'] == 'ADVANTAGE'
    # Repeat before the mount's next turn: its self-Help restriction still lives.
    assert_consumed_then_repeat(tmp_path, mid, 'Athletics', expiry, repeat=False)
    assert receipt.payload['skill'] == 'Athletics' and receipt.payload['target_skill'] == 'Athletics'
    cold = CombatService(ROOT, tmp_path)
    cold_table = TabletopService(cold, tmp_path)
    S.settle(cold_table, mid, action(cold_table, mid, 'Practice Overrun', S.FOE), picks={})
    again = S.reload(tmp_path, mid)
    check = next(e for e in reversed(again.events) if e.event_type == 'CHECK_ROLLED')
    assert check.payload['actor']['mode'] == 'NORMAL'


@pytest.mark.parametrize('producer', ['analyze', 'cultivation_diagnosis'])
def test_a_different_or_unskilled_check_keeps_help_for_its_matching_skill(tmp_path, producer):
    talent = EYE if producer == 'analyze' else DIAGNOSIS
    combat, table, mid, before = helped(tmp_path, 'Investigation', [talent])
    if producer == 'analyze':
        S.settle(table, mid, action(table, mid, 'Analyze', S.FOE),
            picks={'choice:needle.eye_approach': 'Perception'})
    else:
        S.settle(table, mid, action(table, mid, 'Eight-Gate Diagnosis'), picks={
            'choice:needle.iron_fist.Eight-Gate Diagnosis creature': S.FOE,
            'choice:needle.iron_fist.Eight-Gate Diagnosis check': 'Cultivation Check',
            'choice:needle.iron_fist.Eight-Gate Diagnosis information': ['Bloodied', 'Weakest physical save']})
    loaded = S.reload(tmp_path, mid)
    receipt = next(e for e in reversed(loaded.events) if e.event_type == 'CHECK_ROLLED')
    assert receipt.payload['actor']['mode'] == 'NORMAL'
    assert receipt.payload['skill'] == ('Perception' if producer == 'analyze' else None)
    assert not F._held(loaded.state.actors[S.OWNER], F.LANTERN_HELP)[0].data['used']
    # The player's actual skill choice leaves the unrelated Help benefit armed.
    cold = CombatService(ROOT, tmp_path)
    table = TabletopService(cold, tmp_path)
    S.settle(table, mid, action(table, mid, 'Another matching check', S.OWNER), picks={})
    again = S.reload(tmp_path, mid)
    receipt = next(e for e in reversed(again.events) if e.event_type == 'CHECK_ROLLED')
    assert receipt.payload['actor']['mode'] == 'ADVANTAGE'
    assert F._held(again.state.actors[S.OWNER], F.LANTERN_HELP)[0].data['used'] is True
