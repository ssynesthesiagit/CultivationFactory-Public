"""Golden Mandate: source acquisition, native intents, cold reload and replay.

The NPC's initial catalog describes counterplay inputs, never a successful save,
HP bonus, learned technique or generated Seal. All effects use the shipped
condition/save producers; no live state, feature or condition is installed.
"""
from copy import deepcopy
import hashlib
import json

import pytest

from combat.canonical import canonical_sha256
from combat.factory_compiler import compile_character
from combat.ext import foundation_combat as f
from non_sphere_authority.foundation_mechanics import (
    installed_foundation_state, resolve_initial_foundation_mechanics, verified_foundation_records,
)
from tests.h1_support import ROOT, sheet
from tests.worker2_support import OWNER, ALLY, FOE, candidate, fixture, reload, settle, turn

# Literal dynamic inputs are part of the public export dependency closure.
DEPENDENCIES = (
    'APP/authority/typed_mechanics/rules_text.json',
    'APP/authority/typed_mechanics/reviewed_final.d/a2_foundations_2.json',
    'APP/combat/rules/feature_blocks.d/a2_foundations_2.json',
    'APP/non_sphere_authority/authority/Foundation_Runtime_Authority_v0_4C.json',
    'APP/non_sphere_authority/authority/Tianxia_Foundations_Unified_Transparent_GM_Screen_Catalog_v0_4C.md',
)
IDENTITY = 'golden_mandate_seal_v0_2B'
SOURCE = 'foundation.' + IDENTITY + '.golden_mandate_vessel'
POOL = 'resource:foundation.edict_seal'


def source_sheet(status='active', stage='Awakened', talents=()):
    record = verified_foundation_records()[IDENTITY]
    mechanics = resolve_initial_foundation_mechanics(record, ['tianxia.path.qi_cultivation'], stage=stage)
    doc = sheet(list(talents), cl=5, name='Mandate cultivator')
    doc['identity']['proficiency_bonus'] = 3
    doc['foundation'] = {**installed_foundation_state(mechanics, IDENTITY, 'starting-source-acquisition'),
                         'mechanics': mechanics, 'status': status}
    # A legal deterministic starting character: creation has already included
    # its one PB contribution. The causal acquisition test below proves it.
    doc['ability_scores_and_statistics']['hit_points']['maximum'] = 63
    return doc


def npc_action(bundle, name, effects, *, save_dc=1):
    source = 'npc:mandate_counterplay.' + bundle['actor_id'].rsplit('.', 1)[-1] + '.' + name.lower().replace(' ', '_')
    action = {'source_definition_id': 'action:' + source, 'display_name': name,
              'owner_id': bundle['actor_id'], 'economy': 'NONE', 'resolution_kind': 'TYPED',
              'target_kind': 'ANY_CREATURE', 'range_ft': 60, 'costs': [],
              'parameters': {'free_primary': True, 'typed': {'source': source,
                  'numbers': {'save_dc': save_dc}, 'effects': effects, 'riders': [],
                  'duration': {'kind': 'instant'}}}}
    bundle['action_catalog'].append(action)
    bundle['actor_template']['action_ids'].append(action['source_definition_id'])


