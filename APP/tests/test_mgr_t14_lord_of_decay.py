"""Lord of Decay through real compilation, table commits and cold replay.

Every regression here covers a printed clause the F18R review found left as a
rider: Poison immunity, Advantage against disease, Supreme Venom, the Decaying
Presence riders (extra damage, Toxic Cloud Concentration/origin, healing denial)
and Feast of Decay. The typed record is
authority/typed_mechanics/reviewed_final.d/mgr_t14_poison_touch.json.

Damage probes use a fixture-typed Poison action, so the shipped Poison/ Acid
choice in Deliver the Dose cannot quietly pick the other type; the defense,
rider and resource paths are the real engine ones.
"""
import json
import zipfile
from copy import deepcopy

import pytest

from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.ext import mgr_t14_lord_of_decay as lod
from tests.h1_support import ROOT, sheet
from tests.r10_fixup_support import cast_sender, commit

LEFT = 'actor:factory.lod-left'
RIGHT = 'actor:factory.lod-right'
ALLY = 'actor:factory.lod-ally'
RIGHT2 = 'actor:factory.lod-right-2'
DOSE = 'POISON_BASE_DELIVER_THE_DOSE'
RESIST = 'tianxia.talent.poison.venom_body_method'
VENOMOUS = 'tianxia.subpath.qi.poison_cultivator.feature.venomous_qi'
ESSENCE = 'tianxia.subpath.qi.poison_cultivator.feature.essence_rot'
POISON_TOUCH = 'tianxia.subpath.qi.poison_cultivator.feature.poison_touch'
IMMUNE = 'tianxia.subpath.body.hundred_venom_body.feature.myriad_venom_immortal'
DISEASE = 'tianxia.talent.disease.parasite_seed'


@pytest.fixture(autouse=True)
def fake_menu_embeddings(monkeypatch):
    from combat import embedding_rank, menu_rank

    def transport(url, body, timeout):
        count = len(json.loads(body)['input'])
        return json.dumps({'data': [{'index': i, 'embedding': [1] + [0] * (embedding_rank.DIMENSION - 1)}
                                    for i in range(count)]}).encode()

    monkeypatch.setattr(menu_rank, '_CLIENT', embedding_rank.EmbeddingClient(transport=transport))


def fixed_dice(monkeypatch, values):
    from combat.gate4_engine import Gate4ControllerEngine
    from tests.h1_support import script
    current = Gate4ControllerEngine.execute_intent
    original = getattr(current, '_lod_original', current)

    def execute(engine, intent, *args, **kwargs):
        script(engine, values if intent.target_ids else values[1:])
        return original(engine, intent, *args, **kwargs)

    execute._lod_original = original
    monkeypatch.setattr(Gate4ControllerEngine, 'execute_intent', execute)


def actor_sheet(actor, *, mids=(), cl=18, owner=False, features=(), hp=200, qi=100, name=None, initiative=None):
    doc = sheet([DOSE, *mids], cl=cl, dc=50, score=14, primary='Qi')
    doc['identity'].update(display_name=name or ('Lord of Decay' if actor == LEFT else 'Test Target'),
                           proficiency_bonus=4)
    doc['ability_scores_and_statistics']['hit_points']['maximum'] = hp
    doc['ability_scores_and_statistics']['primary_resource']['maximum'] = qi
    doc['ability_scores_and_statistics']['initiative'] = {
        'bonus': initiative if initiative is not None else (100 if actor == LEFT else -100)}
    doc['ability_scores_and_statistics']['technique_attack_bonus'] = 100
    held = list(features) + ([lod.FEATURE] if owner else [])
    if held:
        doc.setdefault('path_and_subpath', {}).setdefault('path_feature_record_ids', []).extend(held)
    return doc


