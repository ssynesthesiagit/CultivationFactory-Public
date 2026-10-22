"""A2R04: Smoke and Sound qualified contract residual 1 (owner 2026-10-11: every printed combat
effect of these features resolved by the engine).  Real compiled abilities through session/table
commit and cold reload, on the owner's service (CombatService + TabletopService + execute_intent).

Resonant Note's printed object/construct clause ("If the target is an unattended object, brittle
structure, ordinary barrier, or construct, add your Proficiency Bonus to the damage") and its
fourth rider ("the target cannot benefit from ordinary sound-based hiding until the start of your
next turn") are the first two automated rows of the lane.
"""

import json
import pytest

from combat.typed_executor import bears_mark
from tests.auto_worker1_support import LEFT, RIGHT, fight, settle, turn
from tests.test_a2_force import cold, open_arena, send_candidate
from tests.h1_support import ROOT

NOTE = "TAL_SOUND_RESONANT_NOTE"


@pytest.fixture(scope="module", autouse=True)
def shipped_note_object_input():
    # Directory enumeration is not a static Python dependency. Preserve the
    # actual feature block in public CI; never replace it with synthetic data.
    data = json.loads((ROOT / "combat/rules/feature_blocks.d/riders_lane5.json").read_text())
    assert data["features"][NOTE]["block"] == "object_damage"

# Resonance is the mark Resonant Note's riders gate on; preparing it up front
# lets a single service-level Action fire the "already bears your Resonance" rider.
RESONANCE = {"type": "mark", "mark": "Resonance", "applies_to": "target"}


def construct_sheet(construct):
    def sheet_edit(sheet, aid):
        if aid == RIGHT:
            sheet["identity"]["creature_type"] = "Construct" if construct else "Humanoid"

    return sheet_edit


def damage_roll(engine):
    return next(r for r in reversed(engine.rolls)
                if r.reason.startswith("DAMAGE:") and "RESONANT" in r.reason.upper())


@pytest.mark.parametrize("construct", [False, True])
def test_resonant_note_adds_proficiency_bonus_only_to_a_construct(tmp_path, construct):
    """"... If the target is an unattended object, brittle structure, ordinary barrier, or
    construct, add your Proficiency Bonus to the damage."  The creature half of that list is
    a creature kind, so the typed damage row carries the bonus
    (combat/ext/creature_kinds.py bonus_if_kind)."""
    combat, table, mid = fight(tmp_path, [NOTE], cl=15, left_attack_bonus=100,
                                   sheet_edit=construct_sheet(construct))
    settle(send_candidate(combat, table, mid, "Resonant Note: Deafen", target=RIGHT))
    engine = cold(combat, mid)
    roll = damage_roll(engine)
    assert int(roll.modifier or 0) == (4 if construct else 0)


def test_resonant_note_sound_hiding_rider_denies_ordinary_sound_hiding(tmp_path):
    """"If the target already bears your Resonance, choose one rider on a hit: ... the target
    cannot benefit from ordinary sound-based hiding until the start of your next turn."  The
    fourth rider is engine state (a held condition with the printed expiry), not a GM reminder."""
    HIDING = "condition:typed.sound_hiding_denied"
    combat, table, mid = fight(tmp_path, [NOTE], cl=15, left_attack_bonus=100,
                                   prepare=[RESONANCE], prepare_target="ANY_CREATURE")
    from tests.auto_worker1_support import act
    assert act(table, mid, "Prepare", target_id=RIGHT)["status"] == "COMMITTED"
    engine = cold(combat, mid)
    assert not [c for c in engine.state.actors[RIGHT].conditions.values()
                if c.condition_id == HIDING]
    settle(send_candidate(combat, table, mid, "Resonant Note: Sound Hiding", target=RIGHT))
    engine = cold(combat, mid)
    held = [c for c in engine.state.actors[RIGHT].conditions.values()
            if c.condition_id == HIDING]
    assert len(held) == 1
    assert held[0].data["rule"] == {"hiding_denied": ["sound_reliance"]}
    assert held[0].expires_on == "START_OF_SOURCE_NEXT_TURN"
    assert bears_mark(engine.state.actors[RIGHT], LEFT, "Resonance")
    # It is the note caster's next turn that retires it, as printed.
    act(table, mid, "end")
    turn(table, mid, LEFT)
    engine = cold(combat, mid)
    assert not [c for c in engine.state.actors[RIGHT].conditions.values()
                if c.condition_id == HIDING]


def brittle_arena(arena):
    open_arena(arena)
    # A wall section is a printed structure; glass is a brittle material
    # (combat/object_rules.py has_tag "fragile"), so together they are a brittle structure.
    arena["map_objects"] = [{"id": 1, "x": 8, "y": 6, "kind": "wall_section",
                             "name": "Glass wall", "material": "glass", "size": "large",
                             "hp": 999, "ac": 1, "unattended": False}]


