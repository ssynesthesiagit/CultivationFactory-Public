"""Friendly-fire recipient rules through accepted table actions and reloads."""

import pytest
from types import SimpleNamespace

from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests.test_tabletop_hunt6 import table_fight, LEFT, ALLY, RIGHT


def test_legacy_selector_summary_keeps_duration_and_each_resource_cost():
    from combat.ext.rider_outcomes import _area_choice_consequences
    ctx = SimpleNamespace(typed={"effects": [{"type": "save", "ability": "dex",
        "on_fail": [{"type": "condition", "condition": "prone", "evidence": "Knocked Prone",
                     "duration": "until_start_of_next_turn"}],
        "on_success": [{"type": "half_damage"}]}]},
        action=SimpleNamespace(costs=[("resource:core.stamina", 3), ("resource:named.demon_spine", 2)]))
    text = _area_choice_consequences(ctx)
    assert "Knocked Prone (until the start of their next turn)" in text
    assert "half damage" in text and "3 Stamina and 2 Demon Spine" in text


def _commit_area_action(table, mid, group_name, destination, reactions=()):
    state = table.state(mid)
    menu = state["menu"]
    groups = [group for group in menu["actions"] if group_name in group["label"]]
    group = next((group for group in groups if group["label"] == group_name), groups[0])
    option = (group["options"][0] if destination is None else
              next((option for option in group["options"] if option.get("destination") == destination), None))
    if destination is None and any("choose a square" in str(o.get("label", "")).lower() for o in group["options"]):
        actor = table.combat._load_session(mid).engine.state.actors[menu["actor_id"]]
        destination = {"x": actor.position.x, "y": actor.position.y}
        option = None
    if option is None:
        # Current menus defer square choices. The table's exact legacy-square
        # transport still validates the full native candidate through act().
        engine = table.combat._load_session(mid).engine
        candidate = next(c for c in engine.legal_candidates()
                         if c.source_definition_id == group["source_definition_id"] and c.destination
                         and {"x": c.destination.x, "y": c.destination.y} == destination)
        option = {**candidate.model_dump(mode="json"), "label": candidate.display_name}
    result = table.act(mid, option["candidate_id"], menu["decision_id"], menu["state_version"],
                       state["last_sequence"], list(reactions))
    return result, option


