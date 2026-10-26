"""Printed Insights through CombatService, table execute_intent and cold replay."""
import pytest
from combat.ext import insights_second as si
from tests.auto_worker1_support import LEFT, RIGHT, act, cell_send, resolve, reload, settle, turn, fight as service_fight

QI = "resource:core.qi"
STAMINA = "resource:core.stamina"


def fight(tmp_path, talents, **kwargs):
    # Unassigned Insights have no sphere_id, so the shared sheet fixture cannot
    # infer them from its talent field. Record exact ownership in its real field.
    def ownership(doc, aid):
        selected = talents if aid == LEFT else kwargs.get("right_talents", ())
        fields = doc["spheres_and_talents"]
        fields["cultivation_insight_record_ids"] = [mid for mid in selected if mid.startswith("insight.")]
        fields["learned_talent_record_ids"] = [mid for mid in fields.get("learned_talent_record_ids", ())
                                               if not mid.startswith("insight.")]
    return service_fight(tmp_path, talents, sheet_edit=ownership, **kwargs)

@pytest.mark.parametrize("owns", [False, True])
def test_dao_parry_adds_two_to_real_native_reduction(tmp_path, owns):
    damage = {"type": "attack", "attack_kind": "weapon", "count": 1,
              "on_hit": [{"type": "damage", "flat": 40, "damage_types": ["slashing"]}]}
    def attack_numbers(bundle):
        for action in bundle["action_catalog"]:
            if action["display_name"] == "Cause":
                action["parameters"]["typed"]["numbers"]["attack_bonus"] = 100
    combat, table, mid = fight(tmp_path, [si.PARRY] + ([si.DAO] if owns else []),
                              cause=[damage], bundle_edit=attack_numbers)
    turn(table, mid, RIGHT)
    resolve(lambda a: act(table, mid, "Cause", a, target_id=LEFT))
    engine = reload(combat, mid)
    event = next(e for e in engine.events if e.event_type == "REACTION_RESOLVED" and e.source_definition_id == si.PARRY)
    roll = next(r for r in engine.rolls if r.reason == "DAMAGE_REDUCTION:" + si.PARRY)
    assert event.payload["reduction"] == roll.total + (2 if owns else 0)
    assert engine.state.actors[LEFT].current_hp == 1000 - event.payload["pending_before"] + event.payload["reduction"]

@pytest.mark.parametrize("count,owns", [(2, True), (3, False), (3, True)])
def test_debt_collector_three_owned_debts_and_once_scene(tmp_path, count, owns):
    # Real condition effects are committed by setup; different source IDs retain
    # separate imprint instances, exactly as the Karma ledger stores Causes.
    from combat.typed_executor import mark_condition_id
    debts = [{"type": "condition", "condition": "test_debt_" + str(i), "applies_to": "target",
              "duration": {"kind": "until_removed"}} for i in range(count)]
    def edit(bundle):
        for action in bundle["action_catalog"]:
            if action["display_name"] == "Prepare":
                for effect in action["parameters"]["typed"]["effects"]:
                    effect["condition"] = mark_condition_id("Debt Imprint", LEFT).removeprefix("condition:typed.")
    combat, table, mid = fight(tmp_path, [si.DEBT] if owns else [], prepare=debts,
        prepare_costs=[(QI, 10)], bundle_edit=edit, extra_witness=True,
        extra_actions=[("Finish", {"target_kind": "HOSTILE_ENTITY", "effects": [
            {"type": "damage", "flat": 1000, "damage_types": ["force"]}]})])
    resolve(lambda a: act(table, mid, "Prepare", a, target_id=RIGHT))
    resolve(lambda a: act(table, mid, "Finish", a, target_id=RIGHT))
    engine = reload(combat, mid)
    assert engine.state.actors[LEFT].resources[QI] == 90 + (4 if owns and count == 3 else 0)
    assert si.used(engine.state.actors[LEFT], si.DEBT) == (owns and count == 3)
    witness = 'actor:factory.auto111-witness'
    turn(table, mid, RIGHT)
    turn(table, mid, LEFT)
    resolve(lambda a: act(table, mid, "Prepare", a, target_id=witness))
    resolve(lambda a: act(table, mid, "Finish", a, target_id=witness))
    engine = reload(combat, mid)
    assert engine.state.actors[LEFT].resources[QI] == 80 + (4 if owns and count == 3 else 0)

