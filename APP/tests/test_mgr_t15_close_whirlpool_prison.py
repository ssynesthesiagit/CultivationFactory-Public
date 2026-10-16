"""Portable native imports, legal table commits, cold continuation and replay.

Dynamic authority dependencies for the public exporter are literal below;
Crushing Current supplies the shared Drowning Pressure option definitions only.
No owner archive, live model transport or synthetic benefit is used.
"""
import json
import zipfile
from pathlib import Path

import pytest

from combat.gate4_engine import Gate4ControllerEngine
from combat.gate5_service import CombatService
from combat.tabletop import ButtonStore
from combat.tabletop_service import TabletopService

ROOT = Path(__file__).resolve().parents[1]
WHIRLPOOL = 'TAL_WATER_WHIRLPOOL_PRISON'
PRESSURE_OPTIONS = 'TAL_WATER_CRUSHING_CURRENT'
BASES = ['WATER_BASE_RETURN_THE_FLOW', 'WATER_BASE_SHAPE_CURRENT',
         'WATER_BASE_WATER_INITIATION', 'WATER_BASE_WATER_LASH']
OWNER, ALLY, FOE = [f'actor:factory.{p}' for p in ('aaaaaaaa', 'bbbbbbbb', 'cccccccc')]
UPGRADE = 'Shape Current: Pressure Basin + Whirlpool Prison'
ORDINARY = 'Shape Current: Pressure Basin'
CHOICE = 'choice:needle.drowning_pressure'


def document(name, owned, water=True):
    return {'identity': {'name': name, 'cultivation_level': 10, 'proficiency_bonus': 4,
                         'path': 'Qi Cultivation', 'key_ability': 'CON'},
            'ability_scores_and_statistics': {
                'abilities': [{'ability': a, 'score': 14, 'modifier': 2} for a in ('STR', 'DEX', 'CON', 'INT', 'WIS', 'CHA')],
                'primary_resource': {'name': 'Qi', 'maximum': 30}, 'armor_class': {'base_value': 14},
                'hit_points': {'maximum': 60}, 'speed': {'walking_ft': 30},
                'technique_save_dc': 16, 'technique_attack_bonus': 8},
            'spheres_and_talents': {'sphere_record_ids': ['tianxia.sphere.water'] if water else [],
                'automatic_sphere_component_record_ids': BASES if water else [],
                'learned_talent_record_ids': [WHIRLPOOL] if owned else []}}


def native(tmp_path, *, owned=True, dual=False):
    for aid, name in zip((OWNER, ALLY, FOE), ('Owner', 'Ally', 'Foe')):
        pid = aid.removeprefix('actor:factory.')
        folder = tmp_path / 'portable_characters' / pid
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as archive:
            water = aid == OWNER or dual and aid == ALLY
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(document(name, owned and water, water)))
        ButtonStore(tmp_path / 'tabletop_buttons').save_reactions(pid, {'mode': 'ask'}, {WHIRLPOOL})
    combat = CombatService(ROOT, tmp_path)
    saved = combat.tabletop_maps.save({'display_name': 'Whirlpool native', 'width_squares': 18,
        'height_squares': 14, 'walls': [], 'starts': {'team1': [[2, 6], [6, 5]], 'team2': [[10, 6]]}})
    mid = combat.create_factory_match(project_ids=['aaaaaaaa', 'bbbbbbbb'], opponent_actor_ids=[FOE],
        control_modes={a: 'MANUAL' for a in (OWNER, ALLY, FOE)},
        arena_id='battlefield:map.' + saved['map_id'], match_seed='MGR-T15-WHIRLPOOL')['match_id']
    table = TabletopService(combat, tmp_path)
    advance(combat, table, mid, OWNER)
    return combat, table, mid


def cold(tmp_path, mid):
    combat = CombatService(ROOT, tmp_path)
    loaded = combat._load_session(mid)
    assert loaded.mechanical.replay()['status'] == 'PASS'
    return combat, TabletopService(combat, tmp_path), loaded.engine


def choose(combat, mid, name, at=None):
    engine = combat._load_session(mid).engine
    rows = [c for c in engine.legal_candidates()
            if getattr(engine.action_catalog.get(c.source_definition_id), 'display_name', c.display_name) == name
            and (at is None or c.destination and (c.destination.x, c.destination.y) == at)]
    assert rows, (name, at, sorted({c.display_name for c in engine.legal_candidates()}))
    return rows[0]


