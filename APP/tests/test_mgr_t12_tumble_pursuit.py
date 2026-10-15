"""MGR-T12: printed movement clauses through journaled table commits and reloads."""
import pytest

from combat import ext, flight
from combat.ext import athletics
from combat.gate2_runtime_models import ActionDefinition, EconomyKind
from tests.auto8f1_table_support import OWNER, FOE, SECOND, fixture, candidate_id, move_candidate_id, reload_identical
from tests.test_a2_athletics import tumble_game, commit, explicit_move, own_rolls


def actions(bundles):
    for bundle in bundles:
        actor_id = bundle["actor_id"]
        template = bundle["actor_template"]
        template["speed_ft"] = 45
        template.setdefault("saving_throws", {})["WIS"] = -100
        if actor_id == OWNER:
            row = ActionDefinition(source_definition_id="action:test.t12.stop_transit", display_name="Test stop in ally transit",
                owner_id=actor_id, economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
                parameters={"free_primary":True,"typed":{"effects":[{"type":"condition",
                    "condition":"test_t12_stop_transit","applies_to":"self","expires_on":"END_OF_CURRENT_TURN"}],
                    "numbers":{},"riders":[],"duration":{"kind":"instant"}}})
            bundle["action_catalog"].append(row.model_dump(mode="json"))
            template["action_ids"].append(row.source_definition_id)
        for kind in ("short", "long"):
            row = ActionDefinition(source_definition_id=f"action:test.t12.rest.{kind}.{actor_id}",
                display_name=f"Verified {kind} rest", owner_id=actor_id, economy=EconomyKind.NONE,
                resolution_kind="TYPED", target_kind="SELF",
                parameters={"free_primary":True,"typed":{"effects":[{"type":"rest_completed", "kind":kind,
                    "rest_id":f"test-rest:{kind}:{actor_id}"}],
                                     "numbers":{}, "riders":[], "duration":{"kind":"instant"}}})
            bundle["action_catalog"].append(row.model_dump(mode="json"))
            template["action_ids"].append(row.source_definition_id)


def finish(game):
    reload_identical(game["combat"], game["match_id"], game["userdata"])


@ext.effect("test_t12_offturn_move")
def offturn_move(ctx, eff):
    """A sealed fixture action grants the other actor willing native movement."""
    from combat.ext.granted_movement import choices, move
    actor = ctx.engine.state.actors[OWNER]
    destination_y = 7 if actor.position.y == 6 else 6
    candidate = next(c for c in choices(ctx.engine, actor, 20)
                     if c.destination.x == 3 and c.destination.y == destination_y and c.destination.z == 0)
    move(ctx.engine, actor, candidate, ctx.intent, 20, [], name="Test willing off-turn movement")


DIZZY_SOURCE_CONTEXTS = []
DIZZY_SOURCE_ALLOWANCES = []


@ext.hook("save_mode")
def t12_observe_offturn_save_source(engine, target, ability, dc, source_id, context=None):
    """Observe native save provenance without altering the save or using hidden rolls."""
    if source_id == athletics.DIZZYING and engine.state.current_actor_id != OWNER:
        DIZZY_SOURCE_CONTEXTS.append((context or {}).get("source_actor_id"))
        source = engine.state.actors.get((context or {}).get("source_actor_id"))
        if source is not None:
            from combat.movement_steps import context as movement_context
            DIZZY_SOURCE_ALLOWANCES.append((source.movement_remaining_ft, movement_context(engine,source).get("allowance_ft")))
    return None


def test_offturn_willing_exits_ask_owner_and_repeat_without_turn_quota(tmp_path):
    DIZZY_SOURCE_CONTEXTS.clear()
    DIZZY_SOURCE_ALLOWANCES.clear()
    def grants(bundles):
        actions(bundles)
        for bundle in bundles:
            if bundle["actor_id"] != FOE:
                continue
            row = ActionDefinition(source_definition_id="action:test.t12.grant", display_name="Test off-turn move",
                owner_id=FOE, economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
                parameters={"free_primary":True,"typed":{"effects":[{"type":"test_t12_offturn_move"}],
                                     "numbers":{},"riders":[],"duration":{"kind":"instant"}}})
            bundle["action_catalog"].append(row.model_dump(mode="json"))
            bundle["actor_template"]["action_ids"].append(row.source_definition_id)
    game = fixture(tmp_path, [athletics.DIZZYING], seed="T12-offturn", bundle_transform=grants)
    game["turn_of"](FOE)
    asks = []
    def choose(prompt, choice):
        asks.append(prompt)
        return [FOE]
    for _ in range(2):
        game["commit"](candidate_id(game["menu"](), "Test off-turn move"), choose)
        finish(game)
    assert len(asks) == 2
    assert all(p["context"]["reactor_id"] == OWNER for p in asks)
    engine = game["stored_engine"]()
    assert engine.state.current_actor_id == FOE
    assert len([e for e in engine.events if e.event_type == "SAVE_ROLLED" and e.actor_id == FOE]) == 2
    assert len([e for e in engine.events if e.event_type == "MOVEMENT_GRANTED"
                and e.source_definition_id == athletics.DIZZYING and e.payload["distance_ft"] == -10]) == 2
    assert DIZZY_SOURCE_CONTEXTS and all(source == OWNER for source in DIZZY_SOURCE_CONTEXTS)
    assert DIZZY_SOURCE_ALLOWANCES and all(pair == (10,10) for pair in DIZZY_SOURCE_ALLOWANCES)
    assert all(e.payload["granted_cost_ft"] == 15 for e in engine.events
               if e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == OWNER and "granted_cost_ft" in e.payload)


