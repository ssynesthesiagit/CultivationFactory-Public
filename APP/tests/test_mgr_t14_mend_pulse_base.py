"""MGR-T14: the base row LIFE_BASE_MEND_THE_PULSE, clause by clause, at the real table.

"Action Type: Action / Range: Touch / Target: One living creature / Duration: Instantaneous /
Cost: 1 CP -- You restore the target's living pattern. The target regains Hit Points based on your
Realm. Mortal: 1d8 + your key ability modifier. Foundation: 2d8 ... Core Formation: 3d8 ...
Nascent Soul: 4d8 ... Mend the Pulse has no effect on undead or constructs unless a talent says
otherwise."

Every case below drives the row through ``TabletopService`` and then cold-reloads the saved session,
so each assertion reads committed fight state rather than an in-memory shortcut. Nothing here
fabricates a wound, a creature label or a receipt: the wound comes from a real committed typed
action on the table, and the labels come from the creature's own printed creature_type field.
Source: APP/authority/typed_mechanics/rules_text.json["LIFE_BASE_MEND_THE_PULSE"]
(sha256 e94088d19f59b695a46726adbfce44d55bfc0a9b5ea0f7224070a8a3c7876cf6), whose reviewed overlay
(APP/authority/typed_mechanics/reviewed_final.d/riders_c12.json, source text_sha256
01eec35d3e771480b2a80dae3f219756e7173dc7e592d4ac519ba87324d6226c) is compiled by
combat/factory_compiler.py::_target_kind and read at run time by combat/typed_executor.py and the
documented kind hooks in combat/ext/creature_kinds.py.
"""
import json
import zipfile

import pytest

from canonical_catalog.service import CanonicalCatalogAuthorityService
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.cw2_service_support import add_action
from tests.h1_support import ROOT, sheet
from tests.worker2_support import (ALLY, FOE, OWNER, candidate, fixture, reload, settle, turn)

MEND = 'LIFE_BASE_MEND_THE_PULSE'
# "unless a talent says otherwise": the talent is not this packet's row; it is only the named
# exception clause of the base row's kind limitation, so it is exercised, never implemented here.
ESOTERIC = 'tianxia.talent.life.esoteric_vitality'
QI = 'resource:core.qi'
# 1 square on this arena's grid is 5 feet, so the default ally square is exactly at Touch range.
TOUCH = {'x': 4, 'y': 6}
BEYOND_TOUCH = {'x': 12, 'y': 6}


def _wound(bundles):
    """Give every creature a real typed action that wounds, so the mend has something to restore."""
    for bundle in bundles:
        add_action(bundle, 'Open a wound', [{'type': 'damage', 'flat': 10, 'damage_types': ['force'],
                                             'applies_to': 'target'}])


def _label(kind):
    def transform(bundles):
        _wound(bundles)
        bundles[1]['actor_template']['creature_types'] = [kind]

    return transform


def _mend(engine, target):
    return [c for c in engine.legal_candidates()
            if getattr(engine.action_catalog.get(c.source_definition_id), 'display_name', '') == 'Mend the Pulse'
            and c.target_ids == (target,)]


