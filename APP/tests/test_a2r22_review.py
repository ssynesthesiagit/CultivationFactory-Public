"""A2R22 review: legal actions, actual rolls, turn boundaries and cold table loads.

Test-only check actions use the general contest effect, not synthetic receipts.
All services use isolated pytest storage; no live model or embedding server is used.
"""
import pytest

from combat import ext, flight, roof_movement
from combat import embedding_rank, menu_rank
from combat.ext import athletics, forged_exhaustion
from combat.gate2_runtime_models import ActionDefinition, EconomyKind
from tests.auto8f1_table_support import (
    fixture, candidate_id, reload_identical, zero_martial_focus, OWNER, FOE,
)
from tests.cw2_service_support import seal
from tests.athletics_rules_support import require_athletics_rules

COORDINATED = "ATHLETICS_BASE_COORDINATED_MOVEMENT"
MERIDIAN = "TAL_ATHLETICS_MERIDIAN_THREADING_DASH"
BOOST = "TAL_ATHLETICS_SPEED_BOOST"
SWIFT = "TAL_ATHLETICS_SWIFT_MOVEMENT"
HEAVEN = "TAL_ATHLETICS_HEAVEN_TREADING_BODY"
SPIDER = "TAL_ATHLETICS_SPIDER_S_TOUCH"
SPARROW = "TAL_ATHLETICS_SPARROW_S_PATH"


@pytest.fixture(autouse=True)
def fake_menu_embeddings(monkeypatch):
    require_athletics_rules()
    class OfflineClient:
        def embed(self, texts):
            raise embedding_rank.EmbeddingError("deterministic native ranking in tests")

        def prefetch(self, texts, **kwargs):
            pass
    monkeypatch.setattr(menu_rank, "_CLIENT", OfflineClient())


def add_action(bundle, name, effects, *, hostile=False):
    source = "action:test.a2r22." + name.replace(" ", "_")
    action = ActionDefinition(
        source_definition_id=source, display_name=name, owner_id=bundle["actor_id"],
        economy=EconomyKind.ACTION, resolution_kind="TYPED",
        target_kind="HOSTILE_ENTITY" if hostile else "SELF", range_ft=120 if hostile else None,
        parameters={"typed": {"effects": effects, "numbers": {"save_dc": 12},
                              "riders": [], "duration": {"kind": "instant"}}},
    )
    bundle["action_catalog"].append(action.model_dump(mode="json"))
    bundle["actor_template"]["action_ids"].append(source)


def choose_check(_prompt, choice):
    return [next((o["id"] for o in choice["options"] if o["id"] in ("check", "Athletics")),
                 choice["options"][0]["id"])]


def use(g, label, chooser=choose_check, *, target=None):
    menu = g["menu"]()
    if target is None:
        cid = candidate_id(menu, label)
    else:
        cid = next(o["candidate_id"] for group in menu["actions"] for o in group["options"]
                   if label in o["label"] and target in o.get("target_ids", []))
    return g["commit"](cid, chooser)


def held(actor):
    return [c for c in actor.conditions.values() if c.condition_id == athletics.MERIDIAN_CHECK]


def finish(g):
    reload_identical(g["combat"], g["match_id"], g["userdata"])


@pytest.mark.parametrize("route", ["general", "brute"])
def test_real_contest_spends_both_sides_once_after_table_reload(tmp_path, route):
    talents = [COORDINATED, MERIDIAN]
    if route == "brute":
        talents += ["TAL_BRUTE_GREATER_BRUTE"]

    def prepare(bundles):
        zero_martial_focus(bundles)
        for b in bundles:
            if b["actor_id"] == FOE:
                for r in b["actor_template"]["resources"]:
                    if r["resource_id"] == athletics.FOCUS:
                        r["initial"] = 0
            if b["actor_id"] == OWNER:
                add_action(b, "Athletics contest", [{"type": "contest_against",
                    "actor_check": {"kind": "check", "ability": "STR", "skill": "Athletics"},
                    "target_check": {"kind": "check", "ability": "STR", "skill": "Athletics"}}], hostile=True)
            seal(b)

    g = fixture(tmp_path, talents, seed="A2R22-contest-" + route,
                talents_by_actor={FOE: [COORDINATED, MERIDIAN]}, ask_actors=(FOE,),
                bundle_transform=prepare)
    use(g, "Dash")
    g["turn_of"](FOE)
    use(g, "Dash")
    g["to_owner"]()
    e = g["stored_engine"]()
    assert held(e.state.actors[OWNER]) and held(e.state.actors[FOE])
    # Menu/preview queries do not consume either entitlement.
    g["menu"]()
    for who in (OWNER, FOE):
        assert held(g["stored_engine"]().state.actors[who])
    label = "Brutal Shove" if route == "brute" else "Athletics contest"
    use(g, label, target=FOE)
    e = g["stored_engine"]()
    check = next(x for x in reversed(e.events) if x.event_type == "CHECK_ROLLED")
    assert len(check.payload["actor"]["dice"]) == 2
    assert len(check.payload["target"]["dice"]) == 2
    assert not held(e.state.actors[OWNER]) and not held(e.state.actors[FOE])
    assert check.payload["target_ability"] == "STR"
    # A second legal contest rolls ordinary dice, with neither grant reusable.
    g["commit"](g["menu"]()["end_turn"])
    g["to_owner"]()
    use(g, "Athletics contest", target=FOE)
    e = g["stored_engine"]()
    check = next(x for x in reversed(e.events) if x.event_type == "CHECK_ROLLED")
    assert len(check.payload["actor"]["dice"]) == len(check.payload["target"]["dice"]) == 1
    finish(g)


