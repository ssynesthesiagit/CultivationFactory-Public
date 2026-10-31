"""Acceptance case for the reviewed general creature-target domain."""

from tests.test_tabletop_hunt6 import table_fight, LEFT, ALLY, RIGHT
from tests import test_tabletop_hunt6 as fixtures
from tests.h1_support import sheet


def test_soul_gaze_offers_visible_enemy_without_hostile_effect(tmp_path, monkeypatch):
    """Respect the explicit primary-pool fixture from fix/devour (83893b6d,
    approved in QUEUE). codex/lock7-soul-gaze 076dbdcb (L7soul-gaze.review.md,
    composition finding fixed in that head; merged by 5e6b03d6) supplies the
    ANY_CREATURE contract, so this is now a passing acceptance test.
    """
    # The shared fixture defaults to Qi; Soul Gaze needs a payable Resonance pool.
    def spirit_sheet(*args, **kwargs):
        document = sheet(*args, **{**kwargs, "primary": "Resonance"})
        document["identity"]["path"] = "Spirit Awakening"
        return document
    monkeypatch.setattr(fixtures, "sheet", spirit_sheet)
    combat, table, mid = table_fight(tmp_path, ["tianxia.path.spirit_awakening.feature.soul_gaze"],
                                     ally_talents=[])
    engine = combat._load_session(mid).engine
    assert engine._line_of_sight_actor_to_actor(engine.state.actors[LEFT], engine.state.actors[RIGHT])
    # Hunt15 owns display text; identify the action independently of its label.
    group = next(g for g in table.state(mid)["menu"]["actions"]
                 if g["source_definition_id"].endswith("tianxia.path.spirit_awakening.feature.soul_gaze"))
    targets = {t for option in group["options"] for t in option["target_ids"]}
    assert ALLY in targets
    assert RIGHT in targets
