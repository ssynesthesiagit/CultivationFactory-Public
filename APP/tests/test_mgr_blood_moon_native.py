"""Blood-Moon acquisition -> table intent -> committed state -> cold replay.

Only dice are scripted. No feature ownership, hit, mark, anatomy or authority
receipt is injected into a combat state. GM declarations use the real endpoint.
"""
from pathlib import Path
import pytest

from combat import table_advance
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import sheet
from tests.hunt12_support import candidate, send, hit_dice
from tests.test_a2_group_traditions_2 import commit, end, advance, cold
from combat.ext.mgr_reserve_blood_moon_execution_saber_cultivator_write_the_first_sentence import ROWS, MARK, STATE

ROOT = Path(__file__).resolve().parents[1]
ME, FOE = 'actor:factory.fix12', 'actor:factory.fix12-foe'
PROJECT = '0badc0de-0000-4000-8000-000000000014'
PATH = 'tianxia.path.qi_cultivation'
QI = 'resource:core.qi'
ACCESS = {'kind': 'scripture', 'classification': 'Restricted Scripture', 'reference': 'campaign:execution-hall-scroll'}
DAO = {'items': [{'item_id': 'tianxia.mortal.weapon.dao', 'name': 'Dao', 'quantity': 1}]}


def scene(tmp_path, cl=18, *, acquire=True, foe_hp=1000, foe_features=()):
    original = sheet([], cl=cl, dc=100, primary='Qi', kit=DAO, name='Executioner')
    original['equipment'] = [{'starting_kit': DAO}]
    original['path_and_subpath'] = {'path_record_ids': [PATH]}
    original['ability_scores_and_statistics']['hit_points']['maximum'] = 1000
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    combat._factory_owner_sheet = lambda project: table_advance.apply(original, table.buttons.get(project).get('advancement'))
    if acquire:
        for tier, source in ROWS.items():
            if tier <= cl:
                table.acquire_feature(PROJECT, source, ACCESS)
    owner = combat._factory_owner_sheet(PROJECT)
    foe = sheet(foe_features, cl=18, primary='Qi', kit=DAO, name='Subject')
    foe['equipment'] = [{'starting_kit': DAO}]
    foe['ability_scores_and_statistics']['hit_points']['maximum'] = foe_hp
    bundles = [compile_character(doc, actor_id=aid, reaction_plan={'ask': True}) for aid, doc in ((ME, owner), (FOE, foe))]
    mid = combat._finish_factory_match(bundles, [ME, FOE], {ME: 'team:a', FOE: 'team:b'},
        {ME: {'x': 3, 'y': 6}, FOE: {'x': 4, 'y': 6}},
        combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'], [ME], [FOE],
        control_modes={ME: 'MANUAL', FOE: 'MANUAL'}, match_seed='BLOOD-MOON', maximum_rounds=20,
        display_name='Blood-Moon regression')['match_id']
    advance(combat, table, mid, ME)
    return combat, table, mid


def strike(combat, table, mid, picks=('Apply Blood-Moon Mark',), *, special=None):
    engine = combat._load_session(mid).engine
    chosen = candidate(combat, mid, lambda c: c.actor_id == ME and FOE in c.target_ids
        and (special in c.display_name and '.weapon.' in c.source_definition_id if special else '.weapon.' in c.source_definition_id and '#' not in c.source_definition_id))
    return commit(combat, table, mid, chosen, picks)


def accumulate(combat, table, mid):
    for n in range(3):
        strike(combat, table, mid)
        engine = combat._load_session(mid).engine
        assert len([c for c in engine.state.actors[FOE].conditions.values() if c.condition_id == MARK]) == n + 1
        end(combat, table, mid)
        advance(combat, table, mid, ME)


