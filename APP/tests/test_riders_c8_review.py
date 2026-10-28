"""Focused table/persistence regressions for the independent C8 review."""
import pytest

from combat import typed_executor
from combat.gate2_runtime_models import ActionIntent
from combat.gate2_scripted import _matches, load_script
from combat.gate4_persistence import Gate4Persistence
from test_riders_c8 import ROOT, ME, FOE, MIND_SPIKE, WH_ALL, bundle, held


REVIEW_FLAGS = {"truth_turn_events", "turn_events_start", "credence_before_strike",
                "moved_unwillingly_round_", "mudang_moved_ft"}


RESONANCE_NAMES = ("Resonance", "Resonance Mark", "Resonance Marked", "resonance", "resonance_mark", "resonance_marked")
SPECIAL_MARKS = ("Soul-Wick Mark", "Pursuit Mark", "Reflection Trace", "Dream-Spore Mark", "Hourglass Mark")


@pytest.mark.parametrize("control", ["MANUAL", "LOCAL_AUTO"])
@pytest.mark.parametrize("kind", ["condition", "modifier"])
@pytest.mark.parametrize("multiple", [False, True])
def test_maw_three_successes_restore_scene_expression_commit_reload(tmp_path, control, kind, multiple):
    from combat.gate5_service import CombatService
    from combat.ext.end_effect import SUPPRESSED_FLAG
    from test_riders_c8 import HE_ALL, HE

    enemy = "actor:factory.c8_restore_target"
    other = bundle([MIND_SPIKE, HE + "crown_of_borrowed_light"], actor_id=enemy, cl=18)
    other["actor_template"]["maximum_hp"] = 500
    ward = next(a for a in other["action_catalog"] if a["display_name"] == "Crown of Borrowed Light")
    ward["display_name"] = "Test radiance ward"
    ward["parameters"]["typed"]["effects"] = [
        {"type": "condition", "condition": "blessed", "applies_to": "self", "condition_data": {"rule": {"effect_kind": "benefit"}}, "expires_on": "UNTIL_REMOVED"}
        if kind == "condition" else
        {"type": "ac_bonus", "amount": 2, "applies_to": "self", "expires_on": "UNTIL_REMOVED"}]
    if multiple:
        ward["parameters"]["typed"]["effects"].append(
            {"type": "condition", "condition": "test_radiance", "applies_to": "self", "condition_data": {"rule": {"effect_kind": "benefit"}}, "expires_on": "UNTIL_REMOVED"}
            if kind == "condition" else
            {"type": "speed", "amount": 10, "applies_to": "self", "expires_on": "UNTIL_REMOVED"})
    aid = next(a for a in other["action_catalog"] if a["display_name"] == "Mind Spike")
    aid["display_name"] = "Test restoration aid"
    aid["target_kind"] = "SELF"
    aid["parameters"]["typed"]["effects"] = [
        {"type": "save_bonus", "amount": 100, "abilities": ["CHA"], "applies_to": "self",
         "expires_on": "UNTIL_REMOVED"}]
    if multiple:
        import copy
        gain = copy.deepcopy(aid)
        gain["source_definition_id"] += ".test_radiance"
        gain["display_name"] = "Test gain radiance"
        gain["parameters"]["typed"]["effects"] = [{"type": "temp_hp", "flat": 1, "applies_to": "self"}]
        other["action_catalog"].append(gain)
        other["actor_template"]["action_ids"].append(gain["source_definition_id"])
    service = CombatService(ROOT, tmp_path)
    session = service.persistence.create_match(
        match_seed="C8-MAW-RESTORE", maximum_rounds=20,
        typed_bundles=(bundle(HE_ALL, cl=18, dc=40), other),
        roster_setup={"primary_actor_ids": [ME, enemy],
                      "team_by_actor": {ME: "team:a", enemy: "team:b"},
                      "starting_positions": {ME: {"x": 6, "y": 6}, enemy: {"x": 10, "y": 6}}})
    metadata = {"participant_control_modes": {ME: "MANUAL", enemy: "MANUAL"}}
    decline = False

    def choose(context):
        if multiple and context.reaction_source_id.endswith("halo_eater.reaction"):
            return ("taste",)
        if context.reaction_source_id.endswith("halo_eater.maw_repeat"):
            assert context.reactor_id == enemy
            prompt = context.choice_trigger["prompt"]
            assert all(s in prompt for s in ("Empty Heaven Maw", "Charisma", "Three successes", "no cost"))
            return () if decline else ("save",)
        if context.reaction_source_id.endswith("halo_eater.maw_restore"):
            return context.extension_choice.option_ids[-1:]  # Player picks the second expression.
        if context.reaction_source_id.endswith("halo_eater.empty_heaven_maw_effects"):
            return context.extension_choice.option_ids[:context.extension_choice.maximum_selections]
        spec = context.extension_choice
        return spec.option_ids[:spec.minimum_selections] if spec and not spec.allow_decline else ()

    def act(name, target=None):
        result = service_commit(service, session, metadata, name, target, choose=choose)
        return result

    def advance(who):
        while session.engine.state.current_actor_id != who:
            act("End turn")

    def reload():
        nonlocal session
        session = service.persistence.load_match(session.match_id)
        assert session.verify()["status"] == "PASS"

    advance(ME)
    act("Mind Spike", enemy)
    act("End turn")
    advance(enemy)
    act("Test radiance ward")
    holder = session.engine.state.actors[enemy]
    key, original = next((k, i.model_dump(mode="json")) for k, i in
                         (holder.conditions if kind == "condition" else holder.modifiers).items()
                         if i.source_definition_id == ward["source_definition_id"])
    act("End turn")
    advance(ME)
    if multiple:
        act("End turn")
        advance(enemy)
        act("Test gain radiance")  # A second turn earns the second Stolen Radiance.
        act("End turn")
        advance(ME)
        holder = session.engine.state.actors[enemy]
        key, original = next((k, i.model_dump(mode="json")) for k, i in
                             (holder.conditions if kind == "condition" else holder.modifiers).items()
                             if i.source_definition_id == ward["source_definition_id"])
    act("Empty Heaven Maw", enemy)
    reload()
    row = session.engine.state.actors[enemy].turn_flags[SUPPRESSED_FLAG][0]
    assert row["boundary"] == "scene" and row["maw_source"] == ME and row["maw_successes"] == 0
    act("End turn")
    advance(enemy)
    metadata["participant_control_modes"][enemy] = control
    if control == "MANUAL":
        decline = True
        events, prompts, _ = act("End turn")
        assert prompts and not any(e.event_type == "SAVE_ROLLED" for e in events)
        reload()
        assert session.engine.state.actors[enemy].turn_flags[SUPPRESSED_FLAG][0]["maw_successes"] == 0
        decline = False
        advance(enemy)
    events, prompts, _ = act("End turn")  # DC 40 cannot be reached without the test aid.
    assert any(e.event_type == "SAVE_ROLLED" for e in events)
    assert bool(prompts) is (control == "MANUAL")
    reload()
    assert session.engine.state.actors[enemy].turn_flags[SUPPRESSED_FLAG][0]["maw_successes"] == 0
    advance(enemy)
    act("Test restoration aid")  # Real typed action; no roller/state replacement.
    for count in (1, 2, 3):
        events, prompts, _ = act("End turn")
        assert bool(prompts) is (control == "MANUAL")
        reload()
        holder = session.engine.state.actors[enemy]
        rows = holder.turn_flags[SUPPRESSED_FLAG]
        if count < 3:
            assert rows[0]["maw_successes"] == count
            advance(enemy)
        else:
            if multiple:
                assert len(rows) == 1 and rows[0]["maw_successes"] == 0
                # Manual chooses the farther option in the list; AI prefers the first.
                assert (rows[0]["key"] == key) is (control == "MANUAL")
                instances = holder.conditions if kind == "condition" else holder.modifiers
                restored = [i for i in instances.values() if i.source_definition_id == ward["source_definition_id"]
                            and "suppressed" not in (i.condition_id if kind == "condition" else i.target_field)]
                assert len(restored) == 1
            else:
                assert not rows
                item = (holder.conditions if kind == "condition" else holder.modifiers)[key]
                assert item.model_dump(mode="json") == original


