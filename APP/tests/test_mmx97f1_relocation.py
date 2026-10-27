"""MMX97f1: review fixes for MMX97 (independent review of 42e43e14..ce0c2e01, MERGE AFTER FIXES).

The review raised three findings against MMX97's ``_ride_damage_branch`` seam:

1. P1 -- the helper collected *every* top-level damage row after attachment, not just the modifier's
   own, so composing an action with an eligible modifier could relocate the BASE ability's own rows.
   Star-Sundering Cut carries a top-level ``8d6 + Cultivation Level`` self-cost next to a line save
   whose target damage sits in ``on_fail``; the helper moved the self-cost into ``on_fail``, where it
   then re-ran once per creature that failed. Unconditional damage (Burn Through's breach packet)
   became conditional the same way.
2. P2 -- the helper returned after the FIRST damaging branch, so a use-timed bonus reached only that
   one. The executor halves a successful save's damage by reading ``type == "damage"`` rows out of
   ``on_fail`` (typed_executor.py), so an ``extra_damage`` rider parked there is dropped on a success,
   and a save with explicit damage on both outcomes paid no bonus on the success.
3. P2 -- the evidence was engine/renderer level and replay identity was unmeasured.

The compiler tests below drive the real authority records. The table tests drive ``TabletopService``:
they press the real offered button, commit it, reload the session from disk and read the real stored
events back, so the damage-gap wording is proven on events the table actually produced.
"""

from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))

from combat.factory_compiler import compile_character  # noqa: E402
from combat.gate5_service import CombatService  # noqa: E402
from combat.tabletop_service import TabletopService  # noqa: E402
from tests.h1_support import ROOT  # noqa: E402
from tests.hunt28_support import act, options  # noqa: E402
from tests.test_mmx97_damage_costs import (  # noqa: E402
    AUGMENTED,
    DAEMONIC,
    DEMON_MARK,
)
from tests.test_riders_c7 import (  # noqa: E402
    ME,
    answers,
    fight,
    sheet,
)

OWNER, FOE = "actor:factory.mmx97f1-owner", "actor:factory.mmx97f1-foe"
TEMP_HP = "Gain test Temporary Hit Points"


# --------------------------------------------------------------------------- helpers
def _mechanics(name):
    data = json.loads((APP / "authority" / "typed_mechanics" / "reviewed_final.d" / name).read_bytes())
    return data.get("mechanics", data)


def _rows(branch):
    return [row for row in branch or [] if isinstance(row, dict) and row.get("type") in ("damage", "extra_damage")]


def _attach(effects, added, when="use"):
    """The compiler's own placement step, so these tests cannot drift from it."""
    from combat.factory_compiler import _attach as attach

    return attach(effects, added, when)


def _pb_row(kind="extra_damage"):
    """The general use-timed rider: "add Proficiency Bonus to one damage roll"."""
    return {"type": kind, "applies_to": "target", "formula": "pb", "damage_label": "Test Augment",
            "evidence": "add Proficiency Bonus to one damage roll"}


def _save_row(on_fail, on_success):
    return {"type": "save", "ability": "cha", "dc": "technique_save_dc", "on_fail": on_fail, "on_success": on_success}


# --------------------------------------------------------------------------- finding 1: the base ability's own rows
def test_a_self_cost_next_to_a_damaging_save_stays_where_the_rules_put_it():
    """P1: Star-Sundering Cut's printed "8d6 + Cultivation Level" price must not join the line save.

    The real record keeps that row at the top level, beside the save, so it is paid once per
    activation. Relocated into ``on_fail`` it became conditional on every creature in the line that
    failed its save -- the caster could pay it three times for one swing, or not at all.
    """
    cut = _mechanics("review_sw-thread.json")["TAL_UNMAKING_SIXTH_RUIN_FORM_STAR_SUNDERING_CUT"]
    self_cost = [row for row in cut["effects"]
                 if row.get("type") == "damage" and row.get("applies_to") == "self"]
    assert self_cost, "the authority record must still print a self-cost at the top level"
    assert self_cost[0]["dice"] == {"count": 8, "sides": 6} and self_cost[0]["formula"] == "cl"

    tree = _attach(copy_effects(cut["effects"]), [_pb_row()])
    save = next(row for row in tree if row.get("type") == "save")
    on_fail = [row for row in save["on_fail"] if row.get("applies_to") == "self"]
    assert on_fail == [], f"the printed self-cost was relocated into a failed save: {on_fail}"
    top_self = [row for row in tree if row.get("type") == "damage" and row.get("applies_to") == "self"]
    assert len(top_self) == 1, f"the self-cost must remain exactly one unconditional top-level row, got {top_self}"