def test_adjacent_to_adjacent_exit_repeats_and_declining_is_free(tmp_path):
    game = fixture(tmp_path, [athletics.DIZZYING], seed="T12-adjacent", bundle_transform=actions)
    before = game["reload_owner"]().movement_remaining_ft
    asks = []
    def answer(prompt, choice):
        asks.append(choice)
        return [FOE]
    game["commit"](move_candidate_id(game["menu"](), 3, 7), answer)
    first = game["stored_engine"]()
    assert first.grid.distance_ft(first.state.actors[OWNER].position, first.state.actors[FOE].position) == 5
    assert game["reload_owner"]().movement_remaining_ft == before - 15
    finish(game)
    game["commit"](move_candidate_id(game["menu"](), 3, 6), answer)
    assert len(asks) == 2
    assert game["reload_owner"]().movement_remaining_ft == before - 30
    saves = [e for e in game["stored_engine"]().events if e.event_type == "SAVE_ROLLED" and e.actor_id == FOE]
    assert len(saves) == 2 and all(e.payload["reason"].endswith(":WIS") for e in saves)
    game["commit"](move_candidate_id(game["menu"](), 3, 7), lambda p,c: [])
    assert game["reload_owner"]().movement_remaining_ft == before - 35
    finish(game)


@pytest.mark.parametrize("kind", ["short", "long"])
def test_source_rest_clears_only_its_immunity_through_table_and_reload(tmp_path, kind):
    def saved(bundles):
        actions(bundles)
        for bundle in bundles:
            bundle["actor_template"].setdefault("saving_throws", {})["WIS"] = 100
    game = fixture(tmp_path, [athletics.DIZZYING], seed="T12-rest-"+kind,
                   talents_by_actor={SECOND:[athletics.DIZZYING]}, bundle_transform=saved, allies=(SECOND,),
                   places={OWNER:{"x":3,"y":6},FOE:{"x":4,"y":6},SECOND:{"x":5,"y":6}})
    game["commit"](move_candidate_id(game["menu"](), 3, 7), lambda p,c: [FOE])
    finish(game)
    engine = game["stored_engine"]()
    assert athletics._dizzy_immune_to(engine.state.actors[FOE], engine.state.actors[OWNER])
    game["turn_of"](SECOND)
    # The shared table helper's menu belongs to SECOND here; pick its own move.
    game["commit"](move_candidate_id(game["menu"](), 5, 7), lambda p,c: [FOE])
    finish(game)
    assert athletics._dizzy_immune_to(game["stored_engine"]().state.actors[FOE], game["stored_engine"]().state.actors[SECOND])
    # An unrelated rest cannot clear the source's receipt.
    game["turn_of"](FOE)
    game["commit"](candidate_id(game["menu"](), f"Verified {kind} rest"))
    finish(game)
    assert athletics._dizzy_immune_to(game["stored_engine"]().state.actors[FOE], game["reload_owner"]())
    game["to_owner"]()
    game["commit"](candidate_id(game["menu"](), f"Verified {kind} rest"))
    finish(game)
    assert not athletics._dizzy_immune_to(game["stored_engine"]().state.actors[FOE], game["reload_owner"]())
    assert athletics._dizzy_immune_to(game["stored_engine"]().state.actors[FOE], game["stored_engine"]().state.actors[SECOND])
    assert any(e.event_type == "PASSIVE_TRIGGERED" and e.actor_id == OWNER
               and e.payload.get("rest_completed") == 1
               and e.payload["rest_id"] == f"test-rest:{kind}:{OWNER}" and e.payload["kind"] == kind
               for e in game["stored_engine"]().events)
    game["commit"](candidate_id(game["menu"](), f"Verified {kind} rest"))
    finish(game)
    assert len([e for e in game["stored_engine"]().events if e.payload.get("rest_completed") == 1 and e.actor_id == OWNER]) == 1


