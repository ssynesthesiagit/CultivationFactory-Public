"""OPUS1 batch 2: Karmic Debt, Persistent Technique and Heaven-Lifting Grip through the real table, with cold reloads.

All three compiled to nothing before (HUNT177 CONFIRMED 2). Saves are forced by sealed typed actions so the d20
rewrite runs on a genuine typed save; the grapple is the native unarmed Grapple option.
"""
import copy

from combat.canonical import canonical_sha256
from combat.ext import insight_rewrites as ir
from combat.ext import martial_insights as mi
from tests.h1_support import sheet
from tests.worker2_support import ALLY, FOE, OWNER, candidate, fixture, prompt_turn, reload, settle

FRIGHTEN = [{'type': 'save', 'ability': 'wis', 'on_success': [], 'on_fail': [
    {'type': 'condition', 'condition': 'frightened', 'applies_to': 'target', 'duration': 'until_end_of_your_next_turn'}]}]


def seal(bundle, name, effects, *, save_dc, sphere=None):
    """A deterministic typed save action on this fighter (the shipped executor resolves it)."""
    aid = 'action:test.opus1.' + bundle['actor_id'].rsplit('.', 1)[-1] + '.' + name.replace(' ', '_').lower()
    typed = {'source': 'test:opus1', 'effects': copy.deepcopy(effects), 'riders': [], 'duration': {'kind': 'instant'},
             'numbers': {'cl': 15, 'pb': 5, 'save_dc': save_dc, 'attack_bonus': 100}}
    if sphere:
        typed['sphere'] = sphere
    bundle['action_catalog'].append({'source_definition_id': aid, 'display_name': name, 'owner_id': bundle['actor_id'],
                                     'economy': 'ACTION', 'resolution_kind': 'TYPED', 'target_kind': 'ANY_CREATURE',
                                     'range_ft': 60, 'costs': [], 'parameters': {'typed': typed, 'expected_damage': 0}})
    bundle['actor_template']['action_ids'].append(aid)
    bundle.pop('bundle_sha256', None)
    bundle['bundle_sha256'] = canonical_sha256(bundle)
    return aid


def _frightened(actor):
    return any(c.condition_id == 'condition:typed.frightened' for c in actor.conditions.values())


def _rewrites(engine, feature):
    return [e for e in engine.events if e.event_type == 'D20_REWRITTEN' and e.source_definition_id == feature]


# ----------------------------------------------------------------------------------------------------- Karmic Debt
def test_karmic_debt_turns_one_failed_save_into_a_success_once_per_fight(tmp_path):
    combat, table, mid = fixture(tmp_path, [], owner_insights=[ir.KARMIC_DEBT], ally_position={'x': 1, 'y': 9},
                                 bundle_transform=lambda bundles: seal(bundles[2], 'Dread Gaze', FRIGHTEN, save_dc=100))
    prompt_turn(table, mid, FOE)
    prompts = settle(table, mid, candidate(combat, mid, 'Dread Gaze', target=OWNER).candidate_id,
                     picks={'reaction:typed.' + ir.KARMIC_DEBT: 'USE'})
    asked = [p for p in prompts if 'Karmic Debt' in str(p)]
    assert asked, prompts
    engine = reload(tmp_path, mid)
    assert len(_rewrites(engine, ir.KARMIC_DEBT)) == 1
    assert not _frightened(engine.state.actors[OWNER])
    assert any('Karmic Debt' in str((e.payload or {}).get('log')) for e in engine.events if e.event_type == 'PASSIVE_TRIGGERED')
    # Once per fight: the next failed save on a later turn is not offered again.
    prompt_turn(table, mid, OWNER)
    prompt_turn(table, mid, FOE)
    prompts = settle(table, mid, candidate(combat, mid, 'Dread Gaze', target=OWNER).candidate_id)
    assert not [p for p in prompts if 'Karmic Debt' in str(p)]
    engine = reload(tmp_path, mid)
    assert len(_rewrites(engine, ir.KARMIC_DEBT)) == 1 and _frightened(engine.state.actors[OWNER])


# ---------------------------------------------------------------------------------------------- Persistent Technique
def test_persistent_technique_spends_3_cp_to_force_a_reroll_of_a_passed_save(tmp_path):
    def setup(bundles):
        seal(bundles[0], 'Fear Palm', FRIGHTEN, save_dc=1, sphere='tianxia.sphere.test')
        seal(bundles[0], 'Plain Fear', FRIGHTEN, save_dc=1)

    combat, table, mid = fixture(tmp_path, [], owner_insights=[ir.PERSISTENT], ally_position={'x': 1, 'y': 9},
                                 bundle_transform=setup)
    qi = reload(tmp_path, mid).state.actors[OWNER].resources['resource:core.qi']
    prompts = settle(table, mid, candidate(combat, mid, 'Fear Palm', target=FOE).candidate_id,
                     picks={'reaction:typed.' + ir.PERSISTENT: 'USE'})
    assert [p for p in prompts if 'Persistent Technique' in str(p)], prompts
    engine = reload(tmp_path, mid)
    assert len(_rewrites(engine, ir.PERSISTENT)) == 1
    assert engine.state.actors[OWNER].resources['resource:core.qi'] == qi - 3


def test_persistent_technique_ignores_actions_that_are_not_sphere_talents(tmp_path):
    combat, table, mid = fixture(tmp_path, [], owner_insights=[ir.PERSISTENT], ally_position={'x': 1, 'y': 9},
                                 bundle_transform=lambda bundles: seal(bundles[0], 'Plain Fear', FRIGHTEN, save_dc=1))
    prompts = settle(table, mid, candidate(combat, mid, 'Plain Fear', target=FOE).candidate_id)
    assert not [p for p in prompts if 'Persistent Technique' in str(p)]
    assert not _rewrites(reload(tmp_path, mid), ir.PERSISTENT)


# ----------------------------------------------------------------------------------------------- Heaven-Lifting Grip
def _held(actor, condition):
    return [c for c in actor.conditions.values() if c.condition_id == 'condition:typed.' + condition]


def test_heaven_lifting_grip_restrains_the_grappled_creature_until_it_escapes(tmp_path):
    weak = sheet([], cl=15, score=1)
    combat, table, mid = fixture(tmp_path, [], owner_insights=[mi.HEAVEN_GRIP], foe_sheet=weak,
                                 foe_position={'x': 4, 'y': 6}, ally_position={'x': 1, 'y': 9})
    settle(table, mid, candidate(combat, mid, 'Grapple', target=FOE).candidate_id)
    engine = reload(tmp_path, mid)
    foe = engine.state.actors[FOE]
    grips, restraints = _held(foe, 'grappled'), _held(foe, 'restrained')
    assert grips and len(restraints) == 1
    assert restraints[0].data['parent_hold'] in foe.conditions
    # Releasing the grapple (here: the parent hold is removed) frees the creature from the linked Restrained too.
    from combat.ext.linked_holds import reconcile
    parent = restraints[0].data['parent_hold']
    foe.conditions.pop(parent)
    reconcile(engine)
    assert not _held(foe, 'restrained')
    assert mi.heaven_grip_companions(engine, engine.state.actors[OWNER], 'missing') is None