def test_a_blocking_structure_is_aimable_at_range_without_sight_through_it(tmp_path):
    """A wall you can see is a legal aim point; the wall's own cell must not hide itself.

    The printed target is "one creature or object you can perceive". Before the
    endpoint rule in combat/sight_lines.py hit() covered solid (BLOCKED) terrain
    too, a blocking object's own cell was reported unseen from every square but
    its own, so no object clause could be used at range at all. The same rule
    must not open a hole: the cell behind the wall stays hidden.
    """
    from combat.gate2_runtime_models import Position

    combat, table, mid = fight(tmp_path, [NOTE], cl=15, left_attack_bonus=100,
                               arena_edit=brittle_arena)
    engine = cold(combat, mid)
    actor = engine.state.actors[LEFT]
    assert engine._line_of_sight_actor_to_cell(actor, Position(x=8, y=6, z=0))
    assert not engine._line_of_sight_actor_to_cell(actor, Position(x=9, y=6, z=0))
    aimed = [c for c in engine.legal_candidates()
             if (engine.action_catalog.get(c.source_definition_id) is not None
                 and engine.action_catalog[c.source_definition_id].display_name == "Resonant Note: Deafen")
             and "object:map.1" in c.target_ids]
    assert len(aimed) == 1


def test_resonant_note_adds_proficiency_bonus_to_a_brittle_structure(tmp_path):
    combat, table, mid = fight(tmp_path, [NOTE], cl=15, left_attack_bonus=100,
                               arena_edit=brittle_arena)
    from combat.object_rules import has_tag

    # Isolate the brittle-structure clause: an unattended target would receive
    # the same bonus even if the structure/fragile group stopped working.
    target = cold(combat, mid).state.objects["object:map.1"]
    assert not has_tag(target, "unattended")
    assert has_tag(target, "structure")
    assert has_tag(target, "fragile")
    assert not has_tag(target, "barrier")
    settle(send_candidate(combat, table, mid, "Resonant Note: Deafen", target="object:map.1"))
    engine = cold(combat, mid)
    lost = 999 - engine.state.objects["object:map.1"].current_hp
    roll = damage_roll(engine)
    # The object path rolls its dice, then adds the Proficiency Bonus to the packet.
    assert lost == int(roll.total) + 4


def stone_arena(arena):
    open_arena(arena)
    # An attended stone wall section is a structure that is not fragile and
    # not unattended, so no printed clause of Resonant Note reaches it.
    arena["map_objects"] = [{"id": 1, "x": 8, "y": 6, "kind": "wall_section",
                             "name": "Stone wall", "material": "stone", "size": "large",
                             "hp": 999, "ac": 1, "unattended": False}]


def test_resonant_note_ordinary_structure_takes_no_proficiency_bonus(tmp_path):
    """... a *brittle* structure: an ordinary stone wall section is not brittle, so the bonus
    does not land on it (the printed word is enforced, not every structure)."""
    combat, table, mid = fight(tmp_path, [NOTE], cl=15, left_attack_bonus=100,
                               arena_edit=stone_arena)
    settle(send_candidate(combat, table, mid, "Resonant Note: Deafen", target="object:map.1"))
    engine = cold(combat, mid)
    lost = 999 - engine.state.objects["object:map.1"].current_hp
    roll = damage_roll(engine)
    assert lost == int(roll.total)


def test_resonant_note_barrier_group_matches_a_barrier_tag(tmp_path):
    """... or an ordinary barrier: the object_damage block's barrier group.  A destructible
    barrier the table itself made carries the barrier tag, so the same bonus lands on it."""
    from combat.ext.objects import _groups, _matches_group

    class Tags:
        def __init__(self, **keys):
            self._keys = keys

        def get(self, tag):
            return self._keys.get(tag)

        def __getitem__(self, tag):
            return self._keys[tag]

    class Fake:
        def __init__(self, component, unattended, object_kind):
            self.component, self.unattended = component, unattended
            self.object_kind = object_kind

    barrier = Fake(Tags(barrier=True, structure=False), False, "barrier")
    crate = Fake(Tags(barrier=False, structure=False), True, "crate")

    assert _matches_group(barrier, ["barrier"])
    assert not _matches_group(barrier, ["unattended"])
    assert not _matches_group(barrier, ["structure", "fragile"])
    assert _matches_group(crate, ["unattended"])
    assert not _matches_group(crate, ["barrier"])
    # The legacy flat list is ANY tag; a grouped entry requires ALL its tags.
    legacy = _groups({"add_pb_for": ["unattended", "barrier"]})
    assert any(_matches_group(barrier, group) for group in legacy)
    assert any(_matches_group(crate, group) for group in legacy)
    grouped = _groups({"add_pb_for_groups": [["unattended", "barrier"]]})
    assert not any(_matches_group(barrier, group) for group in grouped)
    assert not any(_matches_group(crate, group) for group in grouped)
