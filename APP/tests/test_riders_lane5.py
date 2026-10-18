"""Lane 5 of the riders push (owner 2026-09-29: "i want everything we can automated, keep going until its only the non-combat
ones left"): printed lines of partly automated abilities that were only shown to the GM as riders.  Each ability is compiled on a
real character and run through the engine; each test fails on the typing the authority carried before (no action, an effect with
no trigger, or a line that changed nothing).

Overrides: authority/typed_mechanics/reviewed_final.d/riders_lane5.json (+ edits in place in review_sw-water.json and
review_sw-smoke.json for entries already reviewed there); plug-ins: combat/ext/wax.py and sound*.py.
Saves are forced with the sheet's technique DC (16, or 50 where a
foe must fail), attacks always hit (foe AC -50).
"""

import json
from pathlib import Path

import pytest

from combat import ext, zones
from combat.factory_compiler import TYPED_AUTHORITY, compile_character
from tests import test_auto_lane1 as L1
from tests.test_auto_lane1 import ME, FOE, _engine, _held, _payloads, _use

ROOT = Path(__file__).resolve().parents[1]


def _mech():
    return L1._mechanics()


def _bundle(mids, **kw):
    """A character owning the sphere's base abilities and every talent in ``mids``."""
    sheet = L1._sheet(mids[0], **kw)
    sheet["spheres_and_talents"]["learned_talent_record_ids"] = list(mids)
    return compile_character(sheet, actor_id=ME)


def _melee_bundle(mids, **kw):
    sheet = L1._sheet(mids[0], **kw)
    sheet['spheres_and_talents']['learned_talent_record_ids'] = list(mids)
    sheet['path_and_subpath'] = {'path_record_ids': ['tianxia.path.body_refining']}
    sheet['equipment'] = [{'starting_kit': {'items': [
        {'item_id': 'tianxia.mortal.weapon.fu', 'name': 'Fu (Short Axe)', 'quantity': 1}]}}]
    return compile_character(sheet, actor_id=ME)


def _ready(engine):
    return L1._ready(engine)


def _names(engine):
    return {c.display_name for c in engine.legal_candidates()}


def _seal(engine, actor_id):
    return [c for c in engine.state.actors[actor_id].conditions.values() if c.condition_id == f"condition:typed.mark.wax_seal.{ME}"]


def _mark(actor, name):
    return [c for c in actor.conditions.values() if c.condition_id.startswith(f"condition:typed.mark.{name}.")]


def _place(engine, prefix, near):
    """A cell-targeted action's candidate at ``near`` (any cell when it has no such square)."""
    # Round 24 labels include altitude/movement details. Use the candidate's
    # coordinates rather than parsing its player-facing label.
    choices = [c for c in engine.legal_candidates() if c.display_name.startswith(prefix)]
    return min(choices, key=lambda c: (0 if c.destination is None else
               abs(c.destination.x - near.x) + abs(c.destination.y - near.y), c.display_name)).display_name


def _clarity_engine(*, legacy=False, pb=4):
    authority = json.loads(Path(TYPED_AUTHORITY).read_bytes()) if legacy else None
    if legacy:
        authority["mechanics"]["TAL_SOUND_BELL_OF_CLARITY"]["effects"][0].pop("choose_targets")
    sheet = L1._sheet("TAL_SOUND_BELL_OF_CLARITY")
    sheet["identity"]["proficiency_bonus"] = pb
    bundle = compile_character(sheet, actor_id=ME, typed_authority=authority)
    engine = _engine(bundle, allies=(L1._ally_bundle(),))
    for actor_id in (ME, L1.ALLY, FOE):
        engine._apply_condition(engine.state.actors[actor_id], "condition:typed.frightened", "test:fear", FOE,
                                expires_on="UNTIL_REMOVED", data={"origin_save": {"ability": "WIS", "dc": -40}})
    return engine


def _clarity_answers(engine, targets, *, save="first"):
    from combat.gate2_runtime_models import ReactionDecision
    requests = []

    def provider(request):
        requests.append(request)
        options = request["legal_option_ids"]
        chosen = targets if request["reaction_source_id"].endswith(".targets") else options[:1] if save == "first" else save
        return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
            reaction_source_id=request["reaction_source_id"], selection="DECLINE" if chosen is None else "USE",
            option_ids=tuple(chosen or ())), None

    engine.set_reaction_provider(provider)
    return requests


def test_clarity_caster_selects_only_the_chosen_creature_including_a_foe():
    engine = _clarity_engine()
    requests = _clarity_answers(engine, [FOE])
    me = engine.state.actors[ME]
    me.reaction_available = False
    events = _use(engine, "Bell of Clarity")
    assert _held(me, "condition:typed.frightened") and _held(engine.state.actors[L1.ALLY], "condition:typed.frightened")
    assert not _held(engine.state.actors[FOE], "condition:typed.frightened")
    assert len(_payloads(events, "SAVE_ROLLED")) == 1 and not me.reaction_available
    assert requests[0]["extension_choice"]["minimum_selections"] == 0
    assert requests[0]["extension_choice"]["maximum_selections"] == min(me.proficiency_bonus, 3)
    assert requests[1]["reactor_id"] == FOE
    assert all("Bell of Clarity" in r["choice_trigger"]["prompt"] for r in requests)


@pytest.mark.parametrize("targets", [[], None])
def test_clarity_up_to_pb_allows_zero_creatures_and_decline(targets):
    engine = _clarity_engine()
    requests = _clarity_answers(engine, targets)
    events = _use(engine, "Bell of Clarity")
    assert not _payloads(events, "SAVE_ROLLED") and len(requests) == 1
    assert all(_held(a, "condition:typed.frightened") for a in engine.state.actors.values())


def test_clarity_recipient_may_decline_without_rolling():
    engine = _clarity_engine()
    requests = _clarity_answers(engine, [L1.ALLY], save=None)
    events = _use(engine, "Bell of Clarity")
    assert len(requests) == 2 and not _payloads(events, "SAVE_ROLLED")
    assert _held(engine.state.actors[L1.ALLY], "condition:typed.frightened")


def test_clarity_recipient_chooses_one_effect_rather_than_the_easiest_save():
    engine = _clarity_engine()
    ally = engine.state.actors[L1.ALLY]
    engine._apply_condition(ally, "condition:typed.charmed", "test:charm", FOE, expires_on="UNTIL_REMOVED",
                            data={"origin_save": {"ability": "CHA", "dc": -30}})
    charm = _held(ally, "condition:typed.charmed")[0]
    _clarity_answers(engine, [L1.ALLY], save=[charm.instance_id])
    events = _use(engine, "Bell of Clarity")
    assert not _held(ally, "condition:typed.charmed") and _held(ally, "condition:typed.frightened")
    assert len(_payloads(events, "SAVE_ROLLED")) == 1


@pytest.mark.parametrize("invalid", [[ME, ME], ["invented"], [FOE]])
def test_clarity_rejects_duplicate_unknown_and_out_of_range_choices(invalid):
    from combat.gate2_runtime_models import Position
    engine = _clarity_engine()
    engine.state.actors[FOE].position = Position(x=15, y=9)
    _clarity_answers(engine, invalid)
    before = engine.state.model_dump(mode="json")
    with pytest.raises(ValueError, match="invalid extension choice"):
        _use(engine, "Bell of Clarity")
    assert engine.state.model_dump(mode="json") == before


def test_clarity_old_saved_typing_keeps_its_automatic_allies_only_path():
    engine = _clarity_engine(legacy=True)
    requests = _clarity_answers(engine, [FOE])
    events = _use(engine, "Bell of Clarity")
    assert not requests and len(_payloads(events, "SAVE_ROLLED")) == 2
    assert _held(engine.state.actors[FOE], "condition:typed.frightened")


