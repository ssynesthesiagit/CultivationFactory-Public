"""AUTO108 Dark sphere: the printed effects that now run on the fight table.

Every test drives a real compiled character through a real table session -- a TabletopService decision, a
commit, then a cold reload through a *new* CombatService (which must still replay) -- so nothing here is a
detached engine mutation. Blindfold builds no action yet (AUTO108.report.md section 3), so the bundle
transformer stands in for the compiled Meld; the save, the condition, the repeat save, the commit and the
reload are all the engine's own.

- Blindfold: "Darkvision does not overcome Blindfold. A creature that can see through supernatural Darkness is
  immune." Scoped to the *incoming* effect: the very same creature is blinded normally by anyone else's
  blindness, and the victim never has to own Blindfold itself.
- Blindfold: "The creature repeats the saving throw at the end of each of its turns, ending the effect on itself
  on a success" -- the engine's own repeat_save, so it survives a commit and clears on a good roll.
- Hide in Darkness: "While the target stands inside an area of your Darkness, it may take the Hide action even
  while clearly visible" -- an override of the ordinary line-of-sight requirement, and only while its own Meld
  runs. Both directions are proved with a Darkvision foe, which keeps seeing through the Darkness, so the
  override has to be the talent's doing and not the dark's: it lets a still-visible creature hide while its Meld
  runs, and keeps shut while the Meld does not.
"""
import copy
import json
from pathlib import Path

import pytest

from combat import senses, stealth, zones
from tests.h1_support import ROOT
from tests.test_r9i_karma_persistence import end_turn
from tests.worker2_support import ALLY, FOE, OWNER, candidate, fixture, reload, settle, turn

BLINDFOLD = 'TAL_DARK_BLINDFOLD'
HIDE = 'TAL_DARK_HIDE_IN_DARKNESS'
BLINDED = "condition:typed.blinded"
HIDDEN = "condition:typed.hidden"

AUTHORITY = json.loads((Path(ROOT) / 'authority' / 'Tianxia_Typed_Mechanics_Authority_R1.json').read_text(encoding='utf-8'))['mechanics']


def _numbers(bundle):
    """The owner's real compiled numbers (Save DC, Proficiency Bonus, key modifier)."""
    for row in bundle['action_catalog']:
        numbers = ((row.get('parameters') or {}).get('typed') or {}).get('numbers') or {}
        if numbers.get('save_dc') is not None:
            return dict(numbers)
    raise AssertionError('no compiled numbers')


def blindness_action(bundle, *, source=BLINDFOLD, mechanic=BLINDFOLD, display='Blindfold (test cast)',
                     target_kind='HOSTILE_ENTITY'):
    """A real catalog action carrying the reviewed typed row for ``mechanic``.

    Blindfold itself compiles to no action, so the bundle transformer supplies one; ``mechanic_of`` reads it
    exactly as it reads a compiled action, which is what scopes the immunity. Naming a different ``source``
    keeps Blindfold's own blindness row but attributes it to another ability, which is the control for
    "someone else's blindness still blinds".
    """
    row = AUTHORITY[mechanic]
    return {
        'source_definition_id': f"action:typed.auto108test.{source.lower()}",
        'display_name': display, 'owner_id': OWNER, 'economy': 'ACTION', 'resolution_kind': 'TYPED',
        'target_kind': target_kind, 'range_ft': 60, 'reach_ft': None, 'attack_bonus': None, 'attack_count': 1,
        'damage': None, 'damage_type': None, 'save': None, 'costs': [], 'concentration': True, 'radius_ft': None,
        'parameters': {'typed': {'effects': copy.deepcopy(row['effects']), 'riders': [],
                                 'numbers': _numbers(bundle), 'duration': copy.deepcopy(row['duration']),
                                 'source': source, 'coverage': row.get('coverage')},
                       'expected_damage': 0},
    }


_KEEP = object()  # "leave the compiler's own starting Meld alone"


def build(talents, *, blindfold_source=BLINDFOLD, mechanic=BLINDFOLD, foe_senses=(), owner_meld_start=_KEEP,
          owner_stealth_bonus=None):
    """A real fight whose owner can cast the Blindfold row and whose foe has the senses named."""
    def transform(bundles):
        owner, _, foe = bundles
        made = blindness_action(owner, source=blindfold_source, mechanic=mechanic)
        owner['action_catalog'].append(made)
        owner['actor_template']['action_ids'] = [*owner['actor_template']['action_ids'],
                                                 made['source_definition_id']]
        if owner_meld_start is not _KEEP:
            # Melds are cast before a fight or in it: a fighter who pre-cast one starts the fight with it running, and a
            # fighter who has not Melded it starts with none -- the negative case below, which still *knows* the talent.
            owner.setdefault('senses', {'rows': [], 'melds': [], 'meld_start': None})
            owner['senses']['meld_start'] = owner_meld_start
        for row in owner['action_catalog']:
            if (row.get('parameters') or {}).get('stealth') == 'hide' and owner_stealth_bonus is not None:
                # Hiding still has to beat DC 15 on its own check; this keeps the test about the override, not a d20.
                ((row['parameters'].setdefault('typed', {}).setdefault('effects', [{}]))[0])['bonus'] = owner_stealth_bonus
        sense = foe.setdefault('senses', {'rows': [], 'melds': [], 'meld_start': None})
        for name, feet in foe_senses:
            sense['rows'].append({'feature_id': 'test:grant', 'sense': name, 'range_ft': feet, 'when': 'always'})

    return transform