def native_table(tmp_path, *, status='active', tags=('frightened',), blocked=(), talents=(), combat_stage=None, owner_dc=100, pressure_dc=1):
    doc = source_sheet(status, talents=talents)
    if combat_stage:
        # A mature starting fixture keeps its authenticated initial HP share;
        # the compiler acquires the later stage's actual source features.
        doc['foundation']['stage'] = combat_stage
    doc['ability_scores_and_statistics']['technique_save_dc'] = owner_dc
    owner = compile_character(doc, actor_id=OWNER, reaction_plan={'ask': True})

    def inputs(bundles):
        consequence = next((n for n in ('frightened', 'charmed', 'silenced', 'poisoned') if n in tags),
                           'compelled_kneeling' if 'kneel' in tags else
                           ('spiritual_shame' if 'spiritual' in tags else 'shame') if 'shamed' in tags else 'command_pressure')
        for b in bundles[1:]:
            npc_action(b, 'Pressure save', [{'type': 'save', 'applies_to': 'target',
                'ability': 'wis', 'save_categories': list(tags), 'on_fail': [{
                    'type': 'condition', 'condition': consequence, 'applies_to': 'target',
                    'duration': 'one_minute'}], 'on_success': []}], save_dc=pressure_dc)
        npc_action(bundles[2], 'Block expression', [{'type': 'condition', 'applies_to': 'target',
            'condition': 'mandate_counterplay', 'authority_expression_blocked': list(blocked),
            'duration': 'until_start_of_your_next_turn'}] if blocked else [])
        npc_action(bundles[2], 'Suppress Foundation', [{'type': 'condition', 'applies_to': 'target',
            'condition': 'mandate_suppression', 'unavailable_foundations': [IDENTITY],
            'duration': 'until_start_of_your_next_turn'}])
        npc_action(bundles[2], 'Silence voice', [{'type': 'condition', 'applies_to': 'target',
            'condition': 'silenced', 'duration': 'until_start_of_your_next_turn'}])
        npc_action(bundles[2], 'Conceal', [{'type': 'condition', 'applies_to': 'target',
            'condition': 'invisible', 'duration': 'until_start_of_your_next_turn'}])
        npc_action(bundles[2], 'Silence and conceal', [{'type': 'condition', 'applies_to': 'target',
            'condition': 'silenced', 'duration': 'until_start_of_your_next_turn'}, {'type': 'condition',
            'applies_to': 'target', 'condition': 'invisible', 'duration': 'until_start_of_your_next_turn'}])
        npc_action(bundles[2], 'Release suppression', [{'type': 'remove_condition',
            'applies_to': 'target', 'condition': 'mandate_suppression'}])
        for bundle in bundles:
            bundle.pop('bundle_sha256', None)
            bundle['bundle_sha256'] = canonical_sha256(bundle)

    return fixture(tmp_path, [], owner_bundle=owner, bundle_transform=inputs,
                   seed='MANDATE-VESSEL-NATIVE', named=True)


def use(combat, table, mid, name, target=None):
    return settle(table, mid, candidate(combat, mid, name, target=target).candidate_id)


def test_exact_printed_record():
    text = json.loads((ROOT / 'authority/typed_mechanics/rules_text.json').read_text())[SOURCE]
    assert hashlib.sha256(text.encode('utf-8')).hexdigest() == '5310ebe0e5417c339b6758db7fa4335c4b0879246710381ff961a05dec78099c'


@pytest.mark.parametrize('tags,expected', [
    (('frightened',), 'ADVANTAGE'), (('charmed',), 'ADVANTAGE'),
    (('silenced', 'hostile_command'), 'ADVANTAGE'),
    (('compelled', 'kneel', 'magical'), 'ADVANTAGE'),
    (('shamed', 'spiritual', 'false_authority'), 'ADVANTAGE'),
    # The mapping is printed phrase by printed phrase. 'compelled' alone does
    # not cover kneeling, and any missing printed qualifier stays inert.
    (('silenced',), 'NORMAL'), (('hostile_command',), 'NORMAL'),
    (('compelled',), 'NORMAL'), (('compelled', 'kneel'), 'NORMAL'),
    (('magical', 'compelled'), 'NORMAL'), (('kneel', 'magical'), 'NORMAL'),
    (('false_authority',), 'NORMAL'), (('shamed', 'false_authority'), 'NORMAL'),
    (('shamed', 'spiritual'), 'NORMAL'), (('spiritual', 'false_authority'), 'NORMAL'),
    (('poisoned',), 'NORMAL'),
])
def test_native_save_consequence_qualifiers(tmp_path, tags, expected):
    combat, table, mid = native_table(tmp_path, tags=tags)
    turn(table, mid, FOE)
    use(combat, table, mid, 'Pressure save', OWNER)
    engine = reload(tmp_path, mid)
    save = [e for e in engine.events if e.event_type == 'SAVE_ROLLED' and e.actor_id == OWNER][-1]
    assert save.payload['mode'] == expected
    assert save.payload['success'] is True
    assert engine.state.actors[OWNER].maximum_hp == 63
    # No outward display has occurred: the defensive passive is not authority.
    assert engine.state.actors[OWNER].resources[POOL] == 0


