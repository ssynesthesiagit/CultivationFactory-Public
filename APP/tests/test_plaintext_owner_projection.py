"""Owner wording reaches cards and persisted table reminders without retyping rules."""
import json
from pathlib import Path

import pytest

from combat.history_text import rider_text
from combat.player_text import clean
from factory_authoring.owner_text_edits import player_wording
from factory_authoring.player_rules import build_player_text, display_prose
from tests.hunt15_support import LEFT, act, fight, reload, turn

ROOT = Path(__file__).resolve().parents[1]
EDITS = json.loads((ROOT / 'authority/typed_mechanics/owner_text_edits.json').read_text())['records']
RULES = json.loads((ROOT / 'authority/typed_mechanics/rules_text.json').read_text())
PROJECTED = json.loads((ROOT / 'authority/typed_mechanics/player_text.json').read_text())
POLISH = {key: edit for key, edit in EDITS.items()
          if '2026-10-11 ability writing polish' in edit.get('why', '')}
# Two earlier owner entries keep their original why and display text.
POLISH.update({key: EDITS[key] for key in ('TAL_GRAVITY_EXTERNAL_WEIGHT_SHIFT',
                                         'TAL_THREAD_STITCH_THE_FALLING_BODY')})
EVIDENCE = [(key, raw, new) for key, edit in POLISH.items()
            for raw, new in edit.get('player_evidence', {}).items()]
SOURCE = [key for key, edit in POLISH.items() if edit.get('player_replace')]


@pytest.mark.parametrize('key,raw,new', EVIDENCE, ids=[f'{key}:{i}' for i, (key, _, _) in enumerate(EVIDENCE)])
def test_every_authored_reminder_reaches_player_output(key, raw, new):
    assert PROJECTED['evidence'][raw] == new, key
    assert clean(raw) == clean(new), key
    assert rider_text({'rider': raw}, 'Mira', 'An ability', 'Ren') == \
        rider_text({'rider': new}, 'Mira', 'An ability', 'Ren'), key


@pytest.mark.parametrize('key', SOURCE)
def test_every_source_phrase_edit_reaches_the_player_card(key):
    projected = PROJECTED['records'][key]
    expected = player_wording(display_prose(RULES[key]), EDITS[key])
    assert projected == expected
    assert clean(RULES[key]) == clean(expected)
    for pair in EDITS[key]['player_replace']:
        assert pair['new'] in projected


def test_generated_player_text_is_rebuilt_from_owner_data():
    assert PROJECTED == build_player_text(RULES, EDITS)
    assert len(POLISH) >= 700  # do not accidentally drop a category of PR reminders


def test_all_authored_reminders_survive_a_table_commit_and_reload(tmp_path):
    # One real action carries every changed reminder, rather than creating
    # hundreds of duplicate fights just to check the presentation boundary.
    pairs = dict((raw, new) for _, raw, new in EVIDENCE)
    pairs.update({RULES[key]: player_wording(display_prose(RULES[key]), EDITS[key]) for key in SOURCE})
    combat, table, mid = fight(tmp_path, ['POISON_BASE_DELIVER_THE_DOSE'],
        effects=[{'type': 'rider', 'evidence': raw} for raw in pairs])
    turn(table, mid, LEFT)
    assert act(table, mid, 'Test setup')['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    raw_events = [event for event in engine.events if event.event_type == 'GM_RIDER']
    assert [event.payload['rider'] for event in raw_events] == list(pairs)
    names, definitions = table._names_for(mid, engine)
    expected = [rider_text({**event.payload, 'rider': pairs[event.payload['rider']]},
                          names.get(event.actor_id, 'Unknown'),
                          definitions.get(event.source_definition_id, 'Unknown'),
                          ', '.join(names.get(target, 'Unknown') for target in event.target_ids))
                for event in raw_events]
    actual = [event['summary'] for event in table.events(mid, 0)['events'] if event['event_type'] == 'GM_RIDER']
    expected = [line for line in expected if line]
    assert len(actual) == len(expected)
    for index, (seen, wanted) in enumerate(zip(actual, expected)):
        assert seen == wanted, (index, seen, wanted)
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    resumed = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    assert [event['summary'] for event in resumed.events(mid, 0)['events'] if event['event_type'] == 'GM_RIDER'] == actual


def test_phrase_edits_preserve_future_source_additions_and_do_not_cascade():
    edit = {'player_replace': [{'old': 'rider', 'new': 'additional effect', 'count': 1},
                              {'old': 'effect', 'new': 'benefit', 'count': 1}]}
    raw = 'A rider and an effect. Later, gain +3 AC for 1 round.'
    assert player_wording(raw, edit) == 'A additional effect and an benefit. Later, gain +3 AC for 1 round.'
    assert player_wording(raw, None) == raw


@pytest.mark.parametrize('raw,pairs', [
    ('A rider.', [{'old': 'rider', 'new': 'effect', 'count': 2}]),
    ('No phrase.', [{'old': 'rider', 'new': 'effect', 'count': 1}]),
    ('A rider effect.', [{'old': 'rider', 'new': 'benefit', 'count': 1},
                         {'old': 'rider effect', 'new': 'benefit', 'count': 1}]),
    ('Gain +3 AC.', [{'old': '+3', 'new': '+5', 'count': 1}]),
    ('Deal 1d8 damage.', [{'old': '1d8', 'new': '1d10', 'count': 1}]),
    ('Gain +3 AC.', [{'old': '+3', 'new': '-3', 'count': 1}]),
    ('At CL5.', [{'old': 'CL5', 'new': 'CL10', 'count': 1}]),
    ('A rider.', [{'old': '', 'new': 'effect', 'count': 1}]),
    ('A rider.', [{'old': 'rider', 'new': 'effect', 'count': True}]),
])
def test_stale_ambiguous_or_mechanical_phrase_edits_fail_closed(raw, pairs):
    with pytest.raises(ValueError):
        player_wording(raw, {'player_replace': pairs})


def test_conflicting_reminder_wording_is_rejected_instead_of_last_writer_winning():
    with pytest.raises(ValueError, match='Conflicting player_evidence'):
        build_player_text({}, {'one': {'player_evidence': {'same reminder': 'one rule'}},
                               'two': {'player_evidence': {'same reminder': 'another rule'}}})


def test_future_owner_overrides_use_the_same_field_and_cost_projection():
    data = build_player_text({'new': 'Unchanged source.'}, {'new': {
        'player_text': 'Action Type: Reaction\nCost: 2 CP',
        'player_evidence': {'legacy note': 'Trigger: An ally falls. Spend 2 CP.'},
    }})
    assert data['records']['new'] == 'Use a reaction.\nCost: 2 cultivation points (your Path resource)'
    assert clean(data['evidence']['legacy note']) == 'You can use this when An ally falls. Spend 2 cultivation points (your Path resource).'


def test_feather_body_reminder_keeps_the_printed_first_thirty_feet():
    key = 'tianxia.talent.gravity.feather_body'
    assert 'You ignore the first 30 feet of falling when calculating falling damage.' in RULES[key]
    raw = next(raw for raw in EDITS[key]['player_evidence'] if raw.startswith('At CL 5'))
    assert 'ignore the first 30 feet of falling when calculating falling damage' in clean(raw)
    assert 'Body Lightening is active' in clean(raw)
