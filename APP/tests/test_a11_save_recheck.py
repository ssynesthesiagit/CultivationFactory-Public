"""Effective save totals reach events, riders and real table commit/reload."""
import pytest

from combat import typed_executor, ext
from combat.ext import calamity_eyes
from combat.ext.save_recheck import SEAL
from combat.gate4_adapters import ManualControllerAdapter
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, ME, ALLY, FOE, duel, give, script, force_save, events, rewrites, amount, use
from tests.test_tabletop_hunt6 import table_fight, LEFT, RIGHT
from tests.test_lock2_persistence import act

SACRAL = "tianxia.tradition.spirit.inner_soul_gate_ascetic.feature.sacral_soul_gate"
STAR_SOUL = "tianxia.talent.stars.star_soul_guidance"
KILLING = calamity_eyes.PREFIX + "read_the_killing_line"
STOMP = "tianxia.subpath.body.flesh_crucible.feature.world_shaking_stomp"
BINDING = "tianxia.talent.talismans.binding_talisman"
COUNTERFLOW = "tianxia.subpath.qi.devil_heart_second_furnace.feature.heart_devil_counterflow"


def save_on_hold(monkeypatch, callback):
    """Inject a synthetic save through the documented event hook, never an engine patch."""
    ext.effects()

    def dispatch(engine, event_type, kwargs):
        if event_type == "HOLD_POSITION_COMMITTED":
            callback(engine)

    monkeypatch.setitem(ext._HOOKS, "event", [*ext._HOOKS["event"], dispatch])
    monkeypatch.setitem(ext._NESTED_HOOKS, "event", {*ext._NESTED_HOOKS["event"], dispatch})


