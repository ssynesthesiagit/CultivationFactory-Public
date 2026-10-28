"""Ammunition stock is paid per actual weapon strike and survives table reload."""

from types import SimpleNamespace

import pytest

from combat.ext.ammunition import _CEASELESS, _ammunition_record, _ceaseless, _stock
from combat.gate5_service import CombatService
from combat.tabletop import engine_button_description
from tests.test_tabletop_hunt6 import ALLY, LEFT, RIGHT, answer_action, table_fight

BOW = "tianxia.mortal.weapon.gong_jian"
CROSSBOW = "tianxia.mortal.weapon.nu_gong"
ARROWS = "tianxia.mortal.gear.arrows_20"
BOLTS = "tianxia.mortal.gear.bolts_20"
SLING_BULLETS = "tianxia.mortal.gear.bullets_sling_20"
NEEDLES = "tianxia.mortal.gear.needles_50"
EXTRA_ATTACK = "tianxia.path.body_refining.feature.extra_attack"


def kit(*, weapon=BOW, ammo=None, one_piece=False):
    items = [{"item_id": weapon, "quantity": 1}]
    if ammo:
        name = "Arrow bundle with a custom label" if one_piece else {ARROWS: "Arrows (20)", BOLTS: "Bolts (20)"}.get(ammo, ammo)
        items.append({"item_id": ammo, "name": name, "quantity": 1})
    return {"starting_kit": {"items": items}}


@pytest.mark.parametrize("weapon,ammo", [
    ("tianxia.mortal.weapon.dan_gong", SLING_BULLETS),
    ("tianxia.mortal.weapon.chui_jian_tong", NEEDLES),
])
def test_compiler_matches_pellet_and_blowgun_ammunition(weapon, ammo):
    record = _ammunition_record({"source": weapon, "weapon": {"properties": "Ammunition"}})
    assert record["item_id"] == ammo


@pytest.mark.parametrize("weapon,ammo,source", [
    (BOW, ARROWS, ".weapon.gong_jian"),
    (CROSSBOW, BOLTS, ".weapon.nu_gong"),
])
def test_unlisted_ammo_is_unlimited_and_description_stays_silent(tmp_path, weapon, ammo, source):
    combat, table, match_id = table_fight(tmp_path, [], kit=kit(weapon=weapon))
    menu = table.state(match_id)["menu"]
    assert any(source in group["source_definition_id"] for group in menu["actions"])

    loaded = combat._load_session(match_id)
    action = next(row for row in loaded.engine.action_catalog.values() if row.source_definition_id.endswith(source))
    assert action.parameters["typed"]["ammunition"]["item_id"] == ammo
    description = engine_button_description(action.model_dump(mode="json"))
    assert "each attack uses" not in description.lower()
    assert "none are carried" not in description.lower()
    assert "Action:" in description and "Armor Class" in description


def test_explicit_zero_ammunition_is_not_offered_and_has_plain_reason(tmp_path):
    zero_arrows = {"starting_kit": {"items": [
        {"item_id": BOW, "quantity": 1}, {"item_id": ARROWS, "name": "Arrows", "quantity": 0},
    ]}}
    combat, table, match_id = table_fight(tmp_path, [], kit=zero_arrows)
    menu = table.state(match_id)["menu"]
    assert not any(".weapon.gong_jian" in group["source_definition_id"] for group in menu["actions"])
    loaded = combat._load_session(match_id)
    action = next(row for row in loaded.engine.action_catalog.values() if row.source_definition_id.endswith(".weapon.gong_jian"))
    assert action.parameters["typed"]["ammunition"]["tracked"] is True
    description = engine_button_description(action.model_dump(mode="json"))
    assert "no arrows are carried" in description.lower()
    assert "Action:" in description and "feet normally" in description