def added_action(bundle, actor, action_id, name, effects):
    bundle['actor_template']['action_ids'].append(action_id)
    bundle['action_catalog'].append({
        'source_definition_id': action_id, 'display_name': name, 'owner_id': actor, 'economy': 'NONE',
        'resolution_kind': 'TYPED', 'target_kind': 'ANY_CREATURE',
        'parameters': {'free_primary': True, 'typed': {
            'numbers': {'cl': 18, 'save_dc': 50}, 'duration': {'kind': 'instant'},
            'effects': deepcopy(effects), 'riders': []}}})


POISON_JAB = [{'type': 'damage', 'applies_to': 'target', 'flat': 8, 'damage_types': ['poison'],
               'evidence': 'a fixed Poison probe'}]
# Leaves room under the Qi maximum so a regained point is visible on the table.
DRAIN = [('Spend Qi', [{'type': 'spend_resource', 'applies_to': 'self', 'flat': 10,
                        'resource_id': 'resource:core.qi'}])]


def fight(tmp_path, *, owner=True, left_mids=(), right_mids=(), hp=200, right_hp=200,
          left_setup=(), right_setup=(), seed='LOD-native', left_features=(), right_cl=18,
          left_name=None, right_name=None, left_qi=100):
    from combat.canonical import canonical_sha256
    bundles = []
    people = [(LEFT, actor_sheet(LEFT, mids=left_mids, owner=owner, hp=hp, features=left_features,
                                 name=left_name, qi=left_qi)),
              (RIGHT, actor_sheet(RIGHT, mids=right_mids, hp=right_hp, cl=right_cl, name=right_name))]
    for actor, doc in people:
        folder = tmp_path / 'portable_characters' / actor.removeprefix('actor:factory.')
        folder.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(doc))
        bundle = compile_character(doc, actor_id=actor, reaction_plan={'ask': True})
        added_action(bundle, actor, f'action:test.lod.{actor.removeprefix("actor:factory.")}.poison_jab', 'Poison jab', POISON_JAB)
        for name, effects in (left_setup if actor == LEFT else right_setup):
            added_action(bundle, actor, f'action:test.lod.{actor.removeprefix("actor:factory.")}.{name.lower().replace(" ", "_")}', name, effects)
        bundle.pop('bundle_sha256', None)
        bundle['bundle_sha256'] = canonical_sha256(bundle)
        bundles.append(bundle)
    combat = CombatService(ROOT, tmp_path)
    arena = combat.tabletop_maps.save({'display_name': 'Lord of Decay yard', 'width_squares': 14, 'height_squares': 10,
        'walls': [], 'starts': {'team1': [[3, 5]], 'team2': [[8, 5]]}})
    mid = combat._finish_factory_match(bundles, [LEFT, RIGHT], {LEFT: 'team:a', RIGHT: 'team:b'},
        {LEFT: {'x': 3, 'y': 5}, RIGHT: {'x': 8, 'y': 5}},
        combat.factory_arenas()['battlefield:map.' + arena['map_id']],
        [LEFT], [RIGHT], control_modes={LEFT: 'MANUAL', RIGHT: 'MANUAL'}, match_seed=seed,
        maximum_rounds=30, display_name='Lord of Decay regression')['match_id']
    table = TabletopService(combat, tmp_path)
    turn(table, mid, LEFT)
    return combat, table, mid


