"""Regression coverage for INS7E review documentation findings.

Each module-contract assertion is paired with the wiring it describes: a
documented seam must have a real dispatch site in the engine and a real
consumer, and a hook point that only one plug-in used privately must stay gone.
That way the contract text cannot stay green after the seam is deleted,
renamed or replaced by a plug-in-private checkpoint again.
"""

from pathlib import Path
from types import SimpleNamespace
import ast

import pytest


APP = Path(__file__).resolve().parents[1]


def combat_sources():
    return "\n".join(path.read_text() for path in sorted((APP / "combat").rglob("*.py")))


def test_essence_state_is_a_documented_shared_helper_and_enforces_provenance():
    from combat.ext import essence_state

    module = ast.parse((APP / "combat/ext/essence_state.py").read_text())
    doc = (ast.get_docstring(module) or "").lower()
    assert "shared" in doc
    assert "qi_devourer" in doc

    def actor(types=(), summon=None, recorded=None):
        conditions = {}
        if recorded:
            conditions["profile"] = SimpleNamespace(condition_id=essence_state.PROFILE, data=recorded)
        return SimpleNamespace(creature_types=tuple(types), summon=summon or {}, conditions=conditions)

    assert essence_state.profile(actor())["genuine"] == 1                 # ordinary creature
    assert essence_state.profile(actor(types=["construct"]))["genuine"] == 0
    assert essence_state.profile(actor(types=["construct"], recorded={"independent": 1}))["genuine"] == 1
    assert essence_state.profile(actor(summon={"disposable": 1}))["genuine"] == 0
    with pytest.raises(ValueError):
        essence_state.record_profile(None, {"kind": 1.5})                # floats are not provenance
    with pytest.raises(ValueError):
        essence_state.restore(None, {})                                  # only a fully rebuilt source restores


def test_attack_target_interception_hook_contract_is_in_module_docstring():
    module = ast.parse((APP / "combat/ext/__init__.py").read_text())
    doc = ast.get_docstring(module) or ""
    assert "attack_target_interception(engine, attacker, target, source_id, intent, index)" in doc
    assert "or None" in doc
    assert "inert" in doc
    assert "ownership" in doc
    assert "shared_space(engine, left, right) -> True | None" in doc
    assert "native occupancy rules" in doc
    # The documented strict checkpoint is really dispatched, and it has a provider.
    assert 'ext.run_checkpoint("attack_target_interception"' in combat_sources()
    assert '@hook("attack_target_interception")' in combat_sources()


def test_shared_space_contract_preserves_native_and_pair_only_boundaries():
    module = ast.parse((APP / "combat/ext/__init__.py").read_text())
    doc = ast.get_docstring(module) or ""
    contract = " ".join(doc.split("shared_space(engine, left, right)", 1)[1]
                        .split("observer_information(", 1)[0].split())
    assert "True | None" in contract
    assert "live explicit sharing relationship" in contract
    assert "for that pair" in contract
    assert "None (the default for every creature pair)" in contract
    assert "native occupancy rules, including existing rider/mount validation, unchanged" in contract
    assert "never moves a creature, removes terrain or grants passage to any third occupant" in contract
    # Only explicit True answers change occupancy; the shipped query returns pills of True/None.
    sources = combat_sources()
    assert "ext.run_strict('shared_space'" in sources
    assert '@hook("shared_space")' in sources or "@hook('shared_space')" in sources


def test_study_observation_hooks_are_in_the_module_contract_not_only_comments():
    from combat import ext

    module = ast.parse((APP / "combat/ext/__init__.py").read_text())
    doc = " ".join((ast.get_docstring(module) or "").split())
    assert "creature_studied(ctx, target) -> None" in doc
    assert "No subscriber means no information or state change" in doc
    assert "visible_defensive_posture(engine, target) -> True/None" in doc
    assert "Missing facts are inert" in doc
    # The notification and the posture query really run, and the notification has its consumer.
    sources = combat_sources()
    assert 'run_strict("creature_studied"' in sources
    assert 'run_strict("visible_defensive_posture"' in sources
    assert ext.subscribers("creature_studied")


def test_resonance_breaker_has_no_private_hook_point_and_settles_from_the_shared_check():
    from combat import ext
    from combat.ext import resonance_breaker

    sources = combat_sources()
    assert "resonance_breaker_check" not in sources
    assert not hasattr(resonance_breaker, "identified")            # the retired one-off hook handler
    assert resonance_breaker.opposed in ext.subscribers("opposed_check_resolved")
    # The shared settlement helper it calls is the documented opposed-check one.
    assert "settle(ctx, target, actor_check, result.success" in (
        APP / "combat/ext/resonance_breaker.py").read_text()