def test_meridian_survives_granting_turn_and_expires_at_end_of_next_turn(tmp_path):
    def prepare(bundles):
        zero_martial_focus(bundles)
        for b in bundles:
            seal(b)
    g = fixture(tmp_path, [COORDINATED, MERIDIAN], seed="A2R22-deadline", bundle_transform=prepare)
    use(g, "Dash")
    deadline = held(g["reload_owner"]())[0].expires_on
    g["commit"](g["menu"]()["end_turn"])
    assert held(g["reload_owner"]())[0].expires_on == deadline
    g["to_owner"]()
    assert held(g["reload_owner"]())
    g["commit"](g["menu"]()["end_turn"])
    assert not held(g["reload_owner"]())
    finish(g)


@pytest.mark.parametrize("grant,mode,base,expected", [
    (HEAVEN, "fly", 40, 90), (SPIDER, "climb", 40, 90),
    (SPARROW, "fly", 0, 65), (HEAVEN, "fly", 0, 80), (SPIDER, "climb", 0, 80),
])
def test_competing_and_sparrow_grants_receive_bonus_before_selection(tmp_path, grant, mode, base, expected):
    def prepare(bundles):
        bundles[0]["actor_template"][mode + "_speed_ft"] = base
        for b in bundles:
            seal(b)
    g = fixture(tmp_path, [BOOST, grant], seed="A2R22-mode-" + mode + grant,
                bundle_transform=prepare)
    use(g, "Speed Boost: +50 feet")
    e = g["stored_engine"]()
    actor = e.state.actors[OWNER]
    query = flight.profile if mode == "fly" else roof_movement.profile
    assert query(e, actor).speed_ft == expected
    assert flight.remaining(e, actor, mode) == expected
    # Commit a real move, then verify the grant still composes on a fresh service.
    move = next(m for m in g["menu"]()["moves"] if m["cost_ft"] == 5)
    g["commit"](move["candidate_id"])
    e = g["stored_engine"]()
    assert query(e, e.state.actors[OWNER]).speed_ft == expected
    finish(g)


@pytest.mark.parametrize("focused,expected", [(True, 25), (False, 15)])
def test_swift_sparrow_bonus_is_full_ten_and_focus_gated(tmp_path, focused, expected):
    def prepare(bundles):
        if not focused:
            zero_martial_focus(bundles)
        for b in bundles:
            seal(b)
    g = fixture(tmp_path, [SWIFT, SPARROW], seed="A2R22-swift", bundle_transform=prepare)
    use(g, "Dodge")
    e = g["stored_engine"]()
    assert flight.profile(e, e.state.actors[OWNER]).speed_ft == expected
    finish(g)


def test_unrelated_motion_bonus_is_inert_for_athletics_nonowner(tmp_path):
    def prepare(bundles):
        b = bundles[0]
        b["actor_template"].update(fly_speed_ft=40, climb_speed_ft=40)
        b["typed_passives"].append({"block": "motion", "kind": "speed_bonus", "ft": 10,
                                    "feature_id": "test:unrelated-walking-bonus"})
        for b in bundles:
            seal(b)
    g = fixture(tmp_path, [], seed="A2R22-nonowner", bundle_transform=prepare)
    use(g, "Dodge")
    e = g["stored_engine"]()
    actor = e.state.actors[OWNER]
    assert e._effective_speed(actor) == 40
    assert athletics.athletics_flight(e, actor) is None
    assert athletics.athletics_climbing(e, actor) is None
    assert flight.profile(e, actor).speed_ft == roof_movement.profile(e, actor).speed_ft == 40
    finish(g)


def test_bonus_applies_to_another_provider_not_only_actor_fields(monkeypatch):
    from tests.test_auto_athletics import _engine, _me
    e = _engine([BOOST, HEAVEN, SPIDER])
    actor = _me(e)
    e._apply_condition(actor, athletics.BOOST_CONDITION, BOOST, actor.entity_id,
                       expires_on="UNTIL_REMOVED", data={})
    def flying(_engine, _actor):
        return {"fly_speed_ft": 40}
    def climbing(_engine, _actor):
        return {"climb_speed_ft": 40}
    monkeypatch.setitem(ext._HOOKS, "flight", [*ext._HOOKS["flight"], flying])
    monkeypatch.setitem(ext._HOOKS, "climbing", [*ext._HOOKS["climbing"], climbing])
    assert flight.profile(e, actor).speed_ft == roof_movement.profile(e, actor).speed_ft == 90