def battle(tmp_path, people, *, seed='LOD-field'):
    """A real match with any number of fighters: (actor_id, team, (x, y), sheet, own setup actions)."""
    from combat.canonical import canonical_sha256
    bundles, actors, teams, starts = [], [], {}, {}
    for actor, team, (x, y), doc, setup in people:
        slug = actor.removeprefix('actor:factory.')
        folder = tmp_path / 'portable_characters' / slug
        folder.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(doc))
        bundle = compile_character(doc, actor_id=actor, reaction_plan={'ask': True})
        added_action(bundle, actor, f'action:test.lod.{slug}.poison_jab', 'Poison jab', POISON_JAB)
        for name, effects in setup:
            added_action(bundle, actor, f'action:test.lod.{slug}.{name.lower().replace(" ", "_")}', name, effects)
        bundle.pop('bundle_sha256', None)
        bundle['bundle_sha256'] = canonical_sha256(bundle)
        bundles.append(bundle)
        actors.append(actor)
        teams[actor] = team
        starts[actor] = {'x': x, 'y': y}
    combat = CombatService(ROOT, tmp_path)
    arena = combat.tabletop_maps.save({'display_name': 'Lord of Decay field', 'width_squares': 14, 'height_squares': 10,
        'walls': [], 'starts': {'team1': [[2, 5]], 'team2': [[8, 5]]}})
    mid = combat._finish_factory_match(bundles, actors, teams, starts,
        combat.factory_arenas()['battlefield:map.' + arena['map_id']],
        [a for a, t, _, _, _ in people if t == 'team:a'], [a for a, t, _, _, _ in people if t == 'team:b'],
        control_modes={a: 'MANUAL' for a in actors}, match_seed=seed,
        maximum_rounds=30, display_name='Lord of Decay standing regression')['match_id']
    table = TabletopService(combat, tmp_path)
    turn(table, mid, actors[0])
    return combat, table, mid


def cold(tmp_path, mid):
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    assert session.verify()['status'] == 'PASS'
    assert session.mechanical.replay()['status'] == 'PASS'
    return session.engine


def end(table, mid):
    from tests.test_lock2_persistence import act
    result = act(table, mid, 'end')
    assert result['status'] == 'COMMITTED', result


def turn(table, mid, actor):
    for _ in range(7):
        if table.state(mid)['menu']['actor_id'] == actor:
            return
        end(table, mid)
    raise AssertionError('turn did not advance')


def choose(prompt, use=True):
    options = (prompt.get('choice') or {}).get('options') or []
    ids = [option['id'] for option in options]
    poison = next((value for value in ids if str(value).lower() == 'poison'), None)
    return (poison or (ids[0] if ids else None), use)


def accept(prompt, use=True):
    """Answer a prompt by its own plain option: qualify, apply, or the printed damage type."""
    ids = [option['id'] for option in (prompt.get('choice') or {}).get('options') or []]
    for wanted in ('qualifies', 'apply', 'poison'):
        if wanted in ids:
            return wanted, use
    return (ids[0] if ids else None), use


def commit_accept(combat, table, mid, name, *, target=None, at=None):
    return commit(cast_sender(combat, table, mid, name, target=target, at=at), accept)


def cast(combat, table, mid, name, *, target=None, at=None):
    return commit(cast_sender(combat, table, mid, name, target=target, at=at), choose)


def jab(combat, table, mid, target):
    return cast(combat, table, mid, 'Poison jab', target=target)


def events(engine, kind):
    return [event for event in engine.events if event.event_type == kind]


def activate_presence(combat, table, mid):
    cast(combat, table, mid, 'Decaying Presence')


def test_standing_poison_immunity_through_real_attack(tmp_path, monkeypatch):
    fixed_dice(monkeypatch, [19] + [1] * 80)
    combat, table, mid = fight(tmp_path)
    turn(table, mid, RIGHT)
    jab(combat, table, mid, LEFT)
    assert cold(tmp_path, mid).state.actors[LEFT].current_hp == 200
    control, ctable, cmid = fight(tmp_path / 'control', owner=False)
    turn(ctable, cmid, RIGHT)
    jab(control, ctable, cmid, LEFT)
    assert cold(tmp_path / 'control', cmid).state.actors[LEFT].current_hp == 192