def test_clarity_plain_engine_without_dynamic_transport_uses_the_safe_default():
    from combat.gate2_engine import Gate2Engine
    engine = Gate2Engine(ROOT, match_seed="R5-CLARITY-GATE2", typed_bundles=(_bundle(["TAL_SOUND_BELL_OF_CLARITY"]),),
        roster_setup={"primary_actor_ids": [ME, FOE], "team_by_actor": {ME: "team:a", FOE: "team:b"},
                      "starting_positions": {ME: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    me = engine.state.actors[ME]
    engine._apply_condition(me, "condition:typed.frightened", "test:fear", FOE, expires_on="UNTIL_REMOVED",
                            data={"origin_save": {"ability": "WIS", "dc": -40}})
    events = _use(engine, "Bell of Clarity")
    assert not _held(me, "condition:typed.frightened") and len(_payloads(events, "SAVE_ROLLED")) == 1


def test_clarity_rejects_more_than_pb_targets():
    engine = _clarity_engine(pb=2)
    _clarity_answers(engine, [ME, L1.ALLY, FOE])
    before = engine.state.model_dump(mode="json")
    with pytest.raises(ValueError, match="invalid extension choice"):
        _use(engine, "Bell of Clarity")
    assert engine.state.model_dump(mode="json") == before


def test_clarity_failed_chosen_repeat_keeps_both_effects():
    engine = _clarity_engine()
    ally = engine.state.actors[L1.ALLY]
    engine._apply_condition(ally, "condition:typed.charmed", "test:charm", FOE, expires_on="UNTIL_REMOVED",
                            data={"origin_save": {"ability": "CHA", "dc": 50}})
    _clarity_answers(engine, [L1.ALLY], save=[_held(ally, "condition:typed.charmed")[0].instance_id])
    events = _use(engine, "Bell of Clarity")
    assert _held(ally, "condition:typed.charmed") and _held(ally, "condition:typed.frightened")
    assert len(_payloads(events, "SAVE_ROLLED")) == 1


def test_bounded_table_choices_submit_option_ids_and_preserve_legacy_dialog():
    import subprocess
    result = subprocess.run(["node", str(Path(__file__).with_name("test_riders_lane5_choices.js"))],
                            cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def _clarity_intent(engine):
    from combat.gate2_runtime_models import ActionIntent
    candidate = next(c for c in engine.legal_candidates() if c.display_name == "Bell of Clarity")
    return ActionIntent(intent_id="test:clarity", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                        state_version=candidate.state_version, actor_id=candidate.actor_id, target_ids=candidate.target_ids)


def test_clarity_service_preview_asks_caster_then_recipient_and_carries_table_choices(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from combat.gate2_runtime_models import ReactionDecision
    from combat.gate5_service import CombatService, _ReactionRequired
    from combat.tabletop_service import TabletopService
    engine = _clarity_engine()
    service = CombatService(ROOT, tmp_path)
    session = SimpleNamespace(engine=engine, match_id=engine.state.match_id)
    metadata = {"participant_control_modes": {ME: "MANUAL", L1.ALLY: "MANUAL", FOE: "LOCAL_AUTO"}}
    intent = _clarity_intent(engine)
    before = engine.state.model_dump(mode="json")
    with pytest.raises(_ReactionRequired) as caster:
        service._run_preview(session, metadata, intent, ())
    assert caster.value.context.reactor_id == ME
    table = TabletopService(service, tmp_path)
    monkeypatch.setattr(table, "_names_for", lambda match_id: ({a.entity_id: a.display_name for a in engine.state.actors.values()}, {}))
    prompt = table._reaction_prompt(session.match_id, caster.value.context.model_dump(mode="json"), engine=engine)
    assert prompt["choice"]["minimum"] == 0
    assert L1.ALLY in [option["id"] for option in prompt["choice"]["options"]]
    assert "Bell of Clarity" in prompt["moment"]
    first = ReactionDecision(checkpoint=caster.value.context.checkpoint, reactor_id=ME,
                             reaction_source_id=caster.value.context.reaction_source_id, selection="USE", option_ids=(L1.ALLY,))
    with pytest.raises(_ReactionRequired) as recipient:
        service._run_preview(session, metadata, intent, (first,))
    assert recipient.value.context.reactor_id == L1.ALLY
    second = ReactionDecision(checkpoint=recipient.value.context.checkpoint, reactor_id=L1.ALLY,
                              reaction_source_id=recipient.value.context.reaction_source_id, selection="DECLINE")
    preview = service._run_preview(session, metadata, intent, (first, second))
    assert not any(e["event_type"] == "SAVE_ROLLED" for e in preview["events"])
    assert engine.state.model_dump(mode="json") == before


def test_clarity_ai_turn_asks_only_player_owned_ask_me_recipients(tmp_path):
    from types import SimpleNamespace
    from combat.gate2_runtime_models import ReactionDecision
    from combat.gate5_service import CombatService
    engine = _clarity_engine()
    engine.typed_ask_reactors = frozenset({L1.ALLY})
    service = CombatService(ROOT, tmp_path)
    session = SimpleNamespace(engine=engine, match_id=engine.state.match_id)
    choice = SimpleNamespace(intent=_clarity_intent(engine))
    before = engine.state.model_dump(mode="json")
    needed = service._ask_during_ai_step(session, choice, {})
    assert needed.context.reactor_id == L1.ALLY
    assert "Bell of Clarity" in needed.context.choice_trigger["prompt"]
    answer = ReactionDecision(checkpoint=needed.context.checkpoint, reactor_id=L1.ALLY,
                              reaction_source_id=needed.context.reaction_source_id, selection="DECLINE")
    key = (answer.checkpoint, answer.reactor_id, answer.reaction_source_id)
    assert service._ask_during_ai_step(session, choice, {key: answer}) is None
    assert engine.state.model_dump(mode="json") == before


def test_clarity_selected_repeat_save_survives_commit_and_reload(tmp_path):
    import copy
    from combat.canonical import canonical_sha256
    from combat.gate2_runtime_models import ActionIntent
    from combat.gate4_persistence import Gate4Persistence
    bundle = _bundle(["TAL_SOUND_BELL_OF_CLARITY"])
    seed = copy.deepcopy(next(a for a in bundle["action_catalog"] if a["display_name"] == "Bell of Clarity"))
    seed.update(source_definition_id="test:clarity_seed", display_name="Seed fear", economy="BONUS_ACTION")
    seed["costs"] = []
    seed["parameters"]["typed"]["effects"] = [{"type": "condition", "condition": "frightened", "applies_to": "target",
        "duration": {"kind": "until_removed"}, "repeat_save": {"ability": "WIS", "when": "end"}}]
    seed["parameters"]["typed"]["numbers"]["save_dc"] = -40
    bundle["action_catalog"].append(seed)
    bundle["actor_template"]["action_ids"].append(seed["source_definition_id"])
    bundle["bundle_sha256"] = canonical_sha256({k: v for k, v in bundle.items() if k != "bundle_sha256"})
    persistence = Gate4Persistence(ROOT, tmp_path)
    session = persistence.create_match(match_seed="R5-CLARITY-PERSIST", typed_bundles=(bundle, L1._ally_bundle()),
        roster_setup={"primary_actor_ids": [ME, L1.ALLY, FOE],
                      "team_by_actor": {ME: "team:a", L1.ALLY: "team:a", FOE: "team:b"},
                      "starting_positions": {ME: {"x": 3, "y": 6}, L1.ALLY: {"x": 3, "y": 7}, FOE: {"x": 4, "y": 6}}})

    def submit(name, target=None, provider=None):
        candidate = next(c for c in session.engine.legal_candidates() if c.display_name == name
                         and (target is None or target in c.target_ids))
        intent = ActionIntent(intent_id=f"clarity-{session.engine.state.state_version}", decision_id=candidate.decision_id,
            candidate_id=candidate.candidate_id, state_version=candidate.state_version, actor_id=candidate.actor_id,
            target_ids=candidate.target_ids)
        session.submit_intent(intent, primary_decision_record=None, reaction_provider=provider)

    while session.engine.state.current_actor_id != ME:
        submit("End turn")
    submit("Seed fear", L1.ALLY)
    session = persistence.load_match(session.match_id)
    assert _held(session.engine.state.actors[L1.ALLY], "condition:typed.frightened")
    requests = _clarity_answers(session.engine, [L1.ALLY])
    submit("Bell of Clarity", provider=session.engine._gate4_reaction_provider)
    assert len(requests) == 2
    session = persistence.load_match(session.match_id)
    assert not _held(session.engine.state.actors[L1.ALLY], "condition:typed.frightened")
    assert any(e.event_type == "CONDITION_REMOVED" and e.payload.get("bell_of_clarity") for e in session.engine.events)


# ----------------------------------------------------------------------------------------------------- Sound: Muffle Footfall


def _muffle_engine():
    return _engine(_bundle(["TAL_SOUND_MUFFLE_FOOTFALL"]), allies=(L1._ally_bundle(),))


def _muffle_answers(engine, target, consent="accept"):
    from combat.gate2_runtime_models import ReactionDecision
    requests = []

    def provider(request):
        requests.append(request)
        options = [target] if request["reaction_source_id"].endswith(".targets") else [consent]
        return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
            reaction_source_id=request["reaction_source_id"], selection="USE", option_ids=tuple(options)), None

    engine.set_reaction_provider(provider)
    return requests


@pytest.mark.parametrize("target", [ME, L1.ALLY, FOE])
def test_muffle_selects_exactly_one_willing_creature_including_self_and_foe(target):
    engine = _muffle_engine()
    requests = _muffle_answers(engine, target)
    _use(engine, "Muffle Footfall")
    for actor_id, actor in engine.state.actors.items():
        assert bool(_held(actor, "condition:typed.check_mode")) == (actor_id == target)
    assert len(requests) == (1 if target == ME else 2)
    assert all("Muffle Footfall" in r["choice_trigger"]["prompt"] for r in requests)
    if target != ME:
        assert requests[1]["reactor_id"] == target
        assert engine.state.actors[target].display_name in requests[1]["choice_trigger"]["prompt"]
    assert all(a.reaction_available for a in engine.state.actors.values())


def test_muffle_unwilling_recipient_gets_nothing():
    engine = _muffle_engine()
    requests = _muffle_answers(engine, L1.ALLY, "refuse")
    _use(engine, "Muffle Footfall")
    assert len(requests) == 2
    assert not any(_held(a, "condition:typed.check_mode") for a in engine.state.actors.values())


def test_muffle_30_foot_boundary_and_inactive_creatures():
    from combat.gate2_runtime_models import Position
    engine = _muffle_engine()
    engine.state.actors[FOE].position = Position(x=9, y=6)
    engine.state.actors[L1.ALLY].active = False
    engine.state.actors[L1.ALLY].action_available = False
    engine.state.actors[L1.ALLY].bonus_action_available = False
    requests = _muffle_answers(engine, FOE)
    _use(engine, "Muffle Footfall")
    assert FOE in requests[0]["legal_option_ids"]
    assert L1.ALLY not in requests[0]["legal_option_ids"]
    assert _held(engine.state.actors[FOE], "condition:typed.check_mode")


def test_muffle_ai_defaults_to_self_without_consent_or_reaction_spend():
    engine = _muffle_engine()
    _use(engine, "Muffle Footfall")
    assert _held(engine.state.actors[ME], "condition:typed.check_mode")
    assert not _held(engine.state.actors[L1.ALLY], "condition:typed.check_mode")
    assert engine.state.actors[ME].reaction_available


def test_muffle_old_saved_row_keeps_original_behavior_and_has_no_new_choices():
    authority = json.loads(Path(TYPED_AUTHORITY).read_bytes())
    row = authority["mechanics"]["TAL_SOUND_MUFFLE_FOOTFALL"]
    row["effects"] = row["effects"][0]["effects"]
    row["effects"][0]["applies_to"] = "ally"
    bundle = compile_character(L1._sheet("TAL_SOUND_MUFFLE_FOOTFALL"), actor_id=ME, typed_authority=authority)
    engine = _engine(bundle, allies=(L1._ally_bundle(),))
    requests = _muffle_answers(engine, FOE)
    _use(engine, "Muffle Footfall")
    assert not requests and _held(engine.state.actors[L1.ALLY], "condition:typed.check_mode")
    assert not _held(engine.state.actors[FOE], "condition:typed.check_mode")


@pytest.mark.parametrize("target", ["invented", FOE])
def test_muffle_rejects_unknown_or_beyond_30_feet_and_rolls_back(target):
    from combat.gate2_runtime_models import Position
    engine = _muffle_engine()
    engine.state.actors[FOE].position = Position(x=15, y=9)
    _muffle_answers(engine, target)
    before = engine.state.model_dump(mode="json")
    with pytest.raises(ValueError, match="invalid extension choice"):
        _use(engine, "Muffle Footfall")
    assert engine.state.model_dump(mode="json") == before


def _muffle_intent(engine):
    from combat.gate2_runtime_models import ActionIntent
    candidate = next(c for c in engine.legal_candidates() if c.display_name == "Muffle Footfall")
    return ActionIntent(intent_id="test:muffle", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                        state_version=candidate.state_version, actor_id=candidate.actor_id, target_ids=candidate.target_ids)


def test_muffle_service_preview_asks_caster_and_off_turn_recipient(tmp_path):
    from types import SimpleNamespace
    from combat.gate2_runtime_models import ReactionDecision
    from combat.gate5_service import CombatService, _ReactionRequired
    engine = _muffle_engine()
    service = CombatService(ROOT, tmp_path)
    session = SimpleNamespace(engine=engine, match_id=engine.state.match_id)
    metadata = {"participant_control_modes": {ME: "MANUAL", L1.ALLY: "MANUAL", FOE: "LOCAL_AUTO"}}
    intent = _muffle_intent(engine)
    before = engine.state.model_dump(mode="json")
    with pytest.raises(_ReactionRequired) as caster:
        service._run_preview(session, metadata, intent, ())
    first = ReactionDecision(checkpoint=caster.value.context.checkpoint, reactor_id=ME,
        reaction_source_id=caster.value.context.reaction_source_id, selection="USE", option_ids=(L1.ALLY,))
    with pytest.raises(_ReactionRequired) as recipient:
        service._run_preview(session, metadata, intent, (first,))
    assert recipient.value.context.reactor_id == L1.ALLY
    assert "Muffle Footfall" in recipient.value.context.choice_trigger["prompt"]
    second = ReactionDecision(checkpoint=recipient.value.context.checkpoint, reactor_id=L1.ALLY,
        reaction_source_id=recipient.value.context.reaction_source_id, selection="DECLINE")
    preview = service._run_preview(session, metadata, intent, (first, second))
    assert not any(e["event_type"] == "CONDITION_APPLIED" for e in preview["events"])
    assert engine.state.model_dump(mode="json") == before


def test_muffle_selected_recipient_survives_table_commit_and_reload(tmp_path):
    from combat.gate2_runtime_models import ActionIntent
    from combat.gate4_persistence import Gate4Persistence
    persistence = Gate4Persistence(ROOT, tmp_path)
    session = persistence.create_match(match_seed="R5-MUFFLE-PERSIST",
        typed_bundles=(_bundle(["TAL_SOUND_MUFFLE_FOOTFALL"]), L1._ally_bundle()),
        roster_setup={"primary_actor_ids": [ME, L1.ALLY, FOE],
                      "team_by_actor": {ME: "team:a", L1.ALLY: "team:a", FOE: "team:b"},
                      "starting_positions": {ME: {"x": 3, "y": 6}, L1.ALLY: {"x": 3, "y": 7}, FOE: {"x": 4, "y": 6}}})
    while session.engine.state.current_actor_id != ME:
        c = next(c for c in session.engine.legal_candidates() if c.display_name == "End turn")
        session.submit_intent(ActionIntent(intent_id=f"muffle-end-{c.state_version}", decision_id=c.decision_id,
            candidate_id=c.candidate_id, state_version=c.state_version, actor_id=c.actor_id, target_ids=c.target_ids),
            primary_decision_record=None, reaction_provider=None)
    _muffle_answers(session.engine, L1.ALLY)
    from combat.ext.effect_durations import round_token
    expiry = round_token(session.engine, 100)
    session.submit_intent(_muffle_intent(session.engine), primary_decision_record=None,
                          reaction_provider=session.engine._gate4_reaction_provider)
    loaded = persistence.load_match(session.match_id)
    assert _held(loaded.engine.state.actors[L1.ALLY], "condition:typed.check_mode")
    assert not _held(loaded.engine.state.actors[ME], "condition:typed.check_mode")
    condition = _held(loaded.engine.state.actors[L1.ALLY], "condition:typed.check_mode")[0]
    assert condition.expires_on == expiry


def test_muffle_ai_turn_preserves_player_ask_me_consent(tmp_path):
    from types import SimpleNamespace
    from combat.gate2_runtime_models import ReactionDecision
    from combat.gate5_service import CombatService
    engine = _muffle_engine()
    engine.typed_ask_reactors = frozenset({L1.ALLY})
    # An AI caster's already selected recipient; it must still ask the player.
    requests = _muffle_answers(engine, L1.ALLY)
    # Gather its deterministic target checkpoint, then use a fresh original.
    _use(engine, "Muffle Footfall")
    target_request = requests[0]
    engine = _muffle_engine()
    engine.typed_ask_reactors = frozenset({L1.ALLY})
    first = ReactionDecision(checkpoint=target_request["checkpoint"], reactor_id=ME,
        reaction_source_id=target_request["reaction_source_id"], selection="USE", option_ids=(L1.ALLY,))
    answers = {(first.checkpoint, first.reactor_id, first.reaction_source_id): first}
    service = CombatService(ROOT, tmp_path)
    session = SimpleNamespace(engine=engine, match_id=engine.state.match_id)
    choice = SimpleNamespace(intent=_muffle_intent(engine))
    before = engine.state.model_dump(mode="json")
    needed = service._ask_during_ai_step(session, choice, answers)
    assert needed.context.reactor_id == L1.ALLY
    answer = ReactionDecision(checkpoint=needed.context.checkpoint, reactor_id=L1.ALLY,
        reaction_source_id=needed.context.reaction_source_id, selection="DECLINE")
    answers[(answer.checkpoint, answer.reactor_id, answer.reaction_source_id)] = answer
    assert service._ask_during_ai_step(session, choice, answers) is None
    assert engine.state.model_dump(mode="json") == before



# ---------------------------------------------------------------------------------------------------------------- Wax


def test_soft_spread_marks_the_first_hostile_creature_each_round():
    """"The first hostile creature each round that enters the area or starts its turn there must succeed on a Dexterity saving
    throw or become impressed by the wax until the end of your next turn." -- it was a GM line; the zone had no trigger."""
    engine = _engine(_bundle(["TAL_WAX_ADHESIVE_POOL"], dc=50))
    foe = engine.state.actors[FOE]
    _use(engine, _place(engine, "Mold Wax: Soft Spread", foe.position))
    (zone,) = [z for z in zones.typed_zones(engine) if "TAL_WAX_MOLD_WAX" in z.source_definition_id]
    assert any(t.get("first_each_round") for t in zone.trigger_profile["triggers"])
    zones.on_turn_start(engine, foe)
    assert _mark(foe, "impressed")
    # only the first one each round: a second creature the same round is not asked (the once-per-round key is the area's)
    engine.state.actors[FOE].conditions.clear()
    zones.on_turn_start(engine, foe)
    assert not _mark(foe, "impressed")
    engine.state.round_number += 1
    zones.on_turn_start(engine, foe)
    assert _mark(foe, "impressed")


def test_adhesive_pool_stops_the_creature_and_reacts_to_being_knocked_prone():
    """"The first hostile creature each round that enters the area, starts its turn there, or is knocked Prone there must succeed
    on a Strength saving throw or have its Speed reduced to 0 until the start of its next turn"; "impressed by the wax"."""
    engine = _engine(_bundle(["TAL_WAX_ADHESIVE_POOL"], dc=50))
    foe = engine.state.actors[FOE]
    _use(engine, _place(engine, "Mold Wax: Soft Spread", foe.position))
    zones.on_turn_start(engine, foe)
    assert engine._effective_speed(foe) == 0 and _mark(foe, "impressed")
    # knocked Prone inside the wax, the next round: the same Strength save
    engine.state.round_number += 1
    foe.conditions.clear()
    foe.modifiers.clear()
    assert engine._effective_speed(foe) > 0
    engine._apply_condition(foe, "condition:typed.prone", "test", ME, expires_on=None)
    assert engine._effective_speed(foe) == 0


def test_soft_spread_grows_with_cultivation_level():
    """"At CL 5, your Soft Spread can cover a 15-foot square ... At CL 10 ... 20-foot ... At CL 15 ... 25-foot square"."""
    sizes = {}
    for cl in (1, 5, 10, 15):
        engine = _engine(_bundle(["TAL_WAX_ADHESIVE_POOL"], cl=cl))
        foe = engine.state.actors[FOE]
        _use(engine, _place(engine, "Mold Wax: Soft Spread", foe.position))
        (zone,) = [z for z in zones.typed_zones(engine) if "TAL_WAX_MOLD_WAX" in z.source_definition_id]
        sizes[cl] = zone.trigger_profile["size_ft"]
    assert sizes == {1: 10, 5: 15, 10: 20, 15: 25}


def test_press_seal_leaves_a_wax_seal_that_kindle_wax_burns():
    """Press Seal: "On a failure, the seal attaches."; Kindle Wax (Bonus Action, 0 CP): "You burn one ... Wax Seal ... The chosen
    wax is consumed.  Candleflare. One creature within 5 feet of the kindled wax makes a Dexterity saving throw. On a failure, it
    takes fire damage equal to 1d6 + your Proficiency Bonus."  Kindle Wax had no action at all."""
    engine = _engine(_bundle(["TAL_WAX_SMOKE_WICK"], dc=50))
    foe = engine.state.actors[FOE]
    assert not any(n.startswith("Kindle Wax") for n in _names(engine))  # no wax yet: nothing to burn
    _use(engine, "Press Seal")
    assert _seal(engine, FOE)
    _ready(engine)
    hp, qi = foe.current_hp, engine.state.actors[ME].resources["resource:core.qi"]
    events = _use(engine, "Kindle Wax: Candleflare")
    assert not _seal(engine, FOE)  # consumed
    assert 0 < hp - foe.current_hp <= 6 + 4 and engine.state.actors[ME].resources["resource:core.qi"] == qi  # 1d6 + PB, 0 CP
    assert any(p["damage_type"] == "FIRE" for p in _payloads(events, "DAMAGE_COMMITTED"))
    assert not engine.state.actors[ME].bonus_action_available


def test_release_seal_hurts_an_enemy_and_shelters_an_ally():
    """"Release Seal. If the kindled wax was a Wax Seal on an ally, the ally gains temporary hit points equal to your Proficiency
    Bonus. If it was a Wax Seal on an enemy, that enemy takes fire damage equal to your Proficiency Bonus."  A willing creature is
    sealed automatically (Press Seal)."""
    engine = _engine(_bundle(["TAL_WAX_SMOKE_WICK"], dc=50))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    _use(engine, "Seal a Willing Creature (Press Seal)", ME)
    assert _seal(engine, ME)
    _ready(engine)
    _use(engine, "Kindle Wax: Release Seal (ally)", ME)
    assert me.temporary_hp == 4 and not _seal(engine, ME)  # PB
    _ready(engine)
    _use(engine, "Press Seal")
    _ready(engine)
    hp = foe.current_hp
    _use(engine, "Kindle Wax: Release Seal")
    assert hp - foe.current_hp == 4 and not _seal(engine, FOE)


def test_smoke_puff_and_smoke_wick_leave_smoke():
    """Smoke Puff: "thick smoke in a 5-foot radius until the start of your next turn. The area is Lightly Obscured."  Smoke Wick:
    "the smoke fills a 10-foot radius instead ... Heavily Obscured until the start of your next turn, then ... Lightly Obscured
    until the end of your next turn."""
    plain = _engine(_bundle(["TAL_WAX_HUNDRED_SEAL_CONFLAGRATION"], dc=50))
    _use(plain, "Press Seal")
    _ready(plain)
    _use(plain, "Kindle Wax: Smoke Puff")
    (puff,) = [z for z in zones.typed_zones(plain) if z.trigger_profile.get("obscured")]
    assert puff.trigger_profile["obscured"] == "light" and puff.radius_cells == 1
    wick = _engine(_bundle(["TAL_WAX_SMOKE_WICK"], dc=50))
    _use(wick, "Press Seal")
    _ready(wick)
    _use(wick, "Kindle Wax: Smoke Puff")
    made = sorted((z.trigger_profile["obscured"], z.radius_cells) for z in zones.typed_zones(wick) if z.trigger_profile.get("obscured"))
    assert made == [("heavy", 2), ("light", 2)]


def test_searing_seal_adds_a_constitution_save_and_takes_reactions():
    """Searing Seal (1 CP): "When you kindle a Wax Seal on a hostile creature, you may spend 1 CP to make it sear. The creature makes a
    Constitution saving throw. On a failure, it takes 2d8 fire damage and cannot take Reactions until the start of its next turn.
    On a success, it takes half damage and suffers no Reaction loss."  It was a modifier of an action that did not exist."""
    plain = _engine(_bundle(["TAL_WAX_SMOKE_WICK"], dc=50))
    _use(plain, "Press Seal")
    _ready(plain)
    assert not any("Searing" in n for n in _names(plain))
    engine = _engine(_bundle(["TAL_WAX_SEARING_SEAL"], dc=50))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    _use(engine, "Press Seal")
    _ready(engine)
    qi, hp = me.resources["resource:core.qi"], foe.current_hp
    _use(engine, "Kindle Wax: Release Seal + Searing Seal (1 CP)")
    assert me.resources["resource:core.qi"] == qi - 1
    assert hp - foe.current_hp >= 4 + 2  # PB from the release, 2d8 from the sear
    assert _held(foe, "condition:typed.reaction_denied")


def test_hundred_seal_conflagration_ignites_every_seal_and_pushes_away():
    """"You ignite any number of your Wax Seals within range. Choose up to three creatures bearing those seals or adjacent to those
    seals. Each target makes a Dexterity saving throw. On a failure, it takes 4d8 fire damage and is pushed 10 feet away from the
    nearest ignited seal. ... All ignited seals are consumed."  It hit any one creature and left every seal standing."""
    engine = _engine(_bundle(["TAL_WAX_HUNDRED_SEAL_CONFLAGRATION"], dc=50))
    foe = engine.state.actors[FOE]
    assert "Hundred-Seal Conflagration" not in _names(engine)  # no seals: nothing to ignite
    _use(engine, "Press Seal")
    _ready(engine)
    start, hp = foe.position, foe.current_hp
    _use(engine, "Hundred-Seal Conflagration", FOE)  # aimed at a creature bearing a seal (it was offered on its caster)
    assert not _seal(engine, FOE)
    assert hp - foe.current_hp >= 4  # 4d8
    assert foe.position == start  # carried seal has no mapped direction; never substitute the caster
    assert any("GM chooses the 10-foot push direction" in str(e.payload) for e in engine.events)


def test_court_of_ten_thousand_candles_seals_the_first_enemy_that_fails_a_wax_save():
    """"The first time each round an enemy fails a saving throw against one of your Wax talents, you may place a Wax Seal on that
    enemy without spending additional CP."  It was a GM line."""
    engine = _engine(_bundle(["TAL_WAX_COURT_OF_TEN_THOUSAND_CANDLES", "TAL_WAX_ADHESIVE_POOL"], dc=50))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    _use(engine, _place(engine, "Court of Ten Thousand Candles", foe.position))
    _ready(engine)
    assert not _seal(engine, FOE)
    _use(engine, _place(engine, "Mold Wax: Soft Spread", foe.position))  # the foe fails Soft Spread's save, inside the Court
    assert not _seal(engine, FOE)  # Printed trigger is entry/start, never creation.
    zones.on_turn_start(engine, foe)
    assert _seal(engine, FOE)
    assert _mark(me, "wax_court_seal_placed_this_round")  # "the first time each round"


def test_the_riders_that_were_automated_are_gone_from_the_authority():
    mech = json.loads(Path(TYPED_AUTHORITY).read_bytes())["mechanics"]
    assert not mech["TAL_WAX_SEARING_SEAL"].get("riders")
    assert not mech["TAL_WAX_HUNDRED_SEAL_CONFLAGRATION"].get("riders")
    assert not any("first hostile creature each round" in r for r in mech["TAL_WAX_MOLD_WAX"].get("riders") or [])
    assert not any("first time each round an enemy fails" in r for r in mech["TAL_WAX_COURT_OF_TEN_THOUSAND_CANDLES"].get("riders") or [])


# ---------------------------------------------------------------------------------------------------------------- Sound
from combat import typed_executor, typed_reactions
from combat.gate2_runtime_models import ActionIntent
from tests import test_sysv2_objects as OBJ


def _authority_riders(mid):
    mech = json.loads(Path(TYPED_AUTHORITY).read_bytes())["mechanics"]
    return list(mech[mid].get("riders") or [])


def _foe_effects(engine, target_id, effects, *, dc=16):
    """The foe uses an ability with these typed effects on ``target_id`` (inside an action, so reactions may answer)."""
    action = next(iter(engine.action_catalog.values()))
    actor, target = engine.state.actors[FOE], engine.state.actors[target_id]
    intent = ActionIntent(intent_id="foe", decision_id="foe", candidate_id="foe", state_version=0, actor_id=FOE, target_ids=(target_id,))
    ctx = typed_executor.Context(engine, actor, action, intent, {"numbers": {"pb": 4, "save_dc": dc}}, [target], target, {})
    typed_executor.run_effects(ctx, effects)


def _tough(engine):
    foe = engine.state.actors[FOE]
    foe.maximum_hp = foe.current_hp = 900
    return foe


def _resonance(actor):
    return [c for c in actor.conditions.values() if c.condition_id.startswith("condition:typed.mark.resonance.")]


def test_sound_area_talents_leave_resonance_where_the_text_says():
    """Mountain-Cracking Bell ("Failed Save: ... Prone, and gain Resonance. Successful Save: half damage and gain Resonance"),
    World-Ringing Note (Resonance on either result) and Resonant Shatter ("Failed Save: Take Thunder damage and gain Resonance"; a
    success only takes half) -- the Resonance was a GM line."""
    for mid, name, on_fail, on_success in (("TAL_SOUND_MOUNTAIN_CRACKING_BELL", "Mountain-Cracking Bell", True, True),
                                           ("TAL_SOUND_WORLD_RINGING_NOTE", "World-Ringing Note", True, True),
                                           ("TAL_SOUND_RESONANT_SHATTER", "Resonant Shatter", True, False)):
        for dc, expected in ((50, on_fail), (1, on_success)):
            engine = _engine(_bundle([mid], dc=dc))
            foe = _tough(engine)
            _use(engine, _place(engine, name, foe.position))
            assert bool(_resonance(foe)) == expected, (name, dc)


def test_resonance_field_marks_a_hostile_creature_whether_or_not_it_saves():
    """"Failed Save: It gains Resonance and takes Thunder damage equal to your Proficiency Bonus. Successful Save: It gains
    Resonance only."""
    for dc, hurt in ((50, True), (1, False)):
        engine = _engine(_bundle(["TAL_SOUND_RESONANCE_FIELD"], dc=dc))
        foe = _tough(engine)
        _use(engine, "Resonance Field")
        hp = foe.current_hp
        zones.on_turn_start(engine, foe)
        assert _resonance(foe)
        assert (hp - foe.current_hp == 4) == hurt


def test_court_of_the_world_ringing_bell_is_one_court_or_the_other():
    """"When you create the Domain, choose Ringing Court or Silent Court." Ringing: hostile creatures that start their turn inside
    save; "Failed Save: They take 4d8 Thunder damage and gain Resonance. Successful Save: They gain Resonance."  Silent: "Failed Save:
    They cannot speak above a whisper until the start of their next turn. Successful Save: No additional effect."  One action made
    every clause of both at once and never gave Resonance or the whisper."""
    engine = _engine(_bundle(["TAL_SOUND_COURT_OF_THE_WORLD_RINGING_BELL"], dc=50))
    assert any(n.startswith("Court of the World-Ringing Bell: Ringing Court") for n in _names(engine))
    assert any(n.startswith("Court of the World-Ringing Bell: Silent Court") for n in _names(engine))
    foe = _tough(engine)
    _use(engine, _place(engine, "Court of the World-Ringing Bell: Ringing Court", foe.position))
    hp = foe.current_hp
    zones.on_turn_start(engine, foe)
    assert hp - foe.current_hp >= 4 and _resonance(foe) and not _held(foe, "condition:typed.silenced")
    silent = _engine(_bundle(["TAL_SOUND_COURT_OF_THE_WORLD_RINGING_BELL"], dc=50))
    foe = _tough(silent)
    _use(silent, _place(silent, "Court of the World-Ringing Bell: Silent Court", foe.position))
    hp = foe.current_hp
    zones.on_turn_start(silent, foe)
    assert foe.current_hp == hp and not _resonance(foe) and _held(foe, "condition:typed.silenced")
    saved = _engine(_bundle(["TAL_SOUND_COURT_OF_THE_WORLD_RINGING_BELL"], dc=1))
    foe = _tough(saved)
    _use(saved, _place(saved, "Court of the World-Ringing Bell: Ringing Court", foe.position))
    zones.on_turn_start(saved, foe)
    assert _resonance(foe) and foe.current_hp == foe.maximum_hp  # "Successful Save: They gain Resonance"


def test_bell_shell_guard_costs_one_cp_and_answers_thunder_damage():
    """"Cost: 1 CP or expend Martial Focus ..." was a text line (the reaction was free), and its reading's "thunder" never matched the
    damage type the engine reports ("THUNDER"), so the Guard never answered thunder damage at all."""
    engine = _engine(_bundle(["TAL_SOUND_BELL_SHELL_GUARD"], dc=16))
    me = engine.state.actors[ME]
    qi, hp = me.resources["resource:core.qi"], me.current_hp
    _foe_effects(engine, ME, [{"type": "damage", "applies_to": "target", "dice": {"count": 8, "sides": 8}, "damage_types": ["thunder"]}])
    assert me.resources["resource:core.qi"] == qi - 1 and not me.reaction_available
    assert any(e.event_type == "REACTION_RESOLVED" and e.payload.get("reduction", 0) > 0 for e in engine.events if e.actor_id == ME)
    # the same damage from another type is not answered
    other = _engine(_bundle(["TAL_SOUND_BELL_SHELL_GUARD"], dc=16))
    _foe_effects(other, ME, [{"type": "damage", "applies_to": "target", "dice": {"count": 8, "sides": 8}, "damage_types": ["fire"]}])
    assert other.state.actors[ME].reaction_available


@pytest.mark.parametrize("outcome", ["concentration", "reactions", "speed", "resonance"])
def test_dissonant_pulse_is_choose_one_and_a_success_still_leaves_resonance(tmp_path, outcome):
    """"Failed Save: Choose one: Disadvantage on its next Concentration saving throw; cannot take Reactions; reduce Speed by 10 feet;
    apply Resonance until the end of your next turn. Successful Save: Apply Resonance until the start of your next turn." -- every
    result landed at once, and the fourth choice did not exist."""
    from tests.test_a2_sound import note_candidate, choose_pulse, PULSE
    from tests.worker2_support import fixture, reload, OWNER, FOE as TARGET
    from combat.canonical import canonical_sha256
    from combat.typed_executor import condition_rules, mark_condition_id

    def setup(bundles):
        for bundle in bundles:
            if bundle["actor_id"] == OWNER:
                for row in bundle["action_catalog"]:
                    if row["display_name"].startswith("Resonant Note:"):
                        row["parameters"]["typed"]["numbers"]["attack_bonus"] = 50
            bundle.pop("bundle_sha256", None)
            bundle["bundle_sha256"] = canonical_sha256(bundle)
    combat, table, mid = fixture(tmp_path, [PULSE], owner_dc=50,
                                foe_position={"x": 5, "y": 6}, bundle_transform=setup)
    engine = reload(tmp_path, mid)
    assert not any("+ Dissonant Pulse" in a.display_name for a in engine.action_catalog.values())
    qi = engine.state.actors[OWNER].resources["resource:core.qi"]
    prompts = choose_pulse(table, mid, note_candidate(combat, mid).candidate_id, outcome)
    failure = next(p for p in prompts if p["context"]["reaction_source_id"] == "choice:needle.sound_pulse_failure")
    assert {o["id"] for o in failure["choice"]["options"]} == {"concentration", "reactions", "speed", "resonance"}
    engine = reload(tmp_path, mid)
    foe = engine.state.actors[TARGET]
    assert engine.state.actors[OWNER].resources["resource:core.qi"] == qi - 1
    assert engine._effective_speed(foe) == foe.speed_ft - (10 if outcome == "speed" else 0)
    assert bool(any(r.get("no_reactions") for r in condition_rules(foe))) == (outcome == "reactions")
    assert bool(any(r.get("concentration_mode") for r in condition_rules(foe))) == (outcome == "concentration")
    (mark,) = [c for c in foe.conditions.values() if c.condition_id == mark_condition_id("Resonance", OWNER)]
    assert mark.expires_on == ("END_OF_MARKER_NEXT_TURN" if outcome == "resonance" else "START_OF_MARKER_NEXT_TURN")


def test_thunder_meridian_strike_gives_the_four_failed_save_choices():
    """"Failed Save: Choose one: cannot take Reactions until the start of your next turn; Speed reduced by 10 feet ...; Disadvantage
    on its next Concentration saving throw ...; apply Resonance until the end of your next turn."  Its save had no failed branch."""
    engine = _engine(_melee_bundle(["TAL_SOUND_THUNDER_MERIDIAN_STRIKE"], dc=50))
    foe = _tough(engine)
    name = "Fu (Short Axe) attack + Thunder-Meridian Strike: No Reactions (2 CP)"
    assert name in _names(engine)
    qi = engine.state.actors[ME].resources["resource:core.qi"]
    _use(engine, name)
    assert engine.state.actors[ME].resources["resource:core.qi"] == qi - 2 and _held(foe, "condition:typed.reaction_denied")
    saved = _engine(_melee_bundle(["TAL_SOUND_THUNDER_MERIDIAN_STRIKE"], dc=1))
    foe = _tough(saved)
    _use(saved, name)
    assert not _held(foe, "condition:typed.reaction_denied")  # "Successful Save": no choice applies


def test_name_striking_tone_can_leave_resonance():
    engine = _engine(_bundle(["TAL_SOUND_NAME_STRIKING_TONE"], dc=50))
    foe = _tough(engine)
    _use(engine, "Name-Striking Tone: Resonance")
    (mark,) = _resonance(foe)
    assert mark.expires_on == "END_OF_MARKER_NEXT_TURN"


def test_body_resonance_strike_adds_two_dice_from_cl_eleven():
    """"At CL 11, increase the bonus damage to 2d6." -- the bonus stayed 1d6."""
    dice = {}
    for cl in (10, 11):
        engine = _engine(_melee_bundle(["TAL_SOUND_BODY_RESONANCE_STRIKE"], cl=cl))
        _tough(engine)
        before = len(engine.rolls)
        _use(engine, "Fu (Short Axe) attack + Body Resonance Strike (1 CP)")
        extra = [r for r in engine.rolls[before:] if str(r.reason).startswith("DAMAGE:") and not str(r.reason).endswith(":1")]
        dice[cl] = len(extra[-1].dice)
    assert dice == {10: 1, 11: 2}


def _body_strike_bundles(items, *, legacy=False, owned=True):
    authority = json.loads(Path(TYPED_AUTHORITY).read_bytes()) if legacy else None
    if legacy:
        modifier = authority["mechanics"]["TAL_SOUND_BODY_RESONANCE_STRIKE"]["modifier"]
        modifier["effects"] = [e for e in modifier["effects"] if e["type"] != "sound_equipped_resonance"]
    sheet = L1._sheet("TAL_SOUND_BODY_RESONANCE_STRIKE")
    sheet["spheres_and_talents"]["sphere_record_ids"].append("tianxia.sphere.iron_fist")
    sheet["spheres_and_talents"]["automatic_sphere_component_record_ids"].extend(
        k for k, m in _mech().items() if m.get("sphere_id") == "tianxia.sphere.iron_fist" and m.get("kind") == "base_ability")
    sheet["ability_scores_and_statistics"]["abilities"][0].update(score=50, modifier=20)
    sheet["spheres_and_talents"]["learned_talent_record_ids"] = ["TAL_SOUND_BODY_RESONANCE_STRIKE"] if owned else []
    sheet["path_and_subpath"] = {"path_record_ids": ["tianxia.path.body_refining"]}
    sheet["equipment"] = [{"starting_kit": {"items": [
        {"item_id": "tianxia.mortal.weapon.fu", "name": "Fu (Short Axe)", "quantity": 1}]}}]
    attacker = compile_character(sheet, actor_id=ME, typed_authority=authority)
    target = L1._sheet("TAL_SOUND_DAMPEN_SOUND")
    target["ability_scores_and_statistics"]["hit_points"]["maximum"] = 900
    target["equipment"] = [{"starting_kit": {"items": [
        {"item_id": item, "name": item, "quantity": 1} for item in items]}}]
    return attacker, compile_character(target, actor_id=L1.ALLY)


def _body_strike_engine(items, **kw):
    from combat.gate4_engine import Gate4ControllerEngine
    engine = Gate4ControllerEngine(ROOT, match_seed="R5-BODY", typed_bundles=_body_strike_bundles(items, **kw),
        roster_setup={"primary_actor_ids": [ME, L1.ALLY], "team_by_actor": {ME: "team:a", L1.ALLY: "team:b"},
                      "starting_positions": {ME: {"x": 3, "y": 6}, L1.ALLY: {"x": 4, "y": 6}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    engine.state.actors[L1.ALLY].armor_class = -50
    return engine


@pytest.mark.parametrize("item", ["tianxia.mortal.armor.lacquered_lamellar", "tianxia.mortal.armor.shield",
                                  "tianxia.mortal.weapon.bi_shou"])
@pytest.mark.parametrize("attack", ["Fu (Short Axe) attack", "Unarmed Strike (Iron Fist)"])
def test_body_resonance_marks_equipped_targets_on_paid_melee_hits(item, attack):
    engine = _body_strike_engine([item])
    _use(engine, attack + " + Body Resonance Strike" + (" (1 CP)" if attack.startswith("Fu") else ""))
    (mark,) = _resonance(engine.state.actors[L1.ALLY])
    assert mark.source_actor_id == ME and mark.expires_on == "START_OF_MARKER_NEXT_TURN"
    assert mark.data == {"marker_turn": engine.state.actors[ME].turns_started}
    from combat.typed_executor import expire_marks
    engine.state.current_actor_id = L1.ALLY
    engine.state.actors[L1.ALLY].turns_started += 1
    expire_marks(engine)
    assert _resonance(engine.state.actors[L1.ALLY])  # target's turn does not end the caster's mark
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    expire_marks(engine)
    assert not _resonance(engine.state.actors[L1.ALLY])


@pytest.mark.parametrize("item", [None, "tianxia.mortal.armor.shield", "tianxia.mortal.weapon.bi_shou"])
def test_body_resonance_does_not_mark_unequipped_or_dropped_targets(item):
    from combat.typed_executor import Context, block_drop_item
    engine = _body_strike_engine([item] if item else [])
    target = engine.state.actors[L1.ALLY]
    if item:
        action = next(a for a in engine.action_catalog.values() if a.owner_id == L1.ALLY)
        ctx = Context(engine, target, action, None, {}, [], target, {})
        # The production Drop effect writes the ordinary persistent item/disarm state.
        block_drop_item(ctx, {"item": item})
    _use(engine, "Fu (Short Axe) attack + Body Resonance Strike (1 CP)")
    assert not _resonance(target)


def test_body_resonance_old_saved_modifier_and_unmodified_attacks_stay_inert():
    for legacy, owned in ((True, True), (False, False), (False, True)):
        engine = _body_strike_engine(["tianxia.mortal.armor.shield"], legacy=legacy, owned=owned)
        name = "Fu (Short Axe) attack" + (" + Body Resonance Strike (1 CP)" if legacy else "")
        _use(engine, name)
        assert not _resonance(engine.state.actors[L1.ALLY])


def test_body_resonance_marks_a_target_holding_another_actors_weapon():
    engine = _body_strike_engine([])
    weapon = next(item for item in engine.typed_bundle_documents[0]["carrying"]["items"] if item.get("weapon_action"))
    engine._apply_condition(engine.state.actors[ME], "condition:typed.disarmed", "test:take", L1.ALLY,
        expires_on="UNTIL_REMOVED", data={"disables_action": weapon["weapon_action"], "held_by": L1.ALLY})
    _use(engine, "Unarmed Strike (Iron Fist) + Body Resonance Strike")
    assert len(_resonance(engine.state.actors[L1.ALLY])) == 1


def test_body_resonance_does_not_mark_a_missed_target_or_spare_unworn_armor():
    engine = _body_strike_engine(["tianxia.mortal.armor.shield"])
    engine.state.actors[L1.ALLY].armor_class = 1000
    _use(engine, "Fu (Short Axe) attack + Body Resonance Strike (1 CP)")
    assert not _resonance(engine.state.actors[L1.ALLY])
    # Only the armor chosen by the compiler as worn qualifies, not every spare.
    engine = _body_strike_engine(["tianxia.mortal.armor.lacquered_lamellar"])
    target_bundle = next(b for b in engine.typed_bundle_documents if b["actor_id"] == L1.ALLY)
    target_bundle["carrying"]["items"][0]["worn"] = False
    _use(engine, "Fu (Short Axe) attack + Body Resonance Strike (1 CP)")
    assert not _resonance(engine.state.actors[L1.ALLY])


def test_body_resonance_mark_survives_table_commit_and_reload(tmp_path):
    from combat.gate4_persistence import Gate4Persistence
    persistence = Gate4Persistence(ROOT, tmp_path)
    session = persistence.create_match(match_seed="R5-BODY-PERSIST",
        typed_bundles=_body_strike_bundles(["tianxia.mortal.armor.shield"]),
        roster_setup={"primary_actor_ids": [ME, L1.ALLY], "team_by_actor": {ME: "team:a", L1.ALLY: "team:b"},
                      "starting_positions": {ME: {"x": 3, "y": 6}, L1.ALLY: {"x": 4, "y": 6}}})
    def submit(name):
        candidate = next(c for c in session.engine.legal_candidates() if c.display_name == name)
        session.submit_intent(ActionIntent(intent_id=f"body-{session.engine.state.state_version}",
            decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
            state_version=candidate.state_version, actor_id=candidate.actor_id,
            target_ids=candidate.target_ids, destination=candidate.destination),
            primary_decision_record=None, reaction_provider=None)
    while session.engine.state.current_actor_id != ME:
        submit("End turn")
    # Natural attack bonus: this seed must hit without mutating persisted state.
    submit("Fu (Short Axe) attack + Body Resonance Strike (1 CP)")
    before = [c.model_dump(mode="json") for c in _resonance(session.engine.state.actors[L1.ALLY])]
    assert len(before) == 1
    session = persistence.load_match(session.match_id)
    assert [c.model_dump(mode="json") for c in _resonance(session.engine.state.actors[L1.ALLY])] == before
    submit("End turn")
    while session.engine.state.current_actor_id != ME:
        submit("End turn")
    assert not _resonance(session.engine.state.actors[L1.ALLY])
    assert not _resonance(persistence.load_match(session.match_id).engine.state.actors[L1.ALLY])


def test_harmonic_healing_tone_ends_deafened():
    """"The target may also end Deafened ..."."""
    engine = _engine(_bundle(["TAL_SOUND_HARMONIC_HEALING_TONE"]), allies=(L1._ally_bundle(),))
    ally = engine.state.actors[L1.ALLY]
    engine._apply_condition(ally, "condition:typed.deafened", "test", FOE, expires_on=None)
    ally.current_hp = ally.maximum_hp - 20
    _use(engine, "Harmonic Healing Tone", L1.ALLY)
    assert ally.current_hp > ally.maximum_hp - 20 and not _held(ally, "condition:typed.deafened")


def test_resonant_note_riders_need_the_target_to_already_bear_your_resonance():
    """"If the target already bears your Resonance, choose one rider on a hit: the target is Deafened ..." -- Deafened landed on the
    first hit as well."""
    engine = _engine(_bundle(["TAL_SOUND_DAMPEN_SOUND"], dc=16))
    foe = _tough(engine)
    _use(engine, "Resonant Note: Deafen")
    assert _resonance(foe) and not _held(foe, "condition:typed.deafened")  # first note: Resonance only
    _ready(engine)
    _use(engine, "Resonant Note: Deafen")
    assert _held(foe, "condition:typed.deafened")  # it already bore the Resonance
    engine = _engine(_bundle(["TAL_SOUND_DAMPEN_SOUND"], dc=16))
    foe = _tough(engine)
    _use(engine, "Resonant Note: Concentration Disadvantage")
    assert not [c for c in foe.conditions.values() if c.condition_id == "condition:typed.concentration_mode"]
    _ready(engine)
    _use(engine, "Resonant Note: Concentration Disadvantage")
    assert [c for c in foe.conditions.values() if c.condition_id == "condition:typed.concentration_mode"]


def test_bell_that_breaks_the_formation_shatters_an_object_ignoring_hardness():
    """"Make a Sound Cultivation Attack ... Success: Deal 8d10 Thunder damage to the target. This damage ignores ordinary Resistance and
    hardness. ... if the damage reduces [an ordinary temporary barrier] to 0, it breaks."  Its attack was deferred (a GM line)."""
    bundle = OBJ.build("tianxia.sphere.sound", ["TAL_SOUND_BELL_THAT_BREAKS_THE_FORMATION"])
    engine = OBJ.fight(bundle, objects=[{"id": 3, "kind": "wall_section", "x": 8, "y": 3, "threshold": 200, "hp": 10}], foe=(8, 8))
    OBJ.force_d20(engine, 15, 19)
    assert not OBJ.candidates(engine, "Bell That Breaks the Formation", OBJ.AN)  # never aimed at a creature
    events = OBJ.use(engine, "Bell That Breaks the Formation", "object:map.3")
    assert next(e for e in events if e.event_type == "ATTACK_ROLLED").payload["provisional_hit"]
    assert engine.state.objects["object:map.3"].destroyed  # 8d10 against 10 hit points, a Damage Threshold of 200 ignored
    assert any("ignored its Damage Threshold of 200" in note for row in OBJ.updates(events) for note in row.payload["damage"]["notes"])


def test_shatter_vessel_bursts_on_the_creatures_beside_what_it_destroys():
    """"If this damage destroys the object, choose one: creatures within 5 feet make Dexterity saving throws or take 1d8 Thunder damage
    from the burst ..."; "Target: One unattended object ..."."""
    bundle = OBJ.build("tianxia.sphere.sound", ["TAL_SOUND_SHATTER_VESSEL"])
    objects = [{"id": 1, "kind": "crate", "x": 8, "y": 3, "hp": 1}, {"id": 2, "kind": "crate", "x": 6, "y": 3, "hp": 1, "artifact": True}]
    engine = OBJ.fight(bundle, objects=objects, foe=(8, 4))  # the foe stands beside the first crate
    OBJ.force_d20(engine, 15, 19)
    assert not OBJ.candidates(engine, "Shatter Vessel", OBJ.AN)
    assert not OBJ.candidates(engine, "Shatter Vessel", "object:map.2")  # "does not automatically break ... artifacts"
    hp = engine.state.actors[OBJ.AN].current_hp
    events = OBJ.use(engine, "Shatter Vessel", "object:map.1")
    assert engine.state.objects["object:map.1"].destroyed
    assert engine.state.actors[OBJ.AN].current_hp < hp  # the burst (the sheet's DC 30 is beyond its Dexterity save)
    assert any(p["damage_type"] == "thunder" or p["damage_type"] == "THUNDER" for p in _payloads(events, "DAMAGE_COMMITTED"))


def test_resonant_note_can_be_aimed_at_an_object_and_adds_proficiency_bonus():
    """"Target: One creature or object you can perceive ... If the target is an unattended object ... add your Proficiency Bonus."""
    bundle = OBJ.build("tianxia.sphere.sound", [], base=("TAL_SOUND_RESONANT_NOTE",))
    engine = OBJ.fight(bundle, objects=[{"id": 3, "kind": "crate", "x": 8, "y": 3, "hp": 999}], foe=(8, 8))
    OBJ.force_d20(engine, 15, 19)
    before = len(engine.rolls)
    events = OBJ.use(engine, "Resonant Note: Deafen", "object:map.3")
    pb = 4
    assert OBJ.lost(engine, "object:map.3", events) == OBJ.damage_dice(engine, before) + pb


def _exposed_note_object():
    bundle = OBJ.build("tianxia.sphere.sound", [], base=("TAL_SOUND_RESONANT_NOTE",))
    engine = OBJ.fight(bundle, objects=[{"id": 3, "kind": "crate", "x": 8, "y": 3, "hp": 999,
                                         "resist": ["THUNDER", "FIRE"]}], foe=(8, 8))
    OBJ.force_d20(engine, 15, 19)
    assert not OBJ.candidates(engine, "Resonant Note: Expose Object", "object:map.3")
    OBJ.use(engine, "Resonant Note: Deafen", "object:map.3")
    assert not OBJ.candidates(engine, "Resonant Note: Expose Object", OBJ.AN)
    events = OBJ.use(engine, "Resonant Note: Expose Object", "object:map.3")
    assert any("sound_thunder_exposure" in e.payload["object"]["component"] for e in OBJ.updates(events))
    return engine


def test_resonant_note_object_rider_bypasses_only_thunder_for_one_damage_instance():
    from combat.ext import objects

    engine = _exposed_note_object()
    result = objects.deal(engine, engine.state.actors[OBJ.ME], engine.state.objects["object:map.3"],
                          [(10, "THUNDER"), (10, "FIRE")], "test:mixed")
    assert result["total"] == 15
    result = objects.deal(engine, engine.state.actors[OBJ.ME], engine.state.objects["object:map.3"],
                          [(10, "THUNDER")], "test:again")
    assert result["total"] == 5


def test_resonant_note_object_rider_is_consumed_by_non_thunder_damage():
    from combat.ext import objects

    engine = _exposed_note_object()
    obj = engine.state.objects["object:map.3"]
    assert objects.deal(engine, engine.state.actors[OBJ.ME], obj, [(10, "FIRE")], "test:fire")["total"] == 5
    obj = engine.state.objects[obj.object_id]
    assert objects.deal(engine, engine.state.actors[OBJ.ME], obj, [(10, "THUNDER")], "test:thunder")["total"] == 5


def test_resonant_note_object_rider_expires_at_owners_next_turn_only():
    engine = _exposed_note_object()
    engine._append_event("TURN_STARTED", "test", actor_id=OBJ.AN, payload={})
    assert OBJ.ME in engine.state.objects["object:map.3"].component["sound_thunder_exposure"]
    engine._append_event("TURN_STARTED", "test", actor_id=OBJ.ME, payload={})
    assert "sound_thunder_exposure" not in engine.state.objects["object:map.3"].component
    assert not OBJ.candidates(engine, "Resonant Note: Expose Object", "object:map.3")


def test_resonant_note_object_rider_miss_does_not_expose():
    engine = _exposed_note_object()
    from combat.ext import objects

    objects.deal(engine, engine.state.actors[OBJ.ME], engine.state.objects["object:map.3"], [(10, "FIRE")], "test:consume")
    OBJ.force_d20(engine, 1, 1)
    OBJ.use(engine, "Resonant Note: Expose Object", "object:map.3")
    assert "sound_thunder_exposure" not in engine.state.objects["object:map.3"].component


def test_resonant_note_object_rider_preserves_immunity_and_damage_threshold():
    from combat.ext import objects

    engine = _exposed_note_object()
    obj = engine.state.objects["object:map.3"].model_copy(update={"damage_immunities": ("THUNDER",)})
    engine._update_object(obj, "test:immunity", OBJ.ME)
    result = objects.deal(engine, engine.state.actors[OBJ.ME], obj, [(10, "THUNDER")], "test:immune")
    assert result["total"] == 0
    assert "sound_thunder_exposure" in engine.state.objects[obj.object_id].component
    engine = _exposed_note_object()
    obj = engine.state.objects["object:map.3"].model_copy(update={"damage_threshold": 20})
    engine._update_object(obj, "test:threshold", OBJ.ME)
    assert objects.deal(engine, engine.state.actors[OBJ.ME], obj, [(10, "THUNDER")], "test:threshold")["total"] == 0
    assert "sound_thunder_exposure" in engine.state.objects[obj.object_id].component


def test_resonant_note_object_resonance_is_caster_owned_and_evented():
    from combat.ext import sound_objects
    from combat.gate2_runtime_models import RuntimeObjectState

    engine = _exposed_note_object()
    obj = engine.state.objects["object:map.3"]
    component = {**obj.component, "sound_resonance": {OBJ.ME: True, OBJ.AN: True},
                 "sound_thunder_exposure": {OBJ.ME: True, OBJ.AN: True}}
    engine._update_object(obj.model_copy(update={"component": component}), "test:second_caster", OBJ.AN)
    sound_objects.expire(engine, engine.state.actors[OBJ.ME])
    snapshot = next(e.payload["object"] for e in reversed(engine.events) if e.event_type == "OBJECT_UPDATED")
    replayed = RuntimeObjectState.model_validate(snapshot)
    assert replayed == engine.state.objects[obj.object_id]
    assert replayed.component["sound_resonance"] == {OBJ.AN: True}
    assert replayed.component["sound_thunder_exposure"] == {OBJ.AN: True}


def test_sound_sovereign_incarnation_runs_its_lines_while_it_lasts():
    """"once per turn when a creature fails a saving throw against your Sound talent, it cannot take Reactions until the start of your
    next turn; ... Soundwalk Step range increases by 30 feet; your Sound talents ignore ordinary Thunder Resistance."  (Blindsight
    is combat/rules/senses.json; the modifier that lengthened Resonant Note's range was Soundwalk Step's alone.)"""
    def build():
        engine = _engine(_bundle(["TAL_SOUND_SOUND_SOVEREIGN_INCARNATION", "TAL_SOUND_THUNDERING_VOICE", "TAL_SOUND_SOUNDWALK_STEP"], dc=50, cl=10))
        # Owner 2026-10-01: unrestricted areas can hit their caster. Ensure the
        # foe is the first failed save, so it consumes the once-per-turn rider.
        engine.state.actors[ME].saving_throws["CON"] = 1000
        return engine, _tough(engine)
    engine, foe = build()
    voice = next(a for a in engine.action_catalog.values() if a.source_definition_id.endswith("TAL_SOUND_THUNDERING_VOICE"))
    typed = typed_reactions._typed(engine, voice.source_definition_id)
    assert not any("(Sound-Sovereign Incarnation)" in n for n in _names(engine))  # the longer step only exists while it lasts
    assert not typed_reactions._resistance_ignored(engine, "THUNDER", typed, ME)
    _use(engine, _place(engine, "Thundering Voice", foe.position))
    assert not _held(foe, "condition:typed.reaction_denied")
    engine, foe = build()
    _use(engine, "Sound-Sovereign Incarnation")
    _ready(engine)
    assert typed_reactions._resistance_ignored(engine, "THUNDER", typed, ME)  # Resistance to Thunder is set aside for a Sound talent ...
    assert not typed_reactions._resistance_ignored(engine, "FIRE", typed, ME)
    assert not typed_reactions._resistance_ignored(engine, "THUNDER", {**typed, "sphere": "tianxia.sphere.fire"}, ME)  # ... and only for one
    here = engine.state.actors[ME].position
    far = f"{here.x + 7},{here.y}"  # 35 feet away: past the plain step's 30 feet at CL 10, inside the longer one's 60
    assert f"Soundwalk Step (Sound-Sovereign Incarnation) to {far}" in _names(engine)
    assert f"Soundwalk Step to {far}" not in _names(engine)
    _use(engine, _place(engine, "Thundering Voice", foe.position))
    assert _held(foe, "condition:typed.reaction_denied")
    foe.conditions.clear()
    _ready(engine)
    _use(engine, _place(engine, "Thundering Voice", foe.position))
    assert not _held(foe, "condition:typed.reaction_denied")  # once per turn
    from combat import senses
    assert senses.of(engine, engine.state.actors[ME]).get("blindsight", {}).get("range_ft") == 30


def test_sound_riders_that_the_typed_core_already_runs_are_gone():
    gone = {
        "TAL_SOUND_STEAL_VOICE": ("Until the end of your next turn, the target cannot speak",),
        "TAL_SOUND_FORBIDDEN_SILENCE_FIELD": ("Failed Save: The creature cannot speak",),
        "TAL_SOUND_SILENCE_THAT_SWALLOWS_THUNDER": ("hostile creatures that start their turn inside", "Failed Save: The creature cannot speak"),
        "TAL_SOUND_THUNDERING_VOICE": ("Damage by Cultivation Level",),
        "TAL_SOUND_SOUNDWALK_STEP": ("At CL 11",),
        "TAL_SOUND_BODY_RESONANCE_STRIKE": ("you may spend 1 Stamina or 1 CP", "At CL 11"),
        "TAL_SOUND_MOUNTAIN_CRACKING_BELL": ("Objects, structures, barriers",),
        "TAL_SOUND_WORLD_SPLITTING_SCREAM": ("Objects and ordinary barriers",),
        "TAL_SOUND_RESONANT_SHATTER": ("Objects, constructs, barriers",),
        "TAL_SOUND_WORLD_RINGING_NOTE": ("Objects, barriers, constructs",),
        "TAL_SOUND_SOUND_SOVEREIGN_INCARNATION": ("gain Blindsight", "once per turn when a creature fails", "your Sound talents ignore"),
    }
    for mid, prefixes in gone.items():
        riders = _authority_riders(mid)
        assert not [r for r in riders for p in prefixes if r.startswith(p)], (mid, riders)
    # ... and what they said is run: Steal Voice silences until the end of the caster's next turn
    engine = _engine(_bundle(["TAL_SOUND_STEAL_VOICE"], dc=50))
    _tough(engine)
    _use(engine, "Steal Voice")
    assert _held(engine.state.actors[FOE], "condition:typed.silenced")


def test_echo_decoy_makes_a_one_hit_point_decoy_that_a_hit_removes():
    """"Create a sound-body decoy in an unoccupied space ... The decoy has AC 10, 1 HP, and disappears when damaged." -- it was a
    zone on its own caster."""
    engine = _engine(_bundle(["TAL_SOUND_ECHO_DECOY"], dc=16))
    me = engine.state.actors[ME]
    _use(engine, "Echo Decoy")
    (decoy,) = [a for a in engine.state.actors.values() if (a.summon or {}).get("group") == "echo_decoy" and a.active]
    assert decoy.armor_class == 10 and decoy.maximum_hp == 1 and decoy.team_id == me.team_id and decoy.owner_id == ME
    assert engine._distance_actor_to_actor(me, decoy) <= 60
    engine._commit_damage(decoy, 1, "BLUDGEONING", "test", FOE, None, reaction_depth=0)
    assert not decoy.active  # "disappears when damaged"


def test_shatter_vessel_can_choose_a_nonburst_outcome_without_hurting_bystanders():
    bundle = OBJ.build("tianxia.sphere.sound", ["TAL_SOUND_SHATTER_VESSEL"])
    engine = OBJ.fight(bundle, objects=[{"id": 1, "kind": "crate", "x": 8, "y": 3, "hp": 1}], foe=(8, 4))
    OBJ.force_d20(engine, 15, 19)
    OBJ.use(engine, "Choose Shatter Vessel: Loud Report")
    hp = engine.state.actors[OBJ.AN].current_hp
    events = OBJ.use(engine, "Shatter Vessel", "object:map.1")
    assert engine.state.objects["object:map.1"].destroyed
    assert engine.state.actors[OBJ.AN].current_hp == hp
    assert any("loud report audible up to 300 feet" in p.get("rider", "") for p in _payloads(events, "GM_RIDER"))


def test_shatter_vessel_miss_neither_damages_the_object_nor_bursts():
    bundle = OBJ.build("tianxia.sphere.sound", ["TAL_SOUND_SHATTER_VESSEL"])
    engine = OBJ.fight(bundle, objects=[{"id": 1, "kind": "crate", "x": 8, "y": 3, "hp": 1}], foe=(8, 4))
    OBJ.force_d20(engine, 1, 1)
    hp = engine.state.actors[OBJ.AN].current_hp
    OBJ.use(engine, "Shatter Vessel", "object:map.1")
    assert not engine.state.objects["object:map.1"].destroyed
    assert engine.state.actors[OBJ.AN].current_hp == hp


def test_world_splitting_scream_deafened_gets_its_end_turn_repeat_save():
    engine = _engine(_bundle(["TAL_SOUND_WORLD_SPLITTING_SCREAM"], dc=50))
    foe = _tough(engine)
    _use(engine, _place(engine, "World-Splitting Scream", foe.position))
    (deaf,) = [c for c in foe.conditions.values() if c.condition_id == "condition:typed.deafened"]
    assert deaf.data['repeat_save']['ability'] == 'CON'
    assert deaf.data['repeat_save']['when'] == 'end'
    # The engine really rolls the repeat and clears the condition on success.
    deaf.data['repeat_save']['dc'] = 1
    engine.state.current_actor_id = FOE
    engine.state.current_slot_index = engine.state.initiative_order.index(FOE)
    OBJ.force_d20(engine, 15, 19)
    engine.end_turn()
    assert not _held(foe, "condition:typed.deafened")


def _sonic_cage():
    from combat.typed_executor import Context, run_effects
    engine = _engine(_bundle(["TAL_SOUND_SONIC_CAGE"], dc=50))
    me, foe = engine.state.actors[ME], _tough(engine)
    action = next(a for a in engine.action_catalog.values() if a.display_name == "Sonic Cage")
    run_effects(Context(engine, me, action, None, action.parameters["typed"], [foe], foe, {}),
                [{"type": "mark", "mark": "Resonance", "applies_to": "target",
                  "duration": {"kind": "until_removed"}}])
    _use(engine, "Sonic Cage", FOE)
    return engine, foe, action


def _cage_end_turn(engine):
    engine.state.current_actor_id = FOE
    engine.state.current_slot_index = engine.state.initiative_order.index(FOE)
    before = len(engine.events)
    engine.end_turn()
    return [p for p in _payloads(engine.events[before:], "SAVE_ROLLED")
            if "SONIC_CAGE" in p.get("reason", "")]


@pytest.mark.parametrize("kind,amount,temp,expected", [
    ("THUNDER", 3, 0, "DISADVANTAGE"),
    ("THUNDER", 3, 10, "DISADVANTAGE"),
    ("FIRE", 3, 0, "NORMAL"),
    ("THUNDER", 0, 0, "NORMAL"),
])
def test_sonic_cage_thunder_only_penalizes_the_next_cage_save(kind, amount, temp, expected):
    from combat.ext.sound_cage import THUNDER
    engine, foe, action = _sonic_cage()
    foe.temporary_hp = temp
    engine._commit_damage(foe, amount, kind, "test:damage", ME, None, reaction_depth=0)
    # An unrelated CON save must neither receive nor consume the cage penalty.
    assert engine._roll_save(foe, "CON", 50, "test:other").mode == "NORMAL"
    rolls = _cage_end_turn(engine)
    assert len(rolls) == 1 and rolls[0]["mode"] == expected
    assert _held(foe, "condition:typed.restrained")  # failed repeat retains the cage
    assert not _held(foe, THUNDER)
    assert _cage_end_turn(engine)[0]["mode"] == "NORMAL"


def test_sonic_cage_no_thunder_at_cast_and_immunity_does_not_trigger_penalty():
    from combat.ext.sound_cage import THUNDER
    engine, foe, action = _sonic_cage()
    # A modifier is the engine's ordinary immunity representation.
    engine._add_modifier(foe, "test:immune", "damage_immunity", "set", "THUNDER", "self", expires_on=None)
    engine._commit_damage(foe, 3, "THUNDER", "test:damage", ME, None, reaction_depth=0)
    assert not _held(foe, THUNDER)
    assert _cage_end_turn(engine)[0]["mode"] == "NORMAL"


def test_sonic_cage_success_ends_only_its_restraint_and_tracking():
    from combat.ext.sound_cage import REPEAT, THUNDER
    engine, foe, action = _sonic_cage()
    engine._apply_condition(foe, "condition:typed.restrained", "test:other_restraint", ME,
                            expires_on=None, data={})
    engine._commit_damage(foe, 3, "THUNDER", "test:damage", ME, None, reaction_depth=0)
    foe.saving_throws["CON"] = 100
    assert _cage_end_turn(engine)[0]["success"]
    assert not _held(foe, REPEAT) and not _held(foe, THUNDER)
    assert [c.source_definition_id for c in _held(foe, "condition:typed.restrained")] == ["test:other_restraint"]


def test_sonic_cage_new_thunder_refreshes_one_pending_penalty_and_loss_of_cage_cleans_it():
    from combat.ext.sound_cage import REPEAT, THUNDER
    engine, foe, action = _sonic_cage()
    for _ in range(2):
        engine._commit_damage(foe, 3, "THUNDER", "test:damage", ME, None, reaction_depth=0)
    assert len(_held(foe, THUNDER)) == 1
    engine._remove_condition(foe, "condition:typed.restrained", "test:freed")
    assert not _held(foe, REPEAT) and not _held(foe, THUNDER)


def test_sonic_cage_pending_penalty_is_bound_to_its_caster():
    from combat.ext.sound_cage import pending
    engine, foe, action = _sonic_cage()
    engine._commit_damage(foe, 3, "THUNDER", "test:damage", FOE, None, reaction_depth=0)
    assert pending(foe, ME) and not pending(foe, FOE)


def test_sonic_cage_thunder_disadvantage_cancels_save_advantage():
    engine, foe, action = _sonic_cage()
    engine._apply_condition(foe, "condition:typed.test_save_advantage", "test:ward", FOE,
                            expires_on=None, data={"rule": {"save_mode": {"CON": "ADVANTAGE"}}})
    engine._commit_damage(foe, 3, "THUNDER", "test:damage", ME, None, reaction_depth=0)
    assert _cage_end_turn(engine)[0]["mode"] == "NORMAL"


def test_sonic_cage_concentration_loss_removes_repeat_and_pending_penalty():
    from combat.ext.sound_cage import REPEAT, THUNDER
    engine, foe, action = _sonic_cage()
    engine._commit_damage(foe, 3, "THUNDER", "test:damage", ME, None, reaction_depth=0)
    engine._end_concentration(engine.state.actors[ME], "test:end")
    assert not _held(foe, "condition:typed.restrained")
    assert not _held(foe, REPEAT) and not _held(foe, THUNDER)


def test_sonic_cage_defeated_holder_leaves_no_pending_penalty():
    from combat.ext.sound_cage import REPEAT, THUNDER
    engine, foe, action = _sonic_cage()
    engine._commit_damage(foe, foe.current_hp, "THUNDER", "test:damage", ME, None, reaction_depth=0)
    assert not foe.active
    assert not _held(foe, REPEAT) and not _held(foe, THUNDER)


def test_sonic_cage_repeat_rider_is_in_the_typing():
    assert not _authority_riders("TAL_SOUND_SONIC_CAGE")


def test_sonic_cage_thunder_survives_persistent_commit_and_reload(tmp_path):
    from combat.gate4_persistence import Gate4Persistence
    from combat.ext.sound_cage import REPEAT, THUNDER
    sheet = L1._sheet("TAL_SOUND_SONIC_CAGE", dc=50)
    sheet["ability_scores_and_statistics"]["technique_attack_bonus"] = 100
    sheet["ability_scores_and_statistics"]["primary_resource"]["maximum"] = 100
    bundle = compile_character(sheet, actor_id=ME)
    # Fixture-only Bonus Action seeds the cage's prerequisite through a committed
    # effect. Production Note's mark expires before the caster's next Action.
    import copy
    seed = copy.deepcopy(next(a for a in bundle["action_catalog"] if a["display_name"] == "Resonant Note: Deafen"))
    seed.update(source_definition_id="test:seed_resonance", display_name="Seed Resonance", economy="BONUS_ACTION")
    seed["parameters"]["typed"]["effects"] = [{"type": "mark", "mark": "Resonance",
        "applies_to": "target", "duration": {"kind": "until_removed"}}]
    bundle["action_catalog"].append(seed)
    bundle["actor_template"]["action_ids"].append(seed["source_definition_id"])
    from combat.canonical import canonical_sha256
    bundle["bundle_sha256"] = canonical_sha256({k: v for k, v in bundle.items() if k != "bundle_sha256"})
    foe_sheet = L1._sheet("TAL_SOUND_SONIC_CAGE")
    foe_sheet["ability_scores_and_statistics"]["hit_points"]["maximum"] = 900
    foe_bundle = compile_character(foe_sheet, actor_id=L1.ALLY)
    persistence = Gate4Persistence(ROOT, tmp_path)
    session = persistence.create_match(match_seed="R5-CAGE-PERSIST", typed_bundles=(bundle, foe_bundle),
        roster_setup={"primary_actor_ids": [ME, L1.ALLY],
                      "team_by_actor": {ME: "team:a", L1.ALLY: "team:b"},
                      "starting_positions": {ME: {"x": 3, "y": 6}, L1.ALLY: {"x": 4, "y": 6}}})

    def submit(name, target=None):
        candidate = next(c for c in session.engine.legal_candidates() if c.display_name == name
                         and (target is None or target in c.target_ids))
        session.submit_intent(ActionIntent(intent_id=f"cage-{session.engine.state.state_version}",
            decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
            state_version=candidate.state_version, actor_id=candidate.actor_id,
            target_ids=candidate.target_ids, destination=candidate.destination),
            primary_decision_record=None, reaction_provider=None)

    def caster_turn():
        while session.engine.state.current_actor_id != ME:
            submit("End turn")

    caster_turn()
    submit("Seed Resonance", L1.ALLY)
    submit("Sonic Cage", L1.ALLY)
    submit("End turn")
    caster_turn()
    submit("Resonant Note: Deafen", L1.ALLY)
    foe = session.engine.state.actors[L1.ALLY]
    assert _held(foe, REPEAT) and len(_held(foe, THUNDER)) == 1
    saved = [c.model_dump(mode="json") for c in foe.conditions.values()
             if c.condition_id in {REPEAT, THUNDER}]
    session = persistence.load_match(session.match_id)
    foe = session.engine.state.actors[L1.ALLY]
    assert [c.model_dump(mode="json") for c in foe.conditions.values()
            if c.condition_id in {REPEAT, THUNDER}] == saved
    before = len(session.engine.events)
    submit("End turn")
    submit("End turn")
    rolls = [e.payload for e in session.engine.events[before:] if e.event_type == "SAVE_ROLLED"
             and "SONIC_CAGE" in e.payload.get("reason", "")]
    assert len(rolls) == 1 and rolls[0]["mode"] == "DISADVANTAGE"
    session = persistence.load_match(session.match_id)
    assert not _held(session.engine.state.actors[L1.ALLY], THUNDER)


def test_sonic_cage_old_typing_cannot_apply_the_thunder_rider():
    import copy
    from combat.ext.sound_cage import THUNDER
    authority = json.loads(Path(TYPED_AUTHORITY).read_bytes())
    # The pre-fix/old-saved-fight contract, without depending on Git history in CI.
    cage = authority["mechanics"]["TAL_SOUND_SONIC_CAGE"]
    old_restraint = copy.deepcopy(cage["effects"][0]["on_fail"][0])
    old_restraint["repeat_save"] = {"ability": "CON", "when": "end"}
    cage["effects"][0]["on_fail"] = [old_restraint]
    engine = _engine(compile_character(L1._sheet("TAL_SOUND_SONIC_CAGE", dc=50),
                                      actor_id=ME, typed_authority=authority))
    from combat.typed_executor import Context, run_effects
    me, foe = engine.state.actors[ME], _tough(engine)
    action = next(a for a in engine.action_catalog.values() if a.display_name == "Sonic Cage")
    run_effects(Context(engine, me, action, None, action.parameters["typed"], [foe], foe, {}),
                [{"type": "mark", "mark": "Resonance", "applies_to": "target",
                  "duration": {"kind": "until_removed"}}])
    _use(engine, "Sonic Cage", FOE)
    engine._commit_damage(foe, 3, "THUNDER", "test:damage", ME, None, reaction_depth=0)
    assert not _held(foe, THUNDER)
    assert _cage_end_turn(engine)[0]["mode"] == "NORMAL"


def test_sound_sovereign_note_asks_for_one_optional_second_creature():
    from types import SimpleNamespace
    engine = _engine(_bundle(["TAL_SOUND_SOUND_SOVEREIGN_INCARNATION"]), allies=(L1._ally_bundle(),))
    foe = _tough(engine)
    ally = engine.state.actors[L1.ALLY]
    ally.armor_class = -50
    name = "Resonant Note: Deafen (Sound-Sovereign Incarnation)"
    assert name not in _names(engine)
    _use(engine, "Sound-Sovereign Incarnation")
    _ready(engine)
    original = engine._reaction_decision
    calls = []

    def answer(intent, checkpoint, actor_id, choice_id, **kw):
        if choice_id == 'choice:needle.sound_second_note':
            context = kw['context']
            calls.append(context)
            assert context['minimum'] == 0 and context['maximum'] == 1 and context['allow_decline']
            assert context['name'] == 'Sound-Sovereign Incarnation'
            assert 'Resonant Note' in context['prompt'] and foe.display_name in context['prompt']
            assert FOE not in context['needle_options']
            return SimpleNamespace(selection='USE', option_ids=(L1.ALLY,))
        return original(intent, checkpoint, actor_id, choice_id, **kw)

    engine._reaction_decision = answer
    events = _use(engine, name, FOE)
    assert calls and _resonance(foe) and _resonance(ally)
    attacks = [e for e in events if e.event_type == 'ATTACK_ROLLED' and e.actor_id == ME]
    assert {e.target_ids[0] for e in attacks} == {FOE, L1.ALLY} and len(attacks) == 2


def test_sound_strike_riders_are_not_offered_on_ranged_resonant_note():
    for mid in ('TAL_SOUND_BODY_RESONANCE_STRIKE', 'TAL_SOUND_THUNDER_MERIDIAN_STRIKE'):
        engine = _engine(_melee_bundle([mid]))
        assert not any(n.startswith('Resonant Note') and ('Body Resonance Strike' in n or 'Thunder-Meridian Strike' in n)
                       for n in _names(engine))
        assert any('Fu (Short Axe) attack +' in n for n in _names(engine))


# ---------------------------------------------------------------------------------------------------------------- Smoke


def _aim(engine, name, target):
    candidate = next(c for c in engine.legal_candidates() if c.display_name == name and c.target_ids == (target,))
    before = len(engine.events)
    engine.execute_intent(ActionIntent(intent_id='lane5-aim', decision_id=candidate.decision_id,
                                      candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                      actor_id=ME, target_ids=candidate.target_ids, destination=candidate.destination))
    return engine.events[before:]


def test_black_lung_cloud_only_saves_on_entry_or_start_and_lasts_one_round():
    for dc, poisoned in ((50, True), (1, False)):
        engine = _engine(_bundle(['TAL_SMOKE_BLACK_LUNG_CLOUD'], dc=dc))
        me, foe = engine.state.actors[ME], _tough(engine)
        qi = me.resources['resource:core.qi']
        before_state, first_event = engine.state.model_copy(deep=True), len(engine.events)
        _use(engine, _place(engine, 'Smoke Veil + Black-Lung Cloud', foe.position))
        assert me.resources['resource:core.qi'] == qi - 1
        assert not _held(foe, 'condition:typed.poisoned') and engine._effective_speed(foe) == foe.speed_ft
        (cloud,) = [z for z in zones.typed_zones(engine) if z.trigger_profile.get('smoke_choking_until_owner_turn')]
        assert cloud.duration_rounds == 10 and cloud.concentration_link
        assert cloud.trigger_profile.get('obscured') == 'light'
        from combat.gate3_reducer import Gate3EventReducer
        reducer = Gate3EventReducer()
        for event in engine.events[first_event:]:
            if event.event_type == 'ZONE_CREATED':
                reducer.apply_event(before_state, event)
        assert before_state.zones[cloud.zone_id].model_dump(mode='json') == cloud.model_dump(mode='json')
        OBJ.force_d20(engine, 15, 19)
        zones.on_turn_start(engine, foe)
        assert bool(_held(foe, 'condition:typed.poisoned')) == poisoned
        assert engine._effective_speed(foe) == foe.speed_ft - (0 if poisoned else 10)
        effects = [*foe.conditions.values(), *foe.modifiers.values()]
        affected = [e for e in effects if e.source_definition_id == cloud.source_definition_id]
        assert affected and all(e.expires_on == 'START_OF_SELF_NEXT_TURN' for e in affected)
        engine.state.round_number += 1
        # A round number rollover before the caster's next turn does not end the one-round choke early.
        from combat.ext.smoke_riders import choke_save
        action = engine.action_catalog[cloud.source_definition_id]
        ctx = typed_executor.Context(engine, me, action, None, {'numbers': {'save_dc': 50}}, [foe], foe, {})
        before = len(engine.rolls)
        choke_save(ctx, cloud.trigger_profile['triggers'][0]['effects'][0])
        assert len(engine.rolls) > before
        me.turns_started += 1
        zones.on_turn_start(engine, me)
        assert cloud.active
        foe.conditions.clear()
        foe.modifiers.clear()
        before = len(engine.rolls)
        zones.on_turn_start(engine, foe)
        assert not [r for r in engine.rolls[before:] if r.reason.startswith('SAVE:')]
        assert not _held(foe, 'condition:typed.poisoned') and engine._effective_speed(foe) == foe.speed_ft
        engine._end_concentration(me, 'lane5-test-end')
        assert not cloud.active


def _heal(engine, target, amount=20):
    action = next(iter(engine.action_catalog.values()))
    ctx = typed_executor.Context(engine, target, action, None, {'numbers': {}}, [target], target, {})
    typed_executor.run_effects(ctx, [{'type': 'healing', 'applies_to': 'target', 'flat': amount}])


def test_cinder_without_flame_denies_healing_only_on_a_hit_inside_your_veil():
    for inside, dc, stopped in ((True, 50, True), (False, 50, False), (True, 1, False)):
        engine = _engine(_bundle(['TAL_SMOKE_CINDER_WITHOUT_FLAME', 'TAL_SMOKE_CINDER_WISP'], dc=dc))
        foe = _tough(engine)
        if inside:
            _use(engine, _place(engine, 'Smoke Veil', foe.position))
            _ready(engine)
        OBJ.force_d20(engine, 15, 19)
        _use(engine, 'Cinder Wisp')
        hp = foe.current_hp
        _heal(engine, foe)
        assert (foe.current_hp == hp) == stopped
        if stopped:
            (denial,) = [m for m in foe.modifiers.values() if m.target_field == 'healing_reduction']
            assert denial.expires_on == 'START_OF_SOURCE_NEXT_TURN'


def test_cinder_without_flame_miss_does_not_force_a_save_or_prevent_healing():
    engine = _engine(_bundle(['TAL_SMOKE_CINDER_WITHOUT_FLAME', 'TAL_SMOKE_CINDER_WISP'], dc=50))
    foe = _tough(engine)
    foe.current_hp -= 40
    _use(engine, _place(engine, 'Smoke Veil', foe.position))
    _ready(engine)
    OBJ.force_d20(engine, 1, 1)
    start = len(engine.rolls)
    _use(engine, 'Cinder Wisp')
    assert not [r for r in engine.rolls[start:] if r.reason.startswith('SAVE:')]
    hp = foe.current_hp
    _heal(engine, foe)
    assert foe.current_hp > hp


def test_incense_calm_is_one_cp_and_only_targets_inside_your_own_smoke():
    engine = _engine(_bundle(['TAL_SMOKE_INCENSE_CALM']), allies=(L1._ally_bundle(),))
    me, ally = engine.state.actors[ME], engine.state.actors[L1.ALLY]
    assert not any(n.startswith('Incense Calm') for n in _names(engine))
    # At CL 5 this is a run of two connected cubes, not the old single cube.
    # Aim at the caster so the run covers both recipients; prove membership
    # rather than assuming the old cube's half-open cells still apply.
    _use(engine, _place(engine, 'Smoke Veil', me.position))
    from combat.ext.smoke_riders import inside
    assert inside(engine, me, ME) and inside(engine, ally, ME)
    _ready(engine)
    qi = me.resources['resource:core.qi']
    _aim(engine, 'Incense Calm (ally)', L1.ALLY)
    assert me.resources['resource:core.qi'] == qi - 1 and ally.temporary_hp == 6 and me.temporary_hp == 0
    assert any(c.condition_id == 'condition:typed.save_against' for c in ally.conditions.values())
    _foe_effects(engine, L1.ALLY, [{'type': 'save', 'ability': 'wis', 'on_fail': [
        {'type': 'condition', 'condition': 'frightened', 'applies_to': 'target'}]}])
    assert not any(c.condition_id == 'condition:typed.save_against' for c in ally.conditions.values())
    _ready(engine)
    _aim(engine, 'Incense Calm', ME)
    assert me.temporary_hp == 6 and me.resources['resource:core.qi'] == qi - 2


def test_censer_court_calm_offers_an_optional_second_target_inside_smoke():
    from types import SimpleNamespace
    engine = _engine(_bundle(['TAL_SMOKE_CENSER_COURT_METHOD',
                             'TAL_SMOKE_SMOKE_DOMAIN_COURT_OF_HIDDEN_WITNESSES', 'TAL_SMOKE_INCENSE_CALM']),
                     allies=(L1._ally_bundle(),))
    name = 'Incense Calm (Censer Court Method)'
    assert name not in _names(engine)
    me, ally = engine.state.actors[ME], engine.state.actors[L1.ALLY]
    _use(engine, _place(engine, 'Smoke Domain: Court of Hidden Witnesses', me.position))
    _ready(engine)
    original = engine._reaction_decision

    def answer(intent, checkpoint, actor_id, choice_id, **kw):
        if choice_id == 'choice:needle.incense_calm':
            assert kw['context']['maximum'] == 1 and kw['context']['allow_decline']
            assert kw['context']['name'] == 'Censer Court Method'
            assert 'Incense Calm' in kw['context']['prompt'] and me.display_name in kw['context']['prompt']
            return SimpleNamespace(selection='USE', option_ids=(L1.ALLY,))
        return original(intent, checkpoint, actor_id, choice_id, **kw)

    engine._reaction_decision = answer
    qi = me.resources['resource:core.qi']
    _aim(engine, name, ME)
    assert me.resources['resource:core.qi'] == qi - 1
    assert me.temporary_hp == ally.temporary_hp == 6


def test_smoke_riders_already_run_by_the_core_and_smoke_step_are_removed():
    for mid in ('TAL_SMOKE_CINDER_WISP', 'TAL_SMOKE_SMOKE_STEP'):
        assert not _authority_riders(mid)
    # Cinder Wisp's CL dice and the hit's expiring Trace are exercised by test_review_sw-smoke.
    # Smoke Step's direct built action (the compiler's modifiers don't see this action) already uses 20 feet at CL 5.
    for cl, distance in ((1, 15), (5, 20)):
        engine = _engine(_bundle(['TAL_SMOKE_SMOKE_STEP'], cl=cl))
        action = next(a for a in engine.action_catalog.values() if a.display_name == 'Slip the Chimney Path' and a.owner_id == ME)
        assert next(e for e in action.parameters['typed']['effects'] if e['type'] == 'movement')['distance_ft'] == distance
