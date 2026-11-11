"""Ink's printed creature effects through table commits and deterministic replay."""
import pytest

from combat import typed_executor as te, zones
from tests.r1i_service_support import fixture, candidate, force_ai_candidate, OWNER, FOE, SECOND
from tests.test_r1i_round3 import resolve, reload

INK = "tianxia.talent.ink."


@pytest.mark.parametrize("accept", [False, True])
@pytest.mark.parametrize("master,lifetime", [(False, "1 hour"), (True, "8 hours")])
def test_cross_team_player_consents_off_turn_to_ai_press_mark(tmp_path, accept, master, lifetime):
    from combat.canonical import canonical_sha256

    def ask_target(bundles):
        target = next(b for b in bundles if b["actor_id"] == FOE)
        target["reaction_plan"] = {**target["reaction_plan"], "ask": True, "mode": "ask"}
        target.pop("bundle_sha256", None)
        target["bundle_sha256"] = canonical_sha256(target)

    talent = "insight.master-calligrapher" if master else "INK_BASE_PRESS_MARK"
    combat, table, mid, send, commit = fixture(tmp_path, [talent],
        owner_dc=-40, bundle_transform=ask_target)
    cid = candidate(table, mid, "Press Mark", FOE)
    force_ai_candidate(combat, mid, OWNER, cid)
    before, prompts = resolve(combat, mid, send, cid,
        {"choice:needle.ink_accept": "accept" if accept else None}, auto=True)
    consent = next(p for p in prompts if p["context"]["reaction_source_id"] == "choice:needle.ink_accept")
    assert consent["context"]["reactor_id"] == FOE
    assert all(word in str(consent) for word in ("Press Mark", "Owner", "Foe", lifetime, "Ink abilities", "writer's Ink Mark"))
    engine = reload(tmp_path, mid)
    assert engine.state.current_actor_id == OWNER
    assert te.bears_mark(engine.state.actors[FOE], OWNER, "ink_mark") == accept
    assert bool([e for e in engine.events if e.event_type == "SAVE_ROLLED"]) == (not accept)
    assert engine.state.actors[OWNER].resources == before["actors"][OWNER]["resources"]


@pytest.mark.parametrize("willing", [False, True])
def test_paid_manual_concealment_is_honest_in_table_and_history_after_reload(tmp_path, willing):
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from tests.h1_support import ROOT

    combat, table, mid, send, commit = fixture(tmp_path, ["INK_BASE_PRESS_MARK"], seed="AUTO138-MARK")
    before, prompts = resolve(combat, mid, send, candidate(table, mid, "Press Mark", FOE),
        {"choice:needle.ink_conceal": "conceal", "choice:needle.ink_accept": "accept" if willing else None})
    paid_prompt = next(p for p in prompts if p["context"]["reaction_source_id"] == "choice:needle.ink_conceal")
    assert "manual" in str(paid_prompt).lower()
    assert "shared table" in str(paid_prompt).lower()
    assert "failed" not in str(paid_prompt).lower()
    engine = reload(tmp_path, mid)
    assert bool([e for e in engine.events if e.event_type == "SAVE_ROLLED"]) == (not willing)
    assert sum(before["actors"][OWNER]["resources"].values()) - sum(engine.state.actors[OWNER].resources.values()) == 1
    # This table is shared by both teams. Both must see the manual reminder,
    # rather than a claim that payment hides the row from an opponent's screen.
    for service in (table, TabletopService(CombatService(ROOT, tmp_path), tmp_path)):
        shown = next(a for a in service.state(mid)["presentation"]["actors"] if a["entity_id"] == FOE)
        mark = next(c for c in shown["conditions"] if c["condition_id"] == te.mark_condition_id("ink_mark", OWNER))
        assert "manual" in mark["display_name"].lower() and "1 hour" in mark["display_name"]
        assert not mark["hidden"]
        history = service.events(mid, 0)
        assert any("manual" in e["summary"].lower() and "Ink Mark" in e["summary"] for e in history["events"])


def owner_turn(table, mid, commit, who=OWNER):
    while table.state(mid)["menu"]["actor_id"] != who:
        commit(table.state(mid)["menu"]["end_turn"])