def test_standing_immunity_to_poisoned_condition(tmp_path, monkeypatch):
    fixed_dice(monkeypatch, [19] + [1] * 80)
    setup = [('Poison setup', [{'type': 'condition', 'condition': 'poisoned', 'applies_to': 'target',
                                'duration': 'one_minute'}])]
    combat, table, mid = fight(tmp_path, right_setup=setup)
    turn(table, mid, RIGHT)
    cast(combat, table, mid, 'Poison setup', target=LEFT)
    assert not any(condition.condition_id == lod.POISONED
                   for condition in cold(tmp_path, mid).state.actors[LEFT].conditions.values())
    control, ctable, cmid = fight(tmp_path / 'control', owner=False, right_setup=setup)
    turn(ctable, cmid, RIGHT)
    cast(control, ctable, cmid, 'Poison setup', target=LEFT)
    assert any(condition.condition_id == lod.POISONED
               for condition in cold(tmp_path / 'control', cmid).state.actors[LEFT].conditions.values())


def test_supreme_venom_ignores_resistance_and_halves_immunity(tmp_path, monkeypatch):
    fixed_dice(monkeypatch, [19] + [1] * 80)
    combat, table, mid = fight(tmp_path, right_mids=[RESIST])
    jab(combat, table, mid, RIGHT)
    assert cold(tmp_path, mid).state.actors[RIGHT].current_hp == 192
    control, ctable, cmid = fight(tmp_path / 'control', owner=False, right_mids=[RESIST])
    jab(control, ctable, cmid, RIGHT)
    assert cold(tmp_path / 'control', cmid).state.actors[RIGHT].current_hp == 196
    # Myriad-Venom precedent (combat/ext/__init__.py immunity_as_resistance):
    # an ordinary Immunity is treated as Resistance, then the same feature's
    # ordinary-Resistance bypass ignores it, so the packet lands in full.
    immune, itable, imid = fight(tmp_path / 'immune', right_mids=[IMMUNE])
    jab(immune, itable, imid, RIGHT)
    assert cold(tmp_path / 'immune', imid).state.actors[RIGHT].current_hp == 192
    blocked, btable, bmid = fight(tmp_path / 'blocked', owner=False, right_mids=[IMMUNE])
    jab(blocked, btable, bmid, RIGHT)
    assert cold(tmp_path / 'blocked', bmid).state.actors[RIGHT].current_hp == 200


def test_advantage_against_disease_save(tmp_path, monkeypatch):
    fixed_dice(monkeypatch, [3] + [1] * 80)
    combat, table, mid = fight(tmp_path, right_mids=[DISEASE])
    turn(table, mid, RIGHT)
    cast(combat, table, mid, 'Parasite Seed', target=LEFT)
    worked = [event for event in events(cold(tmp_path, mid), 'SAVE_ROLLED') if event.actor_id == LEFT]
    assert worked and worked[-1].payload.get('mode') == 'ADVANTAGE'
    control, ctable, cmid = fight(tmp_path / 'control', owner=False, right_mids=[DISEASE])
    turn(ctable, cmid, RIGHT)
    cast(control, ctable, cmid, 'Parasite Seed', target=LEFT)
    plain = [event for event in events(cold(tmp_path / 'control', cmid), 'SAVE_ROLLED') if event.actor_id == LEFT]
    assert plain and plain[-1].payload.get('mode') in (None, 'NORMAL')


def test_presence_bonus_damage_once_per_turn(tmp_path, monkeypatch):
    fixed_dice(monkeypatch, [19] + [1] * 80)
    setup = [('Poisoned setup', [{'type': 'condition', 'condition': 'poisoned', 'applies_to': 'target',
                                  'duration': 'one_minute'}])]
    combat, table, mid = fight(tmp_path, left_setup=setup, right_hp=500)
    activate_presence(combat, table, mid)
    cast(combat, table, mid, 'Poisoned setup', target=RIGHT)
    jab(combat, table, mid, RIGHT)
    jab(combat, table, mid, RIGHT)  # a second committed damaging action in the same turn

    def bonuses():
        return [event for event in events(cold(tmp_path, mid), 'PASSIVE_TRIGGERED')
                if event.payload.get('presence_bonus') == '2d8']

    assert len(bonuses()) == 1  # the reloaded fight holds the whole turn, second hit included
    assert cold(tmp_path, mid).state.actors[LEFT].turn_flags.get(lod.BONUS_USED)
    turn(table, mid, RIGHT)
    turn(table, mid, LEFT)  # a later turn of the same owner: the bonus is available again
    jab(combat, table, mid, RIGHT)
    assert len(bonuses()) == 2


