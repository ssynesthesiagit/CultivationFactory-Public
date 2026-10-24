"""SOL176: accepted table choices, automatic controllers, cold reload and replay."""
import json

import pytest

from combat.gate2_runtime_models import Position
from combat.gate4_context import build_decision_context
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.ext.teleport_steps import destinations
from combat.ext.subject_repositioning import physical_routes
from combat.ext.needle import cell_id
from combat.falling import can_occupy
from tests.h1_support import ROOT
from tests.test_tabletop_hunt6 import table_fight, LEFT, ALLY, RIGHT
from tests.r10_fixup_support import fixed_dice
from tests.test_friendly_fire_area_table import _commit_area_action

DISPLACE = "tianxia.talent.space.spatial_displacement"
GAP = "TAL_VOID_COLLAPSING_GAP"


def send(table, mid, cid, answers=()):
    state = table.state(mid)
    menu = state["menu"]
    return table.act(mid, cid, menu["decision_id"], menu["state_version"], state["last_sequence"], list(answers))


def automatic_action(combat, mid, label, *, target=None, destination=None):
    """Bound primary scenario; real LocalDeterministicController owns every rider choice."""
    session = combat._load_session(mid)
    policy, _ = combat.policies.for_actor(LEFT)
    context = build_decision_context(session.engine, policy, for_ai=True)
    # This test binds the triggering primary; it does not evaluate primary-action
    # ranking or whether the stock pilot exposes every complex player menu.
    candidate = next(c for c in session.engine.legal_candidates() if c.display_name.startswith(label)
                     and (target is None or target in c.target_ids)
                     and (destination is None or c.destination == destination))
    choice = combat.controller.choose_primary_action(context.model_copy(update={"legal_candidates": (candidate,)}))
    session.execute_controller_choice(choice, controller=combat.controller, policy_library=combat.policies)
    return {"status": "COMMITTED"}