def pursuit_game(tmp_path):
    return fixture(tmp_path, [athletics.PURSUIT], seed="T12-pursuit-"+tmp_path.name,
                   bundle_transform=actions, allies=(SECOND,),
                   places={OWNER:{"x":3,"y":6},FOE:{"x":3,"y":13},SECOND:{"x":4,"y":12}})


def pursuit_choice(choice, subject, benefit):
    """Choose the test's subject/benefit; leave other legal subjects unspent."""
    ids = [option['id'] for option in choice['options']]
    return [subject] if subject in ids else [benefit] if benefit in ids else []


def chosen_path(game, path, chooser):
    """Explicit native route through the same public pause/answer transport."""
    menu = game["menu"]()
    table, mid = game["table"], game["match_id"]
    quote = table.preview_move_path(mid, menu["decision_id"], menu["state_version"], OWNER, path)
    answers, prompts = [], []
    for _ in range(20):
        result = table.commit_move_path(mid, quote["candidate"]["candidate_id"], menu["decision_id"],
            menu["state_version"], OWNER, path, reactions=answers)
        if result["status"] == "COMMITTED":
            return prompts
        assert result["status"] == "REACTION_REQUIRED", result
        prompt = result["reaction"]
        prompts.append(prompt)
        answer = {**prompt["context"], "selection":"DECLINE"}
        if prompt.get("choice"):
            options = chooser(prompt["choice"])
            if options:
                answer.update(selection="USE", option_ids=options)
        answers.append(answer)
    raise AssertionError("route never committed")


def test_pursuit_ally_option_passes_in_the_same_triggering_route(tmp_path):
    game = pursuit_game(tmp_path)
    path = [{"x":3,"y":y} for y in range(6,11)] + [{"x":4,"y":y} for y in range(11,14)]
    before = game["reload_owner"]().movement_remaining_ft
    prompts = chosen_path(game, path, lambda c: pursuit_choice(c, SECOND, 'ally'))
    assert set(o['id'] for o in prompts[0]['choice']['options']) == {FOE, SECOND}
    assert set(o['id'] for o in prompts[1]['choice']['options']) == set(athletics.PURSUIT_LABELS)
    assert all([o['id'] for o in p['choice']['options']] == [FOE] for p in prompts[2:])
    assert game["reload_owner"]().position.y == 13
    assert game["reload_owner"]().movement_remaining_ft == before - 35
    assert not any(c.condition_id == athletics.PURSUIT_PASSAGE for c in game["reload_owner"]().conditions.values())
    finish(game)


def test_pursuit_oa_option_protects_later_steps_of_the_same_route(tmp_path):
    game = fixture(tmp_path, [athletics.PURSUIT], seed="T12-oa-route", bundle_transform=actions,
        places={OWNER:{"x":3,"y":6},FOE:{"x":3,"y":11},SECOND:{"x":9,"y":13}})
    path = [{"x":3,"y":y} for y in range(6,11)] + [{"x":2,"y":y} for y in range(10,14)]
    prompts = chosen_path(game, path, lambda c: [FOE] if FOE in [o["id"] for o in c["options"]] else ["no_oa"])
    assert len(prompts) == 2 and all(p.get("choice") for p in prompts), "no later OA prompt from the chosen creature"
    engine = game["stored_engine"]()
    assert engine.state.actors[FOE].reaction_available
    assert not any(e.event_type == "ATTACK_ROLLED" and e.actor_id == FOE for e in engine.events)
    assert athletics.flowing_pursuit_no_oa(engine, engine.state.actors[SECOND], engine.state.actors[OWNER]) is None
    finish(game)


@pytest.mark.parametrize("benefit,expected_height", [("jump",2),("ac",1)])
def test_pursuit_jump_choice_changes_jump_inside_its_triggering_route(tmp_path, benefit, expected_height):
    game = pursuit_game(tmp_path)
    engine = game["stored_engine"]()
    candidate = next(c for c in engine.legal_candidates() if c.metadata.get("movement_mode") == "jump"
                     and c.destination.x == 3 and c.destination.y == 10 and c.destination.z == 2)
    game["commit"](candidate.candidate_id,
        lambda p,c: pursuit_choice(c, SECOND, benefit))
    engine = game["stored_engine"]()
    move = [e for e in engine.events if e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == OWNER
            and e.payload.get("movement_mode") == "jump" and not e.payload.get("forced")][-1]
    assert max(p.get("z",0) for p in move.payload["path"]) == expected_height
    assert move.payload["jump_taken"] == 1
    assert not any(c.condition_id == athletics.PURSUIT_JUMP for c in game["reload_owner"]().conditions.values())
    finish(game)


