"""Orphan Snipe routes and complete nested Daybreak text in persisted Tables."""
import pytest

from combat.factory_compiler import compile_character
from combat.tabletop import auto_buttons
from tests.h1_support import sheet
from tests.hunt36_support import LEFT, RIGHT, act, fight, reload, send, turn
from tests.equipment_readiness import ready_table_weapon
from tests.test_barrage_hits import helpers
from tests.test_solfsol117_review import hits, choose

TRAINING = 'TAL_SNIPER_SNIPER_TRAINING'
SEAL = 'tianxia.talent.radiance.daybreak_seal'


@pytest.mark.parametrize('talent,name', [
    ('TAL_SNIPER_PUSH_SHOT', 'Push Shot'),
    ('TAL_SNIPER_WEAPON_SHOT', 'Weapon Shot'),
    ('TAL_SNIPER_HINDERING_PROJECTILE', 'Hindering Projectile'),
])
def test_orphan_snipe_manual_sheet_execution_reload(tmp_path, hits, monkeypatch, talent, name):
    owned = [TRAINING, 'TAL_SNIPER_PUSH_SHOT', 'TAL_SNIPER_WEAPON_SHOT', 'TAL_SNIPER_HINDERING_PROJECTILE']
    bundle = compile_character(sheet(owned, cl=5, kit=helpers.BOW_KIT), actor_id=LEFT)
    snipe_rows = [a for a in bundle['action_catalog'] if a['display_name'].startswith('Snipe Shot:')]
    bow_rows = [a for a in snipe_rows if 'Gong Jian (Bow and Arrow)' in a['display_name']]
    assert len(bow_rows) == 3 and all(a['display_name'].count(' + ') == 1 for a in snipe_rows)
    assert not any(a['parameters'].get('attack_modifier_setting', {}).get('family', '').endswith('.snipe')
                   for a in bundle['action_catalog'])
    source = next(a['source_definition_id'] for a in bow_rows if a['display_name'].endswith('+ ' + name))
    assert any((b.get('combat') or {}).get('source_definition_id') == source
               for b in auto_buttons(bundle, {}))
    # Recreate the pre-repair sealed metadata without touching a historical save.
    from tests import hunt36_support
    original_compile = hunt36_support.compile_character
    def legacy_compile(*args, **kwargs):
        compiled = original_compile(*args, **kwargs)
        for row in compiled['action_catalog']:
            typed = row['parameters'].get('typed') or {}
            if row['display_name'].startswith('Snipe Shot:'):
                typed['attack_modifier_variant'] = typed['variant_of']
        return compiled
    monkeypatch.setattr(hunt36_support, 'compile_character', legacy_compile)
    combat, table, mid = fight(tmp_path, owned, kit=helpers.BOW_KIT, cl=5,
                              positions={LEFT: {'x': 3, 'y': 6}, RIGHT: {'x': 6, 'y': 6}},
                              seed='SOLFSOL117R5-' + name)
    turn(combat, table, mid)
    ready_table_weapon(table, mid, source)
    engine = reload(combat, mid)
    assert engine.action_catalog[source].parameters['typed'].get('attack_modifier_variant')
    bundle['action_catalog'] = [a.model_dump(mode='json') for a in engine.action_catalog.values() if a.owner_id == LEFT]
    assert any((b.get('combat') or {}).get('source_definition_id') == source for b in auto_buttons(bundle, {}))
    group = next(g for g in table.state(mid)['menu']['actions'] if g['source_definition_id'] == source)
    option = next(o for o in group['options'] if o['target_ids'] == [RIGHT])
    sequence = engine.state.event_sequence
    before_position = engine.state.actors[RIGHT].position
    send(combat, table, mid, option['candidate_id'])
    engine = reload(combat, mid)  # fresh service, recorded-event verification and mechanical replay
    events = [e for e in engine.events if e.sequence > sequence]
    assert any(e.event_type == 'ATTACK_ROLLED' and e.source_definition_id == source for e in events)
    if name == 'Push Shot':
        assert engine.state.actors[RIGHT].position != before_position
    else:
        assert any(e.event_type == 'SAVE_ROLLED' for e in events)
    assert engine.action_catalog[source].parameters['typed'].get('attack_modifier_variant')
    bundle['action_catalog'] = [a.model_dump(mode='json') for a in engine.action_catalog.values() if a.owner_id == LEFT]
    assert any((b.get('combat') or {}).get('source_definition_id') == source for b in auto_buttons(bundle, {}))


