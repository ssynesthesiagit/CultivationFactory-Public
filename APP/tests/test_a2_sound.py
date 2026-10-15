"""Sound automation through table transactions, cold reload and mechanical replay."""
import pytest

from combat.typed_executor import bears_mark, condition_rules, mark_condition_id
from combat.gate2_runtime_models import ActionIntent
from tests.worker2_support import OWNER, ALLY, FOE, act, fixture, reload, settle, turn

PULSE = "TAL_SOUND_DISSONANT_PULSE"
VOICE = "TAL_SOUND_THUNDERING_VOICE"
NOTE = "TAL_SOUND_RESONANT_NOTE"
USED = "condition:typed.sound_pulse_used"


@pytest.mark.parametrize("talent,cost", [("TAL_SOUND_BODY_RESONANCE_STRIKE", 1),
                                       ("TAL_SOUND_THUNDER_MERIDIAN_STRIKE", 2)])
@pytest.mark.parametrize("weapon", [False, True])
@pytest.mark.parametrize("immune", [False, True])
@pytest.mark.parametrize("outcome", ["speed", "resonance"])
def test_pulse_requires_actual_sound_melee_rider_damage(tmp_path, talent, cost, weapon, immune, outcome):
    from combat.canonical import canonical_sha256
    def setup(bundles):
        for bundle in bundles:
            if bundle["actor_id"] == OWNER:
                for row in bundle["action_catalog"]:
                    typed = row["parameters"].get("typed") or {}
                    typed.setdefault("numbers", {})["attack_bonus"] = 50
            if bundle["actor_id"] == FOE:
                bundle["actor_template"]["maximum_hp"] = 400
                if immune:
                    bundle["typed_passives"].append({"feature_id": "test:thunder_immunity", "block": "defense",
                                                    "kind": "immunity", "damage_types": ["THUNDER"]})
            bundle.pop("bundle_sha256", None)
            bundle["bundle_sha256"] = canonical_sha256(bundle)
    kit = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.fu", "quantity": 1}]}} if weapon else None
    combat, table, mid = fixture(tmp_path, [PULSE, talent], owner_dc=50, owner_kit=kit,
                                foe_position={"x": 3, "y": 5}, bundle_transform=setup,
                                seed="A2SOUNDr1-MELEE")
    engine = reload(tmp_path, mid)
    label = "Body Resonance Strike" if cost == 1 else "Thunder-Meridian Strike: No Reactions"
    base = "Fu (Short Axe) attack" if weapon else "Unarmed Strike"
    c = next(c for c in engine.legal_candidates() if c.target_ids == (FOE,)
             and engine.action_catalog.get(c.source_definition_id)
             and engine.action_catalog[c.source_definition_id].display_name == f"{base} + {label}" + (f" ({cost} CP)" if weapon else ""))
    assert engine.action_catalog[c.source_definition_id].parameters["typed"].get("sphere") != "tianxia.sphere.sound"
    before = engine.state.actors[OWNER].resources["resource:core.qi"]
    hp = engine.state.actors[FOE].current_hp
    prompts = choose_pulse(table, mid, c.candidate_id, outcome)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[FOE].current_hp < hp  # the non-Sound base hit still lands
    assert any("sound_pulse_pay" in str(p) for p in prompts) == (not immune)
    assert engine.state.actors[OWNER].resources["resource:core.qi"] == before - cost - int(not immune)
    assert engine._effective_speed(engine.state.actors[FOE]) == (20 if not immune and outcome == "speed" else 30)
    if not immune:
        assert any("Dissonant Pulse" in str(p) and label in str(p) for p in prompts)
        if outcome == "resonance":
            marks = [c for c in engine.state.actors[FOE].conditions.values()
                     if c.condition_id == mark_condition_id("Resonance", OWNER)]
            assert len(marks) == 1 and marks[0].expires_on == "END_OF_MARKER_NEXT_TURN"
            turn(table, mid, ALLY)
            turn(table, mid, OWNER)
            assert bears_mark(reload(tmp_path, mid).state.actors[FOE], OWNER, "Resonance")


