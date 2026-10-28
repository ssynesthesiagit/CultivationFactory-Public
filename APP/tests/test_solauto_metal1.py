"""Synthetic Metal clauses through compilation, table commit and cold replay."""
import pytest

from combat.ext import forged_exhaustion
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.typed_executor import check_mode
from tests import auto_worker1_support as H

FAN = "TAL_METAL_HUNDRED_NEEDLES_FAN"
BODY = "TAL_METAL_NINEFOLD_ADAMANT_BODY"
BONE = "TAL_METAL_IRON_BONE_INTERNAL_METHOD"
STOCK = "resource:named.metal_scrap_pouches"
STATE = "condition:typed.ninefold_adamant_body"


def cold(c, m):
    before = c._load_session(m).engine.state.model_dump(mode="json")
    c = CombatService(H.ROOT, c.userdata_root)
    session = c._load_session(m)
    assert session.engine.state.model_dump(mode="json") == before
    assert session.verify()["status"] == "PASS"
    assert session.mechanical.replay()["status"] == "PASS"
    return c, TabletopService(c, c.userdata_root), session.engine


def send(t, m, source, *, target=H.RIGHT, destination=None, option=None):
    def act(answers):
        session = t.combat._load_session(m)
        e = session.engine
        candidates = []
        for candidate in e.legal_candidates():
            action = e.action_catalog.get(candidate.source_definition_id)
            typed = (action.parameters or {}).get("typed") or {} if action else {}
            if typed.get("source") != source or (option is not None and typed.get("option") != option):
                continue
            if target is not None and target not in candidate.target_ids:
                # Cone/line activations select an aim cell rather than an entity.
                if candidate.destination != e.state.actors[target].position:
                    continue
            if destination is not None and (candidate.destination is None or
                    (candidate.destination.x, candidate.destination.y) != destination):
                continue
            candidates.append(candidate)
        assert candidates, (source, option)
        candidate = candidates[0]
        state = t.state(m)
        menu = state["menu"]
        return t.act(m, candidate.candidate_id, menu["decision_id"], menu["state_version"],
                     state["last_sequence"], answers)
    return act


def picks(p):
    source = p["context"]["reaction_source_id"]
    if source == "choice:needle.metal_fan_scrap":
        return ["scatter"]
    if source == "choice:needle.rider_targets":
        return [H.RIGHT]
    if source == "choice:needle.ninefold_vent":
        return ["resource:core.qi"]
    if source == "choice:needle.ninefold_counter":
        return ["counter"]
    return [p["choice"]["options"][0]["id"]]


def stock_sheet(count):
    def edit(doc, aid):
        if aid == H.LEFT:
            doc.setdefault("equipment", []).append({"metal_scrap_pouches": count})
    return edit


@pytest.mark.parametrize("success", [False, True])
def test_fan_consumes_real_stock_and_adds_pb_before_halving(tmp_path, success):
    results = []
    for scatter in (False, True):
        c, t, m = H.fight(tmp_path / str(scatter), [FAN], sheet_edit=stock_sheet(1),
                          left_save_dc=-100 if success else 100)
        def choose(p):
            if p["context"]["reaction_source_id"] == "choice:needle.metal_fan_scrap" and not scatter:
                return []
            return picks(p)
        H.settle(send(t, m, FAN), choose)
        c, t, e = cold(c, m)
        results.append(1000 - e.state.actors[H.RIGHT].current_hp)
        assert e.state.actors[H.LEFT].resources[STOCK] == (0 if scatter else 1)
        saves = [v for v in e.events if v.event_type == "SAVE_ROLLED"]
        assert saves and all(v.payload["success"] == success for v in saves)
        if scatter:
            H.turn(t, m, H.RIGHT)
            H.turn(t, m, H.LEFT)
            _, prompts = H.settle(send(t, m, FAN), picks)
            assert not any(p["context"]["reaction_source_id"] == "choice:needle.metal_fan_scrap"
                           for p in prompts)
            assert cold(c, m)[2].state.actors[H.LEFT].resources[STOCK] == 0
    assert results[1] - results[0] == (2 if success else 4)


def test_fan_without_recorded_material_has_no_material_choice(tmp_path):
    c, t, m = H.fight(tmp_path, [FAN])
    _, prompts = H.settle(send(t, m, FAN), picks)
    assert not any(p["context"]["reaction_source_id"] == "choice:needle.metal_fan_scrap"
                   for p in prompts)
    assert STOCK not in cold(c, m)[2].state.actors[H.LEFT].resources


