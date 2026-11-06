from combat.tabletop_service import TabletopService
from types import SimpleNamespace

import pytest


def test_an_extension_choice_prompt_lists_its_options_by_name():
    service = TabletopService.__new__(TabletopService)
    service._names_for = lambda match_id: ({"actor:a": "Tabik Damu", "actor:b": "Bone Guard"}, {})
    context = {"checkpoint": "needle:exploit:861:actor:a:actor:b", "reactor_id": "actor:a", "reaction_source_id": "choice:needle.exploit",
               "extension_choice": {"option_ids": ["x.disarm", "x.trip"], "minimum_selections": 1, "maximum_selections": 1,
                                    "allow_decline": True, "preferred_option_ids": ["x.trip"]},
               "choice_trigger": {"target_id": "actor:b", "labels": {"x.disarm": "Disarm", "x.trip": "Trip (expends Martial Focus)"},
                                  "prompt": "choose an Exploit"}}
    prompt = service._reaction_prompt("match:1", context)
    assert prompt["reaction"] == "Exploit" and prompt["by"] == "Bone Guard" and prompt["moment"] == "choose an Exploit"
    assert [o["label"] for o in prompt["choice"]["options"]] == ["Disarm", "Trip (expends Martial Focus)"]
    assert prompt["context"] == {key: context[key] for key in ("checkpoint", "reactor_id", "reaction_source_id")}


@pytest.mark.parametrize("trigger,expected", [
    ({}, "Wide Open"),
    ({"feature_id": "TAL_PLUGIN_FEATURE"}, "Plugin Feature"),
    ({"feature_id": "TAL_PLUGIN_FEATURE", "name": "Choose a beneficiary"}, "Choose a beneficiary"),
])
def test_instance_choice_names_use_context_then_feature_without_actor_suffix(trigger, expected):
    service = TabletopService.__new__(TabletopService)
    service._names = {}
    engine = SimpleNamespace(state=SimpleNamespace(actors={"actor:h5-player": SimpleNamespace(display_name="H5-Player")}),
                             action_catalog={}, typed_reaction_rows={},
                             typed_passive_rows={"actor:h5-player": [{"feature_id": "TAL_PLUGIN_FEATURE", "name": "Plugin Feature"}]})
    service.combat = SimpleNamespace(_load_session=lambda mid: SimpleNamespace(engine=engine))
    context = {"checkpoint": "PLUGIN@1", "reactor_id": "actor:h5-player",
               "reaction_source_id": "choice:needle.wide_open:1:actor:factory.h5-player",
               "extension_choice": {"option_ids": ["ally"]}, "choice_trigger": trigger}
    assert service._reaction_prompt("match:1", context)["reaction"] == expected
