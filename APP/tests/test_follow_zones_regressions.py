"""Hunt 82 #1-#2 (lane MMX62): an aura or self-centred area stays with the creature that made it.

Hunt 82 found both defects at the table and this file keeps them fixed at the same level:

  * ``combat/ext/mounts.py`` put the rider (or the mount, or a creature carried along) on a new square and
    emitted the movement, but never reconciled the areas around it. Every other relocation in the app --
    ordinary movement in ``combat/typed_reactions.py``, a throw in ``combat/typed_executor.py``, and the
    plug-ins in ``combat/ext/`` that place a creature -- calls ``combat.zones.on_moved`` afterwards, so
    dismounting left the rider's aura standing on the square the rider had left.

  * ``combat/factory_compiler.py`` decided "moves with you" from narrow printed wording. Gravity Domain,
    Ink Domain and Aura of Unapproachable Elegance each print an area centred on its caster ("30-foot-radius
    aura centered on you", "the area within 5 feet of you") without the word "moves", so their areas were
    sealed into the table not following their owner. Each reviewed row now states the flag its printed text
    implies, and the compiler reads that flag, keeping the wording only as a last resort.

Movement regressions play a real fight through the tabletop, commit, reload from disk and replay.
The two authority/compiler checks separately pin the data that enables following.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.legacy_fight_support import legacy_zero_hp

pytestmark = pytest.mark.usefixtures("legacy_zero_hp")

from combat import zones
from combat.ext import mounts
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from tests import r1i_service_support as rider_support
from tests.h1_support import ROOT
from tests.hunt19_support import fight, reload
from tests.r1i_service_support import FOE, OWNER, SECOND
from tests.r10_fixup_support import fixed_dice
from tests.test_lock2_persistence import act

GRAVITY = "tianxia.talent.gravity.gravity_domain"
INK = "tianxia.talent.ink.ink_domain"
ELEGANCE = "tianxia.talent.beauty.aura_of_unapproachable_elegance"
RIDER_PACKAGE = "BEASTMASTERY_BASE_RIDER_PACKAGE"
RUN_DOWN = "TAL_BEASTMASTERY_RUN_DOWN"
WASTELAND = "tianxia.talent.ash.ashen_wasteland"
ASHFALL = "ASH_BASE_ASHFALL"
CRUSHING = "TAL_GRAVITY_CRUSHING_FIELD"
REVIEWED = Path(ROOT) / "authority" / "typed_mechanics" / "reviewed_final.d"

# The rider starts on its mount at this square (hunt19_support's regression yard, team1's first start).
START = (4, 4)

# ------------------------------------------------------------------ the mounted table the MMX64 regressions play
# One rider, its Warhorse, and a foe far out of the way.  Positions are the owner's because
# ``r1i_service_support.fixture`` takes them: the geometry is what these tests are about, so
# each one says where it puts the pair and why.
WIDE = {OWNER: {"x": 2, "y": 6}, FOE: {"x": 4, "y": 6}, SECOND: {"x": 17, "y": 12}}
SOUTH = {OWNER: {"x": 2, "y": 6}, FOE: {"x": 4, "y": 4}, SECOND: {"x": 17, "y": 12}}
NORTH = {OWNER: {"x": 2, "y": 11}, FOE: {"x": 4, "y": 11}, SECOND: {"x": 17, "y": 12}}


def mounted(tmp_path, owner_talents, *, positions, foe_talents=(), seed, wide=False):
    """A real fight whose owner rides a Warhorse, played through the tabletop."""
    combat, table, mid, _send, commit = rider_support.fixture(
        tmp_path, list(owner_talents) + [RIDER_PACKAGE], foe_talents=list(foe_talents),
        positions=positions, seed=seed, wide=wide)
    return combat, table, mid, commit


def turn_to(table, mid, commit, actor_id):
    """Hand the turn round until ``actor_id`` is the one choosing."""
    for _ in range(30):
        if table.state(mid)["menu"]["actor_id"] == actor_id:
            return
        assert commit(table.state(mid)["menu"]["end_turn"])["status"] == "COMMITTED"
    raise AssertionError(f"{actor_id} never got a turn")


def press(table, mid, label, *, target=None, at=None):
    """Choose the printed button, by its own words rather than a hard-coded id."""
    state = table.state(mid)
    menu = state["menu"]
    group = next(g for g in menu["actions"] if g["label"] == label)
    option = next(o for o in group["options"]
                  if (target is None or target in (o.get("target_ids") or []))
                  and (at is None or o.get("destination") == at))
    return table.act(mid, option["candidate_id"], menu["decision_id"], menu["state_version"],
                     state["last_sequence"], [])


def step(table, mid, x, y):
    """Walk the creature whose turn it is to one exact square."""
    state = table.state(mid)
    menu = state["menu"]
    move = next(m for m in menu["moves"] if m["destination"] == {"x": x, "y": y})
    return table.act(mid, move["candidate_id"], menu["decision_id"], menu["state_version"],
                     state["last_sequence"], [])


def pair(engine):
    """The owner and the mount it rides, as ``(rider, mount)`` from a reloaded fight."""
    rider = engine.state.actors[OWNER]
    return rider, mounts.mount_of(engine, rider)


def moments(engine, moment, target):
    """Every passive trigger of one kind that a named creature was the subject of."""
    return [e for e in engine.events if e.event_type == "PASSIVE_TRIGGERED"
            and e.payload.get("moment") == moment and target in (e.target_ids or ())]


def squares(cells):
    """Board squares as a set of plain ``(x, y)``, from tuples or from ``Position`` models alike."""
    return {(getattr(cell, "x", None) if hasattr(cell, "x") else cell[0],
             getattr(cell, "y", None) if hasattr(cell, "y") else cell[1]) for cell in cells}


def _owner(table, combat, mid):
    return combat._load_session(mid).engine.state.actors[table.state(mid)["menu"]["actor_id"]]


def _mine(engine, owner_id):
    """The owner's own area, the one the printed text says travels with it."""
    owned = [z for z in zones.typed_zones(engine) if z.owner_id == owner_id]
    assert owned, "the owner has no area on the table"
    return owned[0]