@pytest.mark.parametrize("choice", ["stamina", "flight", "push"])
def test_dragon_pearl_printed_choices_persist_and_limit(tmp_path, choice):
    damage = {"type": "damage", "flat": 10, "damage_types": ["lightning"]}
    def edit(bundle):
        for action in bundle["action_catalog"]:
            if action["display_name"] == "Prepare":
                action["parameters"]["typed"]["source"] = "tianxia.subpath.body.ryujin.feature.dragon_s_breath"
    combat, table, mid = fight(tmp_path, [si.PEARL], prepare=[damage], prepare_costs=[(STAMINA, 5)],
        bundle_edit=edit, left_resource="Stamina",
        positions={LEFT: {"x": 3, "y": 6}, RIGHT: {"x": 5, "y": 6}})
    def choose(prompt):
        ids = [o["id"] for o in prompt["choice"]["options"]]
        if choice == "push":
            return [i for i in ids if i.startswith("push:")]
        return [i for i in ids if i == choice]
    _, prompts = settle(lambda a: act(table, mid, "Prepare", a, target_id=RIGHT), choose=choose)
    engine = reload(combat, mid)
    assert si.used(engine.state.actors[LEFT], si.PEARL)
    assert any(p["context"]["reaction_source_id"] == "choice:needle.dragon_pearl" for p in prompts)
    assert engine.state.actors[LEFT].resources[STAMINA] == (97 if choice == "stamina" else 95)
    assert engine.state.actors[RIGHT].position.x == (6 if choice == "push" else 5)
    assert si.pearl_flight(engine, engine.state.actors[LEFT]) == ({"fly_speed_ft": 30} if choice == "flight" else None)
    turn(table, mid, RIGHT)
    turn(table, mid, LEFT)
    _, prompts = resolve(lambda a: act(table, mid, "Prepare", a, target_id=RIGHT))
    engine = reload(combat, mid)
    assert not any(p["context"]["reaction_source_id"] == "choice:needle.dragon_pearl" for p in prompts)
    assert si.pearl_flight(engine, engine.state.actors[LEFT]) is None


def test_technique_event_window_is_context_local_during_service_resolution(tmp_path, monkeypatch):
    from combat import ext
    original_run = ext.run
    seen = []

    def inspect_window(name, *args, **kwargs):
        if name == "technique_used":
            ctx = args[0]
            if ctx.action.display_name == "Prepare":
                assert isinstance(ctx.technique_event_start, int)
                assert not hasattr(ctx.engine, "_technique_event_start")
                seen.append(ctx.technique_event_start)
        return original_run(name, *args, **kwargs)

    monkeypatch.setattr(ext, "run", inspect_window)
    combat, table, mid = fight(tmp_path, [si.PEARL], prepare=[
        {"type": "damage", "flat": 10, "damage_types": ["lightning"]}
    ], prepare_costs=[(STAMINA, 5)], left_resource="Stamina")
    settle(lambda answers: act(table, mid, "Prepare", answers, target_id=RIGHT))
    # A player choice checkpoint re-enters the typed action when its answer is
    # submitted; every invocation must still have its own Context window.
    assert len(seen) >= 1
    assert all(start == seen[0] for start in seen)
    engine = reload(combat, mid)
    assert engine.events
    assert not hasattr(engine, "_technique_event_start")


WITNESS = "actor:factory.auto111-witness"


def pearl_breath(bundle):
    """A cone-shaped technique that damages every creature it catches with Lightning."""
    for action in bundle["action_catalog"]:
        if action["display_name"] == "Prepare":
            action["parameters"]["typed"]["source"] = "tianxia.subpath.body.ryujin.feature.dragon_s_breath"
            action["parameters"]["typed"]["area"] = {"shape": "sphere", "size_ft": 15}