@pytest.mark.parametrize("control", ["MANUAL", "LOCAL_AUTO"])
@pytest.mark.parametrize("kind", ["condition", "modifier"])
@pytest.mark.parametrize("expires", [False, True])
def test_maw_successful_save_restores_at_eater_start_commit_reload(tmp_path, control, kind, expires):
    from combat.gate5_service import CombatService
    from test_riders_c8 import HE_ALL, HE

    enemy = "actor:factory.c8_success_target"
    other = bundle([HE + "crown_of_borrowed_light"], actor_id=enemy, cl=18)
    other["actor_template"]["maximum_hp"] = 500
    ward = next(a for a in other["action_catalog"] if a["display_name"] == "Crown of Borrowed Light")
    ward["display_name"] = "Test radiance ward"
    ward["parameters"]["typed"]["effects"] = [
        {"type": "condition", "condition": "blessed", "applies_to": "self", "condition_data": {"rule": {"effect_kind": "benefit"}}, "expires_on": "UNTIL_REMOVED"}
        if kind == "condition" else
        {"type": "ac_bonus", "amount": 2, "applies_to": "self", "expires_on": "UNTIL_REMOVED"}]
    if expires:
        ward["parameters"]["typed"]["effects"][0]["expires_on"] = "START_OF_SOURCE_NEXT_TURN"
    eater = bundle(HE_ALL, cl=18, dc=40)
    # Test-only DC fixture: the real Mind Spike marks, the real Maw succeeds.
    next(a for a in eater["action_catalog"] if a["display_name"] == "Empty Heaven Maw")["parameters"]["typed"]["numbers"]["save_dc"] = 1
    service = CombatService(ROOT, tmp_path)
    session = service.persistence.create_match(
        match_seed="C8-MAW-SUCCESS", maximum_rounds=20,
        typed_bundles=(eater, other),
        roster_setup={"primary_actor_ids": [ME, enemy], "team_by_actor": {ME: "team:a", enemy: "team:b"},
                      "starting_positions": {ME: {"x": 6, "y": 6}, enemy: {"x": 10, "y": 6}}})
    metadata = {"participant_control_modes": {ME: "MANUAL", enemy: "MANUAL"}}

    def act(name, target=None):
        return service_commit(service, session, metadata, name, target)

    def advance(who):
        while session.engine.state.current_actor_id != who:
            act("End turn")

    advance(ME)
    act("Mind Spike", enemy)
    act("End turn")
    advance(enemy)
    act("Test radiance ward")
    holder = session.engine.state.actors[enemy]
    key, original = next((k, i.model_dump(mode="json")) for k, i in
                         (holder.conditions if kind == "condition" else holder.modifiers).items()
                         if i.source_definition_id == ward["source_definition_id"])
    act("End turn")
    advance(ME)
    metadata["participant_control_modes"][ME] = control
    act("Empty Heaven Maw", enemy)
    session = service.persistence.load_match(session.match_id)
    assert session.verify()["status"] == "PASS"
    holder = session.engine.state.actors[enemy]
    item = (holder.conditions if kind == "condition" else holder.modifiers)[key]
    assert "suppressed" in (item.condition_id if kind == "condition" else item.target_field)
    act("End turn")
    advance(ME)
    session = service.persistence.load_match(session.match_id)
    assert session.verify()["status"] == "PASS"
    holder = session.engine.state.actors[enemy]
    item = (holder.conditions if kind == "condition" else holder.modifiers).get(key)
    if expires:
        assert item is None
    else:
        assert item.model_dump(mode="json") == original


@pytest.mark.parametrize("control", ["MANUAL", "LOCAL_AUTO"])
@pytest.mark.parametrize("kind", ["condition", "modifier"])
@pytest.mark.parametrize("source_cl", [18, 24])
@pytest.mark.parametrize("expires", [False, True])
def test_maw_suppression_and_restoration_replay(tmp_path, control, kind, source_cl, expires):
    """Real Maw against a typed ward fixture; no engine/roller replacements."""
    from combat.gate5_service import CombatService
    from combat.ext.end_effect import SUPPRESSED_FLAG
    from test_riders_c8 import HE_ALL, HE

    enemy = "actor:factory.c8_radiance_source"
    other = bundle([MIND_SPIKE, HE + "crown_of_borrowed_light"], actor_id=enemy, cl=source_cl)
    other["actor_template"]["maximum_hp"] = 500
    ward = next(a for a in other["action_catalog"] if a["display_name"] == "Crown of Borrowed Light")
    # A test-only beneficial expression exercises both persisted model kinds.
    # Its duration is independent of the suppression's clock.
    if kind != "condition" or expires:
        ward["display_name"] = "Test radiance ward"
        ward["parameters"]["typed"]["effects"] = [
            {"type": "condition", "condition": "blessed", "applies_to": "self", "condition_data": {"rule": {"effect_kind": "benefit"}}}
            if kind == "condition" else {"type": "ac_bonus", "amount": 2, "applies_to": "self"}]
        ward["parameters"]["typed"]["effects"][0]["expires_on"] = "START_OF_SOURCE_NEXT_TURN" if expires else "UNTIL_REMOVED"
        ward["parameters"]["typed"]["duration"] = {"kind": "scene"}
    service = CombatService(ROOT, tmp_path)
    session = service.persistence.create_match(
        match_seed="C8-RADIANCE-REPLAY", maximum_rounds=20,
        typed_bundles=(bundle(HE_ALL, cl=18, dc=40), other),
        roster_setup={"primary_actor_ids": [ME, enemy],
                      "team_by_actor": {ME: "team:a", enemy: "team:b"},
                      "starting_positions": {ME: {"x": 6, "y": 6}, enemy: {"x": 10, "y": 6}}})
    metadata = {"participant_control_modes": {ME: "MANUAL", enemy: "MANUAL"}}

    def act(name, target=None):
        return service_commit(service, session, metadata, name, target)

    def advance(who):
        while session.engine.state.current_actor_id != who:
            act("End turn")

    advance(ME)
    act("Mind Spike", enemy)
    act("End turn")
    advance(enemy)
    act(ward["display_name"])
    actor = session.engine.state.actors[enemy]
    instances = actor.conditions if kind == "condition" else actor.modifiers
    key, original = next((k, v.model_dump(mode="json")) for k, v in instances.items()
                         if v.source_definition_id == ward["source_definition_id"])
    act("End turn")
    advance(ME)
    metadata["participant_control_modes"][ME] = control
    events, prompts, _ = act("Empty Heaven Maw", enemy)
    session = service.persistence.load_match(session.match_id)
    assert session.verify()["status"] == "PASS"
    assert any(e.event_type == ("CONDITION_APPLIED" if kind == "condition" else "MODIFIER_APPLIED")
               and e.payload.get("instance_id" if kind == "condition" else "modifier_id") == key for e in events)
    if control == "LOCAL_AUTO":
        assert not prompts
    actor = session.engine.state.actors[enemy]
    item = (actor.conditions if kind == "condition" else actor.modifiers)[key]
    field = "condition_id" if kind == "condition" else "target_field"
    assert "suppressed" in getattr(item, field)
    assert item.expires_on == original["expires_on"]
    assert item.source_actor_id == enemy
    act("End turn")
    advance(ME)  # Original expiry happens at the source's intervening start.
    session = service.persistence.load_match(session.match_id)
    assert session.verify()["status"] == "PASS"
    act("End turn")  # Higher source restores at the eater's next turn end.
    session = service.persistence.load_match(session.match_id)
    assert session.verify()["status"] == "PASS"
    actor = session.engine.state.actors[enemy]
    item = (actor.conditions if kind == "condition" else actor.modifiers).get(key)
    if expires:
        assert item is None  # Never resurrect an expression that expired hidden.
    else:
        assert item is not None
        assert getattr(item, field) == (original[field] if source_cl > 18 else
                                       original[field].replace("condition:typed.", "condition:typed.suppressed.", 1)
                                       if kind == "condition" else "suppressed:" + original[field])
        if source_cl > 18:
            assert item.model_dump(mode="json") == original
            assert not actor.turn_flags[SUPPRESSED_FLAG]