@pytest.mark.parametrize("natural", [1, 20])
@pytest.mark.parametrize("cl", [10, 15])
@pytest.mark.parametrize("mode", ["MANUAL", "LOCAL_AUTO"])
def test_target_displacement_chooses_and_moves_only_subject_after_reload(tmp_path, monkeypatch, natural, cl, mode):
    combat, table, mid = table_fight(tmp_path, [DISPLACE], cl=cl, ally_talents=[],
                                   control_modes={LEFT: mode, ALLY: "MANUAL", RIGHT: "MANUAL"})
    engine = combat._load_session(mid).engine
    actor, subject = engine.state.actors[LEFT], engine.state.actors[RIGHT]
    start, caster_start = subject.position, actor.position
    budgets = {a.entity_id: a.movement_remaining_ft for a in (actor, subject)}
    reach = 5 if natural == 20 else 30 if cl >= 15 else 20
    cells = destinations(engine, subject, reach, viewer=actor, include_altitude=True)
    if natural == 20:
        routes = physical_routes(engine, subject, cells, reach)
        cells = [cell for cell in cells if (cell.x, cell.y, cell.z) in routes]
    legal = {cell_id(cell) for cell in cells}
    assert legal
    # A non-flyer's menu holds only squares it can occupy: ground, or a surface it stands on.
    assert all(can_occupy(engine, subject, cell) for cell in cells)
    assert all(cell.z == 0 for cell in cells)
    fixed_dice(monkeypatch, [natural] * 80)
    if mode == "LOCAL_AUTO":
        result = automatic_action(combat, mid, "Spatial Displacement", target=RIGHT)
    else:
        group = next(g for g in table.state(mid)["menu"]["actions"] if g["label"] == "Spatial Displacement")
        option = next(o for o in group["options"] if RIGHT in o["target_ids"])
        result = send(table, mid, option["candidate_id"])
    answers, seen = [], []
    wanted = sorted(legal)[-1]
    for _ in range(12):
        if result["status"] == "COMMITTED":
            break
        assert result["status"] == "REACTION_REQUIRED", result
        prompt = result["reaction"]
        if prompt["context"]["reaction_source_id"] == "choice:needle.subject_destination":
            seen.append(prompt)
            assert {o["id"] for o in prompt["choice"]["options"]} == legal
            assert "Spatial Displacement" in prompt["moment"] and "Right" in prompt["moment"]
            assert prompt["context"]["reactor_id"] == LEFT
            answers.append({**prompt["context"], "selection": "USE", "option_ids": [wanted]})
        else:
            answers.append({**prompt["context"], "selection": "DECLINE"})
        # Reload even while the choice is pending: the rollback must keep costs
        # and all creature positions intact until a complete accepted action.
        fresh = CombatService(ROOT, tmp_path)
        assert fresh._load_session(mid).engine.state.actors[RIGHT].position == start
        table = TabletopService(fresh, tmp_path)
        result = send(table, mid, option["candidate_id"], answers)
    assert result["status"] == "COMMITTED", result
    assert len(seen) == (1 if mode == "MANUAL" else 0)
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    actor, subject = loaded.engine.state.actors[LEFT], loaded.engine.state.actors[RIGHT]
    assert subject.position != start
    assert cell_id(subject.position) in legal
    assert subject.position.z == 0
    if mode == "MANUAL":
        assert cell_id(subject.position) == wanted
    assert actor.position == caster_start
    assert {a.entity_id: a.movement_remaining_ft for a in (actor, subject)} == budgets
    assert not actor.turn_flags.get("oa_free_ft") and not subject.turn_flags.get("oa_free_ft")
    movements = [e for e in loaded.engine.events if e.event_type == "MOVEMENT_COMMITTED" and DISPLACE in (e.source_definition_id or "")]
    assert len(movements) == 1 and movements[0].actor_id == RIGHT
    assert movements[0].payload.get("teleport", False) is (natural == 1)
    assert movements[0].payload["cost_ft"] == 0
    assert not any(e.event_type == "REACTION_RESOLVED" and "opportunity" in (e.source_definition_id or "") for e in loaded.engine.events)
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("mode", ["MANUAL", "LOCAL_AUTO"])
@pytest.mark.parametrize("ability,label,aim", [
    (GAP, "Collapsing Gap", True),
    ("tianxia.talent.gravity.singularity_seed", "Singularity Seed", True),
    ("TAL_METAL_BELL_OF_SHATTERED_WEAPONS", "Bell of Shattered Weapons", True),
    ("tianxia.talent.illusion.consensus_lie", "Consensus Lie", True),
    ("TAL_ALCHEMY_CHOKING_SMOKE_PELLET", "Choking Smoke Pellet", True),
    ("TAL_MONKEY_STYLE_HEAVEN_UPROOTING_STAFF", "Heaven-Uprooting Staff", False),
    ("TAL_WATER_HEAVEN_FALLING_TSUNAMI", "Heaven-Falling Tsunami", True),
    ("tianxia.path.spirit_awakening.feature.domain_pressure", "Domain Pressure", True),
    ("TAL_SCOUNDREL_STRIP_THE_BATTLEFIELD_BARE", "STRIP THE BATTLEFIELD BARE", False),
    ("tianxia.talent.radiance.first_dawn_before_falsehood", "First Dawn Before Falsehood", False),
    ("tianxia.talent.gravity.local_down", "Local Down", True),
])
def test_chosen_area_recipients_commit_reload_and_spare_friends(tmp_path, mode, ability, label, aim):
    combat, table, mid = table_fight(tmp_path, [ability], ally_talents=[], cl=20,
                                   primary="Resonance" if "spirit_awakening" in ability else "Qi",
                                   control_modes={LEFT: mode, ALLY: "MANUAL", RIGHT: "MANUAL"})
    before = {a.entity_id: a.current_hp for a in combat._load_session(mid).engine.state.actors.values()}
    if mode == "LOCAL_AUTO":
        result = automatic_action(combat, mid, label, destination=Position(x=4, y=4) if aim else None)
    else:
        # Setup toggles named "Choose <ability>: ..." are separate buttons.
        group = next(g for g in table.state(mid)["menu"]["actions"] if g["label"].startswith(label))
        option = (next(o for o in group["options"] if o.get("destination") == {"x": 4, "y": 4})
                  if aim else group["options"][0])
        result = send(table, mid, option["candidate_id"])
    answers, choices = [], []
    for _ in range(20):
        if result["status"] == "COMMITTED":
            break
        assert result["status"] == "REACTION_REQUIRED", result
        prompt = result["reaction"]
        if prompt["context"]["reaction_source_id"] == "choice:needle.area_recipients":
            choices.append(prompt)
            assert RIGHT in {o["id"] for o in prompt["choice"]["options"]}
            answers.append({**prompt["context"], "selection": "USE", "option_ids": [RIGHT]})
        else:
            choice = prompt.get("choice") or {}
            if choice and not choice.get("allow_decline"):
                minimum = int(choice.get("minimum") or 1)
                preferred = choice.get("preferred") or [row["id"] for row in choice["options"]]
                answers.append({**prompt["context"], "selection": "USE", "option_ids": preferred[:minimum]})
            else:
                answers.append({**prompt["context"], "selection": "DECLINE"})
        table = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
        result = send(table, mid, option["candidate_id"], answers)
    assert result["status"] == "COMMITTED", result
    assert len(choices) == (1 if mode == "MANUAL" else 0), [p["moment"] for p in choices]
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    saves = {e.actor_id for e in loaded.engine.events if e.event_type == "SAVE_ROLLED" and ability in (e.source_definition_id or "")}
    assert saves == {RIGHT}
    assert all(loaded.engine.state.actors[who].current_hp == before[who] for who in (LEFT, ALLY))
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"