def assert_seal_text(text):
    assert 'typed_executor' not in text and 'GM-only' not in text and 'block_if_marked' not in text
    for expected in ('Dawnmark', '2 cultivation points (your Path resource)', 'Constitution saving throw', 'Failed save:',
                     'cannot regain hit points', 'or gain Temporary HP', 'Successful save:',
                     'until the start of your next turn', 'Unclean', 'Disadvantage', 'undead'):
        assert expected in text


def test_daybreak_nested_tooltip_and_actual_prompt_reload(tmp_path, hits):
    bundle = compile_character(sheet([SEAL, 'RADIANCE_BASE_STRIKE'], cl=5), actor_id=LEFT)
    buttons = [b for b in auto_buttons(bundle, {}) if b.get('attack_modifier') and b['label'] == 'Daybreak Seal']
    assert buttons
    for button in buttons:
        assert_seal_text(button['description'])
    # The tested hit is on our next turn. A bare Dawnmark expires at that
    # turn's start; Scripture's printed extension keeps the target eligible.
    combat, table, mid = fight(tmp_path, [SEAL, 'RADIANCE_BASE_STRIKE',
                                       'tianxia.talent.radiance.dawnmark_scripture'], cl=5)
    # Apply the mark through a real attacking Radiance action instead of a setup row.
    turn(combat, table, mid)
    engine = reload(combat, mid)
    parent = next(a.source_definition_id for a in engine.action_catalog.values()
                  if a.owner_id == LEFT and a.display_name == 'Radiance Strike')
    send(combat, table, mid, next(c.candidate_id for c in engine.legal_candidates()
                                 if c.source_definition_id == parent and c.target_ids == (RIGHT,)))
    act(combat, table, mid, 'end')
    turn(combat, table, mid)
    choose(combat, table, mid, parent, SEAL, 'on', 'toggle')
    engine = reload(combat, mid)
    from combat.typed_executor import bears_mark
    assert bears_mark(engine.state.actors[RIGHT], LEFT, 'Dawnmark')
    prompts = send(combat, table, mid, next(c.candidate_id for c in engine.legal_candidates()
                  if c.source_definition_id == parent and c.target_ids == (RIGHT,)))
    assert prompts
    for prompt in prompts:
        assert 'Daybreak Seal' in prompt['moment'] and 'Radiance Strike' in prompt['moment']
        assert 'Visiting Fighter' in prompt['moment']
        assert_seal_text(prompt['moment'])
    reload(combat, mid)


@pytest.mark.parametrize('missing', ['parent', 'loadout', 'owner', 'modifier'])
def test_missing_replacement_retains_variant(missing):
    from combat.ext.attack_modifiers import settings
    from combat.gate2_runtime_models import ActionDefinition
    from tests.test_sol117_attack_modifiers import NULL, IRON
    bundle = compile_character(sheet([NULL, IRON], cl=5), actor_id=LEFT)
    actions = [ActionDefinition.model_validate(a) for a in bundle['action_catalog']
               if not a['parameters'].get('attack_modifier_setting')]
    variant = next(a for a in actions if a.parameters.get('typed', {}).get('attack_modifier_variant'))
    parent_id = variant.parameters['typed']['attack_modifier_variant']
    parent = next(a for a in actions if a.source_definition_id == parent_id)
    if missing == 'parent':
        actions.remove(parent)
    elif missing == 'loadout':
        parent.parameters['typed'].pop('attack_modifier_loadout')
    elif missing == 'modifier':
        for group in parent.parameters['typed']['attack_modifier_loadout']:
            group['id'] = 'future.unrelated'
    else:
        actions[actions.index(parent)] = parent.model_copy(update={'owner_id': RIGHT})
    settings(actions)
    assert not variant.parameters['typed'].get('attack_modifier_variant')


def test_plain_nested_effect_text_includes_save_outcomes():
    from combat.ext.paid_hit import effect_text
    text = effect_text([{'type': 'future_wrapper', 'evidence': 'Only when eligible.', 'effects': [
        {'type': 'save', 'evidence': 'Make a Dexterity saving throw.',
         'on_fail': [{'evidence': 'Lose 10 feet of Speed.'}],
         'on_success': [{'evidence': 'Keep your Speed.'}]}]}])
    assert text == ('Only when eligible. Make a Dexterity saving throw. '
                    'Failed save: Lose 10 feet of Speed. Successful save: Keep your Speed.')