@pytest.mark.parametrize("talent,cost", [("TAL_SOUND_BODY_RESONANCE_STRIKE", 1),
                                       ("TAL_SOUND_THUNDER_MERIDIAN_STRIKE", 2)])
def test_pulse_sound_melee_direct_session_intent_cold_reload(tmp_path, talent, cost):
    from combat.canonical import canonical_sha256
    def setup(bundles):
        for bundle in bundles:
            if bundle["actor_id"] == OWNER:
                for row in bundle["action_catalog"]:
                    (row["parameters"].get("typed") or {}).setdefault("numbers", {})["attack_bonus"] = 50
            bundle.pop("bundle_sha256", None)
            bundle["bundle_sha256"] = canonical_sha256(bundle)
    combat, table, mid = fixture(tmp_path, [PULSE, talent], owner_dc=50, ask=False,
                                foe_position={"x": 3, "y": 5}, bundle_transform=setup, seed="A2SOUNDr1-DIRECT")
    session = combat._load_session(mid)
    name = "Body Resonance Strike" if cost == 1 else "Thunder-Meridian Strike: No Reactions"
    c = next(c for c in session.engine.legal_candidates() if c.target_ids == (FOE,)
             and session.engine.action_catalog.get(c.source_definition_id)
             and session.engine.action_catalog[c.source_definition_id].display_name == f"Unarmed Strike + {name}")
    before = session.engine.state.actors[OWNER].resources["resource:core.qi"]
    session.mechanical.execute_intent(ActionIntent(intent_id="sound-rider-direct", decision_id=c.decision_id,
        candidate_id=c.candidate_id, state_version=c.state_version, actor_id=c.actor_id,
        target_ids=c.target_ids, destination=c.destination, option_ids=c.option_ids))
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources["resource:core.qi"] == before - cost - 1
    assert any(c.condition_id == USED for c in engine.state.actors[OWNER].conditions.values())


def voice_candidate(combat, mid):
    engine = combat._load_session(mid).engine
    at = engine.state.actors[FOE].position
    return next(c for c in engine.legal_candidates()
                if engine.action_catalog.get(c.source_definition_id)
                and engine.action_catalog[c.source_definition_id].display_name == "Thundering Voice"
                and c.destination == at)


def pulse_fixture(tmp_path, *, dc=50, **kwargs):
    kwargs.setdefault("foe_position", {"x": 5, "y": 6})
    return fixture(tmp_path, [PULSE, VOICE], owner_dc=dc, seed="A2SOUND", **kwargs)


def choose_pulse(table, mid, cid, outcome="reactions", *, accept=True):
    # Thundering Voice expressly affects creatures, including allies. Decline
    # their optional Pulses and choose this test's foe, using the real transport.
    answers, prompts = [], []
    for _ in range(20):
        result = act(table, mid, cid, answers)
        if result["status"] != "REACTION_REQUIRED":
            assert result["status"] == "COMMITTED", result
            return prompts
        p = result["reaction"]
        prompts.append(p)
        context = p["context"]
        rid = context["reaction_source_id"]
        options = (p.get("choice") or {}).get("options") or []
        pick = options[0]["id"] if options and rid.startswith("choice:") else None
        if rid == "choice:needle.sound_pulse_pay":
            pick = "pulse" if accept and context["checkpoint"].endswith(":" + FOE) else None
        elif rid == "choice:needle.sound_pulse_failure":
            pick = outcome
        answer = {**context, "selection": "USE" if pick else "DECLINE"}
        if pick and options:
            answer["option_ids"] = [pick]
        answers.append(answer)
    raise AssertionError("Too many choices")


