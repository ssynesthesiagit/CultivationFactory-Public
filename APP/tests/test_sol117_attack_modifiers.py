"""Player attack modifier rows use the real table transaction and reload path."""
import pytest

from combat.gate4_engine import Gate4ControllerEngine
from combat.tabletop import auto_buttons
from tests.h1_support import script
from tests.hunt36_support import LEFT, RIGHT, fight, turn, send, reload

NULL = 'TAL_VOID_NULLIFYING_STRIKE'
IRON = 'tianxia.path.body_refining.feature.iron_fist'


def setting(combat, table, mid, parent, field, value):
    engine = combat._load_session(mid).engine
    source = next(a.source_definition_id for a in engine.action_catalog.values()
        if (a.parameters.get('attack_modifier_setting') or {}) == {
            'family': parent, 'modifier': NULL, 'name': 'Nullifying Strike', 'field': field, 'value': value})
    cid = next(c.candidate_id for c in engine.legal_candidates() if c.source_definition_id == source)
    send(combat, table, mid, cid)


@pytest.mark.parametrize('hit,option,payment', [(hit, option, '0') for hit in (True, False) for option in ('0', '1', '2', '3')]
                         + [(True, '1', '1'), (False, '1', '1')])
def test_toggle_and_parent_hit_reload(tmp_path, monkeypatch, hit, option, payment):
    from tests import hunt36_support
    make_sheet = hunt36_support.sheet
    def dual_pool(*args, **kwargs):
        doc = make_sheet(*args, **kwargs)
        doc['ability_scores_and_statistics']['primary_resource']['definitions'] = [{'name': 'Stamina', 'max': 30}]
        doc['ability_scores_and_statistics']['technique_save_dc'] = 100
        return doc
    monkeypatch.setattr(hunt36_support, 'sheet', dual_pool)
    original = Gate4ControllerEngine._resolve_attack_spec
    def roll(engine, *args, **kwargs):
        script(engine, [19 if hit else 1, *([1] * 100)])
        return original(engine, *args, **kwargs)
    monkeypatch.setattr(Gate4ControllerEngine, '_resolve_attack_spec', roll)
    combat, table, mid = fight(tmp_path, [NULL, IRON], cl=5, seed='SOL117')
    turn(combat, table, mid)
    engine = reload(combat, mid)
    parent = next(a.source_definition_id for a in engine.action_catalog.values() if a.display_name == 'Iron Fist attack')
    before = dict(engine.state.actors[LEFT].resources)
    hp = engine.state.actors[RIGHT].current_hp
    sequence = engine.state.event_sequence
    setting(combat, table, mid, parent, 'on', 'toggle')
    setting(combat, table, mid, parent, 'option', option)
    setting(combat, table, mid, parent, 'payment', payment)
    setting(combat, table, mid, parent, 'damage', 'psychic')
    engine = reload(combat, mid)
    assert engine.state.actors[LEFT].resources == before
    assert engine.state.actors[RIGHT].current_hp == hp
    assert not [e for e in engine.events if e.sequence > sequence and e.event_type in ('ATTACK_ROLLED', 'DAMAGE_ROLLED', 'RESOURCE_SPENT')]
    state = table.state(mid)
    # The owner's complete-menu contract retains exact variants alongside
    # the free persistent settings; those settings are not candidate aliases.
    assert [g for g in state['menu']['actions'] if ' + Nullifying Strike:' in g['label']]
    row = next(e for e in state['shapes'][LEFT] if e['base'] == parent)
    assert len(row['modifiers']) == 1 and row['modifiers'][0]['on']
    sequence = engine.state.event_sequence
    candidate = next(c for c in engine.legal_candidates() if c.source_definition_id == parent and c.target_ids == (RIGHT,))
    send(combat, table, mid, candidate.candidate_id)
    engine = reload(combat, mid)
    events = [e for e in engine.events if e.sequence > sequence]
    payments = [e for e in events if e.event_type == 'RESOURCE_SPENT' and e.source_definition_id == NULL]
    damage = [e for e in events if e.event_type == 'DAMAGE_ROLLED' and e.payload.get('damage_label') == 'Nullifying Strike']
    assert len(payments) == len(damage) == int(hit)
    assert all(e.payload['amount'] == 2 for e in payments)
    pool = 'resource:core.qi' if payment == '0' else 'resource:core.stamina'
    for resource in ('resource:core.qi', 'resource:core.stamina'):
        assert engine.state.actors[LEFT].resources[resource] == before[resource] - (2 * int(hit) if resource == pool else 0)
    if hit:
        assert any(e.event_type == 'DAMAGE_COMMITTED' and e.payload.get('damage_type') == 'PSYCHIC' for e in events)
        target = engine.state.actors[RIGHT]
        assert any(c.condition_id.endswith('.reaction_denied') for c in target.conditions.values()) == (option == '0')
        assert sum(m.value for m in target.modifiers.values() if m.target_field == 'speed_ft') == (-10 if option == '1' else 0)
        assert any(c.condition_id.endswith('.hollowed') for c in target.conditions.values()) == (option == '2')


def test_sheet_one_row_per_talent_not_payment(tmp_path):
    from combat.factory_compiler import compile_character
    from tests.h1_support import sheet
    doc = sheet([NULL, IRON], cl=5)
    doc['ability_scores_and_statistics']['primary_resource']['definitions'] = [{'name': 'Stamina', 'max': 30}]
    bundle = compile_character(doc, actor_id=LEFT)
    buttons = auto_buttons(bundle, {})
    parent = next(a for a in bundle['action_catalog'] if a['display_name'] == 'Iron Fist attack')
    rows = [b for b in buttons if b.get('attack_modifier') and b.get('variant_of') == 'act:' + parent['source_definition_id']]
    assert len(rows) == 1
    assert rows[0]['label'] == 'Nullifying Strike'
    assert rows[0]['detail']['cost'] == '2 CP or 2 Stamina'
    assert not [b for b in buttons if '+ Nullifying Strike:' in b['label']]
