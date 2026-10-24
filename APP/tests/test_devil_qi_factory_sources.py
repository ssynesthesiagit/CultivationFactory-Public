"""Printed source eligibility on real Factory actions, table commits and cold reloads.

No browser is launched. Browser checks, if added, must be opt-in and run by the
lead outside the sandbox with /usr/bin/chromium.
"""
from types import SimpleNamespace

import pytest

from combat.ext.devil_heart_second_furnace import _qualifying_source
from tests import r1i_service_support as s
from tests.test_devil_qi_augment_service import (
    AUGMENT, DEVIL_QI, chosen_response, cold, play, seal, probe_action, commit_first_choice,
)


def fund_devil_qi(bundles):
    """Set up available fuel; leave the compiler's real action rows unchanged."""
    owner = next(b for b in bundles if b["actor_id"] == s.OWNER)
    next(r for r in owner["actor_template"]["resources"] if r["resource_id"] == DEVIL_QI)["initial"] = 2
    seal(owner)


@pytest.mark.parametrize("source, qualifies", [
    ("FIRE_TAL_FLAME_LASH", True),
    ("tianxia.talent.shadow.shadow_fang", True),
    ("tianxia.path.qi_cultivation.feature.domain_armament", True),
    (AUGMENT, True),
    ("tianxia.path.body_refining.feature.blood_pump", False),
    ("DISEASE_BASE_SOW_THE_FEVER_SEED", True),
    # A TAL_ prefix alone can name a base ability.
    ("TAL_LIGHTNING_LIGHTNING_LASH", True),
    ("weapon_attack", False),
])
def test_authority_category_overrides_runtime_namespace(source, qualifies):
    runtime_id = "action:typed.af93061f14." + source
    ctx = SimpleNamespace(action=SimpleNamespace(source_definition_id=runtime_id),
                          typed={"source": source}, source=runtime_id)
    assert _qualifying_source(ctx) is qualifies


def test_owning_menu_feature_and_opaque_forged_provenance():
    runtime_id = "action:typed.af93061f14.opaque"
    ctx = SimpleNamespace(action=SimpleNamespace(source_definition_id=runtime_id), source=runtime_id,
                          typed={"source": "opaque-option", "option_of": "FIRE_TAL_FLAME_LASH"})
    assert _qualifying_source(ctx)
    ctx.typed = {"source": "player-chosen-technique-id", "forged_from": "DISEASE_BASE_SOW_THE_FEVER_SEED"}
    assert _qualifying_source(ctx)  # A Forged Technique is its own printed category.
    ctx.typed = {"source": "weapon_attack", "weapon": {"name": "Sword"}}
    assert not _qualifying_source(ctx)
    ctx.typed = {"source": "unknown", "forged_from": "unknown"}
    assert not _qualifying_source(ctx)


def test_explicit_damage_attribution_uses_the_owning_feature():
    runtime_id = "action:typed.af93061f14.weapon"
    ctx = SimpleNamespace(action=SimpleNamespace(source_definition_id=runtime_id),
                          typed={"source": "weapon_attack"}, source=runtime_id,
                          effect_source="passive:tianxia.path.qi_cultivation.feature.domain_armament")
    assert _qualifying_source(ctx)
    ctx.effect_source = "passive:tianxia.path.body_refining.feature.blood_pump"
    assert not _qualifying_source(ctx)
    ctx.typed["forged_from"] = "FIRE_TAL_FLAME_LASH"
    assert not _qualifying_source(ctx)  # Explicit packet attribution overrides its enclosing technique.
    ctx.effect_source = "passive:DISEASE_BASE_SOW_THE_FEVER_SEED"
    assert _qualifying_source(ctx)