@pytest.mark.parametrize("mode", ["manual_use", "manual_decline", "automatic"])
def test_truth_forged_strike_explains_real_action_and_credence_commit_reload(tmp_path, mode):
    from combat.gate5_service import CombatService
    from test_riders_c8 import ALLY, PT, GUN, CREDENCE

    service = CombatService(ROOT, tmp_path)
    enemy = bundle([MIND_SPIKE], actor_id=FOE)
    enemy["actor_template"]["maximum_hp"] = 500
    session = service.persistence.create_match(
        match_seed="C8-TRUTH-PROMPT", maximum_rounds=20,
        typed_bundles=(bundle([PT + "word_and_hand"], items=(GUN,)),
                       bundle([MIND_SPIKE], actor_id=ALLY), enemy),
        roster_setup={"primary_actor_ids": [ME, ALLY, FOE],
                      "team_by_actor": {ME: "team:a", ALLY: "team:a", FOE: "team:b"},
                      "starting_positions": {ME: {"x": 6, "y": 6}, ALLY: {"x": 6, "y": 7},
                                             FOE: {"x": 7, "y": 6}}})
    metadata = {"participant_control_modes": {who: "MANUAL" for who in (ME, ALLY, FOE)}}

    def choose(context):
        if context.reaction_source_id.endswith("plain_truth.truth_forged"):
            trigger = context.choice_trigger
            strike = next(a for a in session.engine.action_catalog.values()
                          if a.owner_id == ME and a.display_name == "Gun (Staff) attack")
            assert trigger["source_definition_id"] == strike.source_definition_id
            assert trigger["action_name"] == strike.display_name
            assert trigger["action_actor_id"] == ME
            assert trigger["affected_id"] == trigger["target_id"] == FOE
            assert trigger["cost"] == "1 Credence" and trigger["paying_pool"] == CREDENCE
            prompt = trigger["prompt"]
            assert all(text in prompt for text in (
                "Truth-Forged Strike", strike.display_name, session.engine.state.actors[FOE].display_name,
                "1 Credence", "points earned by completing Open Declarations", "1d8 Psychic",
                "until the start of your next turn", "before this strike"))
            return () if mode == "manual_decline" else ("use",)
        return ()

    def act(name, target=None):
        return service_commit(service, session, metadata, name, target, choose=choose)

    while session.engine.state.current_actor_id != ME:
        act("End turn")
    # Earn the point through the real declaration, without changing saved state
    # or replacing a roller. It must predate the triggering strike.
    act("Open Declaration: Guard", ALLY)
    act("Dodge")
    act("End turn")
    session = service.persistence.load_match(session.match_id)
    assert session.verify()["status"] == "PASS"
    assert session.engine.state.actors[ME].resources[CREDENCE] == 1
    while session.engine.state.current_actor_id != ME:
        act("End turn")
    act("Open Declaration: Challenge", FOE)
    metadata["participant_control_modes"][ME] = "LOCAL_AUTO" if mode == "automatic" else "MANUAL"
    events, prompts, decisions = act("Gun (Staff) attack", FOE)
    choices = [d for d in decisions if d["reaction_source_id"].endswith("plain_truth.truth_forged")]
    assert len(choices) == 1 and choices[0]["reactor_id"] == ME
    use = mode != "manual_decline"
    assert choices[0]["selection"] == ("USE" if use else "DECLINE")
    assert choices[0]["option_ids"] == (["use"] if use else [])
    assert bool([p for p in prompts if p.reaction_source_id.endswith("plain_truth.truth_forged")]) is (mode != "automatic")
    assert len([e for e in events if e.event_type == "DAMAGE_COMMITTED"]) == (2 if use else 1)
    session = service.persistence.load_match(session.match_id)
    assert session.verify()["status"] == "PASS"
    # Completing Challenge earned one more point, then accepting spent one.
    assert session.engine.state.actors[ME].resources[CREDENCE] == (1 if use else 2)
    denied = held(session.engine.state.actors[FOE], "condition:typed.reaction_denied", ME)
    assert bool(denied) is use
    if use:
        assert denied[0].expires_on == "START_OF_SOURCE_NEXT_TURN"
    act("End turn")
    while session.engine.state.current_actor_id != ME:
        act("End turn")
    session = service.persistence.load_match(session.match_id)
    assert session.verify()["status"] == "PASS"
    assert not held(session.engine.state.actors[FOE], "condition:typed.reaction_denied", ME)