@pytest.mark.parametrize("outcome", ["concentration", "reactions", "speed", "resonance"])
def test_pulse_after_other_sound_talent_commits_and_reloads(tmp_path, outcome):
    combat, table, mid = pulse_fixture(tmp_path)
    before = reload(tmp_path, mid).state.actors[OWNER].resources["resource:core.qi"]
    prompts = choose_pulse(table, mid, voice_candidate(combat, mid).candidate_id, outcome)
    pulse_prompts = [p for p in prompts if "sound_pulse" in p["context"]["reaction_source_id"]
                     and p["context"]["checkpoint"].endswith(":" + FOE)]
    assert len(pulse_prompts) == 2
    assert all("Dissonant Pulse" in str(p) and "Thundering Voice" in str(p) for p in pulse_prompts)
    engine = reload(tmp_path, mid)
    owner, foe = engine.state.actors[OWNER], engine.state.actors[FOE]
    assert owner.resources["resource:core.qi"] == before - 2  # Voice plus the accepted Pulse
    assert any(c.condition_id == USED for c in owner.conditions.values())
    if outcome == "reactions":
        assert any(r.get("no_reactions") for r in condition_rules(foe))
    elif outcome == "concentration":
        assert any(r.get("concentration_mode") == "DISADVANTAGE" and r.get("next")
                   for r in condition_rules(foe))
    elif outcome == "speed":
        assert engine._effective_speed(foe) == 20
    else:
        assert bears_mark(foe, OWNER, "Resonance")
        marks = [c for c in foe.conditions.values() if c.condition_id == mark_condition_id("Resonance", OWNER)]
        assert marks
    # The limit expires with the current creature turn; the penalty expires on the source clock.
    settle(table, mid, table.state(mid)["menu"]["end_turn"])
    assert not any(c.condition_id == USED for c in reload(tmp_path, mid).state.actors[OWNER].conditions.values())
    turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    if outcome == "resonance":
        assert bears_mark(engine.state.actors[FOE], OWNER, "Resonance")
        settle(table, mid, table.state(mid)["menu"]["end_turn"])
        assert not bears_mark(reload(tmp_path, mid).state.actors[FOE], OWNER, "Resonance")
    elif outcome == "speed":
        assert engine._effective_speed(engine.state.actors[FOE]) == 30
    elif outcome == "reactions":
        assert not any(r.get("no_reactions") for r in condition_rules(engine.state.actors[FOE]))
    else:
        assert not any(r.get("concentration_mode") for r in condition_rules(engine.state.actors[FOE]))


@pytest.mark.parametrize("accept", [False, True])
def test_pulse_success_and_decline_pay_only_when_accepted(tmp_path, accept):
    combat, table, mid = pulse_fixture(tmp_path, dc=-50)
    before = reload(tmp_path, mid).state.actors[OWNER].resources["resource:core.qi"]
    prompts = choose_pulse(table, mid, voice_candidate(combat, mid).candidate_id, accept=accept)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources["resource:core.qi"] == before - 1 - int(accept)
    assert bears_mark(engine.state.actors[FOE], OWNER, "Resonance") == accept
    assert not any(p["context"]["reaction_source_id"] == "choice:needle.sound_pulse_failure" for p in prompts)


def note_candidate(combat, mid):
    engine = combat._load_session(mid).engine
    return next(c for c in engine.legal_candidates()
                if engine.action_catalog.get(c.source_definition_id)
                and engine.action_catalog[c.source_definition_id].display_name == "Resonant Note: Deafen"
                and c.target_ids == (FOE,))


def test_pulse_note_is_post_hit_and_long_mark_survives_reload(tmp_path):
    def setup(bundles):
        from combat.canonical import canonical_sha256
        for bundle in bundles:
            if bundle["actor_id"] == OWNER:
                for row in bundle["action_catalog"]:
                    if row["display_name"].startswith("Resonant Note:"):
                        row["parameters"]["typed"]["numbers"]["attack_bonus"] = 50
            if bundle["actor_id"] == FOE:
                bundle["actor_template"]["armor_class"] = 0
            bundle.pop("bundle_sha256", None)
            bundle["bundle_sha256"] = canonical_sha256(bundle)
    combat, table, mid = pulse_fixture(tmp_path, bundle_transform=setup)
    engine = combat._load_session(mid).engine
    assert not any((a.parameters.get("typed", {}).get("modifier") or {}).get("id") == PULSE
                   for a in engine.action_catalog.values())
    choose_pulse(table, mid, note_candidate(combat, mid).candidate_id, "resonance")
    assert bears_mark(reload(tmp_path, mid).state.actors[FOE], OWNER, "Resonance")
    turn(table, mid, ALLY)
    turn(table, mid, OWNER)
    assert bears_mark(reload(tmp_path, mid).state.actors[FOE], OWNER, "Resonance")