@pytest.mark.parametrize('tags,condition', [
    (('frightened',), 'frightened'), (('charmed',), 'charmed'),
    (('silenced', 'hostile_command'), 'silenced'),
    (('compelled', 'kneel', 'magical'), 'compelled_kneeling'),
    (('shamed', 'spiritual', 'false_authority'), 'spiritual_shame'),
])
def test_actual_failed_native_saves_apply_the_printed_consequence(tmp_path, tags, condition):
    combat, table, mid = native_table(tmp_path, tags=tags, pressure_dc=100)
    turn(table, mid, FOE)
    use(combat, table, mid, 'Pressure save', OWNER)
    engine = reload(tmp_path, mid)
    save = [e for e in engine.events if e.event_type == 'SAVE_ROLLED' and e.actor_id == OWNER][-1]
    assert save.payload['mode'] == 'ADVANTAGE' and save.payload['success'] is False
    applied = next(c for c in engine.state.actors[OWNER].conditions.values()
                   if c.condition_id == 'condition:typed.' + condition)
    assert applied.source_actor_id == FOE


@pytest.mark.parametrize('status', ['suppressed', 'unknown'])
def test_unavailable_or_unknown_source_never_gives_defense(tmp_path, status):
    combat, table, mid = native_table(tmp_path, status=status)
    turn(table, mid, FOE)
    use(combat, table, mid, 'Pressure save', OWNER)
    engine = reload(tmp_path, mid)
    save = [e for e in engine.events if e.event_type == 'SAVE_ROLLED' and e.actor_id == OWNER][-1]
    assert save.payload['mode'] == 'NORMAL'
    assert engine.state.actors[OWNER].maximum_hp == 60


@pytest.mark.parametrize('tags,expected', [
    (('frightened',), 'ADVANTAGE'), (('charmed',), 'ADVANTAGE'),
    (('silenced', 'hostile_command'), 'NORMAL'),
])
def test_only_command_silence_requires_a_hostile_source(tmp_path, tags, expected):
    combat, table, mid = native_table(tmp_path, tags=tags)
    turn(table, mid, ALLY)
    use(combat, table, mid, 'Pressure save', OWNER)
    engine = reload(tmp_path, mid)
    assert [e for e in engine.events if e.event_type == 'SAVE_ROLLED' and e.actor_id == OWNER][-1].payload['mode'] == expected


@pytest.mark.parametrize('channel,label', [
    ('gesture', 'gesture a lawful order'), ('seal', 'show your seal'),
])
def test_silence_leaves_a_native_alternative_and_passives(tmp_path, channel, label):
    combat, table, mid = native_table(tmp_path)
    use(combat, table, mid, 'Golden Mandate: speak a lawful order')
    turn(table, mid, FOE)
    use(combat, table, mid, 'Silence voice', OWNER)
    # A player-controlled owner can change an owned setting on the enemy turn;
    # the table settings transaction supplies durable accepted-intent provenance.
    engine = combat._load_session(mid).engine
    source = next(a.source_definition_id for a in engine.action_catalog.values()
                  if a.owner_id == OWNER and a.display_name == 'Golden Mandate: ' + label)
    table.save_settings(mid, OWNER, [source], 'alternative-' + channel)
    use(combat, table, mid, 'Pressure save', OWNER)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[POOL] == 1
    assert engine.state.actors[OWNER].maximum_hp == 63
    assert f.held(engine.state.actors[OWNER], 'mandate_display').data['channels'] == [channel]


@pytest.mark.parametrize('blocked,label,generated', [
    (('gesture',), 'show your seal', True),
    (('seal',), 'gesture a lawful order', True),
    (tuple(sorted(f.AUTHORITY_CHANNELS)), 'show your seal', False),
])
def test_source_backed_counterplay_and_real_expiry(tmp_path, blocked, label, generated):
    combat, table, mid = native_table(tmp_path, blocked=blocked)
    use(combat, table, mid, 'Golden Mandate: ' + label)
    turn(table, mid, FOE)
    use(combat, table, mid, 'Block expression', OWNER)
    use(combat, table, mid, 'Pressure save', OWNER)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[POOL] == int(generated)
    assert engine.state.actors[OWNER].maximum_hp == 63
    save = [e for e in engine.events if e.event_type == 'SAVE_ROLLED' and e.actor_id == OWNER][-1]
    assert save.payload['mode'] == 'ADVANTAGE'
    fact = next(c for c in engine.state.actors[OWNER].conditions.values()
                if c.condition_id == 'condition:typed.mandate_counterplay')
    assert fact.data['rule']['authority_expression_blocked'] == sorted(blocked)
    assert fact.source_actor_id == FOE
    assert fact.data['fact_source'].startswith('action:npc:mandate_counterplay.')
    assert fact.data['fact_source'].endswith('.block_expression')
    use(combat, table, mid, 'Pressure save', OWNER)
    assert reload(tmp_path, mid).state.actors[OWNER].resources[POOL] == int(generated)
    # The actual source-next-turn boundary removes the obstruction; a label
    # alone is insufficient. A fresh round can then generate from the display.
    turn(table, mid, OWNER)
    turn(table, mid, FOE)
    engine = reload(tmp_path, mid)
    assert not any(c.condition_id == 'condition:typed.mandate_counterplay'
                   for c in engine.state.actors[OWNER].conditions.values())
    use(combat, table, mid, 'Pressure save', OWNER)
    assert reload(tmp_path, mid).state.actors[OWNER].resources[POOL] == 1


