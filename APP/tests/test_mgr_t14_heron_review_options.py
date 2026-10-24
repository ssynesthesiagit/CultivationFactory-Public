"""Public synthetic declarations in native learning/table commits; no history or live services."""
import copy
import json
import zipfile

import pytest

from canonical_catalog.service import CanonicalCatalogAuthorityService
from combat.canonical import canonical_sha256
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.hunt12_support import hit_dice
from tests.worker2_support import OWNER, FOE, fixture, reload, settle, turn
from tests.test_tabletop_hunt6 import on_hold

SCHOOL = 'tianxia.subpath.body.white_heron_crescent_body'
WING = SCHOOL + '.feature.white_wing_crosses_the_reed_field'
JI = 'tianxia.mortal.weapon.ji'
KIT = {'starting_kit': {'items': [{'item_id': JI}]}}
HOLD = 'system:combat.hold_position'


def learned(tmp_path, *, learn=True):
    """Real portable sheet -> native advancement -> cold projected acquisition."""
    pid = '0badc0de-0000-4000-8000-000000000059'
    doc = sheet([], cl=14, primary='Stamina', kit=KIT, dc=50)
    doc['identity'].update(path='Body Refining', path_ids=['tianxia.path.body_refining'])
    doc['path_and_subpath'] = {'path_record_ids': ['tianxia.path.body_refining']}
    folder = tmp_path / 'portable_characters' / pid
    folder.mkdir(parents=True)
    with zipfile.ZipFile(folder / 'current.zip', 'w') as archive:
        archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(doc))
    table = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    table.canonical_catalog = CanonicalCatalogAuthorityService(ROOT)
    if learn:
        table.add_advancement(pid, 'subpath', SCHOOL)
    return CombatService(ROOT, tmp_path)._factory_owner_sheet(pid)


def fight(tmp_path, *, transform=None, learn=True):
    bundle = compile_character(learned(tmp_path / 'learning', learn=learn),
                               actor_id=OWNER, reaction_plan={'ask': True})
    if transform:
        transform(bundle)
        bundle.pop('bundle_sha256', None)
        bundle['bundle_sha256'] = canonical_sha256(bundle)
    return fixture(tmp_path / 'fight', [], cl=14, owner_bundle=bundle, primary='Stamina',
                   owner_path='Body Refining', owner_kit=KIT, named=True, extra_foes=1,
                   foe_position={'x': 4, 'y': 6}, ally_position={'x': 3, 'y': 7})


def hold_id(combat, mid):
    return next(c.candidate_id for c in combat._load_session(mid).engine.legal_candidates()
                if c.source_definition_id == HOLD)


def grant_opportunity(engine):
    """Synthetic trigger; native accepted Reaction payment, attack and receipt."""
    from combat import typed_reactions as tr
    actor = engine.state.actors[OWNER]
    row = tr.opportunity_reaction_row(engine, actor)
    tr.open_reaction(engine, row, actor, (FOE,), 'test:explicit_opportunity')
    tr.spend_reaction(engine, actor, row)
    tr.opportunity_attack(engine, actor, engine.state.actors[FOE], engine._active_intent,
                          reaction_opened=True)
    engine._append_event('REACTION_RESOLVED', 'system:combat.opportunity_attack',
                         actor_id=OWNER, target_ids=(FOE,))


def admitted_unarmed_default(bundle):
    """Keep a legal unarmed OA alongside the actually readied Polearm."""
    unarmed = compile_character(sheet([], cl=14), actor_id=OWNER)
    default = next(a for a in unarmed['action_catalog'] if a['source_definition_id'].endswith('.opportunity_attack'))
    default = copy.deepcopy(default)
    default['display_name'] = 'Unarmed Opportunity Attack'
    index = next(i for i, a in enumerate(bundle['action_catalog'])
                 if a['source_definition_id'] == default['source_definition_id'])
    bundle['action_catalog'][index] = default
    row = next(r for r in bundle['typed_reactions'] if r.get('block') == 'opportunity')
    row['reach_ft'] = 5


