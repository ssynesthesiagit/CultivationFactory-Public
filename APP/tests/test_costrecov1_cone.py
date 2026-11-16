"""Cone of Death uses chosen ordinary weapon strikes, not a bulk projectile cost."""
import json
from pathlib import Path
from types import SimpleNamespace
import zipfile

import pytest

from combat import ext
from combat.ext import ammunition
from combat.gate5_service import CombatService, CombatServiceError, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService, TabletopError

ROOT = Path(__file__).resolve().parents[1]
CONE = "TAL_BARRAGE_CONE_OF_DEATH"
BOW = "tianxia.mortal.weapon.gong_jian"
DAGGER = "tianxia.mortal.weapon.bi_shou"
ARROWS = "tianxia.mortal.gear.arrows_20"
BOLTS = "tianxia.mortal.gear.bolts_20"
FOCUS = "resource:core.martial_focus"
WHEEL = "tianxia.subpath.qi.samsara_wheel_cultivator.feature.wheel_turns_once"
NAMES = ("archer", "ally", "foe", "omitted", "outside")
ME, ALLY, FOE, OMITTED, OUTSIDE = [FACTORY_ACTOR_PREFIX + name for name in NAMES]


def owner_sheet(name, *, weapon=BOW, stock=1, thrown=2, ac=1, talents=()):
    owner = name == "archer"
    items = [{"item_id": weapon, "quantity": thrown if weapon == DAGGER else 1}]
    if stock is not None:
        items.append({"item_id": ARROWS, "quantity": stock})
    # Unrelated stock must never pay for an arrow or a physical thrown copy.
    items.append({"item_id": BOLTS, "quantity": 4})
    return {
        "identity": {"display_name": name.title(), "cultivation_level": 11,
                     "proficiency_bonus": 4, "path": "Qi Cultivation", "key_ability": "CON"},
        "ability_scores_and_statistics": {
            "abilities": [{"ability": ability, "score": 18 if ability == "DEX" else 10,
                          "modifier": 4 if ability == "DEX" else 0}
                         for ability in ("STR", "DEX", "CON", "INT", "WIS", "CHA")],
            "primary_resource": {"name": "Qi", "maximum": 30},
            "armor_class": {"base_value": 14 if owner else ac},
            "hit_points": {"maximum": 1000}, "speed": {"walking_ft": 30},
            "technique_save_dc": 12, "technique_attack_bonus": 3},
        "equipment": [{"starting_kit": {"items": items}}] if owner else [],
        "spheres_and_talents": {
            "sphere_record_ids": ["tianxia.sphere.barrage"] if owner else [],
            "learned_talent_record_ids": [CONE, "TAL_BARRAGE_SPINNING_SHOT", *talents] if owner else []},
        "path_and_subpath": {"path_feature_record_ids": [WHEEL] if owner and WHEEL in talents else []},
    }