def test_mend_the_pulse_comes_from_the_life_sphere_and_only_to_its_owner(tmp_path):
    """Ownership/acquisition: the Life sphere hands the row out as an automatic component.

    The wrong-owner control matters: a fighter who never took the Life sphere must not see the
    action at all, or the row would be a global button instead of a Life ability.
    """
    # Start with a portable sheet that has neither Life nor any of its base rows.
    # Learn only the Sphere through the real persisted table advancement API; the
    # production sheet loader must discover and materialize its automatic rows.
    project = '0badc0de-0000-4000-8000-000000000014'
    bare = sheet([])
    bare['identity']['path_ids'] = ['tianxia.path.qi_cultivation']
    assert not bare.get('spheres_and_talents')
    folder = tmp_path / 'portable_characters' / project
    folder.mkdir(parents=True)
    with zipfile.ZipFile(folder / 'current.zip', 'w') as archive:
        archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(bare))
    acquisition_combat = CombatService(ROOT, tmp_path)
    acquisition_table = TabletopService(acquisition_combat, tmp_path)
    acquisition_table.canonical_catalog = CanonicalCatalogAuthorityService(ROOT)
    # Explicit runtime resource for public CI's source-input export.
    assert (ROOT / 'authority/Tianxia_Sphere_Path_Access_R1.json').is_file()
    acquisition_table.add_advancement(project, 'sphere', 'tianxia.sphere.life')
    acquired = CombatService(ROOT, tmp_path)._factory_owner_sheet(project)
    block = acquired['spheres_and_talents']
    assert block['sphere_record_ids'] == ['tianxia.sphere.life']
    assert MEND in block['automatic_sphere_component_record_ids']
    assert MEND not in block['learned_talent_record_ids']
    with zipfile.ZipFile(folder / 'current.zip') as archive:
        assert json.loads(archive.read('Tianxia_Owner_Character_Sheet_v1.json')) == bare
    combat, table, mid = fixture(tmp_path, [], owner_bundle=compile_character(acquired, actor_id=OWNER),
                                 bundle_transform=_wound, seed='MGRT14-OWN')
    engine = reload(tmp_path, mid)
    owner = engine.action_catalog[next(c.source_definition_id for c in _mend(engine, ALLY))]

    # Real source acquisition: the row was compiled into this character's action catalog from the
    # sphere, not injected by the test. The compiled action id is namespaced, but it names this row.
    assert owner.parameters['typed']['source'] == MEND, owner.source_definition_id
    assert owner.source_definition_id.endswith(MEND), owner.source_definition_id
    assert owner.economy == 'ACTION', 'the printed Action Type is not an Action'
    assert owner.costs == ((QI, 1),), owner.costs  # "Cost: 1 CP"
    assert owner.range_ft == 5, 'Range: Touch'

    # Check the non-owner's actual menu on its own turn, rather than confusing
    # a candidate's target with the creature that owns the action.
    turn(table, mid, FOE)
    foe_engine = reload(tmp_path, mid)
    assert foe_engine.state.current_actor_id == FOE
    assert not [c for c in foe_engine.legal_candidates()
                if getattr(foe_engine.action_catalog.get(c.source_definition_id), 'display_name', '')
                == 'Mend the Pulse' and c.actor_id == FOE]


def test_a_character_without_the_life_sphere_is_offered_no_mend_at_all(tmp_path):
    """The pure wrong-owner case: no Life sphere on the sheet means no row, anywhere."""
    combat, table, mid = fixture(tmp_path, [], bundle_transform=_wound, seed='MGRT14-NOLIFE')
    engine = reload(tmp_path, mid)
    for candidate_row in engine.legal_candidates():
        action = engine.action_catalog.get(candidate_row.source_definition_id)
        assert getattr(action, 'display_name', '') != 'Mend the Pulse', candidate_row.source_definition_id


def test_mend_the_pulse_spends_one_cp_and_the_action_at_the_table(tmp_path):
    """"Cost: 1 CP" and "Action Type: Action", paid on commit and surviving a cold reload."""
    combat, table, mid = fixture(tmp_path, [MEND], bundle_transform=_wound, cl=10, seed='MGRT14-COST')
    engine = reload(tmp_path, mid)
    before_qi = engine.state.actors[OWNER].resources[QI]
    assert before_qi >= 1

    settle(table, mid, candidate(combat, mid, 'Open a wound', target=ALLY).candidate_id)
    engine = reload(tmp_path, mid)
    wounded = engine.state.actors[ALLY].current_hp
    assert wounded == engine.state.actors[ALLY].maximum_hp - 10

    settle(table, mid, candidate(combat, mid, 'Mend the Pulse', target=ALLY).candidate_id)
    after = reload(tmp_path, mid)
    assert after.state.actors[OWNER].resources[QI] == before_qi - 1
    assert after.state.actors[ALLY].current_hp > wounded
    assert not after.state.actors[OWNER].action_available


