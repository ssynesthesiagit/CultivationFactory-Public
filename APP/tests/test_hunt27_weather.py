"""Sky Mantle combat modes are distinct from its ten-minute ritual.

AUTO13 r25 2026-10-04: the Weather Sign is now chosen by name from the printed six (and whether it is active or
forced with 1 extra Cultivation Point), instead of being a GM-confirmed free-text sign, so this file's Sky Mantle
answers are the matching "wind:active" option. Nothing else about what these tests check -- Touch range, refresh
duration and Concentration bookkeeping, the reload, the free cast -- changes.
"""
import pytest

from combat.ext.weather_mantle import MANTLE
from tests.test_hunt27_table import ALLY, ME, WEATHER, action, arena, commit, owner_turn


@pytest.mark.parametrize("manual", [True, False])
@pytest.mark.parametrize("mover", ["caster", "recipient"])
def test_non_ally_refresh_tracks_touch_range_after_table_movement(tmp_path, manual, mover):
    from combat.gate2_runtime_models import Position
    from combat.gate5_service import CombatService
    from tests.h1_support import ROOT
    from tests.test_hunt27_table import FOE

    combat, table, mid = arena(tmp_path, WEATHER, "weather-refresh-range", ask_actors=(FOE,),
                               maximum_rounds=6)
    owner_turn(combat, table, mid, tmp_path, idle=True)

    def accepting(prompt):
        if prompt["context"]["reaction_source_id"] == "choice:willing.consent":
            assert prompt["context"]["reactor_id"] == FOE
            assert "Mantle" in prompt["moment"] and "East foe" in prompt["moment"]
            return ["accept"]
        return ["wind:active"]

    commit(combat, table, mid, tmp_path,
           action(combat, mid, "Sky Mantle (willing creature)", FOE), choose=accepting)
    engine = combat._load_session(mid).engine
    commit(combat, table, mid, tmp_path, next(c.candidate_id for c in engine.legal_candidates()
                                            if c.kind.value == "END_TURN"))
    owner_turn(combat, table, mid, tmp_path, idle=True)
    # Isolate range from opportunity-attack damage and Concentration saves.
    if mover == "caster":
        commit(combat, table, mid, tmp_path, action(combat, mid, "Disengage"))
    engine = CombatService(ROOT, tmp_path)._load_session(mid).engine
    mantle = next(c for c in engine.state.actors[FOE].conditions.values() if c.condition_id == MANTLE)
    original = mantle.model_dump(mode="json")
    concentration = engine.state.actors[ME].concentration.model_dump(mode="json")
    cp = engine.state.actors[ME].resources["resource:core.qi"]
    refresh = "Refresh Mantle (willing creature)"
    assert any(c.display_name == refresh and FOE in c.target_ids for c in engine.legal_candidates())

    # Move through the table, rather than editing a loaded or saved position.
    moving_actor = ME if mover == "caster" else FOE
    destinations = ((Position(x=2, y=6), False), (Position(x=3, y=6), True)) if mover == "caster" else (
        (Position(x=4, y=8), False), (Position(x=4, y=6), True))
    for destination, in_touch in destinations:
        if mover == "recipient":
            # The bearer moves on its own turn; inspect refresh candidates on
            # the caster's next turn, after the movement has been persisted.
            for _ in range(8):
                engine = combat._load_session(mid).engine
                if engine.state.current_actor_id == FOE:
                    break
                commit(combat, table, mid, tmp_path, next(c.candidate_id for c in engine.legal_candidates()
                                                        if c.kind.value == "END_TURN"))
            else:
                pytest.fail("Mantle recipient never reached its turn")
            commit(combat, table, mid, tmp_path, action(combat, mid, "Disengage", FOE))
        engine = combat._load_session(mid).engine
        move = next(c for c in engine.legal_candidates()
                    if c.kind.value == "MOVE" and c.destination == destination)
        commit(combat, table, mid, tmp_path, move.candidate_id)
        if mover == "recipient":
            engine = combat._load_session(mid).engine
            commit(combat, table, mid, tmp_path, next(c.candidate_id for c in engine.legal_candidates()
                                                    if c.kind.value == "END_TURN"))
            owner_turn(combat, table, mid, tmp_path, idle=True)
        engine = CombatService(ROOT, tmp_path)._load_session(mid).engine
        assert engine.state.current_actor_id == ME
        assert engine.state.actors[moving_actor].position == destination
        assert engine._distance_actor_to_actor(engine.state.actors[ME], engine.state.actors[FOE]) == (5 if in_touch else 10)
        assert any(c.display_name == refresh and FOE in c.target_ids
                   for c in engine.legal_candidates()) == in_touch
        assert engine.state.actors[FOE].conditions[mantle.instance_id].model_dump(mode="json") == original
        assert engine.state.actors[ME].concentration.model_dump(mode="json") == concentration
        assert engine.state.actors[ME].resources["resource:core.qi"] == cp

    if not manual:
        combat.set_controller_mode(mid, actor_id=ME, controller_mode="LOCAL_AUTO")
    start = len(combat._load_session(mid).engine.events)
    answers = commit(combat, table, mid, tmp_path, action(combat, mid, refresh, FOE), choose=accepting)
    assert any(a["reaction_source_id"] == "choice:willing.consent" for a in answers)
    engine = CombatService(ROOT, tmp_path)._load_session(mid).engine
    assert engine.state.actors[ME].resources["resource:core.qi"] == cp - 1
    assert engine.state.actors[FOE].conditions[mantle.instance_id].model_dump(mode="json") == original
    assert engine.state.actors[ME].concentration.model_dump(mode="json") == concentration
    updates = [e for e in engine.events[start:] if e.event_type == "CONDITION_APPLIED"
               and e.payload.get("condition_id") == MANTLE]
    assert len(updates) == 1 and updates[0].payload["retained_instance_update"] == 1