@pytest.mark.parametrize("mode", ["farther", "decline_member", "decline_route", "automatic"])
def test_near_constellation_member_choice_on_turn_start_commit_reload(tmp_path, mode):
    from combat.gate5_service import CombatService
    from test_riders_c8 import ALLY, NF_ALL

    far = "actor:factory.c8_far_near_member"
    service = CombatService(ROOT, tmp_path)
    session = service.persistence.create_match(
        match_seed="C8-NEAR-MEMBER", maximum_rounds=20,
        typed_bundles=(bundle(NF_ALL), bundle([MIND_SPIKE], actor_id=ALLY),
                       bundle([MIND_SPIKE], actor_id=far)),
        roster_setup={"primary_actor_ids": [ME, ALLY, far, FOE],
                      "team_by_actor": {ME: "team:a", ALLY: "team:a", far: "team:a", FOE: "team:b"},
                      "starting_positions": {ME: {"x": 6, "y": 8}, ALLY: {"x": 6, "y": 6},
                                             far: {"x": 10, "y": 6}, FOE: {"x": 12, "y": 12}}})
    metadata = {"participant_control_modes": {who: "MANUAL" for who in (ME, ALLY, far, FOE)}}

    def choose(context):
        choice = context.reaction_source_id
        if choice.endswith("constellation_near"):
            return (ME, ALLY, far)
        if context.reactor_id == ALLY and choice.endswith("constellation_member"):
            assert {ME, far} <= set(context.extension_choice.option_ids)
            prompt = (context.choice_trigger or {}).get("prompt", "")
            assert "10 feet" in prompt and "opportunity attacks" in prompt
            return () if mode == "decline_member" else (far,)
        if context.reactor_id == ALLY and choice.endswith("constellation_step"):
            if mode == "decline_route":
                return ()
            assert "cell:8,6" in context.extension_choice.option_ids
            return ("cell:8,6",)
        return ()

    def act(name):
        return service_commit(service, session, metadata, name, choose=choose)

    while session.engine.state.current_actor_id != ME:
        act("End turn")
    world_name = next(c.display_name for c in session.engine.legal_candidates()
                      if c.display_name.startswith("World Without Between") and c.destination is not None
                      and (c.destination.x, c.destination.y) == (6, 6))
    act(world_name)
    session = service.persistence.load_match(session.match_id)
    assert session.verify()["status"] == "PASS"
    assert held(session.engine.state.actors[ALLY], "condition:typed.constellation", ME)
    metadata["participant_control_modes"] = {who: "LOCAL_AUTO" for who in (ME, ALLY, far, FOE)}
    if mode != "automatic":
        metadata["participant_control_modes"][ALLY] = "MANUAL"
    before = session.engine.state.actors[ALLY].position
    prompts, decisions, events = [], [], []
    for _ in range(8):
        emitted, paused, resolved = act("End turn")
        prompts.extend(paused)
        decisions.extend(resolved)
        events.extend(emitted)
        if session.engine.state.current_actor_id == ALLY:
            break
    else:
        pytest.fail("Near member's turn did not start")
    member = [d for d in decisions if d["reactor_id"] == ALLY and d["reaction_source_id"].endswith("constellation_member")]
    assert len(member) == 1
    assert member[0]["selection"] == ("DECLINE" if mode == "decline_member" else "USE")
    assert member[0]["option_ids"] == ([] if mode == "decline_member" else [ME if mode == "automatic" else far])
    session = service.persistence.load_match(session.match_id)
    assert session.verify()["status"] == "PASS"
    mover = session.engine.state.actors[ALLY]
    if mode == "farther":
        assert (mover.position.x, mover.position.y) == (8, 6)
        assert session.engine._distance_actor_to_actor(mover, session.engine.state.actors[ME]) >= 10
    elif mode.startswith("decline"):
        assert mover.position == before
    else:
        assert session.engine._distance_actor_to_actor(mover, session.engine.state.actors[ME]) < 10
    assert bool([p for p in prompts if p.reactor_id == ALLY]) is (mode != "automatic")
    assert mover.movement_remaining_ft == mover.speed_ft


@pytest.mark.parametrize("control", ["MANUAL", "LOCAL_AUTO"])
@pytest.mark.parametrize("stored_name", [*RESONANCE_NAMES[:3], *SPECIAL_MARKS])
def test_legacy_and_special_marks_qualify_theater_after_table_reload(tmp_path, monkeypatch, control, stored_name):
    """Replay old literal storage, then exercise a real mark-dependent field choice.

    Only fixture rule data is changed during initial placement to reproduce the
    pre-alias spelling. Production methods/classes and save files are untouched.
    """
    from combat.ext.soulstring_dancer import strings
    from combat.gate5_service import CombatService
    from test_riders_c8 import SD_ALL

    dancer = bundle([*SD_ALL, MIND_SPIKE], dc=40)
    spike = next(a for a in dancer["action_catalog"] if a["display_name"] == "Mind Spike")

    def legacy_mark(rows):
        for row in rows:
            if row.get("type") == "mark":
                row.update(mark=stored_name, duration={"kind": "until_removed"})
            for key in ("on_fail", "on_success", "on_hit", "on_miss", "effects"):
                legacy_mark(row.get(key, []))

    legacy_mark(spike["parameters"]["typed"]["effects"])
    service = CombatService(ROOT, tmp_path)
    session = service.persistence.create_match(
        match_seed="C8-LEGACY-MARK-REVIEW", maximum_rounds=20, typed_bundles=(dancer,),
        roster_setup={"primary_actor_ids": [ME, FOE], "team_by_actor": {ME: "team:a", FOE: "team:b"},
                      "starting_positions": {ME: {"x": 6, "y": 6}, FOE: {"x": 7, "y": 7}}})
    metadata = {"participant_control_modes": {ME: "MANUAL", FOE: "LOCAL_AUTO"}}

    def choose(context):
        if context.reaction_source_id.endswith("soulstring.theater_string"):
            return ("place",)
        spec = context.extension_choice
        return spec.option_ids[:spec.minimum_selections] if spec and not spec.allow_decline else ()

    def act(name, target=None):
        return service_commit(service, session, metadata, name, target, choose=choose)

    while session.engine.state.current_actor_id != ME:
        act("End turn")
    # Historical rules stored each spelling literally. Clear configuration only
    # during placement, restoring it before loading/using the saved condition.
    # The fallback allows the same regression to run against the pre-fix table.
    with monkeypatch.context() as historical:
        historical.setitem(typed_executor.rules(), "mark_aliases", {})
        if hasattr(typed_executor, "_MARK_ALIASES"):
            historical.setattr(typed_executor, "_MARK_ALIASES", {})
        act("Mind Spike", FOE)
    literal = stored_name.lower().replace("-", "_").replace(" ", "_")
    saved_id = typed_executor.MARK_PREFIX + literal + "." + ME
    session = service.persistence.load_match(session.match_id)
    assert session.verify()["status"] == "PASS"
    victim = session.engine.state.actors[FOE]
    assert held(victim, saved_id, ME)
    assert strings(session.engine, session.engine.state.actors[ME], victim) == 0
    for query in RESONANCE_NAMES:
        assert typed_executor.bears_mark(victim, ME, query), (stored_name, query)
        assert not typed_executor.bears_mark(victim, "actor:other_dancer", query)
        assert typed_executor.mark_condition_id(query, ME) == typed_executor.MARK_PREFIX + "resonance." + ME
    for special in SPECIAL_MARKS:
        assert typed_executor.bears_mark(victim, ME, special) is (stored_name == special)
    assert not typed_executor.bears_mark(victim, ME, "Unknown Mark")
    assert typed_executor.bears_mark(victim, ME, "*")
    act("End turn")
    while session.engine.state.current_actor_id != ME:
        act("End turn")
    act("Theater of Strings")
    metadata["participant_control_modes"][ME] = control
    _, prompts, decisions = act("End turn")  # Owner choice on the AI target's turn.
    theater = [d for d in decisions if d["reaction_source_id"].endswith("soulstring.theater_string")]
    assert len(theater) == 1 and theater[0]["reactor_id"] == ME and theater[0]["selection"] == "USE"
    assert bool(prompts) is (control == "MANUAL")
    session = service.persistence.load_match(session.match_id)
    assert session.verify()["status"] == "PASS"
    assert held(session.engine.state.actors[FOE], saved_id, ME)  # Lookup never migrates old storage.
    assert strings(session.engine, session.engine.state.actors[ME], session.engine.state.actors[FOE]) == 1


