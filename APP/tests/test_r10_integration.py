"""R10 review regressions across real table preview/commit/disk reload.

Synthetic triggers run inside an accepted Hold position action (Hunt6's fixture
seam), exercising the production rider, choice transport and persistence. No
runtime patch is shipped in combat code. Separate real turn transitions exercise
expiry and the accepted END_TURN answer transport.
"""
from types import SimpleNamespace
import json
import zipfile

import pytest

from combat import typed_executor as te
from combat.ext import disease, force, music, monkey, poison, radiance, stacking_marks as marks
from combat.gate4_adapters import ManualControllerAdapter
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, script, sheet
from tests.test_lock2_persistence import act
from tests.test_tabletop_hunt6 import table_fight, on_hold, LEFT, ALLY, RIGHT, HOLD, PROJECTS

D = "tianxia.talent.disease."
R = "tianxia.talent.radiance."
M = "tianxia.talent.music."
P = "tianxia.talent.poison."
CASES = {
    "expose": (["RADIANCE_BASE_STRIKE", R + "expose_false_form"], "radiance_expose", "Expose False Form"),
    "crown": (["RADIANCE_BASE_STRIKE", R + "crown_of_the_unblinking_sun"], "radiance_crown", "Crown of the Unblinking Sun"),
    "breath": (["DISEASE_BASE_SOW_THE_FEVER_SEED", D + "infection_of_the_cultivation_breath"], "disease_breath", "Infection of the Cultivation Breath"),
    "spreading": (["DISEASE_BASE_SOW_THE_FEVER_SEED", D + "spreading_infection"], "disease_spreading", "Spreading Infection"),
    "store": ([force.COUNTER, force.RESERVOIR], "force_store", "Kinetic Reservoir"),
    "release": ([force.IMPACT, force.RESERVOIR], "force_release_target", "Kinetic Reservoir"),
    "hymn": ([M + "healing_hymn"], "music_healing_hymn", "Healing Hymn"),
    "poison": ([P + "venom_sovereign_incarnation", P + "virulent_presence"], poison.MENU, "Virulent Presence (Poison)"),
    "disease": ([D + "plague_sovereign_incarnation"], disease.VIRULENT_MENU, "Virulent Presence (Disease)"),
    "uprising": ([monkey.UPRISING], monkey.UPRISING_MENU, "Thousand-Monkey Uprising"),
}


def action_of(engine, owner, feature):
    matches = [a for a in engine.action_catalog.values() if a.owner_id == owner.entity_id and feature in a.source_definition_id]
    return matches[0] if matches else next(a for a in engine.action_catalog.values() if a.owner_id == owner.entity_id)


def fight(tmp_path, talents, *, case=None):
    if case != "crown":
        return table_fight(tmp_path, talents, cl=20, ask=True, ally_talents=[])
    for name in ("left", "ally", "right"):
        document = sheet(talents if name == "left" else [], cl=20)
        document["identity"]["display_name"] = name.title()
        folder = tmp_path / "portable_characters" / PROJECTS[name]
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(document))
    from combat.tabletop import ButtonStore
    ButtonStore(tmp_path / "tabletop_buttons").save_reactions(PROJECTS["left"], {"mode": "ask"}, {"opportunity_attack"})
    combat = CombatService(ROOT, tmp_path)
    combat.tabletop_maps.save({"display_name": "R10 crown yard", "width_squares": 12, "height_squares": 8,
                              "walls": [], "starts": {"team1": [[3, 4]], "team2": [[4, 4], [4, 5]]}})
    mid = combat.create_factory_match(project_ids=[PROJECTS["left"]], opponent_actor_ids=[RIGHT, ALLY],
                                     control_modes={a: "MANUAL" for a in (LEFT, ALLY, RIGHT)},
                                     arena_id="battlefield:map.r10-crown-yard", match_seed="R10-CROWN")["match_id"]
    table = TabletopService(combat, tmp_path)
    while table.state(mid)["menu"]["actor_id"] != LEFT:
        assert act(table, mid, "end")["status"] == "COMMITTED"
    return combat, table, mid


def context(engine, owner, target, feature):
    action = action_of(engine, owner, feature)
    return te.Context(engine, owner, action, engine._active_intent, dict(action.parameters.get("typed") or {}), [target], target, {})


