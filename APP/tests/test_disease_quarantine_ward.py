"""Quarantine Ward's optional paid Containment behavior at the real table boundary."""

from __future__ import annotations

import json

import pytest

from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import ActionDefinition, EconomyKind, Position
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet

WARD = "tianxia.talent.disease.quarantine_ward"
VEIL = "DISEASE_BASE_RAISE_THE_QUARANTINE_VEIL"
SOW = "DISEASE_BASE_SOW_THE_FEVER_SEED"
OWNER, SELECTED, UNSELECTED, OUTSIDE = ("actor:qw:" + name for name in ("owner", "selected", "unselected", "outside"))
TEAMS = {OWNER: "team:disease", SELECTED: "team:pestilence", UNSELECTED: "team:pestilence", OUTSIDE: "team:pestilence"}
POSITIONS = {OWNER: {"x": 5, "y": 5}, SELECTED: {"x": 6, "y": 5}, UNSELECTED: {"x": 5, "y": 6}, OUTSIDE: {"x": 9, "y": 5}}
SEED = "MGR-T17-QUARANTINE-WARD"


def _bundle(actor_id, talents=(), *, dc=30, cha=0):
    doc = sheet(list(talents), cl=8, dc=dc, name=actor_id)
    doc["ability_scores_and_statistics"]["technique_attack_bonus"] = 100
    bundle = compile_character(doc, actor_id=actor_id)
    bundle["actor_template"]["saving_throws"]["CHA"] = cha
    bundle["actor_template"]["armor_class"] = 1
    return bundle


def _with_test_teleport(bundle):
    owner_id = bundle["actor_id"]
    bundle["action_catalog"].append(ActionDefinition(
        source_definition_id=f"test:quarantine_ward_teleport:{owner_id}",
        display_name="Test Teleport",
        owner_id=owner_id,
        economy=EconomyKind.ACTION,
        resolution_kind="TYPED",
        target_kind="SELF",
        range_ft=20,
        parameters={"expected_damage": 0,
                    "typed": {"effects": [{"type": "teleport", "applies_to": "self", "distance_ft": 20,
                                            "evidence": "Test Teleport moves its user up to 20 feet."}]}}).model_dump(mode="json"))
    return bundle


def _fight(tmp_path, *, ward=True, spread_actions=False):
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    owner_talents = [VEIL, SOW, WARD] if ward else [VEIL, SOW]
    bundles = [_bundle(OWNER, owner_talents),
               _with_test_teleport(_bundle(SELECTED, cha=-100)),
               _with_test_teleport(_bundle(UNSELECTED, cha=100)),
               _with_test_teleport(_bundle(OUTSIDE, cha=100))]
    if spread_actions:
        for bundle in bundles:
            actor_id = bundle['actor_id']
            if actor_id not in (OWNER, OUTSIDE):
                continue
            bundle['actor_template']['action_ids'].append(f'test:spread:{actor_id}')
            bundle['action_catalog'].append(ActionDefinition(
                source_definition_id=f'test:spread:{actor_id}', display_name='Test Spreading Infection',
                owner_id=actor_id, economy=EconomyKind.ACTION, resolution_kind='TYPED',
                target_kind='ANY_CREATURE', range_ft=60,
                parameters={'expected_damage': 0, 'typed': {'effects': [
                    {'type': 'disease_tokens', 'applies_to': 'target', 'count': 1,
                     'spread_origin_id': SELECTED if actor_id == OUTSIDE else OUTSIDE}]}}
            ).model_dump(mode='json'))
    mid = combat._finish_factory_match(
        bundles, list(TEAMS), TEAMS, POSITIONS,
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"],
        [OWNER], [SELECTED, UNSELECTED, OUTSIDE],
        control_modes={actor_id: "MANUAL" for actor_id in TEAMS}, match_seed=SEED,
        display_name="Quarantine Ward regression", maximum_rounds=20)["match_id"]
    return combat, table, mid


def _fresh(combat, mid):
    return CombatService(ROOT, combat.userdata_root)._load_session(mid)


def _turn(combat, table, mid, actor_id):
    for _ in range(2 * len(TEAMS)):
        state = table.state(mid)
        current = _fresh(combat, mid).engine.state.actors[state["menu"]["actor_id"]]
        if state["menu"]["actor_id"] == actor_id and current.action_available:
            return state
        _submit(table, mid, state, state["menu"]["end_turn"])
    raise AssertionError(f"{actor_id} never received a turn")