def test_feast_of_decay_is_standing_and_pays_without_presence(tmp_path, monkeypatch):
    """The printed clause is standing: no Decaying Presence and any killer's blow counts."""
    fixed_dice(monkeypatch, [19] + [1] * 80)
    setup = [('Poison Touch setup', [{'type': 'condition', 'condition': 'poison_touch', 'applies_to': 'target',
                                      'duration': 'one_minute'}])]
    combat, table, mid = fight(tmp_path, left_setup=setup + DRAIN, right_hp=5)
    cast(combat, table, mid, 'Poison Touch setup', target=RIGHT)
    cast(combat, table, mid, 'Spend Qi')
    before = cold(tmp_path, mid).state.actors[LEFT].resources[lod.QI]
    jab(combat, table, mid, RIGHT)  # its own blow, no Presence
    engine = cold(tmp_path, mid)
    assert engine.state.actors[RIGHT].current_hp <= 0
    assert engine.state.actors[LEFT].resources[lod.QI] == before + 2
    assert any(event.payload.get('feast_of_decay') == 2 for event in events(engine, 'PASSIVE_TRIGGERED'))
    assert not lod._presence(engine, engine.state.actors[LEFT]).get(lod.FEATURE)


def test_feast_of_decay_counts_another_creatures_kill(tmp_path, monkeypatch):
    """An ally's blow pays the owner's Feast, once per round."""
    fixed_dice(monkeypatch, [19] + [1] * 80)
    touch = lambda name: [(name, [{'type': 'condition', 'condition': 'poison_touch', 'applies_to': 'target',
                                   'duration': 'one_minute'}])]
    people = [
        (LEFT, 'team:a', (2, 5), actor_sheet(LEFT, owner=True, initiative=100), touch('Touch one') + DRAIN),
        (ALLY, 'team:a', (2, 7), actor_sheet(ALLY, hp=200, initiative=50, name='Ally'), []),
        (RIGHT, 'team:b', (8, 5), actor_sheet(RIGHT, hp=8, name='Poisoned enemy'), []),
        (RIGHT2, 'team:b', (8, 7), actor_sheet(RIGHT2, hp=8, name='Second enemy'), []),
    ]
    combat, table, mid = battle(tmp_path, people)
    cast(combat, table, mid, 'Touch one', target=RIGHT)
    cast(combat, table, mid, 'Touch one', target=RIGHT2)
    cast(combat, table, mid, 'Spend Qi')
    before = cold(tmp_path, mid).state.actors[LEFT].resources[lod.QI]
    jab(combat, table, mid, RIGHT)  # the owner's own kill in this round
    turn(table, mid, ALLY)
    jab(combat, table, mid, RIGHT2)  # an ally's kill in the same round
    engine = cold(tmp_path, mid)
    assert engine.state.actors[RIGHT].current_hp <= 0 and engine.state.actors[RIGHT2].current_hp <= 0
    assert engine.state.actors[LEFT].resources[lod.QI] == before + 2  # once per round, whoever struck


