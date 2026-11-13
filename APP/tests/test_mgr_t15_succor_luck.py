"""Luck's complete save trigger through portable imports and saved table intents."""
import json
import zipfile

import pytest

from combat.ext.protection import LUCK, aegises
from combat.gate5_service import CombatService
from combat.tabletop import ButtonStore
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.r10_fixup_support import cast_sender, commit, fixed_dice
from tests.test_hidden_targeting import turn
from tests.test_mgr_t14_succor_base import BASE, OWNER, ALLY, FOE, cold


def native_table(tmp_path, case):
    # This is a runtime data dependency, including in the public CI export.
    registry = json.loads((ROOT / 'combat/rules/feature_blocks.d/riders_c4.json').read_text())
    assert registry['features'][LUCK]['kind'] == 'protection_luck'
    for aid in (OWNER, ALLY, FOE):
        talents = [BASE] if aid != FOE else ['SAND_BASE_SCOURING_HAND']
        if aid == FOE and case == 'own_turn':
            talents.append('tianxia.talent.protection.impedance')
        if aid == OWNER:
            if case != 'base_only':
                talents.append(LUCK)
        document = sheet(talents, cl=1, dc=16)
        block = document['spheres_and_talents']
        block['learned_talent_record_ids'] = [t for t in block['learned_talent_record_ids']
                                             if t not in block['automatic_sphere_component_record_ids']]
        document['identity']['display_name'] = {OWNER: 'Owner', ALLY: 'Ally', FOE: 'Foe'}[aid]
        if case.startswith('range_') and aid == OWNER:
            document['ability_scores_and_statistics']['speed']['walking_ft'] = 400
        pid = aid.removeprefix('actor:factory.')
        folder = tmp_path / 'portable_characters' / pid
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(document))
        ButtonStore(tmp_path / 'tabletop_buttons').save_reactions(pid, {'mode': 'ask'}, {LUCK})
    combat = CombatService(ROOT, tmp_path)
    saved = combat.tabletop_maps.save({'display_name': 'Luck native',
        'width_squares': 68 if case.startswith('range_') else 10, 'height_squares': 8,
        'walls': [], 'starts': {'team1': [[1 if case == 'own_turn' else 3, 4], [3, 5]], 'team2': [[4, 5]]}})
    mid = combat.create_factory_match(project_ids=['aaaaaaaa', 'bbbbbbbb'], opponent_actor_ids=[FOE],
        control_modes={aid: 'MANUAL' for aid in (OWNER, ALLY, FOE)},
        arena_id='battlefield:map.' + saved['map_id'], match_seed='MGR-T15-LUCK')['match_id']
    return combat, TabletopService(combat, tmp_path), mid


def settle_luck(send, use):
    """Answer the native binary Reaction, with optional talent choices intact."""
    answers, prompts = [], []
    for _ in range(20):
        result = send(answers)
        if result['status'] == 'COMMITTED':
            return prompts
        assert result['status'] == 'REACTION_REQUIRED', result
        prompt = result['reaction']
        prompts.append(prompt)
        options = (prompt.get('choice') or {}).get('options') or []
        answers.append({**prompt['context'], 'selection': 'USE' if use else 'DECLINE',
                        'option_ids': [options[0]['id']] if use and options else []})
    raise AssertionError('too many native reactions')