def _submit(table, mid, state, candidate, choose=lambda prompt: None):
    menu = state["menu"]
    answers = []
    result = table.act(mid, candidate, menu["decision_id"], menu["state_version"], state["last_sequence"], answers)
    while result["status"] == "REACTION_REQUIRED":
        prompt = result["reaction"]
        from combat.placement_menu import CHOICE as PLACE
        from combat.ext.needle import cell_id
        picked = ([cell_id(Position(**POSITIONS[OWNER]), include_altitude=True)]
                  if prompt["context"].get("reaction_source_id") == PLACE else choose(prompt))
        answer = {**prompt["context"], "selection": "DECLINE" if picked is None else "USE",
                  "option_ids": list(picked or [])}
        answers.append(answer)
        result = table.act(mid, candidate, menu["decision_id"], menu["state_version"], state["last_sequence"], answers)
    assert result["status"] == "COMMITTED", result
    return result["state"]


def _raise_ward(combat, table, mid):
    choice = "choice:needle.quarantine_ward_recipients"
    state = _turn(combat, table, mid, OWNER)
    groups = [g for g in state["menu"]["actions"] if "Containment Mode + Quarantine Ward" in g["label"]]
    assert groups
    candidate = (groups[0]["options"][0] if groups[0].get("placement_picker") else
                 next(o for o in groups[0]["options"] if o.get("destination") is not None
                      and Position(**o["destination"]) == Position(**POSITIONS[OWNER])))

    def choose(prompt):
        if prompt["context"].get("reaction_source_id") == choice:
            return [SELECTED]
        return None

    return _submit(table, mid, state, candidate["candidate_id"], choose=choose)


def _sow(combat, table, mid, target, *, allow=None):
    state = _turn(combat, table, mid, OWNER)
    engine = _fresh(combat, mid).engine
    strike = next(c for c in engine.legal_candidates()
                  if c.source_definition_id.endswith(SOW) and c.actor_id == OWNER and target in c.target_ids)

    def choose(prompt):
        if str(prompt["context"].get("reaction_source_id", "")).startswith("choice:needle.quarantine_spread:"):
            return ["allow"] if allow else ["contain"]
        return None

    _submit(table, mid, state, strike.candidate_id, choose=choose)


