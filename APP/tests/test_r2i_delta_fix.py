"""Table delivery, commit/reload, and later-roll controls for R2b's delta findings."""
import pytest

from tests.test_r2i_review_fix import fixture, take, reload, R, SOVEREIGN, COUNTER, CRANE
from combat.ext.iron_fist_riders import SOVEREIGN_COUNTER_USED

KINGFISHER = "tianxia.talent.sabers.kingfisher_beheads_the_retreat"
CHOICE = "choice:needle.sovereign_counterstrike"


def test_actual_kingfisher_ranged_reaction_miss_does_not_spend_sovereign(tmp_path):
    combat, table, mid = fixture(tmp_path, [SOVEREIGN], foe_sphere="tianxia.sphere.sabers", foe_talents=[KINGFISHER, "tianxia.talent.sabers.forward_cut"])
    take(combat, table, mid, "End Turn")
    take(combat, table, mid, "Saber-Line Pressure: prefer Guard Pressure", R.FOE)
    take(combat, table, mid, "Forward Cut", R.ME)
    take(combat, table, mid, "End Turn")
    take(combat, table, mid, "Sovereign Iron-Body Incarnation", R.ME)
    start = len(combat._load_session(mid).engine.events)
    menu = combat.decision(mid)["context"]["legal_candidates"]
    move = next(c for c in menu if c.get("destination") == {"x": 3, "y": 6})
    prompts = take(combat, table, mid, move["display_name"], destination=move["destination"], declines=["opportunity_attack"])
    engine = reload(tmp_path, combat, mid)
    rolls = [e for e in engine.events[start:] if e.event_type == "ATTACK_ROLLED" and e.source_definition_id == KINGFISHER]
    assert len(rolls) == 1 and not rolls[0].payload["provisional_hit"]
    assert not any(p["context"]["reaction_source_id"] == CHOICE for p in prompts)
    assert SOVEREIGN_COUNTER_USED not in engine.state.actors[R.ME].turn_flags
    take(combat, table, mid, "Move to 4,6", destination={"x": 4, "y": 6})
    take(combat, table, mid, "End Turn")
    start = len(engine.events)
    attack = next(c for c in combat.decision(mid)["context"]["legal_candidates"] if c["display_name"].endswith(" attack") and R.ME in c["target_ids"])
    prompts = take(combat, table, mid, attack["display_name"], R.ME)
    engine = reload(tmp_path, combat, mid)
    assert any(p["context"]["reaction_source_id"] == CHOICE for p in prompts)
    assert any(e.event_type == "ATTACK_ROLLED" and e.source_definition_id.endswith(".sovereign_counterstrike") for e in engine.events[start:])


@pytest.mark.parametrize("mode", ["smoke", "smoke_with_boon"])
def test_reach_abort_cleans_only_strike_modes_across_reload_and_next_target(tmp_path, mode):
    """riders/c13 bfb4e5d0 (approving C13r3.review.md) adds a Smoke Veil mover.
    Select creature movement explicitly: the new zone-move action shares the
    destination but must not replace the foe's step into smoke in this fixture.
    """
    talents = [COUNTER, CRANE, SOVEREIGN]
    combat, table, mid = fixture(tmp_path, talents, third=True,
        foe_sphere="tianxia.sphere.smoke",
        boon=mode == "smoke_with_boon")
    # Smoke is placed by a real table action on a prior turn; the bundle fixture
    # narrows its area to isolate a visible second target.
    if mode.startswith("smoke"):
        take(combat, table, mid, "End Turn")
        take(combat, table, mid, "Smoke Veil at 5,7", destination={"x": 5, "y": 7})
        move = next(c for c in combat.decision(mid)["context"]["legal_candidates"]
                    if c["kind"] == "MOVE" and c.get("destination") == {"x": 5, "y": 7})
        take(combat, table, mid, move["display_name"], destination=move["destination"])
        take(combat, table, mid, "End Turn")
        take(combat, table, mid, "End Turn")
    take(combat, table, mid, "Sovereign Iron-Body Incarnation", R.ME)
    take(combat, table, mid, "End Turn")
    start = len(combat._load_session(mid).engine.events)
    take(combat, table, mid, "Fu (Short Axe) attack", R.ME, choices=["cell:1,6"])
    engine = reload(tmp_path, combat, mid)
    events = engine.events[start:]
    assert not any(e.event_type == "ATTACK_ROLLED" and e.source_definition_id.endswith(".sovereign_counterstrike") for e in events)
    # 943861ca shares cancellation cleanup across aborted projectile attempts.
    assert any(e.event_type == "MODIFIER_REMOVED" and e.payload.get("reason") == "CANCELLED_ATTACK" for e in events)
    held = [m for m in engine.state.actors[R.ME].modifiers.values() if m.target_field == "attack_mode"]
    assert [m.value for m in held] == (["ADVANTAGE"] if mode == "smoke_with_boon" else [])
    take(combat, table, mid, "End Turn")
    take(combat, table, mid, "End Turn")
    start = len(combat._load_session(mid).engine.events)
    take(combat, table, mid, R.STRIKE, "visible")
    engine = reload(tmp_path, combat, mid)
    rolls = [e for e in engine.events[start:] if e.event_type == "ATTACK_ROLLED" and e.actor_id == R.ME]
    assert rolls and rolls[0].payload["mode"] == ("ADVANTAGE" if mode == "smoke_with_boon" else "NORMAL")