@pytest.mark.parametrize("accept,pool", [(True, "Qi"), (True, "Stamina"), (False, "Qi")])
def test_ninefold_end_cost_is_optional_and_replayed_once(tmp_path, accept, pool):
    c, t, m = H.fight(tmp_path, [BODY], maximum_rounds=20, left_resource=pool)
    H.settle(send(t, m, BODY, target=None), picks)
    c, t, e = cold(c, m)
    owner = e.state.actors[H.LEFT]
    assert any(v.condition_id == STATE for v in owner.conditions.values())
    assert owner.resources["resource:core." + pool.lower()] == 92
    prompts = []
    def ending(p):
        prompts.append(p)
        if p["context"]["reaction_source_id"] == "choice:needle.ninefold_vent":
            return ["resource:core." + pool.lower()] if accept else []
        return picks(p)
    for _ in range(24):
        H.settle(lambda answers: H.act(t, m, "end", answers), ending)
        if not any(v.condition_id == STATE for v in c._load_session(m).engine.state.actors[H.LEFT].conditions.values()):
            break
    c, t, e = cold(c, m)
    owner = e.state.actors[H.LEFT]
    assert not any(v.condition_id == STATE for v in owner.conditions.values())
    assert len([p for p in prompts if p["context"]["reaction_source_id"] == "choice:needle.ninefold_vent"]) == 1
    assert owner.resources["resource:core." + pool.lower()] == (90 if accept else 92)
    assert forged_exhaustion.level(owner) == (0 if accept else 1)


@pytest.mark.parametrize("profile,accept", [
    ("cultivation_melee", True), ("cultivation_melee", False), ("cultivation_ranged", True)])
def test_ninefold_melee_counter_is_optional_paid_and_cold_replayable(tmp_path, profile, accept):
    c, t, m = H.fight(tmp_path, [BODY],
        cause=[{"type": "attack", "attack_kind": profile, "first_roll_bonus": 50, "on_hit": [
            {"type": "damage", "flat": 20, "damage_types": ["slashing"]}]}],
        cause_save_dc=100)
    H.settle(send(t, m, BODY, target=None), picks)
    H.turn(t, m, H.RIGHT)
    def choose(p):
        if p["context"]["reaction_source_id"] == "choice:needle.ninefold_counter" and not accept:
            return []
        return picks(p)
    _, prompts = H.settle(lambda answers: H.act(t, m, "Cause", answers, target_id=H.LEFT), choose)
    _, _, e = cold(c, m)
    melee = profile == "cultivation_melee"
    assert any(p["context"]["reaction_source_id"] == "choice:needle.ninefold_counter" for p in prompts) == melee
    assert e.state.actors[H.LEFT].reaction_available == (not (melee and accept))
    # The synthetic attacker also has its ordinary weapon-damage packet.
    assert e.state.actors[H.LEFT].current_hp == 988
    assert e.state.actors[H.RIGHT].current_hp == (994 if melee and accept else 1000)
    uses = [v for v in e.events if v.event_type == "REACTION_WINDOW_OPENED"]
    assert len(uses) == int(melee and accept)


def test_ninefold_strength_and_constitution_saves_not_dexterity(tmp_path):
    c, t, m = H.fight(tmp_path, [BODY], cause=[
        {"type": "save", "ability": a, "on_fail": [], "on_success": []}
        for a in ("str", "con", "dex")])
    H.settle(send(t, m, BODY, target=None), picks)
    H.turn(t, m, H.RIGHT)
    H.settle(lambda answers: H.act(t, m, "Cause", answers, target_id=H.LEFT), picks)
    _, _, e = cold(c, m)
    assert [v.payload["mode"] for v in e.events if v.event_type == "SAVE_ROLLED"] == [
        "ADVANTAGE", "ADVANTAGE", "NORMAL"]