def test_unconditional_base_damage_is_never_made_conditional():
    """P1: Burn Through's shape -- breach damage at the top level, nearby-creature damage in on_fail.

    Only the modifier's own row may move. The base's unconditional packet has to keep firing on a
    successful save, which is the printed "the target is pushed through" that the save never covers.
    """
    base = [
        {"type": "damage", "applies_to": "target", "dice": {"count": 3, "sides": 6}},
        _save_row([{"type": "damage", "applies_to": "creatures_in_area", "dice": {"count": 6, "sides": 6}}], []),
    ]
    tree = _attach(copy_effects(base), [_pb_row()])
    assert tree[0] == {"type": "damage", "applies_to": "target", "dice": {"count": 3, "sides": 6}}, \
        f"the unconditional breach packet moved: {tree[0]}"
    save = next(row for row in tree if row.get("type") == "save")
    assert _rows(save["on_fail"])[0] == {"type": "damage", "applies_to": "creatures_in_area",
                                         "dice": {"count": 6, "sides": 6}}, \
        f"the printed nearby-creature damage must be untouched: {save['on_fail']}"
    assert [row.get("formula") for row in _rows(save["on_fail"])] == [None], \
        "the bonus rides the unconditional packet, not the separate nearby save"
    assert _rows(tree)[-1]["formula"] == "pb"


def test_an_ability_with_no_damaging_outcome_is_left_alone():
    """A modifier granting its own damage keeps it; a roll bonus needs a roll."""
    base = [_save_row([{"type": "condition", "condition": "prone", "applies_to": "target"}], [])]
    packet = {"type": "damage", "formula": "pb", "evidence": "Deal Fire damage equal to Proficiency Bonus."}
    tree = _attach(copy_effects(base), [packet])
    assert tree == base + [packet]
    assert _attach(copy_effects(base), [_pb_row()]) == base


def test_only_the_use_timing_is_repaired():
    """The helper runs on the general top-level landing only.

    ``when: "hit"`` already has a branch to ride, and its row must stay inside ``on_hit`` even when
    the ability also carries a top-level self-cost.
    """
    base = [
        {"type": "damage", "applies_to": "self", "dice": {"count": 2, "sides": 4}},
        {"type": "attack", "on_hit": [{"type": "damage", "applies_to": "target", "dice": {"count": 1, "sides": 8}}],
         "on_miss": []},
    ]
    tree = _attach(copy_effects(base), [{"type": "damage", "applies_to": "target", "formula": "pb"}], when="hit")
    attack = next(row for row in tree if row.get("type") == "attack")
    assert [row.get("formula") for row in attack["on_hit"]] == [None, "pb"], \
        f"a hit-timed rider must stay on the hit branch: {attack['on_hit']}"
    assert not [row for row in _rows(tree) if row.get("formula") == "pb"], \
        f"a hit-timed rider must not be dragged to the top level: {tree}"
    assert tree[0] == {"type": "damage", "applies_to": "self", "dice": {"count": 2, "sides": 4}}, \
        "the ability's own self-cost must stay at the top level"


# --------------------------------------------------------------------------- finding 2: every damaging save outcome
def test_a_save_for_half_keeps_the_bonus_on_a_successful_save():
    """P2: the executor halves a success by reading ``damage`` rows out of on_fail.

    Daemonic Augment's row is an ``extra_damage``, so parking it in ``on_fail`` alone silently
    dropped the whole bonus on every creature that saved.
    """
    half = _save_row([{"type": "damage", "applies_to": "target", "dice": {"count": 8, "sides": 6}}],
                     [{"type": "half_damage", "applies_to": "target", "dice": {"count": 8, "sides": 6}}])
    tree = _attach([half], [_pb_row()])
    save = tree[0]
    assert [row.get("type") for row in save["on_fail"]] == ["damage", "extra_damage"]
    assert [row.get("type") for row in save["on_success"]] == ["half_damage", "extra_damage"], \
        f"a saved creature must still take the bonus: {save['on_success']}"
    assert not _rows(tree), "the rider must not also stay at the top level"


