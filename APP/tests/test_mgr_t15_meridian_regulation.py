"""Meridian Regulation through native portable import, table intents and cold replay.

The initial sheets are deterministic source-backed combat starting fixtures, not
seeded afflictions or successful treatment receipts. Every impairment below is
produced by committing its printed source action. These fixtures do not certify
the complete character-creation UI/export pipeline.
"""
import json
import zipfile
from hashlib import sha256
from pathlib import Path

import pytest

from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.tabletop import ButtonStore
from combat.ext import qi_path
from tests.h1_support import sheet

ROOT = Path(__file__).resolve().parents[1]
MERIDIAN = "tianxia.path.qi_cultivation.feature.meridian_regulation"
CHAIN = "tianxia.talent.chains.chain_prison"
LUNG = "TAL_AIR_EMPTY_LUNG_EDICT"
SLOW = "TAL_ALCHEMY_BINDING_DREGS"
OWNER, TARGET, SOURCE = ("actor:factory.00000000-0000-0000-0000-00000000000" + s for s in ("1", "2", "3"))
QI = "resource:core.qi"
SUPPRESSED = "condition:typed.benefit_suppressed"
CHOICE = "choice:needle.meridian_regulation"
# Literal declarations make runtime rule inputs visible to the safe exporter.
RUNTIME_INPUTS = ("authority/typed_mechanics/rules_text.json",
                  "authority/Tianxia_Typed_Mechanics_Authority_R1.json",
                  "combat/rules/affliction_sources.json")


def fixture(tmp_path, source, *, con=14, strength=14, seed="MGR-MERIDIAN", owner_cl=2, owns=True,
            extra_sources=(), source_at=(5, 6)):
    prerequisite_ids = (["TAL_AIR_BREATH_STEALING_PALM", "TAL_AIR_BREATHLESS_CHAMBER"] if source == LUNG else [])
    if source == "TAL_IRON_FIST_NINE_BELL_MERIDIAN_PALM":
        prerequisite_ids = ["TAL_IRON_FIST_MERIDIAN_SEALING_PALM", "TAL_IRON_FIST_MERIDIAN_LOCK"]
    # The actual Qi profile chooses Intelligence or Charisma (not h1's generic
    # Constitution default), and has a minimum pool of twice its own Path CL.
    docs = [sheet([MERIDIAN] if owns else [], cl=owner_cl, key="INT", name="Regulator"),
            sheet([], cl=15, key="INT", name="Patient"),
            sheet([*prerequisite_ids, source, *extra_sources], cl=15, key="INT", dc=12, name="Afflictor")]
    for aid, doc, dex in zip((OWNER, TARGET, SOURCE), docs, (18, 8, 20)):
        cl = owner_cl if aid == OWNER else 15
        pb = 2 if cl < 5 else 3 if cl < 10 else 4 if cl < 15 else 5
        doc["identity"]["proficiency_bonus"] = pb
        for ability in doc["ability_scores_and_statistics"]["abilities"]:
            score = dex if ability["ability"] == "DEX" else (
                8 if aid == SOURCE and ability["ability"] == "INT" else
                con if aid == TARGET and ability["ability"] == "CON" else
                strength if aid == TARGET and ability["ability"] == "STR" else ability["score"])
            ability.update(score=score, modifier=(score - 10) // 2)
        key_modifier = -1 if aid == SOURCE else 2
        stats = doc["ability_scores_and_statistics"]
        stats["primary_resource"]["maximum"] = max(2 * cl, cl * key_modifier)
        stats["technique_save_dc"] = 8 + pb + key_modifier
        stats["technique_attack_bonus"] = pb + key_modifier
        folder = tmp_path / "portable_characters" / aid.removeprefix("actor:factory.")
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))
    combat = CombatService(ROOT, tmp_path)
    buttons = ButtonStore(tmp_path / "tabletop_buttons")
    for aid in (OWNER, TARGET, SOURCE):
        buttons.save_reactions(aid.removeprefix("actor:factory."), {"mode": "ask"}, set())
    combat.tabletop_maps.save({"map_id": "meridian-yard", "display_name": "Meridian Yard",
        "width_squares": 10, "height_squares": 10,
        "starts": {"team1": [[3, 6], [4, 6]], "team2": [list(source_at)]}})
    mid = combat.create_factory_match(project_ids=[aid.removeprefix("actor:factory.") for aid in (OWNER, TARGET)],
        opponent_actor_ids=[SOURCE], control_modes={aid: "MANUAL" for aid in (OWNER, TARGET, SOURCE)},
        arena_id="battlefield:map.meridian-yard", match_seed=seed, maximum_rounds=20)["match_id"]
    return combat, TabletopService(combat, tmp_path), mid