def test_automatic_actor_selects_jump_during_runup_without_a_player_prompt():
    from tests.test_auto_athletics import _engine, _me, _use, PURSUIT
    engine = _engine([PURSUIT], walking_ft=50, foes=((3,13),(10,10)))
    actor = _me(engine)
    engine.typed_control_modes = {actor.entity_id:"LOCAL_AUTO"}
    from combat.gate2_runtime_models import ReactionDecision
    requests = []
    def automatic_transport(request):
        assert engine.typed_control_modes[request["reactor_id"]] == "LOCAL_AUTO"
        requests.append(request)
        assert request["extension_choice"]["automatic_use"] is True
        options = request["choice_trigger"].get("preferred") or request["legal_option_ids"]
        return ReactionDecision(checkpoint=request["checkpoint"],reactor_id=request["reactor_id"],
            reaction_source_id=request["reaction_source_id"],selection="USE",option_ids=(options[0],)), None
    engine.set_reaction_provider(automatic_transport)
    candidate = next(c for c in engine.legal_candidates() if c.metadata.get("movement_mode") == "jump"
                     and c.destination.x == 3 and c.destination.y == 10 and c.destination.z == 2)
    _use(engine, candidate.display_name)
    move = [e for e in engine.events if e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == actor.entity_id
            and e.payload.get("movement_mode") == "jump" and not e.payload.get("forced")][-1]
    assert max(p.get("z",0) for p in move.payload["path"]) == 2
    assert any(e.event_type == "CONDITION_APPLIED" and e.payload["condition_id"] == athletics.PURSUIT_JUMP for e in engine.events)
    assert set(requests[-1]["legal_option_ids"]) == set(athletics.PURSUIT_LABELS)


@pytest.mark.parametrize("benefit", list(athletics.PURSUIT_LABELS))
def test_pursuit_selects_any_creature_and_four_benefits_midroute(tmp_path, benefit):
    game = pursuit_game(tmp_path)
    seen = []
    def choose(prompt, choice):
        ids = [o["id"] for o in choice["options"]]
        seen.append(ids)
        return pursuit_choice(choice, SECOND, benefit)
    game["commit"](move_candidate_id(game["menu"](), 3, 11), choose)
    assert set(seen[0]) == {FOE, SECOND}
    assert set(seen[1]) == set(athletics.PURSUIT_LABELS)
    engine = game["stored_engine"]()
    receipts = [e for e in engine.events if e.source_definition_id == athletics.PURSUIT and e.event_type == "CONDITION_APPLIED"]
    move = [e for e in engine.events if e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == OWNER][-1]
    assert receipts and receipts[0].sequence < move.sequence
    holder = game["reload_owner"]()
    if benefit == "no_oa":
        assert athletics.flowing_pursuit_no_oa(engine, engine.state.actors[SECOND], holder) is False
        assert athletics.flowing_pursuit_no_oa(engine, engine.state.actors[FOE], holder) is None
    elif benefit == "ac":
        assert any(c.condition_id == athletics.AC_AGAINST and c.data["against"] == SECOND
                   and c.data["amount"] == 2 and c.expires_on == "START_OF_SELF_NEXT_TURN" for c in holder.conditions.values())
    elif benefit == "jump":
        assert flight.jump_extension_ft(engine, holder) == 5
    else:
        from combat.creature_passage import permission
        assert permission(engine, holder, engine.state.actors[SECOND]) == "free"
        assert permission(engine, holder, engine.state.actors[FOE]) is None
    finish(game)


def test_pursuit_unchosen_subject_remains_available_after_table_reload(tmp_path):
    game = pursuit_game(tmp_path)
    subjects = []
    def choose_first(prompt, choice):
        ids = [o['id'] for o in choice['options']]
        if FOE in ids:
            subjects.append(ids)
            return [FOE]
        if SECOND in ids:
            # Leave this subject unchosen until the next move, after reload.
            return []
        return ['ac']
    game['commit'](move_candidate_id(game['menu'](), 3, 11), choose_first)
    assert set(subjects[0]) == {FOE, SECOND}
    finish(game)
    seen = []
    def choose_second(prompt, choice):
        ids = [o['id'] for o in choice['options']]
        seen.append(ids)
        return [SECOND] if SECOND in ids else ['ac']
    game['commit'](move_candidate_id(game['menu'](), 3, 12), choose_second)
    assert seen and seen[0] == [SECOND]
    assert set(seen[1]) == set(athletics.PURSUIT_LABELS)
    finish(game)
    assert {c.data['against'] for c in game['reload_owner']().conditions.values()
            if c.condition_id == athletics.AC_AGAINST} == {FOE, SECOND}