def test_native_suppression_recovery_never_heals_or_stacks(tmp_path):
    combat, table, mid = native_table(tmp_path)
    assert compile_character(source_sheet(), actor_id=OWNER)['actor_template']['maximum_hp'] == 63
    turn(table, mid, FOE)
    for _ in range(2):
        use(combat, table, mid, 'Suppress Foundation', OWNER)
        engine = reload(tmp_path, mid)
        assert (engine.state.actors[OWNER].current_hp, engine.state.actors[OWNER].maximum_hp) == (60, 60)
        use(combat, table, mid, 'Pressure save', OWNER)
        engine = reload(tmp_path, mid)
        assert [e for e in engine.events if e.event_type == 'SAVE_ROLLED' and e.actor_id == OWNER][-1].payload['mode'] == 'NORMAL'
        use(combat, table, mid, 'Release suppression', OWNER)
        engine = reload(tmp_path, mid)
        assert (engine.state.actors[OWNER].current_hp, engine.state.actors[OWNER].maximum_hp) == (60, 63)
    # Rebuilding the unchanged sheet imports the already-included share once.
    assert compile_character(deepcopy(source_sheet()), actor_id=OWNER)['actor_template']['maximum_hp'] == 63


def test_unowned_actor_gets_no_bonus_or_display_control(tmp_path):
    combat, table, mid = native_table(tmp_path, blocked=('gesture',))
    engine = reload(tmp_path, mid)
    assert not any(a.owner_id == ALLY and 'mandate_display' in a.source_definition_id
                   for a in engine.action_catalog.values())
    turn(table, mid, FOE)
    use(combat, table, mid, 'Pressure save', ALLY)
    use(combat, table, mid, 'Block expression', ALLY)
    engine = reload(tmp_path, mid)
    assert [e for e in engine.events if e.event_type == 'SAVE_ROLLED' and e.actor_id == ALLY][-1].payload['mode'] == 'NORMAL'
    assert not any('authority_expression_blocked' in (c.data.get('rule') or {})
                   for c in engine.state.actors[ALLY].conditions.values())


# A blocked talisman leaves the bodily voice and gesture, which a witness can perceive,
# so the seal still generates (printed: no generation only when authority is not perceptible).
@pytest.mark.parametrize('blocked,expected', [((), 1), (('talisman',), 1)])
def test_actually_learned_paid_talisman_expresses_seal_script(tmp_path, blocked, expected):
    from combat.ext.talismans import PREPARED
    talent = 'tianxia.talent.talismans.binding_talisman'
    combat, table, mid = native_table(tmp_path, blocked=blocked, talents=[talent])
    before = reload(tmp_path, mid).state.actors[OWNER].resources[PREPARED]
    if blocked:
        turn(table, mid, FOE)
        use(combat, table, mid, 'Block expression', OWNER)
        turn(table, mid, OWNER)
    use(combat, table, mid, 'Binding Talisman (throw, 20/60 feet)', FOE)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[PREPARED] == before - 1
    assert engine.state.actors[OWNER].resources[POOL] == expected
    assert any(e.event_type == 'SAVE_ROLLED' and e.actor_id == FOE and not e.payload['success']
               for e in engine.events)