def fight(tmp_path, monkeypatch, *, pieces=2, weapon=BOW, stock=1, thrown=2, ac=1,
          talents=(), starts=None, ask=False):
    # A synthetic two-piece quiver makes exact affordability observable without
    # editing a saved fight or depending on private character data.
    monkeypatch.setitem(ammunition._PIECES_PER_UNIT, ARROWS, pieces)
    ext.effects()
    def fixed_attack(engine, request, intent):
        if request.get("actor_id") == ME and CONE.lower() in str(request.get("reason") or "").lower():
            return {"source_id": "test:cone-die", "natural_result": 19}
    monkeypatch.setitem(ext._HOOKS, "before_d20", [*ext._HOOKS.get("before_d20", []), fixed_attack])
    for name in NAMES:
        folder = tmp_path / "portable_characters" / name
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json",
                json.dumps(owner_sheet(name, weapon=weapon, stock=stock, thrown=thrown, ac=ac, talents=talents)))
    if ask:
        from combat.tabletop import ButtonStore
        ButtonStore(tmp_path / "tabletop_buttons").save_reactions("archer", {"mode": "ask"}, {"opportunity_attack"})
    combat = CombatService(ROOT, tmp_path)
    combat.tabletop_maps.save({"display_name": "Cone yard", "width_squares": 20, "height_squares": 16,
        "walls": [], "starts": starts or {"team1": [[3, 8], [5, 7]], "team2": [[5, 8], [6, 9], [2, 8]]}})
    mid = combat.create_factory_match(project_ids=["archer", "ally"], opponent_actor_ids=[FOE, OMITTED, OUTSIDE],
        control_modes={key: "MANUAL" for key in (ME, ALLY, FOE, OMITTED, OUTSIDE)},
        arena_id="battlefield:map.cone-yard", match_seed="COSTRECOV1-CONE")["match_id"]
    table = TabletopService(combat, tmp_path)
    for _ in range(10):
        state = table.state(mid)
        if state["menu"]["actor_id"] == ME:
            break
        assert table.act(mid, state["menu"]["end_turn"], state["menu"]["decision_id"],
            state["menu"]["state_version"], state["last_sequence"], [])["status"] == "COMMITTED"
    else:
        pytest.fail("Archer never received its turn")
    return combat, table, mid


def load(tmp_path, mid):
    return CombatService(ROOT, tmp_path)._load_session(mid)


def cone(engine):
    return next(row for row in engine.action_catalog.values()
                if row.owner_id == ME and (row.parameters.get("typed") or {}).get("source") == CONE)


def candidate(combat, mid):
    engine = combat._load_session(mid).engine
    action = cone(engine)
    return next(row for row in engine.legal_candidates()
                if row.source_definition_id == action.source_definition_id
                and row.destination is not None and (row.destination.x, row.destination.y) == (9, 8))


def send(table, mid, choice, answers=()):
    state = table.state(mid)
    return table.act(mid, choice.candidate_id, state["menu"]["decision_id"],
                     state["menu"]["state_version"], state["last_sequence"], list(answers))


def finish(table, mid, choice, result, selected):
    answers = []
    for _ in range(16):
        if result["status"] == "COMMITTED":
            return result
        assert result["status"] == "REACTION_REQUIRED", result
        prompt = result["reaction"]
        area = prompt["context"]["reaction_source_id"] == "choice:needle.area_recipients"
        answers.append({**prompt["context"], "selection": "USE",
                        **({"option_ids": selected} if area else {})})
        result = send(table, mid, choice, answers)
    pytest.fail("Too many choices")


def rolls(engine):
    source = cone(engine).source_definition_id
    return [event for event in engine.events if event.event_type == "ATTACK_ROLLED"
            and event.actor_id == ME and event.source_definition_id == source]


def spent(engine, item=ARROWS):
    return sum(value for key, value in engine.state.actors[ME].turn_flags.items()
               if key.startswith("_round_ammunition_spent:" + item + ":"))


