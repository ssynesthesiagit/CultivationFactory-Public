"""Owned selector statuses reuse the button's one record presentation.

Shared by status_text and generated_status_text through status_description;
no effect, saved action or fight state is changed.
"""
from . import hook
from .setting_choices import is_setting_action
from factory_authoring.record_display import rule_section as selector_rule_section


@hook("status_description")
def setting_status_description(engine, holder, row, data):
    action = engine.action_catalog.get(row.get("source_definition_id"))
    if holder is None or action is None or action.owner_id != holder.entity_id or not is_setting_action(action):
        return None
    from ..option_text import setting_display
    from .generated_status_text import SOURCES
    key = str(row.get("condition_id") or "").removeprefix("condition:typed.")
    display = setting_display(action.model_dump(mode="json"), SOURCES.get(key))
    if not display:
        return None
    return {"rules": display["text"], "player_card": display,
            "source_ability": action.display_name.partition(":")[0]}