def test_a_plain_damage_rider_is_not_added_to_the_success_branch():
    """The halving loop already halves a ``damage`` row parked in on_fail.

    Copying it onto the success branch as well would make a successful save take 1.5x the rider.
    """
    half = _save_row([{"type": "damage", "applies_to": "target", "dice": {"count": 8, "sides": 6}}],
                     [{"type": "half_damage", "applies_to": "target", "dice": {"count": 8, "sides": 6}}])
    save = _attach([half], [_pb_row("damage")])[0]
    assert [row.get("type") for row in save["on_success"]] == ["half_damage"], \
        f"a damage rider is already halved on a success; do not double it: {save['on_success']}"


def test_a_save_that_damages_on_success_keeps_the_bonus_there():
    """P2: Void Between Worlds' shape -- explicit damage on both outcomes pays the bonus on both."""
    both = _save_row([{"type": "damage", "applies_to": "target", "dice": {"count": 4, "sides": 8}}],
                     [{"type": "damage", "applies_to": "target", "dice": {"count": 2, "sides": 8}}])
    save = _attach([both], [_pb_row()])[0]
    assert [row.get("formula") for row in save["on_fail"]] == [None, "pb"]
    assert [row.get("formula") for row in save["on_success"]] == [None, "pb"]


def test_a_miss_deals_no_bonus():
    """A miss makes no damage roll, so the rider has nothing to add."""
    attack = {"type": "attack", "on_hit": [{"type": "damage", "applies_to": "target", "dice": {"count": 6, "sides": 6}}],
              "on_miss": []}
    tree = _attach([attack], [_pb_row()])
    assert _rows(next(row for row in tree if row.get("type") == "attack")["on_hit"])[-1]["formula"] == "pb"
    assert not _rows(tree)


# --------------------------------------------------------------------------- the real compiled variant
def _mark_character():
    return compile_character(sheet([DEMON_MARK], spheres=DAEMONIC, cl=18, dc=15), actor_id=ME)


def test_the_real_augmented_mark_registers_only_its_deferred_damage_rider():
    """HUNT211: "when you damage it" grants no roll for the Augment to increase."""
    engine = fight(_mark_character())
    answers(engine)
    action = next(a for a in engine.action_catalog.values() if a.display_name == AUGMENTED)
    typed = action.parameters["typed"]
    assert not _rows(typed["effects"]), f"the shipped variant must have no top-level damage: {typed['effects']}"
    save = typed["effects"][0]
    assert save["type"] == "save" and save["on_success"] == []
    damage_rows = _rows(save['on_fail'])
    assert damage_rows and all(row.get('deferred') for row in damage_rows)
    assert not any(row.get('damage_label') == 'Daemonic Augment' for row in damage_rows)


