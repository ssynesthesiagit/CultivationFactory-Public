"""Succor's base contract through imported characters and cold saved tables.

These checks use existing talent providers plus the base wrapper, whose
detailed procedure is retained in the full catalog sphere source.
"""
import hashlib
import json
import zipfile

import pytest

from combat.gate5_service import CombatService
from combat.tabletop import ButtonStore
from combat.tabletop_service import TabletopService
from combat.ext.protection import PUNISHMENT, aegises
from tests.h1_support import ROOT, sheet
from tests.r10_fixup_support import cast_sender, commit
from tests.test_hidden_targeting import turn
from tests.test_lock_choices import install

BASE = 'PROTECTION_BASE_SUCCOR'
OWNER, ALLY, FOE = ('actor:factory.' + pid for pid in ('aaaaaaaa', 'bbbbbbbb', 'ffffffff'))


def make_table(tmp_path, case):
    for aid in (OWNER, ALLY, FOE):
        talents = [BASE] if aid != FOE else []
        if aid == OWNER and case != 'base_only':
            talents.append(PUNISHMENT)
        document = sheet(talents, cl=1, kit={'starting_kit': {
            'items': [{'item_id': 'tianxia.mortal.weapon.jian'}]}})
        # The base is an automatic sphere grant, never a learned talent choice.
        block = document.get('spheres_and_talents')
        if block:
            block['learned_talent_record_ids'] = [talent for talent in block['learned_talent_record_ids']
                                                 if talent != BASE]
            assert BASE in block['automatic_sphere_component_record_ids']
        document['identity']['display_name'] = {OWNER: 'Owner', ALLY: 'Ally', FOE: 'Foe'}[aid]
        if case.startswith('range_') and aid == ALLY:
            document['ability_scores_and_statistics']['speed']['walking_ft'] = 400
        pid = aid.removeprefix('actor:factory.')
        folder = tmp_path / 'portable_characters' / pid
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(document))
        ButtonStore(tmp_path / 'tabletop_buttons').save_reactions(pid, {'mode': 'ask'}, {PUNISHMENT})
    combat = CombatService(ROOT, tmp_path)
    combat.tabletop_maps.save({'display_name': 'Succor contract',
        'width_squares': 68 if case.startswith('range_') else 10, 'height_squares': 8,
        'walls': [], 'starts': {'team1': [[3, 4], [3, 5]],
            'team2': [[65 if case == 'range_outside' else 64, 5]] if case.startswith('range_') else [[4, 5]]}})
    mid = combat.create_factory_match(project_ids=['aaaaaaaa', 'bbbbbbbb'], opponent_actor_ids=[FOE],
        control_modes={aid: 'MANUAL' for aid in (OWNER, ALLY, FOE)},
        arena_id='battlefield:map.succor-contract', match_seed='MGR-SUCCOR-BASE')['match_id']
    return combat, TabletopService(combat, tmp_path), mid


def cold(tmp_path, mid):
    combat = CombatService(ROOT, tmp_path)
    session = combat._load_session(mid)
    assert session.verify()['status'] == session.mechanical.replay()['status'] == 'PASS'
    return combat, TabletopService(combat, tmp_path), session.engine


def test_source_and_automatic_grant_contract():
    text = json.loads((ROOT / 'authority/typed_mechanics/rules_text.json').read_text())[BASE]
    assert hashlib.sha256(text.encode()).hexdigest() == '55ebdf8d8d0cd5b7e689052bc780991915719f8f73238fe7dad2fc613c38644d'
    catalog = json.loads((ROOT / 'catalog_authority/cat3/generated/catalog_authority.v1.json').read_text())
    spheres = catalog['spheres']
    rows = spheres.values() if isinstance(spheres, dict) else spheres
    packets = [p for sphere in rows for p in sphere.get('automatic_base_abilities', [])
               if p.get('candidate_record_id') == BASE]
    assert packets
    for packet in packets:
        assert packet['full_exact_source_text'] == text
        assert packet['automatic_grant'] and not packet['owner_removable']
        assert not any(packet[key] for key in ('counts_as_advancement_talent', 'counts_as_talent_choice',
                                               'counts_as_training_talent'))


