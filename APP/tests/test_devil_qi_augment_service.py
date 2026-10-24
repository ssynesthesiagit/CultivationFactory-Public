"""Devil-Qi Augment through the real table/session commit and cold reload path."""
import pytest
import copy

from combat.canonical import canonical_sha256
from combat.gate5_service import FACTORY_ACTOR_PREFIX
from combat.ext import qi_path
from tests import r1i_service_support as s

AUGMENT = "tianxia.subpath.qi.devil_heart_second_furnace.feature.devil_qi_augment"
DEVIL_QI = "resource:named.devil_qi"
COUNTER = "tianxia.subpath.qi.test.devil_qi_counter"


def seal(bundle):
    bundle.pop("bundle_sha256", None)
    bundle["bundle_sha256"] = canonical_sha256(bundle)


def probe_action(bundle, name, source, effects, *, economy="NONE", numbers=None, weapon=None):
    typed = {"source": source, "numbers": numbers or {"cl": 6, "pb": 4, "save_dc": 18, "attack_bonus": 100},
             "duration": {"kind": "instant"}, "effects": effects}
    if weapon:
        typed["weapon"] = weapon
    bundle["action_catalog"].append({"source_definition_id": source, "display_name": name,
        "owner_id": bundle["actor_id"], "economy": economy, "resolution_kind": "TYPED",
        "target_kind": "HOSTILE_ENTITY", "range_ft": 60,
        "parameters": {"typed": typed, "expected_damage": 8}})
    bundle["actor_template"]["action_ids"].append(source)
    seal(bundle)


def add_counter_probe(bundles):
    """Owned generic cultivation reaction, delivered on an opponent's real turn."""
    add_probe(bundles)
    owner = next(b for b in bundles if b["actor_id"] == s.OWNER)
    owner["typed_reactions"].append({"block": "generic", "kind": "attacked", "feature_id": COUNTER,
        "name": "Second Cultivation Counter", "ask": True, "range_ft": 60,
        "numbers": {"cl": 6, "pb": 4, "save_dc": 18, "attack_bonus": 100},
        "effects": [{"type": "damage", "applies_to": "target", "flat": 3, "damage_types": ["force"]},
                    {"type": "speed", "applies_to": "target", "flat": -5, "expires_on": "UNTIL_REMOVED"}]})
    probe_action(owner, "Native Speed Bonus", "test:native_speed_bonus",
                 [{"type": "speed", "applies_to": "target", "flat": 15, "expires_on": "UNTIL_REMOVED"}])
    for bundle in bundles:
        if bundle["actor_id"] != s.OWNER:
            probe_action(bundle, "Trigger Cultivation Counter", "test:trigger_counter." + bundle["actor_id"],
                [{"type": "attack", "attack_kind": "cultivation", "on_hit": [
                    {"type": "damage", "applies_to": "target", "flat": 1, "damage_types": ["force"]}]}])
    seal(owner)


def damage_totals(engine, start):
    events = engine.events[start:]
    rolls = [e for e in events if e.event_type == "DAMAGE_ROLLED"
             and str(e.payload.get("display_source_id", "")).startswith(AUGMENT)]
    # Works on the defective revision too, whose added damage had no identity.
    if not rolls:
        rolls = [e for e in events if e.event_type == "DAMAGE_ROLLED"
                 and any(str(e.payload.get("expression", "")).startswith(str(n) + "d8+") for n in (2, 3, 4))]
    rolled = sum(int(e.payload["total"]) for e in rolls)
    commits = [e for e in events if e.event_type == "DAMAGE_COMMITTED" and s.FOE in e.target_ids]
    added = sum(int(e.payload.get("hp_damage", 0)) for e in commits if e.payload.get("damage_type") == "PSYCHIC")
    original = sum(int(e.payload.get("hp_damage", 0)) for e in commits if e.payload.get("damage_type") != "PSYCHIC")
    return rolled, added, original


def assert_original_damage_unchanged(engine, start, original):
    rolls = [e for e in engine.events[start:] if e.event_type == "DAMAGE_ROLLED"
             and str(e.payload.get("reason", "")).rsplit(":", 1)[-1] in ("1", "2")]
    assert len(rolls) == 2
    assert original == sum(int(e.payload["total"]) for e in rolls)