@pytest.mark.parametrize(("manual", "sign_mode"), [(True, "active"), (True, "force"), (False, "active")])
@pytest.mark.parametrize("lingering", [True, False])
@pytest.mark.parametrize(("accept", "recipient_auto"), [(True, False), (False, False), (False, True)])
def test_non_ally_mantle_refresh_cost_instance_duration_concentration_reload(
        tmp_path, manual, sign_mode, lingering, accept, recipient_auto):
    from tests.test_hunt27_table import FOE, FOE2
    from combat.gate5_service import CombatService
    from tests.h1_support import ROOT

    combat, table, mid = arena(tmp_path, WEATHER, "weather-refresh", manual=manual,
                               ask_actors=(FOE,), maximum_rounds=12)
    owner_turn(combat, table, mid, tmp_path, idle=True)

    def accepting(prompt):
        if prompt["context"]["reaction_source_id"] == "choice:willing.consent":
            assert prompt["context"]["reactor_id"] == FOE
            assert "Mantle" in prompt["moment"] and "East foe" in prompt["moment"]
            return ["accept"]
        # The sign menu answers are "sign:mode" (AUTO13f1: the printed "active" or forced with 1 CP).
        return ["wind:force"]

    # A lingering Mantle must preserve separately held Concentration as well.
    if lingering:
        commit(combat, table, mid, tmp_path, action(combat, mid, "Sky Mantle"))
        cast = "Quick Mantle + Lingering Mantle (willing creature)"
    else:
        cast = "Sky Mantle (willing creature)"
    commit(combat, table, mid, tmp_path, action(combat, mid, cast, FOE), choose=accepting)
    engine = combat._load_session(mid).engine
    mantle = next(c for c in engine.state.actors[FOE].conditions.values() if c.condition_id == MANTLE)
    original = mantle.model_dump(mode="json")
    concentration = engine.state.actors[ME].concentration.model_dump(mode="json")
    commit(combat, table, mid, tmp_path, next(c.candidate_id for c in engine.legal_candidates()
                                          if c.kind.value == "END_TURN"))
    owner_turn(combat, table, mid, tmp_path, idle=True)
    if recipient_auto:
        # The recipient accepted the cast manually, then returned control to AI.
        # Its ordinary hostile-caster policy must refuse refresh automatically.
        combat.set_controller_mode(mid, actor_id=FOE, controller_mode="LOCAL_AUTO")
    engine = combat._load_session(mid).engine
    refresh = "Refresh Mantle (willing creature)"
    candidates = [c for c in engine.legal_candidates() if c.display_name == refresh]
    assert candidates and {tid for c in candidates for tid in c.target_ids} == {FOE}
    assert not any(FOE2 in c.target_ids for c in candidates), "No refresh without this caster's Mantle"
    before = engine.state.actors[ME].resources["resource:core.qi"]
    start = len(engine.events)

    def refreshing(prompt):
        if prompt["context"]["reaction_source_id"] == "choice:willing.consent":
            assert "Refresh Mantle" in prompt["moment"]
            assert prompt["context"]["reactor_id"] == FOE
            assert "East foe" in prompt["moment"]
            return ["accept" if accept else "refuse"]
        return [f"wind:{sign_mode}"]

    answers = commit(combat, table, mid, tmp_path, action(combat, mid, refresh, FOE), choose=refreshing)
    assert any(a["reaction_source_id"] == "choice:willing.consent" for a in answers) == (not recipient_auto)
    engine = CombatService(ROOT, tmp_path)._load_session(mid).engine
    assert engine.state.actors[ME].resources["resource:core.qi"] == before - 1 - int(accept and sign_mode == "force")
    if accept:
        # The printed "active or forced" pair is stored twice: `sign_supply` names the choice and `forced` is its
        # 0/1 flag, so a refresh answered with the other mode changes both.
        original["data"]["sign_supply"] = sign_mode
        original["data"]["forced"] = int(sign_mode == "force")
    assert engine.state.actors[FOE].conditions[mantle.instance_id].model_dump(mode="json") == original
    assert engine.state.actors[ME].concentration.model_dump(mode="json") == concentration
    updates = [e for e in engine.events[start:] if e.event_type == "CONDITION_APPLIED"
               and e.payload.get("condition_id") == MANTLE]
    if accept:
        assert len(updates) == 1 and updates[0].payload["retained_instance_update"] == 1
    else:
        assert not updates
    assert not any(e.event_type in ("CONCENTRATION_STARTED", "CONCENTRATION_ENDED", "CONDITION_REMOVED")
                   for e in engine.events[start:])

    # Exercise actual expiry after the accepted refresh, beyond merely keeping
    # the stored deadline unchanged. Cover both caster controllers and both
    # lifetime modes without repeating the long turn walk for every sign/refusal.
    if accept and sign_mode == "active":
        deadline = (original["data"]["expiry_round"], original["data"]["expiry_slot"])
        for _ in range(45):
            engine = CombatService(ROOT, tmp_path)._load_session(mid).engine
            now = (engine.state.round_number, engine.state.current_slot_index)
            if now >= deadline:
                break
            assert engine.state.actors[FOE].conditions[mantle.instance_id].model_dump(mode="json") == original
            assert engine.state.actors[ME].concentration.model_dump(mode="json") == concentration
            commit(combat, table, mid, tmp_path, next(c.candidate_id for c in engine.legal_candidates()
                                                     if c.kind.value == "END_TURN"))
        else:
            pytest.fail("Refreshed non-ally Mantle's original minute deadline never reached")
        assert now == deadline, "Refresh must not move the original expiry boundary"
        assert mantle.instance_id not in engine.state.actors[FOE].conditions
        assert not any(c.display_name == refresh and FOE in c.target_ids for c in engine.legal_candidates())
        removals = [e for e in engine.events[start:] if e.event_type == "CONDITION_REMOVED"
                    and e.payload.get("instance_id") == mantle.instance_id]
        assert len(removals) == 1


