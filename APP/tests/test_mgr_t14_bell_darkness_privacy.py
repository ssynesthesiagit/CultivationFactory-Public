"""One native, persisted table scenario: Bell sight belongs to the mark's creator."""
import json
import zipfile
from pathlib import Path

from combat import senses, target_knowledge, zones
from combat.ext import mgr_reserve_bell_tower_cultivator_watch_bell as bell
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import sheet

ROOT = Path(__file__).resolve().parents[1]
OWNER, ALLY, FOE = ('actor:factory.bell-' + name for name in ('ringer', 'ally', 'foe'))


def commit(table, mid, candidate_id, selections=None):
    answers, prompts = [], []
    for _ in range(12):
        menu = table.state(mid)['menu']
        result = table.act(mid, candidate_id, menu['decision_id'], menu['state_version'], 0, answers)
        if result['status'] != 'REACTION_REQUIRED':
            assert result['status'] == 'COMMITTED', result
            return prompts
        prompt = result['reaction']
        prompts.append(prompt)
        context = prompt['context']
        selected = (selections or {}).get(context['reaction_source_id'])
        answer = {**context, 'selection': 'USE' if selected else 'DECLINE'}
        if selected:
            answer['option_ids'] = [selected]
        answers.append(answer)
    raise AssertionError('Unresolved native table choice')


def turn(table, mid, actor_id):
    for _ in range(6):
        menu = table.state(mid)['menu']
        if menu['actor_id'] == actor_id:
            return
        commit(table, mid, menu['end_turn'])
    raise AssertionError('Requested turn did not arrive')


def test_committed_darkness_keeps_bell_mark_private(tmp_path):
    ids = (OWNER, ALLY, FOE)
    # Same source-backed Watch Bell acquisition for both allies. Neither sheet
    # owns a Darkvision/Blindsight grant; no compiled/native capability is removed.
    documents = [sheet([bell.WATCH], cl=3, dc=100, name='Wren'),
                 sheet([bell.WATCH], cl=3, name='Tobin'),
                 sheet(['DARK_BASE_DARKNESS'], cl=3, name='Mara')]
    for aid, document in zip(ids, documents):
        folder = tmp_path / 'portable_characters' / aid.removeprefix('actor:factory.')
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(document))
    bundles = [compile_character(document, actor_id=aid, reaction_plan={'ask': True})
               for aid, document in zip(ids, documents)]
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    mid = combat._finish_factory_match(bundles, list(ids),
        {OWNER: 'team:bell', ALLY: 'team:bell', FOE: 'team:foe'},
        {OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 4, 'y': 6}, FOE: {'x': 6, 'y': 6}},
        combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'],
        [OWNER, ALLY], [FOE], control_modes={aid: 'MANUAL' for aid in ids},
        match_seed='BELL-DARK-0', display_name='Bell privacy', maximum_rounds=5)['match_id']

    def cold():
        fresh = CombatService(ROOT, tmp_path)
        session = fresh._load_session(mid)
        assert session.mechanical.replay()['status'] == 'PASS'
        return session.engine, TabletopService(fresh, tmp_path)

    def press(name, *, at=None):
        engine = combat._load_session(mid).engine
        options = [candidate for candidate in engine.legal_candidates()
                   if engine.action_catalog.get(candidate.source_definition_id)
                   and engine.action_catalog[candidate.source_definition_id].display_name == name
                   and (at is None or candidate.destination
                        and (candidate.destination.x, candidate.destination.y) == at)]
        assert options, name
        return options[0].candidate_id

    turn(table, mid, OWNER)
    engine, fresh_table = cold()
    for aid in (OWNER, ALLY):
        observer = engine.state.actors[aid]
        assert bell.owned(engine, observer)
        assert not {'darkvision', 'blindsight', 'truesight', 'spiritual_sense'} & senses.of(engine, observer).keys()
        assert senses.perceives(engine, observer, engine.state.actors[FOE])
        view = fresh_table.state(mid, fog=True, fog_view='own', fog_actor_ids=(aid,), include_menu=False)
        assert FOE in view['fog_perception'][aid]['creatures']
    before_qi = engine.state.actors[OWNER].resources['resource:core.qi']
    prompts = commit(table, mid, press('Watch Bell: Revealing Tone'),
                     {'choice:needle.bell_reveal_target': FOE})
    assert any(prompt['context']['reaction_source_id'] == 'choice:needle.bell_reveal_target'
               for prompt in prompts)
    engine, _ = cold()
    assert engine.state.actors[OWNER].resources['resource:core.qi'] == before_qi - 1
    assert not engine.state.actors[OWNER].bonus_action_available
    mark = bell.marks(engine.state.actors[FOE], engine.state.actors[OWNER])
    assert len(mark) == 1 and mark[0].expires_on == bell.UNTIL
    assert not bell.marks(engine.state.actors[FOE], engine.state.actors[ALLY])

    # Actual intervening turns, actual Darkness action, then a cold service and
    # table load. No injected condition, zone, observer identity or turn flags.
    turn(table, mid, FOE)
    commit(table, mid, press('Darkness', at=(6, 6)))
    engine, fresh_table = cold()
    owner, ally, foe = (engine.state.actors[aid] for aid in ids)
    darkness = [zone for zone in zones.typed_zones(engine)
                if (zone.trigger_profile.get('visual') or {}).get('darkness')]
    assert darkness, [zone.model_dump(mode='json') for zone in engine.state.zones.values()]
    assert any(zone.owner_id == FOE and zones.actor_inside_zone(engine, foe, zone) for zone in darkness)
    assert bell.marks(foe, owner) and not bell.marks(foe, ally)
    assert not senses.perceives(engine, ally, foe), {'ally_senses': senses.of(engine, ally)}
    assert senses.perceives(engine, owner, foe)
    assert target_knowledge.can_see(engine, owner, foe)
    assert not target_knowledge.can_see(engine, ally, foe)
    assert target_knowledge.knowledge(engine, owner, foe).mode == 'DIRECT'
    remembered = target_knowledge.knowledge(engine, ally, foe)
    assert remembered is None or remembered.mode == 'LAST_OBSERVED'
    for aid, sees in ((OWNER, True), (ALLY, False)):
        view = fresh_table.state(mid, fog=True, fog_view='own', fog_actor_ids=(aid,), include_menu=False)
        assert set(view['fog_perception']) == {aid}
        assert (FOE in view['fog_perception'][aid]['creatures']) is sees