def test_feast_of_decay_requires_the_printed_level_band(tmp_path, monkeypatch):
    fixed_dice(monkeypatch, [19] + [1] * 80)
    setup = [('Poison Touch setup', [{'type': 'condition', 'condition': 'poison_touch', 'applies_to': 'target',
                                      'duration': 'one_minute'}])]
    combat, table, mid = fight(tmp_path, left_setup=setup + DRAIN, right_hp=5, right_cl=12)  # 6 CL below an 18 CL owner
    cast(combat, table, mid, 'Poison Touch setup', target=RIGHT)
    cast(combat, table, mid, 'Spend Qi')
    before = cold(tmp_path, mid).state.actors[LEFT].resources[lod.QI]
    jab(combat, table, mid, RIGHT)
    engine = cold(tmp_path, mid)
    assert engine.state.actors[RIGHT].current_hp <= 0
    assert engine.state.actors[LEFT].resources[lod.QI] == before

    close, ctable, cmid = fight(tmp_path / 'close', left_setup=setup + DRAIN, right_hp=5, right_cl=14)
    cast(close, ctable, cmid, 'Poison Touch setup', target=RIGHT)
    cast(close, ctable, cmid, 'Spend Qi')
    before = cold(tmp_path / 'close', cmid).state.actors[LEFT].resources[lod.QI]
    jab(close, ctable, cmid, RIGHT)  # 4 CL below: inside the printed band
    assert cold(tmp_path / 'close', cmid).state.actors[LEFT].resources[lod.QI] == before + 2


def test_toxic_cloud_needs_no_concentration_during_presence(tmp_path, monkeypatch):
    fixed_dice(monkeypatch, [19] + [1] * 80)
    combat, table, mid = fight(tmp_path, left_mids=[lod.TOXIC_CLOUD])
    activate_presence(combat, table, mid)
    start = cold(tmp_path, mid)
    at = (start.state.actors[RIGHT].position.x, start.state.actors[RIGHT].position.y)
    cast(combat, table, mid, 'Toxic Cloud', at=at)
    engine = cold(tmp_path, mid)
    assert engine.state.actors[LEFT].concentration is None
    clouds = [zone for zone in engine.state.zones.values()
              if zone.source_definition_id in engine.action_catalog
              and (engine.action_catalog[zone.source_definition_id].parameters.get('typed') or {}).get('source')
              == lod.TOXIC_CLOUD]
    assert clouds and all(not zone.concentration_link for zone in clouds)

    control, ctable, cmid = fight(tmp_path / 'control', owner=False, left_mids=[lod.TOXIC_CLOUD])
    start = cold(tmp_path / 'control', cmid)
    at = (start.state.actors[RIGHT].position.x, start.state.actors[RIGHT].position.y)
    cast(control, ctable, cmid, 'Toxic Cloud', at=at)
    assert cold(tmp_path / 'control', cmid).state.actors[LEFT].concentration is not None


def test_toxic_cloud_healing_denial_after_failed_save(tmp_path, monkeypatch):
    fixed_dice(monkeypatch, [2] + [1] * 80)
    setup = [('Healing setup', [{'type': 'healing', 'applies_to': 'target', 'flat': 10}])]
    combat, table, mid = fight(tmp_path, left_mids=[lod.TOXIC_CLOUD], left_setup=setup, right_hp=500)
    activate_presence(combat, table, mid)
    start = cold(tmp_path, mid)
    at = (start.state.actors[RIGHT].position.x, start.state.actors[RIGHT].position.y)
    cast(combat, table, mid, 'Toxic Cloud', at=at)
    turn(table, mid, RIGHT)  # its own turn starts inside the cloud: the save is rolled now
    turn(table, mid, LEFT)
    engine = cold(tmp_path, mid)
    assert any(modifier.target_field == 'healing_reduction'
               for modifier in engine.state.actors[RIGHT].modifiers.values())
    before = engine.state.actors[RIGHT].current_hp
    cast(combat, table, mid, 'Healing setup', target=RIGHT)
    assert cold(tmp_path, mid).state.actors[RIGHT].current_hp == before