@pytest.mark.parametrize("conceal", [False, True])
@pytest.mark.parametrize("ai", [False, True])
def test_press_mark_optional_price_hostile_save_and_reload(tmp_path, conceal, ai):
    combat, table, mid, send, commit = fixture(tmp_path, ["INK_BASE_PRESS_MARK"], seed="AUTO138-MARK")
    cid = candidate(table, mid, "Press Mark", FOE)
    if ai:
        force_ai_candidate(combat, mid, OWNER, cid)
        combat.set_controller_mode(mid, actor_id=FOE, controller_mode="LOCAL_AUTO")
    before, prompts = resolve(combat, mid, send, cid,
        {"choice:needle.ink_conceal": "conceal" if conceal else None}, auto=ai)
    engine = reload(tmp_path, mid)
    mark = next(c for c in engine.state.actors[FOE].conditions.values()
                if c.condition_id == te.mark_condition_id("ink_mark", OWNER))
    paid = conceal and not ai
    assert bool(mark.data.get("concealed")) == paid
    assert mark.expires_on != "UNTIL_REMOVED"
    resources = before["actors"][OWNER]["resources"]
    assert sum(resources.values()) - sum(engine.state.actors[OWNER].resources.values()) == int(paid)
    assert any(e.event_type == "SAVE_ROLLED" and e.actor_id == FOE for e in engine.events)
    assert bool(prompts) == (not ai)
    assert not [e for e in engine.events if e.event_type == "RULE_REMINDER"]


def test_press_mark_willing_ally_has_no_save_or_price(tmp_path):
    combat, table, mid, send, commit = fixture(tmp_path, ["INK_BASE_PRESS_MARK"], allies=[FOE])
    before, prompts = resolve(combat, mid, send, candidate(table, mid, "Press Mark", FOE),
                              {"choice:needle.ink_accept": "accept"})
    engine = reload(tmp_path, mid)
    assert te.bears_mark(engine.state.actors[FOE], OWNER, "ink_mark")
    assert engine.state.actors[OWNER].resources == before["actors"][OWNER]["resources"]
    assert not [e for e in engine.events if e.event_type == "SAVE_ROLLED"]
    assert prompts and "Foe" in str(prompts[0])


def test_press_mark_successful_hostile_save_leaves_no_mark(tmp_path):
    combat, table, mid, send, commit = fixture(tmp_path, ["INK_BASE_PRESS_MARK"], owner_dc=-40)
    resolve(combat, mid, send, candidate(table, mid, "Press Mark", FOE), {})
    engine = reload(tmp_path, mid)
    assert not te.bears_mark(engine.state.actors[FOE], OWNER, "ink_mark")


def test_scripture_prison_success_penalties_end_on_targets_turn(tmp_path):
    combat, table, mid, send, commit = fixture(tmp_path, [INK + "scripture_prison"], owner_dc=-40)
    commit(candidate(table, mid, "Scripture Prison", FOE))
    engine = reload(tmp_path, mid)
    target = engine.state.actors[FOE]
    denied = next(c for c in target.conditions.values() if c.condition_id == "condition:typed.reaction_denied")
    assert denied.expires_on.startswith(f"START_OF_TURN_AT:{FOE}:")
    assert engine._effective_speed(target) == 20
    commit(table.state(mid)["menu"]["end_turn"])
    owner_turn(table, mid, commit, FOE)
    engine = reload(tmp_path, mid)
    assert engine._effective_speed(engine.state.actors[FOE]) == 30
    assert not [c for c in engine.state.actors[FOE].conditions.values() if c.condition_id == "condition:typed.reaction_denied"]