def trigger(case, engine):
    owner, target, ally = (engine.state.actors[a] for a in (LEFT, RIGHT, ALLY))
    script(engine, [1] * 40)
    if case in ("expose", "crown"):
        if case == "expose":
            engine._apply_condition(target, "condition:typed.invisible", "test:veil", RIGHT, expires_on="UNTIL_REMOVED")
        else:
            engine._apply_condition(owner, "condition:typed.crown", radiance.CROWN, LEFT, expires_on="UNTIL_REMOVED")
        te.block_mark(context(engine, owner, target, "RADIANCE_BASE_STRIKE"), {"mark": "Dawnmark", "applies_to": "target"})
    elif case in ("breath", "spreading"):
        marks.add(engine, owner, target, "Contagion Token", 2, "test:tokens")
        if case == "breath":
            engine._spend_resource(target, "resource:core.qi", 1, HOLD)
        else:
            disease._spreading(engine, target)
    elif case == "store":
        engine._append_event("REACTION_RESOLVED", force.COUNTER, actor_id=LEFT, target_ids=(RIGHT,),
                             payload={"checkpoint": "DAMAGE_APPLICATION", "reduction": 7, "protects": LEFT})
    elif case == "release":
        ctx = context(engine, owner, target, force.IMPACT)
        engine._apply_condition(owner, force.STORED, force.RESERVOIR, LEFT, expires_on="UNTIL_REMOVED", data={"amount": 7})
        te._deal(ctx, target, 1, "FORCE")
        force.reservoir_release(ctx)
    elif case == "hymn":
        hymn = action_of(engine, owner, music.HYMN)
        engine._start_concentration(owner, hymn.source_definition_id)
        te._deal(context(engine, owner, ally, music.HYMN), ally, 10, "FORCE")
        music.songs_heal(engine, owner)
    elif case == "poison":
        engine._apply_condition(owner, "condition:typed.venom_form", poison.SOVEREIGN, LEFT, expires_on="UNTIL_REMOVED")
        poison.virulent_presence(engine, target)
    elif case == "disease":
        engine._apply_condition(owner, "condition:typed.plague_form", disease.SOVEREIGN, LEFT, expires_on="UNTIL_REMOVED")
        disease._virulent_presence(engine, target)
    elif case == "uprising":
        monkey._uprising_test(engine, target, owner, "attacks")


def sender(combat, table, mid, active, auto):
    state = table.state(mid)
    menu = state["menu"]
    cid = next(g["options"][0]["candidate_id"] for g in menu["actions"] if g["source_definition_id"] == HOLD)
    if auto:
        combat.set_controller_mode(mid, actor_id=active, controller_mode="LOCAL_AUTO")
        real = combat.controller
        class HoldController:
            def choose_primary_action(self, context):
                return ManualControllerAdapter(lambda _: (cid, ())).choose_primary_action(context)
            def __getattr__(self, name):
                return getattr(real, name)
        combat.controller = HoldController()
    return lambda answers=(): table.auto_step(mid, 0, list(answers)) if auto else table.act(
        mid, cid, menu["decision_id"], menu["state_version"], state["last_sequence"], list(answers))