def test_iron_bone_scoped_checks_already_cover_forced_movement_and_prone(tmp_path):
    c, t, m = H.fight(tmp_path, [BONE])
    # Select the published variant by its typed option index, not its prose.
    e = c._load_session(m).engine
    variants = [a for a in e.action_catalog.values()
                if ((a.parameters or {}).get("typed") or {}).get("source") == BONE]
    variant = next(a for a in variants if "check_against" in str(a.parameters))
    def act(answers):
        state = t.state(m)
        candidate = next(c for c in c_engine().legal_candidates()
                         if c.source_definition_id == variant.source_definition_id)
        menu = state["menu"]
        return t.act(m, candidate.candidate_id, menu["decision_id"], menu["state_version"],
                     state["last_sequence"], answers)
    def c_engine():
        return c._load_session(m).engine
    H.settle(act, picks)
    _, _, e = cold(c, m)
    actor = e.state.actors[H.LEFT]
    for ability in ("STR", "CON"):
        for hazard in ("forced_movement", "prone", "grappled", "restrained"):
            assert check_mode(actor, ability, engine=e, hazards=(hazard,)) == "ADVANTAGE"
    assert check_mode(actor, "DEX", engine=e, hazards=("prone",)) == "NORMAL"
    assert check_mode(actor, "STR", engine=e) == "NORMAL"
    import json
    authority = json.loads((H.ROOT / "authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_text())
    assert not authority["mechanics"][BONE]["riders"]


@pytest.mark.parametrize("active,expected", [(False, 4), (True, 8)])
def test_ninefold_doubles_only_active_sharpen_damage(tmp_path, active, expected):
    needle = "TAL_METAL_NEEDLE_FLICK"
    c, t, m = H.fight(tmp_path, [BODY, needle, "METAL_BASE_SHARPEN", "METAL_BASE_WEIGHT"],
                      spheres=("tianxia.sphere.metal",), left_attack_bonus=100)
    if active:
        H.settle(send(t, m, BODY, target=None), picks)
    H.settle(send(t, m, needle), picks)
    _, _, e = cold(c, m)
    packets = [v for v in e.events if v.event_type == "DAMAGE_COMMITTED"
               and v.payload.get("display_source_id") == "passive:METAL_BASE_SHARPEN"]
    assert len(packets) == 1
    assert packets[0].payload["rolled_or_pending_damage"] == expected


def test_ninefold_without_ending_resources_gains_exhaustion_without_a_choice(tmp_path):
    c, t, m = H.fight(tmp_path, [BODY], maximum_rounds=20,
        prepare=[{"type": "spend_resource", "resource_id": "resource:core.qi",
                  "flat": 92, "applies_to": "self"}], prepare_target="SELF")
    H.settle(send(t, m, BODY, target=None), picks)
    H.settle(lambda answers: H.act(t, m, "Prepare", answers), picks)
    prompts = []
    for _ in range(24):
        _, asked = H.settle(lambda answers: H.act(t, m, "end", answers), picks)
        prompts.extend(asked)
        if not any(v.condition_id == STATE for v in c._load_session(m).engine.state.actors[H.LEFT].conditions.values()):
            break
    _, _, e = cold(c, m)
    assert e.state.actors[H.LEFT].resources["resource:core.qi"] == 0
    assert forged_exhaustion.level(e.state.actors[H.LEFT]) == 1
    assert not any(p["context"]["reaction_source_id"] == "choice:needle.ninefold_vent" for p in prompts)


def test_suppressing_ninefold_does_not_erase_its_ending_pressure(tmp_path):
    c, t, m = H.fight(tmp_path, [BODY], maximum_rounds=20,
        cause=[{"type": "end_effect", "applies_to": "target",
                "conditions": ["ninefold_adamant_body"], "select": "beneficial",
                "on_success": "suppress", "success_rounds": 12}])
    H.settle(send(t, m, BODY, target=None), picks)
    H.turn(t, m, H.RIGHT)
    H.settle(lambda answers: H.act(t, m, "Cause", answers, target_id=H.LEFT), picks)
    c, t, e = cold(c, m)
    actor = e.state.actors[H.LEFT]
    assert not any(v.condition_id == STATE for v in actor.conditions.values())
    assert any(v.condition_id == "condition:typed.suppressed.ninefold_adamant_body"
               for v in actor.conditions.values())
    assert any(v.condition_id == "condition:typed.ninefold_adamant_pressure"
               for v in actor.conditions.values())
    prompts = []
    for _ in range(24):
        _, asked = H.settle(lambda answers: H.act(t, m, "end", answers), picks)
        prompts.extend(asked)
        if any(p["context"]["reaction_source_id"] == "choice:needle.ninefold_vent" for p in prompts):
            break
    _, _, e = cold(c, m)
    assert e.state.actors[H.LEFT].resources["resource:core.qi"] == 90
    assert forged_exhaustion.level(e.state.actors[H.LEFT]) == 0
    assert len([p for p in prompts if p["context"]["reaction_source_id"] == "choice:needle.ninefold_vent"]) == 1
