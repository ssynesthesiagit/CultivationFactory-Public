"""Sound automation through table transactions, cold reload and mechanical replay."""
import pytest

from combat.typed_executor import bears_mark, condition_rules, mark_condition_id
from combat.gate2_runtime_models import ActionIntent
from tests.worker2_support import OWNER, ALLY, FOE, act, fixture, reload, settle, turn

PULSE = "TAL_SOUND_DISSONANT_PULSE"
VOICE = "TAL_SOUND_THUNDERING_VOICE"
NOTE = "TAL_SOUND_RESONANT_NOTE"
USED = "condition:typed.sound_pulse_used"


def rider_toggle(engine):
    """The owner's own on/off control for a captured paid hit rider.

    A paid Unarmed Strike rider is off until its owner turns it on
    (fix/attack-modifier-disabled-variants, commit e1a6c478: "an off-by-default
    rider was offered as a paid attack"); turning it on restores every exact
    variant. The control is free and stays until changed.
    """
    return next(c for c in engine.legal_candidates()
                if c.source_definition_id in engine.action_catalog
                and (engine.action_catalog[c.source_definition_id].parameters.get("attack_modifier_setting") or {})
                    .get("field") == "on")


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
    if not weapon:  # the Unarmed Strike's paid rider is off until its owner turns it on (e1a6c478)
        settle(table, mid, rider_toggle(engine).candidate_id)
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
    # Turn the Unarmed Strike's paid rider on through its own free control first (e1a6c478).
    session = combat._load_session(mid)
    toggle = rider_toggle(session.engine)
    session.mechanical.execute_intent(ActionIntent(intent_id="sound-rider-enable",
        decision_id=toggle.decision_id, candidate_id=toggle.candidate_id, state_version=toggle.state_version,
        actor_id=toggle.actor_id, target_ids=toggle.target_ids, destination=toggle.destination,
        option_ids=toggle.option_ids))
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


def blind_observer_setup(bundles):
    """Declare the synthetic setup action as free, without changing turn rules."""
    from combat.canonical import canonical_sha256
    bundle = bundles[0]
    source = "action:test.a2sound.blind"
    bundle["action_catalog"].append({"source_definition_id": source, "display_name": "Blind the observer",
        "owner_id": OWNER, "economy": "NONE", "resolution_kind": "TYPED", "target_kind": "SELF",
        # NONE alone does not grant primary-action permission.
        "parameters": {"free_primary": True, "typed": {"effects": [{"type": "condition", "condition": "blinded",
            "applies_to": "self", "duration": "one_minute"}]}}, "costs": []})
    bundle["actor_template"]["action_ids"].append(source)
    bundle.pop("bundle_sha256", None)
    bundle["bundle_sha256"] = canonical_sha256(bundle)


def test_pulse_blind_setup_is_free_and_survives_cold_reload(tmp_path):
    from combat.senses import perceives
    combat, table, mid = pulse_fixture(tmp_path, bundle_transform=blind_observer_setup)
    engine = reload(tmp_path, mid)
    before = engine.state.actors[OWNER].resources["resource:core.qi"]
    blind = next(c for c in engine.legal_candidates() if c.source_definition_id == "action:test.a2sound.blind")
    settle(table, mid, blind.candidate_id)
    engine = reload(tmp_path, mid)
    assert engine.state.current_actor_id == OWNER
    assert engine.state.actors[OWNER].resources["resource:core.qi"] == before
    assert not perceives(engine, engine.state.actors[OWNER], engine.state.actors[FOE])
    assert any(engine.action_catalog[c.source_definition_id].display_name == "Thundering Voice"
               for c in engine.legal_candidates() if c.source_definition_id in engine.action_catalog)


@pytest.mark.parametrize("ask,perceived", [(True, True), (False, True), (False, False)])
def test_pulse_zone_damage_on_another_creatures_turn(tmp_path, ask, perceived):
    def setup(bundles):
        if not perceived:
            blind_observer_setup(bundles)
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
# ------------------------------------------------- Resonant Note's construct Proficiency Bonus
# "If the target is an unattended object, brittle structure, ordinary barrier, or construct,
# add your Proficiency Bonus to the damage" (MGR-T14-ling-note-construct-1). The
# unattended-object half is the object_damage feature block (combat/ext/objects.py); these
# regressions drive the construct half through the native service/session/table path.

NOTE_PB = 4  # the worker-2 fixture sheet's Proficiency Bonus


def script_note_dice(engine, values):
    """The next dice this engine rolls come from ``values`` (in order); then the seeded roller carries on."""
    queue = list(values)
    roller = engine.roller
    original = roller._die

    def _die(sides):
        if queue:
            counter = roller.counter
            roller.counter += 1
            return min(int(queue.pop(0)), sides), counter
        return original(sides)

    roller._die = _die
    return queue