def cast(table, mid, combat, display, target):
    settle(table, mid, candidate(combat, mid, display, target=target).candidate_id)


def blinded(engine, actor_id=FOE):
    return [c for c in engine.state.actors[actor_id].conditions.values() if c.condition_id == BLINDED]


@pytest.mark.parametrize('sense,immune', [
    ('truesight', True),     # sees through supernatural Darkness -> immune
    ('blindsight', True),    # sees through Darkness -> immune
    ('darkvision', False),   # "Darkvision does not overcome Blindfold"
    (None, False),           # ordinary sight -> Blinded
])
def test_blindfold_immunity_follows_what_can_see_through_supernatural_darkness(tmp_path, sense, immune):
    """The printed exception, applied through a committed cast and read back after a cold reload."""
    combat, table, mid = fixture(tmp_path, [], seed='AUTO108-BF',
                                 bundle_transform=build([], foe_senses=[(sense, 60)] if sense else []))
    cast(table, mid, combat, 'Blindfold (test cast)', FOE)
    engine = reload(tmp_path, mid)
    assert bool(blinded(engine)) is (not immune)


@pytest.mark.parametrize('restricted,feet,pure', [(True, 60, False), (False, 0, False), (False, 1, True)])
def test_blindfold_requires_general_sight_with_positive_effective_range(tmp_path, restricted, feet, pure):
    """Creature-only sight and a sense reduced to zero do not see through the shadow band."""
    transform = build([], foe_senses=[('blindsight', feet)])

    def grants(bundles):
        transform(bundles)
        bundles[0]['action_catalog'][-1]['parameters']['typed']['numbers']['save_dc'] = 100
        if restricted:
            bundles[2]['senses']['rows'][-1]['against_conditions'] = [BLINDED]

    combat, table, mid = fixture(tmp_path, ['TAL_DARK_PURE_DARKNESS'] if pure else [],
                                 seed='AUTO108-BF', bundle_transform=grants,
                                 foe_position={'x': 4, 'y': 5} if pure else None)
    if pure:
        foe = reload(tmp_path, mid).state.actors[FOE]
        settle(table, mid, candidate(combat, mid, 'Shape Darkness: Pure Darkness').candidate_id)
        settle(table, mid, candidate(combat, mid, 'Darkness', at=(foe.position.x, foe.position.y)).candidate_id)
        end_turn(table, mid)
        turn(table, mid, OWNER)
        engine = reload(tmp_path, mid)
        assert senses.reach(engine, engine.state.actors[FOE], 'blindsight', engine.state.actors[FOE]) == 0
        # The caster's Darkvision reaches only 5 feet in Pure Darkness. Keep this
        # a legal sight-targeted cast under batch 3's LoS rules, not a sight bypass.
        assert stealth.sees(engine, engine.state.actors[OWNER], engine.state.actors[FOE])
    cast(table, mid, combat, 'Blindfold (test cast)', FOE)
    assert len(blinded(reload(tmp_path, mid))) == 1


def test_blindfold_eligibility_is_pure_on_a_reloaded_table(tmp_path):
    """Repeated previews of the committed immunity decision never append events or alter state."""
    from combat.ext.dark_riders import blindfold_immune
    from combat.typed_executor import Context
    combat, table, mid = fixture(tmp_path, [], seed='AUTO108-BF',
                                 bundle_transform=build([], foe_senses=[('truesight', 60)]))
    cast(table, mid, combat, 'Blindfold (test cast)', FOE)
    engine = reload(tmp_path, mid)
    action = next(a for a in engine.action_catalog.values() if a.display_name == 'Blindfold (test cast)')
    subject = engine.state.actors[FOE]
    ctx = Context(engine=engine, actor=engine.state.actors[OWNER], action=action, intent=None,
                  typed=action.parameters['typed'], targets=[subject])
    before = (engine.state.model_dump(mode='json'), [e.model_dump(mode='json') for e in engine.events])
    for _ in range(3):
        assert blindfold_immune(ctx, subject, {'condition': 'blinded'}) is False
    assert (engine.state.model_dump(mode='json'), [e.model_dump(mode='json') for e in engine.events]) == before