@pytest.mark.parametrize("decline", [False, True])
def test_dragon_pearl_release_offers_every_creature_the_effect_damaged(tmp_path, decline):
    """A breath that hurt two creatures offers one Release naming both.

    The printed Release chooses a creature damaged by the triggering effect, so the menu
    must not be limited to whichever recipient the journal recorded first, and declining
    must leave the scene's single use unspent for the next time.
    """
    combat, table, mid = fight(tmp_path, [si.PEARL], prepare=[{"type": "attack",
        "attack_kind": "cultivation_ranged", "count": 1,
        "on_hit": [{"type": "damage", "flat": 10, "damage_types": ["lightning"]}], "on_miss": []}],
        prepare_target="CELL", prepare_attack_bonus=100, prepare_costs=[(STAMINA, 5)],
        bundle_edit=pearl_breath, left_resource="Stamina", extra_witness=True,
        witness_team="team:opponents")
    engine = reload(combat, mid)
    before = {aid: engine.state.actors[aid].position.x for aid in (RIGHT, WITNESS)}
    picked = []
    offered = []

    def choose(prompt):
        ids = [o["id"] for o in prompt["choice"]["options"]]
        if prompt["context"]["reaction_source_id"] != "choice:needle.dragon_pearl":
            return ids[:1]
        pushes = [i for i in ids if i.startswith("push:")]
        assert len(pushes) == 2, ids
        picked.append(pushes[1])
        offered.append(True)
        # Decline the first Release only; the control then takes the second one.
        return [] if (decline and len(offered) == 1) else [pushes[1]]

    _, prompts = settle(cell_send(table, mid, "Prepare", (4, 6)), choose=choose)
    engine = reload(combat, mid)
    release = next(p for p in prompts if p["context"]["reaction_source_id"] == "choice:needle.dragon_pearl")
    names = [engine.state.actors[aid].display_name for aid in (RIGHT, WITNESS)]
    # One Release naming every creature the effect damaged, and a button for each.
    assert all(name in release["moment"] for name in names), release["moment"]
    assert sum(o["id"].startswith("push:") for o in release["choice"]["options"]) == 2
    assert all(any(name in o["label"] for o in release["choice"]["options"])
               for name in names), release["choice"]["options"]
    if decline:
        assert not si.used(engine.state.actors[LEFT], si.PEARL)
        assert {aid: engine.state.actors[aid].position.x for aid in (RIGHT, WITNESS)} == before
        # The declined use is still available: the next breath offers the Release again.
        turn(table, mid, RIGHT)
        turn(table, mid, LEFT)
        _, prompts = settle(cell_send(table, mid, "Prepare", (4, 6)), choose=choose)
        assert si.used(reload(combat, mid).state.actors[LEFT], si.PEARL)
    else:
        assert si.used(engine.state.actors[LEFT], si.PEARL)
        pushed = picked[0].removeprefix("push:")
        other = WITNESS if pushed == RIGHT else RIGHT
        assert engine.state.actors[pushed].position.x == before[pushed] + 1
        assert engine.state.actors[other].position.x == before[other]