def cold(tmp_path, mid):
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    assert session.verify()["status"] == "PASS"
    assert session.mechanical.replay()["status"] == "PASS"
    return session.engine


def act(table, mid, cid, choose=None):
    menu = table.state(mid)["menu"]
    answers, prompts = [], []
    for _ in range(24):
        reply = table.act(mid, cid, menu["decision_id"], menu["state_version"], 0, answers)
        if reply["status"] != "REACTION_REQUIRED":
            assert reply["status"] == "COMMITTED", reply
            return prompts
        prompt = reply["reaction"]
        prompts.append(prompt)
        options = (prompt.get("choice") or {}).get("options") or []
        selected = choose(prompt, options) if choose else (
            [o["id"] for o in options[:max(1, (prompt.get("choice") or {}).get("minimum", 1))]] if options else None)
        answers.append({**prompt["context"], "selection": "USE" if selected else "DECLINE",
                        "option_ids": selected if isinstance(selected, list) else [selected] if selected else []})
    raise AssertionError("unresolved native choices")


def turn(table, mid, aid):
    for _ in range(8):
        menu = table.state(mid)["menu"]
        if menu["actor_id"] == aid:
            return
        act(table, mid, menu["end_turn"])
    raise AssertionError("missing turn")


def use(combat, table, mid, name, target, choose=None):
    engine = combat._load_session(mid).engine
    rows = [c for c in engine.legal_candidates()
            if engine.action_catalog.get(c.source_definition_id) is not None
            and engine.action_catalog[c.source_definition_id].display_name == name
            and target in c.target_ids]
    assert rows, (name, [a.display_name for a in engine.action_catalog.values()])
    return act(table, mid, rows[0].candidate_id, choose)


def test_controlling_source_hash():
    rules = json.loads((ROOT / RUNTIME_INPUTS[0]).read_text())
    assert sha256(rules[MERIDIAN].encode()).hexdigest() == (
        "9083648a7e14763c11c34d609432d649ffcc4de45e0d94b5f1d49601bc36b72b")


def test_native_chain_repeat_keeps_normal_success_bound_result(tmp_path):
    # Real seeded dice, bounded independent native fights; never inject a result.
    for attempt in range(12):
        combat, table, mid = fixture(tmp_path / str(attempt), CHAIN, strength=14, seed=f"MGR-MERIDIAN-CHAIN-{attempt}")
        turn(table, mid, SOURCE)
        use(combat, table, mid, "Chain Prison", TARGET)
        before = cold(tmp_path / str(attempt), mid)
        held = [c for c in before.state.actors[TARGET].conditions.values() if c.data.get("repeat_save")]
        if not held:
            continue
        turn(table, mid, OWNER)
        before = cold(tmp_path / str(attempt), mid)
        if held[0].instance_id not in before.state.actors[TARGET].conditions:
            continue
        qi = before.state.actors[OWNER].resources[QI]
        prompts = use(combat, table, mid, "Meridian Regulation", TARGET)
        asked = [p for p in prompts if p["context"]["reaction_source_id"] == CHOICE]
        assert asked and "Advantage" in json.dumps(asked)
        after = cold(tmp_path / str(attempt), mid)
        owner, target = after.state.actors[OWNER], after.state.actors[TARGET]
        assert owner.resources[QI] == qi - 1 and not owner.action_available
        roll = next(e for e in after.events if e.event_type == "SAVE_ROLLED" and MERIDIAN in e.source_definition_id)
        assert roll.payload["mode"] == "ADVANTAGE" and roll.payload["dc"] == 12
        assert roll.payload["original_save_source_id"] == held[0].source_definition_id
        if roll.payload["success"]:
            assert held[0].instance_id not in target.conditions
            assert any(c.condition_id == "condition:typed.bound" and c.source_actor_id == SOURCE
                       for c in target.conditions.values())
            return
        else:
            assert held[0].instance_id in target.conditions
    raise AssertionError("no successful native granted repeat in twelve deterministic starting fights")