@pytest.mark.parametrize('counter,expected', [
    ((), 1),
    (('Silence and conceal',), 0),  # silenced and invisible: no channel is perceptible, so no seal
])
def test_aligned_talisman_without_display_follows_the_same_perceptibility(tmp_path, counter, expected):
    from combat.ext.talismans import PREPARED
    talent = 'tianxia.talent.talismans.binding_talisman'
    combat, table, mid = native_table(tmp_path, talents=[talent])
    if counter:
        turn(table, mid, FOE)
        for name in counter:
            use(combat, table, mid, name, OWNER)
        turn(table, mid, OWNER)
    before = reload(tmp_path, mid).state.actors[OWNER].resources[PREPARED]
    use(combat, table, mid, 'Binding Talisman (throw, 20/60 feet)', FOE)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[PREPARED] == before - 1
    assert engine.state.actors[OWNER].resources[POOL] == expected


def test_alignment_permission_never_teaches_spheres_or_rank(tmp_path):
    doc = source_sheet()
    bundle = compile_character(doc, actor_id=OWNER)
    assert not doc.get('spheres_and_talents')
    assert not any('binding_talisman' in a['source_definition_id'] for a in bundle['action_catalog'])
    assert not any('rank' in str(r).lower() or 'immunity' in str(r).lower()
                   for r in bundle['typed_passives'] if r.get('feature_id') == SOURCE)


@pytest.mark.parametrize('blocked,spend_legal', [
    (('voice',), True), (tuple(sorted(f.AUTHORITY_CHANNELS)), False),
    (('voice', 'gesture', 'seal'), False),
])
def test_every_expression_blocked_vetoes_authority_payment(tmp_path, blocked, spend_legal):
    combat, table, mid = native_table(tmp_path, blocked=blocked)
    use(combat, table, mid, 'Golden Mandate: gesture a lawful order')
    turn(table, mid, FOE)
    use(combat, table, mid, 'Pressure save', OWNER)
    assert reload(tmp_path, mid).state.actors[OWNER].resources[POOL] == 1
    use(combat, table, mid, 'Block expression', OWNER)
    turn(table, mid, OWNER)
    engine = combat._load_session(mid).engine
    legal = [c for c in engine.legal_candidates() if c.display_name == 'Golden Seal Bearing']
    assert bool(legal) is spend_legal
    if spend_legal:
        use(combat, table, mid, 'Golden Seal Bearing')
        assert reload(tmp_path, mid).state.actors[OWNER].resources[POOL] == 0
    else:
        # Not offered, so it cannot be submitted or paid for through the legal path.
        with pytest.raises(AssertionError):
            use(combat, table, mid, 'Golden Seal Bearing')
        assert reload(tmp_path, mid).state.actors[OWNER].resources[POOL] == 1


@pytest.mark.parametrize('counter,spend_legal', [
    ((), True),
    (('Silence voice',), True),  # silenced, but the visible gesture still expresses authority
    (('Conceal',), True),  # invisible, but the voice is still heard
    (('Silence and conceal',), False),  # silenced and invisible: no perceptible channel at all
])
def test_invisible_silenced_owner_cannot_pay_authority_after_earning_it(tmp_path, counter, spend_legal):
    combat, table, mid = native_table(tmp_path)
    use(combat, table, mid, 'Golden Mandate: gesture a lawful order')
    turn(table, mid, FOE)
    use(combat, table, mid, 'Pressure save', OWNER)
    assert reload(tmp_path, mid).state.actors[OWNER].resources[POOL] == 1
    for name in counter:
        use(combat, table, mid, name, OWNER)
    turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    legal = [c for c in engine.legal_candidates() if c.display_name == 'Golden Seal Bearing']
    assert bool(legal) is spend_legal
    if spend_legal:
        use(combat, table, mid, 'Golden Seal Bearing')
        assert reload(tmp_path, mid).state.actors[OWNER].resources[POOL] == 0
    else:
        with pytest.raises(AssertionError):
            use(combat, table, mid, 'Golden Seal Bearing')
        assert reload(tmp_path, mid).state.actors[OWNER].resources[POOL] == 1


