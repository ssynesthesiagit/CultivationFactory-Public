"""F29R2: printed Bone-Still Archer and Tidal Body benefits reach the saved table.

All characters, prerequisite effects and stores are synthetic. No model servers,
private records, history reads or browser processes are used.
"""
from types import SimpleNamespace

import pytest

from combat.ext import br_variants as bv
from combat.typed_executor import check_mode
from tests.auto_worker1_support import (
    LEFT, RIGHT, act, action_sender, fight, reload, resolve, settle, turn,
)
from tests.body_refining_support import BODY
from tests.test_body_refining_zone_riders import _area, _world

SNIPER = "tianxia.sphere.sniper"
WATER = "tianxia.sphere.water"
BOW = {"items": [{"item_id": "tianxia.mortal.weapon.gong_jian",
                  "name": "Gong Jian (Bow and Arrow)", "quantity": 1}]}
BONE_CHOICE = "choice:br_variant.br_choice_bone_still"
TIDAL_CHOICE = "choice:br_variant.br_choice_tidal_body"


def body(doc, aid):
    if aid == LEFT:
        doc["identity"]["path_ids"] = [BODY]


def held(engine, cid):
    return [c for c in engine.state.actors[LEFT].conditions.values() if c.condition_id == cid]


def shot_label(combat, mid):
    engine = combat._load_session(mid).engine
    return next(c.display_name for c in engine.legal_candidates()
                if c.display_name.startswith("Snipe Shot:")
                and RIGHT in c.target_ids)