def test_mend_the_pulse_reaches_a_creature_at_touch_range(tmp_path):
    """"Range: Touch" -- five feet. The grid square is 5 feet, so this ally stands exactly at reach."""
    combat, table, mid = fixture(tmp_path, [MEND], bundle_transform=_wound, ally_position=TOUCH,
                                  seed='MGRT14-TOUCH')
    engine = reload(tmp_path, mid)
    assert _mend(engine, ALLY), 'an ally at 5 feet was not offered Mend the Pulse'


def test_mend_the_pulse_does_not_reach_past_touch(tmp_path):
    """The other side of the same boundary: 45 feet away, the table offers no Mend the Pulse."""
    combat, table, mid = fixture(tmp_path, [MEND], bundle_transform=_wound, ally_position=BEYOND_TOUCH,
                                  seed='MGRT14-FAR')
    engine = reload(tmp_path, mid)
    assert not _mend(engine, ALLY), 'Mend the Pulse reached a creature 45 feet away'


@pytest.mark.parametrize('cl,dice', [(1, 1), (4, 1), (5, 2), (9, 2), (10, 3), (14, 3), (15, 4), (20, 4)])
def test_mend_the_pulse_heals_the_printed_realm_dice_plus_the_key_ability_modifier(tmp_path, cl, dice):
    """"The target regains Hit Points based on your Realm" -- 1d8 / 2d8 / 3d8 / 4d8 + key modifier.

    The Mortal-to-Nascent Soul branches are four separate printed numbers, so every band boundary
    (CL 4|5, 9|10, 14|15) is checked against the committed roll receipt.
    """
    combat, table, mid = fixture(tmp_path, [MEND], bundle_transform=_wound, cl=cl,
                                  seed=f'MGRT14-CL{cl}')
    engine = reload(tmp_path, mid)
    typed = next(a for a in engine.action_catalog.values()
                 if getattr(a, 'display_name', '') == 'Mend the Pulse').parameters['typed']
    # The input sheet has CON 14: independently pin +2, not a value taken on trust
    # from the compiled row whose modifier propagation this test is checking.
    key_mod = (14 - 10) // 2
    assert typed['numbers']['key_mod'] == key_mod
    assert typed['numbers']['cl'] == cl

    settle(table, mid, candidate(combat, mid, 'Open a wound', target=ALLY).candidate_id)
    engine = reload(tmp_path, mid)
    ally = engine.state.actors[ALLY]
    before = ally.current_hp

    settle(table, mid, candidate(combat, mid, 'Mend the Pulse', target=ALLY).candidate_id)
    after = reload(tmp_path, mid)
    ally = after.state.actors[ALLY]
    (healing,) = [e for e in after.events if e.event_type == 'HEALING_APPLIED']
    offered = int(healing.payload['offered'])
    (roll,) = [e.payload for e in after.events if e.event_type == 'DAMAGE_ROLLED'
               and e.actor_id == OWNER and e.target_ids == (ALLY,)
               and str(e.payload.get('reason', '')).startswith('HEALING:')]
    assert roll['expression'] == f'{dice}d8+2', (cl, roll)
    assert len(roll['dice']) == dice
    assert all(1 <= value <= 8 for value in roll['dice'])
    assert roll['modifier'] == key_mod
    assert offered == roll['total'] == sum(roll['dice']) + key_mod
    assert ally.current_hp == min(ally.maximum_hp, before + offered), (cl, ally.current_hp, offered)