def commit(table, mid, c, option='speech'):
    answers, prompts = [], []
    for _ in range(16):
        state = table.state(mid)
        result = table.act(mid, c.candidate_id, c.decision_id, c.state_version, state['last_sequence'], answers)
        if result['status'] == 'COMMITTED':
            return prompts
        assert result['status'] == 'REACTION_REQUIRED', result
        prompt = result['reaction']
        prompts.append(prompt)
        options = (prompt.get('choice') or {}).get('options') or []
        selected = option if any(o['id'] == option for o in options) else (options[0]['id'] if options else None)
        answers.append({**prompt['context'], 'selection': 'USE' if selected else 'DECLINE',
                        'option_ids': [selected] if selected else []})
    raise AssertionError('unsettled table prompt')


def advance(combat, table, mid, actor):
    for _ in range(12):
        if table.state(mid)['menu']['actor_id'] == actor:
            return
        commit(table, mid, choose(combat, mid, 'End turn'))
    raise AssertionError('turn did not arrive')


def dice(monkeypatch, face):
    """Script only dice; all save resolution, choices and commits stay native."""
    original = Gate4ControllerEngine.execute_intent
    def execute(engine, *args, **kwargs):
        die = engine.roller._die
        def fixed(sides):
            counter = engine.roller.counter
            engine.roller.counter += 1
            return min(face[0], sides), counter
        engine.roller._die = fixed
        try:
            return original(engine, *args, **kwargs)
        finally:
            engine.roller._die = die
    monkeypatch.setattr(Gate4ControllerEngine, 'execute_intent', execute)


def conditions(engine, actor, name):
    return [c for c in engine.state.actors[actor].conditions.values()
            if c.condition_id == 'condition:typed.' + name]


def saves(engine, start=0):
    return [e for e in engine.events[start:] if e.event_type == 'SAVE_ROLLED' and e.actor_id == FOE]


def move(combat, table, mid, at):
    rows = [c for c in combat._load_session(mid).engine.legal_candidates()
            if c.source_definition_id == 'system:combat.movement' and c.destination
            and (c.destination.x, c.destination.y) == at]
    assert rows, at
    commit(table, mid, rows[0])


@pytest.mark.parametrize('owned,upgrade,cost', [(True, True, 3), (True, False, 1), (False, False, 1)])
def test_native_import_optional_cost_and_radius(tmp_path, owned, upgrade, cost):
    combat, table, mid = native(tmp_path, owned=owned)
    engine = combat._load_session(mid).engine
    if not owned:
        assert not any(a.display_name == UPGRADE for a in engine.action_catalog.values())
    before = engine.state.actors[OWNER].resources['resource:core.qi']
    commit(table, mid, choose(combat, mid, UPGRADE if upgrade else ORDINARY, (6, 6)))
    _, _, engine = cold(tmp_path, mid)
    assert before - engine.state.actors[OWNER].resources['resource:core.qi'] == cost
    zone = next(z for z in engine.state.zones.values() if z.active and z.owner_id == OWNER)
    assert zone.radius_cells == (4 if upgrade else 2)
    if upgrade:
        assert zone.trigger_profile['shape'] == 'sphere'
        cells = {(p.x, p.y) for p in zone.affected_cells}
        assert (10, 6) in cells and (11, 6) not in cells
        assert not saves(engine), 'creating the area is neither entry nor turn start'
        assert not conditions(engine, ALLY, 'restrained')


