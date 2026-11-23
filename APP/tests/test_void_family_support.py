"""The shared Void-family fixture builds a compilable native Sphere owner."""
from combat.authority_projection import compile_project_character
from combat.ext import void_touched_cultivator as void
from tests.void_family_support import VOID_SPHERE, acquired, owner_sheet
from tests.worker2_support import OWNER


def test_owner_sheet_initializes_the_sphere_section_before_native_compilation(acquired):
    service, project = acquired
    document = owner_sheet(service, project)
    assert document["spheres_and_talents"] == {"sphere_record_ids": [VOID_SPHERE]}
    assert document["path_and_subpath"] == {"paths": service.get_state(project)["paths"]}
    assert document["identity"]["name"] == "Void cultivator"

    compiled = compile_project_character(service, project, document, actor_id=OWNER,
                                         reaction_plan={"ask": True})
    step = next(action for action in compiled["action_catalog"]
                if (action.get("parameters", {}).get("typed") or {}).get("source") == void.VOID_STEP)
    assert step["source_definition_id"] in compiled["actor_template"]["action_ids"]
    assert step["economy"] == "BONUS_ACTION"
    assert step["range_ft"] == 30
    assert list(step["costs"]) == [["resource:core.qi", 2]]
    assert step["parameters"]["typed"]["void_scar"] == "My reflection no longer appears."