@pytest.mark.parametrize("manual", [True, False])
@pytest.mark.parametrize("accept", [True, False])
@pytest.mark.parametrize("hostile", [True, False])
def test_sky_mantle_recipient_consent_preserves_refused_mantle_reload(tmp_path, manual, accept, hostile):
    from tests.test_hunt27_table import FOE
    target = FOE if hostile else ALLY
    combat, table, mid = arena(tmp_path, WEATHER, "weather-consent", ask_actors=(target,))
    owner_turn(combat, table, mid, tmp_path, idle=True)
    name = "Sky Mantle (willing creature)" if hostile else "Sky Mantle"

    def accepting(prompt):
        return ["accept"] if prompt["context"]["reaction_source_id"] == "choice:willing.consent" else ["wind:active"]

    commit(combat, table, mid, tmp_path, action(combat, mid, name, target), choose=accepting)
    engine = combat._load_session(mid).engine
    original = next(c for c in engine.state.actors[target].conditions.values() if c.condition_id == MANTLE)
    concentration = engine.state.actors[ME].concentration.model_dump(mode="json")
    commit(combat, table, mid, tmp_path, next(c.candidate_id for c in engine.legal_candidates() if c.kind.value == "END_TURN"))
    owner_turn(combat, table, mid, tmp_path, idle=True)
    if not manual:
        combat.set_controller_mode(mid, actor_id=ME, controller_mode="LOCAL_AUTO")
    start = len(combat._load_session(mid).engine.events)

    def choose(prompt):
        if prompt["context"]["reaction_source_id"] == "choice:willing.consent":
            assert prompt["context"]["reactor_id"] == target
            assert "Sky Mantle" in prompt["moment"] and engine.state.actors[target].display_name in prompt["moment"]
            return ["accept" if accept else "refuse"]
        return ["wind:active"]

    answers = commit(combat, table, mid, tmp_path, action(combat, mid, name, target), choose=choose)
    assert any(a["reaction_source_id"] == "choice:willing.consent" for a in answers)
    engine = combat._load_session(mid).engine
    mantles = [c for c in engine.state.actors[target].conditions.values() if c.condition_id == MANTLE]
    assert len(mantles) == 1
    if accept:
        assert mantles[0].instance_id != original.instance_id
    else:
        assert mantles[0].model_dump(mode="json") == original.model_dump(mode="json")
        assert engine.state.actors[ME].concentration.model_dump(mode="json") == concentration
        assert not any(e.event_type == "CONCENTRATION_STARTED" for e in engine.events[start:])