def assert_plain_augment_history(engine, source):
    from combat.history_feed import format_history_feed
    events = [e.model_dump(mode="json") for e in engine.events
              if e.source_definition_id == source or e.payload.get("display_source_id") == source]
    assert events
    feed = format_history_feed(events, [], pre_state=None, post_state=engine.state.model_dump(mode="json"),
        actor_names={aid: actor.display_name for aid, actor in engine.state.actors.items()}, definition_names={})
    if source.rsplit(".", 1)[-1] in ("push", "pull"):
        assert any("moved by force" in e["summary"] for e in feed)
    else:
        assert any("Devil-Qi Augment" in e["summary"] for e in feed)
    assert not any("tianxia." in e["summary"] or "condition:typed" in e["summary"] for e in feed)


def add_probe(bundles):
    owner = next(row for row in bundles if row["actor_id"] == s.OWNER)
    pool = next(row for row in owner["actor_template"]["resources"] if row["resource_id"] == DEVIL_QI)
    pool["initial"] = 2
    action_id = "tianxia.path.qi_cultivation.feature.devil_qi_test_bolt"
    owner["action_catalog"].append({
        "source_definition_id": action_id, "display_name": "Test Cultivation Bolt", "owner_id": s.OWNER,
        "economy": "ACTION", "resolution_kind": "TYPED", "target_kind": "HOSTILE_ENTITY", "range_ft": 60,
        "parameters": {"typed": {"source": action_id, "numbers": {"cl": 6, "pb": 4, "save_dc": 18, "attack_bonus": 100},
                                 "duration": {"kind": "instant"}, "effects": [
                                     {"type": "attack", "attack_kind": "cultivation", "count": 2,
                                      "on_hit": [{"type": "damage", "applies_to": "target", "flat": 3,
                                                  "damage_types": ["force"], "evidence": "Test Cultivation Bolt deals 3 Force damage"}]},
                                 ]}, "expected_damage": 5}
    })
    owner["actor_template"]["action_ids"].append(action_id)
    plain_id = "action:basic.weapon_attack.test"
    owner["action_catalog"].append({
        "source_definition_id": plain_id, "display_name": "Test Plain Weapon Attack", "owner_id": s.OWNER,
        "economy": "NONE", "resolution_kind": "TYPED", "target_kind": "HOSTILE_ENTITY", "range_ft": 60,
        "parameters": {"typed": {"source": "weapon_attack", "numbers": {"cl": 6, "pb": 4, "save_dc": 18},
                                 "duration": {"kind": "instant"}, "effects": [
                                     {"type": "damage", "applies_to": "target", "flat": 1,
                                      "damage_types": ["slashing"], "evidence": "Test Plain Weapon Attack deals 1 Slashing damage"},
                                 ]}, "expected_damage": 1}
    })
    owner["actor_template"]["action_ids"].append(plain_id)
    second = copy.deepcopy(next(row for row in owner["action_catalog"] if row["source_definition_id"] == action_id))
    second_id = "tianxia.subpath.qi.test.devil_qi_second_bolt"
    second["source_definition_id"] = second_id
    second["display_name"] = "Second Cultivation Bolt"
    second["economy"] = "NONE"
    second["parameters"]["typed"]["source"] = second_id
    owner["action_catalog"].append(second)
    owner["actor_template"]["action_ids"].append(second_id)
    owner.pop("bundle_sha256", None)
    owner["bundle_sha256"] = canonical_sha256(owner)


def add_consecrated_probe(bundles):
    add_probe(bundles)
    owner = next(row for row in bundles if row["actor_id"] == s.OWNER)
    foe = next(row for row in bundles if row["actor_id"] == s.FOE)
    foe["actor_template"]["saving_throws"]["CON"] = 100
    ward_id = "test:consecrated_ward"
    owner["action_catalog"].append({
        "source_definition_id": ward_id, "display_name": "Test Consecrated Ward", "owner_id": s.OWNER,
        "economy": "NONE", "resolution_kind": "TYPED", "target_kind": "HOSTILE_ENTITY", "range_ft": 60,
        "parameters": {"typed": {"source": ward_id, "numbers": {"cl": 6, "pb": 4, "save_dc": 18},
                                 "duration": {"kind": "instant"}, "effects": [
                                     {"type": "condition", "applies_to": "target", "condition": "restrained",
                                      "condition_data": {"label": "Consecrated Ward", "source_cl": 6},
                                      "expires_on": "UNTIL_REMOVED"},
                                 ]}, "expected_damage": 0}
    })
    owner["actor_template"]["action_ids"].append(ward_id)
    owner.pop("bundle_sha256", None)
    owner["bundle_sha256"] = canonical_sha256(owner)
    foe.pop("bundle_sha256", None)
    foe["bundle_sha256"] = canonical_sha256(foe)


