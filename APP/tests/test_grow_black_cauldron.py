"""Saved Grow regression: an acquired Qi Path reaches the Cauldron capstone."""
from combat.ext import black_cauldron
from tests.test_grow3_levelup import BODY, PID, QI, TALENTS, baseline, choices, service
from tests.test_grow3_review_fixes import install


def test_saved_grow_unlocks_black_cauldron_capstone_in_cold_combat(tmp_path):
    sheet = baseline(BODY)
    sheet["identity"].update(cultivation_level=16, proficiency_bonus=5, realm="Nascent Soul")
    body_row = {"path_id": BODY, "effective_cl": 16, "attainment": 16, "key_ability": "CON"}
    sheet["identity"]["paths"] = [body_row]
    # A finalized sheet has a separate, rules-bearing Path list in addition to identity's rows.
    sheet["path_and_subpath"].update(path_record_id=BODY, paths=[dict(body_row)])
    install(tmp_path, sheet)

    grow = service(tmp_path, BODY)
    template = grow.advancement(PID)["level_up"]["add_templates"][QI]
    subpath = next(row for group in template["subpaths"] for row in group["options"]
                   if row["id"] == black_cauldron.PARENT)
    assert subpath["legal"] and subpath["requires_confirmation"]
    view = grow.level_up(PID, {
        "cl": 17,
        "add_path_id": QI,
        "add_access": "gm",
        "add_source_id": "Black cauldron imprint",
        "add_confirmed": True,
        "access_confirmed": True,
        "subpaths": {QI: subpath["id"]},
        "feature_choices": {row["feature_id"]: row["options"][0]["id"]
                            for row in [*template["feature_choices"], *subpath["build_choices"]]},
        "talent_ids": [TALENTS[0]["canonical_talent_id"]],
    })
    grow.level_up(PID, choices(view, 1))

    cold = service(tmp_path, BODY)
    bundle = cold.combat.compile_factory_actor(PID)
    assert bundle["cl"] == 18
    [passive] = [row for row in bundle["typed_passives"]
                 if row["feature_id"] == black_cauldron.FIELD and row["block"] == black_cauldron.BLOCK]
    assert passive["numbers"]["cl"] == 18
    [move] = [row for row in bundle["action_catalog"] if row["display_name"] == "Move Cauldron Anchor"]
    assert move["source_definition_id"] in bundle["actor_template"]["action_ids"]