def _at(zone):
    return (zone.center.x, zone.center.y)


def _cast(table, mid, label):
    return send(table, mid, label)([])


def send(table, mid, label, *, target=None):
    state = table.state(mid)
    menu = state["menu"]
    group = next(g for g in menu["actions"] if g["label"] == label)
    option = next(o for o in group["options"] if target is None or o.get("target_ids") == [target])
    return lambda answers: table.act(mid, option["candidate_id"], menu["decision_id"], menu["state_version"],
                                    state["last_sequence"], answers)


def _walk(table, mid, goal):
    """Walk the creature whose turn it is as far along as the table offers toward ``goal``."""
    state = table.state(mid)
    menu = state["menu"]
    start = menu["moves"][0]["path"][0]
    move = min(menu["moves"],
               key=lambda m: (max(abs(m["destination"]["x"] - goal[0]), abs(m["destination"]["y"] - goal[1])),
                              -abs(m["destination"]["x"] - start["x"]) - abs(m["destination"]["y"] - start["y"])))
    table.act(mid, move["candidate_id"], menu["decision_id"], menu["state_version"], state["last_sequence"])
    return (move["destination"]["x"], move["destination"]["y"])


def _fresh(combat, tmp_path, mid):
    """Reload from disk: the fight state, and proof the fight still verifies and replays."""
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    assert session.mechanical.replay()["status"] == "PASS", "the fight still replays from its committed events"
    assert session.verify()["status"] == "PASS", "the reloaded fight still verifies"
    return session.engine


# -------------------------------------------------------------------------------------- #1 dismounting takes the areas along
def test_dismounting_recentres_the_riders_aura_on_the_square_the_rider_stepped_to(tmp_path):
    """A rider with an aura that prints "aura centered on you" dismounts: the aura ends up under the rider,
    not on the square they left. 5.5e "During your move, you can ... dismount" is ordinary movement."""
    combat, table, mid = fight(tmp_path, [RIDER_PACKAGE, GRAVITY])
    assert _cast(table, mid, "Gravity Domain")["status"] == "COMMITTED"

    engine = _fresh(combat, tmp_path, mid)
    owner = engine.state.actors[table.state(mid)["menu"]["actor_id"]]
    zone_id = _mine(engine, owner.entity_id).zone_id
    assert (owner.position.x, owner.position.y) == START
    assert _at(_mine(engine, owner.entity_id)) == START, "'aura centered on you': it starts centred on its owner"

    assert _cast(table, mid, "Dismount")["status"] == "COMMITTED", "the table offered a dismount"

    reloaded = _fresh(combat, tmp_path, mid)
    rider = reloaded.state.actors[owner.entity_id]
    zone = reloaded.state.zones[zone_id]
    stepped = (rider.position.x, rider.position.y)
    assert stepped != START, "dismounting really did move the rider"
    assert mounts.mount_of(reloaded, rider) is None, "and the rider really did dismount"
    assert _at(zone) == stepped, "the aura followed the rider down"
    assert _at(zone) != START, "and is no longer on the square it was cast on"
    assert zone.affected_cells, "and still covers its squares"


def test_aura_stays_put_when_a_different_creature_moves(tmp_path):
    """The other side of the same seam: an aura only travels for the creature that cast it, so a
    different creature walking across the board must leave it standing.  The previous version of this
    test ended the turn without moving anyone, which could not tell that apart (MMX64)."""
    combat, table, mid = fight(tmp_path, [RIDER_PACKAGE, GRAVITY])
    assert _cast(table, mid, "Gravity Domain")["status"] == "COMMITTED"
    engine = _fresh(combat, tmp_path, mid)
    owner_id = table.state(mid)["menu"]["actor_id"]
    zone_id = _mine(engine, owner_id).zone_id

    # A different creature, on its own turn, really walks.
    while table.state(mid)["menu"]["actor_id"] == owner_id:
        assert act(table, mid, "end")["status"] == "COMMITTED"
    assert table.state(mid)["menu"]["actor_id"] != owner_id
    stranger_walked = _walk(table, mid, (11, 7))

    reloaded = _fresh(combat, tmp_path, mid)
    stranger = reloaded.state.actors[table.state(mid)["menu"]["actor_id"]]
    assert (stranger.position.x, stranger.position.y) == stranger_walked, "the other creature really moved"
    assert (stranger.position.x, stranger.position.y) != START, "and it moved off the aura's square too"
    assert _at(reloaded.state.zones[zone_id]) == START, "an aura that follows its owner only moves when its owner does"


# -------------------------------------------------------------------------------------- #2 the areas state that they follow
def _label_for(table, mid, talent):
    """The button the table prints for this ability, so the test never hard-codes a display name."""
    stem = talent.rsplit(".", 1)[-1].replace("_", " ")
    return next(g["label"] for g in table.state(mid)["menu"]["actions"]
                if stem.split()[-1].title() in g["label"] or stem.title() in g["label"])


def _follows_after_walking(tmp_path, talent):
    """Cast the area, walk, and report where the area ended up relative to its owner."""
    combat, table, mid = fight(tmp_path, [talent])
    label = _label_for(table, mid, talent)
    assert _cast(table, mid, label)["status"] == "COMMITTED", f"{label} did not cast"
    engine = _fresh(combat, tmp_path, mid)
    owner_id = table.state(mid)["menu"]["actor_id"]
    zone = _mine(engine, owner_id)
    assert zones.moves_with_owner(zone), "the compiled area says it moves with its owner"
    assert _at(zone) == START, "and it is centred on its owner to begin with"

    assert act(table, mid, "end")["status"] == "COMMITTED", "end the casting turn"
    state = table.state(mid)
    while state["menu"]["actor_id"] != owner_id:
        assert act(table, mid, "end")["status"] == "COMMITTED"
        state = table.state(mid)
    walked = _walk(table, mid, (9, 4))
    reloaded = _fresh(combat, tmp_path, mid)
    return reloaded, owner_id, zone.zone_id, walked


