"""A shaped area tells the creatures standing in it what it does to them.

Fight audit 2026-10-04, HUNT118 #1: Pure Darkness's two strongest printed clauses -- "Darkvision is reduced to
5 feet inside your Darkness" and "All other senses, including Blindsight and Scent, have their range reduced by
half" -- reached no player text at all. ``combat/factory_compiler.py._inside_rules`` kept only inside-effects whose
typed ``type`` was advantage/disadvantage, so those two sentences were dropped before they could become a reading or
a rider. The mechanics were always right (``combat/senses.py.reach`` cuts Darkvision to 5 feet and halves the rest);
only the text was missing, which is a checklist-13 failure.

The general seam is ``combat/factory_compiler.py._inside_clauses``: a printed inside-clause of ANY area talent that
the typing does not already carry somewhere else is compiled onto the shape as ``inside_text`` and shown on the zone
card. It is text only -- it never adds an effect, a condition or a save, so no talent's behaviour changes.
"""
import json
import re
from functools import lru_cache
from pathlib import Path

import pytest

from combat import factory_compiler
from combat.factory_compiler import _rules_text, _talent_tags
from tests.test_hunt32_edge import match, reload

ROOT = Path(__file__).resolve().parents[1]
DARKNESS = "DARK_BASE_DARKNESS"
PURE = "TAL_DARK_PURE_DARKNESS"

# The two clauses HUNT118 found in no player text, and the one that already was.
DARKVISION_CLAUSE = "Darkvision is reduced to 5 feet inside your Darkness."
HALVED_SENSES_CLAUSE = "All other senses, including Blindsight and Scent, have their range reduced by half."
HEARING_CLAUSE = "Wisdom (Perception) checks relying on hearing have Disadvantage."

# What a printed clause spends, requires or scales with is not a standing rule about the creatures inside the area.
_META = re.compile(r"^(?:#{1,6}\s|\*?\*?(?:Prerequisite|Requirement|Cost|Duration|Tags?|Tag|Note|Time|Action Type|"
                   r"Timing Detail|Type|Available At|Trigger|Range|Target|Effect|Size|AC|Hit Points|Attack or Save|"
                   r"Cultivation Level|Damage|Augment)\b|\s*\||If you (?:purchase|buy)\b)", re.I)

# An outcome label restates a rolled check the table already reported with its own outcome; on its own it is a fragment.
_OUTCOME = re.compile(r"^(?:(?:Failed|Successful|Unsuccessful|Success|Failure)\b[^.:]{0,30}:|On (?:a|an) (?:success|failure)\b)", re.I)


@lru_cache(maxsize=1)
def _mechanics():
    """The typed authority, read once: it is a 10 MB file and the guard below walks every talent in it."""
    return json.loads(factory_compiler.TYPED_AUTHORITY.read_bytes()).get("mechanics") or {}


def _press(table, mid, name):
    """Press the first option of the action whose label starts with ``name`` (a cell option reads "Darkness at 3, 6")."""
    state = table.state(mid)
    menu = state["menu"]
    group = next(g for g in menu["actions"] if g["label"] == name or g["label"].startswith(f"{name} at "))
    return table.act(mid, group["options"][0]["candidate_id"], menu["decision_id"], menu["state_version"],
                     state["last_sequence"], [])


def _zone_text(state):
    """Everything the table shows about every area in the fight, as one string."""
    zones = (state.get("presentation") or state).get("zones") or []
    return " ".join(" ".join(str(zone.get(field) or "") for field in ("rule_text", "detail", "display_name"))
                    for zone in zones)


def _pure_darkness(tmp_path):
    """A real table with a Pure Darkness zone the caster chose, and its (combat, table, match id)."""
    combat, table, mid = match(tmp_path, [DARKNESS, PURE])
    assert _press(table, mid, "Shape Darkness: Pure Darkness")["status"] == "COMMITTED"
    assert _press(table, mid, "Darkness")["status"] == "COMMITTED"
    return combat, table, mid


def test_pure_darkness_zone_card_carries_both_of_its_strong_clauses(tmp_path):
    """Table level, HUNT118 #1: the two missing clauses reach the zone the creatures are actually standing in."""
    combat, table, mid = _pure_darkness(tmp_path)
    shown = _zone_text(table.state(mid))
    assert DARKVISION_CLAUSE in shown, shown
    assert HALVED_SENSES_CLAUSE in shown, shown
    assert HEARING_CLAUSE in shown, shown

    # The clauses ride the zone's saved profile, so they survive a table commit and a reload. ``reload`` also asserts
    # the saved state reloads byte-identically and its journal still replays.
    engine = reload(combat, tmp_path, mid)
    zone = next(row for row in engine.state.zones.values() if row.active)
    saved = " ".join(zone.trigger_profile.get("inside_text") or [])
    assert DARKVISION_CLAUSE in saved and HALVED_SENSES_CLAUSE in saved, saved