def test_held_one_ally_passage_quotes_a_reachable_detour_and_reload(tmp_path):
    def held_receipt(bundles):
        actions(bundles)
        for bundle in bundles:
            if bundle['actor_id'] != OWNER:
                continue
            row = ActionDefinition(source_definition_id='action:test.t12.held_passage',
                display_name='Test held passage', owner_id=OWNER, economy=EconomyKind.NONE,
                resolution_kind='TYPED', target_kind='SELF',
                parameters={'free_primary':True,'typed':{'effects':[{'type':'condition',
                    'condition':'flowing_pursuit_passage','applies_to':'self',
                    'expires_on':'END_OF_CURRENT_TURN','data':{'ally_id':''}}],
                    'numbers':{},'riders':[],'duration':{'kind':'instant'}}})
            bundle['action_catalog'].append(row.model_dump(mode='json'))
            bundle['actor_template']['action_ids'].append(row.source_definition_id)
    # Both allies are too close for any new 20-foot approach to be possible.
    game = fixture(tmp_path, [athletics.PURSUIT], seed='T12-held-two-allies',
        bundle_transform=held_receipt, allies=(FOE, SECOND),
        places={OWNER:{'x':3,'y':6}, FOE:{'x':4,'y':6}, SECOND:{'x':5,'y':6}})
    game['commit'](candidate_id(game['menu'](), 'Test held passage'))
    finish(game)
    engine = game['stored_engine']()
    assert any(c.condition_id == athletics.PURSUIT_PASSAGE
               for c in engine.state.actors[OWNER].conditions.values())
    menu = game['menu']()
    from combat.tabletop_service import TabletopError
    with pytest.raises(TabletopError, match='legal path'):
        game['table'].preview_move_path(game['match_id'], menu['decision_id'], menu['state_version'],
            OWNER, [{'x':x,'y':6} for x in range(3,7)])
    moves = [c for c in engine.legal_candidates() if c.kind.value == 'MOVE'
             and c.metadata.get('movement_mode','walk') == 'walk']
    candidate = next(c for c in moves if (c.destination.x,c.destination.y,c.destination.z) == (6,6,0))
    crossed = {other.entity_id for other in engine.state.actors.values() if other.entity_id != OWNER
               and any(set(engine._actor_volume(engine.state.actors[OWNER], p))
                       & set(engine._actor_volume(other)) for p in candidate.canonical_path)}
    assert len(crossed) <= 1
    # Each ally remains independently passable, and no endpoint is discarded.
    assert {(6,6),(4,7),(5,7)} <= {(c.destination.x,c.destination.y) for c in moves}
    # The same full set of walking destinations remains reachable to an AI seat.
    engine.typed_control_modes[OWNER] = 'LOCAL_AUTO'
    automatic = [c for c in engine.legal_candidates() if c.kind.value == 'MOVE'
                 and c.metadata.get('movement_mode','walk') == 'walk']
    assert {c.destination for c in automatic} == {c.destination for c in moves}
    game['commit'](candidate.candidate_id, lambda p,c: pytest.fail('No new Pursuit subject is eligible'))
    finish(game)
    actor = game['reload_owner']()
    assert (actor.position.x,actor.position.y,actor.position.z) == (6,6,0)
    assert actor.movement_remaining_ft == 45 - candidate.movement_cost_ft


def test_independently_earned_passages_spend_one_receipt_per_ally(tmp_path):
    game = fixture(tmp_path, [athletics.PURSUIT], seed='T12-two-earned-passages',
        bundle_transform=actions, allies=(FOE, SECOND),
        places={OWNER:{'x':3,'y':6}, FOE:{'x':3,'y':12}, SECOND:{'x':4,'y':12}})
    picked = []
    def choose(prompt, choice):
        ids = [o['id'] for o in choice['options']]
        subjects = [subject for subject in (FOE, SECOND) if subject in ids]
        if subjects:
            picked.append(subjects[0])
            return [subjects[0]]
        return ['ally']
    game['commit'](move_candidate_id(game['menu'](), 3, 11), choose)
    finish(game)
    assert picked == [FOE, SECOND]
    assert len([c for c in game['reload_owner']().conditions.values()
                if c.condition_id == athletics.PURSUIT_PASSAGE]) == 2
    path = [{'x':3,'y':11},{'x':3,'y':12},{'x':4,'y':12},{'x':4,'y':13}]
    chosen_path(game, path, lambda c: pytest.fail('Both creature thresholds were already selected'))
    finish(game)
    actor = game['reload_owner']()
    assert (actor.position.x,actor.position.y) == (4,13)
    assert not any(c.condition_id == athletics.PURSUIT_PASSAGE for c in actor.conditions.values())


def held_passages(count):
    """Seal independently held receipts through a real table action."""
    def transform(bundles):
        actions(bundles)
        bundle = next(b for b in bundles if b['actor_id'] == OWNER)
        row = ActionDefinition(source_definition_id='action:test.t12.receipts', display_name='Test held receipts',
            owner_id=OWNER, economy=EconomyKind.NONE, resolution_kind='TYPED', target_kind='SELF',
            parameters={'free_primary':True, 'typed':{'effects':[{'type':'condition',
                'condition':'flowing_pursuit_passage', 'applies_to':'self',
                'expires_on':'END_OF_CURRENT_TURN', 'data':{'ally_id':''}} for _ in range(count)],
                'numbers':{}, 'riders':[], 'duration':{'kind':'instant'}}})
        bundle['action_catalog'].append(row.model_dump(mode='json'))
        bundle['actor_template']['action_ids'].append(row.source_definition_id)
    return transform