def test_restricted_grant_does_not_mask_an_independent_general_sense(tmp_path):
    """An ordinary Blindsight grant still qualifies alongside creature-restricted Blindsight."""
    transform = build([], foe_senses=[('blindsight', 60), ('blindsight', 120)])
    def grants(bundles):
        transform(bundles)
        bundles[2]['senses']['rows'][-1]['against_conditions'] = [BLINDED]
    combat, table, mid = fixture(tmp_path, [], seed='AUTO108-BF', bundle_transform=grants)
    cast(table, mid, combat, 'Blindfold (test cast)', FOE)
    assert not blinded(reload(tmp_path, mid))


def test_contesting_light_reminder_discloses_the_supported_subset_after_reload(tmp_path):
    """The table's reminder must distinguish its narrow Radiance contest from GM adjudication."""
    def transform(bundles):
        owner = bundles[0]
        made = blindness_action(owner, source='TAL_DARK_CONTESTING_LIGHT', mechanic='TAL_DARK_CONTESTING_LIGHT',
                                display='Contesting Light reminder', target_kind='SELF')
        made['parameters']['typed']['riders'] = AUTHORITY['TAL_DARK_CONTESTING_LIGHT']['riders']
        owner['action_catalog'].append(made)
        owner['actor_template']['action_ids'].append(made['source_definition_id'])
    combat, table, mid = fixture(tmp_path, [], seed='DARK-CONTEST-REMINDER', bundle_transform=transform)
    cast(table, mid, combat, 'Contesting Light reminder', OWNER)
    text = ' '.join(str(e.payload.get('rider') or '') for e in reload(tmp_path, mid).events)
    assert 'Radiance area' in text
    assert 'center' in text and 'another creature' in text and 'one' in text
    assert 'Light-sphere effects' in text and 'GM' in text and 'remaining overlaps' in text
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    fresh_table = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    shown = ' '.join(row['summary'] for row in fresh_table.events(mid, 0)['events'])
    assert 'Radiance area' in shown and 'center' in shown
    assert 'Light-sphere effects' in shown and 'remaining overlaps' in shown


def test_the_immunity_is_blindfolds_own_effect_and_no_other_blindsources(tmp_path):
    """Any other blindness blinds the same Truesighted creature: the gate is the incoming source."""
    combat, table, mid = fixture(tmp_path, [], seed='AUTO108-UNRELATED',
                                 bundle_transform=build([], blindfold_source='test:other_spell',
                                                        mechanic=BLINDFOLD, foe_senses=[('truesight', 60)]))
    cast(table, mid, combat, 'Blindfold (test cast)', FOE)
    engine = reload(tmp_path, mid)
    assert len(blinded(engine)) == 1  # Truesight does not make a creature immune to someone else's blindness


def test_a_nonowner_with_a_qualifying_sense_is_still_immune_to_blindfold(tmp_path):
    """The foe owns no Blindfold talent at all, and is still immune: the printed exception belongs to the effect."""
    combat, table, mid = fixture(tmp_path, [HIDE], seed='AUTO108-NONOWNER',
                                 bundle_transform=build([HIDE], foe_senses=[('blindsight', 60)]))
    assert BLINDFOLD not in senses.melds_of(reload(tmp_path, mid), reload(tmp_path, mid).state.actors[FOE])
    cast(table, mid, combat, 'Blindfold (test cast)', FOE)
    assert not blinded(reload(tmp_path, mid))


def test_blindfold_repeat_save_ends_the_blindfold_on_a_good_roll(tmp_path):
    """End of the target's own turn: the repeat save it passes ends the effect on itself, across a commit."""
    combat, table, mid = fixture(tmp_path, [], seed='AUTO108-RPT', bundle_transform=build([]))
    cast(table, mid, combat, 'Blindfold (test cast)', FOE)
    engine = reload(tmp_path, mid)
    held = blinded(engine)
    assert len(held) == 1
    assert held[0].data.get('repeat_save') == {'ability': 'WIS', 'dc': 16, 'when': 'end'}  # the engine's own repeat save
    turn(table, mid, FOE)
    end_turn(table, mid)          # the printed save is at the *end* of its turn
    assert not blinded(reload(tmp_path, mid))
    assert any(r.event_type == 'SAVE_ROLLED' for r in reload(tmp_path, mid).events)


def hide_offered(engine, actor_id=OWNER):
    """Whether the table is currently offering this fighter the Hide action at all."""
    return any(getattr(engine.action_catalog.get(c.source_definition_id), 'display_name', None) == 'Hide'
               and c.actor_id == actor_id for c in engine.legal_candidates())