def test_actual_strike_spends_one_arrow_across_table_reload_and_replay(tmp_path):
    combat, table, match_id = table_fight(tmp_path, [EXTRA_ATTACK], cl=11, kit=kit(ammo=ARROWS, one_piece=True))
    assert any(".weapon.gong_jian" in group["source_definition_id"] for group in table.state(match_id)["menu"]["actions"])
    loaded = combat._load_session(match_id)
    action = next(row for row in loaded.engine.action_catalog.values() if row.source_definition_id.endswith(".weapon.gong_jian"))
    assert action.parameters["typed"]["effects"][0]["count"] > 1
    answer_action(table, match_id, ".weapon.gong_jian")

    loaded = combat._load_session(match_id)
    actor = loaded.engine.state.actors[LEFT]
    rolls = [event for event in loaded.engine.events if event.event_type == "ATTACK_ROLLED"
             and event.actor_id == LEFT and event.source_definition_id.endswith(".weapon.gong_jian")]
    assert len(rolls) == 3  # one inventory unit has twenty arrows, regardless of its label
    spent_key = "_round_ammunition_spent:" + ARROWS + ":" + ARROWS
    assert actor.turn_flags[spent_key] == 3
    assert type(actor.turn_flags[spent_key]) is int
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_bundle_without_ammunition_counts_keeps_legacy_unlimited_behavior():
    actor = SimpleNamespace(entity_id=LEFT, turn_flags={})
    ammo = {"item_id": ARROWS, "label": "arrow"}
    old = SimpleNamespace(typed_bundle_documents=({"actor_id": LEFT},))
    explicit_empty = SimpleNamespace(typed_bundle_documents=({"actor_id": LEFT, "carrying": {"items": []}},))
    assert _stock(old, actor, ammo) is None
    assert _stock(explicit_empty, actor, ammo) is None
    assert _stock(explicit_empty, actor, {**ammo, "tracked": True}) == 0


def test_unlisted_arrows_fire_repeatedly_through_table_reload_and_replay(tmp_path):
    combat, table, match_id = table_fight(tmp_path, [EXTRA_ATTACK], cl=11, kit=kit())
    assert any(".weapon.gong_jian" in group["source_definition_id"] for group in table.state(match_id)["menu"]["actions"])
    answer_action(table, match_id, ".weapon.gong_jian")

    loaded = combat._load_session(match_id)
    rolls = [event for event in loaded.engine.events if event.event_type == "ATTACK_ROLLED"
             and event.actor_id == LEFT and event.source_definition_id.endswith(".weapon.gong_jian")]
    assert len(rolls) >= 2
    assert not any(key.startswith("_round_ammunition_spent:") for key in loaded.engine.state.actors[LEFT].turn_flags)
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_ceaseless_ammunition_requires_ten_pieces_and_does_not_spend():
    actor = SimpleNamespace(entity_id=LEFT, turn_flags={})
    ammo = {"item_id": ARROWS, "label": "arrow", "ceaseless": True}
    bundle = {"actor_id": LEFT, "carrying": {"items": [
        {"key": ARROWS, "item_id": ARROWS, "name": "Arrows (20)", "quantity": 1},
    ]}}
    actor.conditions = {}
    engine = SimpleNamespace(typed_bundle_documents=(bundle,))
    assert _stock(engine, actor, ammo) == 20
    assert _ceaseless(engine, actor, ammo)
    actor.turn_flags["_round_ammunition_spent:" + ARROWS + ":" + ARROWS] = 11
    assert not _ceaseless(engine, actor, ammo)


