"""Service-level regression for the optional Bitter Trace save replacement (review LUNA74r, finding 3).

The engine-level regressions live in tests/test_review_sw-monkey_style.py. This file covers what
only the service can show: that the table offers both choices, that the replacement's button
explains the trade, and that choosing it survives a real persistence commit and reload -- the mark
it guarantees and the ordinary attack damage it keeps.
"""
import json
import zipfile
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
AUTH = json.loads((APP / "authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_text())["mechanics"]
SPHERE = "tianxia.sphere.poison"
BITTER_TRACE = "tianxia.talent.poison.bitter_trace"
LEFT, RIGHT = "actor:factory.left", "actor:factory.right"


def _poison_sheet():
    from tests.test_auto_docket import _sheet

    bases = [key for key, row in AUTH.items()
             if row.get("sphere_id") == SPHERE and row.get("kind") == "base_ability"]
    return _sheet([*bases, BITTER_TRACE], [SPHERE])


@pytest.fixture
def in_range(tmp_path):
    """A committed service match, played through the API until Deliver the Dose is on the table.

    The fighters start 75 feet apart and the ability reaches 60, so the character walks into range
    the way a player would: every step here is a service submit or a committed auto step.
    """
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService

    for project in ("left", "right"):
        folder = tmp_path / "portable_characters" / project
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(_poison_sheet()))

    service = CombatService(APP, tmp_path)
    table = TabletopService(service, tmp_path)
    match_id = service.create_factory_match(
        project_ids=["left"], opponent_actor_ids=[RIGHT], match_seed="MMX19-BITTER-TRACE",
        control_modes={LEFT: "MANUAL", RIGHT: "LOCAL_AUTO"})["match_id"]

    for turn in range(24):
        menu = table.state(match_id).get("menu") or {}
        buttons = [group["label"] for group in menu.get("actions") or []]
        if menu.get("actor_id") == LEFT and "Deliver the Dose" in buttons:
            return service, table, match_id, menu
        if menu.get("actor_id") == LEFT:
            engine = service._load_session(match_id).engine
            rival = engine.state.actors[RIGHT].position
            moves = [option for option in menu.get("moves") or [] if option.get("destination")]
            if moves:
                nearest = min(moves, key=lambda option: max(abs(option["destination"]["x"] - rival.x),
                                                            abs(option["destination"]["y"] - rival.y)))
                service.submit_intent(match_id, {
                    "intent_id": f"mmx19-approach-{turn}", "decision_id": menu["decision_id"],
                    "candidate_id": nearest["candidate_id"], "state_version": menu["state_version"],
                    "actor_id": LEFT, "target_ids": [], "destination": nearest["destination"]}, [], None)
                continue
            # Movement spent and still nothing to press: end the turn and let the fight come back around.
            service.submit_intent(match_id, {
                "intent_id": f"mmx19-end-{turn}", "decision_id": menu["decision_id"],
                "candidate_id": next(candidate.candidate_id for candidate in engine.legal_candidates()
                                     if candidate.actor_id == LEFT and candidate.display_name == "End turn"),
                "state_version": menu["state_version"], "actor_id": LEFT, "target_ids": []}, [], None)
            continue
        table.auto_step(match_id, 0)
    pytest.fail("Deliver the Dose never became available at the table")


def _button(menu, label):
    return next(group for group in menu["actions"] if group["label"] == label)


def test_the_table_offers_both_choices_and_the_replacement_button_explains_itself(in_range):
    _, _, _, menu = in_range
    base, variant = _button(menu, "Deliver the Dose"), _button(menu, "Deliver the Dose + Bitter Trace")
    assert base.get("description") and "Constitution saving throw" in base["description"]
    help_text = variant["description"]
    assert "removed" in help_text and "Constitution save" in help_text
    assert "Poison or Acid damage" in help_text  # the damage the replacement still deals
    assert "1 Dose Mark" in help_text and "no save to fail" in help_text
    assert "Cost:" in help_text and "Failed Save" not in help_text


def test_the_chosen_replacement_survives_a_service_commit_and_reload(in_range, tmp_path):
    from combat.gate5_service import CombatService

    service, table, match_id, menu = in_range
    before = service._load_session(match_id).engine.state.actors[RIGHT]
    hp, maximum = before.current_hp, before.maximum_hp
    group = _button(menu, "Deliver the Dose + Bitter Trace")
    option = group["options"][0]
    service.submit_intent(match_id, {
        "intent_id": "mmx19-bitter-trace", "decision_id": menu["decision_id"],
        "candidate_id": option["candidate_id"], "state_version": menu["state_version"],
        "actor_id": LEFT, "target_ids": option.get("target_ids") or []}, [], None)

    session = CombatService(APP, tmp_path)._load_session(match_id)  # a fresh service, reading saved state
    assert session.mechanical.replay()["status"] == "PASS"
    engine = session.engine
    foe = engine.state.actors[RIGHT]
    # The replacement keeps the ordinary attack damage...
    assert foe.current_hp < hp and foe.maximum_hp == maximum
    # ...and its guaranteed Dose Mark is still on the target after the commit.
    assert te_marks_bear(engine, foe)
    assert not [roll for roll in engine.rolls if roll.reason.startswith("SAVE:")]


def te_marks_bear(engine, foe):
    from combat import typed_executor as te

    return te.bears_mark(foe, LEFT, "Dose Mark")