def test_domain_armament_is_an_offered_toxic_cloud_origin(tmp_path, monkeypatch):
    fixed_dice(monkeypatch, [19] + [1] * 80)
    combat, table, mid = fight(tmp_path, left_mids=[lod.TOXIC_CLOUD])
    activate_presence(combat, table, mid)
    engine = cold(tmp_path, mid)
    actor = engine.state.actors[LEFT]
    engine._apply_condition(actor, 'condition:typed.domain_armament', lod.FEATURE, LEFT,
                            expires_on='UNTIL_REMOVED', data={'ax': 10, 'ay': 2})
    action = next(a for a in engine.action_catalog.values()
                  if (a.parameters.get('typed') or {}).get('source') == lod.TOXIC_CLOUD)
    from combat import action_geometry
    found = [row for row in action_geometry.origins(engine, actor, action) if row['id'] == 'lord_of_decay:armament']
    assert found and found[0]['position'] == {'x': 10, 'y': 2}


# ------------------------------------------------------------------ Venom Conversion (Venomous Qi)
FIRE = 'FIRE_BASE_IGNITE'


def variant_action(engine, *, name='Ignite'):
    """The compiled '<technique> + Venomous Qi' variant the compiler offered this character."""
    return next((action for action in engine.action_catalog.values()
                 if ((action.parameters.get('typed') or {}).get('modifier') or {}).get('id') == VENOMOUS
                 and name in action.display_name), None)


def damage_packets(engine, actor=LEFT):
    return [event for event in events(engine, 'DAMAGE_COMMITTED')
            if event.actor_id == actor and int(event.payload.get('hp_damage') or 0) > 0]


def test_venom_conversion_changes_the_packet_and_costs_one_qi(tmp_path, monkeypatch):
    """Ignite deals Fire; the paid variant makes the same packet Poison."""
    fixed_dice(monkeypatch, [19] + [1] * 80)
    combat, table, mid = fight(tmp_path, left_mids=(FIRE,), left_features=(VENOMOUS,), right_hp=500)
    assert variant_action(cold(tmp_path, mid)) is not None
    before = cold(tmp_path, mid).state.actors[LEFT].resources[lod.QI]
    commit_accept(combat, table, mid, 'Ignite: Push Target + Venomous Qi', target=RIGHT)
    engine = cold(tmp_path, mid)
    assert damage_packets(engine)[-1].payload['damage_type'] == 'POISON'
    assert engine.state.actors[LEFT].resources[lod.QI] == before - 1  # the conversion's printed 1 Qi

    plain, ptable, pmid = fight(tmp_path / 'plain', left_mids=(FIRE,), left_features=(VENOMOUS,), right_hp=500)
    start = cold(tmp_path / 'plain', pmid).state.actors[LEFT].resources[lod.QI]
    commit_accept(plain, ptable, pmid, 'Ignite: Push Target', target=RIGHT)
    control = cold(tmp_path / 'plain', pmid)
    assert damage_packets(control)[-1].payload['damage_type'] == 'FIRE'  # the unconverted technique
    assert control.state.actors[LEFT].resources[lod.QI] == start


def test_venom_conversion_is_free_during_decaying_presence(tmp_path, monkeypatch):
    """"Venom Conversion costs 0 Qi once per turn" while Decaying Presence is active."""
    fixed_dice(monkeypatch, [19] + [1] * 80)
    combat, table, mid = fight(tmp_path, left_mids=(FIRE,), left_features=(VENOMOUS,), right_hp=500)
    activate_presence(combat, table, mid)
    before = cold(tmp_path, mid).state.actors[LEFT].resources[lod.QI]
    commit_accept(combat, table, mid, 'Ignite: Push Target + Venomous Qi', target=RIGHT)
    engine = cold(tmp_path, mid)
    assert damage_packets(engine)[-1].payload['damage_type'] == 'POISON'
    assert engine.state.actors[LEFT].resources[lod.QI] == before  # the one conversion this turn is waived


