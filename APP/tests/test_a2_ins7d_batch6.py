"""INS7D creation, sound-reroll and pursuit service transactions + cold replay."""
import pytest

from combat.ext import insights7_batch6 as plug
from tests.auto_worker1_support import LEFT, RIGHT, act, action_sender, cell_send, fight, reload, resolve, turn


def fresh(combat, mid):
    engine = reload(combat, mid)
    session = combat._load_session(mid)
    assert session.verify()["status"] == "PASS"
    assert session.mechanical.replay()["status"] == "PASS"
    return engine


def sheet(feature, owns=True):
    def edit(doc, aid):
        if aid == LEFT:
            doc["spheres_and_talents"]["cultivation_insight_record_ids"] = [feature] if owns else []
    return edit


WALL = {"name": "Humble Wall", "centered_on_self": True, "size_ft": 5,
        "wall": {"thick_ft": 5, "height_ft": 5, "object": {"ac": "12", "hp": "25", "scope": "section"}},
        "duration": {"kind": "one_minute"}}


def road_match(tmp_path, *, owns=True, sphere="tianxia.sphere.earth", duration=10, name="Humble Wall"):
    spec = {**WALL, "name": name, "duration": {"kind": "rounds", "amount": duration}}
    return fight(tmp_path, sheet_edit=sheet(plug.ROAD, owns), prepare=[{"type": "zone"}],
        prepare_target="SELF", prepare_zone_spec=spec, prepare_sphere=sphere)


def created(engine):
    return [e.payload["zone"] for e in engine.events if e.event_type == "ZONE_CREATED"]


@pytest.mark.parametrize("choice", ["hp", "duration", "section"])
@pytest.mark.parametrize("ai", [False, True])
def test_earth_refinements_are_one_choice_per_scene_and_reload(tmp_path, choice, ai):
    c, t, mid = road_match(tmp_path)
    if ai:
        # Automatic preference comes from its own compiled row, not target HP.
        # HP is first; other outcomes are exercised as player-owned choices.
        choice = "hp"
    _, prompts = resolve(action_sender(c, t, mid, "Prepare", ai=ai), {plug.CHOICE + "road": [choice]})
    e = fresh(c, mid)
    zone = created(e)[0]
    assert zone["duration_rounds"] == (100 if choice == "duration" else 10)
    assert int(zone["trigger_profile"]["wall"]["object"]["hp"]) == (40 if choice == "hp" else 25)
    assert len(zone["affected_cells"]) == (2 if choice == "section" else 1)
    if not ai:
        q = next(p for p in prompts if p["context"]["reaction_source_id"] == plug.CHOICE + "road")
        assert {o["id"] for o in q["choice"]["options"]} == {"hp", "duration", "section"}
    else:
        assert not prompts
        c.set_controller_mode(mid, actor_id=LEFT, controller_mode="MANUAL")
    # Separate committed activation, after cold reload, cannot refine again.
    resolve(lambda a: act(t, mid, "Prepare", a))
    assert int(created(fresh(c, mid))[-1]["trigger_profile"]["wall"]["object"]["hp"]) == 25


@pytest.mark.parametrize("before,after", [(10, 100), (100, 600), (600, 14400)])
def test_each_printed_duration_step(tmp_path, before, after):
    c, t, mid = road_match(tmp_path, duration=before)
    resolve(lambda a: act(t, mid, "Prepare", a), {plug.CHOICE + "road": ["duration"]})
    assert created(fresh(c, mid))[0]["duration_rounds"] == after


@pytest.mark.parametrize("owns,sphere", [(False, "tianxia.sphere.earth"), (True, "tianxia.sphere.force")])
def test_other_owners_and_non_earth_creations_are_inert(tmp_path, owns, sphere):
    c, t, mid = road_match(tmp_path, owns=owns, sphere=sphere)
    _, prompts = resolve(lambda a: act(t, mid, "Prepare", a))
    assert not prompts and created(fresh(c, mid))[0]["duration_rounds"] == 10


def test_decline_preserves_refinement_and_all_adjacent_sections_are_offered(tmp_path):
    c, t, mid = road_match(tmp_path)
    resolve(lambda a: act(t, mid, "Prepare", a), {plug.CHOICE + "road": []})
    assert not fresh(c, mid).state.actors[LEFT].turn_flags.get("_round_ins7d_road_used")
    _, prompts = resolve(lambda a: act(t, mid, "Prepare", a), {plug.CHOICE + "road": ["section"]})
    q = next(p for p in prompts if p["context"]["reaction_source_id"] == plug.CHOICE + "road_section")
    assert len(q["choice"]["options"]) == 8
    assert fresh(c, mid).state.actors[LEFT].turn_flags["_round_ins7d_road_used"] == 1


