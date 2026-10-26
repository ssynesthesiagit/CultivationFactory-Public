"""Public, synthetic before/after contracts for the Palace closure and zone typing.

No Git history, private fixture or model transport is needed for either arm.
"""
import copy
import json

from combat import factory_compiler
from combat.ext.taiyin_palace import PICK, SOURCE, STATE
from tests.h1_support import sheet
from tests.palace_support import game, activate
from tests.worker2_support import OWNER, ALLY, FOE, reload, turn


def test_redacted_darkness_needs_a_typed_zone_not_a_candidate_gate(tmp_path, monkeypatch):
    real_read = factory_compiler._read_compilation_authority

    def read_without_prose(path):
        authority, sha = real_read(path)
        authority = copy.deepcopy(authority)
        for mechanic in authority['mechanics'].values():
            if isinstance(mechanic, dict):
                mechanic['description'] = []
                mechanic['riders'] = []
        return authority, sha

    monkeypatch.setattr(factory_compiler, '_read_compilation_authority', read_without_prose)
    monkeypatch.setattr(factory_compiler, '_rules_text', lambda: {})
    doc = sheet(['DARK_BASE_DARKNESS', 'TAL_DARK_FEARFUL_DARKNESS'])
    bundle = factory_compiler.compile_character(doc, actor_id=FOE)
    darkness = next(a for a in bundle['action_catalog'] if a['display_name'] == 'Darkness')
    assert darkness['parameters']['typed']['zone_spec']['spreads'] is True
    shapes = [a for a in bundle['action_catalog'] if a['parameters'].get('zone_shape')]
    assert 'Shape Darkness: Fearful Darkness' in {a['display_name'] for a in shapes}

    # Reproduce the actual old model in-process: a lasting geometric area with
    # no zone effect was recognised only by its description's "sphere of".
    def legacy_read(path):
        authority, sha = read_without_prose(path)
        authority['mechanics']['DARK_BASE_DARKNESS']['effects'] = []
        return authority, sha

    monkeypatch.setattr(factory_compiler, '_read_compilation_authority', legacy_read)
    old = factory_compiler.compile_character(doc, actor_id=FOE)
    assert not any(a['parameters'].get('zone_shape') for a in old['action_catalog'])
    # With both prose and effects absent, the compiler omits the inert action
    # altogether. The old model loses Darkness itself as well as its shapes.
    assert not any(a['display_name'] == 'Darkness' for a in old['action_catalog'])


def test_palace_activation_behavior_diff_matches_the_printed_choice_and_duration(tmp_path, monkeypatch):
    real_read = factory_compiler._read_compilation_authority

    # Synthetic old contract: the same single temp-HP grant, followed by a
    # prose-only conditional Advantage effect. It previously emitted GM_RIDER
    # instead of installing the finite moving field.
    def legacy_read(path):
        authority, sha = real_read(path)
        authority = copy.deepcopy(authority)
        record = authority['mechanics'][SOURCE]
        record['effects'] = [
            next(copy.deepcopy(e) for e in record['effects'] if e['type'] == 'temp_hp'),
            {'type': 'advantage', 'applies_to': 'ally', 'distance_ft': 30,
             'on': 'saving throws against cold, necrotic drain, corpse-qi contamination, fear caused by darkness/death/cold, hostile stilling pressure, and anti-healing effects based on Yin, death, corpse-qi, or drain',
             'duration': 'one_minute'},
        ]
        return authority, sha

    with monkeypatch.context() as patch:
        patch.setattr(factory_compiler, '_read_compilation_authority', legacy_read)
        combat, table, mid = game(tmp_path / 'before')
        before = len(combat._load_session(mid).engine.events)
        old_prompts = activate(combat, table, mid, (ALLY,))
        old_engine = reload(tmp_path / 'before', mid)
    old_events = old_engine.events[before:]
    assert not old_prompts
    assert any(e.event_type == 'GM_RIDER' for e in old_events)
    assert not any(c.condition_id == STATE for c in old_engine.state.actors[OWNER].conditions.values())

    combat, table, mid = game(tmp_path / 'after')
    start = combat._load_session(mid).engine.state
    expected_expiry = f'START_OF_SLOT_AT:{start.round_number + 10}:{start.current_slot_index}'
    before = len(combat._load_session(mid).engine.events)
    prompts = activate(combat, table, mid, (ALLY,))
    engine = reload(tmp_path / 'after', mid)
    events = engine.events[before:]
    assert [p['context']['reaction_source_id'] for p in prompts] == [PICK]
    assert not any(e.event_type == 'GM_RIDER' for e in events)
    field = next(c for c in engine.state.actors[OWNER].conditions.values() if c.condition_id == STATE)
    assert json.loads(field.data['chosen']) == [ALLY]
    assert field.expires_on == expected_expiry
    assert engine.state.actors[OWNER].temporary_hp == old_engine.state.actors[OWNER].temporary_hp == 4
    assert not engine.state.actors[OWNER].bonus_action_available
    # The "USE" answer is a recipient decision, not a second activation or
    # confirmation: it offers the chosen allies required by the printed rule.
    assert {o['id'] for o in prompts[0]['choice']['options']} == {OWNER, ALLY}
