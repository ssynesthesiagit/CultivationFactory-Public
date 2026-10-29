"""Small persisted table fixtures for hunt 28; no owner data or browsers."""
import json
import zipfile

from combat.gate3_reducer import canonical_state_document
from combat.factory_compiler import compile_character
from combat.gate4_adapters import ManualControllerAdapter
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet

OWNER, ALLY, FOE = [FACTORY_ACTOR_PREFIX + 'h28-' + name for name in ('owner', 'ally', 'foe')]


def fixture(tmp_path, talents, *, cp=30, borrowed=False, foe_kit=False, legacy_payment=False, ally_talents=(), legacy_targets=False, legacy_shadow=False, primary='Qi', setup_mark=None, legacy_unpaid=False):
    docs = [sheet(talents, dc=30, primary=primary), sheet(ally_talents, dc=30), sheet([])]
    docs[0]['ability_scores_and_statistics']['primary_resource']['maximum'] = cp
    if foe_kit:
        from tests.test_carry import KIT
        docs[2] = sheet([], kit={'starting_kit': KIT})
        docs[0]['ability_scores_and_statistics']['armor_class']['base_value'] = 1
    if borrowed:
        docs[0]['spheres_and_talents']['sphere_record_ids'] = []
        docs[0]['spheres_and_talents']['automatic_sphere_component_record_ids'] = []
    bundles = []
    for actor, doc in zip((OWNER, ALLY, FOE), docs):
        pid = actor.removeprefix(FACTORY_ACTOR_PREFIX)
        folder = tmp_path / 'portable_characters' / pid
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(doc))
        compiled = compile_character(doc, actor_id=actor, reaction_plan={'ask': True})
        if legacy_unpaid and actor == OWNER:
            for action in compiled['action_catalog']:
                if action.get('parameters', {}).get('typed'):
                    action['costs'] = []
        if setup_mark and actor == setup_mark[0]:
            # A test-only generic mark action supplies the prerequisite through a
            # real table commit, without depending on Glow's GM light modelling.
            aid = 'action:test.prerequisite_mark.' + actor
            compiled['actor_template']['action_ids'].append(aid)
            compiled['action_catalog'].append({
                'source_definition_id': aid, 'display_name': 'Prepare prerequisite mark', 'owner_id': actor,
                'economy': 'NONE', 'resolution_kind': 'TYPED', 'target_kind': 'ALLY_OR_SELF', 'range_ft': 30,
                'parameters': {'typed': {'effects': [{'type': 'mark', 'mark': setup_mark[1], 'applies_to': 'target',
                                                    'duration': {'kind': 'until_end_of_your_next_turn'}}],
                                         'numbers': {}, 'duration': {'kind': 'instant'}}}})
        if legacy_shadow:
            # Old bundles predate the supplemental non-ally consent variant.
            compiled['action_catalog'] = [a for a in compiled['action_catalog']
                if not (a['display_name'] == 'Second Silhouette: Willing Creature (willing creature)')]
            valid_ids = {a['source_definition_id'] for a in compiled['action_catalog']}
            compiled['actor_template']['action_ids'] = [a for a in compiled['actor_template']['action_ids'] if a in valid_ids]
            for action in compiled['action_catalog']:
                if action['display_name'] == 'Second Silhouette: Willing Creature':
                    typed = action['parameters']['typed']
                    typed['effects'] = typed['effects'][0]['effects']
                    typed['effects'][0]['applies_to'] = 'target'
                    action['target_kind'] = 'HOSTILE_ENTITY'
        if legacy_targets:
            for action in compiled['action_catalog']:
                parameters = action.get('parameters', {})
                if parameters.get('typed', {}).get('target_requires_mark'):
                    parameters.pop('target_requires_condition', None)
                    parameters['typed'].pop('target_requires_mark', None)
        if legacy_payment and actor == OWNER:
            # The original serialized option shape: payment was an effect after the benefit.
            for action in compiled['action_catalog']:
                typed = action.get('parameters', {}).get('typed', {})
                if typed.get('option_of') and action.get('costs'):
                    for pool, amount in action['costs']:
                        typed['effects'].append({'type': 'spend_resource', 'applies_to': 'self',
                                                 'resource_id': pool, 'flat': amount, 'formula': 'none'})
                    action['costs'] = []
        bundles.append(compiled)
    combat = CombatService(ROOT, tmp_path)
    mid = combat._finish_factory_match(
        bundles, [OWNER, ALLY, FOE], {OWNER: 'team:factory', ALLY: 'team:factory', FOE: 'team:opponents'},
        {OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 3, 'y': 7}, FOE: {'x': 4, 'y': 6}},
        combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'], [OWNER, ALLY], [FOE],
        control_modes={a: 'MANUAL' for a in (OWNER, ALLY, FOE)}, match_seed='hunt28',
        display_name='Hunt 28 regression', maximum_rounds=10)['match_id']
    table = TabletopService(combat, tmp_path)
    owner_turn(table, mid)
    return combat, table, mid


def act(table, mid, cid, answers=()):
    state = table.state(mid)
    menu = state['menu']
    return table.act(mid, cid, menu['decision_id'], menu['state_version'], state['last_sequence'], list(answers))


def owner_turn(table, mid, *, next_turn=False):
    if next_turn:
        assert act(table, mid, table.state(mid)['menu']['end_turn'])['status'] == 'COMMITTED'
    for _ in range(10):
        if table.state(mid)['menu']['actor_id'] == OWNER:
            return
        assert act(table, mid, table.state(mid)['menu']['end_turn'])['status'] == 'COMMITTED'
    raise AssertionError('owner turn not reached')


def options(table, mid, label):
    return [o for g in table.state(mid)['menu']['actions'] if g['label'] == label for o in g['options']]


def send(combat, table, mid, cid, auto, answers=(), *, actor=OWNER):
    if not auto:
        return act(table, mid, cid, answers)
    original = combat.controller

    class SelectedController:
        def choose_primary_action(self, context):
            return ManualControllerAdapter(lambda _: (cid, ())).choose_primary_action(context)

        def __getattr__(self, name):
            return getattr(original, name)

    combat.controller = SelectedController()
    combat.set_controller_mode(mid, actor_id=actor, controller_mode='LOCAL_AUTO')
    try:
        return table.auto_step(mid, 0, list(answers))
    finally:
        combat.controller = original
        combat.set_controller_mode(mid, actor_id=actor, controller_mode='MANUAL')


def reload(combat, mid):
    fresh = CombatService(ROOT, combat.userdata_root)._load_session(mid)
    assert fresh.mechanical.replay()['state'] == canonical_state_document(fresh.engine.state)
    return fresh.engine