@pytest.mark.parametrize("dc", [1, 50])
def test_scripture_prison_action_escape_success_and_failure(tmp_path, dc):
    combat, table, mid, send, commit = fixture(tmp_path, [INK + "scripture_prison"], owner_dc=dc,
        foe_score=30, bundle_transform=lambda bs: bs[1]["actor_template"]["saving_throws"].update(DEX=-100))
    commit(candidate(table, mid, "Scripture Prison", FOE))
    engine = reload(tmp_path, mid)
    restraint = next(c for c in engine.state.actors[FOE].conditions.values() if c.condition_id == "condition:typed.restrained")
    assert restraint.data["action_escape"]["dc"] == dc
    assert restraint.data["repeat_save"]["ability"] == "DEX"
    commit(table.state(mid)["menu"]["end_turn"])
    owner_turn(table, mid, commit, FOE)
    before, prompts = resolve(combat, mid, send, candidate(table, mid, "Escape source restraint"),
                              {"choice:needle.restraint_escape": "$first"})
    engine = reload(tmp_path, mid)
    assert bool([c for c in engine.state.actors[FOE].conditions.values() if c.condition_id == "condition:typed.restrained"]) == (dc == 50)
    checks = [e.payload for e in engine.events if e.event_type == "CHECK_ROLLED"]
    assert checks[-1]["ability"] == "STR" and checks[-1]["dc"] == dc
    assert any("Scripture Prison" in o["label"] for p in prompts for o in p["choice"]["options"])


@pytest.mark.parametrize("heavy", [False, True])
def test_ink_cloud_paid_obscurity_expires_and_replays(tmp_path, heavy):
    combat, table, mid, send, commit = fixture(tmp_path, [INK + "ink_cloud"])
    cid = next(o["candidate_id"] for g in table.state(mid)["menu"]["actions"] if g["label"] == "Ink Cloud"
               for o in g["options"] if o.get("destination") == {"x": 4, "y": 6})
    before, prompts = resolve(combat, mid, send, cid, {
        "choice:needle.ink_cloud": "heavy" if heavy else None, "choice:needle.area_recipients": FOE})
    engine = reload(tmp_path, mid)
    cloud = next(z for z in zones.typed_zones(engine) if z.owner_id == OWNER)
    assert cloud.trigger_profile["obscured"] == ("heavy" if heavy else "light")
    assert any("Perception" in str(p) for p in prompts)
    assert any(c.source_definition_id.endswith(INK + "ink_cloud") and c.data.get("rule", {}).get("check_mode")
               for c in engine.state.actors[FOE].conditions.values())
    assert not any(c.source_definition_id.endswith(INK + "ink_cloud") for c in engine.state.actors[SECOND].conditions.values())
    assert sum(before["actors"][OWNER]["resources"].values()) - sum(engine.state.actors[OWNER].resources.values()) == 1 + int(heavy)
    commit(table.state(mid)["menu"]["end_turn"])
    owner_turn(table, mid, commit)
    engine = reload(tmp_path, mid)
    assert not [z for z in zones.typed_zones(engine) if z.owner_id == OWNER]
    assert not any(c.source_definition_id.endswith(INK + "ink_cloud") for c in engine.state.actors[FOE].conditions.values())


def test_ink_domain_free_mark_reaches_the_whole_domain(tmp_path):
    combat, table, mid, send, commit = fixture(tmp_path, [INK + "ink_domain"],
        positions={OWNER: {"x": 3, "y": 0}, FOE: {"x": 9, "y": 0}, SECOND: {"x": 10, "y": 0}})
    commit(candidate(table, mid, "Ink Domain"))
    before = reload(tmp_path, mid).state.actors[OWNER].resources.copy()
    cid = candidate(table, mid, "Press Mark (free)", FOE)
    assert not [o for g in table.state(mid)["menu"]["actions"] if "Press Mark (free)" in g["label"]
                for o in g["options"] if SECOND in o.get("target_ids", [])]
    resolve(combat, mid, send, cid, {})
    engine = reload(tmp_path, mid)
    assert te.bears_mark(engine.state.actors[FOE], OWNER, "ink_mark")
    assert engine.state.actors[OWNER].resources == before
    assert not engine.state.actors[OWNER].action_available
    assert not [g for g in table.state(mid)["menu"]["actions"] if "Press Mark (free)" in g["label"]]


@pytest.mark.parametrize("form,ac,speed", [("tiger", 16, 40), ("crane", 16, 40),
                                         ("serpent", 16, 40), ("spider", 16, 40),
                                         ("horse", 16, 60), ("tortoise", 19, 20)])