def test_generic_creature_sphere_spares_ally_and_replays_after_reload(tmp_path):
    combat, table, mid = table_fight(tmp_path, ["STARS_TAL_FALLING_STAR"])
    result, option = _commit_area_action(table, mid, "Falling Star", {"x": 4, "y": 2})
    assert result["status"] == "COMMITTED", result

    loaded = CombatService(ROOT, combat.userdata_root)._load_session(mid)
    saves = [event.actor_id for event in loaded.engine.events
             if event.event_type == "SAVE_ROLLED" and "STARS_TAL_FALLING_STAR" in (event.source_definition_id or "")]
    assert set(saves) == {RIGHT}  # Generic creatures-in-area wording uses the enemies-only default.
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_hostile_area_prompts_only_for_enemy_and_spares_ally_after_reload(tmp_path):
    combat, table, mid = table_fight(tmp_path, ["TAL_SAND_BURIAL_OF_THE_NAMELESS_ARMY"])
    result, option = _commit_area_action(table, mid, "Burial of the Nameless Army", {"x": 4, "y": 2})
    assert result["status"] == "REACTION_REQUIRED", result
    prompt = result["reaction"]
    assert "Right" in prompt["moment"] and "Ally" not in prompt["moment"]
    state = table.state(mid)
    committed = table.act(mid, option["candidate_id"], state["menu"]["decision_id"], state["menu"]["state_version"],
                          state["last_sequence"], [{**prompt["context"], "selection": "USE", "option_ids": [RIGHT]}])
    assert committed["status"] == "COMMITTED", committed

    loaded = CombatService(ROOT, combat.userdata_root)._load_session(mid)
    saves = [event.actor_id for event in loaded.engine.events
             if event.event_type == "SAVE_ROLLED" and "SAND_BURIAL_OF_THE_NAMELESS_ARMY" in (event.source_definition_id or "")]
    assert saves == [RIGHT]  # Printed text: “Hostile creatures of your choice in the area make a Strength saving throw.”
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_creatures_you_choose_area_asks_and_shows_allies_before_reload(tmp_path):
    combat, table, mid = table_fight(tmp_path, ["TAL_DAEMONIC_CULTIVATION_WORLD_DEVOURING_MAW"])
    result, option = _commit_area_action(table, mid, "World-Devouring Maw", {"x": 4, "y": 2})
    answers = []
    prompts = []
    while result["status"] == "REACTION_REQUIRED" and len(answers) < 8:
        prompt = result["reaction"]
        if not prompts:
            assert any(option["id"] == ALLY for option in prompt["choice"]["options"])
            for consequence in ("12d10", "half damage", "pulled 30 feet", "pulled 10 feet", "Demon Mark for 1 minute", "12 Qi or 12 Devoured Essence",
                                "Qi means Cultivation Points, your technique resource", "Cultivation Level",
                                "Corruption tracks daemonic taint", "above 10 into Demonic Debt"):
                assert consequence in prompt["moment"]
            assert " CP" not in prompt["moment"], "explain the resource that pays the printed cost"
        prompts.append(prompt["moment"])
        # Round 23's Devour Essence rider also asks after a failed Daemonic save
        # or marked damage. Decline that optional rider; recipient choices still
        # select exactly the hostile creature and retain all area assertions.
        if "Devour Essence" in prompt["moment"]:
            answers.append({**prompt["context"], "selection": "DECLINE", "option_ids": []})
        else:
            answers.append({**prompt["context"], "selection": "USE", "option_ids": [RIGHT]})
        state = table.state(mid)
        result = table.act(mid, option["candidate_id"], state["menu"]["decision_id"],
                           state["menu"]["state_version"], state["last_sequence"], answers)
    assert result["status"] == "COMMITTED", result
    assert any("Allies in the area: Ally." in prompt for prompt in prompts)
    assert any("choose which creatures" in prompt for prompt in prompts)

    loaded = CombatService(ROOT, combat.userdata_root)._load_session(mid)
    saves = [event.actor_id for event in loaded.engine.events
             if event.event_type == "SAVE_ROLLED" and "WORLD_DEVOURING_MAW" in (event.source_definition_id or "")]
    assert saves == [RIGHT]  # Printed text: “Creatures you choose inside make Constitution saving throws.”
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("ability,label,destination,phrases", [
    ("TAL_FORCE_SHOCKWAVE", "Shockwave", None,
     ("Pressure Anchor you can perceive", "solid 5-foot square", "largest creature size", "Large at levels 1–4", "Huge at 5–9", "Gargantuan at 10–14", "any ordinary size at 15+", "Cultivation Levels 1–10")),
    ("tianxia.talent.disease.thousand_symptom_plague", "Thousand-Symptom Plague", None,
     ("Failed Save", "Successful Save", "disease markers", "Disease talents can use them for its stated effects", "start of your next turn",
      "12 Qi", "Qi means Cultivation Points, your technique resource")),
])
def test_actual_area_recipient_prompt_explains_game_terms(tmp_path, ability, label, destination, phrases):
    combat, table, mid = table_fight(tmp_path, [ability])
    result, _option = _commit_area_action(table, mid, label, destination)
    assert result["status"] == "REACTION_REQUIRED", result
    moment = result["reaction"]["moment"]
    for phrase in phrases:
        assert phrase in moment