def test_reviewed_cast_area_choices_have_selector():
    ids = [GAP, "TAL_METAL_BELL_OF_SHATTERED_WEAPONS", "TAL_ALCHEMY_CHOKING_SMOKE_PELLET",
           "TAL_MONKEY_STYLE_HEAVEN_UPROOTING_STAFF", "TAL_WATER_TIDAL_WAVE", "TAL_WATER_HEAVEN_FALLING_TSUNAMI",
           "tianxia.talent.gravity.singularity_seed", "tianxia.talent.illusion.consensus_lie",
           "tianxia.path.spirit_awakening.feature.domain_pressure", "TAL_SCOUNDREL_STRIP_THE_BATTLEFIELD_BARE",
           "tianxia.talent.radiance.first_dawn_before_falsehood", "tianxia.talent.gravity.local_down"]
    mechanics = json.loads((ROOT / "authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_text())["mechanics"]
    for ability in ids:
        assert "rider_choose_area_recipients" in json.dumps(mechanics[ability]), ability


def test_bob_and_weave_plain_player_text():
    reviewed = json.loads((ROOT / "authority/typed_mechanics/reviewed_final.d/auto11_scoundrel.json").read_text())
    text = " ".join(reviewed["mechanics"]["TAL_SCOUNDREL_BOB_AND_WEAVE"]["riders"])
    assert "Half Cover" in text and "start of your next turn" in text and "no longer adjacent" in text
    assert "Returning beside it does not restore" in text
    assert "the table reads" not in text and "live condition" not in text


@pytest.mark.parametrize("level,size", [(5, 15), (11, 30), (17, 60)])
def test_chosen_scaled_area_is_sealed_for_compilation(level, size):
    from combat.factory_compiler import compile_character
    from tests.h1_support import sheet
    ability = "tianxia.path.spirit_awakening.feature.domain_pressure"
    bundle = compile_character(sheet([ability], cl=level), actor_id=LEFT)
    action = next(a for a in bundle["action_catalog"] if a["display_name"] == "Domain Pressure")
    assert action["target_kind"] == "CELL" and action["range_ft"] == size
    assert action["parameters"]["typed"]["area"]["size_ft"] == size


def test_subject_landing_uses_its_footprint_and_casters_sight(tmp_path):
    combat, table, mid = table_fight(tmp_path, [DISPLACE], ally_talents=[])
    engine = combat._load_session(mid).engine
    caster, subject = engine.state.actors[LEFT], engine.state.actors[RIGHT]
    subject.transformed_size_category = "Large"
    engine._apply_condition(subject, "condition:typed.blinded", "test:blind", LEFT, expires_on="UNTIL_REMOVED")
    cells = destinations(engine, subject, 20, viewer=caster)
    assert cells  # the moved subject's blindness does not blind its controller
    assert not destinations(engine, subject, 20)
    assert all(engine.grid.placement_legal(cell, footprint=engine._footprint(subject),
               occupied_cells=engine._occupied_cells_except(RIGHT)) for cell in cells)
    assert Position(x=11, y=4) not in cells  # a 2x2 footprint would leave the map
    engine._apply_condition(caster, "condition:typed.blinded", "test:blind", RIGHT, expires_on="UNTIL_REMOVED")
    assert not destinations(engine, subject, 20, viewer=caster)


def test_successful_displacement_does_not_protect_casters_next_walk(tmp_path, monkeypatch):
    combat, table, mid = table_fight(tmp_path, [DISPLACE], ally_talents=[])
    fixed_dice(monkeypatch, [20] * 80)
    group = next(g for g in table.state(mid)["menu"]["actions"] if g["label"] == "Spatial Displacement")
    option = next(o for o in group["options"] if RIGHT in o["target_ids"])
    result = send(table, mid, option["candidate_id"])
    assert result["status"] == "REACTION_REQUIRED"
    prompt = result["reaction"]
    assert prompt["context"]["reaction_source_id"] == "choice:needle.subject_destination"
    answer = {**prompt["context"], "selection": "USE", "option_ids": ["cell:4,3"]}
    assert send(table, mid, option["candidate_id"], [answer])["status"] == "COMMITTED"
    table = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    move = next(m for m in table.state(mid)["menu"]["moves"] if m["destination"] == {"x": 1, "y": 4})
    result = send(table, mid, move["candidate_id"])
    assert result["status"] == "COMMITTED", result["status"]
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert any(e.event_type == "ATTACK_ROLLED" and e.actor_id == RIGHT and LEFT in e.target_ids
               and "opportunity_attack" in (e.source_definition_id or "") for e in loaded.engine.events)
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"


def test_subject_teleport_gate_uses_subjects_own_check_numbers(tmp_path):
    from combat.typed_executor import Context, teleport_subject
    from combat.ext.ability_source import numbers_of
    from combat.ext.void_riders import PRISONED
    combat, table, mid = table_fight(tmp_path, [DISPLACE], ally_talents=[])
    engine = combat._load_session(mid).engine
    caster, subject = engine.state.actors[LEFT], engine.state.actors[RIGHT]
    action = next(a for a in engine.action_catalog.values() if a.owner_id == LEFT and a.display_name == "Spatial Displacement")
    engine._apply_condition(subject, PRISONED, "test:prison", LEFT, expires_on="UNTIL_REMOVED", data={"dc": 100})
    typed = {**action.parameters["typed"], "numbers": {"pb": 100, "key_mod": 100}}
    ctx = Context(engine, caster, action, None, typed, [subject], subject, {})
    start = subject.position
    teleport_subject(ctx, subject, Position(x=4, y=3))
    assert subject.position == start
    check = next(e for e in reversed(engine.events) if e.event_type == "CHECK_ROLLED")
    personal = numbers_of(engine, subject)
    assert check.actor_id == RIGHT and check.payload["success"] is False
    assert check.payload["actor"]["modifier"] == int(personal.get("pb") or 0) + int(personal.get("key_mod") or 0)


def test_bob_cover_ends_on_leaving_and_does_not_return_after_commit_reload(tmp_path):
    combat, table, mid = table_fight(tmp_path, ["TAL_SCOUNDREL_BOB_AND_WEAVE"], ally_talents=[])
    menu = table.state(mid)["menu"]
    group = next(g for g in menu["actions"] if g["label"].casefold() == "bob and weave")
    cid = group["options"][0]["candidate_id"]
    answers = []
    for _ in range(12):
        result = send(table, mid, cid, answers)
        if result["status"] == "COMMITTED":
            break
        assert result["status"] == "REACTION_REQUIRED", result
        prompt = result["reaction"]
        suffix = prompt["context"]["reaction_source_id"].rsplit(".", 1)[-1]
        wanted = {"bob_and_weave": ALLY, "bob_and_weave_willing": "accept", "bob_and_weave_covers": "yes"}[suffix]
        answers.append({**prompt["context"], "selection": "USE", "option_ids": [wanted]})
    assert result["status"] == "COMMITTED"
    from combat.ext.scoundrel_riders import ANCHOR
    actor = CombatService(ROOT, tmp_path)._load_session(mid).engine.state.actors[LEFT]
    assert any(c.condition_id == ANCHOR for c in actor.conditions.values())
    for x, y in [(1, 4), (3, 4)]:
        move = next(m for m in table.state(mid)["menu"]["moves"] if m["destination"] == {"x": x, "y": y})
        result = send(table, mid, move["candidate_id"])
        answers = []
        for _ in range(12):
            if result["status"] == "COMMITTED":
                break
            assert result["status"] == "REACTION_REQUIRED", result
            answers.append({**result["reaction"]["context"], "selection": "DECLINE"})
            result = send(table, mid, move["candidate_id"], answers)
        assert result["status"] == "COMMITTED", result
        fresh = CombatService(ROOT, tmp_path)
        actor = fresh._load_session(mid).engine.state.actors[LEFT]
        assert not any(c.condition_id == ANCHOR for c in actor.conditions.values())
        table = TabletopService(fresh, tmp_path)
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"