def test_mend_the_pulse_is_instantaneous(tmp_path):
    """"Duration: Instantaneous" -- the mend resolves at once and leaves nothing running on the table."""
    combat, table, mid = fixture(tmp_path, [MEND], bundle_transform=_wound, cl=10, seed='MGRT14-INSTANT')
    settle(table, mid, candidate(combat, mid, 'Open a wound', target=ALLY).candidate_id)
    before = reload(tmp_path, mid)

    settle(table, mid, candidate(combat, mid, 'Mend the Pulse', target=ALLY).candidate_id)
    after = reload(tmp_path, mid)
    assert not after.state.actors[ALLY].conditions, 'an Instantaneous mend left a condition behind'
    assert not after.state.actors[OWNER].conditions, 'an Instantaneous mend left a condition behind'
    assert after.state.actors[ALLY].temporary_hp == 0
    # Nothing is queued to fire later either.
    assert not [e for e in after.events[len(before.events):]
                if e.event_type in ('REACTION_OFFERED', 'CHECKPOINT_CREATED')]


@pytest.mark.parametrize('kind', ['Undead', 'Construct'])
@pytest.mark.parametrize('exception', [False, True])
def test_mend_the_pulse_has_no_effect_on_undead_or_constructs_unless_a_talent_says_otherwise(
        tmp_path, kind, exception):
    """"... has no effect on undead or constructs unless a talent says otherwise."

    Both halves are real: the base row withholds the action against a printed Undead/Construct
    label, and Esoteric Vitality ("can affect undead, constructs, ...") re-admits the very same row.
    An unlabelled creature remains eligible; nothing is inferred from a name or a condition.
    """
    talents = [MEND, ESOTERIC] if exception else [MEND]
    combat, table, mid = fixture(tmp_path, talents, bundle_transform=_label(kind),
                                  seed=f'MGRT14-{kind[:3]}{int(exception)}')
    engine = reload(tmp_path, mid)
    assert engine.state.actors[ALLY].creature_types == (kind,)

    assert bool(_mend(engine, ALLY)) is exception, (kind, exception, _mend(engine, ALLY))
    if exception:
        settle(table, mid, candidate(combat, mid, 'Open a wound', target=ALLY).candidate_id)
        wounded = reload(tmp_path, mid).state.actors[ALLY].current_hp
        assert wounded == engine.state.actors[ALLY].maximum_hp - 10
        settle(table, mid, candidate(combat, mid, 'Mend the Pulse', target=ALLY).candidate_id)
        healed = reload(tmp_path, mid)
        (receipt,) = [e for e in healed.events if e.event_type == 'HEALING_APPLIED'
                      and e.target_ids == (ALLY,)]
        offered = int(receipt.payload['offered'])
        assert offered > 0
        assert healed.state.actors[ALLY].current_hp == min(
            healed.state.actors[ALLY].maximum_hp, wounded + offered)
        assert healed.state.actors[ALLY].current_hp > wounded
        assert not healed.state.actors[OWNER].action_available
        # The cast spent this turn's action; remaining candidate checks below
        # describe the original, pre-cast menu captured above.
    # The caster remains eligible; this foe is outside Touch range. The foe
    # assertion establishes no ally-only rules contract.
    assert _mend(engine, OWNER)
    assert not [c for c in engine.legal_candidates()
                if getattr(engine.action_catalog.get(c.source_definition_id), 'display_name', '') == 'Mend the Pulse'
                and c.target_ids == (FOE,)]


def test_an_unlabelled_creature_is_never_guessed_into_being_undead(tmp_path):
    """The kind gate reads the printed label only; nothing is inferred from a name."""
    def nameless(bundles):
        _wound(bundles)
        bundles[1]['actor_template'].pop('creature_types', None)

    combat, table, mid = fixture(tmp_path, [MEND], bundle_transform=nameless, seed='MGRT14-PLAIN')
    engine = reload(tmp_path, mid)
    assert not engine.state.actors[ALLY].creature_types
    assert _mend(engine, ALLY)