def test_native_attack_penalty_is_selectable_and_suppresses_only_one_instance(tmp_path):
    for attempt in range(12):
        combat, table, mid = fixture(tmp_path / str(attempt), LUNG, seed=f"MGR-MERIDIAN-ATTACK-{attempt}")
        turn(table, mid, SOURCE)
        use(combat, table, mid, "Empty-Lung Edict", TARGET)
        turn(table, mid, OWNER)
        before = cold(tmp_path / str(attempt), mid)
        if not any(m.target_field == "attack_mode" and m.value == "DISADVANTAGE"
                   for m in before.state.actors[TARGET].modifiers.values()):
            continue
        penalties = [r for r in qi_path._suppressible(before, before.state.actors[TARGET])
                     if r[2] == "Disadvantage on attack rolls"]
        assert penalties, "a real source-owned attack penalty must be offered"
        selected, original, _, dc = penalties[0]
        siblings = {key: c.model_dump(mode="json") for key, c in before.state.actors[TARGET].conditions.items()}
        def choose(prompt, options):
            if prompt["context"]["reaction_source_id"] == CHOICE:
                assert selected in [o["id"] for o in options]
                return selected
            return options[0]["id"] if options else None
        use(combat, table, mid, "Meridian Regulation", TARGET, choose)
        after = cold(tmp_path / str(attempt), mid)
        target = after.state.actors[TARGET]
        roll = next(e for e in after.events if e.event_type == "SAVE_ROLLED" and MERIDIAN in e.source_definition_id)
        assert roll.payload["mode"] == "ADVANTAGE" and roll.payload["dc"] == dc
        assert roll.payload["original_save_source_id"] == original.source_definition_id
        assert {key: target.conditions[key].model_dump(mode="json") for key in siblings} == siblings
        if roll.payload["success"]:
            assert original.modifier_id not in target.modifiers
            markers = [c for c in target.conditions.values() if c.condition_id == SUPPRESSED]
            assert len(markers) == 1 and markers[0].data["model"]["modifier_id"] == original.modifier_id
            assert markers[0].data["until"] == "holder_turn_end"
            assert markers[0].data["model"]["source_actor_id"] == SOURCE
        else:
            assert original.modifier_id in target.modifiers
        turn(table, mid, TARGET)
        act(table, mid, table.state(mid)["menu"]["end_turn"])
        after = cold(tmp_path / str(attempt), mid)
        assert not any(c.condition_id == SUPPRESSED for c in after.state.actors[TARGET].conditions.values())
        if roll.payload["success"]:
            return
    raise AssertionError("no successful native attack-penalty suppression in twelve deterministic starting fights")


def test_native_speed_suppression_success_and_exact_next_turn_end(tmp_path):
    combat, table, mid = fixture(tmp_path, SLOW, con=100, strength=2, seed="MGR-MERIDIAN-SPEED")
    turn(table, mid, SOURCE)
    use(combat, table, mid, "Binding Dregs", TARGET)
    turn(table, mid, OWNER)
    before = cold(tmp_path, mid)
    [chosen] = [r for r in qi_path._suppressible(before, before.state.actors[TARGET]) if r[2] == "Speed reduced"]
    use(combat, table, mid, "Meridian Regulation", TARGET)
    target = cold(tmp_path, mid).state.actors[TARGET]
    [marker] = [c for c in target.conditions.values() if c.condition_id == SUPPRESSED]
    assert chosen[1].modifier_id not in target.modifiers
    turn(table, mid, TARGET)
    target = cold(tmp_path, mid).state.actors[TARGET]
    assert any(c.condition_id == SUPPRESSED for c in target.conditions.values()), "suppression ended at turn start"
    act(table, mid, table.state(mid)["menu"]["end_turn"])
    target = cold(tmp_path, mid).state.actors[TARGET]
    assert not any(c.condition_id == SUPPRESSED for c in target.conditions.values())