def test_quarantine_ward_payment_selection_source_resistance_spread_permissions_and_reload(tmp_path):
    from combat.factory_compiler import TYPED_AUTHORITY

    compiled = json.loads(TYPED_AUTHORITY.read_bytes())["mechanics"][WARD]
    assert compiled["riders"] == ["The veil becomes a proper ward.", "The ward does not physically trap creatures."]
    assert any(row.get("type") == "disease_quarantine_ward"
               for row in (compiled.get("modifier") or {}).get("effects") or [])

    combat, table, mid = _fight(tmp_path)
    before = _fresh(combat, mid).engine
    resource = next(resource for resource in before.state.actors[OWNER].resources if resource.endswith("qi"))
    balance = before.state.actors[OWNER].resources[resource]

    # A character without the talent has only the normal Containment action.
    nonowner = before.state.actors[SELECTED]
    assert not any("Quarantine Ward" in before.action_catalog[aid].display_name for aid in nonowner.action_ids)
    _raise_ward(combat, table, mid)
    engine = _fresh(combat, mid).engine
    ward = next(zone for zone in engine.state.zones.values()
                if isinstance((zone.trigger_profile or {}).get("quarantine_ward"), dict))
    assert engine.state.actors[OWNER].resources[resource] == balance - 4
    assert ward.trigger_profile["quarantine_ward"]["selected"] == [SELECTED]
    # The saved area and recipient choice survive a cold service reload.
    assert _fresh(combat, mid).engine.state.zones[ward.zone_id].trigger_profile["quarantine_ward"]["selected"] == [SELECTED]

    # Real Disease damage is halved only for the selected creature. Both attacks and the token placement use TabletopService.
    _sow(combat, table, mid, SELECTED)
    engine = _fresh(combat, mid).engine
    assert engine.state.actors[SELECTED].current_hp < engine.state.actors[SELECTED].maximum_hp
    assert _fresh(combat, mid).engine.state.zones[ward.zone_id].trigger_profile["quarantine_ward"]["selected"] == [SELECTED]
    _sow(combat, table, mid, UNSELECTED)
    engine = _fresh(combat, mid).engine
    from combat import typed_reactions
    sow = next(a for a in engine.state.actors[OWNER].action_ids if a.endswith(SOW))
    # Direct defense checks show the selected creature taking half Poison/Necrotic Disease damage, while an
    # unselected creature in the same area and unrelated Poison damage take full damage.
    for kind in ("POISON", "NECROTIC"):
        assert typed_reactions.defend(engine, engine.state.actors[SELECTED], 12, kind, sow, OWNER) == 6
        assert typed_reactions.defend(engine, engine.state.actors[UNSELECTED], 12, kind, sow, OWNER) == 12
    assert typed_reactions.defend(engine, engine.state.actors[SELECTED], 12, "POISON",
                                  "POISON_BASE_DELIVER_THE_DOSE", OWNER) == 12

    # Direct token placement from inside also requires the Ward owner\'s permission.
    _sow(combat, table, mid, OUTSIDE, allow=False)
    engine = _fresh(combat, mid).engine
    from combat.ext.disease import tokens
    assert tokens(engine, engine.state.actors[OWNER], engine.state.actors[OUTSIDE]) == 0
    # Sow can use another attack on the same turn, but may place only one token per creature per turn.
    # A veto does not undo that attempt; ask again on a genuinely new turn.
    state = table.state(mid)
    assert state["menu"]["actor_id"] == OWNER
    _submit(table, mid, state, state["menu"]["end_turn"])
    _sow(combat, table, mid, OUTSIDE, allow=True)
    engine = _fresh(combat, mid).engine
    assert tokens(engine, engine.state.actors[OWNER], engine.state.actors[OUTSIDE]) == 1


def test_owner_can_decline_the_optional_ward_and_keep_base_containment_cost(tmp_path):
    combat, table, mid = _fight(tmp_path)
    before = _fresh(combat, mid).engine
    resource = next(resource for resource in before.state.actors[OWNER].resources if resource.endswith("qi"))
    balance = before.state.actors[OWNER].resources[resource]
    state = _turn(combat, table, mid, OWNER)
    group = next(group for group in state["menu"]["actions"]
                 if group["label"] == "Raise the Quarantine Veil: Containment Mode")
    option = (group["options"][0] if group.get("placement_picker") else
              next(row for row in group["options"] if row.get("destination") is not None
                   and Position(**row["destination"]) == Position(**POSITIONS[OWNER])))
    _submit(table, mid, state, option["candidate_id"])
    after = _fresh(combat, mid).engine
    assert after.state.actors[OWNER].resources[resource] == balance - 2
    assert not any(isinstance((zone.trigger_profile or {}).get("quarantine_ward"), dict)
                   for zone in after.state.zones.values())