def test_inside_text_is_text_only_and_mints_no_condition(tmp_path):
    """The new surface is player text, so it must not become a zone effect on every creature in the area.

    ``combat/zones.sync_inside`` mints one ``condition:typed.zone_effect`` per row of ``trigger_profile["inside"]``;
    that is why the clauses ride their own key instead of joining that list.
    """
    combat, _table, mid = _pure_darkness(tmp_path)
    engine = reload(combat, tmp_path, mid)
    zone = next(row for row in engine.state.zones.values() if row.active)
    assert zone.trigger_profile.get("inside_text")
    for row in zone.trigger_profile.get("inside") or []:
        assert row.get("rule") or row.get("muffles") or row.get("modifiers"), "every inside row still has a real effect"
    assert PURE in {row.get("id") for row in zone.trigger_profile.get("inside") or []}
    for actor in engine.state.actors.values():
        conditions = " ".join(str((c.data or {}).get("reading") or "") for c in actor.conditions.values())
        assert DARKVISION_CLAUSE not in conditions, "the clauses are player text, not a condition"


def _shaped(tmp_path, talent, shape_label):
    """A real table with a Darkness zone shaped by ``talent``, the caster having chosen it, and the match id."""
    combat, table, mid = match(tmp_path, [DARKNESS, talent])
    assert _press(table, mid, shape_label)["status"] == "COMMITTED"
    assert _press(table, mid, "Darkness")["status"] == "COMMITTED"
    return combat, table, mid


# Disorienting Darkness' printed conditional, checked in the parts that do not carry a typographic apostrophe.
SAVE_WHEN = ("The first time on a turn that a creature attempts to enter, leave, or move through the area, "
             "it makes an Intelligence saving throw.")
SAVE_HEAD = "Failed Save: Roll 1d8 to determine the creature"
SAVE_ROLL_OUTCOME = "1 is the intended direction; 2-8 rotate clockwise around the creature."
SAVE_RESULT = "The creature moves as though the rolled direction were its intended route."


def test_disorienting_darkness_card_keeps_the_failed_save_rule_whole(tmp_path):
    """Table level, MMX114 review finding 1: the save's condition and its consequence stay on the same card.

    The card used to carry the tail of the rule only -- "1 is the intended direction; 2-8 rotate clockwise ..." -- with
    no roll and no failed save, so a player could not tell when the redirection applied. A conditional is shown whole
    or not at all.
    """
    _combat, table, mid = _shaped(tmp_path, "TAL_DARK_DISORIENTING_DARKNESS", "Shape Darkness: Disorienting Darkness")
    shown = _zone_text(table.state(mid))
    for part in (SAVE_WHEN, SAVE_HEAD, SAVE_ROLL_OUTCOME, SAVE_RESULT):
        assert part in shown, f"{part!r} is not on the zone card: {shown}"
    # In order, and with nothing between the condition and what it produces.
    assert shown.index(SAVE_WHEN) < shown.index(SAVE_HEAD) < shown.index(SAVE_ROLL_OUTCOME) < shown.index(SAVE_RESULT)


def test_area_clauses_explain_cultivation_level(tmp_path):
    """Table level, MMX114 review finding 3: a newly shown clause never hands a player an abbreviation.

    Tenebrous Legerdemain's card ends "You may move objects weighing up to 5 x CL pounds." Basic D&D does not say what
    CL is. The stored clause keeps the owner's printed wording (it is their rule, verbatim); the card resolves it.
    """
    _combat, table, mid = _shaped(tmp_path, "TAL_DARK_TENEBROUS_LEGERDEMAIN", "Shape Darkness: Tenebrous Legerdemain")
    shown = _zone_text(table.state(mid))
    assert "5 x CL" not in shown, shown
    assert "weighing up to" in shown, shown
    assert re.search(r"\bCL\b", shown) is None, f"the bare abbreviation CL reached the card: {shown}"


def test_shadow_tag_card_carries_no_meld_instruction(tmp_path):
    """Table level, MMX114 review finding 3: no card tells a standing creature to act on one outside the area.

    Shadow Tag is filed under a Darkness heading, so its block was surfaced whole -- including "As a Meld talent, apply
    the same effect directly to one creature.", which is a second way of USING the talent, not a rule about the area.
    """
    _combat, table, mid = _shaped(tmp_path, "TAL_DARK_SHADOW_TAG", "Shape Darkness: Shadow Tag")
    shown = _zone_text(table.state(mid))
    assert "As a Meld talent" not in shown, shown
    assert "Meld" not in shown, shown
    # The area's own standing rule is still there; only the alternate use is gone.
    assert "passing through your Darkness" in shown, shown


