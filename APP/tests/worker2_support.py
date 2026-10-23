"""Worker 2 service fixtures: genuine compiled characters, table commits and reloads."""
import json
import zipfile
from hashlib import sha256

from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.test_r9i_karma_persistence import act, end_turn

OWNER = "actor:factory.worker2-owner"
ALLY = "actor:factory.worker2-ally"
FOE = "actor:factory.worker2-foe"
# Distinct creature names for fixtures that ask which creature is which. Left off by
# default so no existing lane's prompts change; turn it on for any test that compares
# the creatures a prompt names.
NAMED = ("Wren", "Tobin", "Mara")


def fixture(tmp_path, talents, *, ally_talents=(), cl=15, seed="WORKER2", ask=True, owner_speed=30,
            foe_kit=None, foe_position=None, owner_ac=14, owner_kit=None, ally_kit=None,
            owner_dc=16, bundle_transform=None, primary="Qi", modes=None,
            foe_sheet=None, positions=None, dc=None, extra_allies=0, owner_path=None, ally_position=None,
            ally_skills=None, owner_permission=None, owner_features=(), owner_plan=None, owner_bundle=None,
            owner_pb=None, named=False, owner_insights=(), extra_foes=0, battlefield_transform=None,
            battlefield=None, ally_score=14, team_overrides=None):
    names = NAMED if named else (None, None, None)
    documents = [sheet(talents, cl=cl, kit=owner_kit, dc=dc if dc is not None else owner_dc, primary=primary, name=names[0]),
                 sheet(ally_talents, cl=cl, kit=ally_kit, name=names[1]),
                 foe_sheet if foe_sheet is not None else sheet([], cl=cl, kit=foe_kit, name=names[2])]
    documents[0]['ability_scores_and_statistics']['speed']['walking_ft'] = owner_speed
    if ally_score != 14:
        for ability in documents[1]['ability_scores_and_statistics']['abilities']:
            ability['score'] = ally_score
            ability['modifier'] = (ally_score - 10) // 2
    if owner_pb is not None:
        documents[0]['identity']['proficiency_bonus'] = owner_pb
    documents[0]['ability_scores_and_statistics']['armor_class']['base_value'] = owner_ac
    if owner_path:
        documents[0]['identity']['path'] = owner_path
    if owner_permission is not None:
        documents[0].setdefault('path_and_subpath', {})['life_seal_reach_permission'] = owner_permission
    if owner_insights:
        fields = documents[0].setdefault('spheres_and_talents', {})
        fields['cultivation_insight_record_ids'] = list(owner_insights)
        fields['learned_talent_record_ids'] = [mid for mid in fields.get('learned_talent_record_ids', []) if mid not in owner_insights]
    if owner_features:
        documents[0].setdefault('path_and_subpath', {})['path_feature_record_ids'] = list(owner_features)
    if ally_skills:
        documents[1]['ability_scores_and_statistics']['skills'] = [dict(row) for row in ally_skills]
    ids = [OWNER, ALLY, FOE]
    opponent_ids = {FOE}
    for _ in range(extra_foes):
        documents.append(sheet([], cl=cl, kit=foe_kit))
        aid = f"actor:factory.worker2-foe{len(opponent_ids)}"
        ids.append(aid)
        opponent_ids.add(aid)
    for index in range(extra_allies):
        documents.append(sheet([], cl=cl, name=f"Reinforcement {index + 1}" if named else None))
        ids.append(f"actor:factory.worker2-ally{len(ids)}")
    for aid, document in zip(ids, documents):
        document['ability_scores_and_statistics']['primary_resource']['maximum'] = 100
        folder = tmp_path / 'portable_characters' / aid.removeprefix('actor:factory.')
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as z:
            z.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(document))
    bundles = [compile_character(doc, actor_id=aid, reaction_plan={'ask': ask},
               **({'summon_plan': owner_plan} if aid == OWNER and owner_plan else {}))
               for aid, doc in zip(ids, documents)]
    if owner_bundle is not None:
        bundles[0] = owner_bundle
    if bundle_transform:
        bundle_transform(bundles)
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    places = positions or {OWNER: {'x': 3, 'y': 6}, ALLY: ally_position or {'x': 4, 'y': 6}, FOE: foe_position or {'x': 6, 'y': 6}}
    for index, aid in enumerate(ids[3:]):
        places.setdefault(aid, {'x': 4 + (index % 3), 'y': 7 - (index // 3)})
    arena = battlefield if battlefield is not None else combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena']
    if battlefield_transform:
        import copy
        arena = copy.deepcopy(arena)
        battlefield_transform(arena)
    teams = {aid: ('team:opponents' if aid in opponent_ids else 'team:factory') for aid in ids}
    teams.update(team_overrides or {})
    mid = combat._finish_factory_match(
        bundles, ids, teams,
        places,
        arena, [aid for aid in ids if aid not in opponent_ids], sorted(opponent_ids),
        control_modes=modes or {aid: 'MANUAL' for aid in ids}, match_seed=seed, display_name=seed,
        maximum_rounds=15)['match_id']
    turn(table, mid, OWNER)
    return combat, table, mid


def turn(table, mid, actor):
    """Advance initiative, including choices raised by intervening turns."""
    return prompt_turn(table, mid, actor)


def settle(table, mid, cid, picks=None, decline_after=None, *, choices=None, auto=False):
    """Drive one candidate to its commit, answering every prompt it raises.

    ``auto`` uses the real table AI step instead of submitting a manual intent.
    ``picks`` maps a prompt's reaction_source_id to the option id(s) to take ('first', a list, or an id); a prompt
    with no entry and no options is declined. Shared by the worker-2 sphere tests (AUTO107 moved these here from
    test_auto35_yang.py, whose Yang-only imports do not exist on main)."""
    selected = choices if choices is not None else picks or {}
    answers, prompts, seen = [], [], {}
    for _ in range(20):
        result = table.auto_step(mid, 0, answers) if auto else act(table, mid, cid, answers)
        if result['status'] != 'REACTION_REQUIRED':
            assert result['status'] == 'COMMITTED', result
            return prompts
        p = result['reaction']; prompts.append(p)
        rid = p['context']['reaction_source_id']
        default = ((p.get('choice') or {}).get('preferred') or [None])[0] if choices is not None else ('first' if rid.startswith('choice:') else None)
        choice = selected.get(rid, default)
        used = seen.get(rid, 0)
        seen[rid] = used + 1
        if isinstance(choice, tuple):
            choice = choice[min(used, len(choice) - 1)]
        if decline_after is not None and used >= decline_after:
            choice = None
        answer = {**p['context'], 'selection': 'USE' if choice is not None else 'DECLINE'}
        if choice is not None and p.get('choice'):
            answer['option_ids'] = ([p['choice']['options'][0]['id']] if choice == 'first'
                                    else choice if isinstance(choice, list) else [choice])
        answers.append(answer)
    raise AssertionError('Too many prompts')


def reload(tmp_path, mid):
    """Cold-reload the saved fight and assert its replay still passes."""
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.mechanical.replay()['status'] == 'PASS'
    return loaded.engine


def prompt_turn(table, mid, actor):
    """Advance initiative and answer choices raised between turns."""
    for _ in range(12):
        menu = table.state(mid)['menu']
        setup = next((group for group in menu['actions'] if group['source_definition_id'] == 'system:combat.fight_setup'), None)
        if setup is not None:
            settle(table, mid, setup['options'][0]['candidate_id'], auto=menu['control_mode'] == 'LOCAL_AUTO')
            continue
        if menu['actor_id'] == actor:
            return
        settle(table, mid, menu['end_turn'])
    raise AssertionError('No turn')


settle_turn = prompt_turn


def candidate(combat, mid, name, *, target=None, at=None, remote=None):
    engine = combat._load_session(mid).engine
    rows = [c for c in engine.legal_candidates()
            if getattr(engine.action_catalog.get(c.source_definition_id), 'display_name', None) == name
            and (target is None or c.target_ids == (target,))
            and (at is None or c.destination and (c.destination.x, c.destination.y) == at)
            and (remote is None or bool(c.metadata.get('effect_origin')) == remote)]
    if not rows:
        from combat.action_legality import query
        sources = [a.source_definition_id for a in engine.action_catalog.values() if a.display_name == name]
        details = {source: query(engine, engine.state.current_actor_id, source) for source in sources}
        raise AssertionError((name, details, engine.state.current_actor_id))
    return rows[0]


def sealed_native_attack(bundle, name, *, damage_type='FIRE', count=1, sides=6, modifier=6,
                         attack_bonus=20, range_ft=60, attacks=1):
    """Seal one native (non-typed) attack on a character: the engine's own attack code, so its damage
    reaches hooks a typed damage packet never does. ``attacks`` > 1 strikes once per action."""
    from combat.canonical import canonical_sha256

    owner = sha256(bundle['actor_id'].encode()).hexdigest()[:10]
    source = 'action:test.native.' + owner + '.' + name.lower().replace(' ', '_')
    row = {'source_definition_id': source, 'display_name': name, 'owner_id': bundle['actor_id'],
           'economy': 'ACTION', 'resolution_kind': 'ATTACK' if attacks == 1 else 'MULTI_ATTACK',
           'target_kind': 'HOSTILE_ENTITY', 'range_ft': range_ft, 'attack_bonus': attack_bonus,
           'damage': {'count': count, 'sides': sides, 'modifier': modifier},
           'damage_type': damage_type, 'parameters': {}, 'costs': []}
    if attacks > 1:
        row['attack_count'] = attacks
    bundle['action_catalog'].append(row)
    bundle['actor_template']['action_ids'].append(source)
    bundle.pop('bundle_sha256', None)
    bundle['bundle_sha256'] = canonical_sha256(bundle)
    return source