@pytest.mark.parametrize("manual", [True, False])
@pytest.mark.parametrize("cl", [4, 5])
def test_lingering_mantle_cost_replacement_and_refresh_reload(tmp_path, manual, cl):
    combat, table, mid = arena(tmp_path, WEATHER, "weather", manual=manual, cl=cl)
    owner_turn(combat, table, mid, tmp_path, idle=True)
    before = combat._load_session(mid).engine.state.actors[ME].resources["resource:core.qi"]
    commit(combat, table, mid, tmp_path, action(combat, mid, "Sky Mantle + Lingering Mantle"))
    engine = combat._load_session(mid).engine
    first = next(c for c in engine.state.actors[ME].conditions.values() if c.condition_id == MANTLE)
    assert first.expires_on.startswith("START_OF_SLOT_AT:")
    assert engine.state.actors[ME].concentration is None
    assert not any(e.event_type == "CONCENTRATION_STARTED" for e in engine.events)
    commit(combat, table, mid, tmp_path,
           action(combat, mid, "Quick Mantle (free once per short rest) + Lingering Mantle", ALLY))
    engine = combat._load_session(mid).engine
    assert engine.state.actors[ME].resources["resource:core.qi"] == before - 5
    assert (first.instance_id in engine.state.actors[ME].conditions) == (cl >= 5)
    assert engine.state.actors[ME].concentration is None
    mantle = next(c for c in engine.state.actors[ALLY].conditions.values() if c.condition_id == MANTLE)
    original = mantle.model_dump(mode="json")
    commit(combat, table, mid, tmp_path, next(c.candidate_id for c in engine.legal_candidates()
                                          if c.kind.value == "END_TURN"))
    owner_turn(combat, table, mid, tmp_path, idle=True)
    commit(combat, table, mid, tmp_path, action(combat, mid, "Refresh Mantle", ALLY))
    engine = combat._load_session(mid).engine
    assert engine.state.actors[ME].resources["resource:core.qi"] == before - 6
    assert engine.state.actors[ALLY].conditions[mantle.instance_id].model_dump(mode="json") == original
    assert engine.state.actors[ME].concentration is None