@pytest.mark.parametrize('case,first,used', [
    ('accept', 20, True), ('failed', 1, True), ('decline', 20, False),
    ('auto_success', 20, False), ('auto_failure', 1, True), ('own_turn', 20, True),
    ('ai_turn', 20, True),
    ('base_only', 20, False), ('no_aegis', 20, False), ('transient', 20, False),
    ('other_owner', 20, False), ('range_edge', 20, True), ('range_outside', 20, False),
    ('no_benefit', 1, True),
])
def test_native_luck_every_save(monkeypatch, tmp_path, case, first, used):
    combat, table, mid = native_table(tmp_path, case)
    bearer = OWNER if case == 'own_turn' else ALLY
    if case != 'no_aegis':
        creator = ALLY if case == 'other_owner' else OWNER
        turn(table, mid, creator)
        commit(cast_sender(combat, table, mid,
            'Aegis: Armored Aegis' + ('' if case == 'transient' else ' (Persistent)'), target=bearer))
    if case == 'own_turn':
        turn(table, mid, FOE)
        commit(cast_sender(combat, table, mid, 'Aegis: Impedance (Persistent)', target=FOE))
    combat, table, engine = cold(tmp_path, mid)
    if case != 'base_only':
        assert any(row.get('kind') == 'protection_luck'
                   for row in engine.typed_passive_rows.get(OWNER, [])), 'native import must retain the Luck provider'
    if case.startswith('range_'):
        turn(table, mid, OWNER)
        state = table.state(mid)
        x = 63 if case == 'range_edge' else 64
        c = next(c for c in combat._load_session(mid).engine.legal_candidates()
                 if c.destination and (c.destination.x, c.destination.y) == (x, 5))
        commit(lambda answers=(): table.act(mid, c.candidate_id, c.decision_id,
               c.state_version, state['last_sequence'], list(answers)))
        combat, table, engine = cold(tmp_path, mid)
        assert engine.grid.distance_ft(engine.state.actors[OWNER].position,
                                       engine.state.actors[ALLY].position) == (300 if x == 63 else 305)
    turn(table, mid, OWNER if case == 'own_turn' else FOE)
    if case.startswith('auto_'):
        combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    # Only dice are scripted: Scouring Hand is acquired and submitted natively.
    # Success -> failure proves the mandatory new result; failure -> failure
    # proves an ineffective rescue still spends the ward irrevocably.
    second = 1 if first == 20 or case == 'no_benefit' else 20
    fixed_dice(monkeypatch, [first, second] + [1] * 40)
    def sender(combat, table):
        if case == 'own_turn':
            state = table.state(mid)
            c = next(c for c in combat._load_session(mid).engine.legal_candidates()
                     if c.destination and (c.destination.x, c.destination.y) == (3, 4))
            return lambda answers=(): table.act(mid, c.candidate_id, c.decision_id,
                c.state_version, state['last_sequence'], list(answers))
        if case != 'ai_turn':
            return cast_sender(combat, table, mid, 'Scouring Hand', target=ALLY)
        from combat.gate4_adapters import ManualControllerAdapter

        original = combat.controller

        class ScriptedController:
            def choose_primary_action(self, context):
                chosen = next(c for c in context.legal_candidates
                              if 'Scouring Hand' in c.display_name and ALLY in c.target_ids)
                return ManualControllerAdapter(lambda _: (chosen.candidate_id, ())).choose_primary_action(context)

            def __getattr__(self, name):
                return getattr(original, name)

        combat.controller = ScriptedController()
        combat.set_controller_mode(mid, actor_id=FOE, controller_mode='LOCAL_AUTO')
        return lambda answers=(): table.auto_step(mid, table.state(mid)['last_sequence'], list(answers))

    send = sender(combat, table)
    before = combat._load_session(mid).engine.state.model_dump(mode='json')
    eligible = case in ('accept', 'failed', 'decline', 'own_turn', 'ai_turn', 'range_edge', 'no_benefit')
    if eligible:
        paused = send()
        assert paused['status'] == 'REACTION_REQUIRED'
        names = ('Luck', 'Impedance', 'Owner') if case == 'own_turn' else ('Luck', 'Scouring Hand', 'Ally')
        assert all(word in str(paused['reaction']) for word in names)
        assert combat._load_session(mid).engine.state.model_dump(mode='json') == before
        combat, table, _ = cold(tmp_path, mid)
        send = sender(combat, table)
    prompts = settle_luck(send, case != 'decline')
    _, _, engine = cold(tmp_path, mid)
    rewrites = [e for e in engine.events if e.event_type == 'D20_REWRITTEN'
                and e.source_definition_id == LUCK]
    assert len(rewrites) == int(used)
    assert engine.state.actors[OWNER].reaction_available is not used
    creator = ALLY if case == 'other_owner' else OWNER
    if case != 'no_aegis':
        assert bool(aegises(engine.state.actors[bearer], creator)) is not used
    saves = [e for e in engine.events if e.event_type == 'SAVE_ROLLED' and e.actor_id == bearer]
    assert saves
    if used:
        rewrite = rewrites[0]
        assert rewrite.payload['original']['natural_result'] == first
        assert rewrite.payload['result']['natural_result'] == second
        removals = [e for e in engine.events if e.event_type == 'CONDITION_REMOVED'
                    and bearer in e.target_ids and e.payload.get('reason') == 'SACRIFICED']
        assert len(removals) == 1
        assert removals[0].sequence < rewrite.sequence < saves[-1].sequence
        assert saves[-1].payload['success'] is (second == 20)
    else:
        assert saves[-1].payload['success'] is (first == 20)
    if not eligible:
        assert not prompts