def add_immune_probe(bundles):
    add_probe(bundles)
    owner = next(row for row in bundles if row["actor_id"] == s.OWNER)
    immune_id = "test:psychic_immunity"
    owner["action_catalog"].append({
        "source_definition_id": immune_id, "display_name": "Test Psychic Immunity", "owner_id": s.OWNER,
        "economy": "NONE", "resolution_kind": "TYPED", "target_kind": "HOSTILE_ENTITY", "range_ft": 60,
        "parameters": {"typed": {"source": immune_id, "numbers": {"cl": 6, "pb": 4, "save_dc": 18},
                                 "duration": {"kind": "instant"}, "effects": [
                                     {"type": "immunity", "applies_to": "target", "damage_types": ["psychic"],
                                      "expires_on": "UNTIL_REMOVED", "evidence": "Test protection prevents Psychic damage"},
                                 ]}, "expected_damage": 0}
    })
    owner["actor_template"]["action_ids"].append(immune_id)
    owner.pop("bundle_sha256", None)
    owner["bundle_sha256"] = canonical_sha256(owner)


def cold(combat, tmp_path, mid):
    from combat.gate5_service import CombatService
    from tests.h1_support import ROOT
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    assert session.verify()["status"] == "PASS"
    assert session.mechanical.replay()["status"] == "PASS"
    return session.engine


def chosen_response(result, want):
    prompt = result["reaction"]
    options = prompt["choice"]["options"]
    option = next((row for row in options if want.lower() in str(row.get("label") or "").lower()), None)
    assert option, {"want": want, "options": options}
    return {**prompt["context"], "selection": "USE", "option_ids": [option["id"]]}


def play(combat, table, mid, candidate, rider_label, *, decline_offer=False,
         decline_first=False, packet="weapon", consecrated="save", auto=False):
    answers, prompts = [], []
    for _ in range(12):
        menu = table.state(mid)["menu"]
        result = (table.auto_step(mid, 0, answers) if auto else
                  table.act(mid, candidate, menu["decision_id"], menu["state_version"], 0, answers))
        if result["status"] == "COMMITTED":
            return prompts
        assert result["status"] == "REACTION_REQUIRED", result
        prompt = result["reaction"]
        prompts.append(prompt)
        checkpoint = str(prompt.get("context", {}).get("checkpoint") or "")
        if checkpoint.endswith(":packet"):
            # Selection pauses before either packet is committed, including
            # when the answers are reconstructed after a fresh service load.
            answers.append(chosen_response(result, packet + " damage only"))
            continue
        if checkpoint.endswith(":offer"):
            offers = sum(str(p.get("context", {}).get("checkpoint", "")).endswith(":offer") for p in prompts)
            answers.append({**prompt["context"], "selection": "DECLINE"} if decline_offer or decline_first and offers == 1
                           else chosen_response(result, "add damage"))
        elif checkpoint.endswith(":damage_type"):
            answers.append(chosen_response(result, "psychic"))
        elif checkpoint.endswith(":rider"):
            answers.append(chosen_response(result, rider_label))
        elif checkpoint.endswith(":consecrated"):
            answers.append(chosen_response(result, "Make a Constitution save" if consecrated == "save" else "Skip the save"))
        elif "DEVIL_QI_AUGMENT_ARMAMENT" in checkpoint:
            answers.append(chosen_response(result, "Move the Domain Armament"))
        else:
            # Fixture's cultivation counter is a real owned reaction.
            answers.append({**prompt["context"], "selection": "USE"}
                           if str(prompt["context"].get("reaction_source_id", "")).endswith(COUNTER) else
                           {**prompt["context"], "selection": "DECLINE"})
    raise AssertionError("too many table prompts")