@pytest.mark.parametrize("symptom,path,label", [
    ("Speed -20", "speed", "Speed reduced"),
    ("No Reactions", "rule.no_reactions", "Cannot take Reactions"),
    ("Dexterity save Disadvantage", "rule.save_mode.DEX", "Disadvantage on saving throws"),
    ("Concentration save Disadvantage", "rule.concentration_mode", "Disadvantage on saving throws"),
])
def test_native_nonrepeat_disease_suppresses_one_field_and_restores_same_parent(tmp_path, symptom, path, label):
    source = "tianxia.talent.disease.weakening_sickness"
    combat, table, mid = fixture(tmp_path, source, con=100, seed="MGR-MERIDIAN-" + symptom)
    def choose_symptom(prompt, options):
        chosen = [o["id"] for o in options if symptom.lower() in str(o.get("label", o["id"])).lower()]
        # The native success question uses plain labels; the preparation menu
        # uses the printed symptom names. Both must retain this legal choice.
        if not chosen and path == "rule.no_reactions":
            chosen = [o["id"] for o in options if "reactions" in str(o.get("label", o["id"])).lower()]
        if not chosen and path == "speed":
            chosen = [o["id"] for o in options if "speed" in str(o.get("label", o["id"])).lower()]
        if not chosen and path == "rule.save_mode.DEX":
            chosen = [o["id"] for o in options if "dexterity" in str(o.get("label", o["id"])).lower()]
        if not chosen and path == "rule.concentration_mode":
            chosen = [o["id"] for o in options if "concentration" in str(o.get("label", o["id"])).lower()]
        return chosen[:1] or ([options[0]["id"]] if options else None)
    turn(table, mid, SOURCE)
    use(combat, table, mid, "Weakening Sickness", TARGET, choose_symptom)
    turn(table, mid, OWNER)
    before = cold(tmp_path, mid)
    target = before.state.actors[TARGET]
    [parent] = [c for c in target.conditions.values() if c.condition_id == "condition:typed.affliction"]
    assert not parent.data.get("repeat_save"), "the real initial successful save must produce the no-repeat branch"
    [option] = [r for r in qi_path._suppressible(before, target) if r[0].endswith("|" + path)]
    assert option[2] == label
    hp, expiry, parts = target.current_hp, parent.expires_on, parent.data["parts"]
    def select(prompt, options):
        return option[0] if prompt["context"]["reaction_source_id"] == CHOICE else (options[0]["id"] if options else None)
    use(combat, table, mid, "Meridian Regulation", TARGET, select)
    target = cold(tmp_path, mid).state.actors[TARGET]
    assert parent.instance_id in target.conditions, "suppression removed the underlying disease"
    current = target.conditions[parent.instance_id]
    assert current.expires_on == expiry and current.data["parts"] == parts
    assert target.current_hp == hp, "suppression healed or damaged the patient"
    [marker] = [c for c in target.conditions.values() if c.condition_id == SUPPRESSED]
    if path == "rule.no_reactions":
        assert target.reaction_available, "the suppressed denial still blocks Reactions"
    turn(table, mid, TARGET)
    assert any(c.condition_id == SUPPRESSED for c in cold(tmp_path, mid).state.actors[TARGET].conditions.values())
    act(table, mid, table.state(mid)["menu"]["end_turn"])
    after = cold(tmp_path, mid)
    target = after.state.actors[TARGET]
    assert not any(c.condition_id == SUPPRESSED for c in target.conditions.values())
    from combat.ext.suppressed_effects import alive
    if alive(after, marker.data["lifetime"]):
        assert parent.instance_id in target.conditions
        assert target.conditions[parent.instance_id].data["rule"] == parent.data["rule"]
    else:
        assert parent.instance_id not in target.conditions, "suppression revived an expired disease"