def test_chosen_recipients_are_the_roster_seen_by_target_reactions(tmp_path, monkeypatch):
    from combat import typed_reactions

    combat, table, mid = table_fight(tmp_path, ["RADIANCE_TAL_BLINDING_FLASH"])
    seen = []
    original = typed_reactions.on_technique_start

    def observe(engine, actor, targets, typed, intent=None):
        seen.append([row.entity_id for row in targets])
        return original(engine, actor, targets, typed, intent)

    monkeypatch.setattr(typed_reactions, "on_technique_start", observe)
    result, option = _commit_area_action(table, mid, "10-Foot Emanation", None)
    assert result["status"] == "REACTION_REQUIRED", result
    prompt = result["reaction"]
    assert any(row["id"] == ALLY for row in prompt["choice"]["options"])
    answers = [{**prompt["context"], "selection": "USE", "option_ids": [ALLY]}]
    for _ in range(12):
        state = table.state(mid)
        result = table.act(mid, option["candidate_id"], state["menu"]["decision_id"], state["menu"]["state_version"],
                           state["last_sequence"], answers)
        if result["status"] == "COMMITTED":
            break
        assert result["status"] == "REACTION_REQUIRED", result
        answers.append({**result["reaction"]["context"], "selection": "DECLINE"})
    assert result["status"] == "COMMITTED", result
    assert [ALLY] in seen and all(RIGHT not in roster for roster in seen)

    loaded = CombatService(ROOT, combat.userdata_root)._load_session(mid)
    saves = [event.actor_id for event in loaded.engine.events
             if event.event_type == "SAVE_ROLLED" and "BLINDING_FLASH" in (event.source_definition_id or "")]
    assert saves == [ALLY]
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_automatic_chosen_area_uses_hostile_subset(tmp_path, monkeypatch):
    from combat import typed_executor
    from combat.ext import needle, rider_outcomes

    combat, table, mid = table_fight(tmp_path, ["TAL_DAEMONIC_CULTIVATION_WORLD_DEVOURING_MAW"])
    engine = combat._load_session(mid).engine
    actor = engine.state.actors[LEFT]
    action = next(row for row in engine.action_catalog.values()
                  if row.owner_id == LEFT and "TAL_DAEMONIC_CULTIVATION_WORLD_DEVOURING_MAW" in row.source_definition_id
                  and row.parameters.get("typed", {}).get("area"))
    typed = {**action.parameters["typed"], "_area_centre": [4, 2]}
    area_targets = typed_executor._area_targets(engine, actor, actor.position.__class__(x=4, y=2), typed["area"])
    engine.typed_control_modes = {LEFT: "LOCAL_AUTO"}
    ctx = typed_executor.Context(engine, actor, action, None, typed, area_targets, None, {})
    captured = {}

    def automatic_choice(*args, **kwargs):
        captured.update(kwargs)
        captured["options"] = args[5]
        return kwargs["preferred"]

    monkeypatch.setattr(needle, "ask", automatic_choice)
    rider_outcomes.choose_area_recipients(ctx, {})
    assert captured["options"] == [RIGHT]
    assert [row.entity_id for row in ctx.targets] == [RIGHT]