@pytest.mark.parametrize("stored_name", ["Resonance Mark", "Resonance Marked"])
def test_miko_purifies_a_legacy_mark_after_table_reload(tmp_path, monkeypatch, stored_name):
    from combat.gate5_service import CombatService
    from test_riders_c8 import MK_ALL

    enemy = bundle([MIND_SPIKE], actor_id=FOE, cl=5, dc=40)
    spike = next(a for a in enemy["action_catalog"] if a["display_name"] == "Mind Spike")
    for row in spike["parameters"]["typed"]["effects"]:
        for effect in row.get("on_fail", []):
            if effect.get("type") == "mark":
                effect.update(mark=stored_name, duration={"kind": "until_removed"})
    service = CombatService(ROOT, tmp_path)
    session = service.persistence.create_match(
        match_seed="C8-MIKO-LEGACY", typed_bundles=(bundle(MK_ALL), enemy),
        roster_setup={"primary_actor_ids": [ME, FOE], "team_by_actor": {ME: "team:a", FOE: "team:b"},
                      "starting_positions": {ME: {"x": 6, "y": 6}, FOE: {"x": 7, "y": 7}}})
    metadata = {"participant_control_modes": {ME: "MANUAL", FOE: "LOCAL_AUTO"}}

    def act(name, target=None):
        return service_commit(service, session, metadata, name, target)

    while session.engine.state.current_actor_id != FOE:
        act("End turn")
    with monkeypatch.context() as historical:
        historical.setitem(typed_executor.rules(), "mark_aliases", {})
        if hasattr(typed_executor, "_MARK_ALIASES"):
            historical.setattr(typed_executor, "_MARK_ALIASES", {})
        act("Mind Spike", ME)
    act("End turn")
    session = service.persistence.load_match(session.match_id)
    assert session.verify()["status"] == "PASS"
    saved_id = typed_executor.MARK_PREFIX + stored_name.lower().replace(" ", "_") + "." + FOE
    assert held(session.engine.state.actors[ME], saved_id, FOE)
    events, _, _ = act("Purification Dance: Remove a Resonance Mark", ME)
    assert any(e.event_type == "CONDITION_REMOVED" and e.payload.get("condition_id") == saved_id for e in events)
    session = service.persistence.load_match(session.match_id)
    assert session.verify()["status"] == "PASS"
    assert not held(session.engine.state.actors[ME], saved_id, FOE)


def test_mark_relationship_data_is_general_and_absent_tables_are_literal(monkeypatch):
    from types import SimpleNamespace

    creature = SimpleNamespace(conditions={"old": SimpleNamespace(condition_id=typed_executor.MARK_PREFIX + "old_probe.owner"),
                                           "special": SimpleNamespace(condition_id=typed_executor.MARK_PREFIX + "special_probe.owner")})
    data = typed_executor.rules()
    monkeypatch.setitem(data, "mark_aliases", {"old_probe": "probe"})
    monkeypatch.setitem(data, "mark_counts_as", {"probe": ["special_probe"]})
    assert typed_executor.bears_mark(creature, "owner", "Probe")
    assert typed_executor.bears_mark(creature, "owner", "Old Probe")
    assert not typed_executor.bears_mark(creature, "other", "Probe")
    assert typed_executor.mark_condition_id("Old Probe", "owner") == typed_executor.MARK_PREFIX + "probe.owner"
    monkeypatch.delitem(data, "mark_aliases")
    monkeypatch.delitem(data, "mark_counts_as")
    assert not typed_executor.bears_mark(creature, "owner", "Probe")
    assert typed_executor.bears_mark(creature, "owner", "Old Probe")
    assert typed_executor.mark_condition_id("Old Probe", "owner") == typed_executor.MARK_PREFIX + "old_probe.owner"


@pytest.mark.parametrize("control,place,failed", [
    ("MANUAL", True, True), ("MANUAL", False, True),
    ("LOCAL_AUTO", True, True), ("MANUAL", True, False),
    ("LOCAL_AUTO", True, False),
])
def test_theater_failed_save_belongs_to_its_dancer_until_target_turn_end(tmp_path, control, place, failed):
    from combat.ext.soulstring_dancer import strings
    from combat.gate5_service import CombatService
    from test_riders_c8 import SD_ALL

    other, target = "actor:factory.c8_other_dancer", "actor:factory.c8_string_target"
    first = bundle(SD_ALL, dc=40 if failed else -40)
    # Mind Spike must seed one String even in the successful-Rhythm fixture.
    for action in first["action_catalog"]:
        if action["display_name"] == "Mind Spike":
            action["parameters"]["typed"]["numbers"]["save_dc"] = 40
    victim = bundle([MIND_SPIKE], actor_id=target)
    victim["actor_template"]["maximum_hp"] = 500
    service = CombatService(ROOT, tmp_path)
    session = service.persistence.create_match(
        match_seed="C8-TWO-DANCERS-REVIEW", maximum_rounds=20,
        typed_bundles=(first, bundle(SD_ALL, actor_id=other), victim),
        roster_setup={"primary_actor_ids": [ME, other, target],
                      "team_by_actor": {ME: "team:a", other: "team:a", target: "team:b"},
                      "starting_positions": {ME: {"x": 6, "y": 6}, other: {"x": 8, "y": 6},
                                             target: {"x": 7, "y": 7}}})
    metadata = {"participant_control_modes": {ME: "MANUAL", other: "MANUAL", target: "LOCAL_AUTO"}}
    stage = "seed"
    seen, decisions = [], []

    def choose(context):
        choice = context.reaction_source_id
        if choice.endswith("soulstring.place"):
            return ("place",) if stage == "seed" else ()
        if choice.endswith("soulstring.theater_string"):
            return ("place",) if stage == "trigger" and place else ()
        spec = context.extension_choice
        return spec.option_ids[:spec.minimum_selections] if spec is not None and not spec.allow_decline else ()

    def act(name, who=None):
        events, prompts, resolved = service_commit(service, session, metadata, name, who, choose=choose)
        seen.extend(prompts)
        decisions.extend(resolved)
        return events

    def advance(who):
        for _ in range(12):
            if session.engine.state.current_actor_id == who:
                return
            act("End turn")
        pytest.fail("Target turn not reached")

    def reload():
        nonlocal session
        session = service.persistence.load_match(session.match_id)
        assert session.verify()["status"] == "PASS"

    advance(ME)
    act("Mind Spike", target)  # One real String; decline the optional forced move.
    stage = "setup"
    act("End turn")
    advance(other)
    act("Theater of Strings")
    act("End turn")
    advance(ME)
    act("Theater of Strings")
    events = act("Stolen Rhythm", target)  # No mark; consumes the seeded String on failure.
    saves = [e for e in events if e.event_type == "SAVE_ROLLED" and e.actor_id == target]
    assert saves and saves[0].payload["success"] is not failed
    reload()
    prefix = "failed_spirit_save_round_:"
    # The original Mind Spike mark ends when A's current turn ends. Neither
    # dancer moves the target, and B has never forced a failed Spirit save.
    stage = "trigger"
    metadata["participant_control_modes"].update({ME: control, other: control})
    seen.clear()
    decisions.clear()
    act("End turn")
    advance(target)
    reload()
    creature = session.engine.state.actors[target]
    assert not typed_executor.bears_mark(creature, ME, "Resonance")
    assert not typed_executor.bears_mark(creature, other, "Resonance")
    assert "moved_unwillingly_round_" not in creature.turn_flags
    assert strings(session.engine, session.engine.state.actors[other], creature) == 0
    assert strings(session.engine, session.engine.state.actors[ME], creature) == (
        int(place) if failed else 1)  # A successful Rhythm preserves the original String.
    theater = [r for r in decisions if r["reaction_source_id"].endswith("soulstring.theater_string")]
    assert [r["reactor_id"] for r in theater] == ([ME] if failed else [])
    if theater:
        assert theater[0]["selection"] == ("USE" if place else "DECLINE")
    if control == "MANUAL":
        assert [p.reactor_id for p in seen if p.reaction_source_id.endswith("soulstring.theater_string")] == ([ME] if failed else [])
    else:
        assert not seen  # Local Auto resolves the actual field choice automatically.
    assert (prefix + ME in creature.turn_flags) is failed  # Survives start + reload.
    assert prefix + other not in creature.turn_flags
    before = strings(session.engine, session.engine.state.actors[ME], creature)
    act("End turn")
    reload()
    assert not any(k.startswith(prefix) for k in session.engine.state.actors[target].turn_flags)
    seen.clear()
    decisions.clear()
    advance(target)
    reload()
    assert not any(r["reaction_source_id"].endswith("soulstring.theater_string") for r in decisions)
    assert strings(session.engine, session.engine.state.actors[ME], session.engine.state.actors[target]) == before
    assert strings(session.engine, session.engine.state.actors[other], session.engine.state.actors[target]) == 0


