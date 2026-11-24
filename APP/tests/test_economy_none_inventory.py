"""The instant toggle path trusts is_setting_action; no compiled NONE row may also be an immediate activation."""
from tools.economy_none_inventory import IMMEDIATE, actions
from combat.ext.setting_choices import is_setting_action


def test_no_immediate_activation_claims_to_store_a_setting():
    contradictions = sorted({action.source_definition_id for _, action in actions() if is_setting_action(action)
                             and {e.get('type') for e in ((action.parameters or {}).get('typed') or {}).get('effects') or []} & IMMEDIATE})
    assert contradictions == []