def test_real_humble_wall_compilation_uses_refinement(tmp_path):
    c, t, mid = fight(tmp_path, ["TAL_EARTH_HUMBLE_WALL"], spheres=["tianxia.sphere.earth"],
                      sheet_edit=sheet(plug.ROAD))
    resolve(cell_send(t, mid, "Humble Wall", (4, 6)), {plug.CHOICE + "road": ["hp"]})
    zone = created(fresh(c, mid))[0]
    assert int(zone["trigger_profile"]["wall"]["object"]["hp"]) == 40


def test_extra_wall_section_can_extend_diagonally_after_reload(tmp_path):
    c, t, mid = road_match(tmp_path)
    owner = fresh(c, mid).state.actors[LEFT]
    destination = f"cell:{owner.position.x + 1},{owner.position.y + 1}"
    _, prompts = resolve(lambda a: act(t, mid, "Prepare", a),
        {plug.CHOICE + "road": ["section"], plug.CHOICE + "road_section": [destination]})
    q = next(p for p in prompts if p["context"]["reaction_source_id"] == plug.CHOICE + "road_section")
    assert destination in {o["id"] for o in q["choice"]["options"]}
    cells = created(fresh(c, mid))[0]["affected_cells"]
    assert {"x": owner.position.x + 1, "y": owner.position.y + 1} in cells


def silent_match(tmp_path, *, owns=True, hazard="sound", area=None, area_owner=LEFT, ai=False, dc=100):
    check = {"type": "contest_against", "actor_check": {"kind": "check", "ability": "DEX", "skill": "stealth",
             "hazards": [hazard]}, "target_check": {"kind": "dc", "dc": dc}, "on_success": [], "on_fail": []}
    def bundle(b):
        if area and b["actor_id"] == area_owner:
            a = next(a for a in b["action_catalog"] if a["display_name"] == ("Ward" if area_owner == LEFT else "Cause"))
            a["parameters"]["typed"]["source"] = area
            a["parameters"]["typed"]["zone_spec"] = spec
    spec = {"name": "Dampen Sound", "centered_on_self": True, "shape": "sphere", "size_ft": 15,
            "duration": {"kind": "one_minute"}}
    extras = [("Ward", {"effects": [{"type": "zone"}], "zone_spec": spec})] if area_owner == LEFT else []
    return fight(tmp_path, sheet_edit=sheet(plug.SILENT, owns), prepare=[check], extra_actions=extras,
        cause=[{"type": "zone"}] if area_owner == RIGHT else [], cause_target="SELF", bundle_edit=bundle,
        reaction_ask=not ai, prepare_target="HOSTILE_ENTITY")


def rewrites(engine):
    return [e for e in engine.events if e.event_type == "D20_REWRITTEN" and e.source_definition_id == plug.SILENT
            and e.payload.get("operation") == "reroll"]


@pytest.mark.parametrize("area", [None, "TAL_SOUND_DAMPEN_SOUND", "TAL_SOUND_TRUE_SILENCE"])
@pytest.mark.parametrize("ai", [False, True])
def test_sound_failure_reroll_once_per_scene_with_owned_area_bonus(tmp_path, area, ai):
    c, t, mid = silent_match(tmp_path, area=area, ai=ai)
    if area:
        resolve(lambda a: act(t, mid, "Ward", a))
    _, prompts = resolve(action_sender(c, t, mid, "Prepare", ai=ai, target_id=RIGHT))
    e = fresh(c, mid)
    assert len(rewrites(e)) == 1
    bonuses = [ev for ev in e.events if ev.event_type == "D20_REWRITTEN"
               and ev.source_definition_id == plug.SILENT and ev.payload.get("operation") == "bonus"]
    assert [ev.payload["bonus"] for ev in bonuses] == ([4] if area else [])
    rolled = [r for r in e.rolls if r.reason.startswith("CHECK:") and r.actor_id == LEFT][-1]
    assert rolled.modifier == (6 if area else 2)
    assert bool(prompts) != ai
    if ai:
        c.set_controller_mode(mid, actor_id=LEFT, controller_mode="MANUAL")
    resolve(lambda a: act(t, mid, "Prepare", a, target_id=RIGHT))
    assert len(rewrites(fresh(c, mid))) == 1