def test_unowned_sound_damage_has_no_pulse_prompt(tmp_path):
    combat, table, mid = fixture(tmp_path, [VOICE], owner_dc=50, seed="A2-NO-PULSE",
                                foe_position={"x": 5, "y": 6})
    prompts = settle(table, mid, voice_candidate(combat, mid).candidate_id)
    assert not any("sound_pulse" in str(p) for p in prompts)
    assert not any(c.condition_id == USED for c in reload(tmp_path, mid).state.actors[OWNER].conditions.values())


@pytest.mark.parametrize("ask,perceived", [(True, True), (False, True), (False, False)])
def test_pulse_zone_damage_on_another_creatures_turn(tmp_path, ask, perceived):
    def setup(bundles):
        if perceived:
            return
        from combat.canonical import canonical_sha256
        bundle = bundles[0]
        source = "action:test.a2sound.blind"
        bundle["action_catalog"].append({"source_definition_id": source, "display_name": "Blind the observer",
            "owner_id": OWNER, "economy": "NONE", "resolution_kind": "TYPED", "target_kind": "SELF",
            "parameters": {"typed": {"effects": [{"type": "condition", "condition": "blinded",
                "applies_to": "self", "duration": "one_minute"}]}}, "costs": []})
        bundle["actor_template"]["action_ids"].append(source)
        bundle.pop("bundle_sha256", None)
        bundle["bundle_sha256"] = canonical_sha256(bundle)
    combat, table, mid = fixture(tmp_path, [PULSE, "TAL_SOUND_RESONANCE_FIELD"], owner_dc=50,
                                foe_position={"x": 5, "y": 6}, seed="A2-ZONE", ask=ask, bundle_transform=setup)
    engine = combat._load_session(mid).engine
    if not perceived:
        blind = next(c for c in engine.legal_candidates() if c.source_definition_id == "action:test.a2sound.blind")
        settle(table, mid, blind.candidate_id)
        engine = combat._load_session(mid).engine
    field = next(c for c in engine.legal_candidates()
                 if engine.action_catalog.get(c.source_definition_id)
                 and engine.action_catalog[c.source_definition_id].display_name == "Resonance Field")
    settle(table, mid, field.candidate_id)
    after_cast = reload(tmp_path, mid).state.actors[OWNER].resources["resource:core.qi"]
    seen = []
    if not ask:
        from combat.gate4_adapters import ManualControllerAdapter
        cid = table.state(mid)["menu"]["end_turn"]
        real = combat.controller
        class EndTurnController:
            def choose_primary_action(self, context):
                return ManualControllerAdapter(lambda _context: (cid, ())).choose_primary_action(context)
            def __getattr__(self, name):
                return getattr(real, name)
        combat.controller = EndTurnController()
        combat.set_controller_mode(mid, actor_id=OWNER, controller_mode="LOCAL_AUTO")
        result = table.auto_step(mid, 0, [])
        assert result["status"] == "COMMITTED", result
        combat.controller = real
    for _ in range(4):
        if table.state(mid)["menu"]["actor_id"] == FOE:
            break
        seen += choose_pulse(table, mid, table.state(mid)["menu"]["end_turn"])
    engine = reload(tmp_path, mid)
    assert engine.state.current_actor_id == FOE
    assert engine.state.actors[OWNER].resources["resource:core.qi"] == after_cast - int(perceived)
    assert any(r.get("no_reactions") for r in condition_rules(engine.state.actors[FOE])) == perceived
    assert any("sound_pulse_pay" in str(p) for p in seen) == ask


