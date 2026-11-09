"""TALISMANS_BASE_TALISMAN_SCRIBE -- the printed clauses of the Talismans sphere's Talisman Scribe.

Every test here is a real compiled character in a real table fight: the menu is taken, the action is
committed, and the fight is reloaded from disk (which also asserts the replay). No test types the row's id
into a sheet. Each fighter's only Talisman Scribe record arrives through the table's own acquisition producer
(``combat.table_advance.apply`` -> ``base_abilities``, which grants a learned Sphere's ``kind ==
"base_ability"`` records), so a fighter that never learned the Talismans sphere has nothing to inherit and
every assertion below fails if that producer is removed.

The printed record (owner's Sphere Compendium, authority/typed_mechanics/rules_text.json, full decoded
rules_text SHA256 cef68fd6dcae1892b61cc3c9240ef05a9c6cce4773c42eeff51a4e3e904985bc):

    "When you gain the Talismans sphere, you gain proficiency with Calligrapher's Supplies. If you already
     have this proficiency, gain one additional Common formula.
     You learn three Common formulae of your choice.
     You may craft Common talismans using the Talisman Crafting procedure.
     You can identify your own talismans automatically. You have Advantage on checks to identify a talisman
     formula you personally know."

What is asserted natively, and what is not:

  * Acquisition of the row and of its sphere-mates is delivered and asserted here.
  * The one deliverable clause -- "Advantage on checks to identify a talisman formula you personally know" --
    is asserted end to end: the Advantage rides the real Read the Script check only when the fighter names a
    formula they personally know, and the check rolls normally when they do not. Both branches and the
    wrong-owner control are checked, and the persisted fight is reloaded before each is read.
  * The other four printed clauses are build-time grants and a crafting permission with no fight-time
    producer. They are deliberately NOT asserted here: nothing on the sheet records them, so a test that
    claimed them would be a fixture-only fact. They are listed as residuals in the lane report.
"""
from combat import table_advance
from combat.ext import talisman_scribe
from tests.hunt12_support import ME as TABLE_ME, reload
from tests.talisman_scribe_support import (ALLY_TABLE, PURIFYING, SCRIPT, SPHERE,
                                           learned_talismans as _learned_talismans,
                                           script_check as _script_check, table as _table,
                                           unacquired as _unacquired)
from tests.inscription_support import press

SCRIBE = talisman_scribe.SCRIBE
SCRIPT_NAME = "Read the Script"
YES = talisman_scribe.YES


def test_learning_the_talismans_sphere_grants_the_talisman_scribe_row():
    """Acquisition: learning the Sphere at the table grants this row, with no id typed in by this test."""
    granted = _learned_talismans()["spheres_and_talents"]["automatic_sphere_component_record_ids"]
    assert SCRIBE in granted, f"acquiring the Talismans sphere must grant Talisman Scribe, got {granted}"
    # Ownership is inert until the Sphere is learned, and one acquisition is not paid twice.
    assert _unacquired()["spheres_and_talents"]["automatic_sphere_component_record_ids"] == []
    twice = table_advance.apply(_learned_talismans(), {"spheres": [{"id": SPHERE}]})
    assert twice["spheres_and_talents"]["automatic_sphere_component_record_ids"] == granted


def test_known_formula_reads_with_advantage_and_unknown_one_reads_normally(tmp_path):
    """Native delivery: the printed Advantage reaches the real Read the Script check only for a formula
    the fighter personally knows. Both branches are taken through the table's own menu and reloaded."""
    combat, table, mid = _table(tmp_path, _learned_talismans())
    press(combat, table, mid, name=SCRIPT_NAME, steps=["Arcana", "worn or smudged", YES])
    engine = reload(tmp_path, mid)
    known = _script_check(engine)
    assert known, "Read the Script must roll its printed Intelligence check"
    assert known[0].payload["actor"]["mode"] == "ADVANTAGE", \
        "'Advantage on checks to identify a talisman formula you personally know' did not reach the check"

    combat2, table2, mid2 = _table(tmp_path, _learned_talismans(), seed="MGR14SCRIBE-UNKNOWN")
    press(combat2, table2, mid2, name=SCRIPT_NAME, steps=["Arcana", "worn or smudged", talisman_scribe.NO])
    engine2 = reload(tmp_path, mid2)
    unknown = _script_check(engine2)
    assert unknown, "the unclaimed branch must still roll the check"
    assert unknown[0].payload["actor"]["mode"] == "NORMAL", \
        "a formula the fighter has not learned must not receive Talisman Scribe's Advantage"


def _riders(engine):
    """The GM narration this fight recorded, as text."""
    return [str(event.payload.get("rider") or "") for event in engine.events if event.event_type == "GM_RIDER"]


PRINTED_CLAUSE = "Advantage on checks to identify a talisman formula you personally know"


def test_the_printed_clause_is_not_narrated_as_a_gm_rider_on_either_answer(tmp_path):
    """Regression (F11R): the Scribe row must reach the check only through its own printed question, never as
    a GM rider. Both answers are taken through the table and reloaded; the rider text must not appear."""
    combat, table, mid = _table(tmp_path, _learned_talismans())
    press(combat, table, mid, name=SCRIPT_NAME, steps=["Arcana", "worn or smudged", YES])
    known = _riders(reload(tmp_path, mid))
    assert not any(PRINTED_CLAUSE in text for text in known), known

    combat2, table2, mid2 = _table(tmp_path, _learned_talismans(), seed="MGR14SCRIBE-RIDER-NO")
    press(combat2, table2, mid2, name=SCRIPT_NAME, steps=["Arcana", "worn or smudged", talisman_scribe.NO])
    unknown = _riders(reload(tmp_path, mid2))
    assert not any(PRINTED_CLAUSE in text for text in unknown), unknown


def test_a_fighter_who_never_acquired_talisman_scribe_gets_no_advantage(tmp_path):
    """Wrong-owner / boundary control: a fighter who can read scripts but never acquired this row gets none
    of it. The fighter still owns Read the Script, so the printed check itself stays reachable."""
    base = _unacquired()
    # This fighter holds Read the Script (and so has the action and its check) but acquired no sphere
    # component at all, so Talisman Scribe is not theirs. Nothing here types the Scribe id anywhere.
    base["spheres_and_talents"]["learned_talent_record_ids"] = [PURIFYING, SCRIPT]
    combat, table, mid = _table(tmp_path, base, seed="MGR14SCRIBE-NOOWNER",
                                ally_sheet=_learned_talismans())
    engine = combat._load_session(mid).engine
    assert talisman_scribe._owns_scribe(engine, engine.state.actors[ALLY_TABLE])
    assert not talisman_scribe._owns_scribe(engine, engine.state.actors[TABLE_ME]), \
        "a fighter whose sheet never acquired Talisman Scribe must not own the row"
    press(combat, table, mid, name=SCRIPT_NAME, steps=["Arcana", "worn or smudged"])
    engine = reload(tmp_path, mid)
    checks = _script_check(engine)
    assert checks, "Read the Script stays reachable for a fighter who owns it by another route"
    assert checks[0].payload["actor"]["mode"] == "NORMAL", \
        "no Talisman Scribe Advantage may reach a fighter who never acquired the row"
    assert not any(PRINTED_CLAUSE in text for text in _riders(engine)), \
        "an unowned fight must not carry Talisman Scribe's printed clause as a GM rider"