@pytest.mark.parametrize("owns,hazard", [(False, "sound"), (True, "visual_concealment"), (True, "ordinary")])
def test_unowned_and_non_sound_failed_checks_do_not_reroll(tmp_path, owns, hazard):
    c, t, mid = silent_match(tmp_path, owns=owns, hazard=hazard)
    _, prompts = resolve(lambda a: act(t, mid, "Prepare", a, target_id=RIGHT))
    assert not prompts and not rewrites(fresh(c, mid))


def test_successful_sound_check_does_not_spend_reroll(tmp_path):
    c, t, mid = silent_match(tmp_path, dc=-100)
    _, prompts = resolve(lambda a: act(t, mid, "Prepare", a, target_id=RIGHT))
    assert not prompts and not rewrites(fresh(c, mid))


def test_other_owners_sound_area_does_not_add_bonus(tmp_path):
    c, t, mid = silent_match(tmp_path, area="TAL_SOUND_DAMPEN_SOUND", area_owner=RIGHT)
    turn(t, mid, RIGHT)
    resolve(lambda a: act(t, mid, "Cause", a))
    turn(t, mid, LEFT)
    resolve(lambda a: act(t, mid, "Prepare", a, target_id=RIGHT))
    e = fresh(c, mid)
    assert len(rewrites(e)) == 1
    assert [r for r in e.rolls if r.reason.startswith("CHECK:") and r.actor_id == LEFT][-1].modifier == 2


DAO = {"items": [{"item_id": "tianxia.mortal.weapon.dao", "name": "Dao (Saber)", "quantity": 1}]}


def sash_match(tmp_path, *, owns=True, ai=False, flying=False):
    def bundle(b):
        if b["actor_id"] == LEFT:
            if flying:
                b["actor_template"].update(fly_speed_ft=50, hover=True, climb_speed_ft=50,
                                           speed_ft=50, strength_score=24)
            old = "action:test.worker1." + LEFT
            for a in b["action_catalog"]:
                if a["source_definition_id"] == old:
                    a["source_definition_id"] = plug.PURSUIT
            b["actor_template"]["action_ids"] = [plug.PURSUIT if a == old else a for a in b["actor_template"]["action_ids"]]
    def arena(document):
        if flying:
            from combat.tabletop import normalize_map, to_battlefield
            from tests.test_walkable_roofs import roof_document
            document.update(to_battlefield(normalize_map(roof_document())))
    return fight(tmp_path, [plug.PURSUIT], sheet_edit=sheet(plug.SASH, owns), bundle_edit=bundle, arena_edit=arena,
        left_kit=DAO, prepare=[{"type": "movement", "distance_ft": "half_speed", "ins7d_pursuit_step": 1}], prepare_target="HOSTILE_ENTITY",
        reaction_ask=not ai, positions={LEFT: {"x": 1 if flying else 2, "y": 0 if flying else 2}, RIGHT: {"x": 8, "y": 0 if flying else 2}})


@pytest.mark.parametrize("ai", [False, True])
def test_pursuit_extends_half_speed_by_five_with_all_destinations(tmp_path, ai):
    c, t, mid = sash_match(tmp_path, ai=ai)
    before = fresh(c, mid)
    half = before._effective_speed(before.state.actors[LEFT]) // 2
    _, prompts = resolve(action_sender(c, t, mid, "Prepare", ai=ai, target_id=RIGHT))
    e = fresh(c, mid)
    assert e.state.actors[LEFT].position.x == 2 + (half + 5) // 5
    assert e.state.actors[LEFT].movement_remaining_ft == before.state.actors[LEFT].movement_remaining_ft
    rows = [r for r in e.typed_reaction_rows[LEFT] if r.get("feature_id") == plug.PURSUIT]
    assert rows and sum(bool(x.get("ins7d_pursuit_step")) for x in rows[0]["effects"]) == 1
    if not ai:
        q = next(p for p in prompts if p["context"]["reaction_source_id"] == plug.CHOICE + "sash")
        assert len(q["choice"]["options"]) > 10
    else:
        assert not prompts


def test_pursuit_nonowner_does_not_gain_step(tmp_path):
    c, t, mid = sash_match(tmp_path, owns=False)
    _, prompts = resolve(lambda a: act(t, mid, "Prepare", a, target_id=RIGHT))
    assert not prompts and fresh(c, mid).state.actors[LEFT].position.x == 2