def test_gravity_domain_area_follows_its_owner_when_they_walk(tmp_path):
    """"Area: 30-foot-radius aura centered on you." An area centred on its caster travels with it."""
    engine, owner_id, zone_id, walked = _follows_after_walking(tmp_path, GRAVITY)
    zone = engine.state.zones[zone_id]
    owner = engine.state.actors[owner_id]
    assert (owner.position.x, owner.position.y) == walked, "the owner really walked"
    assert _at(zone) == walked, "the Domain followed its owner"
    assert _at(zone) != START, "and is no longer on the square it was cast on"
    assert zone.affected_cells, "and still covers its squares"


def test_ink_domain_area_follows_its_owner_when_they_walk(tmp_path):
    """Ink Domain states its printed area ("30-foot-radius aura centered on you") without a zone effect of
    its own, so the flag has to be readable from the area itself."""
    engine, owner_id, zone_id, walked = _follows_after_walking(tmp_path, INK)
    zone = engine.state.zones[zone_id]
    assert (engine.state.actors[owner_id].position.x, engine.state.actors[owner_id].position.y) == walked
    assert _at(zone) == walked, "the Ink Domain followed its owner"
    assert _at(zone) != START, "and is no longer on the square it was cast on"
    assert zone.affected_cells


def test_aura_of_unapproachable_elegance_follows_its_owner_when_they_walk(tmp_path):
    """"creatures bearing your Beauty Mark treat the area within 5 feet of you as difficult terrain": an
    area measured from its caster is centred on that caster."""
    engine, owner_id, zone_id, walked = _follows_after_walking(tmp_path, ELEGANCE)
    zone = engine.state.zones[zone_id]
    assert (engine.state.actors[owner_id].position.x, engine.state.actors[owner_id].position.y) == walked
    assert _at(zone) == walked, "the aura followed its owner"
    assert _at(zone) != START, "and is no longer on the square it was cast on"
    assert zone.affected_cells


def test_the_ground_an_aura_covers_moves_with_its_owner(tmp_path):
    """The point of an aura that follows: the ground it covers travels with its caster, so the squares it
    helps stop being the squares it helped. Without the fix the area is still standing on the square it was
    cast on, helping a place its owner walked away from."""
    combat, table, mid = fight(tmp_path, [GRAVITY])
    assert _cast(table, mid, "Gravity Domain")["status"] == "COMMITTED"
    engine = _fresh(combat, tmp_path, mid)
    owner_id = table.state(mid)["menu"]["actor_id"]
    zone = _mine(engine, owner_id)
    zone_id = zone.zone_id
    cast_cells = {(c.x, c.y) for c in zone.affected_cells}
    assert START in cast_cells, "the owner starts inside their own aura"

    assert act(table, mid, "end")["status"] == "COMMITTED"
    state = table.state(mid)
    while state["menu"]["actor_id"] != owner_id:
        assert act(table, mid, "end")["status"] == "COMMITTED"
        state = table.state(mid)
    walked = _walk(table, mid, (11, 4))

    reloaded = _fresh(combat, tmp_path, mid)
    moved = reloaded.state.zones[zone_id]
    owner = reloaded.state.actors[owner_id]
    walked_cells = {(c.x, c.y) for c in moved.affected_cells}
    assert (owner.position.x, owner.position.y) == walked, "the owner really walked"
    assert walked != START, "and left the square it cast on"
    assert walked_cells != cast_cells, "the ground the aura covers moved with its owner"
    assert (owner.position.x, owner.position.y) in walked_cells, "the owner is still inside their own aura"


# -------------------------------------------------------------------------------------- the data says so, not the wording
def test_each_reviewed_row_states_in_data_that_its_area_follows_its_owner():
    """The printed text is the source, and the row carries it. Without these the compiler can only guess
    from wording, which is what left the three areas stuck."""
    rows = {
        "gravity_canvas.json": (GRAVITY, "zone"),
        "review_sw-imbuement.json": (INK, "area"),
        "riders_lane3.json": (ELEGANCE, "zone"),
    }
    for filename, (mid, where) in rows.items():
        reviewed = json.loads((REVIEWED / filename).read_text())["mechanics"][mid]
        if where == "zone":
            stated = [e for e in reviewed["effects"] if e.get("type") == "zone"]
            assert stated and all(e.get("follows_owner") is True for e in stated), f"{mid} states no follow flag"
        else:
            assert reviewed["area"].get("follows_owner") is True, f"{mid}'s area states no follow flag"


def test_the_compiler_reads_that_flag_instead_of_guessing_from_wording():
    """All three compile to an area that follows, from the flag alone."""
    from tests.h1_support import sheet

    for mid, path, primary in ((GRAVITY, "Gravity", "Chi"), (INK, "Imbuement", "Resonance"),
                               (ELEGANCE, "Beauty", "Charm")):
        doc = sheet([mid], cl=12, primary=primary, score=18)
        doc["identity"]["path"] = path
        bundle = compile_character(doc, actor_id="actor:probe")
        specs = [(a.get("parameters") or {}).get("typed", {}).get("zone_spec")
                 for a in bundle["action_catalog"]]
        specs = [s for s in specs if isinstance(s, dict)]
        assert specs, f"{mid} compiled no area"
        assert any(s.get("follows_owner") is True for s in specs), f"{mid}'s area does not follow its owner"
        assert any(s.get("centered_on_self") is True for s in specs), f"{mid}'s area is not centred on its owner"