def test_ceaseless_owner_keeps_twenty_arrows_unspent_in_a_saved_fight(tmp_path):
    combat, table, match_id = table_fight(tmp_path, [_CEASELESS], kit=kit(ammo=ARROWS))
    before = combat._load_session(match_id)
    action = next(row for row in before.engine.action_catalog.values() if row.source_definition_id.endswith(".weapon.gong_jian"))
    assert action.parameters["typed"]["ammunition"]["ceaseless"] is True
    answer_action(table, match_id, ".weapon.gong_jian")
    loaded = combat._load_session(match_id)
    actor = loaded.engine.state.actors[LEFT]
    rolls = [event for event in loaded.engine.events if event.event_type == "ATTACK_ROLLED"
             and event.actor_id == LEFT and ".weapon.gong_jian." in event.source_definition_id]
    assert rolls, "the table action must make a real bow attack"
    spent_prefix = "_round_ammunition_spent:" + ARROWS + ":"
    assert not any(key.startswith(spent_prefix) for key in actor.turn_flags)
    assert _stock(loaded.engine, actor, action.parameters["typed"]["ammunition"]) == 20
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_delivery_technique_is_hidden_when_its_bow_has_explicitly_zero_arrows(tmp_path):
    talents = ["TAL_LIGHTNING_THUNDER_ARROW", "TAL_LIGHTNING_THOUSAND_SPARK_VOLLEY"]
    zero = {"starting_kit": {"items": [
        {"item_id": BOW, "quantity": 1}, {"item_id": ARROWS, "name": "renamed arrows", "quantity": 0},
    ]}}
    combat, table, match_id = table_fight(tmp_path, talents, cl=11, kit=zero)
    before = combat._load_session(match_id)
    technique = next(row for row in before.engine.action_catalog.values()
                     if "thousand_spark_volley" in row.source_definition_id.lower())
    assert technique.parameters["typed"].get("delivered_by")
    assert not any("thousand_spark_volley" in group["source_definition_id"].lower()
                   for group in table.state(match_id)["menu"]["actions"])
    loaded = combat._load_session(match_id)
    assert not any(event.source_definition_id == technique.source_definition_id
                   and event.event_type in {"RESOURCE_SPENT", "ACTION_DECLARED"} for event in loaded.engine.events)
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("talents", [[], [_CEASELESS]])
def test_dropped_arrows_do_not_supply_attacks_or_ceaseless(tmp_path, talents):
    combat, table, match_id = table_fight(tmp_path, talents, kit=kit(ammo=ARROWS))
    before = table.state(match_id)
    drop_id = next(group["options"][0]["candidate_id"] for group in before["menu"]["actions"]
                   if ".item_drop." in group["source_definition_id"] and "arrows" in group["label"].lower())
    assert table.act(match_id, drop_id, before["menu"]["decision_id"], before["menu"]["state_version"],
                     before["last_sequence"], [])["status"] == "COMMITTED"
    loaded = combat._load_session(match_id)
    actor = loaded.engine.state.actors[LEFT]
    assert _stock(loaded.engine, actor, {"item_id": ARROWS, "tracked": True}) == 0
    assert not any("gong_jian" in group["source_definition_id"] for group in table.state(match_id)["menu"]["actions"])
    assert not _ceaseless(loaded.engine, actor, {"item_id": ARROWS, "tracked": True, "ceaseless": True})
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_pack_piece_count_uses_ammunition_identity_not_display_name():
    actor = SimpleNamespace(entity_id=LEFT, turn_flags={})
    bundle = {"actor_id": LEFT, "carrying": {"items": [
        {"key": "renamed", "item_id": ARROWS, "name": "single arrow", "quantity": 2},
    ]}}
    actor.conditions = {}
    engine = SimpleNamespace(typed_bundle_documents=(bundle,), state=SimpleNamespace(actors={LEFT: actor}))
    assert _stock(engine, actor, {"item_id": ARROWS, "tracked": True}) == 40


def test_spent_count_stays_with_its_stack_after_another_stack_is_dropped():
    from combat.ext.ammunition import _SPENT_PREFIX
    from combat import carry

    actor = SimpleNamespace(entity_id=LEFT, turn_flags={_SPENT_PREFIX + ARROWS + ":used": 20}, conditions={})
    rows = [
        {"key": "used", "item_id": ARROWS, "quantity": 1},
        {"key": "fresh", "item_id": ARROWS, "quantity": 1},
    ]
    engine = SimpleNamespace(typed_bundle_documents=({"actor_id": LEFT, "carrying": {"items": rows}},))
    assert _stock(engine, actor, {"item_id": ARROWS, "tracked": True}) == 20
    actor.conditions["dropped-fresh"] = SimpleNamespace(
        condition_id=carry.DROPPED, data={"item_key": "fresh"})
    assert _stock(engine, actor, {"item_id": ARROWS, "tracked": True}) == 0
    del actor.conditions["dropped-fresh"]  # picking up the same stack restores only its unspent pieces
    assert _stock(engine, actor, {"item_id": ARROWS, "tracked": True}) == 20