@pytest.mark.parametrize("source, name", [
    ("FIRE_TAL_FLAME_LASH", "Flame Lash"),
    ("tianxia.talent.shadow.shadow_fang", "Shadow Fang"),
    ("DISEASE_BASE_SOW_THE_FEVER_SEED", "Sow the Fever Seed"),
])
def test_compiled_sphere_talent_offers_pays_and_persists_damage_and_rider(tmp_path, source, name):
    combat, table, mid, _, _ = s.fixture(tmp_path, [AUGMENT, source], wide=True,
                                        bundle_transform=fund_devil_qi)
    engine = cold(combat, tmp_path, mid)
    action = next(a for a in engine.action_catalog.values()
                  if a.owner_id == s.OWNER and a.parameters.get("typed", {}).get("source") == source)
    assert action.source_definition_id.startswith("action:typed.")
    before_qi = engine.state.actors[s.OWNER].resources[DEVIL_QI]
    before_hp = engine.state.actors[s.FOE].current_hp
    start = len(engine.events)
    candidate = s.candidate(table, mid, name, s.FOE)
    menu = table.state(mid)["menu"]
    paused = table.act(mid, candidate, menu["decision_id"], menu["state_version"], 0, [])
    assert paused["status"] == "REACTION_REQUIRED", paused
    context = paused["reaction"]["context"]
    assert context["checkpoint"].endswith(":offer"), paused
    assert paused["reaction"]["action"] == name
    assert paused["reaction"]["affected"] == "Foe"
    assert paused["reaction"]["reaction"] == "Devil-Qi Augment"
    assert "Spend 1 Devil Qi" in str(paused["reaction"])
    # Pending intent did not commit damage/payment. Resume from a fresh service.
    pending = cold(combat, tmp_path, mid)
    assert pending.state.actors[s.OWNER].resources[DEVIL_QI] == before_qi
    assert pending.state.actors[s.FOE].current_hp == before_hp
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from tests.h1_support import ROOT
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    prompts = play(combat, table, mid, candidate, "Reactions")
    assert sum(str(p.get("context", {}).get("checkpoint", "")).endswith(":offer") for p in prompts) == 1
    engine = cold(combat, tmp_path, mid)
    owner, foe = engine.state.actors[s.OWNER], engine.state.actors[s.FOE]
    assert owner.resources[DEVIL_QI] == before_qi - 1
    assert owner.turn_flags["typed_once_turn:devil_qi_augment"] is True
    commits = [e for e in engine.events[start:] if e.event_type == "DAMAGE_COMMITTED" and s.FOE in e.target_ids]
    added = [e for e in commits if e.payload.get("display_source_id") == AUGMENT + ".damage"]
    assert added and sum(e.payload["hp_damage"] for e in added) > 0
    assert any(e.source_definition_id == action.source_definition_id for e in commits)
    assert before_hp - foe.current_hp == sum(e.payload["hp_damage"] for e in commits)
    rider = next(c for c in foe.conditions.values() if c.condition_id == "condition:typed.reaction_denied")
    assert rider.source_definition_id == AUGMENT + ".no_reactions"
    assert rider.expires_on == f"START_OF_TURN_AT:{s.FOE}:1"


def test_real_compiled_basic_attack_does_not_offer(tmp_path):
    combat, table, mid, _, _ = s.fixture(tmp_path, [AUGMENT], wide=True, foe_ac=1,
                                        owner_kit={"starting_kit": {"items": [
                                            {"item_id": "tianxia.mortal.weapon.jian", "quantity": 1}]}},
                                        bundle_transform=fund_devil_qi)
    engine = cold(combat, tmp_path, mid)
    actions = [a for a in engine.action_catalog.values() if a.owner_id == s.OWNER]
    action = next(a for a in actions if a.parameters.get("typed", {}).get("source") == "tianxia.mortal.weapon.jian"
                  and a.economy.value == "ACTION"
                  and any(effect.get("type") == "attack" and any(
                      hit.get("type") == "damage" and hit.get("weapon_damage")
                      for hit in effect.get("on_hit", []))
                          for effect in a.parameters.get("typed", {}).get("effects", [])))
    assert action.display_name == "Jian (Straight Sword) attack"
    assert action.source_definition_id.startswith("action:typed.")
    before_qi = engine.state.actors[s.OWNER].resources[DEVIL_QI]
    before_hp = engine.state.actors[s.FOE].current_hp
    candidate = s.candidate(table, mid, action.display_name, s.FOE)
    answers, prompts = [], []
    for _ in range(10):
        menu = table.state(mid)["menu"]
        result = table.act(mid, candidate, menu["decision_id"], menu["state_version"], 0, answers)
        if result["status"] == "COMMITTED":
            break
        assert result["status"] == "REACTION_REQUIRED", result
        prompt = result["reaction"]
        prompts.append(prompt)
        assert "DEVIL_QI_AUGMENT" not in str(prompt)
        options = prompt.get("choice", {}).get("options", [])
        answers.append(chosen_response(result, options[0]["label"]) if options else
                       {**prompt["context"], "selection": "DECLINE"})
    else:
        raise AssertionError("too many table prompts")
    engine = cold(combat, tmp_path, mid)
    assert engine.state.actors[s.FOE].current_hp < before_hp
    assert engine.state.actors[s.OWNER].resources[DEVIL_QI] == before_qi
    assert not engine.state.actors[s.OWNER].turn_flags.get("typed_once_turn:devil_qi_augment")
    assert not any(c.condition_id == "condition:typed.reaction_denied"
                   for c in engine.state.actors[s.FOE].conditions.values())