def test_pulse_limit_survives_cold_reload_and_direct_session_intent(tmp_path):
    def two_notes(bundles):
        from combat.canonical import canonical_sha256
        for bundle in bundles:
            if bundle["actor_id"] == OWNER:
                for row in bundle["action_catalog"]:
                    if row["display_name"].startswith("Resonant Note:"):
                        row["parameters"]["typed"]["numbers"]["attack_bonus"] = 50
                        row["parameters"]["typed"]["effects"][0]["count"] = 2
            bundle.pop("bundle_sha256", None)
            bundle["bundle_sha256"] = canonical_sha256(bundle)
    combat, table, mid = pulse_fixture(tmp_path, ask=False, bundle_transform=two_notes)
    session = combat._load_session(mid)
    c = note_candidate(combat, mid)
    before = session.engine.state.actors[OWNER].resources["resource:core.qi"]
    session.mechanical.execute_intent(ActionIntent(intent_id="a2-two-notes", decision_id=c.decision_id,
        candidate_id=c.candidate_id, state_version=c.state_version, actor_id=c.actor_id,
        target_ids=c.target_ids,
        destination=c.destination, option_ids=c.option_ids))
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources["resource:core.qi"] == before - 1
    assert sum(e.event_type == "RESOURCE_SPENT" and e.actor_id == OWNER
               and e.payload.get("amount") == 1 for e in engine.events) == 1


def test_later_note_does_not_shorten_pulse_resonance(tmp_path):
    def two_notes(bundles):
        from combat.canonical import canonical_sha256
        for bundle in bundles:
            if bundle["actor_id"] == OWNER:
                for row in bundle["action_catalog"]:
                    if row["display_name"].startswith("Resonant Note:"):
                        row["parameters"]["typed"]["numbers"]["attack_bonus"] = 50
                        row["parameters"]["typed"]["effects"][0]["count"] = 2
            if bundle["actor_id"] == FOE:
                bundle["actor_template"]["maximum_hp"] = 400
            bundle.pop("bundle_sha256", None)
            bundle["bundle_sha256"] = canonical_sha256(bundle)
    combat, table, mid = pulse_fixture(tmp_path, bundle_transform=two_notes)
    prompts = choose_pulse(table, mid, note_candidate(combat, mid).candidate_id, "resonance")
    assert sum(p["context"]["reaction_source_id"] == "choice:needle.sound_pulse_pay" for p in prompts) == 1
    turn(table, mid, ALLY)
    turn(table, mid, OWNER)
    assert bears_mark(reload(tmp_path, mid).state.actors[FOE], OWNER, "Resonance")


@pytest.mark.parametrize("prevented", ["immune", "no_cp"])
def test_pulse_not_offered_without_damage_or_payment(tmp_path, prevented):
    def setup(bundles):
        from combat.canonical import canonical_sha256
        for bundle in bundles:
            if prevented == "immune" and bundle["actor_id"] == FOE:
                bundle["typed_passives"].append({"feature_id": "test:thunder_immunity", "block": "defense",
                    "kind": "immunity", "damage_types": ["THUNDER"]})
            if prevented == "no_cp" and bundle["actor_id"] == OWNER:
                next(r for r in bundle["actor_template"]["resources"]
                     if r["resource_id"] == "resource:core.qi")["initial"] = 1
            bundle.pop("bundle_sha256", None)
            bundle["bundle_sha256"] = canonical_sha256(bundle)
    combat, table, mid = pulse_fixture(tmp_path, bundle_transform=setup)
    before = reload(tmp_path, mid).state.actors[OWNER].resources["resource:core.qi"]
    prompts = choose_pulse(table, mid, voice_candidate(combat, mid).candidate_id)
    engine = reload(tmp_path, mid)
    assert not any("sound_pulse" in p["context"]["reaction_source_id"]
                   and p["context"]["checkpoint"].endswith(":" + FOE) for p in prompts)
    assert engine.state.actors[OWNER].resources["resource:core.qi"] == before - 1
    assert not any(c.condition_id == USED for c in engine.state.actors[OWNER].conditions.values())