def test_living_illustration_form_belongs_to_summon_and_replays(tmp_path, form, ac, speed):
    from combat import flight
    combat, table, mid, send, commit = fixture(tmp_path, [INK + "painted_beast", INK + "living_illustration"],
        positions={OWNER: {"x": 3, "y": 0}, FOE: {"x": 5, "y": 0}, SECOND: {"x": 8, "y": 0}}, seed="AUTO138-BEAST")
    summon = candidate(table, mid, "Painted Beast")
    before, prompts = resolve(combat, mid, send, summon,
                              {"choice:needle.ink_forms": form})
    engine = reload(tmp_path, mid)
    beast = next(a for a in engine.state.actors.values() if (a.summon or {}).get("group") == "painted_beast")
    assert beast.summon["ink_forms"] == form
    assert beast.armor_class + engine._ac_modifier(beast) == ac and beast.maximum_hp == 85 and engine._effective_speed(beast) == speed
    assert engine.state.actors[OWNER].armor_class == before["actors"][OWNER]["armor_class"]
    if form == "crane":
        assert flight.profile(engine, beast).speed_ft == 50
        assert flight.profile(engine, beast).hover
    if form in {"tiger", "serpent", "spider"}:
        commit(candidate(table, mid, "Command Painted Beast"))
        commit(table.state(mid)["menu"]["end_turn"])
        owner_turn(table, mid, commit, beast.entity_id)
        commit(candidate(table, mid, "Ink Fang", FOE))
        engine = reload(tmp_path, mid)
        assert engine.state.actors[FOE].current_hp < before["actors"][FOE]["current_hp"]
        if form == "tiger":
            damage = [e.payload for e in engine.events if e.event_type == "DAMAGE_ROLLED" and e.actor_id == beast.entity_id]
            assert len(damage[-1]["dice"]) == 3 and all(1 <= d <= 6 for d in damage[-1]["dice"])
        elif form == "serpent":
            poison = next(c for c in engine.state.actors[FOE].conditions.values() if c.condition_id == "condition:typed.poisoned")
            assert poison.source_actor_id == OWNER and poison.expires_on == "START_OF_SOURCE_NEXT_TURN"
            commit(table.state(mid)["menu"]["end_turn"])
            owner_turn(table, mid, commit, OWNER)
            assert not [c for c in reload(tmp_path, mid).state.actors[FOE].conditions.values()
                        if c.condition_id == "condition:typed.poisoned"]
        else:
            assert engine._effective_speed(engine.state.actors[FOE]) == 0


def test_illustration_adept_adds_stats_and_second_distinct_benefit(tmp_path):
    combat, table, mid, send, commit = fixture(tmp_path,
        [INK + "painted_beast", INK + "living_illustration", "insight.living-illustration-adept"])
    # fixture's commit helper must answer multi-select minimums explicitly.
    answers = []
    cid = candidate(table, mid, "Painted Beast")
    for _ in range(8):
        result = send(cid, answers)
        if result["status"] == "COMMITTED":
            break
        p = result["reaction"]
        answers.append({**p["context"], "selection": "USE", "option_ids": ["tiger", "tortoise"]})
    else:
        pytest.fail("form selection did not commit")
    engine = reload(tmp_path, mid)
    beast = next(a for a in engine.state.actors.values() if (a.summon or {}).get("group") == "painted_beast")
    assert beast.armor_class + engine._ac_modifier(beast) == 21 and beast.maximum_hp == 119 and engine._effective_speed(beast) == 20
    assert set(beast.summon["ink_forms"].split(",")) == {"tiger", "tortoise"}