def commit_first_choice(table, mid, candidate):
    answers, prompts = [], []
    for _ in range(10):
        menu = table.state(mid)["menu"]
        result = table.act(mid, candidate, menu["decision_id"], menu["state_version"], 0, answers)
        if result["status"] == "COMMITTED":
            return prompts
        assert result["status"] == "REACTION_REQUIRED", result
        prompt = result["reaction"]
        prompts.append(prompt)
        options = prompt.get("choice", {}).get("options", [])
        assert options
        answers.append({**prompt["context"], "selection": "USE", "option_ids": [options[0]["id"]]})
    raise AssertionError("too many prompts")


@pytest.mark.parametrize("rider", ["Reactions", "Push", "Pull", "Speed", "Temporary Hit Points"])
def test_augment_spends_pool_once_for_multi_packet_action_and_cold_reloads(tmp_path, rider):
    positions = ({s.OWNER: {"x": 2, "y": 6}, s.FOE: {"x": 5, "y": 6}, s.SECOND: {"x": 4, "y": 7}}
                 if rider == "Pull" else
                 {s.OWNER: {"x": 3, "y": 6}, s.FOE: {"x": 4, "y": 6}, s.SECOND: {"x": 5, "y": 7}})
    combat, table, mid, _, _ = s.fixture(tmp_path, [AUGMENT], positions=positions, wide=True,
                                        bundle_transform=add_probe)
    engine = cold(combat, tmp_path, mid)
    owner = engine.state.actors[s.OWNER]
    foe = engine.state.actors[s.FOE]
    assert DEVIL_QI in owner.resources and DEVIL_QI in owner.resource_maximums
    assert owner.resource_maximums[DEVIL_QI] > 0
    initial_qi = owner.resources[DEVIL_QI]
    initial_hp = foe.current_hp
    initial_position = (foe.position.x, foe.position.y)
    candidate = s.candidate(table, mid, "Test Cultivation Bolt", s.FOE)
    prompts = play(combat, table, mid, candidate, rider)
    assert len([p for p in prompts if "Spend 1 Devil Qi" in str(p)]) == 1
    assert any("Spend 1 Devil Qi to add 2d8 necrotic, psychic, or force damage and a rider" in str(p)
               for p in prompts)
    engine = cold(combat, tmp_path, mid)
    owner, foe = engine.state.actors[s.OWNER], engine.state.actors[s.FOE]
    assert owner.resources[DEVIL_QI] == initial_qi - 1
    assert foe.current_hp < initial_hp - 5  # added dice damage followed the activation's two packets once
    if rider == "Reactions":
        assert any(c.condition_id == "condition:typed.reaction_denied" for c in foe.conditions.values())
    elif rider in ("Push", "Pull"):
        assert (foe.position.x, foe.position.y) != initial_position
    elif rider == "Speed":
        assert engine._effective_speed(foe) == 20
    else:
        assert owner.temporary_hp >= owner.proficiency_bonus
    rider_key = {"Reactions": "no_reactions", "Push": "push", "Pull": "pull",
                 "Speed": "speed", "Temporary Hit Points": "temp_hp"}[rider]
    assert any(e.source_definition_id == AUGMENT + "." + rider_key for e in engine.events)
    assert_plain_augment_history(engine, AUGMENT + "." + rider_key)
    assert_plain_augment_history(engine, AUGMENT + ".damage")
    second = s.candidate(table, mid, "Second Cultivation Bolt", s.SECOND)
    # The accepted use is once this turn even though a new qualifying activation follows.
    assert not commit_first_choice(table, mid, second)
    assert cold(combat, tmp_path, mid).state.actors[s.OWNER].resources[DEVIL_QI] == initial_qi - 1


def test_plain_weapon_attack_is_not_a_qualifying_source():
    from combat.ext.devil_heart_second_furnace import _qualifying_source
    from types import SimpleNamespace

    assert not _qualifying_source(SimpleNamespace(action=SimpleNamespace(source_definition_id="action:basic.weapon_attack"),
                                                   typed={"source": "weapon_attack"}, source="action:basic.weapon_attack"))
    assert _qualifying_source(SimpleNamespace(action=SimpleNamespace(source_definition_id="tianxia.subpath.qi.example.feature"),
                                               typed={}, source="tianxia.subpath.qi.example.feature"))