def test_area_wording_resolves_a_known_cultivation_level():
    """The owner's own Cultivation Level, so the card can show the real weight instead of a scale.

    Unit level because the synthetic test fixture carries no projection, so no table in these tests has a Cultivation
    Level to resolve: the table-level test above pins the wording used when the level is not in the view.
    """
    from combat.status_text import area_wording

    printed = "You may move objects weighing up to 5 x CL pounds."
    assert area_wording(printed, 20) == "You may move objects weighing up to 100 pounds."
    assert area_wording(printed, 5) == "You may move objects weighing up to 25 pounds."
    assert area_wording(printed) == "You may move objects weighing up to 5 x your Cultivation Level in pounds."
    # Inert on text with no abbreviation, so it cannot rewrite the rest of the card.
    assert area_wording(DARKVISION_CLAUSE, 20) == DARKVISION_CLAUSE


def test_no_rendered_area_clause_shows_an_unexpanded_abbreviation():
    """Corpus level: whatever the compiler stores for a card, no player is shown a bare "CL".

    The stored clause keeps the owner's printed wording verbatim, so the check is on what the card renders
    (``status_text.area_wording``), which is the surface a player reads.
    """
    from combat.status_text import area_wording

    for mid, name in _area_talents():
        for clause in factory_compiler._inside_clauses(mid, _mechanics().get(mid) or {}, name):
            rendered = area_wording(clause, 20)
            assert re.search(r"\bCL\b", rendered) is None, f"{mid} ({name}) shows a bare abbreviation: {rendered}"


def _area_talents():
    """Every talent that changes an area of some kind ("### Pure Darkness - Darkness"), with that area's name.

    An area is a mechanic that fills space (a typed area size, or a zone effect) and a talent belongs to one when its
    printed heading names it -- the same pairing ``_zone_shapes`` builds, so the guard below covers the corpus
    instead of one hand-picked ability. Sphere tags that are not areas ("### Clarity - Protection") are not areas and
    are left out; a talent printed as its own area talent is covered the day it is written.
    """
    areas = set()
    for mechanic in _mechanics().values():
        if not isinstance(mechanic, dict):
            continue
        if (mechanic.get("area") or {}).get("size_ft") or any(
                isinstance(effect, dict) and effect.get("type") == "zone" for effect in mechanic.get("effects") or []):
            areas.add(str(mechanic.get("name") or ""))
    out = []
    for mid, mechanic in sorted(_mechanics().items()):
        if not isinstance(mechanic, dict):
            continue
        if (mechanic.get("activation") or {}).get("economy") in ("action", "bonus_action", "reaction"):
            continue
        area = next((tag for tag in _talent_tags(mid) if tag in areas), None)
        if area:
            out.append((mid, area))
    return out


def _printed_inside_clauses(mid, name):
    """The talent's own printed block that speaks about being in the area, read here independently of the compiler.

    Deliberately simple: a block under the heading that puts a creature in the area is an inside-clause block, and
    every rule sentence of it is an inside-clause. The compiler may choose how to render one; it may not drop one.
    Two kinds of printed sentence are not clauses of the area and are excluded: an outcome label ("Failed Save:
    Restrained until the start of its next turn."), which restates a rolled check the table already reported with its
    own outcome; and everything from an "Augment - N CP:" line onward, which is a paid option the area's owner
    chooses rather than a standing rule about the creatures in it.
    """
    marker = re.compile(rf"\b(?:inside|within)\b|\b(?:in|within|through(?:out)?)\s+(?:the|your|this|that|an?)\s+"
                        rf"{re.escape(name)}\b", re.I)
    body = "\n".join(line for line in str(_rules_text().get(mid) or "").splitlines()
                     if not line.lstrip().startswith("#"))
    out = []
    for block in re.split(r"\n\s*\n", body):
        if not marker.search(block):
            continue
        for part in re.split(r"(?<=[.;])\s+|\n", block):
            clause = " ".join(part.replace("*", "").split())
            if clause.startswith("Augment"):
                break  # a paid option the area's owner chooses; nothing after it is a standing rule
            if len(clause) < 20 or _META.match(clause) or _OUTCOME.match(clause):
                continue
            out.append(clause)
    return out