@pytest.mark.parametrize("mode", ["jump", "fly", "climb"])
def test_pursuit_keeps_native_routes_sharing_an_endpoint(tmp_path, monkeypatch, mode):
    from combat.ext.granted_movement import choices
    from combat.gate2_runtime_models import Position
    c, t, mid = sash_match(tmp_path, flying=True)
    engine = fresh(c, mid)
    owner = engine.state.actors[LEFT]
    endpoint = Position(x=4, y=2, z=2)
    paths = [p for p in choices(engine, owner, engine._effective_speed(owner) // 2 + 5)
             if p.destination == endpoint]
    by_mode = {p.metadata.get("movement_mode", "walk"): p for p in paths}
    assert {"jump", "fly", "climb"} <= by_mode.keys()
    original = plug.ask
    observed = []
    def capture(engine, intent, checkpoint, chooser, choice_id, options, **kwargs):
        if choice_id == plug.CHOICE + "sash":
            same_endpoint = [p for p in choices(engine, chooser, engine._effective_speed(chooser) // 2 + 5)
                             if p.destination == endpoint]
            assert {p.candidate_id for p in same_endpoint} <= set(options)
            observed.append({p.metadata.get("movement_mode", "walk") for p in same_endpoint})
        return original(engine, intent, checkpoint, chooser, choice_id, options, **kwargs)
    monkeypatch.setattr(plug, "ask", capture)
    answers, prompts = [], []
    for _ in range(12):
        result = act(t, mid, "Prepare", answers, target_id=RIGHT)
        if result["status"] == "COMMITTED":
            break
        assert result["status"] == "REACTION_REQUIRED", result
        q = result["reaction"]
        prompts.append(q)
        opts = (q.get("choice") or {}).get("options", [])
        if q["context"]["reaction_source_id"] == plug.CHOICE + "sash":
            # IDs are bound to the checkpoint's decision, so answer the real
            # prompt rather than supplying a pre-action candidate identity.
            selected = next(o for o in opts if mode.capitalize() in str(o)
                            and "(4, 2)" in str(o) and "height 10 feet" in str(o))
            ids = [selected["id"]]
        else:
            ids = [o["id"] for o in opts][:1]
        answers.append({**q["context"], "selection": "USE", "option_ids": ids})
    else:
        raise AssertionError("too many pursuit choices")
    assert observed and all({"jump", "fly", "climb"} <= modes for modes in observed)
    assert fresh(c, mid).state.actors[LEFT].position == endpoint


@pytest.mark.parametrize("hit,away", [(True, True), (False, True), (True, False)])
def test_real_pursuit_reaction_requires_a_saber_hit_and_movement_away(tmp_path, hit, away):
    c, t, mid = fight(tmp_path, [plug.PURSUIT, "tianxia.talent.sabers.forward_cut"],
        sheet_edit=sheet(plug.SASH), left_kit=DAO, left_attack_bonus=100 if hit else -100,
        positions={LEFT: {"x": 2, "y": 2}, RIGHT: {"x": 3, "y": 2}})
    resolve(lambda a: act(t, mid, "Forward Cut", a, target_id=RIGHT))
    turn(t, mid, RIGHT)
    e = fresh(c, mid)
    assert bool(e.state.actors[LEFT].turn_flags.get("_round_ins7d_saber_hit:" + RIGHT)) == hit
    def send(answers):
        state = t.state(mid)
        engine = c._load_session(mid).engine
        dest = {"x": 6, "y": 2} if away else {"x": 3, "y": 3}
        candidate = next(x for x in engine.legal_candidates() if x.kind == "MOVE"
                         and x.destination and x.destination.model_dump(exclude_defaults=True) == dest)
        return t.act(mid, candidate.candidate_id, state["menu"]["decision_id"], state["menu"]["state_version"],
                     state["last_sequence"], answers)
    answers, prompts = [], []
    for _ in range(12):
        result = send(answers)
        if result["status"] != "REACTION_REQUIRED":
            assert result["status"] == "COMMITTED", result
            break
        prompt = result["reaction"]
        prompts.append(prompt)
        # Keep the one Reaction for Red Trail Pursuit. Bare reaction consent
        # accepts USE with no option ids; inventing an id is invalid transport.
        decline = prompt["context"]["reaction_source_id"] in {
            "system:combat.opportunity_attack", "reaction:typed.opportunity_attack", "reaction:core.opportunity_attack"}
        ids = [o["id"] for o in (prompt.get("choice") or {}).get("options", [])][:1]
        answers.append({**prompt["context"], "selection": "DECLINE" if decline else "USE",
                        "option_ids": [] if decline else ids})
    else:
        raise AssertionError("too many pursuit choices")
    after = fresh(c, mid)
    triggered = any(p["context"]["reaction_source_id"] == plug.CHOICE + "sash" for p in prompts)
    assert triggered == (hit and away)
    assert (after.state.actors[LEFT].position.x > 2) == (hit and away)