# --------------------------------------------------------------------------- table level: TabletopService
def _table(tmp_path, *, extra=()):
    """A real persisted table: two characters, the arena, MANUAL control, a fresh data root."""
    docs = [sheet([DEMON_MARK], spheres=DAEMONIC, cl=18, dc=30), sheet([])]
    combat = CombatService(ROOT, tmp_path)
    bundles = []
    for actor, doc in zip((OWNER, FOE), docs):
        folder = tmp_path / "portable_characters" / actor.removeprefix("actor:factory.")
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))
        compiled = compile_character(doc, actor_id=actor, reaction_plan={"ask": True})
        for aid, label, typed in extra:
            if actor != OWNER:
                continue
            compiled["actor_template"]["action_ids"].append(aid)
            compiled["action_catalog"].append({
                "source_definition_id": aid, "display_name": label, "owner_id": actor,
                "economy": "NONE", "resolution_kind": "TYPED", "target_kind": "HOSTILE_ENTITY", "range_ft": 30,
                "parameters": {"typed": {"effects": typed, "numbers": {}, "duration": {"kind": "instant"}}}})
        bundles.append(compiled)
    mid = combat._finish_factory_match(
        bundles, [OWNER, FOE], {OWNER: "team:factory", FOE: "team:opponents"},
        {OWNER: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [OWNER], [FOE],
        control_modes={actor: "MANUAL" for actor in (OWNER, FOE)}, match_seed="mmx97f1",
        display_name="MMX97f1 regression", maximum_rounds=10)["match_id"]
    table = TabletopService(combat, tmp_path)
    _owner_turn(table, mid)
    return combat, table, mid


def _reload(combat, mid):
    session = CombatService(ROOT, combat.userdata_root)._load_session(mid)
    assert session.mechanical.replay()["state"], "the reloaded fight must still match its canonical state"
    return session


def _owner_turn(table, mid):
    """End turns until the owner's menu opens, so the tests press a real offered button."""
    for _ in range(10):
        if table.state(mid)["menu"]["actor_id"] == OWNER:
            return
        assert act(table, mid, table.state(mid)["menu"]["end_turn"])["status"] == "COMMITTED"
    raise AssertionError("owner turn not reached")


def test_the_table_commits_the_augmented_button_and_keeps_its_cost_visible(tmp_path):
    """Checklist item 7, at the level the review asked for: the table, a commit, and a reload.

    HUNT99 #4 said a "+ modifier" button printed the base cost and charged base + rider. The player
    sees the button through TabletopService and the ledger through the same service after a reload.
    """
    combat, table, mid = _table(tmp_path)
    option = next(o for o in options(table, mid, AUGMENTED) if o["target_ids"] == [FOE])
    assert act(table, mid, option["candidate_id"])["status"] == "COMMITTED"

    session = _reload(combat, mid)
    spent = [e.payload for e in session.engine.events if e.event_type == "RESOURCE_SPENT"]
    assert spent, "pressing the button must charge something through the table"
    button = next(a for a in session.engine.action_catalog.values() if a.display_name == AUGMENTED)
    from combat.tabletop import engine_button_description

    line = engine_button_description(button.model_dump())
    for payload in spent:
        word = str(payload["resource_id"]).split(".")[-1].replace("_", " ").title()
        assert f"{payload['amount']} {word}" in line, \
            f"the table charged {payload['amount']} {word} but the button said: {line}"


def test_the_damage_gap_words_come_from_events_the_table_actually_recorded(tmp_path):
    """HUNT99 #1 at the level the review asked for: a real commit, a reload, and real events.

    The review's objection was that the original test fabricated the payload and called the
    formatter directly. Here the target really gains Temporary Hit Points through a real table
    action, really takes a real packet that those Temporary Hit Points absorb, and the feed is
    rendered from the events the table stored.
    """
    combat, table, mid = _table(tmp_path, extra=[(
        "action:test.mmx97f1_temp_hp", TEMP_HP,
        [{"type": "temp_hp", "applies_to": "target", "flat": 40, "formula": "none",
          "duration": "one_minute", "evidence": "the target gains 40 Temporary HP"}]),
        ("action:test.mmx97f1_damage", "Test Fire Damage",
         [{"type": "damage", "applies_to": "target", "flat": 12, "damage_types": ["fire"]}])])
    option = next(o for o in options(table, mid, TEMP_HP) if o["target_ids"] == [FOE])
    assert act(table, mid, option["candidate_id"])["status"] == "COMMITTED"

    damage = next(o for o in options(table, mid, "Test Fire Damage") if o["target_ids"] == [FOE])
    assert act(table, mid, damage["candidate_id"])["status"] == "COMMITTED"

    session = _reload(combat, mid)
    events = [e.model_dump(mode="json") for e in session.engine.events]
    committed = [e for e in events if e["event_type"] == "DAMAGE_COMMITTED"]
    assert committed, "the explicit Fire damage must have committed for this to be worth checking"
    absorbed = [e for e in committed if (e["payload"].get("temporary_hp_absorbed") or 0) > 0]
    assert absorbed, f"the target's Temporary HP must have absorbed part of a real packet: {committed}"

    from combat.history_feed import format_history_feed

    names = {actor: actor.rsplit("-", 1)[-1].title() for actor in (OWNER, FOE)}
    definitions = {a.source_definition_id: a.display_name for a in session.engine.action_catalog.values()}
    feed = format_history_feed(events, [], pre_state=None, post_state={}, actor_names=names,
                               definition_names=definitions)
    line = " ".join(row["summary"] for row in feed)
    assert "rolled" in line, f"the feed must state the rolled number for a real absorbed packet: {line}"
    assert "temporary Hit Points" in line, f"the feed must name what absorbed it: {line}"


def copy_effects(effects):
    import copy

    return copy.deepcopy(effects)