# -------------------------------------------------------------------------------------- the plug-in stays inert
def test_a_character_with_none_of_these_areas_is_still_relocated_by_the_mount_rules(tmp_path):
    """Nothing in ``mounts._move``'s new call keys on who moved: a fighter with none of the three
    abilities is moved by exactly the same code, commits, reloads, and owns no area for the call to
    do anything with.  The previous version of this test only built an engine and read its starting
    zones, never running the patched relocation (MMX64)."""
    combat, table, mid, commit = mounted(tmp_path, [], positions=WIDE, seed="MMX64-INERT")
    engine = _fresh(combat, tmp_path, mid)
    rider, mount = pair(engine)
    start = (rider.position.x, rider.position.y)
    assert mount is not None, "the fighter starts in the saddle"
    assert not [z for z in zones.typed_zones(engine) if z.owner_id == OWNER], \
        "a fighter with none of these abilities owns no area"

    assert press(table, mid, "Dismount")["status"] == "COMMITTED", "the table offered a dismount"

    reloaded = _fresh(combat, tmp_path, mid)
    rider, mount = pair(reloaded)
    stepped = (rider.position.x, rider.position.y)
    assert stepped != start, "the relocation the mount rules make really happened"
    assert mount is None, "and the fighter really did get off the mount"
    assert not [z for z in zones.typed_zones(reloaded) if z.owner_id == OWNER], \
        "and still owns no area, so the new call had nothing to reconcile"


# ================================================================================ MMX64 (pre-merge review of 2939c051..c272540b)
# The review found that the hunt-82 fix covered the one function the mount rules relocate through but
# not the second one: Brute Overrun moved the mount and the rider by hand, emitting the movement and
# stopping there, so both of them left their Domains and Elegance standing on the square they charged
# off.  It also found the two places where the fix trusts a default: ``_move`` calls ``on_moved`` with
# ``forced=True`` unless a caller says otherwise, and the two willing steps -- mounting and dismounting,
# which the printed rules call ordinary movement -- said nothing, so a creature could step off its mount
# to dodge a named terrain's "moving more than 10 feet through" save.  The tests below play both at the
# table, commit, reload from disk, and re-verify.

def _zone_of(engine, owner, seen=()):
    """The one area ``owner`` owns that is not in ``seen`` -- so a foe who has laid down two is still
    told apart by the test that laid them down."""
    fresh = [z for z in zones.typed_zones(engine) if z.owner_id == owner and z.zone_id not in seen]
    assert len(fresh) == 1, f"expected one new area from {owner}, found {len(fresh)}"
    return fresh[0]


def test_an_accepted_overrun_takes_the_riders_area_with_the_pair(tmp_path, monkeypatch):
    """Brute Overrun moves two creatures: the mount passes through the target and the rider is carried
    over with it.  Both of them have to reconcile what is centred on them, or the pair ends the turn
    standing in a place their own Domain is not."""
    combat, table, mid, commit = mounted(tmp_path, [GRAVITY, RUN_DOWN], positions=WIDE, seed="MMX64-OVERRUN-AURA")
    assert press(table, mid, "Gravity Domain")["status"] == "COMMITTED"
    before = _fresh(combat, tmp_path, mid)
    rider, mount = pair(before)
    zone_id = _zone_of(before, OWNER).zone_id
    assert _at(before.state.zones[zone_id]) == (rider.position.x, rider.position.y), "it starts centred on its caster"

    turn_to(table, mid, commit, OWNER)
    fixed_dice(monkeypatch, [19, 1])  # the mount's Athletics against the target's
    assert press(table, mid, "Mount: Overrun (Action)", target=FOE)["status"] == "COMMITTED"

    reloaded = _fresh(combat, tmp_path, mid)
    rider, mount = pair(reloaded)
    zone = reloaded.state.zones[zone_id]
    assert mount is not None, "the pair is still together"
    assert rider.turn_flags.get("mount_overrun_target") == FOE, "the Overrun was won"
    charged = (rider.position.x, rider.position.y)
    assert charged != (2, 6), "the rider really was carried over the target"
    assert (mount.position.x, mount.position.y) != (2, 6), "and so was the mount"
    assert _at(zone) == charged, "the rider's Domain came with the rider"
    assert _at(zone) != (2, 6), "and is no longer on the square they charged off"
    assert zone.affected_cells, "and still covers its ground"


def test_the_mount_that_overruns_is_reconciled_too(tmp_path, monkeypatch):
    """The other mover in the same Overrun.  A mount is a creature like any other: it enters the ground
    it charges through, and a hostile area that fires on entry fires for it as well.  This is the half
    that was still going straight to the event, so nothing about the mount's new square was reconciled."""
    combat, table, mid, commit = mounted(tmp_path, [RUN_DOWN], positions=NORTH,
                                         foe_talents=[WASTELAND], seed="MMX64-OVERRUN-MOUNT")
    turn_to(table, mid, commit, FOE)
    # Ground the pair does not start in, laid across the square they end on: the mount's 2x2 body
    # stands outside the area at (2, 11) and inside it at the far end of the charge.
    assert press(table, mid, "Ashen Wasteland", at={"x": 5, "y": 6})["status"] == "COMMITTED"
    before = _fresh(combat, tmp_path, mid)
    rider, mount = pair(before)
    wasteland = _zone_of(before, FOE)
    assert not squares(before._actor_cells(mount)) & squares(wasteland.affected_cells), \
        "the mount starts clear of the hostile ground"

    turn_to(table, mid, commit, OWNER)
    fixed_dice(monkeypatch, [19, 1])
    assert press(table, mid, "Mount: Overrun (Action)", target=FOE)["status"] == "COMMITTED"

    reloaded = _fresh(combat, tmp_path, mid)
    rider, mount = pair(reloaded)
    assert mount is not None, "the pair is still together"
    assert (mount.position.x, mount.position.y) != (2, 11), "the mount really was moved"
    assert squares(reloaded._actor_cells(mount)) & squares(_zone_of(reloaded, FOE).affected_cells), \
        "and it ended standing in the ground it charged through"
    assert moments(reloaded, "enter", mount.entity_id), \
        "so the area's entry save fired for the mount, which only happens if the mount's move was reconciled"