def test_counterflow_failed_rescue_has_no_backlash_after_table_commit_reload(tmp_path, monkeypatch):
    combat, table, mid = table_fight(tmp_path, [COUNTERFLOW], ally_talents=[])
    hp = combat._load_session(mid).engine.state.actors[RIGHT].current_hp

    def save(engine):
        give(engine, LEFT, devil_qi=2)
        script(engine, [3, 8])  # 8 + save modifier 2 + PB 4 = 14; adding PB again would reach 18.
        engine._roll_save(engine.state.actors[LEFT], "WIS", 16, "test:hostile_effect",
                          roll_context={"source_actor_id": RIGHT})

    save_on_hold(monkeypatch, save)
    assert act(table, mid, "system:combat.hold_position")["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    result = events(loaded.engine, "SAVE_ROLLED")[-1].payload
    assert result["total"] == 14 and result["success"] is False
    assert len(rewrites(loaded.engine)) == 1 and amount(loaded.engine, LEFT, "devil_qi") == 0
    source = loaded.engine.state.actors[RIGHT]
    assert source.current_hp == hp and source.reaction_available
    assert not any("reaction" in c.condition_id for c in source.conditions.values())
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("free", [False, True])
@pytest.mark.parametrize("wasted_total", [5, 20])
@pytest.mark.parametrize("useful_total", [16, 19])
def test_exposed_meridian_auto_conserves_use_then_takes_useful_save_at_table(
        tmp_path, monkeypatch, free, wasted_total, useful_total):
    owned = [KILLING, STOMP] + ([calamity_eyes.PREFIX + "thousand_eyed_revelation"] if free else [])
    combat, table, mid = table_fight(tmp_path, owned, ally_talents=[], primary="Stamina", cl=18)
    if free:
        state = table.state(mid)
        menu = state["menu"]
        cid = next(o["candidate_id"] for g in menu["actions"] if g["label"] == "Thousand-Eyed Revelation"
                   for o in g["options"])
        assert table.act(mid, cid, menu["decision_id"], menu["state_version"], state["last_sequence"])["status"] == "COMMITTED"

    def saves(engine):
        actor, target = engine.state.actors[LEFT], engine.state.actors[RIGHT]
        assert LEFT not in engine.typed_ask_reactors
        ability = min(("STR", "DEX", "CON"), key=lambda a: target.saving_throws.get(a, 0))
        modifier = target.saving_throws.get(ability, 0)
        engine._apply_condition(target, typed_executor.mark_condition_id("Appraised Target", LEFT), KILLING, LEFT,
                                expires_on="START_OF_SOURCE_NEXT_TURN", data={})
        source = next(a.source_definition_id for a in engine.action_catalog.values()
                      if a.owner_id == LEFT and a.display_name == "World-Shaking Stomp")
        before = amount(engine, LEFT, "stamina")
        script(engine, [wasted_total - modifier])
        engine._roll_save(target, ability, 16, source, roll_context={"source_actor_id": LEFT})
        assert not rewrites(engine) and amount(engine, LEFT, "stamina") == before
        assert "_round_killing_line" not in actor.turn_flags
        assert "_round_killing_line_free" not in actor.turn_flags
        script(engine, [useful_total - modifier, 4])
        engine._roll_save(target, ability, 16, source, roll_context={"source_actor_id": LEFT})
        assert amount(engine, LEFT, "stamina") == before - (0 if free else 1)

    save_on_hold(monkeypatch, saves)
    assert act(table, mid, "system:combat.hold_position")["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    results = events(loaded.engine, "SAVE_ROLLED")[-2:]
    assert [e.payload["total"] for e in results] == [wasted_total, useful_total - 4]
    assert results[-1].payload["success"] is False and len(rewrites(loaded.engine)) == 1
    flags = loaded.engine.state.actors[LEFT].turn_flags
    assert isinstance(flags["_round_killing_line"], str)
    assert ("_round_killing_line_free" in flags) == free
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("total", [5, 20])
def test_exposed_meridian_ask_preserves_player_option_even_without_useful_outcome(tmp_path, monkeypatch, total):
    combat, table, mid = table_fight(tmp_path, [KILLING, STOMP], ally_talents=[], ask=True, primary="Stamina")

    def save(engine):
        target = engine.state.actors[RIGHT]
        ability = min(("STR", "DEX", "CON"), key=lambda a: target.saving_throws.get(a, 0))
        engine._apply_condition(target, typed_executor.mark_condition_id("Appraised Target", LEFT), KILLING, LEFT,
                                expires_on="START_OF_SOURCE_NEXT_TURN", data={})
        source = next(a.source_definition_id for a in engine.action_catalog.values()
                      if a.owner_id == LEFT and a.display_name == "World-Shaking Stomp")
        script(engine, [total - target.saving_throws.get(ability, 0), 4])
        engine._roll_save(target, ability, 16, source, roll_context={"source_actor_id": LEFT})

    save_on_hold(monkeypatch, save)
    state = table.state(mid)
    menu = state["menu"]
    cid = next(o["candidate_id"] for g in menu["actions"] if g["label"] == "Hold position" for o in g["options"])
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    prompt = table.act(mid, cid, menu["decision_id"], menu["state_version"], state["last_sequence"])
    assert prompt["status"] == "REACTION_REQUIRED"
    assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
    assert table.act(mid, cid, menu["decision_id"], menu["state_version"], state["last_sequence"],
                     [{**prompt["reaction"]["context"], "selection": "USE"}])["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert events(loaded.engine, "SAVE_ROLLED")[-1].payload["total"] == total - 4
    assert amount(loaded.engine, LEFT, "stamina") == 29
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("domain", ["stars_domain", "world_beneath_the_constellations"])
@pytest.mark.parametrize("foreign", [False, True])
@pytest.mark.parametrize("recipient_inside", [False, True])
def test_star_soul_domain_alignment_qualifies_recipient_and_owner_after_reload(
        tmp_path, monkeypatch, domain, foreign, recipient_inside):
    from combat import zones
    from tests.test_tabletop_hunt6 import ALLY as TABLE_ALLY

    domain_id = "tianxia.talent.stars." + domain
    combat, table, mid = table_fight(tmp_path, [STAR_SOUL, domain_id], ally_talents=[domain_id], cl=18)
    domain_owner = TABLE_ALLY if foreign else LEFT
    center_id = TABLE_ALLY if recipient_inside else LEFT

    def place_domain(engine):
        owner, center = engine.state.actors[domain_owner], engine.state.actors[center_id]
        action = next(a for a in engine.action_catalog.values()
                      if a.owner_id == domain_owner and a.parameters.get("typed", {}).get("source") == domain_id)
        ctx = typed_executor.Context(engine, owner, action, None, action.parameters["typed"], [center], center, {})
        # A minimal synthetic Domain isolates footprint/ownership from casting and area-size rules.
        zones.create(ctx, {"name": action.display_name, "shape": "cube", "size_ft": 5,
                           "duration": {"kind": "minutes", "amount": 1}})

    save_on_hold(monkeypatch, place_domain)
    assert act(table, mid, "system:combat.hold_position")["status"] == "COMMITTED"
    first = CombatService(ROOT, tmp_path)._load_session(mid)
    zone, = zones.typed_zones(first.engine)
    assert zone.owner_id == domain_owner
    assert {(p.x, p.y) for p in zone.affected_cells} == {
        (first.engine.state.actors[center_id].position.x, first.engine.state.actors[center_id].position.y)}

    def save(engine):
        script(engine, [2, 12])
        engine._roll_save(engine.state.actors[TABLE_ALLY], "WIS", 16, "test:spiritual_disturbance",
                          roll_context={"source_actor_id": RIGHT, "named": ["frightened"]})

    # Switch only this test's event callback, retaining the production hooks.
    monkeypatch.undo()
    save_on_hold(monkeypatch, save)
    assert act(table, mid, "end")["status"] == "COMMITTED"
    while table.state(mid)["menu"]["actor_id"] != LEFT:
        assert act(table, mid, "end")["status"] == "COMMITTED"
    assert act(table, mid, "system:combat.hold_position")["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    aligned = recipient_inside and not foreign
    result = events(loaded.engine, "SAVE_ROLLED")[-1].payload
    assert result["total"] == (18 if aligned else 14) and result["success"] == aligned
    assert len(rewrites(loaded.engine)) == 1 and amount(loaded.engine, LEFT, "cp") == 27
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("typed", [False, True])
def test_sacral_recheck_reports_the_effective_total_before_success_riders(typed):
    engine = duel(SACRAL, primary="Resonance")
    script(engine, [13])  # +2 original modifier fails DC 16; +2 Wisdom rescues it.
    force_save(engine, ME, "DEX", dc=16, typed=typed, condition="restrained")
    result = events(engine, "SAVE_ROLLED")[-1].payload
    assert result["natural_result"] == 13 and result["modifier"] == 4
    assert result["total"] == 17 and result["success"] is True
    assert rewrites(engine)[-1].payload["result"]["total"] == 17
    assert typed_executor.bears_mark(engine.state.actors[ME], ME, "Resonance")
    assert not getattr(engine, "_typed_roll_outcome", {})


@pytest.mark.parametrize("aligned,expected", [(False, 14), (True, 18)])
def test_star_soul_guidance_only_adds_bonus_to_an_owner_aligned_recipient(aligned, expected):
    engine = duel(STAR_SOUL, ally_mids=[])
    if aligned:
        engine._apply_condition(engine.state.actors[ALLY], typed_executor.mark_condition_id("Stellar Mark", ME),
                                STAR_SOUL, ME, expires_on="START_OF_SOURCE_NEXT_TURN", data={})
    script(engine, [2, 12])
    force_save(engine, ALLY, "WIS", dc=16, typed=True, condition="frightened")
    result = events(engine, "SAVE_ROLLED")[-1].payload
    assert result["total"] == expected and result["success"] == aligned
    assert rewrites(engine)[-1].payload["result"]["total"] == expected
    assert amount(engine, ME, "cp") == 27


def test_seal_of_final_authority_subtracts_from_a_success_and_rechecks_before_resolution():
    engine = duel([SEAL, BINDING], foundation={"foundation_id": "golden_mandate_seal_v0_2B", "stage": "Perfected",
                                             "resource": {"name": "Edict Seal", "resource_id": "edict_seal", "maximum": 1, "current": 1}})
    action = next(a for a in engine.action_catalog.values() if a.owner_id == ME and a.display_name == "Binding Talisman")
    target = engine.state.actors[FOE]
    script(engine, [16])
    engine._roll_save(target, "WIS", 16, action.source_definition_id, roll_context={"source_actor_id": ME})
    result = events(engine, "SAVE_ROLLED")[-1].payload
    assert result["total"] == 16 + target.saving_throws.get("WIS", 0) - 6
    assert result["success"] is False
    assert amount(engine, ME, "edict_seal") == 0 and not engine.state.actors[ME].reaction_available
    assert any(c.condition_id == "condition:typed.reaction_denied" and c.expires_on == "START_OF_TARGET_NEXT_TURN"
               for c in target.conditions.values())
    from combat.typed_reactions import _can_react

    assert not _can_react(engine, target)
    engine.state.current_actor_id = FOE
    engine.state.current_slot_index = engine.state.initiative_order.index(FOE)
    engine._system_start_turn()
    assert not any(c.condition_id == "condition:typed.reaction_denied" for c in target.conditions.values())


def test_seal_does_not_deny_reactions_when_the_adjusted_save_still_succeeds():
    engine = duel([SEAL, BINDING])
    give(engine, ME, edict_seal=1)
    action = next(a for a in engine.action_catalog.values() if a.owner_id == ME and a.display_name == "Binding Talisman")
    target = engine.state.actors[FOE]
    script(engine, [20])
    engine._roll_save(target, "WIS", 5, action.source_definition_id, roll_context={"source_actor_id": ME})
    assert events(engine, "SAVE_ROLLED")[-1].payload["success"] is True
    assert not any(c.condition_id == "condition:typed.reaction_denied" for c in target.conditions.values())


@pytest.mark.parametrize("source,die", [("test:unrelated", 16), (None, 2)])
def test_seal_leaves_unrelated_saves_and_already_failed_saves_unchanged(source, die):
    engine = duel([SEAL, BINDING])
    give(engine, ME, edict_seal=1)
    source = source or next(a.source_definition_id for a in engine.action_catalog.values()
                           if a.owner_id == ME and a.display_name == "Binding Talisman")
    script(engine, [die])
    engine._roll_save(engine.state.actors[FOE], "WIS", 16, source, roll_context={"source_actor_id": ME})
    assert not rewrites(engine) and amount(engine, ME, "edict_seal") == 1


@pytest.mark.parametrize("kind", ["star_soul", "exposed_meridian", "seal"])
def test_new_save_recheck_rows_ask_at_the_table_and_commit_the_effective_result(tmp_path, monkeypatch, kind):
    import tests.test_tabletop_hunt6 as harness

    owned = {"star_soul": [STAR_SOUL], "exposed_meridian": [KILLING, STOMP], "seal": [SEAL, BINDING]}[kind]
    if kind == "seal":
        real_sheet = harness.sheet

        def with_seal_pool(talents, **kwargs):
            return real_sheet(talents, **kwargs, foundation={"foundation_id": "golden_mandate_seal_v0_2B", "stage": "Perfected",
                                                           "resource": {"name": "Edict Seal", "resource_id": "edict_seal", "maximum": 1, "current": 1}})

        monkeypatch.setattr(harness, "sheet", with_seal_pool)
    combat, table, mid = table_fight(tmp_path, owned, ally_talents=[], ask=True,
                                   primary="Stamina" if kind == "exposed_meridian" else "Qi")
    cid = next(o["candidate_id"] for g in table.state(mid)["menu"]["actions"]
               if g["label"] == "Hold position" for o in g["options"])

    def save(engine):
        owner = engine.state.actors[LEFT]
        target = owner if kind == "star_soul" else engine.state.actors[RIGHT]
        if kind in ("star_soul", "exposed_meridian"):
            mark = "Stellar Mark" if kind == "star_soul" else "Appraised Target"
            engine._apply_condition(target, typed_executor.mark_condition_id(mark, LEFT), owned[0], LEFT,
                                    expires_on="START_OF_SOURCE_NEXT_TURN", data={})
        name = "World-Shaking Stomp" if kind == "exposed_meridian" else "Binding Talisman"
        source = "test:spiritual_disturbance" if kind == "star_soul" else next(
            a.source_definition_id for a in engine.action_catalog.values() if a.owner_id == LEFT and a.display_name == name)
        ability = "WIS" if kind != "exposed_meridian" else "STR"
        script(engine, [2, 12] if kind == "star_soul" else [16 - target.saving_throws[ability], 4])
        engine._roll_save(target, ability, 16, source,
                          roll_context={"source_actor_id": RIGHT if kind == "star_soul" else LEFT, "named": ["frightened"]})

    save_on_hold(monkeypatch, save)

    def send(answers):
        state = table.state(mid)
        menu = state["menu"]
        return table.act(mid, cid, menu["decision_id"], menu["state_version"], state["last_sequence"], answers)

    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    prompt = send([])
    assert prompt["status"] == "REACTION_REQUIRED", prompt
    assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
    assert send([])["reaction"] == prompt["reaction"]
    assert send([{**prompt["reaction"]["context"], "selection": "USE"}])["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    result = events(loaded.engine, "SAVE_ROLLED")[-1].payload
    assert result["success"] == (kind == "star_soul")
    assert result["total"] == {"star_soul": 18, "exposed_meridian": 12, "seal": 10}[kind]
    assert loaded.mechanical.replay()["status"] == "PASS"
    if kind == "seal":
        assert loaded.engine.state.actors[LEFT].resources["resource:foundation.edict_seal"] == 0
    if kind == "exposed_meridian":
        assert "_round_killing_line" in loaded.engine.state.actors[LEFT].turn_flags


@pytest.mark.parametrize("ability,qualifies", [("STR", True), ("DEX", False), ("CON", True)])
def test_exposed_meridian_uses_the_identified_lowest_save_and_shared_turn_limit(ability, qualifies):
    engine = duel([KILLING, STOMP], primary="Stamina")
    actor, target = engine.state.actors[ME], engine.state.actors[FOE]
    target.saving_throws.update(STR=0, DEX=4, CON=0)
    engine._apply_condition(target, typed_executor.mark_condition_id("Appraised Target", ME), KILLING, ME,
                            expires_on="START_OF_SOURCE_NEXT_TURN", data={})
    action = next(a for a in engine.action_catalog.values() if a.owner_id == ME and a.display_name == "World-Shaking Stomp")
    script(engine, [16, 4])
    engine._roll_save(target, ability, 16, action.source_definition_id, roll_context={"source_actor_id": ME})
    result = events(engine, "SAVE_ROLLED")[-1].payload
    assert result["total"] == 16 + target.saving_throws[ability] - (4 if qualifies else 0)
    assert len(rewrites(engine)) == int(qualifies)
    assert amount(engine, ME, "stamina") == 30 - int(qualifies)
    if qualifies:
        assert actor.turn_flags["_round_killing_line"] == f"{engine.state.round_number}:{engine.state.current_actor_id}"
        script(engine, [16])
        engine._roll_save(target, ability, 16, action.source_definition_id, roll_context={"source_actor_id": ME})
        assert len(rewrites(engine)) == 1


def test_exposed_meridian_during_revelation_is_free_and_still_uses_the_shared_turn_limit():
    engine = duel([KILLING, STOMP, calamity_eyes.PREFIX + "thousand_eyed_revelation"], primary="Stamina", cl=18)
    use(engine, "Thousand-Eyed Revelation")
    target = engine.state.actors[FOE]
    target.saving_throws.update(STR=0, DEX=0, CON=0)
    engine._apply_condition(target, typed_executor.mark_condition_id("Appraised Target", ME), KILLING, ME,
                            expires_on="START_OF_SOURCE_NEXT_TURN", data={})
    action = next(a for a in engine.action_catalog.values() if a.owner_id == ME and a.display_name == "World-Shaking Stomp")
    before = amount(engine, ME, "stamina")
    script(engine, [16, 4, 16])
    engine._roll_save(target, "STR", 16, action.source_definition_id, roll_context={"source_actor_id": ME})
    assert events(engine, "SAVE_ROLLED")[-1].payload["total"] == 12
    assert amount(engine, ME, "stamina") == before
    engine._roll_save(target, "STR", 16, action.source_definition_id, roll_context={"source_actor_id": ME})
    assert len(rewrites(engine)) == 1 and events(engine, "SAVE_ROLLED")[-1].payload["total"] == 16


@pytest.mark.parametrize("auto_turn", [False, True])
@pytest.mark.parametrize("selection", ["USE", "DECLINE"])
def test_sacral_save_recheck_table_preview_commit_reload_on_manual_and_ai_turns(tmp_path, monkeypatch, auto_turn, selection):
    combat, table, mid = table_fight(tmp_path, [SACRAL], ally_talents=[], ask=True, primary="Resonance")
    assert act(table, mid, "end")["status"] == "COMMITTED"
    while table.state(mid)["menu"]["actor_id"] != RIGHT:
        assert act(table, mid, "end")["status"] == "COMMITTED"
    cid = next(o["candidate_id"] for g in table.state(mid)["menu"]["actions"]
               if g["label"] == "Hold position" for o in g["options"])

    def save(engine):
        script(engine, [13])
        engine._roll_save(engine.state.actors[LEFT], "DEX", 16, "test:spiritual_disturbance",
                          roll_context={"source_actor_id": RIGHT})

    save_on_hold(monkeypatch, save)
    if auto_turn:
        real = combat.controller

        class Controller:
            def choose_primary_action(self, context):
                return ManualControllerAdapter(lambda _: (cid, ())).choose_primary_action(context)

            def __getattr__(self, name):
                return getattr(real, name)

        combat.controller = Controller()
        combat.set_controller_mode(mid, actor_id=RIGHT, controller_mode="LOCAL_AUTO")
    def send(answers):
        if auto_turn:
            return table.auto_step(mid, 0, answers)
        state = table.state(mid)
        menu = state["menu"]
        return table.act(mid, cid, menu["decision_id"], menu["state_version"], state["last_sequence"], answers)
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    prompt = send([])
    assert prompt["status"] == "REACTION_REQUIRED", prompt
    assert prompt["reaction"]["context"]["reactor_id"] == LEFT
    assert send([])["reaction"] == prompt["reaction"]
    assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
    answer = {**prompt["reaction"]["context"], "selection": selection}
    assert send([answer])["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    result = events(loaded.engine, "SAVE_ROLLED")[-1].payload
    assert result["success"] == (selection == "USE")
    assert result["total"] == (17 if selection == "USE" else 15)
    assert loaded.engine.state.actors[LEFT].resources["resource:core.resonance"] == (28 if selection == "USE" else 30)
    assert typed_executor.bears_mark(loaded.engine.state.actors[LEFT], LEFT, "Resonance") == (selection == "USE")
    assert loaded.mechanical.replay()["status"] == "PASS"