def test_chosen_area_can_select_nobody_and_commits_no_saves(tmp_path):
    combat, table, mid = table_fight(tmp_path, ["TAL_DAEMONIC_CULTIVATION_WORLD_DEVOURING_MAW"])
    result, option = _commit_area_action(table, mid, "World-Devouring Maw", {"x": 4, "y": 2})
    assert result["status"] == "REACTION_REQUIRED", result
    first = result["reaction"]
    answers = [{**first["context"], "selection": "USE", "option_ids": []}]
    for _ in range(12):
        state = table.state(mid)
        result = table.act(mid, option["candidate_id"], state["menu"]["decision_id"],
                           state["menu"]["state_version"], state["last_sequence"], answers)
        if result["status"] == "COMMITTED":
            break
        assert result["status"] == "REACTION_REQUIRED", result
        answers.append({**result["reaction"]["context"], "selection": "DECLINE"})
    assert result["status"] == "COMMITTED", result
    loaded = CombatService(ROOT, combat.userdata_root)._load_session(mid)
    assert not [event for event in loaded.engine.events
                if event.event_type == "SAVE_ROLLED" and "WORLD_DEVOURING_MAW" in (event.source_definition_id or "")]
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("ability,label,destination,expected", [
    ("tianxia.subpath.qi.dust_cultivator.feature.sandstorm_field", "Sandstorm Field", {"x": 4, "y": 2}, {RIGHT}),
    # Generic "Creatures inside" wording harms enemies only, even when its
    # 10-foot-wide beam geometrically covers the user and Ally.
    ("RADIANCE_TAL_HEAVEN_OPENING_JUDGMENT", "Heaven-Opening Judgment", {"x": 3, "y": 7}, {RIGHT}),
    ("tianxia.subpath.qi.iron_cloth_cultivator.feature.silken_prison", "Silken Prison", {"x": 4, "y": 4}, {LEFT, ALLY, RIGHT}),
    ("TAL_BRUTE_EARTHQUAKE_STOMP", "Earthquake Stomp", None, {ALLY, RIGHT}),
    ("tianxia.subpath.body.black_thorn_demon_body.feature.impaling_garden", "Impaling Garden", None, {RIGHT}),
])
def test_effect_recipient_scope_commits_reloads_and_replays(tmp_path, monkeypatch, ability, label, destination, expected):
    # Owner 2026-09-27: round radii use cell centres. Keep the ally beside
    # Silken Prison's aim, rather than diagonally beyond its five-foot radius.
    starts = {'team1': [[3, 4], [4, 3]], 'team2': [[4, 4]]} if ability.endswith('silken_prison') else None
    combat, table, mid = table_fight(tmp_path, [ability], cl=20, ally_talents=[],
                                   starts=starts,
                                   primary="Stamina" if ability.endswith("impaling_garden") else "Qi")
    if ability.endswith("impaling_garden"):
        from tests.test_tabletop_hunt6 import on_hold, HOLD
        from tests.test_lock2_persistence import act
        def supply_costs(engine):
            actor = engine.state.actors[LEFT]
            engine._gain_resource(actor, "resource:named.demon_spine", 2, "test:fixture")
        on_hold(monkeypatch, supply_costs)
        assert act(table, mid, HOLD)["status"] == "COMMITTED"
    result, option = _commit_area_action(table, mid, label, destination)
    answers = []
    for _ in range(16):
        if result["status"] == "COMMITTED":
            break
        assert result["status"] == "REACTION_REQUIRED", result
        answers.append({**result["reaction"]["context"], "selection": "DECLINE"})
        state = table.state(mid)
        result = table.act(mid, option["candidate_id"], state["menu"]["decision_id"], state["menu"]["state_version"], state["last_sequence"], answers)
    assert result["status"] == "COMMITTED", result
    loaded = CombatService(ROOT, combat.userdata_root)._load_session(mid)
    saves = {event.actor_id for event in loaded.engine.events if event.event_type == "SAVE_ROLLED" and ability in event.source_definition_id}
    assert saves == expected
    if ability.endswith("sandstorm_field"):
        assert loaded.engine.state.actors[ALLY].current_hp == loaded.engine.state.actors[ALLY].maximum_hp
        assert any(event.event_type == "DAMAGE_COMMITTED" and event.target_ids == (RIGHT,) and ability in event.source_definition_id for event in loaded.engine.events)
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_dawn_wave_cleanses_ally_without_hostile_save_or_healing_block(tmp_path, monkeypatch):
    from tests.test_tabletop_hunt6 import on_hold, HOLD
    from tests.test_lock2_persistence import act

    ability = "RADIANCE_TAL_DAWN_CLEANSING_WAVE"
    combat, table, mid = table_fight(tmp_path, [ability], ally_talents=[],
                                   starts={"team1": [[3, 4], [4, 5]], "team2": [[4, 4]]})
    def poison(engine):
        engine._apply_condition(engine.state.actors[ALLY], "condition:core.poisoned", "test:poison", RIGHT,
                                expires_on="UNTIL_REMOVED", data={"origin_save": {"ability": "CON", "dc": 1}})
    on_hold(monkeypatch, poison)
    assert act(table, mid, HOLD)["status"] == "COMMITTED"
    result, option = _commit_area_action(table, mid, "Dawn-Cleansing Wave", {"x": 5, "y": 5})
    answers = []
    for _ in range(16):
        if result["status"] == "COMMITTED":
            break
        assert result["status"] == "REACTION_REQUIRED", result
        prompt = result["reaction"]
        choices = prompt.get("choice") or {}
        selected = choices.get("preferred", [])[:1] or [row["id"] for row in choices.get("options", [])[:1]]
        answers.append({**prompt["context"], "selection": "USE", "option_ids": selected})
        state = table.state(mid)
        result = table.act(mid, option["candidate_id"], state["menu"]["decision_id"], state["menu"]["state_version"], state["last_sequence"], answers)
    assert result["status"] == "COMMITTED", result
    loaded = CombatService(ROOT, combat.userdata_root)._load_session(mid)
    ally = loaded.engine.state.actors[ALLY]
    assert not any(condition.condition_id.endswith(".poisoned") for condition in ally.conditions.values())
    saves = [event for event in loaded.engine.events if event.event_type == "SAVE_ROLLED" and ability in event.source_definition_id]
    # The ally's optional repeat-save is distinct from the hostile wave save.
    assert [event.payload["dc"] for event in saves if event.actor_id == ALLY] == [1]
    assert any(event.actor_id == RIGHT and event.payload["dc"] > 1 for event in saves)
    assert not any(event.event_type == "DAMAGE_COMMITTED" and event.target_ids == (ALLY,) and ability in event.source_definition_id for event in loaded.engine.events)
    assert not any(modifier.target_field == "healing_reduction" for modifier in ally.modifiers.values())
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("ask,automatic", [(False, True), (True, False), (True, True)])
def test_chosen_area_real_ai_turn_and_ask_me_commit_reload_replay(tmp_path, ask, automatic):
    from combat.gate4_adapters import ManualControllerAdapter

    ability = "TAL_DAEMONIC_CULTIVATION_WORLD_DEVOURING_MAW"
    combat, table, mid = table_fight(tmp_path, [ability], ask=ask, ally_talents=[])
    state = table.state(mid)
    group = next(group for group in state["menu"]["actions"] if "World-Devouring Maw" in group["label"])
    option = group["options"][0]
    real = combat.controller
    class AreaController:
        def choose_primary_action(self, context):
            return ManualControllerAdapter(lambda _context: (option["candidate_id"], ())).choose_primary_action(context)
        def __getattr__(self, name):
            return getattr(real, name)
    combat.controller = AreaController()
    if automatic:
        combat.set_controller_mode(mid, actor_id=LEFT, controller_mode="LOCAL_AUTO")
    def send(answers=()):
        if automatic:
            return table.auto_step(mid, 0, list(answers))
        current = table.state(mid)
        return table.act(mid, option["candidate_id"], current["menu"]["decision_id"], current["menu"]["state_version"], current["last_sequence"], list(answers))
    result = send()
    answers = []
    if not automatic and result["status"] == "REACTION_REQUIRED" and result["reaction"]["context"]["reaction_source_id"] == "choice:placement_menu.square":
        prompt = result["reaction"]
        answers.append({**prompt["context"], "selection": "USE", "option_ids": ["cell:4,2,0"]})
        result = send(answers)
    if not automatic:
        assert result["status"] == "REACTION_REQUIRED", result
        prompt = result["reaction"]
        assert any(row["id"] == ALLY for row in prompt["choice"]["options"])
        assert "World-Devouring Maw" in prompt["moment"] and "Ally" in prompt["moment"]
        answers.append({**prompt["context"], "selection": "USE", "option_ids": [ALLY]})
    for _ in range(16):
        if result["status"] == "COMMITTED":
            break
        if automatic:
            pytest.fail(str(result))
        result = send(answers)
        if result["status"] == "REACTION_REQUIRED":
            answers.append({**result["reaction"]["context"], "selection": "DECLINE"})
    assert result["status"] == "COMMITTED", result
    loaded = CombatService(ROOT, combat.userdata_root)._load_session(mid)
    saves = [event.actor_id for event in loaded.engine.events if event.event_type == "SAVE_ROLLED" and ability in event.source_definition_id]
    assert saves == ([RIGHT] if automatic else [ALLY])
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("phrase,expected", [
    ("Hostile creatures in the area make Constitution saving throws.", {RIGHT}),
    ("Creatures in the area make Constitution saving throws.", {RIGHT}),
    ("Each creature in the area makes a Constitution saving throw.", {LEFT, ALLY, RIGHT}),
])
@pytest.mark.parametrize("shape", ["sphere", "cone", "line"])
def test_unscoped_save_reads_its_own_printed_recipients(tmp_path, phrase, expected, shape):
    from combat import typed_executor as te

    combat, _, mid = table_fight(tmp_path, ["RADIANCE_TAL_DAWN_CLEANSING_WAVE"])
    engine = combat._load_session(mid).engine
    actor = engine.state.actors[LEFT]
    action = next(action for action in engine.action_catalog.values()
                  if action.owner_id == LEFT and "DAWN_CLEANSING_WAVE" in action.source_definition_id)
    # A legacy typed save may lack applies_to. Generic wording defaults to
    # enemies; only inclusive wording admits allies. Emitted shapes never
    # admit their user, even if the mixed action supplies its full roster.
    typed = {**action.parameters["typed"],
             "area": {**action.parameters["typed"]["area"], "shape": shape}}
    ctx = te.Context(engine, actor, action, None, typed,
                     list(engine.state.actors.values()), None, {})
    te.block_save(ctx, {"type": "save", "ability": "con", "recipient_text": phrase,
                        "on_fail": [], "on_success": []})
    assert {event.actor_id for event in engine.events if event.event_type == "SAVE_ROLLED"} == (
        expected - {LEFT} if shape in {"cone", "line"} else expected)