@pytest.mark.parametrize('chosen', ['Cause', 'Cause Again'])
def test_cut_snare_names_each_binding_and_ends_only_that_one(tmp_path, chosen):
    """Two grips of the same Difficulty Class are separately named and separately cut.

    Cut the Snare ends exactly one binding, so the table must be able to say which one
    before it answers, and the answer must free the grip it named, leave the other in
    place, and end only the conditions belonging to the grip it chose.
    """
    grip = {'type': 'condition', 'condition': 'grappled', 'applies_to': 'target',
            'hold_kind': 'ordinary_physical', 'duration': {'kind': 'until_removed'}}

    def edit(bundle):
        # A second grip from its own action, so the two bindings differ only by which
        # effect laid them down: the same holder, the same Difficulty Class, two grips.
        if any(a['display_name'] == 'Cause' for a in bundle['action_catalog']):
            extra = 'action:test.worker1.second_grip'
            bundle['actor_template']['action_ids'].append(extra)
            bundle['action_catalog'].append({
                'source_definition_id': extra, 'display_name': 'Cause Again', 'owner_id': RIGHT,
                'economy': 'NONE', 'resolution_kind': 'TYPED', 'target_kind': 'HOSTILE_ENTITY',
                'range_ft': 60, 'costs': [],
                'parameters': {'typed': {'effects': [dict(grip)], 'numbers': {'cl': 15, 'pb': 4,
                    'key_mod': 3, 'save_dc': 1}, 'duration': {'kind': 'instant'}, 'riders': []}}})

    combat, table, mid = fight(tmp_path, [si.SNARE], cause=[dict(grip)], cause_save_dc=1, bundle_edit=edit)
    turn(table, mid, RIGHT)
    resolve(lambda a: act(table, mid, 'Cause', a, target_id=LEFT))
    resolve(lambda a: act(table, mid, 'Cause Again', a, target_id=LEFT))
    turn(table, mid, LEFT)
    held = si.bindings(reload(combat, mid), reload(combat, mid).state.actors[LEFT])
    assert len(held) == 2, held
    engine = reload(combat, mid)
    labels = si.binding_labels(engine, held)
    # Two grips of the same Difficulty Class no longer print the same button.
    assert len(set(labels.values())) == 2, labels
    assert all('Visitor' in text and 'Cause' in text for text in labels.values()), labels
    by_action = {engine.action_catalog[c.source_definition_id].display_name: labels[iid]
                 for iid, c in held.items()}
    kept = next(iid for iid, c in held.items()
                if engine.action_catalog[c.source_definition_id].display_name != chosen)

    def choose(prompt):
        ids = [o['id'] for o in prompt['choice']['options']]
        if prompt['context']['reaction_source_id'] == 'choice:needle.cut_snare_hold':
            marked = [i for i in ids if labels[i] == by_action[chosen]]
            assert len(marked) == 1, labels
            return marked
        return [i for i in ids if i == 'STR']

    _, prompts = settle(lambda a: act(table, mid, 'Cut the Snare', a), choose=choose)
    engine = reload(combat, mid)
    menu = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.cut_snare_hold')
    # Every offered button names the binding and its holder; the prompt names who is bound.
    assert all(o['id'] in labels and 'Visitor' in o['label'] for o in menu['choice']['options'])
    assert 'Keeper' in menu['moment'], menu['moment']
    after = engine.state.actors[LEFT]
    assert kept in after.conditions, 'the grip that was not chosen must survive'
    assert all(iid not in after.conditions for iid in set(held) - {kept})
    # Only the chosen grip's own condition was removed; the other's bookkeeping is untouched.
    removed = {e.payload['instance_id'] for e in engine.events
               if e.event_type == 'CONDITION_REMOVED' and e.actor_id == LEFT}
    assert removed == set(held) - {kept}, removed
    assert si.used(after, si.SNARE)

@pytest.mark.parametrize("owns,source,kind", [(False, "ryujin", "lightning"),
    (True, "other", "lightning"), (True, "ryujin", "fire")])
def test_pearl_never_triggers_without_printed_ownership_source_and_type(tmp_path, owns, source, kind):
    combat, table, mid = fight(tmp_path, [si.PEARL] if owns else [],
        prepare=[{"type": "damage", "flat": 10, "damage_types": [kind]}],
        prepare_source=("tianxia.subpath.body.ryujin.feature.dragon_s_breath" if source == "ryujin"
                        else "tianxia.path.qi_cultivation.feature.unrelated"))
    _, prompts = resolve(lambda a: act(table, mid, "Prepare", a, target_id=RIGHT))
    assert not si.used(reload(combat, mid).state.actors[LEFT], si.PEARL)
    assert not any(p["context"]["reaction_source_id"] == "choice:needle.dragon_pearl" for p in prompts)