def test_used_talisman_remains_an_expression_for_a_native_paid_reaction(tmp_path):
    from combat.ext.save_recheck import SEAL
    talent = 'tianxia.talent.talismans.binding_talisman'
    combat, table, mid = native_table(tmp_path, talents=[talent], combat_stage='Perfected',
                                     owner_dc=1, blocked=('voice', 'gesture'))
    use(combat, table, mid, 'Golden Mandate: gesture a lawful order')
    turn(table, mid, FOE)
    use(combat, table, mid, 'Pressure save', OWNER)
    assert reload(tmp_path, mid).state.actors[OWNER].resources[POOL] == 1
    use(combat, table, mid, 'Block expression', OWNER)
    turn(table, mid, OWNER)
    prompts = settle(table, mid,
        candidate(combat, mid, 'Binding Talisman (throw, 20/60 feet)', target=FOE).candidate_id,
        picks={'reaction:typed.' + SEAL: 'first'})
    assert any(p['context']['reaction_source_id'] == 'reaction:typed.' + SEAL for p in prompts)
    engine = reload(tmp_path, mid)
    assert any(e.event_type == 'RESOURCE_SPENT' and e.actor_id == OWNER
               and e.payload.get('resource_id') == POOL and e.payload.get('amount') == 1
               for e in engine.events)


def test_native_suppression_vetoes_payment_of_an_existing_seal(tmp_path):
    combat, table, mid = native_table(tmp_path)
    use(combat, table, mid, 'Golden Mandate: gesture a lawful order')
    turn(table, mid, FOE)
    use(combat, table, mid, 'Pressure save', OWNER)
    assert reload(tmp_path, mid).state.actors[OWNER].resources[POOL] == 1
    use(combat, table, mid, 'Suppress Foundation', OWNER)
    turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[POOL] == 1
    assert not any(c.display_name == 'Golden Seal Bearing' for c in engine.legal_candidates())
    with pytest.raises(AssertionError):
        use(combat, table, mid, 'Golden Seal Bearing')
    assert reload(tmp_path, mid).state.actors[OWNER].resources[POOL] == 1
    assert engine.state.actors[OWNER].maximum_hp == 60


def test_display_settings_are_free_declarations_of_the_printed_expression(tmp_path):
    """The menu entries declare the printed Counterplay forms; they are not abilities.

    Printed Vessel Limit: authority is lost only "when all expression is
    blocked"; Counterplay: "silence the voice, bind the hands, hide the seal".
    Every offered display is therefore free, self-only and effect-free apart
    from recording which form is in use.
    """
    combat, table, mid = native_table(tmp_path)
    engine = reload(tmp_path, mid)
    rows = [a for a in engine.action_catalog.values()
            if a.owner_id == OWNER and a.source_definition_id.startswith('action:typed.')
            and '.mandate_display.' in a.source_definition_id]
    assert {r.display_name for r in rows} == {'Golden Mandate: ' + label for label in f.DISPLAY_LABELS.values()}
    for row in rows:
        assert row.economy == 'NONE' and row.target_kind == 'SELF' and not row.costs
        assert row.parameters['setting_only'] is True
        assert [effect.get('type') for effect in row.parameters['typed']['effects']] == ['mandate_display']
        text = row.parameters['setting_description']
        assert 'costs no Action and no resource' in text
        assert 'does not command' in text and 'legal immunity' in text
        assert 'speech' in text and 'seal' in text


def test_the_printed_seal_route_and_hiding_it_are_the_third_expression(tmp_path):
    """Speech and hands obstructed leaves the seal; hiding it blocks authority.

    This is the printed Counterplay ("silence the voice, bind the hands, hide
    the seal") and the Limit ("no authority when all expression is blocked").
    A display is the player's own setting, so it is committed through the table
    settings transaction even on another creature's turn.
    """
    def set_display(label):
        engine = combat._load_session(mid).engine
        source = next(a.source_definition_id for a in engine.action_catalog.values()
                      if a.owner_id == OWNER and a.display_name == 'Golden Mandate: ' + label)
        table.save_settings(mid, OWNER, [source], 'seal-route-' + label)

    combat, table, mid = native_table(tmp_path, blocked=('voice', 'gesture'))
    turn(table, mid, FOE)
    use(combat, table, mid, 'Block expression', OWNER)
    use(combat, table, mid, 'Pressure save', OWNER)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[POOL] == 0
    assert f.mandate_expression_channels(engine, engine.state.actors[OWNER]) == set()
    set_display('show your seal')
    use(combat, table, mid, 'Pressure save', OWNER)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[POOL] == 1
    assert f.held(engine.state.actors[OWNER], 'mandate_display').data['channels'] == ['seal']
    set_display('hide your seal')
    engine = reload(tmp_path, mid)
    assert f.held(engine.state.actors[OWNER], 'mandate_display') is None
    assert f.mandate_expression_channels(engine, engine.state.actors[OWNER]) == set()