@pytest.mark.parametrize("cl,owns,offered", [(1, True, False), (2, False, False), (2, True, True)])
def test_native_import_requires_owned_record_and_cl2(tmp_path, cl, owns, offered):
    combat, table, mid = fixture(tmp_path, SLOW, owner_cl=cl, owns=owns)
    turn(table, mid, OWNER)
    engine = cold(tmp_path, mid)
    rows = [c for c in engine.legal_candidates()
            if engine.action_catalog.get(c.source_definition_id) is not None
            and engine.action_catalog[c.source_definition_id].display_name == "Meridian Regulation"]
    assert bool(rows) is offered
    if offered:
        assert any(TARGET in c.target_ids for c in rows), "an adjacent creature is outside actual Touch"
        assert not any(SOURCE in c.target_ids for c in rows), "a creature ten feet away is inside Touch"


def test_native_touch_includes_self_ally_and_foe(tmp_path):
    combat, table, mid = fixture(tmp_path, SLOW, source_at=(4, 5))
    turn(table, mid, OWNER)
    engine = cold(tmp_path, mid)
    targets = {target for c in engine.legal_candidates()
               if engine.action_catalog.get(c.source_definition_id) is not None
               and engine.action_catalog[c.source_definition_id].display_name == "Meridian Regulation"
               for target in c.target_ids}
    assert {OWNER, TARGET, SOURCE} <= targets


def test_native_repeat_one_seal_keeps_other_seals_and_patient_choice(tmp_path):
    source = "TAL_IRON_FIST_NINE_BELL_MERIDIAN_PALM"
    for attempt in range(12):
        data = tmp_path / str(attempt)
        combat, table, mid = fixture(data, source, seed=f"MGR-MERIDIAN-SEALS-{attempt}")
        def pick_seals(prompt, options):
            minimum = max(1, (prompt.get("choice") or {}).get("minimum", 1))
            legal = [o["id"] for o in options if "arm seal" not in str(o.get("label", o["id"])).lower()]
            return legal[:minimum] if options else None
        turn(table, mid, SOURCE)
        use(combat, table, mid, "Nine-Bell Meridian Palm", TARGET, pick_seals)
        turn(table, mid, OWNER)
        before = cold(data, mid)
        if not before.state.actors[TARGET].active:
            continue
        held = [c for c in before.state.actors[TARGET].conditions.values() if c.data.get("repeat_one")]
        if not held:
            continue
        [parent] = held
        assert len(parent.data["picks"]) >= 2
        offered = qi_path._regulable(before, before.state.actors[TARGET])
        assert parent.instance_id in [iid for iid, _ in offered]
        assert not [p for p in qi_path._suppressible(before, before.state.actors[TARGET])
                    if p[1].source_definition_id == parent.source_definition_id], "a repeat effect entered the no-repeat branch"
        selected = "condition:" + parent.instance_id
        removed = parent.data["picks"][-1]
        def choose(prompt, options):
            rid = prompt["context"]["reaction_source_id"]
            if rid == CHOICE:
                return selected
            if rid == "choice:needle.end_one_seal":
                assert prompt["context"]["reactor_id"] == TARGET
                return removed
            return options[0]["id"] if options else None
        prompts = use(combat, table, mid, "Meridian Regulation", TARGET, choose)
        after = cold(data, mid)
        roll = next(e for e in after.events if e.event_type == "SAVE_ROLLED" and MERIDIAN in e.source_definition_id)
        assert roll.payload["mode"] == "ADVANTAGE"
        assert roll.payload["original_save_source_id"] == parent.source_definition_id
        if not roll.payload["success"]:
            assert parent.instance_id in after.state.actors[TARGET].conditions
            continue
        assert any(p["context"]["reaction_source_id"] == "choice:needle.end_one_seal" for p in prompts)
        [remaining] = [c for c in after.state.actors[TARGET].conditions.values()
                       if c.condition_id == "condition:typed.affliction"]
        assert remaining.data["picks"] == [p for p in parent.data["picks"] if p != removed]
        assert remaining.source_actor_id == SOURCE and remaining.expires_on == parent.expires_on
        return
    raise AssertionError("no successful native repeat-one seal case in twelve deterministic fights")