def test_named_hidden_strike_offers_after_declining_enclosing_hit_and_cold_reloads(tmp_path):
    hidden = "tianxia.subpath.qi.ninpo_adept.feature.hidden_strike"

    def prepare(bundles):
        fund_devil_qi(bundles)
        owner = next(b for b in bundles if b["actor_id"] == s.OWNER)
        # Establish printed concealment through a real table action, without
        # patching visibility, attack resolution or Hidden Strike's damage.
        probe_action(owner, "Concealment Setup", "test:concealment_setup", [
            {"type": "condition", "applies_to": "self", "condition": "invisible",
             "expires_on": "START_OF_SOURCE_NEXT_TURN"}])

    combat, table, mid, _, _ = s.fixture(tmp_path, [AUGMENT, "FIRE_TAL_FLAME_LASH", hidden],
                                        wide=True, foe_ac=1, bundle_transform=prepare)
    commit_first_choice(table, mid, s.candidate(table, mid, "Concealment Setup", s.FOE))
    before = cold(combat, tmp_path, mid)
    assert any(c.condition_id == "condition:typed.invisible"
               for c in before.state.actors[s.OWNER].conditions.values())
    start = len(before.events)
    candidate = s.candidate(table, mid, "Flame Lash", s.FOE)
    answers, prompts = [], []
    for _ in range(16):
        menu = table.state(mid)["menu"]
        result = table.act(mid, candidate, menu["decision_id"], menu["state_version"], 0, answers)
        if result["status"] == "COMMITTED":
            break
        assert result["status"] == "REACTION_REQUIRED", result
        prompt = result["reaction"]
        prompts.append(prompt)
        checkpoint = str(prompt["context"].get("checkpoint", ""))
        if checkpoint.endswith(":offer"):
            count = sum(str(p["context"].get("checkpoint", "")).endswith(":offer") for p in prompts)
            answers.append({**prompt["context"], "selection": "DECLINE"} if count == 1 else
                           chosen_response(result, "add damage"))
        elif checkpoint.endswith(":damage_type"):
            answers.append(chosen_response(result, "psychic"))
        elif checkpoint.endswith(":rider"):
            answers.append(chosen_response(result, "Reactions"))
        elif prompt["reaction"] == "Hidden Strike":
            # Its printed rider is mandatory. Choose a different benefit so
            # reaction denial below can only come from Devil-Qi Augment.
            answers.append(chosen_response(result, "Vanishing Posture"))
        elif prompt.get("choice") and not prompt["choice"].get("allow_decline"):
            answers.append(chosen_response(result, prompt["choice"]["options"][0]["label"]))
        else:
            answers.append({**prompt["context"], "selection": "DECLINE"})
    else:
        raise AssertionError("too many table prompts")
    offers = [p for p in prompts if str(p["context"].get("checkpoint", "")).endswith(":offer")]
    assert len(offers) == 2  # The second offer must come from the named passive packet.
    assert all(p["action"] == "Flame Lash" and p["affected"] == "Foe"
               and p["reaction"] == "Devil-Qi Augment" and "1 Devil Qi" in p["moment"] for p in offers)
    engine = cold(combat, tmp_path, mid)
    commits = [e for e in engine.events[start:] if e.event_type == "DAMAGE_COMMITTED"
               and s.FOE in e.target_ids]
    named = next(e for e in commits if e.payload.get("display_source_id") == "passive:" + hidden)
    added = next(e for e in commits if e.payload.get("display_source_id") == AUGMENT + ".damage")
    assert named.payload["hp_damage"] > 0 and added.payload["hp_damage"] > 0
    assert named.sequence < added.sequence
    assert before.state.actors[s.FOE].current_hp - engine.state.actors[s.FOE].current_hp == sum(
        e.payload["hp_damage"] for e in commits)
    assert engine.state.actors[s.OWNER].resources[DEVIL_QI] == 1
    assert engine.state.actors[s.OWNER].turn_flags["typed_once_turn:devil_qi_augment"] is True
    rider = next(c for c in engine.state.actors[s.FOE].conditions.values()
                 if c.source_definition_id == AUGMENT + ".no_reactions")
    assert rider.expires_on == f"START_OF_TURN_AT:{s.FOE}:1"