@pytest.mark.parametrize('auto', [False, True])
@pytest.mark.parametrize('selection', ['unarmed', 'polearm'])
def test_learning_retains_default_and_added_oa_through_table_and_reload(tmp_path, monkeypatch, auto, selection):
    from combat import typed_reactions as tr
    from tests.test_c7_review_fixup import hold_ai

    hit_dice(monkeypatch)
    combat, table, mid = fight(tmp_path, transform=admitted_unarmed_default)
    turn(table, mid, FOE)
    if auto:
        hold_ai(combat, mid, FOE)

    on_hold(monkeypatch, grant_opportunity)
    # Native automatic seats use the same admission/choice path; only the
    # creature's already-legal options are inspected, never hidden opponents.
    prompts = settle(table, mid, hold_id(combat, mid), auto=auto, choices={
        'choice:needle.opportunity_profile': ['0' if selection == 'unarmed' else '1'],
        'choice:needle.white_wing_move': None,
        'choice:needle.herons_passing_cut': None,
    })
    offered = next(p['choice']['options'] for p in prompts
                   if p['context']['reaction_source_id'] == 'choice:needle.opportunity_profile')
    labels = [o['label'] for o in offered]
    assert labels[0] == 'Unarmed Opportunity Attack'
    assert any('Ji' in label for label in labels[1:])
    engine = reload(tmp_path / 'fight', mid)
    assert not engine.state.actors[OWNER].reaction_available
    attacks = [e for e in engine.events if e.event_type == 'ATTACK_ROLLED' and e.actor_id == OWNER]
    assert len(attacks) == 1
    assert attacks[0].source_definition_id.endswith('.opportunity_attack') is (selection == 'unarmed')


def bonus_polearm(bundle):
    base = next(a for a in bundle['action_catalog'] if a['display_name'] == 'Ji (Halberd) attack')
    action = copy.deepcopy(base)
    action.update(source_definition_id='action:test.heron.bonus_polearm', display_name='Practice bonus Polearm hit',
                  economy='BONUS_ACTION')
    action['parameters']['typed']['weapon_source_id'] = base['source_definition_id']
    attack = action['parameters']['typed']['effects'][0]
    attack['count'] = 1
    attack.pop('count_by_cl', None)
    bundle['action_catalog'].append(action)
    bundle['actor_template']['action_ids'].append(action['source_definition_id'])


@pytest.mark.parametrize('trigger', ['bonus', 'own_turn_oa'])
@pytest.mark.parametrize('outcome', ['push', 'prone', 'ac'])
def test_white_wing_non_attack_action_hits_keep_non_attack_endings(tmp_path, monkeypatch, trigger, outcome):
    from combat import typed_reactions as tr

    hit_dice(monkeypatch, save_roll=1)
    combat, table, mid = fight(tmp_path, transform=bonus_polearm if trigger == 'bonus' else None)
    if trigger == 'own_turn_oa':
        on_hold(monkeypatch, grant_opportunity)
        cid = hold_id(combat, mid)
    else:
        cid = next(c.candidate_id for c in combat._load_session(mid).engine.legal_candidates()
                   if c.source_definition_id == 'action:test.heron.bonus_polearm' and c.target_ids == (FOE,))
    prompts = settle(table, mid, cid, choices={
        'choice:needle.opportunity_profile': 'first',
        'choice:needle.white_wing_move': ['cell:5,6'],
        'choice:needle.white_wing_result': [outcome],
        'choice:needle.herons_passing_cut': None,
    })
    result = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.white_wing_result')
    options = {o['id'] for o in result['choice']['options']}
    assert options == {'push', 'prone', 'ac'}  # A granted hit cannot grant another attack.
    engine = reload(tmp_path / 'fight', mid)
    actor, foe = engine.state.actors[OWNER], engine.state.actors[FOE]
    assert (actor.position.x, actor.position.y) == (5, 6)
    assert actor.turn_flags.get('_round_white_wing')
    assert len([e for e in engine.events if e.event_type == 'ATTACK_ROLLED' and e.actor_id == OWNER]) == 1
    if outcome == 'push':
        assert foe.position.x < 4
    elif outcome == 'prone':
        assert any(c.condition_id.endswith('.prone') for c in foe.conditions.values())
    else:
        assert any(m.source_definition_id == WING and m.value == 2 for m in actor.modifiers.values())
        # Start-of-source-next-turn expiry is durable, not a fight-long bonus.
        settle(table, mid, table.state(mid)['menu']['end_turn'], choices={})
        turn(table, mid, OWNER)
        assert not any(m.source_definition_id == WING for m in reload(tmp_path / 'fight', mid).state.actors[OWNER].modifiers.values())


@pytest.mark.parametrize('learn,own_turn', [(False, True), (True, False)])
def test_white_wing_non_attack_trigger_is_inert_for_nonowner_or_off_turn(tmp_path, monkeypatch, learn, own_turn):
    from combat import typed_reactions as tr

    hit_dice(monkeypatch)
    combat, table, mid = fight(tmp_path, learn=learn)
    if not own_turn:
        turn(table, mid, FOE)
    on_hold(monkeypatch, grant_opportunity)
    prompts = settle(table, mid, hold_id(combat, mid), choices={'choice:needle.opportunity_profile': 'first'})
    assert not any(p['context']['reaction_source_id'].startswith('choice:needle.white_wing') for p in prompts)
    engine = reload(tmp_path / 'fight', mid)
    assert not engine.state.actors[OWNER].turn_flags.get('_round_white_wing')