def test_ordinary_thunder_attack_is_not_a_sound_talent(tmp_path):
    from tests.worker2_support import sealed_native_attack
    def setup(bundles):
        sealed_native_attack(bundles[0], "Ordinary thunder strike", damage_type="THUNDER", attack_bonus=50)
    combat, table, mid = pulse_fixture(tmp_path, bundle_transform=setup)
    engine = combat._load_session(mid).engine
    c = next(c for c in engine.legal_candidates() if c.target_ids == (FOE,)
             and engine.action_catalog.get(c.source_definition_id)
             and engine.action_catalog[c.source_definition_id].display_name == "Ordinary thunder strike")
    before = engine.state.actors[OWNER].resources["resource:core.qi"]
    prompts = settle(table, mid, c.candidate_id)
    engine = reload(tmp_path, mid)
    assert not any("sound_pulse" in str(p) for p in prompts)
    assert engine.state.actors[OWNER].resources["resource:core.qi"] == before


@pytest.mark.parametrize("primary", ["Stamina", "Resonance"])
def test_pulse_pays_the_owners_cultivation_pool(tmp_path, primary):
    combat, table, mid = pulse_fixture(tmp_path, primary=primary)
    resource = "resource:core." + primary.lower()
    before = reload(tmp_path, mid).state.actors[OWNER].resources[resource]
    prompts = choose_pulse(table, mid, voice_candidate(combat, mid).candidate_id)
    assert primary in str(prompts)
    assert reload(tmp_path, mid).state.actors[OWNER].resources[resource] == before - 2


def test_pulse_uses_its_owners_dc_not_a_modified_triggering_action(tmp_path):
    def setup(bundles):
        from combat.canonical import canonical_sha256
        bundle = bundles[0]
        for row in bundle["action_catalog"]:
            if row["display_name"] == "Thundering Voice":
                row["parameters"]["typed"]["numbers"]["save_dc"] = 1
        bundle.pop("bundle_sha256", None)
        bundle["bundle_sha256"] = canonical_sha256(bundle)
    combat, table, mid = pulse_fixture(tmp_path, bundle_transform=setup)
    choose_pulse(table, mid, voice_candidate(combat, mid).candidate_id)
    engine = reload(tmp_path, mid)
    assert any(r.get("no_reactions") for r in condition_rules(engine.state.actors[FOE]))
    pulse_saves = [e for e in engine.events if e.event_type == "SAVE_ROLLED" and e.source_definition_id == PULSE]
    assert pulse_saves and all(e.payload["dc"] == 50 for e in pulse_saves)


def test_pulse_penalizes_only_the_next_actual_concentration_save(tmp_path):
    from tests.h1_support import sheet
    def setup(bundles):
        from combat.canonical import canonical_sha256
        for bundle in bundles:
            if bundle["actor_id"] == OWNER:
                for row in bundle["action_catalog"]:
                    if row["display_name"].startswith("Resonant Note:"):
                        row["parameters"]["typed"]["numbers"]["attack_bonus"] = 50
                        row["parameters"]["typed"]["effects"][0]["count"] = 2
            if bundle["actor_id"] == FOE:
                bundle["actor_template"]["maximum_hp"] = 400
                bundle["actor_template"]["saving_throws"]["CON"] = 50
            bundle.pop("bundle_sha256", None)
            bundle["bundle_sha256"] = canonical_sha256(bundle)
    combat, table, mid = pulse_fixture(tmp_path, dc=100, bundle_transform=setup,
                                      foe_sheet=sheet(["TAL_SOUND_DAMPEN_SOUND"], cl=15))
    turn(table, mid, FOE)
    engine = combat._load_session(mid).engine
    c = next(c for c in engine.legal_candidates() if engine.action_catalog.get(c.source_definition_id)
             and engine.action_catalog[c.source_definition_id].display_name == "Dampen Sound"
             and c.destination == engine.state.actors[FOE].position)
    settle(table, mid, c.candidate_id)
    turn(table, mid, OWNER)
    choose_pulse(table, mid, note_candidate(combat, mid).candidate_id, "concentration")
    engine = reload(tmp_path, mid)
    saves = [e for e in engine.events if e.event_type == "SAVE_ROLLED"
             and e.source_definition_id == "system:combat.concentration"]
    assert [e.payload["mode"] for e in saves[-2:]] == ["NORMAL", "DISADVANTAGE"]
    assert not any(r.get("concentration_mode") for r in condition_rules(engine.state.actors[FOE]))