@pytest.mark.parametrize("control", ["MANUAL", "LOCAL_AUTO"])
def test_borrowed_limbs_end_turn_failure_opens_a_new_theater_interval(tmp_path, control):
    from combat.gate5_service import CombatService
    from test_riders_c8 import SD_ALL

    victim = bundle([MIND_SPIKE], actor_id=FOE)
    victim["actor_template"]["maximum_hp"] = 500
    service = CombatService(ROOT, tmp_path)
    session = service.persistence.create_match(
        match_seed="C8-STRINGS-END-SAVE", maximum_rounds=20,
        typed_bundles=(bundle(SD_ALL, dc=40), victim),
        roster_setup={"primary_actor_ids": [ME, FOE], "team_by_actor": {ME: "team:a", FOE: "team:b"},
                      "starting_positions": {ME: {"x": 6, "y": 6}, FOE: {"x": 7, "y": 7}}})
    metadata = {"participant_control_modes": {ME: "MANUAL", FOE: control}}
    seed_strings = True

    def choose(context):
        if context.reaction_source_id.endswith("soulstring.place"):
            return ("place",) if seed_strings else ()
        spec = context.extension_choice
        return spec.option_ids[:spec.minimum_selections] if spec and not spec.allow_decline else ()

    def act(name, target=None):
        return service_commit(service, session, metadata, name, target, choose=choose)

    while session.engine.state.current_actor_id != ME:
        act("End turn")
    for _ in range(2):
        act("Mind Spike", FOE)
        act("End turn")
        act("End turn")
    seed_strings = False
    act("Dance of Borrowed Limbs", FOE)
    metadata["participant_control_modes"][ME] = control
    act("End turn")
    assert session.engine.state.current_actor_id == FOE
    key = "failed_spirit_save_round_:" + ME
    assert key in session.engine.state.actors[FOE].turn_flags
    events, prompts, resolved = act("End turn")
    saves = [e for e in events if e.event_type == "SAVE_ROLLED" and e.actor_id == FOE]
    assert saves and saves[0].source_definition_id.endswith("dance_of_borrowed_limbs")
    assert saves[0].payload["success"] is False
    reloaded = service.persistence.load_match(session.match_id)
    assert key in reloaded.engine.state.actors[FOE].turn_flags
    assert reloaded.verify()["status"] == "PASS"
    assert held(reloaded.engine.state.actors[FOE], "condition:typed.borrowed_limbs", ME)
    if control == "LOCAL_AUTO":
        assert not prompts
    else:
        assert any(p.reaction_source_id.endswith("soulstring.place") and p.reactor_id == ME for p in prompts)


def test_theater_ignores_and_retires_legacy_save_flag_without_source(tmp_path):
    from combat.ext.soulstring_dancer import strings
    from combat.gate5_service import CombatService
    from test_riders_c8 import SD_ALL

    service = CombatService(ROOT, tmp_path)
    session = service.persistence.create_match(
        match_seed="C8-STRINGS-LEGACY", typed_bundles=(bundle(SD_ALL),),
        roster_setup={"primary_actor_ids": [ME, FOE], "team_by_actor": {ME: "team:a", FOE: "team:b"},
                      "starting_positions": {ME: {"x": 6, "y": 6}, FOE: {"x": 7, "y": 7}}})
    metadata = {"participant_control_modes": {ME: "LOCAL_AUTO", FOE: "LOCAL_AUTO"}}
    while session.engine.state.current_actor_id != ME:
        service_commit(service, session, metadata, "End turn")
    # Compatibility fixture: the old lane's ambiguous turn flag, transported by
    # the existing runtime-control snapshot. No production save or class patched.
    session.engine.state.actors[FOE].turn_flags["failed_spirit_save_round_"] = "1:0"
    service_commit(service, session, metadata, "Theater of Strings")
    session = service.persistence.load_match(session.match_id)
    assert session.engine.state.actors[FOE].turn_flags["failed_spirit_save_round_"] == "1:0"
    assert session.verify()["status"] == "PASS"
    _, prompts, choices = service_commit(service, session, metadata, "End turn")
    assert not prompts and not any(r["reaction_source_id"].endswith("soulstring.theater_string") for r in choices)
    session = service.persistence.load_match(session.match_id)
    assert strings(session.engine, session.engine.state.actors[ME], session.engine.state.actors[FOE]) == 0
    service_commit(service, session, metadata, "End turn")
    reloaded = service.persistence.load_match(session.match_id)
    assert "failed_spirit_save_round_" not in reloaded.engine.state.actors[FOE].turn_flags
    assert reloaded.verify()["status"] == "PASS"