def test_overrun_prone_entry_throws_the_rider_from_the_new_square(tmp_path, monkeypatch):
    """Crushing Field knocks the charging mount Prone; the rider fails its real fall save.

    Both charge events must precede entry, and the landing must survive commit/reload rather
    than being overwritten by the second half of the charge.
    """
    combat, table, mid, commit = mounted(tmp_path, [RUN_DOWN], positions=NORTH,
                                       foe_talents=[CRUSHING], seed="SOL87-OVERRUN-PRONE")
    turn_to(table, mid, commit, FOE)
    assert press(table, mid, "Crushing Field", at={"x": 6, "y": 8})["status"] == "COMMITTED"
    before = _fresh(combat, tmp_path, mid)
    rider, mount = pair(before)
    mount_id = mount.entity_id
    field = _zone_of(before, FOE)
    assert not squares(before._actor_cells(mount)) & squares(field.affected_cells)
    turn_to(table, mid, commit, OWNER)
    fixed_dice(monkeypatch, [19, 1] + [1] * 40)
    assert press(table, mid, "Mount: Overrun (Action)", target=FOE)["status"] == "COMMITTED"

    reloaded = _fresh(combat, tmp_path, mid)
    rider = reloaded.state.actors[OWNER]
    mount = reloaded.state.actors[mount_id]
    assert mount.active and rider.active
    assert any(c.condition_id == mounts.PRONE for c in mount.conditions.values())
    assert mounts.mount_of(reloaded, rider) is None
    assert any(c.condition_id == mounts.PRONE for c in rider.conditions.values())
    charges = [e for e in reloaded.events if e.event_type == "MOVEMENT_COMMITTED" and e.payload.get("overrun")]
    entries = moments(reloaded, "enter", mount_id)
    assert len(charges) == 2 and entries
    assert max(e.sequence for e in charges) < entries[0].sequence
    assert len(moments(reloaded, "enter", OWNER)) == 1, "the rider enters once even when its fall stays inside"
    falls = [e for e in reloaded.events if e.event_type == "MOVEMENT_COMMITTED"
             and e.actor_id == OWNER and e.payload.get("thrown_from") == mount_id]
    assert len(falls) == 1 and falls[0].sequence > entries[0].sequence
    assert rider.position.model_dump(mode="json") == falls[0].payload["destination"]
    assert falls[0].payload["path"][0] == next(e for e in charges if e.actor_id == OWNER).payload["destination"]
    assert not squares(reloaded._actor_cells(rider)) & squares(reloaded._actor_cells(mount))
    assert not rider.turn_flags.get("mount_overrun_target"), "a broken bond cannot enable the mounted follow-up"


def test_crushing_field_cannot_be_placed_inside_the_arena_pillar(tmp_path):
    """Keep casting legality separate from the clear-yard charge regressions."""
    combat, table, mid, commit = mounted(tmp_path, [RUN_DOWN], positions=NORTH,
                                       foe_talents=[CRUSHING], seed="SOL148-PILLAR-ORIGIN")
    turn_to(table, mid, commit, FOE)
    assert (6, 10) in combat._load_session(mid).engine.grid.blocked
    group = next(g for g in table.state(mid)["menu"]["actions"] if g["label"] == "Crushing Field")
    destinations = [option.get("destination") for option in group["options"]]
    assert {"x": 6, "y": 10} not in destinations, "a stone pillar blocks the field's origin"
    assert {"x": 4, "y": 10} in destinations, "a nearby clear origin remains available"


def test_overrun_entry_still_hits_a_rider_thrown_outside_the_field(tmp_path, monkeypatch):
    """The charge enters Crushing Field even when its entry effect throws the rider clear."""
    # The field origin (6, 10) is a stone pillar in the default arena. Use the
    # clear yard: this regression tests deferred entry, not casting into a wall.
    combat, table, mid, commit = mounted(tmp_path, [RUN_DOWN], positions=NORTH,
                                       foe_talents=[CRUSHING], seed="SOL97-OUTSIDE-LANDING", wide=True)
    turn_to(table, mid, commit, FOE)
    assert (6, 10) not in combat._load_session(mid).engine.grid.blocked
    assert press(table, mid, "Crushing Field", at={"x": 6, "y": 10})["status"] == "COMMITTED"
    turn_to(table, mid, commit, OWNER)
    before = _fresh(combat, tmp_path, mid)
    rider, mount = pair(before)
    mount_id, hp = mount.entity_id, rider.current_hp
    cells = squares(_zone_of(before, FOE).affected_cells)
    assert (rider.position.x, rider.position.y) not in cells
    fixed_dice(monkeypatch, [19, 1] + [1] * 40)
    assert press(table, mid, "Mount: Overrun (Action)", target=FOE)["status"] == "COMMITTED"

    reloaded = _fresh(combat, tmp_path, mid)
    rider = reloaded.state.actors[OWNER]
    charge = next(e for e in reloaded.events if e.event_type == "MOVEMENT_COMMITTED"
                  and e.actor_id == OWNER and e.payload.get("overrun"))
    fall = next(e for e in reloaded.events if e.event_type == "MOVEMENT_COMMITTED"
                and e.actor_id == OWNER and e.payload.get("thrown_from") == mount_id)
    assert tuple(charge.payload["destination"][k] for k in ("x", "y")) in cells
    assert tuple(fall.payload["destination"][k] for k in ("x", "y")) not in cells
    assert fall.payload["path"][0] == charge.payload["destination"]
    assert rider.position.model_dump(mode="json") == fall.payload["destination"]
    assert charge.payload["forced"] is False and charge.payload["carried_by"] == mount_id
    assert fall.payload["forced"] is True
    assert mounts.mount_of(reloaded, rider) is None
    assert len(moments(reloaded, "enter", OWNER)) == 1, "the recorded charge still enters exactly once"
    assert rider.current_hp < hp, "the outside landing cannot erase the charge's entry damage"
    assert any(c.condition_id == mounts.PRONE for c in rider.conditions.values())
    assert not rider.turn_flags.get("mount_overrun_target")