@pytest.mark.parametrize('option', ['speech', 'reactions', 'concentration', 'healing'])
@pytest.mark.parametrize('victim_mode', ['MANUAL', 'LOCAL_AUTO'])
def test_native_failed_start_pressure_choice_and_action_escape(tmp_path, monkeypatch, option, victim_mode):
    face = [1]
    dice(monkeypatch, face)
    combat, table, mid = native(tmp_path)
    commit(table, mid, choose(combat, mid, UPGRADE, (6, 6)))
    combat.set_controller_mode(mid, actor_id=FOE, controller_mode=victim_mode)
    # Ask choices belong to the Basin owner even when the victim's turn starts.
    prompts = []
    while table.state(mid)['menu']['actor_id'] != FOE:
        prompts += commit(table, mid, choose(combat, mid, 'End turn'), option)
    combat, table, engine = cold(tmp_path, mid)
    assert len(saves(engine)) == 1
    held = conditions(engine, FOE, 'restrained')
    assert len(held) == 1 and not held[0].data.get('repeat_save')
    pressure = [p for p in prompts if p['context']['reaction_source_id'] == CHOICE]
    assert len(pressure) == 1 and pressure[0]['context']['reactor_id'] == OWNER
    prompt_text = str(pressure[0])
    assert 'Whirlpool Prison' in prompt_text and 'Foe' in prompt_text
    assert any('drowning_pressure' in c.condition_id for c in engine.state.actors[FOE].conditions.values())
    if option == 'speech':
        assert conditions(engine, FOE, 'silenced')
    elif option == 'reactions':
        assert conditions(engine, FOE, 'reaction_denied')
    else:
        assert engine.state.actors[FOE].modifiers, 'the selected option must impose a real modifier'
    # A committed failed escape costs the Action and keeps this exact restraint.
    # Switch seats through the public producer before manually submitting the
    # escape. Merely starting an automatic victim's turn needs no model call.
    combat.set_controller_mode(mid, actor_id=FOE, controller_mode='MANUAL')
    iid = held[0].instance_id
    commit(table, mid, choose(combat, mid, 'Break free'))
    combat, table, engine = cold(tmp_path, mid)
    assert iid in engine.state.actors[FOE].conditions
    assert not engine.state.actors[FOE].action_available


def test_native_success_start_and_reentry_clock(tmp_path, monkeypatch):
    dice(monkeypatch, [20])
    combat, table, mid = native(tmp_path)
    commit(table, mid, choose(combat, mid, UPGRADE, (6, 6)))
    advance(combat, table, mid, FOE)
    combat, table, engine = cold(tmp_path, mid)
    assert len(saves(engine)) == 1 and not conditions(engine, FOE, 'restrained')
    assert any(m.value == -10 for m in engine.state.actors[FOE].modifiers.values())
    # Start and first entry are independently printed events; repeated entry on
    # this same turn is suppressed. Boundary squares use actual legal movement.
    for at in [(11, 6), (10, 6), (11, 6), (10, 6)]:
        move(combat, table, mid, at)
    combat, table, engine = cold(tmp_path, mid)
    assert len(saves(engine)) == 2
    commit(table, mid, choose(combat, mid, 'End turn'))
    advance(combat, table, mid, FOE)
    _, _, engine = cold(tmp_path, mid)
    assert len(saves(engine)) == 3


def test_native_escape_success_after_cold_reload(tmp_path, monkeypatch):
    face = [1]
    dice(monkeypatch, face)
    combat, table, mid = native(tmp_path)
    commit(table, mid, choose(combat, mid, UPGRADE, (6, 6)))
    advance(combat, table, mid, FOE)
    combat, table, engine = cold(tmp_path, mid)
    assert conditions(engine, FOE, 'restrained')
    face[0] = 20
    commit(table, mid, choose(combat, mid, 'Break free'))
    _, _, engine = cold(tmp_path, mid)
    assert not conditions(engine, FOE, 'restrained')
    assert not engine.state.actors[FOE].action_available
    assert len(saves(engine)) == 2


def test_native_expiry_has_no_free_end_turn_save(tmp_path, monkeypatch):
    dice(monkeypatch, [1])
    combat, table, mid = native(tmp_path)
    commit(table, mid, choose(combat, mid, UPGRADE, (6, 6)))
    advance(combat, table, mid, FOE)
    combat, table, engine = cold(tmp_path, mid)
    old = conditions(engine, FOE, 'restrained')[0].instance_id
    commit(table, mid, choose(combat, mid, 'End turn'))
    combat, table, engine = cold(tmp_path, mid)
    assert len(saves(engine)) == 1, 'no automatic end-of-turn repeat is printed'
    advance(combat, table, mid, FOE)
    _, _, engine = cold(tmp_path, mid)
    assert old not in engine.state.actors[FOE].conditions
    assert len(conditions(engine, FOE, 'restrained')) == 1 and len(saves(engine)) == 2