def test_cone_of_death_reviewed_row_has_no_manual_projectile_clause():
    row = json.loads((ROOT / "authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_text())["mechanics"][CONE]
    assert row["typing_status"] == "reviewed_final"
    assert row["riders"] == ["Cone of Death is a Volley, not a Barrage."]
    assert [effect["type"] for effect in row["effects"]] == ["rider_choose_area_recipients", "attack"]
    assert row["area"]["printed_recipient_seal"]["chosen"] is True
    assert set(row["area"]["printed_recipient_seal"]["payload_scopes"].values()) == {"all"}
    assert row["effects"][0]["weapon_stock_per_target"] is True


def test_cone_of_death_chosen_creatures_receive_separate_weapon_attacks(tmp_path, monkeypatch):
    combat, table, mid = fight(tmp_path, monkeypatch)
    before = load(tmp_path, mid)
    action = cone(before.engine)
    weapon = before.engine.action_catalog[action.parameters["typed"]["delivered_by"]]
    assert action.target_kind == "CELL" and action.radius_ft == 30
    assert action.costs == ((FOCUS, 1),) and action.economy.value == "ACTION"
    assert action.parameters["typed"]["weapon"] == weapon.parameters["typed"]["weapon"]
    assert action.parameters["typed"]["numbers"]["attack_bonus"] == weapon.parameters["typed"]["numbers"]["attack_bonus"]
    assert action.range_ft == weapon.range_ft
    choice = candidate(combat, mid)
    result = send(table, mid, choice)
    assert result["status"] == "REACTION_REQUIRED", result
    paused = load(tmp_path, mid)
    assert paused.engine.state.model_dump(mode="json") == before.engine.state.model_dump(mode="json")
    assert not rolls(paused.engine) and spent(paused.engine) == 0
    finish(table, mid, choice, result, [FOE, OMITTED])
    loaded = load(tmp_path, mid)
    assert [event.target_ids for event in rolls(loaded.engine)] == [(FOE,), (OMITTED,)]
    damage = [event for event in loaded.engine.events if event.event_type == "DAMAGE_COMMITTED"
              and event.source_definition_id == action.source_definition_id]
    assert {event.target_ids for event in damage} == {(FOE,), (OMITTED,)}
    die = weapon.parameters["typed"]["weapon"]["damage"]
    assert all(die["modifier"] + die["count"] <= event.payload["hp_damage"]
               <= die["modifier"] + 2 * die["count"] * die["sides"] for event in damage)
    actor = loaded.engine.state.actors[ME]
    assert actor.resources[FOCUS] == before.engine.state.actors[ME].resources[FOCUS] - 1
    assert actor.action_available is False
    payments = [e for e in loaded.engine.events if e.event_type == "RESOURCE_SPENT"
                and e.source_definition_id == action.source_definition_id and e.payload.get("resource_id") == FOCUS]
    assert len(payments) == 1
    assert not loaded.engine.state.zones
    assert not actor.turn_flags.get("barrage_sequences")
    assert not any(e.event_type == "RESOURCE_GAINED" and e.payload.get("resource_id") == FOCUS
                   and e.source_definition_id == action.source_definition_id for e in loaded.engine.events)
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_cone_of_death_can_choose_ally_and_omit_enemy(tmp_path, monkeypatch):
    combat, table, mid = fight(tmp_path, monkeypatch, ask=True)
    choice = candidate(combat, mid)
    result = send(table, mid, choice)
    prompt = result["reaction"]
    offered = {row["id"] for row in prompt["choice"]["options"]}
    assert offered == {ALLY, FOE, OMITTED}
    assert "Cone of Death" in prompt["moment"] and "Ally" in prompt["moment"]
    assert "Martial Focus" in prompt["moment"]
    finish(table, mid, choice, result, [ALLY, FOE])
    loaded = load(tmp_path, mid)
    assert [e.target_ids for e in rolls(loaded.engine)] == [(ALLY,), (FOE,)]
    assert loaded.engine.state.actors[OMITTED].current_hp == 1000
    assert loaded.engine.state.actors[OUTSIDE].current_hp == 1000
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("ac", [1, 100])
def test_cone_of_death_pays_one_delivery_projectile_per_target(tmp_path, monkeypatch, ac):
    combat, table, mid = fight(tmp_path, monkeypatch, ac=ac, pieces=5)
    choice = candidate(combat, mid)
    finish(table, mid, choice, send(table, mid, choice), [FOE, OMITTED])
    loaded = load(tmp_path, mid)
    assert len(rolls(loaded.engine)) == 2
    assert spent(loaded.engine) == 2 and spent(loaded.engine, BOLTS) == 0
    if ac == 100:
        assert any(e.payload["natural_result"] != 20 for e in rolls(loaded.engine))
    assert ammunition.delivery_stock(loaded.engine, loaded.engine.state.actors[ME], cone(loaded.engine)) == 3
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_cone_of_death_does_not_double_charge_stock(tmp_path, monkeypatch):
    combat, table, mid = fight(tmp_path, monkeypatch)
    choice = candidate(combat, mid)
    finish(table, mid, choice, send(table, mid, choice), [FOE, OMITTED])
    loaded = load(tmp_path, mid)
    assert len(rolls(loaded.engine)) == 2 and spent(loaded.engine) == 2
    assert ammunition.delivery_stock(loaded.engine, loaded.engine.state.actors[ME], cone(loaded.engine)) == 0
    assert not any("spend_projectiles" == e.get("type") for e in cone(loaded.engine).parameters["typed"]["effects"])
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_cone_of_death_two_held_thrown_copies_land_at_their_chosen_targets(tmp_path, monkeypatch):
    combat, table, mid = fight(tmp_path, monkeypatch, weapon=DAGGER, stock=0)
    choice = candidate(combat, mid)
    result = send(table, mid, choice)
    assert result["reaction"]["choice"]["maximum"] == 2
    finish(table, mid, choice, result, [FOE, OMITTED])
    loaded = load(tmp_path, mid)
    assert [e.target_ids for e in rolls(loaded.engine)] == [(FOE,), (OMITTED,)]
    dropped = [c.data for c in loaded.engine.state.actors[ME].conditions.values() if c.data.get("dropped_at")]
    assert len(dropped) == 2 and len({row["disables_action"] for row in dropped}) == 2
    assert {tuple(sorted(row["dropped_at"].items())) for row in dropped} == {
        tuple(sorted(loaded.engine.state.actors[key].position.model_dump(mode="json").items())) for key in (FOE, OMITTED)}
    assert spent(loaded.engine) == spent(loaded.engine, BOLTS) == 0
    assert ammunition.delivery_stock(loaded.engine, loaded.engine.state.actors[ME], cone(loaded.engine)) == 0
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("copies", [0, 1])
def test_cone_of_death_cannot_substitute_unrelated_stock_for_held_thrown_copies(tmp_path, monkeypatch, copies):
    combat, table, mid = fight(tmp_path, monkeypatch, weapon=DAGGER, thrown=copies)
    if not copies:
        assert not any((a.parameters.get("typed") or {}).get("source") == CONE
                       for a in load(tmp_path, mid).engine.action_catalog.values())
        return
    choice = candidate(combat, mid)
    result = send(table, mid, choice)
    assert result["reaction"]["choice"]["maximum"] == 1
    finish(table, mid, choice, result, [FOE])
    loaded = load(tmp_path, mid)
    assert [e.target_ids for e in rolls(loaded.engine)] == [(FOE,)]
    assert spent(loaded.engine) == spent(loaded.engine, BOLTS) == 0
    assert ammunition.delivery_stock(loaded.engine, loaded.engine.state.actors[ME], cone(loaded.engine)) == 0
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("stock,maximum", [(None, 3), (0, None), (1, 1)])
def test_cone_of_death_stock_policy_bounds_the_chosen_set(tmp_path, monkeypatch, stock, maximum):
    combat, table, mid = fight(tmp_path, monkeypatch, pieces=1, stock=stock)
    if stock == 0:
        action = cone(load(tmp_path, mid).engine)
        assert not any(c.source_definition_id == action.source_definition_id
                       for c in combat._load_session(mid).engine.legal_candidates())
        assert not rolls(load(tmp_path, mid).engine)
        return
    choice = candidate(combat, mid)
    result = send(table, mid, choice)
    assert result["reaction"]["choice"]["maximum"] == maximum
    finish(table, mid, choice, result, [FOE] if stock == 1 else [FOE, OMITTED])
    loaded = load(tmp_path, mid)
    assert len(rolls(loaded.engine)) == (1 if stock == 1 else 2)
    assert spent(loaded.engine) == (1 if stock == 1 else 0)
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_cone_of_death_rechecks_full_stock_before_activation_payment(tmp_path, monkeypatch):
    combat, table, mid = fight(tmp_path, monkeypatch)
    choice = candidate(combat, mid)
    result = send(table, mid, choice)
    before = load(tmp_path, mid).engine.state.model_dump(mode="json")
    ext.effects()
    def other_shot(engine, actor, action, candidate, intent):
        if (action.parameters.get("typed") or {}).get("source") == CONE:
            ammunition.spend_unrolled_projectile(SimpleNamespace(engine=engine, actor=actor, action=action,
                                                                 typed=action.parameters["typed"]))
    monkeypatch.setitem(ext._HOOKS, "technique_declared", [*ext._HOOKS.get("technique_declared", []), other_shot])
    answer = {**result["reaction"]["context"], "selection": "USE", "option_ids": [FOE, OMITTED]}
    with pytest.raises((TabletopError, CombatServiceError, ValueError), match="not enough projectiles"):
        send(table, mid, choice, [answer])
    loaded = load(tmp_path, mid)
    assert loaded.engine.state.model_dump(mode="json") == before
    assert not rolls(loaded.engine) and spent(loaded.engine) == 0


def test_cone_of_death_reroll_does_not_pay_another_projectile(tmp_path, monkeypatch):
    combat, table, mid = fight(tmp_path, monkeypatch, ac=100, talents=[WHEEL])
    choice = candidate(combat, mid)
    finish(table, mid, choice, send(table, mid, choice), [FOE, OMITTED])
    loaded = load(tmp_path, mid)
    assert any(e.event_type == "D20_REWRITTEN" and e.source_definition_id == WHEEL for e in loaded.engine.events)
    assert len(rolls(loaded.engine)) == 2
    assert spent(loaded.engine) == 2
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_cone_of_death_ai_selects_an_affordable_hostile_subset(tmp_path, monkeypatch):
    from combat.gate4_adapters import ManualControllerAdapter
    combat, table, mid = fight(tmp_path, monkeypatch, ask=True)
    real = combat.controller
    class ConeController:
        def choose_primary_action(self, context):
            selected = next(c for c in context.legal_candidates
                if CONE.lower() in c.source_definition_id.lower() and c.destination is not None
                and (c.destination.x, c.destination.y) == (9, 8))
            return ManualControllerAdapter(lambda _context: (selected.candidate_id, ())).choose_primary_action(context)
        def __getattr__(self, name):
            return getattr(real, name)
    combat.controller = ConeController()
    combat.set_controller_mode(mid, actor_id=ME, controller_mode="LOCAL_AUTO")
    result = table.auto_step(mid, table.state(mid)["last_sequence"], [])
    assert result["status"] == "COMMITTED", result
    loaded = load(tmp_path, mid)
    assert {e.target_ids for e in rolls(loaded.engine)} == {(FOE,), (OMITTED,)}
    assert spent(loaded.engine) == 2
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_cone_of_death_geometry_and_weapon_long_range_both_apply(tmp_path, monkeypatch):
    # A dagger's normal range is shorter than the cone. The far target is
    # inside both long range and the cone, while the rear target is outside.
    combat, table, mid = fight(tmp_path, monkeypatch, weapon=DAGGER,
        starts={"team1": [[3, 8], [5, 7]], "team2": [[8, 8], [10, 8], [2, 8]]})
    choice = candidate(combat, mid)
    result = send(table, mid, choice)
    offered = {row["id"] for row in result["reaction"]["choice"]["options"]}
    assert offered == {ALLY, FOE}
    finish(table, mid, choice, result, [FOE])
    loaded = load(tmp_path, mid)
    (roll,) = rolls(loaded.engine)
    assert roll.target_ids == (FOE,) and roll.payload["mode"] == "DISADVANTAGE"
    assert loaded.mechanical.replay()["status"] == "PASS"