def commit(session, name, target=None):
    candidate = next(c for c in session.engine.legal_candidates()
                     if c.display_name == name and (target is None or target in c.target_ids))
    session.mechanical.execute_intent(ActionIntent(
        intent_id=f"c8-review-{candidate.state_version}", decision_id=candidate.decision_id,
        candidate_id=candidate.candidate_id, state_version=candidate.state_version,
        actor_id=candidate.actor_id, target_ids=candidate.target_ids, destination=candidate.destination))


def test_unrelated_existing_script_never_records_c8_tracking_flags(tmp_path):
    persistence = Gate4Persistence(ROOT, tmp_path)
    session = persistence.create_match(match_seed="TIANXIA-GATE2-MANUAL-0001", maximum_rounds=20)
    script = load_script(ROOT / "combat_gate2/scripted/Gate2_Scripted_Fight_Input.json")
    for index, step in enumerate(script.steps, 1):
        candidate, = [c for c in session.engine.legal_candidates() if _matches(c, step)]
        session.mechanical.execute_intent(ActionIntent(
            intent_id=f"intent:script:{index:04d}", decision_id=candidate.decision_id,
            candidate_id=candidate.candidate_id, state_version=candidate.state_version,
            actor_id=candidate.actor_id, target_ids=candidate.target_ids,
            destination=candidate.destination, option_ids=step.option_ids,
            reaction_decisions=step.reaction_decisions))
        assert all(not REVIEW_FLAGS.intersection(a.turn_flags)
                   for a in session.engine.state.actors.values())
    reloaded = persistence.load_match(session.match_id)
    assert reloaded.verify()["status"] == "PASS"


def service_commit(service, session, metadata, name, target=None, *, assign=True, choose=None):
    """Answer real service choices, then persist exactly the previewed intent.

    Optional unrelated reactions are declined by the manual fixture. AI choices
    use the real local controller. No production function or die roller is replaced.
    """
    from combat.gate2_runtime_models import ReactionDecision
    from combat.gate5_service import _ReactionRequired

    candidate = next(c for c in session.engine.legal_candidates()
                     if c.display_name == name and (target is None or target in c.target_ids))
    intent = ActionIntent(intent_id=f"c8-healing-{candidate.state_version}",
                          decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                          state_version=candidate.state_version, actor_id=candidate.actor_id,
                          target_ids=candidate.target_ids, destination=candidate.destination)
    decisions, prompts = [], []
    for _ in range(24):
        try:
            preview = service._run_preview(session, metadata, intent, tuple(decisions))
            break
        except _ReactionRequired as paused:
            context = paused.context
            prompts.append(context)
            spec = context.extension_choice
            choice = context.reaction_source_id
            if choose is not None:
                options = choose(context)
            elif choice.endswith("well.refuse"):
                options = ("refuse",) if (context.choice_trigger or {}).get("target_id") == ME else ()
            elif choice.endswith("well.deferred_healing"):
                options = ("assign",) if assign else ()
            elif spec is not None and not spec.allow_decline:
                options = spec.option_ids[:spec.minimum_selections]
            else:
                options = ()
            decisions.append(ReactionDecision(
                checkpoint=context.checkpoint, reactor_id=context.reactor_id,
                reaction_source_id=choice, selection="USE" if options else "DECLINE",
                option_ids=options))
    else:
        pytest.fail("Healing fixture produced too many service choices")
    before = len(session.engine.events)
    session.mechanical.execute_intent(ActionIntent.model_validate(preview["intent"]))
    events = session.engine.events[before:]
    assert [e.model_dump(mode="json") for e in events] == preview["events"]
    return events, prompts, preview["resolved_reactions"]