@pytest.mark.parametrize("off_turn", [False, True])
def test_spider_speed_returns_on_writers_next_turn_after_table_commit_and_cold_reload(tmp_path, off_turn):
    """Ink Fang and its opportunity hit share the writer's clock, not the beast's or victim's.

    Hits commit through the table; subsequent boundaries use the persisted
    session's execute_intent. Every boundary is checked by a fresh service and
    mechanical replay, including the target's turn before the writer returns.
    """
    from combat.gate2_runtime_models import ActionIntent
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from tests.h1_support import ROOT

    combat, table, mid, send, commit = fixture(tmp_path,
        [INK + "painted_beast", INK + "living_illustration"],
        positions={OWNER: {"x": 3, "y": 0}, FOE: {"x": 5, "y": 0}, SECOND: {"x": 8, "y": 0}},
        seed="AUTO138-BEAST")
    resolve(combat, mid, send, candidate(table, mid, "Painted Beast"), {"choice:needle.ink_forms": "spider"})
    beast = next(a for a in reload(tmp_path, mid).state.actors.values()
                 if (a.summon or {}).get("group") == "painted_beast")
    commit(candidate(table, mid, "Command Painted Beast"))
    commit(table.state(mid)["menu"]["end_turn"])
    owner_turn(table, mid, commit, beast.entity_id)
    if off_turn:
        commit(table.state(mid)["menu"]["end_turn"])
        owner_turn(table, mid, commit, FOE)
        cid = next(o["candidate_id"] for o in table.state(mid)["menu"]["moves"]
                   if o["destination"] == {"x": 5, "y": 2})
        answers = []
        for _ in range(16):
            result = send(cid, answers)
            if result["status"] == "COMMITTED":
                break
            assert result["status"] == "REACTION_REQUIRED", result
            prompt = result["reaction"]
            # Accept only the Painted Beast's actual opportunity attack.
            answers.append({**prompt["context"], "selection":
                "USE" if prompt["context"]["reactor_id"] == beast.entity_id else "DECLINE"})
        assert result["status"] == "COMMITTED"
    else:
        commit(candidate(table, mid, "Ink Fang", FOE))

    engine = reload(tmp_path, mid)
    hit_actor = FOE if off_turn else beast.entity_id
    assert engine.state.current_actor_id == hit_actor
    assert any(e.event_type == "ATTACK_ROLLED" and e.actor_id == beast.entity_id
               and (e.source_definition_id.endswith("opportunity_attack") if off_turn
                    else ".attack" in e.source_definition_id)
               for e in engine.events)
    assert engine._effective_speed(engine.state.actors[FOE]) == 0
    writer_turn = engine.state.actors[OWNER].turns_started
    speed_rows = [m for m in engine.state.actors[FOE].modifiers.values() if m.target_field == "speed_ft"]
    assert len(speed_rows) == 1
    modifier_id = speed_rows[0].modifier_id
    saw_target_turn = off_turn

    for _ in range(8):
        # Do not mutate an engine behind the persistence reducer.
        session = CombatService(ROOT, tmp_path)._load_session(mid)
        end = next(c for c in session.engine.legal_candidates() if c.display_name == "End turn")
        session.mechanical.execute_intent(ActionIntent(
            intent_id=f"auto138r2-end-{session.engine.state.event_sequence}",
            decision_id=end.decision_id, candidate_id=end.candidate_id,
            state_version=end.state_version, actor_id=end.actor_id, target_ids=end.target_ids))
        engine = reload(tmp_path, mid)
        fresh_table = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
        assert fresh_table.state(mid)["menu"]["actor_id"] == engine.state.current_actor_id
        if engine.state.current_actor_id == OWNER:
            assert engine.state.actors[OWNER].turns_started == writer_turn + 1
            assert engine._effective_speed(engine.state.actors[FOE]) == 30
            assert modifier_id not in engine.state.actors[FOE].modifiers
            removed = next(e for e in engine.events if e.event_type == "MODIFIER_REMOVED"
                           and e.payload.get("modifier_id") == modifier_id)
            assert removed.actor_id == OWNER and removed.payload["checkpoint"] == "START_OF_TURN"
            break
        saw_target_turn |= engine.state.current_actor_id == FOE
        assert engine.state.actors[OWNER].turns_started == writer_turn
        assert engine._effective_speed(engine.state.actors[FOE]) == 0
        assert modifier_id in engine.state.actors[FOE].modifiers
    else:
        pytest.fail("writer's next turn never started")
    assert saw_target_turn
