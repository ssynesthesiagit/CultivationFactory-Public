"""Native acquired Shield table fixture, independent of journey activities.

Used by the Active Defense window tests and their production-authority variant.
Only public synthetic characters are written; advancement, compilation, commit,
reload and replay use the ordinary services.
"""
import json
import zipfile

from canonical_catalog.service import CanonicalCatalogAuthorityService
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet

PIDS = ['0badc0de-0000-4000-8000-000000000071', '0badc0de-0000-4000-8000-000000000072']
A, B = [FACTORY_ACTOR_PREFIX + pid for pid in PIDS]


def acquired_combat(tmp_path, monkeypatch, *, synthetic=True):
    if synthetic:
        from tests.active_defense_authority_support import install
        install(tmp_path, monkeypatch)
    shield = {'item_id': 'tianxia.mortal.armor.shield', 'name': 'Shield', 'quantity': 1}
    dagger = {'item_id': 'tianxia.mortal.weapon.bi_shou', 'name': 'Bi Shou (Dagger)', 'quantity': 1}
    for i, pid in enumerate(PIDS):
        doc = sheet([], name='Shield Bearer' if i == 0 else 'Attacker')
        doc['identity']['path_ids'] = ['tianxia.path.qi_cultivation', 'tianxia.path.spirit_awakening', 'tianxia.path.body_refining']
        doc['path_and_subpath'] = {'path_record_ids': doc['identity']['path_ids']}
        doc['equipment'] = [{'starting_kit': {'items': [shield, dagger] if i == 0 else [dagger]}}]
        folder = tmp_path / 'portable_characters' / pid
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(doc))
    service = CombatService(ROOT, tmp_path)
    table = TabletopService(service, tmp_path)
    table.canonical_catalog = CanonicalCatalogAuthorityService(ROOT)
    table.add_advancement(PIDS[0], 'sphere', 'tianxia.sphere.shield')
    table.save_reactions(PIDS[0], {'mode': 'ask'})
    acquired = service._factory_owner_sheet(PIDS[0])
    assert 'SHIELD_BASE_ACTIVE_DEFENSE' in acquired['spheres_and_talents']['automatic_sphere_component_record_ids']
    bundles = [compile_character(service._factory_owner_sheet(pid), actor_id=aid,
                                 reaction_plan={'ask': True}) for pid, aid in zip(PIDS, (A, B))]
    arena = {'stable_id': 'battlefield:shield-window-test', 'display_name': 'Shield proving ground',
             'width_squares': 10, 'height_squares': 10, 'square_size_ft': 5,
             'starting_positions': {}, 'terrain_regions': []}
    mid = service._finish_factory_match(bundles, [A, B], {A: 'team:a', B: 'team:b'},
        {A: {'x': 2, 'y': 2}, B: {'x': 2, 'y': 3}}, arena, ['shield_window'], [],
        control_modes={A: 'MANUAL', B: 'MANUAL'}, match_seed='SHIELD-WINDOW',
        display_name='Shield window regression', maximum_rounds=2)['match_id']
    return table, mid


def advance(table, mid, actor):
    for _ in range(8):
        state = table.state(mid)
        if state['menu']['actor_id'] == actor:
            return
        result = table.act(mid, state['menu']['end_turn'], state['menu']['decision_id'],
                           state['menu']['state_version'], state['last_sequence'])
        assert result['status'] == 'COMMITTED', result
    raise AssertionError('turn did not arrive')


def force_ai_attack(table, mid):
    from combat.gate4_adapters import ManualControllerAdapter
    engine = table.combat._load_session(mid).engine
    attack = next(c for c in engine.legal_candidates() if c.target_ids == (A,)
                  and engine.action_catalog.get(c.source_definition_id)
                  and engine.action_catalog[c.source_definition_id].display_name == 'Bi Shou (Dagger) attack')
    real = table.combat.controller
    class FixedController:
        def choose_primary_action(self, context):
            return ManualControllerAdapter(lambda _context: (attack.candidate_id, ())).choose_primary_action(context)
        def __getattr__(self, name):
            return getattr(real, name)
    table.combat.controller = FixedController()
    table.combat.set_controller_mode(mid, actor_id=B, controller_mode='LOCAL_AUTO')


def finish(table, mid, choose, *, auto=False):
    answers, prompts = [], []
    for _ in range(20):
        before = table.combat._load_session(mid).engine.state.model_dump(mode='json')
        if auto:
            result = table.auto_step(mid, 0, answers)
        else:
            state = table.state(mid)
            group = next(g for g in state['menu']['actions'] if g['label'] == 'Bi Shou (Dagger) attack')
            engine = table.combat._load_session(mid).engine
            cid = next(o['candidate_id'] for o in group['options'] if next(
                c for c in engine.legal_candidates() if c.candidate_id == o['candidate_id']).target_ids == (A,))
            result = table.act(mid, cid, state['menu']['decision_id'], state['menu']['state_version'],
                               state['last_sequence'], answers)
        if result['status'] == 'COMMITTED':
            return prompts
        assert result['status'] == 'REACTION_REQUIRED', result
        assert table.combat._load_session(mid).engine.state.model_dump(mode='json') == before
        prompt = result['reaction']
        prompts.append(prompt)
        options = choose(prompt)
        answers.append({**prompt['context'], 'selection': 'DECLINE' if options is None else 'USE',
                        'option_ids': options or []})
    raise AssertionError('action did not finish')