@pytest.mark.parametrize('dc,success', [(1, True), (100, False)])
@pytest.mark.parametrize('check_choice', ['STR', 'DEX', 'cultivation'])
def test_cut_snare_ends_one_physical_hold_only_on_success(tmp_path, dc, success, check_choice):
    hold = {'type': 'condition', 'condition': 'grappled', 'applies_to': 'target',
            'hold_kind': 'ordinary_physical', 'duration': {'kind': 'until_removed'}}
    combat, table, mid = fight(tmp_path, [si.SNARE], cause=[hold], cause_save_dc=dc)
    turn(table, mid, RIGHT)
    resolve(lambda a: act(table, mid, 'Cause', a, target_id=LEFT))
    turn(table, mid, LEFT)
    resolve(lambda a: act(table, mid, 'Cut the Snare', a),
            {'choice:needle.cut_snare_check': [check_choice]})
    engine = reload(combat, mid)
    assert bool(si.bindings(engine, engine.state.actors[LEFT])) == (not success)
    assert si.used(engine.state.actors[LEFT], si.SNARE) == success
    roll = next(e for e in engine.events if e.event_type == 'CHECK_ROLLED' and e.source_definition_id.endswith(si.SNARE))
    assert roll.payload['dc'] == dc and roll.payload['success'] == success
    assert roll.payload['ability'] == ('CON' if check_choice == 'cultivation' else check_choice)
    assert not engine.state.actors[LEFT].bonus_action_available
    assert engine.state.actors[LEFT].resources[QI] == 100
    if success:
        turn(table, mid, RIGHT)
        resolve(lambda a: act(table, mid, 'Cause', a, target_id=LEFT))
        turn(table, mid, LEFT)
        engine = reload(combat, mid)
        assert not any(c.display_name.startswith('Cut the Snare') for c in engine.legal_candidates())


def test_snare_does_not_offer_unknown_magical_binding(tmp_path):
    hold = {'type': 'condition', 'condition': 'restrained', 'applies_to': 'target',
            'duration': {'kind': 'until_removed'}}
    combat, table, mid = fight(tmp_path, [si.SNARE], cause=[hold])
    turn(table, mid, RIGHT)
    resolve(lambda a: act(table, mid, 'Cause', a, target_id=LEFT))
    turn(table, mid, LEFT)
    engine = reload(combat, mid)
    assert not any(c.display_name.startswith('Cut the Snare') for c in engine.legal_candidates())


@pytest.mark.parametrize('owns', [False, True])
def test_dual_mandate_load_and_free_layered_activation(tmp_path, owns):
    from tests.auto_worker1_support import settle
    from combat.ext.imbuement_mandates import load
    prefix = 'tianxia.talent.imbuement.'
    combat, table, mid = fight(tmp_path,
        ['IMBUEMENT_BASE_PLACE_MANDATE'] + [prefix + k for k in ['layered_mandate', 'quicken_and_slow', 'tempered_equipment']]
        + ([si.DUAL] if owns else []))
    engine = reload(combat, mid)
    assert load(engine, engine.state.actors[LEFT], 4) == (3 if owns else 2)
    label = 'Place Mandate: Layered Mandate (' + ('0' if owns else '1') + ' CP)'
    action = next(a for a in engine.action_catalog.values() if a.owner_id == LEFT and a.display_name == label)
    candidates = [c for c in engine.legal_candidates() if c.source_definition_id == action.source_definition_id]
    assert candidates and all(RIGHT not in c.target_ids for c in candidates)
    def choose(prompt):
        options = [o['id'] for o in prompt['choice']['options']]
        if prompt['context']['reaction_source_id'] == 'choice:needle.layered_mandate':
            return [o for o in options if o.endswith('.quicken') or o.endswith('.temper_weapon')]
        return options[:max(1, prompt['choice'].get('minimum', 1))]
    settle(lambda a: act(table, mid, label, a, target_id=LEFT), choose=choose)
    engine = reload(combat, mid)
    assert engine.state.actors[LEFT].resources[QI] == (100 if owns else 99)
    assert any(m.target_field == 'speed_ft' and int(m.value) == 20 for m in engine.state.actors[LEFT].modifiers.values())
    assert any(c.condition_id == 'condition:typed.mandate_vessel' for c in engine.state.actors[LEFT].conditions.values())
    assert not engine.state.actors[LEFT].action_available
    assert not any(e.event_type == 'SAVE_ROLLED' for e in engine.events)
