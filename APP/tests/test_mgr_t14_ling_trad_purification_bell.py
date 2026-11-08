"""Purification Bell (tianxia.tradition.spirit.exorcist.feature.purification_bell) at the table.

Lane MGR-T14-ling-trad-purification-bell-1. Owned scope: the Purification-Bell branch of
``exorcist.rite``, ``_purify`` for Bell recipients, and Bell-specific helpers only. Grand Exorcism
(``remove_marks`` absent -> the Frightened/Charmed-only branch) and the sibling Ghost Sight /
Name the Intruder handlers are untouched and appear here only as controls.

These run through the real compiled character -> CombatService/TabletopService intent -> table
commit -> cold reload + mechanical replay path (tests/test_tabletop_hunt6.table_fight plus
CombatService._load_session), never a direct plug-in call.

Printed clause under test: Purification Bell's willing-ally purification benefit, fourth option --
"Remove one Resonance Mark, ordinary Spiritual Pressure effect, or hostile spirit-tracking mark
**with Source CL lower than yours**." The Bell may only strip a mark whose recorded Source CL is
below the exorcist's own; a mark at or above it is not the Bell's to remove.
"""

from combat import typed_executor
from combat.ext import exorcist as ex
from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests.r10_fixup_support import fixed_dice
from tests.r1i_service_support import force_ai_candidate
from tests.test_lock2_persistence import act
from tests.test_tabletop_hunt6 import ALLY, HOLD, LEFT, RIGHT, on_hold, table_fight

BELL = ex.BELL
FOE_KIND = "Intruder"  # the Bell's printed hostile target kind


def reload(tmp_path, mid):
    """Cold reload from disk: verifies the persisted fight and replays it mechanically."""
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    assert session.verify()["status"] == "PASS"
    assert session.mechanical.replay()["status"] == "PASS"
    return session.engine


def left_turn(table, mid):
    """Commit the pre-fight setup action and advance until it is LEFT's turn."""
    assert act(table, mid, HOLD)["status"] == "COMMITTED"
    for _ in range(6):
        if table.state(mid)["menu"]["actor_id"] == LEFT:
            return
        assert act(table, mid, "end")["status"] == "COMMITTED"
    raise AssertionError("LEFT never received its next turn")


def cast_on_ai(combat, table, mid, name):
    """Force ``name`` on the AI seat and answer its menus, then commit."""
    engine = combat._load_session(mid).engine
    candidate = next(c for c in engine.legal_candidates() if c.display_name == name)
    force_ai_candidate(combat, mid, LEFT, candidate.candidate_id)
    assert table.auto_step(mid, 0, [])["status"] == "COMMITTED"


def bell_fight(tmp_path, monkeypatch, *, cl=15, source_cl=5):
    """A Bell exorcist (LEFT) whose ally carries a Resonance Mark placed by the controlled hostile.

    ``source_cl`` is the recorded Source CL of the mark's source, so the same fight covers both
    sides of the printed "lower than yours" limit.
    """
    combat, table, mid = table_fight(tmp_path, [BELL], cl=cl, primary="Resonance", foe_types=[FOE_KIND], ally_talents=[])

    def marked(engine):
        engine._apply_condition(engine.state.actors[ALLY],
                                typed_executor.mark_condition_id("Resonance", RIGHT),
                                "test:hostile-mark", RIGHT, expires_on="UNTIL_REMOVED",
                                data={"source_cl": source_cl})

    on_hold(monkeypatch, marked)
    fixed_dice(monkeypatch, [1] * 200)
    left_turn(table, mid)
    return combat, table, mid


def hostile_marks_on_ally(engine):
    ally = engine.state.actors[ALLY]
    return [c for c in ally.conditions.values()
            if c.condition_id.startswith(typed_executor.MARK_PREFIX) and c.condition_id.endswith(RIGHT)]


# ------------------------------------------------------------------ printed limit: Source CL lower than yours
def test_purification_bell_removes_an_ally_mark_of_lower_source_cl(tmp_path, monkeypatch):
    """Source CL 5 < exorcist CL 15: the printed benefit applies and survives the commit."""
    combat, table, mid = bell_fight(tmp_path, monkeypatch, cl=15, source_cl=5)
    cast_on_ai(combat, table, mid, "Purification Bell")

    engine = reload(tmp_path, mid)
    assert not hostile_marks_on_ally(engine), "a lower-Source-CL hostile mark is the Bell's to remove"


def test_purification_bell_keeps_an_ally_mark_at_or_above_its_own_source_cl(tmp_path, monkeypatch):
    """Source CL 20 >= exorcist CL 15: the printed limit forbids removing it, so the mark stays.

    This is the regression: before the Source CL gate the Bell offered to strip any hostile mark
    on an ally regardless of that mark's recorded authority.
    """
    combat, table, mid = bell_fight(tmp_path, monkeypatch, cl=15, source_cl=20)
    cast_on_ai(combat, table, mid, "Purification Bell")

    engine = reload(tmp_path, mid)
    assert hostile_marks_on_ally(engine), "the Bell must not remove a mark whose Source CL is not lower than its own"


# ------------------------------------------------------------------ controls: scope boundaries
def test_purification_bell_is_not_offered_to_a_character_without_the_feature(tmp_path, monkeypatch):
    """Wrong-owner control: a character without the Bell row never offers the ability."""
    combat, table, mid = table_fight(tmp_path, [], primary="Resonance", foe_types=[FOE_KIND], ally_talents=[])
    fixed_dice(monkeypatch, [1] * 200)
    engine = combat._load_session(mid).engine
    assert not any(c.display_name == "Purification Bell" for c in engine.legal_candidates())


def test_grand_exorcism_purification_is_unaffected_by_the_bell_source_cl_gate(tmp_path, monkeypatch):
    """Sibling control: Grand Exorcism has no remove_marks, so it still ends Frightened."""
    combat, table, mid = table_fight(tmp_path, [ex.GRAND], primary="Resonance", foe_types=[FOE_KIND], ally_talents=[])

    def fear(engine):
        engine._apply_condition(engine.state.actors[ALLY], "condition:typed.frightened", "test:fear", RIGHT,
                                expires_on="UNTIL_REMOVED")

    on_hold(monkeypatch, fear)
    fixed_dice(monkeypatch, [1] * 200)
    left_turn(table, mid)
    cast_on_ai(combat, table, mid, "Grand Exorcism")

    engine = reload(tmp_path, mid)
    assert not any(c.condition_id == "condition:typed.frightened" for c in engine.state.actors[ALLY].conditions.values())