@pytest.mark.parametrize("ash_at,charge_ft,total_ft", [
    ({"x": 3, "y": 12}, 10, 15),
    ({"x": 0, "y": 13}, 5, 10),
], ids=["whole-charge", "partial-charge"])
def test_interrupted_overrun_does_not_invent_willing_ash_terrain_distance(
        tmp_path, monkeypatch, ash_at, charge_ft, total_ft):
    """Count the five-foot walk and actual voluntary charge, never the forced landing.

    Ash requires more than ten feet: the whole charge crosses that threshold, while
    the partially covered route ends exactly at ten. Both survive commit/reload/replay.
    """
    positions = {OWNER: {"x": 2, "y": 11}, FOE: {"x": 4, "y": 12}, SECOND: {"x": 11, "y": 12}}
    combat, table, mid, _send, commit = rider_support.fixture(
        tmp_path, [RUN_DOWN, RIDER_PACKAGE], foe_talents=[CRUSHING], second_talents=[ASHFALL],
        positions=positions, seed="SOL97-TERRAIN-DISTANCE", wide=True)
    turn_to(table, mid, commit, FOE)
    # Keep the exact charge/ash geometry without the default arena's pillar at
    # the chosen field origin. A solid obstacle correctly blocks this cast.
    assert (6, 10) not in combat._load_session(mid).engine.grid.blocked
    assert press(table, mid, "Crushing Field", at={"x": 6, "y": 10})["status"] == "COMMITTED"
    turn_to(table, mid, commit, SECOND)
    assert press(table, mid, "Ashfall", at=ash_at)["status"] == "COMMITTED"
    turn_to(table, mid, commit, OWNER)
    before = _fresh(combat, tmp_path, mid)
    mount_id = pair(before)[1].entity_id
    ash_cells = squares(_zone_of(before, SECOND).affected_cells)
    assert (2, 11) in ash_cells and (2, 12) in ash_cells
    assert step(table, mid, 2, 12)["status"] == "COMMITTED"
    walked = _fresh(combat, tmp_path, mid)
    walk = next(e for e in reversed(walked.events)
                if e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == OWNER)
    assert walk.payload["path"] == [{"x": 2, "y": 11}, {"x": 2, "y": 12}]
    assert not walk.payload.get("forced") and not walk.payload.get("carried_by")
    assert walked.grid.distance_ft((2, 11), (2, 12)) == 5
    assert not moments(walked, "move_through", OWNER)
    sequence = walked.events[-1].sequence
    fixed_dice(monkeypatch, [19, 1] + [1] * 40)
    assert press(table, mid, "Mount: Overrun (Action)", target=FOE)["status"] == "COMMITTED"

    reloaded = _fresh(combat, tmp_path, mid)
    rider = reloaded.state.actors[OWNER]
    moves = [e for e in reloaded.events if e.event_type == "MOVEMENT_COMMITTED"
             and e.actor_id == OWNER and e.sequence > sequence]
    assert len(moves) == 2
    charge, fall = moves
    assert charge.payload.get("overrun") and charge.payload["carried_by"] == mount_id
    assert charge.payload["forced"] is False
    assert charge.payload["path"] == [
        {"x": 2, "y": 12}, {"x": 3, "y": 11}, {"x": 4, "y": 10}]
    assert fall.payload.get("thrown_from") == mount_id and fall.payload["forced"] is True
    assert fall.payload["path"][0] == charge.payload["destination"]
    assert rider.position.model_dump(mode="json") == fall.payload["destination"]
    assert reloaded.grid.distance_ft((2, 12), rider.position) > 5
    assert mounts.mount_of(reloaded, rider) is None
    path = charge.payload["path"]
    recorded_charge_ft = sum(reloaded.grid.distance_ft((a["x"], a["y"]), (b["x"], b["y"]))
                             for a, b in zip(path, path[1:])
                             if (a["x"], a["y"]) in ash_cells or (b["x"], b["y"]) in ash_cells)
    assert recorded_charge_ft == charge_ft
    from combat.gate2_runtime_models import Position
    segment = (Position(**path[0]), Position(**path[-1]))
    distance, intersects = zones._movement_distance_through_zone(
        reloaded, rider, _zone_of(reloaded, SECOND), fallback_path=segment)
    assert intersects and distance == total_ft, "walk + voluntary carried charge; forced fall adds zero"
    assert len(moments(reloaded, "move_through", OWNER)) == (1 if total_ft > 10 else 0)
    assert len(moments(reloaded, "enter", OWNER)) == 1, "the separate charge entry still resolves"