@pytest.mark.parametrize('count', [1, 2])
def test_repeated_ally_crossing_quotes_commit_and_reload(tmp_path, count):
    from combat.tabletop_service import TabletopError
    game = fixture(tmp_path, [athletics.PURSUIT], seed=f'T12-reentry-{count}',
        bundle_transform=held_passages(count), allies=(FOE, SECOND),
        places={OWNER:{'x':3,'y':6}, FOE:{'x':4,'y':6}, SECOND:{'x':2,'y':6}})
    game['commit'](candidate_id(game['menu'](), 'Test held receipts'))
    finish(game)
    path = [{'x':x,'y':6} for x in (3,4,5,4,3)] + [{'x':3,'y':7}]
    menu = game['menu']()
    if count == 1:
        with pytest.raises(TabletopError, match='legal path'):
            game['table'].preview_move_path(game['match_id'], menu['decision_id'], menu['state_version'], OWNER, path)
        finish(game)
        assert (game['reload_owner']().position.x, game['reload_owner']().position.y) == (3,6)
    else:
        quote = game['table'].preview_move_path(game['match_id'], menu['decision_id'], menu['state_version'], OWNER, path)
        assert quote['candidate']['movement_cost_ft'] == 25
        chosen_path(game, path, lambda c: pytest.fail('No new subject is eligible'))
        finish(game)
        actor = game['reload_owner']()
        assert (actor.position.x,actor.position.y) == (3,7)
        assert actor.movement_remaining_ft == 20
        assert not any(c.condition_id == athletics.PURSUIT_PASSAGE for c in actor.conditions.values())


def test_held_passage_composes_with_unlimited_difficult_crossings(tmp_path, monkeypatch):
    from tests.test_lock_choices import install
    from combat.relations import relation, ALLY
    install(monkeypatch, 'pass_through', lambda e,a,b: 'difficult' if relation(e,a,b) == ALLY else None)
    game = fixture(tmp_path, [athletics.PURSUIT], seed='T12-mixed-passage',
        bundle_transform=held_passages(1), allies=(FOE,SECOND),
        places={OWNER:{'x':3,'y':6},FOE:{'x':4,'y':6},SECOND:{'x':2,'y':6}})
    game['commit'](candidate_id(game['menu'](), 'Test held receipts'))
    finish(game)
    path = [{'x':x,'y':6} for x in (3,4,5,4,3)] + [{'x':3,'y':7}]
    menu = game['menu']()
    quote = game['table'].preview_move_path(game['match_id'], menu['decision_id'], menu['state_version'], OWNER, path)
    assert quote['candidate']['movement_cost_ft'] == 30
    chosen_path(game,path,lambda c: pytest.fail('No new subject is eligible'))
    finish(game)
    actor = game['reload_owner']()
    assert (actor.position.x,actor.position.y,actor.movement_remaining_ft) == (3,7,15)
    assert not any(c.condition_id == athletics.PURSUIT_PASSAGE for c in actor.conditions.values())


def test_receipt_search_keeps_supported_roof_climb_routes(monkeypatch):
    from tests.test_roof_movement import engine_at_wall
    from tests.test_lock_choices import install
    from combat import roof_movement
    from combat.granted_movement import native_path_cost
    from combat.gate2_runtime_models import Position
    engine, actor = engine_at_wall(climb_speed=20,height_ft=10)
    ally = next(a for a in engine.state.actors.values() if a.entity_id != actor.entity_id)
    ally.team_id = actor.team_id
    ally.position = Position(x=2,y=5)
    install(monkeypatch,'pass_through_limited_grant',lambda e,a,b: [('free',None,'test:held')] if a is actor and b.entity_id == ally.entity_id else None)
    routes = roof_movement.routes(engine,actor)
    destination = Position(x=6,y=5,z=2)
    assert destination in routes
    path,cost,mode = routes[destination]
    assert mode == 'climb' and cost == 25
    assert native_path_cost(engine,actor,path,mode=mode) == cost