def test_plain_weapon_packet_does_not_offer_but_qualifying_hit_still_does(tmp_path):
    combat, table, mid, _, _ = s.fixture(tmp_path, [AUGMENT], wide=True, bundle_transform=add_probe)
    engine = cold(combat, tmp_path, mid)
    before = engine.state.actors[s.OWNER].resources[DEVIL_QI]
    plain = s.candidate(table, mid, "Test Plain Weapon Attack", s.FOE)
    assert not commit_first_choice(table, mid, plain)
    assert cold(combat, tmp_path, mid).state.actors[s.OWNER].resources[DEVIL_QI] == before
    bolt = s.candidate(table, mid, "Test Cultivation Bolt", s.FOE)
    prompts = play(combat, table, mid, bolt, "Reactions")
    assert sum("Spend 1 Devil Qi" in str(p) for p in prompts) == 1


def test_declining_does_not_suppress_later_packets_but_one_accepted_augment_per_turn(tmp_path):
    combat, table, mid, _, _ = s.fixture(tmp_path, [AUGMENT], wide=True, bundle_transform=add_probe)
    engine = cold(combat, tmp_path, mid)
    before = engine.state.actors[s.OWNER].resources[DEVIL_QI]
    first = s.candidate(table, mid, "Test Cultivation Bolt", s.FOE)
    hp = engine.state.actors[s.FOE].current_hp
    declined = play(combat, table, mid, first, "Reactions", decline_first=True)
    assert sum(str(p["context"]["checkpoint"]).endswith(":offer") for p in declined) == 2
    after = cold(combat, tmp_path, mid)
    assert after.state.actors[s.OWNER].resources[DEVIL_QI] == before - 1
    assert after.state.actors[s.FOE].current_hp < hp - 6
    second = s.candidate(table, mid, "Second Cultivation Bolt", s.SECOND)
    accepted = play(combat, table, mid, second, "Reactions")
    assert not accepted
    assert cold(combat, tmp_path, mid).state.actors[s.OWNER].resources[DEVIL_QI] == before - 1


def test_domain_armament_rider_moves_the_manifested_armament_and_cold_reloads(tmp_path):
    armament = "tianxia.path.qi_cultivation.feature.domain_armament"
    combat, table, mid, _, _ = s.fixture(tmp_path, [AUGMENT, armament], wide=True,
                                        bundle_transform=add_probe)
    engine = cold(combat, tmp_path, mid)
    manifest = s.candidate(table, mid, "Domain Armament: Manifest")
    commit_first_choice(table, mid, manifest)
    engine = cold(combat, tmp_path, mid)
    owner = engine.state.actors[s.OWNER]
    before = qi_path.armament_point(owner)
    candidate = s.candidate(table, mid, "Test Cultivation Bolt", s.FOE)
    play(combat, table, mid, candidate, "Domain Armament")
    engine = cold(combat, tmp_path, mid)
    after = qi_path.armament_point(engine.state.actors[s.OWNER])
    assert after != before
    assert any(e.source_definition_id == AUGMENT + ".armament" for e in engine.events)
    assert_plain_augment_history(engine, AUGMENT + ".armament")


def test_consecrated_resistance_success_halves_augment_and_skips_rider(tmp_path):
    combat, table, mid, _, _ = s.fixture(tmp_path, [AUGMENT], wide=True,
                                        bundle_transform=add_consecrated_probe)
    ward = s.candidate(table, mid, "Test Consecrated Ward", s.FOE)
    commit_first_choice(table, mid, ward)
    engine = cold(combat, tmp_path, mid)
    hp = engine.state.actors[s.FOE].current_hp
    start = len(engine.events)
    candidate = s.candidate(table, mid, "Test Cultivation Bolt", s.FOE)
    prompts = play(combat, table, mid, candidate, "Reactions")
    engine = cold(combat, tmp_path, mid)
    foe = engine.state.actors[s.FOE]
    saves = [event for event in engine.events if event.event_type == "SAVE_ROLLED" and event.actor_id == s.FOE
             and str(event.payload.get("reason") or "").endswith(":CON")]
    assert saves and saves[-1].payload.get("total", 0) >= 18
    assert not any(c.condition_id == "condition:typed.reaction_denied" for c in foe.conditions.values())
    rolled, added, original = damage_totals(engine, start)
    assert rolled > 0 and added == rolled // 2
    assert_original_damage_unchanged(engine, start, original)
    assert foe.current_hp == hp - original - added
    prompt = next(p for p in prompts if str(p["context"]["checkpoint"]).endswith(":consecrated"))
    assert prompt["context"]["reactor_id"] == s.FOE
    labels = str(prompt["choice"]["options"])
    assert "Owner's Cultivation Save DC 18" in labels
    assert "your Cultivation Save DC" not in labels


