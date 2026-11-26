"""Review regressions through table transactions and shipped source producers."""
import copy

import pytest

from combat.ext.taiyin_palace import USED, protects
from tests.h1_support import sheet
from tests.palace_support import game, activate, save_mode
from tests.worker2_support import OWNER, ALLY, FOE, candidate, settle, turn, reload


def test_allied_and_environmental_cold_are_not_hostility_gated(tmp_path):
    combat, table, mid = game(tmp_path)
    activate(combat, table, mid)
    assert save_mode(combat, table, mid, OWNER, 'cold', source=ALLY) == 'ADVANTAGE'
    engine = reload(tmp_path, mid)
    assert protects(engine, engine.state.actors[OWNER], None, {'damage:cold'})
    assert not protects(engine, engine.state.actors[OWNER], None, {'hostile_stilling_pressure'})


@pytest.mark.parametrize('active', [False, True])
def test_shipped_fearful_darkness_save_receives_palace_advantage(tmp_path, active):
    combat, table, mid = game(
        tmp_path, foe_sheet=sheet(['DARK_BASE_DARKNESS', 'TAL_DARK_FEARFUL_DARKNESS']))
    if active:
        activate(combat, table, mid)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Shape Darkness: Fearful Darkness').candidate_id,
           choices={})
    # Shape selection costs the foe's action. Cast on its next turn.
    turn(table, mid, OWNER)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Darkness', at=(3, 6)).candidate_id,
           choices={})
    before = len(combat._load_session(mid).engine.events)
    turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    saves = [e for e in engine.events[before:]
             if e.event_type == 'SAVE_ROLLED' and e.actor_id == OWNER]
    assert saves, 'Starting in the shipped Fearful Darkness must produce a save'
    assert saves[-1].payload['mode'] == ('ADVANTAGE' if active else 'NORMAL')


def test_fearful_darkness_shape_is_offered_when_printed_prose_is_redacted(tmp_path, monkeypatch):
    # The public CI export redacts prose fields (tools/public_test_redact.py: description, riders, rules_text.json), so a
    # talent's "- Darkness" heading and its "Your Darkness ..." description are gone there. The structured name and trigger
    # survive. The shape must still be offered, from those mechanical fields alone.
    from combat import factory_compiler
    real_read = factory_compiler._read_compilation_authority

    def redacted_read(path):
        authority, sha = real_read(path)
        authority = copy.deepcopy(authority)  # the cache hands out shared read-only data; never redact it in place
        for mechanic in authority['mechanics'].values():
            if isinstance(mechanic, dict):
                mechanic['description'] = ['[text redacted]'] if mechanic.get('description') else []
                mechanic['riders'] = ['[text redacted]'] if mechanic.get('riders') else []
        return authority, sha

    monkeypatch.setattr(factory_compiler, '_read_compilation_authority', redacted_read)
    monkeypatch.setattr(factory_compiler, '_rules_text', lambda: {})
    combat, table, mid = game(
        tmp_path, foe_sheet=sheet(['DARK_BASE_DARKNESS', 'TAL_DARK_FEARFUL_DARKNESS']))
    turn(table, mid, FOE)
    engine = combat._load_session(mid).engine
    shapes = [a for a in engine.action_catalog.values()
              if a.owner_id == FOE and a.parameters.get('zone_shape')]
    offered = {c.source_definition_id for c in engine.legal_candidates()}
    assert any(a.display_name == 'Shape Darkness: Fearful Darkness'
               and a.source_definition_id in offered for a in shapes), {
        'current_actor': engine.state.current_actor_id,
        'shapes': [(a.display_name, a.source_definition_id,
                    engine.action_availability(FOE, a.source_definition_id)) for a in shapes],
        'foe_actions': [(a.display_name, a.parameters) for a in engine.action_catalog.values()
                        if a.owner_id == FOE],
    }


@pytest.mark.parametrize('cold', [False, True])
def test_brittle_opening_cannot_reclassify_the_primary_hit(tmp_path, cold):
    combat, table, mid = game(tmp_path)
    if cold:
        turn(table, mid, FOE)
        settle(table, mid, candidate(combat, mid, 'Piercing ward', target=FOE).candidate_id)
        turn(table, mid, OWNER)
    activate(combat, table, mid)
    before = len(combat._load_session(mid).engine.events)
    settle(table, mid, candidate(combat, mid, 'Shard Needle', target=FOE).candidate_id,
           choices={'choice:needle.fracture_response': 'brittle', 'choice:needle.brittle_type': 'COLD'})
    engine = reload(tmp_path, mid)
    packets = [e for e in engine.events[before:]
               if e.event_type == 'DAMAGE_COMMITTED' and e.actor_id == OWNER]
    assert packets[0].payload['damage_type'].lower() == ('cold' if cold else 'piercing')
    assert any(e.payload['damage_type'].lower() == 'cold' for e in packets[1:])
    # Two primary strikes and one real Fracture response; only an actually Cold
    # technique receives Palace's in-hit bonus and consumes the once-turn allowance.
    assert len(packets) == 3
    assert bool(engine.state.actors[OWNER].turn_flags.get(USED)) is cold
