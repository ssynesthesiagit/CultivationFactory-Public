"""Automatic Scribe choices use the owner's answer transport, never global facts.

The deterministic controller stands in for an informed owner-side provider. It
attests to this writing only when its own supplied information establishes the
formula; the ordinary local controller handles the unknown case. No model calls.
"""
import json

import pytest

from combat.gate2_runtime_models import ReactionDecision
from combat.gate4_adapters import ManualControllerAdapter
from combat.gate5_service import AI_RESPONSE_SCHEMA
from combat.ext import talisman_scribe
from tests.hunt12_support import ME, candidate, reload, send
from tests.test_mgr_t14_talisman_scribe import _learned_talismans, _script_check, _table


@pytest.mark.parametrize("mode", ["LOCAL_AUTO", "API_AUTO"])
@pytest.mark.parametrize("personally_known", [True, False])
def test_automatic_scribe_can_attest_personal_knowledge_but_unknown_defaults_no(
        tmp_path, mode, personally_known):
    combat, table, mid = _table(tmp_path, _learned_talismans(),
                                seed=f"SCRIBE-AUTO-{mode}-{personally_known}")
    combat.set_controller_mode(mid, actor_id=ME, controller_mode=mode)
    original = combat.controller
    seen = []

    class OwnerKnowledgeController:
        def choose_reaction(self, context):
            if context.reaction_source_id.endswith("talisman_scribe_known_formula"):
                assert context.reactor_id == ME
                # The same full legal pool must reach both automatic modes.
                assert set(context.legal_option_ids) == {talisman_scribe.YES, talisman_scribe.NO}
                if personally_known:
                    decision = ReactionDecision(
                        checkpoint=context.checkpoint, reactor_id=context.reactor_id,
                        reaction_source_id=context.reaction_source_id, selection="USE",
                        option_ids=(talisman_scribe.YES,))
                    choice = ManualControllerAdapter(
                        lambda _: ("", ()), reaction_chooser=lambda _: decision
                    ).choose_reaction(context)
                else:
                    # No knowledge provider: exercise the shipped local preference.
                    choice = original.choose_reaction(context)
                seen.append(choice.decision.option_ids)
                return choice
            return original.choose_reaction(context)

        def __getattr__(self, name):
            return getattr(original, name)

    combat.controller = OwnerKnowledgeController()
    if mode == "API_AUTO":
        class OfflineActionProvider:
            def status(self):
                return {"ready": True}

            def complete_json(self, *, prompt_text, **kwargs):
                frame = json.loads(prompt_text.split("\n\n", 1)[1])
                action = next(c for c in frame["legal_candidates"]
                              if c["display_name"] == "Read the Script")
                payload = {key: action[key] for key in
                           ("candidate_id", "actor_id", "target_ids", "destination", "option_ids")}
                payload.update(decision_id=frame["decision_id"], state_version=frame["state_version"])
                return {"value": {"schema": AI_RESPONSE_SCHEMA, "action_intent": payload},
                        "provider_id": "test:offline", "model": "fake", "request_sha256": "test-request"}

        combat.ai_provider = OfflineActionProvider()
    chosen = candidate(combat, mid, lambda c: c.display_name == "Read the Script")
    result = send(combat, table, mid, chosen, auto=True)
    assert result["status"] == "COMMITTED", result
    expected_answer = talisman_scribe.YES if personally_known else talisman_scribe.NO
    assert seen and all(answer == (expected_answer,) for answer in seen)
    engine = reload(tmp_path, mid)
    checks = _script_check(engine)
    assert len(checks) == 1
    assert checks[0].payload["actor"]["mode"] == ("ADVANTAGE" if personally_known else "NORMAL")