def test_forced_fall_from_outside_fires_the_hostile_zone_entry(tmp_path, monkeypatch):
    """A fall is forced, but entering Crushing Field still deals damage and knocks Prone."""
    from tests.test_tabletop_hunt6 import HOLD, on_hold

    combat, table, mid, commit = mounted(tmp_path, [], positions=SOUTH,
                                       foe_talents=[CRUSHING], seed="SOL87-FORCED-ENTRY")
    turn_to(table, mid, commit, FOE)
    assert press(table, mid, "Crushing Field", at={"x": 1, "y": 2})["status"] == "COMMITTED"
    turn_to(table, mid, commit, OWNER)
    before = _fresh(combat, tmp_path, mid)
    rider, mount = pair(before)
    mount_id = mount.entity_id
    field_id = _zone_of(before, FOE).zone_id
    assert not squares(before._actor_cells(rider)) & squares(before.state.zones[field_id].affected_cells)
    hp = rider.current_hp

    def knock_prone(engine):
        engine._apply_condition(engine.state.actors[mount_id], mounts.PRONE, "test:prone",
                                FOE, expires_on="STAND_UP")

    on_hold(monkeypatch, knock_prone)
    fixed_dice(monkeypatch, [1] * 40)
    assert act(table, mid, HOLD)["status"] == "COMMITTED"
    reloaded = _fresh(combat, tmp_path, mid)
    rider = reloaded.state.actors[OWNER]
    falls = [e for e in reloaded.events if e.event_type == "MOVEMENT_COMMITTED"
             and e.actor_id == OWNER and e.payload.get("thrown_from") == mount_id]
    assert len(falls) == 1 and falls[0].payload["forced"] is True
    assert squares(reloaded._actor_cells(rider)) & squares(reloaded.state.zones[field_id].affected_cells)
    assert mounts.mount_of(reloaded, rider) is None
    assert rider.current_hp < hp
    entries = moments(reloaded, "enter", OWNER)
    assert entries and entries[-1].sequence > falls[0].sequence
    assert any(c.condition_id == mounts.PRONE for c in rider.conditions.values())


@pytest.mark.parametrize("participant", ["mount", "rider"])
def test_overrun_entry_defeat_cannot_carry_or_enable_a_mounted_followup(tmp_path, monkeypatch, participant):
    """Entry damage can defeat either participant; charge geometry and bond cleanup still replay."""
    from tests.test_tabletop_hunt6 import HOLD, on_hold

    combat, table, mid, commit = mounted(tmp_path, [RUN_DOWN], positions=NORTH,
                                       foe_talents=[CRUSHING], seed=f"SOL87-ENTRY-DEFEAT-{participant}")
    mount_id = pair(_fresh(combat, tmp_path, mid))[1].entity_id
    victim_id = mount_id if participant == "mount" else OWNER

    def weaken(engine):
        victim = engine.state.actors[victim_id]
        engine._commit_damage(victim, victim.current_hp - 1, "force", "test:weaken", FOE,
                              None, reaction_depth=0)

    on_hold(monkeypatch, weaken)
    assert act(table, mid, HOLD)["status"] == "COMMITTED"
    assert _fresh(combat, tmp_path, mid).state.actors[victim_id].current_hp == 1
    turn_to(table, mid, commit, FOE)
    assert press(table, mid, "Crushing Field", at={"x": 6, "y": 8})["status"] == "COMMITTED"
    turn_to(table, mid, commit, OWNER)
    fixed_dice(monkeypatch, [19, 1] + [1] * 40)
    assert press(table, mid, "Mount: Overrun (Action)", target=FOE)["status"] == "COMMITTED"

    reloaded = _fresh(combat, tmp_path, mid)
    rider = reloaded.state.actors[OWNER]
    assert not reloaded.state.actors[victim_id].active
    assert mounts.mount_of(reloaded, rider) is None
    assert not rider.turn_flags.get("mount_overrun_target")
    charges = [e for e in reloaded.events if e.event_type == "MOVEMENT_COMMITTED" and e.payload.get("overrun")]
    assert len(charges) == 2
    defeated = [e for e in reloaded.events if e.event_type == "ENTITY_DEFEATED" and e.actor_id == victim_id]
    assert defeated and max(e.sequence for e in charges) < defeated[-1].sequence
    assert moments(reloaded, "enter", OWNER), "the rider's actual charge or landing still enters the field"


def test_walking_then_willingly_dismounting_past_the_mark_asks_the_terrain_save(tmp_path):
    """Ash Terrain: "moving more than 10 feet through" it makes a Constitution save, and the distance
    is read from the walk the creature chose.  Ten feet of walking plus the five feet of a dismount is
    more than ten, so the save is asked -- which it was not while a dismount was filed as forced
    movement (MMX64).  "During your move, you can ... dismount" is ordinary movement."""
    combat, table, mid, commit = mounted(tmp_path, [], positions=SOUTH,
                                         foe_talents=[ASHFALL], seed="MMX64-DISMOUNT-THRESHOLD")
    turn_to(table, mid, commit, FOE)
    assert press(table, mid, "Ashfall", at={"x": 6, "y": 6})["status"] == "COMMITTED"

    turn_to(table, mid, commit, OWNER)
    assert step(table, mid, 3, 6)["status"] == "COMMITTED"
    assert step(table, mid, 4, 6)["status"] == "COMMITTED"
    walked = _fresh(combat, tmp_path, mid)
    assert not moments(walked, "move_through", OWNER), "ten feet of walking is not more than ten feet"
    assert press(table, mid, "Dismount")["status"] == "COMMITTED"

    reloaded = _fresh(combat, tmp_path, mid)
    rider, mount = pair(reloaded)
    assert mount is None, "the rider really did dismount"
    dismounted = [e for e in reloaded.events
                  if e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == OWNER
                  and e.payload.get("dismounting") and e.sequence > 0]
    assert dismounted, "the dismount is on the record"
    saves = moments(reloaded, "move_through", OWNER)
    assert saves, "fifteen feet through Ash Terrain asks the save"
    assert all(s.sequence > dismounted[-1].sequence for s in saves), \
        "and it is the dismount's own five feet that carried the day past the mark"