def test_blood_moon_acquisition_and_three_native_marks(tmp_path, monkeypatch):
    combat, table, mid = scene(tmp_path)
    hit_dice(monkeypatch, save_roll=1)
    accumulate(combat, table, mid)
    engine = cold(tmp_path, mid)
    assert len([c for c in engine.state.actors[FOE].conditions.values() if c.condition_id == MARK]) == 3
    assert engine.state.actors[ME].resources[QI] == 27
    view = table.state(mid, fog=True, fog_view='own', fog_actor_ids=(ME, FOE))['fog_perception']
    lines = view[ME]['information_text']
    assert 'Blood-Moon Mark: Direction to a creature bearing your mark: east.' in lines
    assert not any('half its maximum HP or less is nearby' in line for line in lines)
    assert not any('Blood-Moon Mark:' in line for line in view[FOE].get('information_text', []))
    assert any('Moon-Edged Sentence' in c.display_name for c in engine.legal_candidates())
    assert not any(c.condition_id == 'condition:typed.incapacitated' for c in engine.state.actors[FOE].conditions.values())


def test_blood_moon_wrong_owner_and_default_inert(tmp_path, monkeypatch):
    combat, table, mid = scene(tmp_path, acquire=False)
    hit_dice(monkeypatch)
    assert not any('Execution Line' in c.display_name or 'Moon-Edged' in c.display_name for c in combat._load_session(mid).engine.legal_candidates())
    strike(combat, table, mid)
    engine = cold(tmp_path, mid)
    assert not any(c.condition_id == MARK for a in engine.state.actors.values() for c in a.conditions.values())


def test_blood_moon_execution_closes_meridian_after_reload(tmp_path, monkeypatch):
    combat, table, mid = scene(tmp_path)
    hit_dice(monkeypatch, save_roll=1)
    accumulate(combat, table, mid)
    strike(combat, table, mid, ('Closed Meridian',), special='Moon-Edged Sentence')
    engine = cold(tmp_path, mid)
    target = engine.state.actors[FOE]
    assert not any(c.condition_id == MARK for c in target.conditions.values())
    assert any(c.condition_id == STATE and c.data['kind'] == 'cp_recovery' for c in target.conditions.values())
    assert engine.state.actors[ME].resources[QI] == 22


def test_blood_moon_two_sentences_and_hemorrhage(tmp_path, monkeypatch):
    combat, table, mid = scene(tmp_path, cl=6)
    hit_dice(monkeypatch, save_roll=1)
    accumulate(combat, table, mid)
    strike(combat, table, mid, (('Close the Wound', 'Cut the Step'),))
    engine = cold(tmp_path, mid)
    target = engine.state.actors[FOE]
    assert any(c.data.get('kind') == 'hemorrhage' for c in target.conditions.values())
    hp = target.current_hp
    end(combat, table, mid)
    engine = cold(tmp_path, mid)
    assert engine.state.actors[FOE].current_hp < hp


@pytest.mark.parametrize('cl', [3, 6, 10, 14, 18])
def test_blood_moon_progression_native_access(tmp_path, cl):
    combat, table, mid = scene(tmp_path, cl=cl)
    engine = cold(tmp_path, mid)
    rows = [r for r in engine.typed_passive_rows[ME] if r.get('block') == 'blood_moon']
    assert {r['tier'] for r in rows} == {tier for tier in ROWS if tier <= cl}


def test_blood_moon_anatomy_is_owner_recorded_and_persisted(tmp_path):
    combat, table, mid = scene(tmp_path)
    engine = combat._load_session(mid).engine
    document = {'record_id': 'source:anatomy', 'subject_id': FOE, 'subject_name': 'Subject',
        'subject_kind': 'creature', 'position': {'x': 4, 'y': 6}, 'source_reference': 'campaign:creature-profile',
        'witness_ids': [ME], 'valid_through_round': 20,
        'answers': {'arm': {'fact': 'The left arm holds the saber.', 'category': 'anatomy',
            'visible_sign': 'left arm', 'source_cl': 18,
            'relationship': {'key': 'left_arm', 'kind': 'structure', 'name': 'Left arm',
                'source_reference': 'campaign:creature-profile'}}}}
    assert table.record_fact(mid, document, expected_state_version=engine.state.state_version)['status'] == 'COMMITTED'
    from combat.table_facts import records
    engine = cold(tmp_path, mid)
    assert records(engine, engine.state.actors[ME])['source:anatomy'].answers['arm'].relationship.name == 'Left arm'
    assert not records(engine, engine.state.actors[FOE])