def test_venom_conversion_is_once_per_turn(tmp_path, monkeypatch):
    fixed_dice(monkeypatch, [19] + [1] * 80)
    combat, table, mid = fight(tmp_path, left_mids=(FIRE,), left_features=(VENOMOUS,), right_hp=500)
    variant = variant_action(cold(tmp_path, mid))
    commit_accept(combat, table, mid, 'Ignite: Push Target + Venomous Qi', target=RIGHT)
    engine = cold(tmp_path, mid)
    assert not any(candidate.source_definition_id == variant.source_definition_id
                   for candidate in engine.legal_candidates())
    turn(table, mid, RIGHT)
    turn(table, mid, LEFT)
    assert any(candidate.source_definition_id == variant.source_definition_id
               for candidate in cold(tmp_path, mid).legal_candidates())


# ------------------------------------------------------------------------------ Essence Rot
def touched(engine, target=RIGHT):
    return any(condition.condition_id == 'condition:typed.poison_touch'
               for condition in engine.state.actors[target].conditions.values())


def essence_rot_paid(engine):
    return [event for event in events(engine, 'PASSIVE_TRIGGERED') if 'essence_rot' in event.payload]


def poison_touch_strike(combat, table, mid):
    """A real Poison Touch through the table: the printed condition, not a fixture."""
    commit_accept(combat, table, mid, 'Deliver the Dose', target=RIGHT)


def test_essence_rot_costs_four_qi_and_lowers_the_maximum(tmp_path, monkeypatch):
    fixed_dice(monkeypatch, [19] + [1] * 80)
    combat, table, mid = fight(tmp_path, left_features=(POISON_TOUCH, ESSENCE), right_hp=500)
    poison_touch_strike(combat, table, mid)
    assert touched(cold(tmp_path, mid))
    before = cold(tmp_path, mid).state.actors[LEFT].resources[lod.QI]
    commit_accept(combat, table, mid, 'Poison jab', target=RIGHT)
    engine = cold(tmp_path, mid)
    assert [event.payload['essence_rot'] for event in essence_rot_paid(engine)] == [5]  # 3d8 (all 1s) + Key Ability 2
    assert engine.state.actors[LEFT].resources[lod.QI] == before - 4
    assert engine.state.actors[RIGHT].maximum_hp == 500 - 5
    assert engine.state.actors[RIGHT].maximum_hp_base == 500


def test_essence_rot_costs_two_during_decaying_presence(tmp_path, monkeypatch):
    fixed_dice(monkeypatch, [19] + [1] * 80)
    combat, table, mid = fight(tmp_path, left_mids=(POISON_TOUCH,), left_features=(POISON_TOUCH, ESSENCE), right_hp=500)
    activate_presence(combat, table, mid)
    poison_touch_strike(combat, table, mid)
    before = cold(tmp_path, mid).state.actors[LEFT].resources[lod.QI]
    commit_accept(combat, table, mid, 'Poison jab', target=RIGHT)
    engine = cold(tmp_path, mid)
    assert [event.payload['essence_rot'] for event in essence_rot_paid(engine)] == [5]
    assert engine.state.actors[LEFT].resources[lod.QI] == before - 2


def test_essence_rot_is_once_per_target_per_scene(tmp_path, monkeypatch):
    fixed_dice(monkeypatch, [19] + [1] * 80)
    combat, table, mid = fight(tmp_path, left_features=(POISON_TOUCH, ESSENCE), right_hp=500)
    poison_touch_strike(combat, table, mid)
    commit_accept(combat, table, mid, 'Poison jab', target=RIGHT)
    before = cold(tmp_path, mid).state.actors[LEFT].resources[lod.QI]
    floor = cold(tmp_path, mid).state.actors[RIGHT].maximum_hp
    jab(combat, table, mid, RIGHT)
    engine = cold(tmp_path, mid)
    assert len(essence_rot_paid(engine)) == 1
    assert engine.state.actors[LEFT].resources[lod.QI] == before
    assert engine.state.actors[RIGHT].maximum_hp == floor