def note_construct_fixture(tmp_path, *, construct=True, attack_bonus=50, seed="A2NOTE"):
    """A fight whose owner's Resonant Note hits as scripted, against a Construct-labelled (or ordinary) foe."""
    from combat.canonical import canonical_sha256

    def setup(bundles):
        for bundle in bundles:
            if bundle["actor_id"] == OWNER:
                for row in bundle["action_catalog"]:
                    if row["display_name"].startswith("Resonant Note:"):
                        row["parameters"]["typed"]["numbers"]["attack_bonus"] = attack_bonus
            if bundle["actor_id"] == FOE:
                bundle["actor_template"]["creature_types"] = ["Construct"] if construct else []
            bundle.pop("bundle_sha256", None)
            bundle["bundle_sha256"] = canonical_sha256(bundle)

    return fixture(tmp_path, [NOTE], owner_dc=50, ask=False,
                     bundle_transform=setup, seed=seed)


def note_attack(engine, name):
    """The Note's foe-targeted candidate with this exact display name."""
    return next(c for c in engine.legal_candidates()
                if c.target_ids == (FOE,) and engine.action_catalog.get(c.source_definition_id)
                and engine.action_catalog[c.source_definition_id].display_name == name)


def note_commit(session, candidate, tag):
    """Execute the candidate through the session's own intent machinery."""
    session.mechanical.execute_intent(ActionIntent(intent_id="a2-note-construct-" + tag,
        decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
        state_version=candidate.state_version, actor_id=candidate.actor_id,
        target_ids=candidate.target_ids, destination=candidate.destination,
        option_ids=candidate.option_ids))


def note_damage(engine):
    """The Note's own damage roll record and committed damage, read back from the committed fight."""
    rolled = next(e for e in engine.events if e.event_type == "DAMAGE_ROLLED"
                    and NOTE in e.source_definition_id)
    committed = next(e for e in engine.events if e.event_type == "DAMAGE_COMMITTED"
                       and NOTE in e.source_definition_id)
    return rolled, committed


@pytest.mark.parametrize("name", ["Resonant Note: Deafen",
                                   "Resonant Note: Concentration Disadvantage"])
def test_note_hit_on_a_construct_adds_proficiency_bonus_once(tmp_path, name):
    """"... or construct, add your Proficiency Bonus to the damage": every option of the
    Note rides its own primary packet, exactly once, as the packet's modifier, so the
    Thunder type (and its Resistance and Immunity answers) is unchanged."""
    combat, table, mid = note_construct_fixture(tmp_path, seed="A2NOTE-C")
    session = combat._load_session(mid)
    engine = session.engine
    before = engine.state.actors[FOE].current_hp
    candidate = note_attack(engine, name)
    script_note_dice(engine, [10, 3, 4, 5])  # the attack roll, then the CL 15 3d8
    note_commit(session, candidate, "hit")
    engine = reload(tmp_path, mid)
    rolled, committed = note_damage(engine)
    assert rolled.payload["dice"] == [3, 4, 5]
    assert rolled.payload["expression"] == f"3d8+{NOTE_PB}"
    assert committed.payload["hp_damage"] == 12 + NOTE_PB
    assert committed.payload["damage_type"] == "THUNDER"
    assert engine.state.actors[FOE].current_hp == before - 12 - NOTE_PB


def test_note_hit_on_an_ordinary_creature_adds_no_proficiency_bonus(tmp_path):
    """Only the printed kinds qualify: an unlabelled creature takes the 3d8 alone."""
    combat, table, mid = note_construct_fixture(tmp_path, construct=False, seed="A2NOTE-O")
    session = combat._load_session(mid)
    engine = session.engine
    before = engine.state.actors[FOE].current_hp
    candidate = note_attack(engine, "Resonant Note: Deafen")
    script_note_dice(engine, [10, 3, 4, 5])
    note_commit(session, candidate, "creature")
    engine = reload(tmp_path, mid)
    rolled, committed = note_damage(engine)
    assert rolled.payload["expression"] == "3d8+0"
    assert committed.payload["hp_damage"] == 12
    assert engine.state.actors[FOE].current_hp == before - 12


def test_note_miss_on_a_construct_deals_no_damage(tmp_path):
    """A miss rolls no damage packet, so the construct bonus never lands."""
    combat, table, mid = note_construct_fixture(tmp_path, attack_bonus=-50, seed="A2NOTE-M")
    session = combat._load_session(mid)
    engine = session.engine
    before = engine.state.actors[FOE].current_hp
    candidate = note_attack(engine, "Resonant Note: Deafen")
    script_note_dice(engine, [1])  # a natural 1 always misses
    note_commit(session, candidate, "miss")
    engine = reload(tmp_path, mid)
    assert not [e for e in engine.events if e.event_type == "DAMAGE_COMMITTED"
                 and NOTE in e.source_definition_id]
    assert engine.state.actors[FOE].current_hp == before