def test_native_overlap_escape_is_source_isolated(tmp_path, monkeypatch):
    face = [1]
    dice(monkeypatch, face)
    combat, table, mid = native(tmp_path, dual=True)
    commit(table, mid, choose(combat, mid, UPGRADE, (6, 6)))
    advance(combat, table, mid, ALLY)
    commit(table, mid, choose(combat, mid, UPGRADE, (6, 6)))
    since = len(combat._load_session(mid).engine.events)
    advance(combat, table, mid, FOE)
    combat, table, engine = cold(tmp_path, mid)
    assert len(saves(engine, since)) == 2
    held = conditions(engine, FOE, 'restrained')
    assert {c.source_actor_id for c in held} == {OWNER, ALLY}
    assert not conditions(engine, ALLY, 'restrained') and not conditions(engine, OWNER, 'restrained')
    face[0] = 20
    commit(table, mid, choose(combat, mid, 'Break free'))
    _, _, engine = cold(tmp_path, mid)
    remaining = conditions(engine, FOE, 'restrained')
    assert len(remaining) == 1 and remaining[0].instance_id in {c.instance_id for c in held}
    assert not engine.state.actors[FOE].action_available


def test_native_ending_water_effect_stops_whirlpool(tmp_path, monkeypatch):
    dice(monkeypatch, [1])
    combat, table, mid = native(tmp_path)
    commit(table, mid, choose(combat, mid, UPGRADE, (6, 6)))
    advance(combat, table, mid, FOE)
    commit(table, mid, choose(combat, mid, 'End turn'))
    advance(combat, table, mid, OWNER)
    # Factory characters may hold multiple concentration effects. Use the actual
    # Water ending action rather than assuming a second Basin cancels the first.
    commit(table, mid, choose(combat, mid, 'Return the Flow: End It Early'))
    combat, table, engine = cold(tmp_path, mid)
    assert not any(z.active and 'Whirlpool Prison' in engine.action_catalog[z.source_definition_id].display_name
                   for z in engine.state.zones.values())
    assert engine.state.actors[OWNER].concentration is None
    count = len(saves(engine))
    advance(combat, table, mid, FOE)
    _, _, engine = cold(tmp_path, mid)
    assert len(saves(engine)) == count and not conditions(engine, FOE, 'restrained')


def test_native_allied_start_and_boundary_entry_are_inert(tmp_path, monkeypatch):
    dice(monkeypatch, [1])
    combat, table, mid = native(tmp_path)
    commit(table, mid, choose(combat, mid, UPGRADE, (6, 6)))
    advance(combat, table, mid, ALLY)
    move(combat, table, mid, (6, 1))  # outside the actual 20-foot radius
    move(combat, table, mid, (6, 2))  # first entry at its boundary
    _, _, engine = cold(tmp_path, mid)
    assert not any(e.event_type == 'SAVE_ROLLED' and e.actor_id in {OWNER, ALLY} for e in engine.events)
    assert not conditions(engine, ALLY, 'restrained')
    assert not any('drowning_pressure' in c.condition_id for c in engine.state.actors[ALLY].conditions.values())


def test_native_automatic_basin_owner_decides_pressure_without_human_prompt(tmp_path, monkeypatch):
    dice(monkeypatch, [1])
    combat, table, mid = native(tmp_path, dual=True)
    order = combat._load_session(mid).engine.state.initiative_order
    before_foe = order[order.index(FOE) - 1]
    caster = ALLY if before_foe == OWNER else OWNER
    # Cast with the other allied fighter, then switch that fighter's seat while
    # the manual fighter immediately preceding the victim is active. The real
    # End turn producer starts the victim and delivers the automatic owner's
    # decision; no model action selection or live model transport is needed.
    advance(combat, table, mid, caster)
    commit(table, mid, choose(combat, mid, UPGRADE, (6, 6)))
    advance(combat, table, mid, before_foe)
    combat.set_controller_mode(mid, actor_id=caster, controller_mode='LOCAL_AUTO')
    prompts = commit(table, mid, choose(combat, mid, 'End turn'))
    _, _, engine = cold(tmp_path, mid)
    assert engine.state.current_actor_id == FOE
    assert conditions(engine, FOE, 'restrained')
    assert conditions(engine, FOE, 'silenced'), 'automatic owner takes the canonical preferred pressure option'
    assert not any(p['context']['reaction_source_id'] == CHOICE for p in prompts)