def test_blood_moon_scene_boundary_removes_marks_and_private_readings(tmp_path, monkeypatch):
    combat, table, mid = scene(tmp_path)
    hit_dice(monkeypatch)
    strike(combat, table, mid)
    engine = cold(tmp_path, mid)
    document = {'record_id': 'scene:ended', 'subject_id': 'scene:encounter', 'subject_name': 'The encounter ended',
        'subject_kind': 'event', 'position': {'x': 3, 'y': 6},
        'source_reference': 'GM: the continuous meaningful situation has ended',
        'witness_ids': [ME, FOE], 'valid_through_round': 20, 'answers': {}, 'scene_ended': True}
    assert table.record_fact(mid, document, expected_state_version=engine.state.state_version)['status'] == 'COMMITTED'
    engine = cold(tmp_path, mid)
    assert not any(c.condition_id == MARK for a in engine.state.actors.values() for c in a.conditions.values())
    assert not any(c.condition_id == 'condition:information.reading' for c in engine.state.actors[ME].conditions.values())


def test_blood_moon_mark_cap_never_spends_a_fourth_qi(tmp_path, monkeypatch):
    combat, table, mid = scene(tmp_path)
    hit_dice(monkeypatch)
    accumulate(combat, table, mid)
    prompts = strike(combat, table, mid)
    engine = cold(tmp_path, mid)
    assert len([c for c in engine.state.actors[FOE].conditions.values() if c.condition_id == MARK]) == 3
    assert engine.state.actors[ME].resources[QI] == 27
    assert not any(p['context']['reaction_source_id'] == 'choice:needle.blood_moon_mark' for p in prompts)


def test_blood_moon_final_sentence_hides_empty_fact_choices(tmp_path, monkeypatch):
    from combat.ext.mgr_reserve_blood_moon_execution_saber_cultivator_write_the_first_sentence import final_sentence_options
    combat, table, mid = scene(tmp_path)
    hit_dice(monkeypatch)
    accumulate(combat, table, mid)
    engine = combat._load_session(mid).engine
    target = engine.state.actors[FOE]
    class Context:
        pass
    ctx = Context()
    ctx.engine, ctx.target, ctx.actor = engine, target, engine.state.actors[ME]
    assert final_sentence_options(ctx) == ['Death']


def test_blood_moon_final_miss_spends_qi_one_mark_and_scene_use(tmp_path, monkeypatch):
    combat, table, mid = scene(tmp_path)
    hit_dice(monkeypatch)
    accumulate(combat, table, mid)
    monkeypatch.undo()
    from combat.gate4_engine import Gate4ControllerEngine
    from tests.h1_support import script
    original = Gate4ControllerEngine._resolve_attack_spec
    def miss(engine, *args, **kwargs):
        script(engine, [1] * 60)
        return original(engine, *args, **kwargs)
    monkeypatch.setattr(Gate4ControllerEngine, '_resolve_attack_spec', miss)
    strike(combat, table, mid, special='Blood Moon Falls')
    engine = cold(tmp_path, mid)
    assert engine.state.actors[ME].resources[QI] == 19
    assert len([c for c in engine.state.actors[FOE].conditions.values() if c.condition_id == MARK]) == 2
    assert any(c.data.get('kind') == 'final_used' for c in engine.state.actors[ME].conditions.values())
    monkeypatch.undo()
    hit_dice(monkeypatch)
    end(combat, table, mid)
    advance(combat, table, mid, ME)
    # Recovering the third mark does not reset the scene limit.
    strike(combat, table, mid)
    engine = cold(tmp_path, mid)
    assert len([c for c in engine.state.actors[FOE].conditions.values() if c.condition_id == MARK]) == 3
    assert not any('Blood Moon Falls' in c.display_name for c in engine.legal_candidates())