def test_quarantine_ward_teleport_exit_saves_use_authored_boundary_and_do_not_trap_walkers(tmp_path):
    combat, table, mid = _fight(tmp_path)
    _raise_ward(combat, table, mid)
    _sow(combat, table, mid, SELECTED)  # persisted token for the later cold reload and walking check
    engine = _fresh(combat, mid).engine
    from combat import typed_executor
    from combat.ext.disease import add_tokens, tokens
    ward = next(zone for zone in engine.state.zones.values()
                if isinstance((zone.trigger_profile or {}).get("quarantine_ward"), dict))
    owner, selected, unselected, successful = (engine.state.actors[actor_id]
                                                for actor_id in (OWNER, SELECTED, UNSELECTED, OUTSIDE))
    assert tokens(engine, owner, selected) == 1  # _sow already persisted the token; do not seed it twice.

    def teleport(actor, destination):
        action = next(a for a in engine.action_catalog.values()
                      if a.source_definition_id == f"test:quarantine_ward_teleport:{actor.entity_id}")
        ctx = typed_executor.Context(engine, actor, action, None, action.parameters["typed"], [actor], actor)
        typed_executor.teleport_subject(ctx, actor, destination)

    outside = Position(x=9, y=5)
    teleport(selected, outside)
    assert selected.position != outside  # a token bearer fails the ward owner's high-DC save
    assert tokens(engine, owner, selected) == 1

    # The token-bearing creature may teleport within the authored area without a save.
    inside = Position(x=6, y=4)
    teleport(selected, inside)
    assert selected.position == inside

    # A creature without a token exits freely by teleport.
    walk_destination = Position(x=8, y=6)
    teleport(unselected, walk_destination)
    assert unselected.position == walk_destination

    # A successful Charisma save permits the token-bearing exit.
    successful.position = Position(x=5, y=6)
    add_tokens(engine, owner, successful, 1, "test:seed")
    successful_outside = Position(x=9, y=6)
    teleport(successful, successful_outside)
    assert successful.position == successful_outside
    assert ward.active and tokens(engine, owner, successful) == 1

    # The Ward does not trap a token bearer who walks out through the table's ordinary move candidates.
    from combat.spatial_areas import zone_contains
    state = _turn(combat, table, mid, SELECTED)
    move_engine = _fresh(combat, mid).engine
    move_subject = move_engine.state.actors[SELECTED]
    move_ward = move_engine.state.zones[ward.zone_id]
    held_before_walk = tokens(move_engine, move_engine.state.actors[OWNER], move_subject)
    assert held_before_walk > 0
    move = next(row for row in state["menu"]["moves"]
                if not zone_contains(move_engine, move_subject, move_ward,
                                     at=Position(**row["destination"])))
    menu = state["menu"]
    result = table.act(mid, move["candidate_id"], menu["decision_id"], menu["state_version"],
                       state["last_sequence"], [])
    assert result["status"] == "COMMITTED", result
    after = _fresh(combat, mid).engine
    assert after.state.actors[SELECTED].position != Position(**POSITIONS[SELECTED])
    assert tokens(after, after.state.actors[OWNER], after.state.actors[SELECTED]) == held_before_walk


@pytest.mark.parametrize("source_owner,allow", [(OUTSIDE, False), (OUTSIDE, True), (OWNER, False)])
def test_spread_boundary_uses_bearer_not_token_owner_after_table_reload(tmp_path, source_owner, allow):
    combat, table, mid = _fight(tmp_path, spread_actions=True)
    _raise_ward(combat, table, mid)
    state = _turn(combat, table, mid, source_owner)
    engine = _fresh(combat, mid).engine
    candidate = next(c for c in engine.legal_candidates()
                     if c.source_definition_id == f"test:spread:{source_owner}" and OUTSIDE in c.target_ids)
    prompts = []

    def choose(prompt):
        if "quarantine_spread:" in prompt["context"]["reaction_source_id"]:
            prompts.append(prompt)
            return ["allow" if allow else "contain"]
        return None

    _submit(table, mid, state, candidate.candidate_id, choose)
    from combat.ext.disease import tokens
    loaded = _fresh(combat, mid).engine
    # Outside owner / inside bearer crosses; inside owner / outside bearer does not.
    assert len(prompts) == int(source_owner == OUTSIDE)
    assert tokens(loaded, loaded.state.actors[source_owner], loaded.state.actors[OUTSIDE]) == int(
        allow or source_owner == OWNER)


def test_blocked_multitarget_mark_does_not_mutate_row_or_poison_later_placements(tmp_path, monkeypatch):
    """A per-recipient veto must not corrupt shared authored mark data."""
    combat, table, mid = _fight(tmp_path)
    _raise_ward(combat, table, mid)
    engine = _fresh(combat, mid).engine
    from combat import typed_executor
    from combat.ext import rider_choices
    from combat.ext.disease import tokens

    engine.state.actors[UNSELECTED].position = Position(x=9, y=6)
    answers = iter([["contain"], ["allow"], ["allow"]])
    seen = []

    def choose(_engine, _owner, _checkpoint, _name, options, **kwargs):
        seen.append(kwargs["subject"].entity_id)
        return next(answers)

    monkeypatch.setattr(rider_choices, "pick", choose)
    owner = engine.state.actors[OWNER]
    action = next(engine.action_catalog[a] for a in owner.action_ids
                  if engine.action_catalog[a].source_definition_id.endswith(SOW))
    row = {"type": "mark", "mark": "Contagion Token", "applies_to": "target",
           "duration": {"kind": "until_removed"}}
    original = json.loads(json.dumps(row))

    def apply_mark(ids):
        targets = [engine.state.actors[actor_id] for actor_id in ids]
        typed_executor.run_effects(
            typed_executor.Context(engine, owner, action, None, {}, targets, None, {}), [row])
        assert row == original

    apply_mark([OUTSIDE, UNSELECTED, SELECTED])
    assert seen == [OUTSIDE, UNSELECTED]
    assert tokens(engine, owner, engine.state.actors[OUTSIDE]) == 0
    assert tokens(engine, owner, engine.state.actors[UNSELECTED]) == 1
    assert tokens(engine, owner, engine.state.actors[SELECTED]) == 1
    apply_mark([OUTSIDE])
    assert seen == [OUTSIDE, UNSELECTED, OUTSIDE]
    assert tokens(engine, owner, engine.state.actors[OUTSIDE]) == 1
    zone = next(zone for zone in engine.state.zones.values()
                if isinstance((zone.trigger_profile or {}).get("quarantine_ward"), dict))
    zone.active = False
    apply_mark([OUTSIDE])
    assert tokens(engine, owner, engine.state.actors[OUTSIDE]) == 2