def test_hide_in_darkness_lets_a_visible_creature_hide_in_its_own_darkness(tmp_path):
    """The override of the Hide action's line-of-sight requirement, committed and read back cold.

    The foe is Darkvision, so it keeps seeing the owner *through* the Darkness (combat/rules/senses.json: "A creature with
    Darkvision can see through this Darkness"). That is the whole point: without it, ordinary loss of sight would let any
    creature hide and the test would pass even with the talent's override broken. Every visibility claim below is made
    after the Darkness is on the table, not before.
    """
    combat, table, mid = fixture(tmp_path, [HIDE], seed='AUTO108-HIDE',
                                 bundle_transform=build([HIDE], owner_meld_start=HIDE, owner_stealth_bonus=20,
                                                        foe_senses=[('darkvision', 60)]))
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    # Clearly visible: an enemy sees it, so the ordinary Hide action is refused and not even offered.
    assert any(stealth.sees(engine, other, owner) for other in engine.state.actors.values()
               if other.entity_id != owner.entity_id and other.team_id != owner.team_id)
    assert not stealth.can_hide(engine, owner)
    assert hide_offered(engine) is False

    # Standing inside an area of its own Darkness, with its Meld running, the requirement is overridden.
    settle(table, mid, candidate(combat, mid, 'Darkness',
                                 at=(owner.position.x, owner.position.y)).candidate_id)
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert senses.meld_active(engine, owner, HIDE) is True
    assert any(z.owner_id == OWNER and str(z.trigger_profile.get('name') or '').lower() == 'darkness'
               and zones._inside(engine, owner, z) for z in zones.typed_zones(engine))

    # Still clearly visible: the Darkvision foe sees it right through its own Darkness, so Hide is still unavailable
    # without the talent. This is what makes the rest of the test the talent's doing and not the dark's.
    assert any(stealth.sees(engine, other, owner) for other in engine.state.actors.values()
               if other.entity_id != owner.entity_id and other.team_id != owner.team_id)
    assert stealth.can_hide(engine, owner) is False
    assert stealth.can_hide(engine, owner, inside='Darkness') is True

    end_turn(table, mid)          # Darkness spent the Action; Hide needs a fresh one
    turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    # Same Action state as the refusal at the top of this test, opposite outcome: the compiled Hide action carries its own
    # area ("hide_inside") and the running Meld now puts it on the menu.
    assert hide_offered(engine) is True
    cast(table, mid, combat, 'Hide', OWNER)
    engine = reload(tmp_path, mid)
    assert any(c.condition_id == HIDDEN for c in engine.state.actors[OWNER].conditions.values())


def test_hide_in_darkness_stays_shut_while_its_meld_is_inactive(tmp_path):
    """The same fight with the Meld not running: still visible, so Hide is refused and not offered at all.

    The owner still *knows* Hide in Darkness -- the compiler gave its Hide action the own-area ("hide_inside") parameter --
    so only the Meld itself keeps the override shut (combat/stealth.py in_own_area asks senses.meld_active).
    """
    combat, table, mid = fixture(tmp_path, [HIDE], seed='AUTO108-NOMELD',
                                 bundle_transform=build([HIDE], owner_meld_start=None, owner_stealth_bonus=20,
                                                        foe_senses=[('darkvision', 60)]))
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert HIDE not in (senses.melds_of(engine, owner))       # knows the talent, has not Melded it
    assert senses.meld_active(engine, owner, HIDE) is False

    settle(table, mid, candidate(combat, mid, 'Darkness',
                                 at=(owner.position.x, owner.position.y)).candidate_id)
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    # Every other part of the printed rule holds: its own Meld aside, it stands in an area of its own Darkness.
    assert any(z.owner_id == OWNER and str(z.trigger_profile.get('name') or '').lower() == 'darkness'
               and zones._inside(engine, owner, z) for z in zones.typed_zones(engine))
    assert any(stealth.sees(engine, other, owner) for other in engine.state.actors.values()
               if other.entity_id != owner.entity_id and other.team_id != owner.team_id)

    # ... and the override stays shut: no Hiding, so the Hide action is not on the menu. The Action is refreshed first, so
    # a spent Action cannot be what is refusing it -- the missing Meld is.
    assert stealth.can_hide(engine, owner) is False
    assert stealth.can_hide(engine, owner, inside='Darkness') is False
    end_turn(table, mid)
    turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    assert hide_offered(engine) is False
    assert stealth.can_hide(engine, engine.state.actors[OWNER], inside='Darkness') is False
    assert not any(c.condition_id == HIDDEN for c in engine.state.actors[OWNER].conditions.values())