@pytest.mark.parametrize("native,expected", [(0, 80), (40, 90)])
@pytest.mark.parametrize("provider", ["daemonic", "drunken"])
def test_another_land_derived_provider_does_not_double_count_athletics(native, expected, provider):
    from tests.test_auto_athletics import _engine, _me
    e = _engine([BOOST])
    actor = _me(e)
    actor.fly_speed_ft = native
    e._apply_condition(actor, athletics.BOOST_CONDITION, BOOST, actor.entity_id,
                       expires_on="UNTIL_REMOVED", data={})
    # Real providers: flight equals effective walking Speed.
    if provider == "daemonic":
        condition, data = "condition:typed.test_daemonic_flight", {"auto63_walking_flight": 1}
    else:
        from combat.ext.drunken_style import FLIGHT
        condition, data = FLIGHT, {"drunken_sovereign_flight": 1}
    e._apply_condition(actor, condition, "test:flight", actor.entity_id,
                       expires_on="UNTIL_REMOVED", data=data)
    assert flight.profile(e, actor).speed_ft == expected


@pytest.mark.parametrize("native", [0, 40])
def test_lightning_mixed_fixed_and_land_grants_keep_the_fastest_boosted_speed(native):
    from tests.test_auto_athletics import _engine, _me
    from combat.ext import lightning_riders, states
    e = _engine([BOOST])
    actor = _me(e)
    actor.fly_speed_ft = native
    e.typed_passive_rows[actor.entity_id].append({"block": "lightning_combat", "kind": "wings"})
    e._apply_condition(actor, athletics.BOOST_CONDITION, BOOST, actor.entity_id,
                       expires_on="UNTIL_REMOVED", data={})
    e._apply_condition(actor, states.PREFIX + states.slug(lightning_riders.SOVEREIGN),
                       "test:lightning-sovereign", actor.entity_id, expires_on="UNTIL_REMOVED", data={})
    # Sovereign's fixed 60 + 50 beats land 30 + 50; neither is double-counted.
    assert flight.profile(e, actor).speed_ft == 110


def test_ordinary_exhaustion_after_real_boost_expiry_preserves_immune_penalty(tmp_path):
    def prepare(bundles):
        b = bundles[0]
        b["typed_reactions"].append({"block": "condition_immunity", "conditions": ["exhaustion"]})
        add_action(b, "Ordinary exhaustion", [{"type": "exhaustion", "amount": 1, "applies_to": "self"}])
        add_action(b, "Recover exhaustion", [{"type": "exhaustion", "amount": -1, "applies_to": "self"}])
        for b in bundles:
            seal(b)
    g = fixture(tmp_path, [BOOST], seed="A2R22-immune", bundle_transform=prepare)
    use(g, "Speed Boost: +50 feet")
    assert any(c.condition_id == athletics.BOOST_CONDITION for c in g["reload_owner"]().conditions.values())
    for _ in range(6):
        g["commit"](g["menu"]()["end_turn"])
        g["to_owner"]()
        if forged_exhaustion.level(g["reload_owner"]()):
            break
    actor = g["reload_owner"]()
    assert forged_exhaustion.level(actor) == 1
    before = actor.movement_remaining_ft
    penalty = next(c for c in actor.conditions.values() if c.condition_id == forged_exhaustion.CONDITION_ID)
    use(g, "Ordinary exhaustion")
    actor = g["reload_owner"]()
    assert forged_exhaustion.level(actor) == 1
    assert actor.movement_remaining_ft == before
    assert penalty.instance_id in actor.conditions
    g["commit"](g["menu"]()["end_turn"])
    g["to_owner"]()
    use(g, "Recover exhaustion")
    assert forged_exhaustion.level(g["reload_owner"]()) == 0
    finish(g)


def test_immune_bearer_can_reduce_an_unavoidable_level_without_erasing_the_remainder():
    from tests.test_auto_athletics import _engine, _me
    e = _engine([])
    actor = _me(e)
    e.typed_reaction_rows[actor.entity_id] = [
        {"block": "condition_immunity", "conditions": ["exhaustion"]}]
    forged_exhaustion.add(e, actor, 2, "test:unavoidable", immune_bypass=True)
    before = actor.movement_remaining_ft
    forged_exhaustion.add(e, actor, 1, "test:ordinary")
    assert forged_exhaustion.level(actor) == 2
    assert actor.movement_remaining_ft == before
    forged_exhaustion.set_level(e, actor, 1, "test:recovery")
    assert forged_exhaustion.level(actor) == 1
    assert actor.movement_remaining_ft == before + 5