def test_quarantine_ward_ai_owner_automatically_contains_outward_spread(tmp_path):
    """An AI Ward maker makes the default containment choice without a player prompt."""
    combat, table, mid = _fight(tmp_path)
    _raise_ward(combat, table, mid)
    engine = _fresh(combat, mid).engine
    engine.typed_control_modes[OWNER] = "LOCAL_AUTO"
    from combat.ext.disease import add_tokens, tokens

    source_owner, bearer = (engine.state.actors[actor_id] for actor_id in (OUTSIDE, SELECTED))
    add_tokens(engine, source_owner, source_owner, 1, "test:spreading-infection", origin=bearer)
    # The outside token owner supplied the source; the distinct bearer crossed the Ward boundary.
    assert tokens(engine, source_owner, source_owner) == 0


@pytest.mark.parametrize("allow", [False, True])
def test_ward_only_manual_owner_is_asked_on_ai_turn_after_cold_reload(tmp_path, monkeypatch, allow):
    combat, table, mid = _fight(tmp_path, spread_actions=True)
    assert OWNER not in _fresh(combat, mid).engine.typed_ask_reactors
    _raise_ward(combat, table, mid)
    _turn(combat, table, mid, OUTSIDE)
    combat.set_controller_mode(mid, actor_id=OUTSIDE, controller_mode="LOCAL_AUTO")
    combat = CombatService(ROOT, combat.userdata_root)
    table = TabletopService(combat, combat.userdata_root)
    session = combat._load_session(mid)
    assert OWNER in session.engine.typed_ask_reactors
    choose_primary = combat.controller.choose_primary_action

    def choose(context):
        candidate = next(c for c in context.legal_candidates
                         if c.source_definition_id == f"test:spread:{OUTSIDE}" and OUTSIDE in c.target_ids)
        return choose_primary(context.model_copy(update={"legal_candidates": (candidate,)}))

    monkeypatch.setattr(combat.controller, "choose_primary_action", choose)
    before = session.engine.state.model_dump(mode="json")
    paused = table.auto_step(mid, table.state(mid)["last_sequence"], [])
    assert paused["status"] == "REACTION_REQUIRED", paused
    prompt = paused["reaction"]
    assert prompt["context"]["reactor_id"] == OWNER
    assert "quarantine_spread:" in prompt["context"]["reaction_source_id"]
    assert "Quarantine Ward" in str(prompt) and "Test Spreading Infection" in str(prompt)
    assert _fresh(combat, mid).engine.state.model_dump(mode="json") == before
    repeated = table.auto_step(mid, table.state(mid)["last_sequence"], [])
    assert repeated["reaction"]["context"] == prompt["context"]
    answer = {**prompt["context"], "selection": "USE", "option_ids": ["allow" if allow else "contain"]}
    committed = table.auto_step(mid, table.state(mid)["last_sequence"], [answer])
    assert committed["status"] == "COMMITTED", committed
    from combat.ext.disease import tokens
    loaded = _fresh(combat, mid).engine
    assert tokens(loaded, loaded.state.actors[OUTSIDE], loaded.state.actors[OUTSIDE]) == int(allow)