def test_note_critical_on_a_construct_doubles_dice_and_adds_proficiency_bonus_once(tmp_path):
    """A critical doubles the Note's dice; the Proficiency Bonus is still one flat modifier."""
    combat, table, mid = note_construct_fixture(tmp_path, seed="A2NOTE-X")
    session = combat._load_session(mid)
    engine = session.engine
    before = engine.state.actors[FOE].current_hp
    candidate = note_attack(engine, "Resonant Note: Deafen")
    script_note_dice(engine, [20, 3, 4, 5, 6, 7, 8])  # natural 20, then the doubled 6d8
    note_commit(session, candidate, "critical")
    engine = reload(tmp_path, mid)
    rolled, committed = note_damage(engine)
    assert rolled.payload["dice"] == [3, 4, 5, 6, 7, 8]
    assert rolled.payload["expression"] == f"6d8+{NOTE_PB}"
    assert committed.payload["hp_damage"] == 33 + NOTE_PB
    assert engine.state.actors[FOE].current_hp == before - 33 - NOTE_PB


def test_other_sound_attack_on_a_construct_adds_no_note_proficiency_bonus(tmp_path):
    """A Sound talent that is not the Note pays no Note bonus -- not on its weapon packet,
    not on its own attached on-hit rider (Body Resonance Strike's Thunder)."""
    from combat.canonical import canonical_sha256

    def setup(bundles):
        for bundle in bundles:
            if bundle["actor_id"] == OWNER:
                for row in bundle["action_catalog"]:
                    if row["display_name"].startswith("Resonant Note:") \
                            or "Body Resonance Strike" in row["display_name"]:
                        row["parameters"]["typed"]["numbers"]["attack_bonus"] = 50
            if bundle["actor_id"] == FOE:
                bundle["actor_template"]["creature_types"] = ["Construct"]
            bundle.pop("bundle_sha256", None)
            bundle["bundle_sha256"] = canonical_sha256(bundle)

    kit = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.fu", "quantity": 1}]}}
    combat, table, mid = fixture(tmp_path, [NOTE, "TAL_SOUND_BODY_RESONANCE_STRIKE"],
                                     owner_dc=50, owner_kit=kit, foe_position={"x": 3, "y": 5},
                                     bundle_transform=setup, seed="A2NOTE-S", ask=False)
    session = combat._load_session(mid)
    engine = session.engine
    before = engine.state.actors[FOE].current_hp
    candidate = next(c for c in engine.legal_candidates()
                     if c.target_ids == (FOE,) and engine.action_catalog.get(c.source_definition_id)
                     and engine.action_catalog[c.source_definition_id].display_name
                         .startswith("Fu (Short Axe) attack + Body Resonance Strike"))
    script_note_dice(engine, [10, 6, 1, 3])  # the attack roll, the fu's 1d6, the rider's 2d6
    note_commit(session, candidate, "strike")
    engine = reload(tmp_path, mid)
    damage_rolls = [r for r in engine.rolls if str(r.reason).startswith("DAMAGE:")]
    assert [r.expression for r in damage_rolls] == ["1d6+2", "2d6+0"]
    assert before - engine.state.actors[FOE].current_hp == 8 + 4


def test_note_construct_bonus_commits_and_survives_cold_reload(tmp_path):
    """The bonus lands through the table's own manual transport and survives a commit and
    cold reload: the committed fight replays with the Proficiency Bonus in its damage."""
    combat, table, mid = note_construct_fixture(tmp_path, seed="A2NOTE-R4")
    engine = combat._load_session(mid).engine
    before = engine.state.actors[FOE].current_hp
    prompts = settle(table, mid, note_candidate(combat, mid).candidate_id)
    assert not any("sound_pulse" in str(p) for p in prompts)  # this owner holds no Dissonant Pulse
    engine = reload(tmp_path, mid)  # asserts the committed fight replays
    rolled, committed = note_damage(engine)
    dice = sum(rolled.payload["dice"])
    assert rolled.payload["modifier"] == NOTE_PB
    assert committed.payload["hp_damage"] == dice + NOTE_PB
    assert engine.state.actors[FOE].current_hp == before - dice - NOTE_PB


def test_note_options_on_a_construct_stay_unchanged(tmp_path):
    """Every existing Note option keeps its own targeting: the object-only Expose Object
    option is still not offered against a construct creature."""
    combat, table, mid = note_construct_fixture(tmp_path, seed="A2NOTE-OPT")
    engine = combat._load_session(mid).engine
    offered = {engine.action_catalog.get(c.source_definition_id).display_name
               for c in engine.legal_candidates() if c.target_ids == (FOE,)}
    assert "Resonant Note: Deafen" in offered
    assert "Resonant Note: Concentration Disadvantage" in offered
    assert "Resonant Note: Expose Object" not in offered