@pytest.mark.parametrize(("manual", "mode"), [(True, "active"), (False, "active"), (True, "force")])
def test_lingering_mantle_preserves_other_concentration_reload(tmp_path, manual, mode):
    combat, table, mid = arena(tmp_path, WEATHER, "weather", manual=manual, cl=4)
    owner_turn(combat, table, mid, tmp_path, idle=True)
    before = combat._load_session(mid).engine.state.actors[ME].resources["resource:core.qi"]
    commit(combat, table, mid, tmp_path, action(combat, mid, "Sky Mantle"))
    engine = combat._load_session(mid).engine
    original = engine.state.actors[ME].concentration.model_dump(mode="json")
    commit(combat, table, mid, tmp_path, action(combat, mid, "Quick Mantle + Lingering Mantle", ALLY),
           choose=lambda prompt: ["accept"] if prompt["context"]["reaction_source_id"] == "choice:willing.consent" else [f"wind:{mode}"])
    engine = combat._load_session(mid).engine
    assert engine.state.actors[ME].concentration.model_dump(mode="json") == original
    assert any(c.condition_id == MANTLE for c in engine.state.actors[ME].conditions.values())
    assert any(c.condition_id == MANTLE for c in engine.state.actors[ALLY].conditions.values())
    assert engine.state.actors[ME].resources["resource:core.qi"] == before - 4 - int(mode == "force")


def test_lingering_mantle_expires_at_original_minute_table_reload(tmp_path):
    combat, table, mid = arena(tmp_path, WEATHER, "weather", cl=4, maximum_rounds=12)
    owner_turn(combat, table, mid, tmp_path)
    commit(combat, table, mid, tmp_path, action(combat, mid, "Sky Mantle + Lingering Mantle"))
    engine = combat._load_session(mid).engine
    mantle = next(c for c in engine.state.actors[ME].conditions.values() if c.condition_id == MANTLE)
    deadline = (mantle.data["expiry_round"], mantle.data["expiry_slot"])
    for _ in range(45):
        engine = combat._load_session(mid).engine
        now = (engine.state.round_number, engine.state.current_slot_index)
        assert (mantle.instance_id in engine.state.actors[ME].conditions) == (now < deadline)
        if now >= deadline:
            break
        commit(combat, table, mid, tmp_path, next(c.candidate_id for c in engine.legal_candidates()
                                              if c.kind.value == "END_TURN"))
    else:
        pytest.fail("Mantle's original minute deadline never reached")


def test_lingering_mantle_requires_owned_talent(tmp_path):
    combat, table, mid = arena(tmp_path, [t for t in WEATHER if t != "TAL_WEATHER_LINGERING_MANTLE"], "weather")
    assert not any("Lingering Mantle" in a.display_name for a in combat._load_session(mid).engine.action_catalog.values())


@pytest.mark.parametrize(("manual", "mode"), [(True, "active"), (False, "active"), (True, "force")])
def test_quick_mantle_bonus_and_free_cast_commit_reload(tmp_path, manual, mode):
    combat, table, mid = arena(tmp_path, WEATHER, "weather", manual=manual)
    owner_turn(combat, table, mid, tmp_path)
    engine = combat._load_session(mid).engine
    before = engine.state.actors[ME].resources["resource:core.qi"]
    assert any(a.display_name == "Quick Mantle" and a.economy.value == "BONUS_ACTION"
               for a in engine.action_catalog.values())
    commit(combat, table, mid, tmp_path, action(combat, mid, "Quick Mantle (free once per short rest)"),
           choose=lambda prompt: [f"wind:{mode}"])
    engine = combat._load_session(mid).engine
    assert engine.state.actors[ME].resources["resource:core.qi"] == before - int(mode == "force")
    assert any(c.condition_id == MANTLE for c in engine.state.actors[ME].conditions.values())
    commit(combat, table, mid, tmp_path, next(c.candidate_id for c in engine.legal_candidates()
                                          if c.kind.value == "END_TURN"))
    owner_turn(combat, table, mid, tmp_path)
    engine = combat._load_session(mid).engine
    assert not any("free once per short rest" in c.display_name for c in engine.legal_candidates())
    commit(combat, table, mid, tmp_path, action(combat, mid, "Quick Mantle"),
           choose=lambda prompt: ["wind:active"])
    assert combat._load_session(mid).engine.state.actors[ME].resources["resource:core.qi"] == before - int(mode == "force") - 1