def test_equivalent_receipts_bound_search_work_and_keep_all_destinations(tmp_path, monkeypatch):
    from combat.passage_routes import Resources
    from combat.granted_movement import routes
    game = fixture(tmp_path, [athletics.PURSUIT], seed='T12-counted-receipts',
        bundle_transform=held_passages(6), allies=(FOE,SECOND),
        places={OWNER:{'x':3,'y':6}, FOE:{'x':4,'y':6}, SECOND:{'x':5,'y':6}})
    game['commit'](candidate_id(game['menu'](), 'Test held receipts'))
    finish(game)
    engine = game['stored_engine']()
    actor = engine.state.actors[OWNER]
    # Six separate observed allies, cloned only in this detached query engine.
    from combat.gate2_runtime_models import Position
    for index, (x,y) in enumerate(((4,7),(5,7),(4,5),(5,5))):
        ally = engine.state.actors[FOE].model_copy(deep=True)
        ally.entity_id = f'test:observed-ally-{index}'
        ally.position = Position(x=x,y=y)
        engine.state.actors[ally.entity_id] = ally
    from combat.target_knowledge import observe
    observe(engine)
    grouped = Resources(engine, actor)
    assert len(grouped.groups) == 1 and len(grouped.groups[0][1]) == 6
    assert len(grouped.groups[0][0]) == 6
    # The old Cartesian planner rebuilds 6**6 full routes here. Stop it
    # deterministically at the third build instead of waiting for a stall.
    builds = []
    original_grid = type(engine.grid).reachable
    def bounded_grid(self, *args, **kwargs):
        builds.append(1)
        assert len(builds) <= 2, 'Cartesian route rebuilding exceeds the bounded work budget'
        return original_grid(self, *args, **kwargs)
    monkeypatch.setattr(type(engine.grid), 'reachable', bounded_grid)
    calls = []
    original = Resources.advance
    def counted(self, *args):
        calls.append(1)
        yield from original(self, *args)
    monkeypatch.setattr(Resources, 'advance', counted)
    actual = routes(engine, actor, 20, mode='walk')
    assert len(calls) < 20000
    from combat.creature_passage import geometry
    blocked, ends, difficult, _ = geometry(engine, actor, observed=True)
    expected = engine.grid.reachable(actor.position, movement_ft=20, occupied_cells=blocked,
        end_blocked_cells=ends, difficult_cells=difficult, footprint=engine._footprint(actor))
    assert set(actual) == set(expected)
    moves = engine._movement_candidates(actor, movement_grant_ft=20)
    walking = {c.destination for c in moves if c.metadata.get('movement_mode','walk') == 'walk'}
    assert walking == set(expected)
    engine.typed_control_modes[OWNER] = 'LOCAL_AUTO'
    assert {c.destination for c in engine._movement_candidates(actor, movement_grant_ft=20)
            if c.metadata.get('movement_mode','walk') == 'walk'} == walking
    assert len(builds) == 1
    actor.fly_speed_ft = 45
    flying_moves = engine._movement_candidates(actor, movement_grant_ft=10)
    assert {c.metadata.get('movement_mode','walk') for c in flying_moves
            if c.destination == Position(x=3,y=7)} >= {'walk','fly'}
    print(f'Counted receipt searches: {len(calls)} edge attempts; {len(builds)} ordinary geometry builds')


def test_pursuit_one_ally_passage_real_occupancy_normal_cost_and_consumption(tmp_path):
    game = pursuit_game(tmp_path)
    game["commit"](move_candidate_id(game["menu"](), 3, 11),
                    lambda p,c: pursuit_choice(c, SECOND, 'ally'))
    finish(game)
    before = game["reload_owner"]().movement_remaining_ft
    explicit_move(game, [{"x":3,"y":11},{"x":4,"y":12},{"x":4,"y":13}])
    assert game["reload_owner"]().movement_remaining_ft == before - 10
    assert not any(c.condition_id == athletics.PURSUIT_PASSAGE for c in game["reload_owner"]().conditions.values())
    finish(game)


@ext.hook("movement_step", priority=100)
def t12_stop_during_ally_transit(engine, mover, previous, nxt, intent):
    """Sealed test-only marker models a real interruption inside an occupied footprint."""
    if not any(c.condition_id == "condition:typed.test_t12_stop_transit" for c in mover.conditions.values()):
        return None
    ally = engine.state.actors.get(SECOND)
    if ally is not None and set(engine._actor_volume(mover)) & set(engine._actor_volume(ally)):
        return {"stop":True,"source_id":"action:test.t12.stop_transit","label":"Test interruption during ally passage"}
    return None


def test_interrupted_ally_transit_recovery_also_consumes_the_one_passage(tmp_path):
    game = pursuit_game(tmp_path)
    game["commit"](move_candidate_id(game["menu"](), 3, 11),
                    lambda p,c: pursuit_choice(c, SECOND, 'ally'))
    game["commit"](candidate_id(game["menu"](), "Test stop in ally transit"))
    finish(game)
    explicit_move(game, [{"x":3,"y":11},{"x":4,"y":12},{"x":4,"y":13}])
    holder = game["reload_owner"]()
    assert (holder.position.x,holder.position.y) == (3,11)
    assert not any(c.condition_id == athletics.PURSUIT_PASSAGE for c in holder.conditions.values())
    engine = game["stored_engine"]()
    assert athletics.flowing_pursuit_unbound_passage(engine, holder, engine.state.actors[SECOND]) is None
    finish(game)