def test_rider_is_skipped_when_target_takes_none_of_the_extra_damage(tmp_path):
    combat, table, mid, _, _ = s.fixture(tmp_path, [AUGMENT], wide=True, bundle_transform=add_immune_probe)
    immunity = s.candidate(table, mid, "Test Psychic Immunity", s.FOE)
    commit_first_choice(table, mid, immunity)
    engine = cold(combat, tmp_path, mid)
    foe = engine.state.actors[s.FOE]
    assert any(m.target_field == "damage_immunity" and m.value == "PSYCHIC" for m in foe.modifiers.values())
    before_position = (foe.position.x, foe.position.y)
    play(combat, table, mid, s.candidate(table, mid, "Test Cultivation Bolt", s.FOE), "Reactions")
    engine = cold(combat, tmp_path, mid)
    foe = engine.state.actors[s.FOE]
    assert any(m.target_field == "damage_immunity" and m.value == "PSYCHIC" for m in foe.modifiers.values())
    assert not any(c.condition_id == "condition:typed.reaction_denied" for c in foe.conditions.values())
    assert (foe.position.x, foe.position.y) == before_position


def test_once_per_turn_resets_at_each_creature_turn_and_survives_reload(tmp_path):
    combat, table, mid, _, _ = s.fixture(tmp_path, [AUGMENT], wide=True, bundle_transform=add_counter_probe)
    cold(combat, tmp_path, mid)
    first = s.candidate(table, mid, "Test Cultivation Bolt", s.FOE)
    play(combat, table, mid, first, "Speed")
    engine = cold(combat, tmp_path, mid)
    after_first = engine.state.actors[s.OWNER].resources[DEVIL_QI]
    assert after_first == 1
    menu = table.state(mid)["menu"]
    table.act(mid, menu["end_turn"], menu["decision_id"], menu["state_version"], 0, [])
    engine = cold(combat, tmp_path, mid)
    assert engine.state.current_actor_id != s.OWNER
    assert "typed_once_turn:devil_qi_augment" not in engine.state.actors[s.OWNER].turn_flags
    second = s.candidate(table, mid, "Trigger Cultivation Counter", s.OWNER)
    prompts = play(combat, table, mid, second, "Speed")
    assert sum("Spend 1 Devil Qi" in str(p) for p in prompts) == 1
    assert cold(combat, tmp_path, mid).state.actors[s.OWNER].resources[DEVIL_QI] == after_first - 1



def test_speed_rider_stacks_as_a_relative_penalty_with_other_speed_modifiers(tmp_path):
    combat, table, mid, _, _ = s.fixture(tmp_path, [AUGMENT], wide=True, bundle_transform=add_counter_probe)
    commit_first_choice(table, mid, s.candidate(table, mid, "Native Speed Bonus", s.FOE))
    engine = cold(combat, tmp_path, mid)
    before = sorted(m.value for m in engine.state.actors[s.FOE].modifiers.values() if m.target_field == "speed_ft")
    assert before == [15]
    play(combat, table, mid, s.candidate(table, mid, "Test Cultivation Bolt", s.FOE), "Speed")
    engine = cold(combat, tmp_path, mid)
    after = sorted(m.value for m in engine.state.actors[s.FOE].modifiers.values() if m.target_field == "speed_ft")
    assert -10 in after
    assert sorted(after) == sorted(before + [-10])
    assert engine._effective_speed(engine.state.actors[s.FOE]) == 35