def test_quick_mantle_variants_are_owner_gated(tmp_path):
    combat, table, mid = arena(tmp_path, [], "weather")
    assert not any("Quick Mantle" in a.display_name or "free once per short rest" in a.display_name
                   for a in combat._load_session(mid).engine.action_catalog.values())


def test_sky_mantle_and_refresh_compile_as_combat_actions(tmp_path):
    combat, table, mid = arena(tmp_path, WEATHER, "weather")
    owner_turn(combat, table, mid, tmp_path)
    actions = list(combat._load_session(mid).engine.action_catalog.values())
    assert any(a.display_name == "Sky Mantle" and a.economy.value == "ACTION" for a in actions)
    assert any(a.display_name == "Refresh Mantle" and a.economy.value == "BONUS_ACTION" for a in actions)
    refresh = next(a for a in actions if a.display_name == "Refresh Mantle")
    consenting = next(a for a in actions if a.display_name == "Refresh Mantle (willing creature)")
    assert refresh.range_ft is None and refresh.reach_ft is None, "Preserve the existing ally/self path"
    assert consenting.range_ft == consenting.parameters["typed"]["effects"][0]["range_ft"] == 5
    free = [a for a in actions if "free once per short rest" in a.display_name
            and "Lingering Mantle" not in a.display_name]
    assert {a.economy.value for a in free} == {"ACTION", "BONUS_ACTION"}
    assert len({a.costs for a in free}) == 1, "Both timings share one free-cast allowance"
    lingering = [a for a in actions if "free once per short rest" in a.display_name
                 and "Lingering Mantle" in a.display_name]
    assert {a.economy.value for a in lingering} == {"ACTION", "BONUS_ACTION"}
    assert {a.costs for a in lingering} == {(*free[0].costs, ("resource:core.qi", 2))}, \
        "The free base cast shares its allowance but does not waive the 2 CP augment"


@pytest.mark.parametrize(("manual", "mode"), [(True, "active"), (False, "active"), (True, "force")])
def test_sky_mantle_cast_refresh_costs_and_original_lifetime_reload(tmp_path, manual, mode):
    combat, table, mid = arena(tmp_path, WEATHER, "weather", manual=manual)
    owner_turn(combat, table, mid, tmp_path)
    engine = combat._load_session(mid).engine
    before = engine.state.actors[ME].resources["resource:core.qi"]
    answers = commit(combat, table, mid, tmp_path, action(combat, mid, "Sky Mantle"), choose=lambda prompt: [f"wind:{mode}"])
    engine = combat._load_session(mid).engine
    cost = 1 + int(mode == "force")
    assert engine.state.actors[ME].resources["resource:core.qi"] == before - cost
    mantle = next(c for c in engine.state.actors[ME].conditions.values() if c.condition_id == MANTLE)
    original = mantle.model_dump(mode="json")
    start = len(engine.events)
    refreshed = commit(combat, table, mid, tmp_path, action(combat, mid, "Refresh Mantle"), choose=lambda prompt: [f"wind:{mode}"])
    engine = combat._load_session(mid).engine
    assert engine.state.actors[ME].resources["resource:core.qi"] == before - 2 * cost
    assert engine.state.actors[ME].conditions[mantle.instance_id].model_dump(mode="json") == original
    updates = [e for e in engine.events[start:] if e.event_type == "CONDITION_APPLIED" and e.payload.get("condition_id") == MANTLE]
    assert len(updates) == 1 and updates[0].payload["retained_instance_update"] == 1
    assert not any(e.event_type == "CONCENTRATION_STARTED" for e in engine.events[start:])
    assert bool(answers) == bool(refreshed) == manual

    # Boundary check on a disposable loaded engine, supplementing the real
    # table/reload checks above. Refresh cannot turn a minute into the whole fight.
    from combat.ext.weather_mantle import expire_mantles
    engine.state.round_number = mantle.data["expiry_round"]
    engine.state.current_slot_index = mantle.data["expiry_slot"]
    expire_mantles(engine, engine.state.actors[ME])
    assert not any(c.condition_id == MANTLE for c in engine.state.actors[ME].conditions.values())
    assert engine.state.actors[ME].concentration is None