def test_a_willing_dismount_short_of_the_mark_does_not_ask_the_save(tmp_path):
    """The other side of that threshold, so the test above is about the mark and not about dismounting:
    five feet of walking plus five feet of dismounting is ten feet, and ten is not *more than* ten."""
    combat, table, mid, commit = mounted(tmp_path, [], positions=SOUTH,
                                         foe_talents=[ASHFALL], seed="MMX64-DISMOUNT-UNDER")
    turn_to(table, mid, commit, FOE)
    assert press(table, mid, "Ashfall", at={"x": 6, "y": 6})["status"] == "COMMITTED"

    turn_to(table, mid, commit, OWNER)
    assert step(table, mid, 3, 6)["status"] == "COMMITTED"
    assert press(table, mid, "Dismount")["status"] == "COMMITTED"

    reloaded = _fresh(combat, tmp_path, mid)
    rider, mount = pair(reloaded)
    assert mount is None, "the rider really did dismount"
    assert not moments(reloaded, "move_through", OWNER), "ten feet through Ash Terrain is not more than ten"


def test_willingly_mounting_past_the_mark_asks_the_terrain_save(tmp_path):
    """The same mark, reached the other way round, for the other willing step.  Five feet of walking
    plus the five feet of a dismount is ten feet and asks nothing; stepping back into the saddle is a
    fifth foot of movement the rider chose, which carries the day past ten.  Mounting is "During your
    move, you can mount a creature that is within 5 feet of you" -- ordinary movement (MMX64)."""
    combat, table, mid, commit = mounted(tmp_path, [], positions=SOUTH,
                                         foe_talents=[ASHFALL], seed="MMX64-MOUNT-THRESHOLD")
    turn_to(table, mid, commit, FOE)
    assert press(table, mid, "Ashfall", at={"x": 6, "y": 6})["status"] == "COMMITTED"

    turn_to(table, mid, commit, OWNER)
    mount_id = pair(_fresh(combat, tmp_path, mid))[1].entity_id  # it is still in the saddle here
    assert step(table, mid, 3, 6)["status"] == "COMMITTED"
    assert press(table, mid, "Dismount")["status"] == "COMMITTED"
    ridden = _fresh(combat, tmp_path, mid)
    rider = ridden.state.actors[OWNER]
    assert mounts.mount_of(ridden, rider) is None, "the rider is on foot"
    assert not moments(ridden, "move_through", OWNER), "ten feet through Ash Terrain is not more than ten"

    assert press(table, mid, "Mount", target=mount_id)["status"] == "COMMITTED", "the rider mounts again"

    reloaded = _fresh(combat, tmp_path, mid)
    rider = reloaded.state.actors[OWNER]
    mount = reloaded.state.actors[mount_id]
    assert mounts.mount_of(reloaded, rider) is mount, "the rider is back in the saddle"
    assert rider.position == mount.position, "and the pair shares one square again"
    assert moments(reloaded, "move_through", OWNER), \
        "so the fifteen feet of willing movement through Ash Terrain asked the save"


def test_a_rider_thrown_off_a_prone_mount_lands_in_terrain_without_being_offered_the_save(tmp_path, monkeypatch):
    """The other half of the printed line, and the twin of the dismount test above.  Ash Terrain asks
    its save for movement "more than 10 feet through" that the creature chose.  A rider walks ten feet
    through it and is then thrown off a mount knocked Prone: the fall is five more feet of the same
    turn, into the same ground, and it is not movement the rider chose, so it does not carry the day
    past the mark and the save is not offered.  File that fall as willing and the test fails, which is
    the point: being pushed or pulled in still enters the ground you land in, but the moving-through
    save is for movement the creature chose.

    The mount is knocked Prone inside a committed table action, the way the existing mount regressions
    set up the conditions they need, so the throw is the mount rules' own reaction."""
    from tests.test_tabletop_hunt6 import HOLD, on_hold

    combat, table, mid, commit = mounted(tmp_path, [], positions=SOUTH,
                                         foe_talents=[ASHFALL], seed="MMX64-FORCED-THROUGH")
    turn_to(table, mid, commit, FOE)
    # Laid so the ground the rider walks into and the square it is thrown onto are both inside it.
    assert press(table, mid, "Ashfall", at={"x": 5, "y": 5})["status"] == "COMMITTED"
    ashfall_id = _zone_of(_fresh(combat, tmp_path, mid), FOE).zone_id

    turn_to(table, mid, commit, OWNER)
    mount_id = pair(_fresh(combat, tmp_path, mid))[1].entity_id
    assert step(table, mid, 3, 6)["status"] == "COMMITTED"
    assert step(table, mid, 4, 6)["status"] == "COMMITTED"
    walked = _fresh(combat, tmp_path, mid)
    assert not moments(walked, "move_through", OWNER), "ten feet of walking is not more than ten feet"

    def knock_prone(engine):
        engine._apply_condition(engine.state.actors[mount_id], mounts.PRONE, "test:prone",
                                engine.state.actors[FOE].entity_id, expires_on="STAND_UP")

    on_hold(monkeypatch, knock_prone)
    fixed_dice(monkeypatch, [1])  # the rider fails the DC 10 Dexterity save to stay in the saddle
    assert act(table, mid, HOLD)["status"] == "COMMITTED"

    reloaded = _fresh(combat, tmp_path, mid)
    rider = reloaded.state.actors[OWNER]
    assert reloaded.state.actors[mount_id].active, "the mount is still there"
    assert mounts.mount_of(reloaded, rider) is None, "the rider was thrown out of the saddle"
    falls = [e for e in reloaded.events if e.event_type == "MOVEMENT_COMMITTED"
             and e.actor_id == OWNER and e.payload.get("thrown_from")]
    assert falls, "the fall is on the record"
    assert falls[-1].payload.get("forced") is True, "and filed as the forced movement it is"
    assert squares(reloaded._actor_cells(rider)) & squares(reloaded.state.zones[ashfall_id].affected_cells), \
        "it landed inside the named terrain, which forced movement does reach"
    assert not moments(reloaded, "move_through", OWNER), \
        "but a forced step is not offered the moving-through save, which is for willing movement"