def _zone_ground_surfaces(mid, mechanic):
    """The two printed clauses the compiler converts into zone fields of their own, whatever talent shaped the area.

    "Your Darkness becomes difficult terrain" becomes ``trigger_profile["difficult"]``, and the card says "Difficult
    terrain: movement costs twice normal"; "cannot take the Dash or Disengage actions" becomes the mechanical inside
    row the card reads "Cannot take the Dash or Disengage actions". Both are the printed clause, in the fight's words.
    """
    ground = factory_compiler._left_terrain(factory_compiler._texts(mechanic))
    # The compiler reads the barred actions off the printed text first (factory_compiler._zone_abilities).
    barred = factory_compiler._barred_actions(str(_rules_text().get(mid) or "") or factory_compiler._texts(mechanic))
    out = [str((ground or {}).get("sentence") or "")]
    if barred:
        out.append(f"Cannot take the {' or '.join(word.title() for word in barred)} action{'s' if len(barred) > 1 else ''}.")
    return [text for text in out if text]


def _served_surfaces(mid, mechanic, name):
    """Everything the zone card shows a creature standing in the area, in the words a player reads.

    Only standing surfaces count: the mechanical inside rows the card reads, the compiled ``inside_text``, and the zone
    fields a printed clause is converted into.

    Deliberately NOT the raw ``evidence``/``on`` string of every effect in the authority (MMX114 review finding 2). An
    effect that only ever fires as a trigger rider is a ruling shown at the moment the trigger fires; crediting its
    authority string let Calming Perfume's "A hostile creature inside has Disadvantage on Charisma (Intimidation)
    checks" pass this guard while the card never showed it and ``_inside_rules`` rejected its ``applies_to: target``.
    """
    shown = [str(row.get("reading") or "") for row in factory_compiler._inside_rules(mid, mechanic)]
    shown += list(factory_compiler._inside_clauses(mid, mechanic, name))
    shown += _zone_ground_surfaces(mid, mechanic)
    return [" ".join(text.split()) for text in shown if text]


# Printed inside-clauses that reach no standing surface, named rather than credited to something the player is not
# shown. Each is asserted to still be missing (test_named_exclusions_are_still_live), so a later fix that surfaces one
# has to delete its entry instead of leaving a silent pass behind.
NOT_A_RULE_ABOUT_THE_AREA = {
    ("TAL_DARK_SHADOW_TAG", "As a Meld talent, apply the same effect directly to one creature."):
        "the print files a second way of USING the talent (apply it straight to one creature) under a Darkness heading; "
        "it is not a rule about the creatures in the area, and the card would tell them to act on a creature outside it",
    ("TAL_DARK_THICK_DARKNESS", "Creatures inside move at half Speed and cannot take the Dash or Disengage actions."):
        "the compiler turns this line into the barred-action row, and the half-Speed half has no zone field at all; the "
        "printed half Speed is unenforced, so showing the words would advertise a rule the fight does not apply. "
        "Inherited, and deliberately not repaired here (no inherited mechanical repairs in this lane)",
}


@pytest.mark.parametrize("mid,name", _area_talents(), ids=[f"{mid}" for mid, _ in _area_talents()])
def test_every_printed_inside_clause_reaches_the_zone_card(mid, name):
    """The corpus guard for HUNT118 #1: no printed inside-clause of an area talent is silently dropped.

    A clause is accounted for when the card says it, in full. A 20-character fragment of a longer surface does not
    count -- that shortcut let "Cannot take the Dash or Disengage actions." pass for the whole of Thick Darkness's
    "move at half Speed and cannot take ..." sentence, which is the MMX114 review's second counterexample.
    """
    mechanic = _mechanics().get(mid)
    if mechanic is None:
        pytest.skip(f"{mid} is not in the typed authority")
    if not hasattr(factory_compiler, "_inside_clauses"):
        pytest.skip("the inside-clause seam is not in this build")
    served = " ".join(_served_surfaces(mid, mechanic, name)).lower()
    missing = [clause for clause in _printed_inside_clauses(mid, name)
               if clause.lower() not in served and (mid, clause) not in NOT_A_RULE_ABOUT_THE_AREA]
    assert not missing, f"{mid} ({name}) drops {missing}"


def test_named_exclusions_are_still_live():
    """A named omission must still be an omission, or its entry is stale and has to go.

    Guards the exclusion list itself: if a later change surfaces one of these clauses this fails, and the entry is
    deleted, rather than the corpus guard quietly keeping an exclusion for text that is now on the card.
    """
    for (mid, clause), reason in NOT_A_RULE_ABOUT_THE_AREA.items():
        assert reason, f"{mid}: an exclusion needs a reason"
        area = dict(_area_talents()).get(mid)
        assert area, f"{mid}: an exclusion names a talent the area corpus no longer has"
        printed = _printed_inside_clauses(mid, area)
        assert any(clause in row for row in printed), \
            f"{mid}: {clause!r} is no longer a printed inside-clause; drop the exclusion"
        served = " ".join(_served_surfaces(mid, _mechanics()[mid], area)).lower()
        assert clause.lower() not in served, \
            f"{mid}: {clause!r} is now served on the zone card; drop the exclusion"