def test_jump_adds_five_after_standing_scaling_and_spends_one_real_jump(tmp_path):
    game = pursuit_game(tmp_path)
    game["commit"](move_candidate_id(game["menu"](), 3, 11),
                    lambda p,c: pursuit_choice(c, SECOND, 'jump'))
    finish(game)
    engine = game["stored_engine"]()
    actor = engine.state.actors[OWNER]
    # End the run-up with a genuine side step, so the standing distance is quoted.
    side_step = next(c for c in engine.legal_candidates() if c.kind.value == "MOVE"
                     and c.metadata.get("movement_mode","walk") == "walk"
                     and c.destination.x == 2 and c.destination.y == 11 and c.destination.z == 0)
    game["commit"](side_step.candidate_id)
    engine = game["stored_engine"]()
    actor = engine.state.actors[OWNER]
    assert flight.long_jump_ft(engine, actor, [actor.position]) == actor.strength_score // 2 + 5
    # Horizontal and high jumps both reach the native candidate menu.
    candidates = [c for c in engine.legal_candidates() if c.metadata.get("movement_mode") == "jump"]
    assert any(c.destination.z == actor.position.z for c in candidates)
    assert any(c.destination.z > actor.position.z for c in candidates)
    ordinary = {c.destination:c.candidate_id for c in engine.legal_candidates()
                if c.kind.value == "MOVE" and c.metadata.get("movement_mode", "walk") == "walk"}
    assert all(c.candidate_id != ordinary[c.destination] for c in candidates if c.destination in ordinary)
    chosen = next(c for c in candidates if c.destination.z == actor.position.z and c.destination != actor.position)
    game["commit"](chosen.candidate_id)
    assert not any(c.condition_id == athletics.PURSUIT_JUMP for c in game["reload_owner"]().conditions.values())
    finish(game)


def test_sudden_flank_consumed_by_first_native_attack_even_when_it_misses(tmp_path):
    def native(bundles):
        for bundle in bundles:
            if bundle["actor_id"] != OWNER:
                continue
            for row in bundle["action_catalog"]:
                if row["display_name"] == "Unarmed Strike":
                    row.update(resolution_kind="ATTACK", parameters={"attack_kind":"melee","free_primary":True},
                               attack_bonus=-100, damage={"count":1,"sides":2,"modifier":0}, damage_type="BLUDGEONING")
                    row["economy"] = "NONE"
    from tests.test_a2_athletics import setup_actions
    def transform(bundles):
        setup_actions(bundles)
        native(bundles)
        for b in bundles:
            b.setdefault("skills", {})["Acrobatics"] = 60 if b["actor_id"] == OWNER else -60
            b["actor_template"].setdefault("skills", {})["Acrobatics"] = 60 if b["actor_id"] == OWNER else -60
    game = fixture(tmp_path, [athletics.SUDDEN_FLANK], seed="T12-native", bundle_transform=transform,
        places={OWNER:{"x":3,"y":6},FOE:{"x":4,"y":6},SECOND:{"x":5,"y":7}})
    commit(game, "Tumble (Bonus Action)")
    explicit_move(game, [{"x":3,"y":6},{"x":4,"y":6},{"x":5,"y":6}])
    finish(game)
    assert any(m.source_definition_id == athletics.SUDDEN_FLANK for m in game["reload_owner"]().modifiers.values())
    other_attack = next(c for c in game["stored_engine"]().legal_candidates()
                        if c.display_name == "Unarmed Strike" and c.target_ids == (SECOND,))
    game["commit"](other_attack.candidate_id)
    assert own_rolls(game)[-1].payload["mode"] == "NORMAL"
    assert any(m.source_definition_id == athletics.SUDDEN_FLANK for m in game["reload_owner"]().modifiers.values())
    finish(game)
    against_foe = next(c for c in game["stored_engine"]().legal_candidates()
                      if c.display_name == "Unarmed Strike" and c.target_ids == (FOE,))
    game["commit"](against_foe.candidate_id)
    assert own_rolls(game)[-1].payload["mode"] == "ADVANTAGE"
    assert not any(m.source_definition_id == athletics.SUDDEN_FLANK for m in game["reload_owner"]().modifiers.values())
    finish(game)
    against_foe = next(c for c in game["stored_engine"]().legal_candidates()
                      if c.display_name == "Unarmed Strike" and c.target_ids == (FOE,))
    game["commit"](against_foe.candidate_id)
    assert own_rolls(game)[-1].payload["mode"] == "NORMAL"
    finish(game)