@pytest.mark.parametrize("case", CASES)
@pytest.mark.parametrize("other_turn,auto", [(False, False), (True, False), (True, True)])
@pytest.mark.parametrize("use", [False, True])
def test_owner_bound_riders_preview_answer_commit_reload(monkeypatch, tmp_path, case, other_turn, auto, use):
    talents, key, name = CASES[case]
    combat, table, mid = fight(tmp_path, talents, case=case)
    active = RIGHT if other_turn else LEFT
    while table.state(mid)["menu"]["actor_id"] != active:
        assert act(table, mid, "end")["status"] == "COMMITTED"
    on_hold(monkeypatch, lambda e: trigger(case, e))
    send = sender(combat, table, mid, active, auto)
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    result = send()
    assert result["status"] == "REACTION_REQUIRED"
    prompt = result["reaction"]
    assert prompt["context"]["reactor_id"] == LEFT
    assert prompt["context"]["reaction_source_id"] == "choice:needle." + key
    assert name in prompt["reaction"] and name in prompt["moment"]
    if case == "hymn":
        assert prompt["cost"] == "No additional resource or Reaction cost"
        assert "paid when" in prompt["table_note"]
    assert "Right" in prompt["moment"] or case in ("store", "hymn") and "Left" in prompt["moment"]
    assert send()["reaction"] == prompt
    assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
    mandatory = case in ("poison", "disease", "uprising")
    assert prompt["choice"]["allow_decline"] == (not mandatory)
    answers = []
    for _ in range(5):
        chosen = use or mandatory
        options = prompt["choice"]["options"]
        option = (prompt["choice"].get("preferred") or [options[0]["id"]])[0]
        if case == "release" and "amount" in prompt["context"]["reaction_source_id"]:
            option = "3"
        if case in ("spreading", "hymn"):
            option = ALLY
        answers.append({**prompt["context"], "selection": "USE" if chosen else "DECLINE", "option_ids": [option] if chosen else []})
        result = send(answers)
        if result["status"] == "COMMITTED":
            break
        prompt = result["reaction"]
    assert result["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    engine = loaded.engine
    owner, target, ally = (engine.state.actors[a] for a in (LEFT, RIGHT, ALLY))
    if case == "expose":
        assert bool(owner.turn_flags.get(f"_round_radiance_expose:{RIGHT}")) == use
    elif case == "crown":
        assert te.bears_mark(ally, LEFT, "Dawnmark") == use
    elif case == "breath":
        assert marks.count(engine, owner, target, "Contagion Token") == (1 if use else 2)
        assert owner.reaction_available == (not use)
    elif case == "spreading":
        assert marks.count(engine, owner, ally, "Contagion Token") == int(use)
        assert owner.reaction_available == (not use)
    elif case == "store":
        assert any(c.condition_id == force.STORED for c in owner.conditions.values()) == use
    elif case == "release":
        assert any(c.condition_id == force.STORED for c in owner.conditions.values()) == (not use)
        extra = [e for e in engine.events if e.event_type == "DAMAGE_COMMITTED" and e.source_definition_id == action_of(engine, owner, force.IMPACT).source_definition_id]
        assert len(extra) == (2 if use else 1)
        if use:
            assert extra[-1].payload["hp_damage"] == 3
    elif case == "hymn":
        assert bool(owner.turn_flags.get(f"_round_music_hymn:{ALLY}")) == use
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("case,feature,key,optional", [
    ("containment", "DISEASE_BASE_SOW_THE_FEVER_SEED", "disease_containment", True),
    ("surge", D + "epidemic_surge", "disease_surge", True),
    ("audience", M + "war_song", "music_audience", True),
    ("bait", "TAL_MONKEY_STYLE_MISCHIEVOUS_FEINT", "monkey_bait", False),
    ("origin", force.IMPACT, "force_origin", False),
    ("anchor_limit", force.IMPACT, "force_anchor_limit", False),
])
@pytest.mark.parametrize("other_turn,auto", [(False, False), (True, False), (True, True)])
@pytest.mark.parametrize("use", [False, True])
def test_additional_rider_recipient_and_origin_choices_commit_reload(monkeypatch, tmp_path, case, feature, key, optional, other_turn, auto, use):
    from combat.gate2_runtime_models import Position
    combat, table, mid = fight(tmp_path, [feature])
    active = RIGHT if other_turn else LEFT
    while table.state(mid)["menu"]["actor_id"] != active:
        assert act(table, mid, "end")["status"] == "COMMITTED"
    def trigger_extra(engine):
        owner, target = engine.state.actors[LEFT], engine.state.actors[RIGHT]
        ctx = context(engine, owner, target, feature)
        if case == "containment":
            disease.add_tokens(engine, target, owner, 1, "test:infection")
            engine._apply_condition(owner, "condition:typed.test_containment", ctx.source, LEFT, expires_on="UNTIL_REMOVED",
                                    data={"rule": {"disease_containment": True}})
            disease._containment_cleanse(engine, owner)
        elif case == "surge":
            disease.add_tokens(engine, owner, target, 1, "test:infection")
            disease.surge(ctx, {"effects": []})
        elif case == "audience":
            music.music_mark(ctx, {"mark": "music_war_song", "range_ft": 30, "count": "pb", "rule": {}})
        elif case == "bait":
            script(engine, [1] * 20)
            monkey.bait(ctx, {})
        elif case == "origin":
            force.place_anchor(engine, owner, Position(x=2, y=4), ctx.source)
            force.force_origin(ctx, {"feature": force.IMPACT})
        else:
            for x in range(int(owner.proficiency_bonus)):
                force.place_anchor(engine, owner, Position(x=x, y=0), ctx.source)
            force.place_anchor(engine, owner, Position(x=7, y=0), ctx.source)
    on_hold(monkeypatch, trigger_extra)
    send = sender(combat, table, mid, active, auto)
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    result = send()
    assert result["status"] == "REACTION_REQUIRED"
    prompt = result["reaction"]
    assert prompt["context"]["reactor_id"] == LEFT
    assert prompt["context"]["reaction_source_id"] == "choice:needle." + key
    assert prompt["choice"]["allow_decline"] == optional
    assert "Left" in prompt["moment"] or "Right" in prompt["moment"]
    assert send()["reaction"] == prompt
    assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
    chosen = use or not optional
    answer = {**prompt["context"], "selection": "USE" if chosen else "DECLINE",
              "option_ids": [prompt["choice"]["options"][0]["id"]] if chosen else []}
    assert send([answer])["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    owner, target = loaded.engine.state.actors[LEFT], loaded.engine.state.actors[RIGHT]
    if case == "containment":
        assert disease.tokens(loaded.engine, target, owner) == (not use)
    elif case == "surge":
        assert disease.tokens(loaded.engine, owner, target) == (not use)
    elif case == "audience":
        assert any(c.condition_id.endswith("music_war_song") for a in loaded.engine.state.actors.values() for c in a.conditions.values()) == use
    elif case == "anchor_limit":
        assert len(force.external(loaded.engine, owner)) == owner.proficiency_bonus
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("case", CASES)
def test_ai_owned_rider_choices_are_automatic(monkeypatch, tmp_path, case):
    combat, table, mid = fight(tmp_path, CASES[case][0], case=case)
    on_hold(monkeypatch, lambda e: trigger(case, e))
    assert sender(combat, table, mid, LEFT, True)()["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_cleansed_counted_marks_restart_and_partial_spending_preserves_deadline(monkeypatch, tmp_path):
    combat, table, mid = table_fight(tmp_path, ["POISON_BASE_DELIVER_THE_DOSE"], ally_talents=[])
    def place(engine):
        owner, target = engine.state.actors[LEFT], engine.state.actors[RIGHT]
        ctx = context(engine, owner, target, "POISON_BASE_DELIVER_THE_DOSE")
        row = {"mark": "Dose Mark", "applies_to": "target", "duration": {"kind": "minutes", "amount": 1}}
        for _ in range(3):
            te.block_mark(ctx, row)
        assert marks.count(engine, owner, target, "Dose Mark") == 3
        engine._remove_condition(target, te.mark_condition_id("Dose Mark", LEFT), "test:cleanse")
        te.block_mark(ctx, row)
        assert marks.count(engine, owner, target, "Dose Mark") == 1
        for _ in range(2):
            te.block_mark(ctx, row)
        mark = next(c for c in target.conditions.values() if c.condition_id == te.mark_condition_id("Dose Mark", LEFT))
        deadline = mark.expires_on
        sequence = engine.state.event_sequence
        te.block_spend_mark(ctx, {"mark": "Dose Mark", "applies_to": "target", "count": 4})
        assert marks.count(engine, owner, target, "Dose Mark") == 3
        assert engine.state.event_sequence == sequence  # no spend notification when the cost cannot be paid
        te.block_spend_mark(ctx, {"mark": "Dose Mark", "applies_to": "target", "count": 1})
        remaining = next(c for c in target.conditions.values() if c.condition_id == mark.condition_id)
        assert remaining.expires_on == deadline and deadline.startswith("START_OF_SLOT_AT:")
        assert marks.count(engine, owner, target, "Dose Mark") == 2
    on_hold(monkeypatch, place)
    assert act(table, mid, HOLD)["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    engine = loaded.engine
    assert marks.count(engine, engine.state.actors[LEFT], engine.state.actors[RIGHT], "Dose Mark") == 2
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("modifier", [False, True])
@pytest.mark.parametrize("lifetime", ["turn", "concentration", "live"])
def test_suppression_keeps_absolute_lifetime_original_owner_and_other_instances(monkeypatch, tmp_path, modifier, lifetime):
    from combat.ext import destruction_blast
    from combat.ext.effect_durations import token
    feature = "tianxia.talent.destruction.unmaking_pressure" if modifier else radiance.GENTLE
    combat, table, mid = table_fight(tmp_path, [feature], ally_talents=[])
    original = {}
    def suppress(engine):
        if engine.state.current_actor_id != LEFT:
            return
        owner, caster, holder = (engine.state.actors[a] for a in (LEFT, RIGHT, ALLY))
        source = "test:original-defense" if modifier else "test:original-fear"
        expiry = "CONCENTRATION_END" if lifetime == "concentration" else "START_OF_SOURCE_NEXT_TURN" if lifetime == "turn" else token("start", RIGHT, caster.turns_started + 5)
        if lifetime == "concentration":
            engine._start_concentration(caster, source)
        if modifier:
            engine._add_modifier(holder, source, "armor_class", "ADD", 3, "ALL", expires_on=expiry)
            row = next(m for m in holder.modifiers.values() if m.source_definition_id == source)
            row.source_actor_id = RIGHT
            original.update(id=row.modifier_id, expiry=expiry)
            destruction_blast.unmake_defense(context(engine, owner, holder, feature), {})
            assert not any(m.source_definition_id == source for m in holder.modifiers.values())
        else:
            engine._apply_condition(holder, "condition:typed.frightened", source, RIGHT, expires_on=expiry)
            engine._apply_condition(holder, "condition:typed.frightened", "test:other-caster", ALLY, expires_on="UNTIL_REMOVED")
            row = next(c for c in holder.conditions.values() if c.source_definition_id == source)
            original.update(id=row.instance_id, expiry=expiry)
            radiance.suppress(context(engine, owner, holder, feature), {"conditions": ["frightened"]})
            assert [c.source_definition_id for c in holder.conditions.values() if c.condition_id.endswith(".frightened")] == ["test:other-caster"]
    on_hold(monkeypatch, suppress)
    assert act(table, mid, HOLD)["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert any(c.condition_id in (radiance.SUPPRESSED, destruction_blast.SUPPRESSED) for c in loaded.engine.state.actors[ALLY].conditions.values())
    if lifetime == "concentration":
        def end(engine):
            if engine.state.current_actor_id == RIGHT:
                engine._end_concentration(engine.state.actors[RIGHT], "test:ended")
        on_hold(monkeypatch, end)
    assert act(table, mid, "end")["status"] == "COMMITTED"
    for _ in range(5):
        active = table.state(mid)["menu"]["actor_id"]
        if active == LEFT:
            break
        if lifetime == "concentration" and active == RIGHT:
            assert act(table, mid, HOLD)["status"] == "COMMITTED"
        assert act(table, mid, "end")["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    holder = loaded.engine.state.actors[ALLY]
    rows = holder.modifiers if modifier else holder.conditions
    assert (original["id"] in rows) == (lifetime == "live")
    if lifetime == "live":
        assert rows[original["id"]].source_actor_id == RIGHT
        assert rows[original["id"]].expires_on == original["expiry"]
    if not modifier:
        assert any(c.source_definition_id == "test:other-caster" for c in holder.conditions.values())
    assert not any(c.condition_id in (radiance.SUPPRESSED, destruction_blast.SUPPRESSED) for c in holder.conditions.values())
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_one_opening_penalties_expire_at_source_next_turn_end_after_reload(monkeypatch, tmp_path):
    from combat.ext import needle_opening
    combat, table, mid = table_fight(tmp_path, [needle_opening.OPENING], cl=20, ally_talents=[])
    def apply(engine):
        owner, target = engine.state.actors[LEFT], engine.state.actors[RIGHT]
        ctx = context(engine, owner, target, needle_opening.OPENING)
        rows = [{k: v for k, v in row.items() if k not in ("menu", "option")}
                for row in needle_opening._consequences()[:4]]
        te.run_effects(ctx, rows)
    on_hold(monkeypatch, apply)
    assert act(table, mid, HOLD)["status"] == "COMMITTED"
    engine = CombatService(ROOT, tmp_path)._load_session(mid).engine
    target = engine.state.actors[RIGHT]
    assert engine._effective_speed(target) == 0
    assert any(c.condition_id.endswith("reaction_denied") for c in target.conditions.values())
    assert act(table, mid, "end")["status"] == "COMMITTED"
    for _ in range(5):
        if table.state(mid)["menu"]["actor_id"] == LEFT:
            break
        assert act(table, mid, "end")["status"] == "COMMITTED"
    engine = CombatService(ROOT, tmp_path)._load_session(mid).engine
    assert engine._effective_speed(engine.state.actors[RIGHT]) == 0  # still applies during next source turn
    assert act(table, mid, "end")["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    target = loaded.engine.state.actors[RIGHT]
    assert loaded.engine._effective_speed(target) > 0
    assert not any(c.condition_id.endswith("reaction_denied") for c in target.conditions.values())
    assert not any(m.target_field in ("attack_mode", "speed_ft", "suppress_resistance") for m in target.modifiers.values())
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("auto_turn", [False, True])
def test_traitorous_blade_bonus_attack_is_one_strike_with_multiattack_weapon(monkeypatch, tmp_path, auto_turn):
    from combat.ext import needle_bind
    from tests.test_carry import KIT
    combat, table, mid = table_fight(tmp_path, [needle_bind.TRAITOROUS], cl=20, kit={"starting_kit": KIT}, ask=True, ally_talents=[])
    while table.state(mid)["menu"]["actor_id"] != RIGHT:
        assert act(table, mid, "end")["status"] == "COMMITTED"
    def attack(engine):
        owner, target = engine.state.actors[LEFT], engine.state.actors[RIGHT]
        script(engine, [19] * 40)
        caught = next(a for a in engine.action_catalog.values() if a.owner_id == LEFT and (a.parameters or {}).get("requires_held_weapon")
                      and "#" not in a.source_definition_id)
        weapon = caught.parameters["requires_held_weapon"]
        row = next(e for e in caught.parameters["typed"]["effects"] if e.get("type") == "attack")
        row.update(count=4, count_by_cl=[[1, 20, 4]])
        engine._apply_condition(target, "condition:typed.disarmed", "test:catch", LEFT, expires_on="UNTIL_REMOVED",
                                data={"disables_action": weapon, "held_by": LEFT})
        needle_bind._traitorous_attack(engine, owner, target, weapon, engine._active_intent)
    on_hold(monkeypatch, attack)
    send = sender(combat, table, mid, RIGHT, auto_turn)
    prompt = send()["reaction"]
    assert prompt["context"]["reactor_id"] == LEFT
    assert "Traitorous Blade" in prompt["moment"] and "Right" in prompt["moment"]
    result = send([{**prompt["context"], "selection": "USE", "option_ids": ["attack"]}])
    assert result["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    attacks = [e for e in loaded.engine.events if e.event_type == "ATTACK_ROLLED" and e.actor_id == LEFT]
    assert len(attacks) == 1
    assert not loaded.engine.state.actors[LEFT].bonus_action_available
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("light,magical,superior,lifts", [
    (radiance.REVEALING, False, False, True), (radiance.REVEALING, True, False, False),
    (radiance.COURT, True, False, False), (radiance.WORLD, True, False, False),
    (radiance.FIRST_DAWN, True, False, True), (radiance.FIRST_DAWN, True, True, False),
    (radiance.HEAVENLY, True, False, True), (radiance.HEAVENLY, True, True, False),
])
def test_light_respects_actual_darkness_zone_scope(light, magical, superior, lifts):
    from combat import zones
    from tests import test_riders_lane10 as lane
    _, engine, owner, target = lane._dawn(light.removeprefix(R), cl=20)
    lane.SWF.cast(engine, action_of(engine, owner, light).display_name)
    # A real ZoneState on the map, not a bare hook call. Supernatural Darkness
    # is classified from its source; ordinary map darkness is explicitly typed.
    dark_ctx = context(engine, target, target, "missing")
    dark_ctx.typed = {"source": "DARK_BASE_DARKNESS" if magical else "test:ordinary-darkness", "numbers": {}}
    spec = {"name": "Darkness", "shape": "sphere", "size_ft": 5, "centered_on_self": True,
            "obscured": "heavy", "visual": {"darkness": True, "magical": magical, "legendary": superior},
            "duration": {"kind": "minutes", "amount": 1}}
    zone = zones.create(dark_ctx, spec)
    assert zone is not None and zone.active
    assert zones._blocks(engine, zone, owner, target) == (not lifts)


def test_deferred_vacuum_slice_cannot_bypass_blindness_or_bonus_ac():
    from combat.ext import needle_vacuum
    from tests import test_riders_lane10 as lane
    engine, owner = lane._vacuum([needle_vacuum.VACUUM_SLICE], {lane.N.FOE1: (5, 6), lane.N.FOE2: (7, 6)})
    target = engine.state.actors[lane.N.FOE1]
    engine._apply_condition(owner, "condition:typed.blinded", "test:blind", target.entity_id, expires_on="UNTIL_REMOVED")
    engine._add_modifier(target, "test:shield", "armor_class", "ADD", 20, "ALL_ATTACKS", expires_on="UNTIL_REMOVED")
    action = next(a for a in engine.action_catalog.values() if a.owner_id == owner.entity_id and ".weapon." in a.source_definition_id)
    before_hp, before_rolls = target.current_hp, len(engine.rolls)
    needle_vacuum.vacuum_slice(te.Context(engine, owner, action, None, action.parameters["typed"], [target], target, {}), {})
    assert target.current_hp == before_hp and len(engine.rolls) == before_rolls
    assert not [c for c in engine.legal_candidates() if "Vacuum Slice" in c.display_name]
    assert owner.bonus_action_available


@pytest.mark.parametrize("expired", [False, True])
def test_purging_breath_suppresses_without_curing_or_resurrecting_sickened(monkeypatch, tmp_path, expired):
    feature = D + "purging_breath"
    combat, table, mid = table_fight(tmp_path, [feature], ally_talents=[])
    original = {}
    def suppress(engine):
        owner, caster, holder = (engine.state.actors[a] for a in (LEFT, RIGHT, ALLY))
        engine._apply_condition(holder, "condition:typed.sickened", "test:illness", RIGHT,
                                expires_on="START_OF_SOURCE_NEXT_TURN" if expired else "UNTIL_REMOVED")
        row = next(c for c in holder.conditions.values() if c.source_definition_id == "test:illness")
        original["id"] = row.instance_id
        disease.purge(context(engine, owner, holder, feature), {"choice": "sickened"})
        assert original["id"] not in holder.conditions
    on_hold(monkeypatch, suppress)
    assert act(table, mid, HOLD)["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert any(c.condition_id.endswith("disease_sickened_suppressed") for c in loaded.engine.state.actors[ALLY].conditions.values())
    assert act(table, mid, "end")["status"] == "COMMITTED"
    for _ in range(5):
        if table.state(mid)["menu"]["actor_id"] == LEFT:
            break
        assert act(table, mid, "end")["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    holder = loaded.engine.state.actors[ALLY]
    assert (original["id"] in holder.conditions) == (not expired)
    if not expired:
        assert holder.conditions[original["id"]].source_actor_id == RIGHT
    assert not any(c.condition_id.endswith("disease_sickened_suppressed") for c in holder.conditions.values())
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_reservoir_does_not_release_from_a_previous_technique_hit(monkeypatch, tmp_path):
    combat, table, mid = table_fight(tmp_path, [force.IMPACT, force.RESERVOIR], ally_talents=[])
    def store_and_hit(engine):
        owner, target = engine.state.actors[LEFT], engine.state.actors[RIGHT]
        if any(c.condition_id == force.STORED for c in owner.conditions.values()):
            return
        engine._apply_condition(owner, force.STORED, force.RESERVOIR, LEFT, expires_on="UNTIL_REMOVED", data={"amount": 7})
        te._deal(context(engine, owner, target, force.IMPACT), target, 1, "FORCE")
    on_hold(monkeypatch, store_and_hit)
    assert act(table, mid, HOLD)["status"] == "COMMITTED"
    def no_hit(engine):
        force.reservoir_release(context(engine, engine.state.actors[LEFT], engine.state.actors[RIGHT], force.IMPACT))
    on_hold(monkeypatch, no_hit)
    assert act(table, mid, HOLD)["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert next(c for c in loaded.engine.state.actors[LEFT].conditions.values() if c.condition_id == force.STORED).data["amount"] == 7
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("case", ["spreading", "poison", "disease"])
def test_real_turn_start_choices_use_accepted_end_turn_answers(monkeypatch, tmp_path, case):
    talents, key, name = CASES[case]
    combat, table, mid = fight(tmp_path, talents)
    def prime(engine):
        owner, target = engine.state.actors[LEFT], engine.state.actors[RIGHT]
        if case == "spreading":
            disease.add_tokens(engine, owner, target, 1, "test:seed")
        else:
            form = "condition:typed.venom_form" if case == "poison" else "condition:typed.plague_form"
            feature = poison.SOVEREIGN if case == "poison" else disease.SOVEREIGN
            engine._apply_condition(owner, form, feature, LEFT, expires_on="UNTIL_REMOVED")
    on_hold(monkeypatch, prime)
    assert act(table, mid, HOLD)["status"] == "COMMITTED"
    for _ in range(3):
        state = table.state(mid)
        menu = state["menu"]
        before = combat._load_session(mid).engine.state.model_dump(mode="json")
        def send(answers=()):
            return table.act(mid, menu["end_turn"], menu["decision_id"], menu["state_version"], state["last_sequence"], list(answers))
        result = send()
        if result["status"] == "REACTION_REQUIRED":
            break
        assert result["status"] == "COMMITTED"
    assert result["status"] == "REACTION_REQUIRED"
    prompt = result["reaction"]
    assert prompt["context"]["reactor_id"] == LEFT
    assert prompt["context"]["reaction_source_id"] == "choice:needle." + key
    assert name in prompt["moment"] and "Right" in prompt["moment"] and "starts" in prompt["moment"]
    assert send()["reaction"] == prompt
    assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
    option = ALLY if case == "spreading" else prompt["choice"]["options"][0]["id"]
    answer = {**prompt["context"], "selection": "USE", "option_ids": [option]}
    assert send([answer])["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.current_actor_id == RIGHT
    if case == "spreading":
        assert disease.tokens(loaded.engine, loaded.engine.state.actors[LEFT], loaded.engine.state.actors[ALLY]) == 1
    assert loaded.engine._active_intent is None
    assert not getattr(loaded.engine, '_active_turn_advancing', False)
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_cover_denial_refresh_preserves_another_casters_instance(monkeypatch, tmp_path):
    from combat.ext import destruction_blast
    feature = "tianxia.talent.destruction.unmaking_pressure"
    combat, table, mid = table_fight(tmp_path, [feature], ally_talents=[])
    def deny(engine):
        owner, target = engine.state.actors[LEFT], engine.state.actors[RIGHT]
        engine._apply_condition(target, destruction_blast.NO_HALF_COVER, "test:other-caster", ALLY, expires_on="UNTIL_REMOVED")
        other = next(c for c in target.conditions.values() if c.source_definition_id == "test:other-caster")
        for _ in range(2):
            destruction_blast.no_half_cover(context(engine, owner, target, feature), {})
        assert other.instance_id in target.conditions
        assert len([c for c in target.conditions.values() if c.condition_id == destruction_blast.NO_HALF_COVER]) == 2
    on_hold(monkeypatch, deny)
    assert act(table, mid, HOLD)["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert any(c.source_definition_id == "test:other-caster" for c in loaded.engine.state.actors[RIGHT].conditions.values())
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("other_turn,auto", [(False, False), (True, False), (True, True)])
def test_opening_owner_chooses_three_consequences_at_hit_on_manual_and_ai_turns(monkeypatch, tmp_path, other_turn, auto):
    from combat.ext import needle_opening
    combat, table, mid = fight(tmp_path, [needle_opening.OPENING])
    active = RIGHT if other_turn else LEFT
    while table.state(mid)["menu"]["actor_id"] != active:
        assert act(table, mid, "end")["status"] == "COMMITTED"
    def hit(engine):
        needle_opening.choose_consequences(context(engine, engine.state.actors[LEFT], engine.state.actors[RIGHT], needle_opening.OPENING), {})
    on_hold(monkeypatch, hit)
    send = sender(combat, table, mid, active, auto)
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    result = send()
    assert result["status"] == "REACTION_REQUIRED"
    prompt = result["reaction"]
    assert prompt["context"]["reactor_id"] == LEFT
    assert "The One Opening Beneath Heaven" in prompt["moment"] and "hits Right" in prompt["moment"]
    assert prompt["choice"]["minimum"] == prompt["choice"]["maximum"] == 3
    assert not prompt["choice"]["allow_decline"]
    assert send()["reaction"] == prompt
    assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
    answer = {**prompt["context"], "selection": "USE", "option_ids": ["No Reactions", "Speed 0", "Disadvantage on attack rolls"]}
    assert send([answer])["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine._effective_speed(loaded.engine.state.actors[RIGHT]) == 0
    assert loaded.mechanical.replay()["status"] == "PASS"