@pytest.mark.parametrize("penalty,con", [("Poisoned", 14), ("Disadvantage on ability checks", 100)])
def test_native_poison_families_preserve_other_source_instances(tmp_path, penalty, con):
    dose = "POISON_BASE_DELIVER_THE_DOSE"
    strike = "tianxia.talent.poison.venomous_strike"
    for attempt in range(12):
        data = tmp_path / str(attempt)
        # Deliver the Dose is a ranged attack. Start outside melee reach so
        # this save/suppression fixture does not add unrelated close-range
        # Disadvantage to every setup attack.
        combat, table, mid = fixture(data, dose, con=con, extra_sources=[strike], source_at=(6, 6),
                                   seed=f"MGR-MERIDIAN-POISON-{penalty}-{attempt}")
        turn(table, mid, SOURCE)
        use(combat, table, mid, "Deliver the Dose", TARGET)
        turn(table, mid, OWNER)
        before = cold(data, mid)
        patient = before.state.actors[TARGET]
        if not patient.active:
            continue
        options = [r for r in qi_path._suppressible(before, patient) if r[2] == penalty]
        if not options:
            continue
        selected, original, _, dc = options[0]
        others = {key: c.model_dump(mode="json") for key, c in patient.conditions.items()
                  if key != original.instance_id}
        hp = patient.current_hp
        def choose(prompt, offered):
            if prompt["context"]["reaction_source_id"] == CHOICE:
                return selected
            return offered[0]["id"] if offered else None
        use(combat, table, mid, "Meridian Regulation", TARGET, choose)
        after = cold(data, mid)
        patient = after.state.actors[TARGET]
        roll = next(e for e in after.events if e.event_type == "SAVE_ROLLED" and MERIDIAN in e.source_definition_id)
        assert roll.payload["dc"] == dc and roll.payload["mode"] == "ADVANTAGE"
        assert roll.payload["original_save_source_id"] == original.source_definition_id
        assert patient.current_hp == hp
        assert {key: patient.conditions[key].model_dump(mode="json") for key in others} == others
        if not roll.payload["success"]:
            assert original.instance_id in patient.conditions
            continue
        assert original.instance_id not in patient.conditions
        [marker] = [c for c in patient.conditions.values() if c.condition_id == SUPPRESSED]
        assert marker.data["model"]["instance_id"] == original.instance_id
        assert marker.data["model"]["source_actor_id"] == SOURCE
        turn(table, mid, TARGET)
        act(table, mid, table.state(mid)["menu"]["end_turn"])
        patient = cold(data, mid).state.actors[TARGET]
        assert not any(c.condition_id == SUPPRESSED for c in patient.conditions.values())
        return
    raise AssertionError(f"no successful native {penalty} suppression in twelve deterministic fights")


def test_native_failed_suppression_pays_but_changes_no_target_effect(tmp_path):
    for attempt in range(12):
        data = tmp_path / str(attempt)
        combat, table, mid = fixture(data, LUNG, con=2, seed=f"MGR-MERIDIAN-FAIL-{attempt}")
        turn(table, mid, SOURCE)
        use(combat, table, mid, "Empty-Lung Edict", TARGET)
        turn(table, mid, OWNER)
        before = cold(data, mid)
        options = qi_path._suppressible(before, before.state.actors[TARGET])
        if not options:
            continue
        selected = options[0][0]
        target_before = before.state.actors[TARGET].model_dump(mode="json")
        qi = before.state.actors[OWNER].resources[QI]
        def choose(prompt, offered):
            return selected if prompt["context"]["reaction_source_id"] == CHOICE else (offered[0]["id"] if offered else None)
        use(combat, table, mid, "Meridian Regulation", TARGET, choose)
        after = cold(data, mid)
        roll = next(e for e in after.events if e.event_type == "SAVE_ROLLED" and MERIDIAN in e.source_definition_id)
        if roll.payload["success"]:
            continue
        assert roll.payload["mode"] == "ADVANTAGE"
        assert after.state.actors[OWNER].resources[QI] == qi - 1
        assert not after.state.actors[OWNER].action_available
        assert after.state.actors[TARGET].model_dump(mode="json") == target_before
        return
    raise AssertionError("no naturally failed native suppression in twelve deterministic fights")