@pytest.mark.parametrize("scenario,control", [
    (scenario, control)
    for scenario in ("drum_denies", "drum_halves", "refuse", "both_denied", "both_halved")
    for control in ("MANUAL", "LOCAL_AUTO")
] + [("refuse_decline", "MANUAL"), ("both_halved_decline", "MANUAL")])
def test_actual_maw_healing_restrictions_and_assignment_commit_reload(tmp_path, control, scenario):
    from combat.ext import spirit_traditions as st
    from combat.gate5_service import CombatService
    from test_riders_c8 import HE_ALL, HE, TG_ALL, WH, RADIANCE, BEATS

    enemy = "actor:factory.c8_healing_enemy"
    protector = "actor:factory.c8_healing_protector"
    drum, refuse = scenario.startswith("drum") or scenario.startswith("both"), scenario.startswith("refuse") or scenario.startswith("both")
    denied = scenario in {"drum_denies", "both_denied"}
    assign = not scenario.endswith("decline")
    mine = bundle(HE_ALL, dc=40, cl=24)
    other = bundle([*(TG_ALL if drum else [MIND_SPIKE]), HE + "crown_of_borrowed_light"],
                   actor_id=enemy, dc=40 if denied else -40, wis=10)
    # A durable high-HP target survives the real Mind Spike + Maw setup sequence.
    other["actor_template"]["maximum_hp"] = 500
    bundles = [mine, other]
    actors = [ME, enemy]
    teams = {ME: "team:a", enemy: "team:b"}
    positions = {ME: {"x": 6, "y": 6}, enemy: {"x": 10, "y": 6}}
    if refuse:
        bundles.append(bundle([WH + "hourglass_mark", WH + "refuse_the_moment"], actor_id=protector))
        actors.append(protector)
        teams[protector] = "team:a"
        # The protector sees the eater within 30 feet, but cannot defer the Maw's
        # damage to its enemy (45 feet away). AI need not decline an eligible trigger.
        positions[protector] = {"x": 1, "y": 6}
    service = CombatService(ROOT, tmp_path)
    session = service.persistence.create_match(
        match_seed="C8-HEALING-REVIEW", typed_bundles=tuple(bundles), maximum_rounds=20,
        roster_setup={"primary_actor_ids": actors, "team_by_actor": teams, "starting_positions": positions})
    # Manual setup preserves the Reaction rather than spending it to protect the
    # enemy or taste its radiance. Switch to the tested mode for the actual trigger.
    metadata = {"participant_control_modes": {ME: "MANUAL", enemy: "LOCAL_AUTO", protector: "MANUAL"}}

    def act(name, target=None):
        return service_commit(service, session, metadata, name, target, assign=assign)

    def advance(actor):
        while session.engine.state.current_actor_id != actor:
            act("End turn")

    advance(enemy)
    act("Crown of Borrowed Light")  # Actual qualifying radiance earns Stolen Radiance.
    if drum:
        act("Burial Drum")
    act("End turn")
    advance(ME)
    act("Mind Spike", enemy)  # Actual failed Spirit save places the eater's mark.
    act("End turn")
    advance(enemy)
    metadata["participant_control_modes"][ME] = control
    metadata["participant_control_modes"][protector] = control
    _, damage_prompts, _ = act("Mind Spike", ME)  # Actual Refuse the Moment creates the deferred packet.
    if control == "MANUAL" and refuse:
        assert any(p.reaction_source_id.endswith("well.refuse") and p.reactor_id == protector for p in damage_prompts)
    if control == "LOCAL_AUTO":
        assert not damage_prompts
    act("End turn")
    advance(ME)
    session = service.persistence.load_match(session.match_id)
    assert session.verify()["status"] == "PASS"
    eater = session.engine.state.actors[ME]
    assert eater.resources[RADIANCE] >= 1
    deferred = held(eater, "condition:typed.deferred_consequence", protector)
    assert bool(deferred) is refuse
    waiting = sum(p[0] for p in st.data_of(eater, deferred[0])["packets"]) if refuse else 0
    events, prompts, reactions = act("Empty Heaven Maw", enemy)
    if control == "LOCAL_AUTO":
        assert not prompts
    [healing] = [e for e in events if e.event_type == "HEALING_APPLIED" and e.target_ids == (ME,)]
    damage = sum(e.payload["hp_damage"] for e in events
                 if e.event_type == "DAMAGE_COMMITTED" and enemy in e.target_ids)
    offer = min(damage // 2, eater.maximum_hp // 2)
    assert offer > 0
    surviving = 0 if denied else offer // 2 if drum else offer
    paid = min(waiting, surviving) if refuse and assign else 0
    assert healing.payload["offered"] == surviving - paid
    assert healing.payload["after"] == min(eater.maximum_hp, healing.payload["before"] + surviving - paid)
    if drum:
        saves = [e for e in events if e.event_type == "SAVE_ROLLED" and e.actor_id == ME
                 and e.payload["reason"].endswith(":WIS")]
        assert len(saves) == 1 and saves[0].payload["success"] is not denied
        if denied:
            assert session.engine.state.actors[enemy].resources[BEATS] >= 1
    assignment = [r for r in reactions if r["reaction_source_id"].endswith("well.deferred_healing")]
    assert bool(assignment) is (refuse and not denied)
    if assignment:
        assert assignment[0]["selection"] == ("USE" if assign else "DECLINE")
    if control == "MANUAL" and refuse and not denied:
        assert any(p.reaction_source_id.endswith("well.deferred_healing") and p.reactor_id == ME for p in prompts)
    if refuse:
        assert int(st.data_of(eater, deferred[0]).get("paid") or 0) == paid
    reloaded = service.persistence.load_match(session.match_id)
    assert reloaded.engine.state.actors[ME].current_hp == eater.current_hp
    if refuse:
        [reloaded_deferred] = held(reloaded.engine.state.actors[ME], "condition:typed.deferred_consequence", protector)
        assert int(st.data_of(reloaded.engine.state.actors[ME], reloaded_deferred).get("paid") or 0) == paid
    assert reloaded.verify()["status"] == "PASS"
    if refuse:
        session = reloaded
        before_arrival = session.engine.state.actors[ME].current_hp
        act("End turn")
        after_arrival = service.persistence.load_match(session.match_id)
        assert after_arrival.engine.state.actors[ME].current_hp == before_arrival - (waiting - paid)
        assert not held(after_arrival.engine.state.actors[ME], "condition:typed.deferred_consequence", protector)
        assert after_arrival.verify()["status"] == "PASS"
    assert all(not REVIEW_FLAGS.intersection(a.turn_flags)
               for a in reloaded.engine.state.actors.values())


def test_unrelated_crushing_blast_does_not_track_unwilling_movement(tmp_path):
    from test_auto_destruction import _bundle, CRUSHING, ME as caster

    persistence = Gate4Persistence(ROOT, tmp_path)
    session = persistence.create_match(
        match_seed="DESTRUCTION", typed_bundles=(_bundle([CRUSHING]),),
        roster_setup={"primary_actor_ids": [caster, FOE],
                      "team_by_actor": {caster: "team:a", FOE: "team:b"},
                      "starting_positions": {caster: {"x": 3, "y": 6}, FOE: {"x": 6, "y": 6}}})
    while session.engine.state.current_actor_id != caster:
        commit(session, "End turn")
    commit(session, "Blast Type: Crushing Break")
    commit(session, "Destructive Blast", FOE)
    reloaded = persistence.load_match(session.match_id)
    assert any(e.event_type == "MOVEMENT_COMMITTED" and e.payload.get("forced")
               for e in reloaded.engine.events)
    assert all(not REVIEW_FLAGS.intersection(a.turn_flags)
               for a in reloaded.engine.state.actors.values())
    assert reloaded.verify()["status"] == "PASS"


def test_unrelated_typed_technique_never_records_credence_tracking(tmp_path):
    persistence = Gate4Persistence(ROOT, tmp_path)
    session = persistence.create_match(
        match_seed="C8-REVIEW-INERT", typed_bundles=(bundle([MIND_SPIKE]),),
        roster_setup={"primary_actor_ids": [ME, FOE],
                      "team_by_actor": {ME: "team:a", FOE: "team:b"},
                      "starting_positions": {ME: {"x": 3, "y": 6}, FOE: {"x": 6, "y": 6}}})
    while session.engine.state.current_actor_id != ME:
        commit(session, "End turn")
    commit(session, "Mind Spike", FOE)
    reloaded = persistence.load_match(session.match_id)
    assert not REVIEW_FLAGS.intersection(reloaded.engine.state.actors[ME].turn_flags)
    assert reloaded.verify()["status"] == "PASS"


@pytest.mark.parametrize("control", ["MANUAL", "LOCAL_AUTO"])
@pytest.mark.parametrize("seed,success", [("C8-REPEAT-0", True), ("C8-REPEAT-1", False)])
def test_hourglass_end_turn_repeat_save_in_service_and_after_reload(tmp_path, control, seed, success):
    from combat.gate5_service import CombatService

    service = CombatService(ROOT, tmp_path)
    session = service.persistence.create_match(
        match_seed=seed, typed_bundles=(bundle(WH_ALL, dc=17),),
        roster_setup={"primary_actor_ids": [ME, FOE],
                      "team_by_actor": {ME: "team:a", FOE: "team:b"},
                      "starting_positions": {ME: {"x": 3, "y": 6}, FOE: {"x": 6, "y": 6}}})
    while session.engine.state.current_actor_id != ME:
        commit(session, "End turn")
    commit(session, "Hourglass Mark", FOE)
    session = service.persistence.load_match(session.match_id)
    mark = typed_executor.mark_condition_id("Hourglass Mark", ME)
    assert held(session.engine.state.actors[FOE], mark, ME)
    assert session.verify()["status"] == "PASS"
    while session.engine.state.current_actor_id != FOE:
        commit(session, "End turn")
    metadata = {"participant_control_modes": {actor: control for actor in (ME, FOE)}}
    candidate = next(c for c in session.engine.legal_candidates() if c.display_name == "End turn")
    intent = ActionIntent(intent_id="c8-repeat-preview", decision_id=candidate.decision_id,
                          candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                          actor_id=FOE, target_ids=candidate.target_ids)
    # The same end-turn save resolves without a player choice in either mode.
    service._run_preview(session, metadata, intent, ())
    before = len(session.engine.events)
    session.mechanical.execute_intent(intent)
    saves = [e for e in session.engine.events[before:]
             if e.event_type == "SAVE_ROLLED" and e.actor_id == FOE]
    assert len(saves) == 1 and saves[0].payload["success"] is success
    assert bool(held(session.engine.state.actors[FOE], mark, ME)) is not success
    reloaded = service.persistence.load_match(session.match_id)
    assert bool(held(reloaded.engine.state.actors[FOE], mark, ME)) is not success
    assert reloaded.verify()["status"] == "PASS"