@pytest.mark.parametrize('case', ['accept', 'decline', 'ai', 'base_only', 'no_aegis', 'transient',
                                 'other_owner', 'range_edge', 'range_outside', 'prevented'])
def test_native_talent_trigger_requires_own_current_persistent_aegis(monkeypatch, tmp_path, case):
    combat, table, mid = make_table(tmp_path, case)
    if case != 'no_aegis':
        creator = ALLY if case == 'other_owner' else OWNER
        turn(table, mid, creator)
        commit(cast_sender(combat, table, mid,
            'Aegis: Armored Aegis' + ('' if case == 'transient' else ' (Persistent)'), target=ALLY))
    # Reload the actual cast, not a manufactured mark or compiled test receipt.
    combat, table, engine = cold(tmp_path, mid)
    if case != 'no_aegis':
        assert aegises(engine.state.actors[ALLY], ALLY if case == 'other_owner' else OWNER,
                       persistent=case != 'transient')
    assert not any(a.display_name == 'Succor' for a in engine.action_catalog.values())
    if case.startswith('range_'):
        turn(table, mid, ALLY)
        destination = 64 if case == 'range_outside' else 63
        state = table.state(mid)
        candidate = next(c for c in combat._load_session(mid).engine.legal_candidates()
                         if c.destination and (c.destination.x, c.destination.y) == (destination, 5))
        commit(lambda answers=(): table.act(mid, candidate.candidate_id, candidate.decision_id,
               candidate.state_version, state['last_sequence'], list(answers)))
        combat, table, engine = cold(tmp_path, mid)
        assert engine.grid.distance_ft(engine.state.actors[OWNER].position, engine.state.actors[ALLY].position) == (
            305 if case == 'range_outside' else 300)
    if case == 'prevented':
        install(monkeypatch, 'final_damage', lambda engine, target, amount, dtype, source, *args:
                {'amount': 0} if source == PUNISHMENT else None)
    # Deterministic dice only: the opponent uses its real imported Jian action.
    install(monkeypatch, 'd20_result', lambda *args: {
        'source_id': 'test:succor-dice', 'operation': 'replace', 'natural_result': 20})
    turn(table, mid, FOE)
    if case == 'ai':
        combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    send = cast_sender(combat, table, mid, 'Jian', target=ALLY)
    engine = combat._load_session(mid).engine
    foreign_aegis_ids = {key for key, condition in aegises(engine.state.actors[ALLY])
                        if condition.source_actor_id != OWNER}
    before = engine.state.model_dump(mode='json')
    eligible = case in ('accept', 'decline', 'ai', 'range_edge', 'prevented')
    if eligible and case != 'ai':
        paused = send()
        assert paused['status'] == 'REACTION_REQUIRED'
        assert all(word in str(paused['reaction']) for word in ('Punishment', 'Jian', 'Ally'))
        assert combat._load_session(mid).engine.state.model_dump(mode='json') == before
        # A fresh service resumes the persisted prompt with no provider or model.
        combat, table, _ = cold(tmp_path, mid)
        send = cast_sender(combat, table, mid, 'Jian', target=ALLY)
    prompts = commit(send, lambda prompt: (None, case != 'decline'))
    _, _, engine = cold(tmp_path, mid)
    used = eligible and case != 'decline'
    damage = [event for event in engine.events if event.event_type == 'DAMAGE_COMMITTED'
              and event.source_definition_id == PUNISHMENT]
    assert len(damage) == int(used)
    if used:
        removals = [event for event in engine.events if event.event_type == 'CONDITION_REMOVED'
                    and ALLY in event.target_ids and event.sequence > 0]
        assert removals and removals[-1].sequence < damage[0].sequence
        if case == 'prevented':
            assert damage[0].payload['hp_damage'] == 0
    assert engine.state.actors[OWNER].reaction_available is not used
    if case != 'no_aegis':
        creator = ALLY if case == 'other_owner' else OWNER
        assert bool(aegises(engine.state.actors[ALLY], creator)) is not used
    assert foreign_aegis_ids <= {key for key, _ in aegises(engine.state.actors[ALLY])}
    if not eligible or case == 'ai':
        assert not prompts