def archer(tmp_path, *, moved=0, owner=True, score=18, disadvantage=False):
    def edit(bundle):
        for action in bundle["action_catalog"]:
            if action["display_name"].startswith("Snipe Shot:"):
                # Repeat the real compiled shot without turn economy to prove the
                # rider is once per turn and Prone removal belongs to one roll.
                action["economy"] = "NONE"
                action["parameters"]["free_primary"] = True
                if disadvantage:
                    action["parameters"]["typed"]["disadvantage"] = True
            if action["display_name"] in {"Hold Sniper", "Hold Water"}:
                action["parameters"]["typed"]["duration"] = {"kind": "minutes", "amount": 1, "concentration": True}

    combat, table, mid = fight(
        tmp_path, ["TAL_SNIPER_SNIPER_TRAINING", "TAL_SNIPER_DEADLY_SHOT"], cl=4,
        left_kit=BOW, spheres=[SNIPER], sheet_edit=body if owner else None, left_score=score,
        positions={LEFT: {"x": 3, "y": 6}, RIGHT: {"x": 6, "y": 6}},
        prepare=[{"type": "condition", "condition": "prone", "applies_to": "self"}],
        bundle_edit=edit,
        extra_actions=[("Hold Sniper", {"sphere": SNIPER}), ("Hold Water", {"sphere": WATER}),
                       ("Chip", {"effects": [{"type": "damage", "flat": 1,
                                             "damage_type": "FORCE", "applies_to": "self"}]})])
    if moved:
        from tests.auto_worker1_support import cell_send
        resolve(cell_send(table, mid, "Move", (3, 6 + moved // 5)))
    resolve(lambda answers: act(table, mid, "Prepare", answers, target_id=RIGHT))
    return combat, table, mid


@pytest.mark.parametrize("pick", ["temp_hp", "prone", "brace", "concentration"])
def test_bone_still_archer_offers_all_four_benefits_before_the_saved_snipe(tmp_path, pick):
    combat, table, mid = archer(tmp_path)
    start = len(combat._load_session(mid).engine.events)
    _, prompts = resolve(action_sender(combat, table, mid, shot_label(combat, mid), target_id=RIGHT),
                         {BONE_CHOICE: [pick]})
    choices = [p for p in prompts if p["context"]["reaction_source_id"] == BONE_CHOICE]
    assert len(choices) == 1
    assert [o["id"] for o in choices[0]["choice"]["options"]] == ["temp_hp", "prone", "brace", "concentration"]
    prompt = choices[0]["moment"]
    assert "Bone-Still Archer" in prompt and "Snipe Shot" in prompt and "Keeper" in prompt
    assert "against Visitor" in prompt and "against Keeper" not in prompt
    engine = reload(combat, mid)
    attacks = [e for e in engine.events[start:] if e.event_type == "ATTACK_ROLLED" and e.actor_id == LEFT]
    assert attacks
    if pick == "temp_hp":
        assert engine.state.actors[LEFT].temporary_hp == 4
    elif pick == "prone":
        assert attacks[0].payload["mode"] == "NORMAL"
        assert attacks[0].payload["attack_mode_removed"] == ["DISADVANTAGE:prone"]
        assert any(c.condition_id.endswith(".prone") for c in engine.state.actors[LEFT].conditions.values())
    elif pick == "brace":
        assert held(engine, bv.FORCED_CONDITION)[0].data["feet"] == 10
        assert bv.rider_forced_movement(SimpleNamespace(engine=engine), engine.state.actors[LEFT]) == 10
    else:
        assert held(engine, bv.CONCENTRATION_CONDITION)[0].data["bonus"] == 4
    if pick == "prone":
        start = len(engine.events)
        _, again = resolve(action_sender(combat, table, mid, shot_label(combat, mid), target_id=RIGHT))
        engine = reload(combat, mid)
        assert not [p for p in again if p["context"]["reaction_source_id"] == BONE_CHOICE]
        second = next(e for e in engine.events[start:] if e.event_type == "ATTACK_ROLLED" and e.actor_id == LEFT)
        assert second.payload["mode"] == "DISADVANTAGE"
        assert not second.payload.get("attack_mode_removed")
    # All timed options end at the next start, not the end of this turn.
    turn(table, mid, RIGHT)
    turn(table, mid, LEFT)
    engine = reload(combat, mid)
    assert not held(engine, bv.FORCED_CONDITION) and not held(engine, bv.CONCENTRATION_CONDITION)


@pytest.mark.parametrize("moved,owner,asked", [(5, True, True), (10, True, False), (0, False, False)])
def test_archer_movement_limit_and_non_owner_neutrality(tmp_path, moved, owner, asked):
    combat, table, mid = archer(tmp_path, moved=moved, owner=owner)
    _, prompts = resolve(action_sender(combat, table, mid, shot_label(combat, mid), target_id=RIGHT))
    assert bool([p for p in prompts if p["context"]["reaction_source_id"] == BONE_CHOICE]) is asked
    reload(combat, mid)


@pytest.mark.parametrize("score,bonus", [(18, 4), (8, 1)])
def test_archer_concentration_bonus_is_sniper_only_consumed_once_and_cold_reloaded(tmp_path, score, bonus):
    combat, table, mid = archer(tmp_path, score=score)
    resolve(lambda answers: act(table, mid, "Hold Water", answers))
    resolve(action_sender(combat, table, mid, shot_label(combat, mid), target_id=RIGHT),
            {BONE_CHOICE: ["concentration"]})

    def chip():
        start = len(combat._load_session(mid).engine.events)
        resolve(lambda answers: act(table, mid, "Chip", answers))
        engine = reload(combat, mid)
        saves = [e for e in engine.events[start:] if e.event_type == "SAVE_ROLLED"
                 and e.source_definition_id == "system:combat.concentration"]
        assert saves
        return engine, saves[-1]

    engine, save = chip()
    assert held(engine, bv.CONCENTRATION_CONDITION), "a Water concentration save must not spend Sniper's bonus"
    assert not any(k.startswith("br_concentration:") for k in save.payload.get("save_bonus_contributions", {}))
    resolve(lambda answers: act(table, mid, "Hold Sniper", answers))
    engine, save = chip()
    assert list(v for k, v in save.payload["save_bonus_contributions"].items()
                if k.startswith("br_concentration:")) == [bonus]
    assert not held(engine, bv.CONCENTRATION_CONDITION)
    resolve(lambda answers: act(table, mid, "Hold Sniper", answers))
    engine, save = chip()
    assert not any(k.startswith("br_concentration:") for k in save.payload.get("save_bonus_contributions", {}))


def test_prone_choice_does_not_remove_another_attack_penalty(tmp_path):
    combat, table, mid = archer(tmp_path, disadvantage=True)
    resolve(action_sender(combat, table, mid, shot_label(combat, mid), target_id=RIGHT),
            {BONE_CHOICE: ["prone"]})
    engine = reload(combat, mid)
    attack = next(e for e in reversed(engine.events) if e.event_type == "ATTACK_ROLLED" and e.actor_id == LEFT)
    assert attack.payload["mode"] == "DISADVANTAGE"
    assert attack.payload["attack_mode_removed"] == ["DISADVANTAGE:prone"]


def test_ai_archer_answers_automatically_without_hiding_any_printed_choice(tmp_path):
    combat, table, mid = archer(tmp_path)
    _, prompts = resolve(action_sender(combat, table, mid, shot_label(combat, mid), ai=True, target_id=RIGHT))
    assert not [p for p in prompts if p["context"]["reaction_source_id"] == BONE_CHOICE]
    assert reload(combat, mid).state.actors[LEFT].temporary_hp == 4


SOAK = {"type": "mark", "mark": "Soaked", "applies_to": "self"}
PUSH_SAVE = {"type": "save", "ability": "STR", "applies_to": "self",
             "on_fail": [{"type": "forced_movement", "distance_ft": 5, "direction": "away"}],
             "on_success": []}


def tidal(tmp_path, *, enemy_soak=False):
    def extra_attack(bundle):
        # Synthetic Extra Attack: two real native Unarmed Strikes in this action.
        if bundle["actor_id"] == LEFT:
            for action in bundle["action_catalog"]:
                if action["source_definition_id"].endswith(".natural.unarmed_strike"):
                    action["parameters"]["typed"]["effects"][0]["count"] = 2
    return fight(tmp_path, spheres=[WATER], sheet_edit=body, left_kit={"items": []},
                 cl=5, left_score=18, bundle_edit=extra_attack,
                 prepare=[] if enemy_soak else [SOAK],
                 cause=[{**SOAK, "applies_to": "target"}] if enemy_soak else [],
                 extra_actions=[("Test Push Save", {"effects": [PUSH_SAVE]}),
                                ("Dry", {"effects": [{"type": "spend_mark", "mark": "Soaked", "applies_to": "self"}]})])


def choose_tidal(table, mid, pick):
    _, prompts = resolve(lambda answers: act(table, mid, "Tidal Body: choose benefit", answers),
                         {TIDAL_CHOICE: [pick]})
    choice = next(p for p in prompts if p["context"]["reaction_source_id"] == TIDAL_CHOICE)
    assert [o["id"] for o in choice["choice"]["options"]] == ["brace", "breath", "step"]
    return choice


def test_tidal_choice_is_exclusive_and_gates_checks_and_saves_after_reload(tmp_path):
    combat, table, mid = tidal(tmp_path)
    assert not any(c.display_name == "Tidal Body: choose benefit"
                   for c in combat._load_session(mid).engine.legal_candidates())
    _, prompts = resolve(lambda answers: act(table, mid, "Prepare", answers, target_id=RIGHT),
                         {TIDAL_CHOICE: ["brace"]})
    assert any(p["context"]["reaction_source_id"] == TIDAL_CHOICE for p in prompts)

    def verify(expected):
        engine = reload(combat, mid)
        me = engine.state.actors[LEFT]
        assert check_mode(me, "STR", "Athletics", engine=engine, hazards=("forced_movement",)) == expected
        assert check_mode(me, "STR", "Athletics", engine=engine, hazards=()) == "NORMAL"
        start = len(engine.events)
        resolve(lambda answers: act(table, mid, "Test Push Save", answers))
        engine = reload(combat, mid)
        save = next(e for e in engine.events[start:] if e.event_type == "SAVE_ROLLED" and e.actor_id == LEFT)
        assert save.payload["mode"] == expected

    verify("ADVANTAGE")
    verify("ADVANTAGE")  # continuous, not a one-save consumable
    choose_tidal(table, mid, "breath")
    verify("NORMAL")
    choose_tidal(table, mid, "brace")
    resolve(lambda answers: act(table, mid, "Dry", answers))
    verify("NORMAL")  # a saved selection never works while dry


def test_tidal_unarmed_step_moves_natively_once_per_turn_without_spending_movement(tmp_path):
    combat, table, mid = tidal(tmp_path)
    resolve(lambda answers: act(table, mid, "Prepare", answers, target_id=RIGHT),
            {TIDAL_CHOICE: ["step"]})
    before = reload(combat, mid).state.actors[LEFT]
    start = len(combat._load_session(mid).engine.events)
    def pick(prompt):
        options = [o["id"] for o in prompt.get("choice", {}).get("options", [])]
        if prompt["context"]["reaction_source_id"] == "choice:needle.rider_step":
            return ["cell:3,7"]  # stays adjacent; the two native attacks can both hit
        return options[:1]
    _, prompts = settle(action_sender(combat, table, mid, "Unarmed Strike", target_id=RIGHT), pick)
    steps = [p for p in prompts if p["context"]["reaction_source_id"] == "choice:needle.rider_step"]
    assert len(steps) == 1 and "Tidal Body" in steps[0]["moment"]
    engine = reload(combat, mid)
    me = engine.state.actors[LEFT]
    assert (me.position.x, me.position.y) == (3, 7)
    assert me.movement_remaining_ft == before.movement_remaining_ft
    assert engine.state.actors[RIGHT].reaction_available
    assert not [e for e in engine.events[start:] if e.event_type == "ATTACK_ROLLED"
                and e.actor_id == RIGHT and "opportunity" in e.source_definition_id]
    assert not any(c.condition_id == bv.SAVE_CONDITION for c in me.conditions.values())


def test_tidal_step_resolves_after_its_hit_before_the_next_extra_attack(tmp_path, monkeypatch):
    from tests.hunt12_support import hit_dice
    hit_dice(monkeypatch)
    combat, table, mid = tidal(tmp_path)
    resolve(lambda answers: act(table, mid, "Prepare", answers, target_id=RIGHT),
            {TIDAL_CHOICE: ["step"]})
    start = len(combat._load_session(mid).engine.events)
    resolve(action_sender(combat, table, mid, "Unarmed Strike", target_id=RIGHT),
            {"choice:needle.rider_step": ["cell:2,6"]})
    engine = reload(combat, mid)
    assert (engine.state.actors[LEFT].position.x, engine.state.actors[LEFT].position.y) == (2, 6)
    attacks = [e for e in engine.events[start:] if e.event_type == "ATTACK_ROLLED" and e.actor_id == LEFT]
    assert len(attacks) == 1, "stepping out of reach after the first hit prevents the later attack"
    assert engine.state.actors[RIGHT].reaction_available


def test_declining_tidal_step_keeps_the_option_for_a_later_hit_this_turn(tmp_path, monkeypatch):
    from tests.hunt12_support import hit_dice
    hit_dice(monkeypatch)
    combat, table, mid = tidal(tmp_path)
    resolve(lambda answers: act(table, mid, "Prepare", answers, target_id=RIGHT),
            {TIDAL_CHOICE: ["step"]})
    count = 0
    def pick(prompt):
        nonlocal count
        if prompt["context"]["reaction_source_id"] == "choice:needle.rider_step":
            count += 1
            return [] if count == 1 else ["cell:3,7"]
        return [o["id"] for o in prompt.get("choice", {}).get("options", [])][:1]
    settle(action_sender(combat, table, mid, "Unarmed Strike", target_id=RIGHT), pick)
    engine = reload(combat, mid)
    assert count == 2
    assert (engine.state.actors[LEFT].position.x, engine.state.actors[LEFT].position.y) == (3, 7)


def test_tidal_manual_owner_is_asked_when_soaked_on_an_ai_turn(tmp_path):
    combat, table, mid = tidal(tmp_path, enemy_soak=True)
    turn(table, mid, RIGHT)
    _, prompts = resolve(action_sender(combat, table, mid, "Cause", ai=True, target_id=LEFT),
                         {TIDAL_CHOICE: ["step"]})
    prompt = next(p for p in prompts if p["context"]["reaction_source_id"] == TIDAL_CHOICE)
    assert prompt["context"]["reactor_id"] == LEFT
    assert "Cause" in prompt["moment"] and "Keeper" in prompt["moment"]
    assert prompt["affected"] == "Keeper"
    assert held(reload(combat, mid), bv.STANCE_CONDITION)[0].data["option"] == "step"


def test_tidal_reselection_is_a_setting_for_ai_scoring_not_a_repeatable_combat_action(tmp_path):
    from combat.ext.ai_restraint import setting_history_key, free_setting_metadata
    from combat.ext.setting_choices import is_setting_action

    combat, table, mid = tidal(tmp_path)
    resolve(lambda answers: act(table, mid, "Prepare", answers, target_id=RIGHT))
    engine = reload(combat, mid)
    candidate = next(c for c in engine.legal_candidates() if c.display_name == "Tidal Body: choose benefit")
    action = engine.action_catalog[candidate.source_definition_id]
    assert is_setting_action(action)
    _, prompts = resolve(action_sender(combat, table, mid, candidate.display_name, ai=True))
    assert not [p for p in prompts if p["context"]["reaction_source_id"] == TIDAL_CHOICE]
    engine = reload(combat, mid)
    actor = engine.state.actors[LEFT]
    assert actor.turn_flags[setting_history_key(candidate)] == 1
    assert free_setting_metadata(actor, candidate, action) == {"ai_repeated_setting": 1}
    # Score a repeated declaration, never hide it from either seat's legal menu.
    assert any(c.source_definition_id == action.source_definition_id for c in engine.legal_candidates())


@pytest.mark.parametrize("owner", [True, False])
def test_tidal_gate_uses_real_owned_water_areas_not_air_or_another_owners_area(owner):
    engine, me, foe = _world(WATER)
    # The zone-kind owner reads the sealed Shape Current source, not a display name.
    from combat.gate2_runtime_models import ActionDefinition, EconomyKind
    source = "action:test.water"
    engine.action_catalog[source] = ActionDefinition(
        source_definition_id=source, display_name="Shape Current: Basin", owner_id=me.entity_id,
        economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind="SELF",
        parameters={"typed": {"source": "WATER_BASE_SHAPE_CURRENT"}})
    zone = _area(engine, me, "zone:test.water", {"name": "Basin"}, me if owner else foe)
    zone.source_definition_id = source
    rider = next(r for r in bv._riders(engine, me.entity_id, "choice") if r["trigger"] == "while")
    assert bv._rider_when(engine, me, rider, {}) is owner
    zone.source_definition_id = "action:test.air"
    assert not bv._rider_when(engine, me, rider, {})