def test_blood_moon_sever_life_uses_native_dying_and_two_failures(tmp_path, monkeypatch):
    combat, table, mid = scene(tmp_path, cl=14, foe_hp=60)
    hit_dice(monkeypatch, save_roll=1)
    accumulate(combat, table, mid)
    engine = combat._load_session(mid).engine
    # Fixed dice: accumulation leaves the foe at 33 of 60 HP (above the band), so one more unconditional strike is needed.
    assert engine.state.actors[FOE].current_hp == 33
    strike(combat, table, mid, picks=())
    end(combat, table, mid)
    advance(combat, table, mid, ME)
    strike(combat, table, mid, ('Sever Life from Body',), special='Moon-Edged Sentence')
    engine = cold(tmp_path, mid)
    target = engine.state.actors[FOE]
    from combat.ext.life_state import encounter_death_saves
    assert target.current_hp == 0 and target.life_state == 'DYING'
    assert encounter_death_saves(target) == {'ok': 0, 'bad': 2}
    assert engine.state.actors[ME].resources[QI] == 19


def test_blood_moon_cut_breath_surcharge_is_paid_by_native_activation(tmp_path, monkeypatch):
    # Qi Armor is a reaction, never a primary candidate, so a foe holding it has no Qi-powered action
    # on its own turn. Tears like Pearls is a 1-Qi Action talent: the Cut the Breath surcharge applies to it.
    tears = 'tianxia.talent.beauty.tears_like_pearls'
    combat, table, mid = scene(tmp_path, cl=6, foe_features=(tears,))
    hit_dice(monkeypatch)
    strike(combat, table, mid)
    end(combat, table, mid)
    advance(combat, table, mid, ME)
    strike(combat, table, mid, ('Cut the Breath',))
    end(combat, table, mid)
    advance(combat, table, mid, FOE)
    engine = combat._load_session(mid).engine
    chosen = candidate(combat, mid, lambda c: c.actor_id == FOE and c.source_definition_id in engine.action_catalog
        and (engine.action_catalog[c.source_definition_id].parameters.get('typed') or {}).get('source') == tears)
    base = sum(n for pool, n in engine.action_catalog[chosen.source_definition_id].costs if pool == QI)
    before = engine.state.actors[FOE].resources[QI]
    commit(combat, table, mid, chosen)
    engine = cold(tmp_path, mid)
    assert engine.state.actors[FOE].resources[QI] == before - base - 2
    assert not any(c.data.get('kind') == 'surcharge' for c in engine.state.actors[FOE].conditions.values())


def test_blood_moon_marked_cut_uses_receipt_despite_intervening_logs(tmp_path, monkeypatch):
    combat, table, mid = scene(tmp_path, cl=3)
    hit_dice(monkeypatch)
    from tests.hunt12_support import event_hook
    def log_noise(engine, event_type, kwargs):
        if event_type == 'DAMAGE_COMMITTED':
            for index in range(20):
                engine._append_event('PASSIVE_TRIGGERED', 'test:observational-log-noise',
                    actor_id=ME, payload={'text': f'An unrelated observation {index}.'})
    event_hook(monkeypatch, log_noise)
    strike(combat, table, mid)
    engine = cold(tmp_path, mid)
    packets = [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED'
               and e.actor_id == ME and FOE in e.target_ids]
    # Scripted normal Dao damage plus PB 4 + one actual native mark.
    assert len(packets) == 2
    assert packets[-1].payload['hp_damage'] == 5
    assert engine.state.actors[FOE].current_hp == 1000 - sum(e.payload['hp_damage'] for e in packets)


@pytest.mark.parametrize('round_no', [1, 2, 3])
def test_blood_moon_acquisition_commit_reload_stress(tmp_path, monkeypatch, round_no):
    # Repeats acquire -> commit -> cold reload in fresh scenes; counts must hold after every reload.
    for attempt in range(round_no):
        sub = tmp_path / f'attempt{attempt}'
        sub.mkdir()
        combat, table, mid = scene(sub, cl=6)
        hit_dice(monkeypatch, save_roll=1)
        strike(combat, table, mid)
        first = cold(sub, mid)
        marks = len([c for c in first.state.actors[FOE].conditions.values() if c.condition_id == MARK])
        assert marks == 1
        again = cold(sub, mid)
        assert len([c for c in again.state.actors[FOE].conditions.values() if c.condition_id == MARK]) == 1
        assert again.state.actors[ME].resources[QI] == first.state.actors[ME].resources[QI]