def test_mixed_zero_and_positive_rows_do_not_create_phantom_stock_after_drop(tmp_path):
    mixed = {"starting_kit": {"items": [
        {"item_id": BOW, "quantity": 1},
        {"item_id": ARROWS, "name": "empty bundle", "quantity": 0},
        {"item_id": ARROWS, "name": "full bundle", "quantity": 1},
    ]}}
    combat, table, match_id = table_fight(tmp_path, [], kit=mixed)
    before = table.state(match_id)
    drops = [group for group in before["menu"]["actions"]
             if ".item_drop." in group["source_definition_id"] and "full bundle" in group["label"].lower()]
    assert drops
    drop_id = drops[0]["options"][0]["candidate_id"]
    assert table.act(match_id, drop_id, before["menu"]["decision_id"], before["menu"]["state_version"],
                     before["last_sequence"], [])["status"] == "COMMITTED"
    loaded = combat._load_session(match_id)
    assert _stock(loaded.engine, loaded.engine.state.actors[LEFT], {"item_id": ARROWS, "tracked": True,
                    "zero_stack_keys": ARROWS}) == 0
    assert not any("gong_jian" in group["source_definition_id"]
                   for group in table.state(match_id)["menu"]["actions"])
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_last_projectile_fires_then_attack_disappears_after_reload_and_replay(tmp_path, monkeypatch):
    import combat.ext.ammunition as ammunition

    monkeypatch.setitem(ammunition._PIECES_PER_UNIT, ARROWS, 1)
    combat, table, match_id = table_fight(tmp_path, [], kit=kit(ammo=ARROWS))
    assert any("gong_jian" in group["source_definition_id"] for group in table.state(match_id)["menu"]["actions"])
    answer_action(table, match_id, ".weapon.gong_jian")
    loaded = combat._load_session(match_id)
    rolls = [event for event in loaded.engine.events if event.event_type == "ATTACK_ROLLED"
             and event.actor_id == LEFT and event.source_definition_id.endswith(".weapon.gong_jian")]
    assert len(rolls) == 1
    assert not any("gong_jian" in group["source_definition_id"] for group in table.state(match_id)["menu"]["actions"])
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_extra_attack_spends_one_projectile_per_strike_and_stops_at_zero(tmp_path, monkeypatch):
    import combat.ext.ammunition as ammunition

    monkeypatch.setitem(ammunition._PIECES_PER_UNIT, ARROWS, 2)
    combat, table, match_id = table_fight(tmp_path, [EXTRA_ATTACK], cl=11, kit=kit(ammo=ARROWS))
    answer_action(table, match_id, ".weapon.gong_jian")
    loaded = combat._load_session(match_id)
    rolls = [event for event in loaded.engine.events if event.event_type == "ATTACK_ROLLED"
             and event.actor_id == LEFT and event.source_definition_id.endswith(".weapon.gong_jian")]
    assert len(rolls) == 2
    assert not any("gong_jian" in group["source_definition_id"] for group in table.state(match_id)["menu"]["actions"])
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_weapon_delivered_technique_spends_stock_and_exhausts(tmp_path, monkeypatch):
    import combat.ext.ammunition as ammunition

    monkeypatch.setitem(ammunition._PIECES_PER_UNIT, ARROWS, 1)
    talents = ["TAL_LIGHTNING_THUNDER_ARROW", "TAL_LIGHTNING_THOUSAND_SPARK_VOLLEY"]
    combat, table, match_id = table_fight(tmp_path, talents, cl=11, kit=kit(ammo=ARROWS))
    technique = next(row for row in combat._load_session(match_id).engine.action_catalog.values()
                     if "thousand_spark_volley" in row.source_definition_id.lower())
    answer_action(table, match_id, "THOUSAND_SPARK_VOLLEY")
    loaded = combat._load_session(match_id)
    assert any(event.event_type == "ATTACK_ROLLED" and event.source_definition_id == technique.source_definition_id
               for event in loaded.engine.events)
    assert not any("thousand_spark_volley" in group["source_definition_id"].lower()
                   for group in table.state(match_id)["menu"]["actions"])
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_ai_turn_spends_tracked_ammunition(tmp_path, monkeypatch):
    import combat.ext.ammunition as ammunition

    monkeypatch.setitem(ammunition._PIECES_PER_UNIT, ARROWS, 3)
    control = {LEFT: "MANUAL", ALLY: "LOCAL_AUTO", RIGHT: "MANUAL"}
    kits = {"ally": kit(ammo=ARROWS)}
    combat, table, match_id = table_fight(tmp_path, [], cl=11, kits=kits, control_modes=control)
    state = table.state(match_id)
    from tests.test_lock2_persistence import act
    assert act(table, match_id, "end")["status"] == "COMMITTED"
    state = table.state(match_id)
    if state["menu"].get("control_mode") == "LOCAL_AUTO":
        from combat.gate4_adapters import ManualControllerAdapter
        real_controller = combat.controller

        class AmmoController:
            def choose_primary_action(self, context):
                attack = next(candidate for candidate in context.legal_candidates
                              if candidate.source_definition_id.endswith(".weapon.gong_jian"))
                return ManualControllerAdapter(lambda _context: (attack.candidate_id, ())).choose_primary_action(context)

            def __getattr__(self, name):
                return getattr(real_controller, name)

        combat.controller = AmmoController()
        result = table.auto_step(match_id, state["last_sequence"])
        assert result["status"] == "COMMITTED"
    loaded = combat._load_session(match_id)
    rolls = [event for event in loaded.engine.events if event.event_type == "ATTACK_ROLLED"
             and event.actor_id == ALLY]
    assert rolls
    assert any(key.startswith("_round_ammunition_spent:" + ARROWS + ":")
               for key in loaded.engine.state.actors[ALLY].turn_flags)
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_dropping_spent_stack_between_turns_keeps_fresh_stack_available(tmp_path, monkeypatch):
    import combat.ext.ammunition as ammunition
    from tests.test_lock2_persistence import act

    monkeypatch.setitem(ammunition._PIECES_PER_UNIT, ARROWS, 1)
    two_stacks = {"starting_kit": {"items": [
        {"item_id": BOW, "quantity": 1},
        {"item_id": ARROWS, "name": "First arrows", "quantity": 1},
        {"item_id": ARROWS, "name": "Second arrows", "quantity": 1},
    ]}}
    combat, table, match_id = table_fight(tmp_path, [], kit=two_stacks)
    answer_action(table, match_id, ".weapon.gong_jian")
    assert act(table, match_id, "end")["status"] == "COMMITTED"
    while table.state(match_id)["menu"]["actor_id"] != LEFT:
        assert act(table, match_id, "end")["status"] == "COMMITTED"
    loaded = combat._load_session(match_id)
    actor = loaded.engine.state.actors[LEFT]
    spent = next(key.rsplit(":", 1)[1] for key in actor.turn_flags
                 if key.startswith("_round_ammunition_spent:" + ARROWS + ":"))
    drop_action = next(row for row in loaded.engine.action_catalog.values()
                       if row.owner_id == LEFT and row.parameters.get("item_action") == "drop"
                       and row.parameters.get("item_key") == spent)
    state = table.state(match_id)
    menu_group = next(group for group in state["menu"]["actions"]
                      if group["source_definition_id"] == drop_action.source_definition_id)
    result = table.act(match_id, menu_group["options"][0]["candidate_id"], state["menu"]["decision_id"],
                       state["menu"]["state_version"], state["last_sequence"], [])
    assert result["status"] == "COMMITTED"
    loaded = combat._load_session(match_id)
    assert _stock(loaded.engine, loaded.engine.state.actors[LEFT], {"item_id": ARROWS, "tracked": True}) == 1
    assert any("gong_jian" in group["source_definition_id"] for group in table.state(match_id)["menu"]["actions"])
    assert loaded.mechanical.replay()["status"] == "PASS"
