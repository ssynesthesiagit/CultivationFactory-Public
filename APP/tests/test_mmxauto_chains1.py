"""MMXAUTO-CHAINS1: the Chains sphere's printed clauses the Game Master used to rule on.

Five Chains mechanics lost their top-level Game Master riders in lane MMXAUTO-CHAINS1
(2026-10-26). Each clause they lost is either wired to something the engine really does, or is
kept as an explicit Game Master rider when no engine seam exists for it:

* Grappling Chain: the failed save is the printed "Choose one" (pull 15 feet, knock Prone,
  become Bound, deny Reactions, or attempt a Grapple when the target is within reach), the
  successful save pulls 5 feet, and the Realm damage uses the printed bands. The choice itself
  is combat/ext/chains_sphere.py ``chains_grappling_binding``; the Grapple outcome reuses the
  shared combat/ext/grapple_attempts helper, so it is this owner's own Grapple attempt.
* Chain Counter: the successful save already asked the owner for its printed outcomes
  (combat/ext/chains_sphere.py ``chains_counter_success``); the rider only restated it.
* Chain-Sovereign Incarnation: the printed "Once per long rest" is a typed use limit, so the
  Game Master no longer restores it by hand.
* Restraining Hook: a reaction talent is never the engine's opportunity attack, so the printed
  "does not count as an opportunity attack" needs no line from the Game Master.
* Meridian Chain Lock (PARTIAL, CORE_WITH_RIDERS): the compiler does not enforce the printed
  target prerequisite, so it remains an explicit reminder; the denied Reactions and Concentration
  Disadvantage are typed. The deferred first-spend Cultivation Point tax remains a Game Master
  rider until the shared first-spend trigger exists, and is never charged on the failed save.

Every case below drives the real table: the owner really swings the Chain Lash, the target
really saves, the owner is really asked, and the result is read back after a commit through a
fresh CombatService (``reload`` also asserts full-state equality and a PASSING mechanical replay).
"""
import json

from combat.factory_compiler import compile_character
from tests.auto_worker1_support import LEFT, RIGHT, fight, reload, turn
from tests.h1_support import sheet

LASH = "TAL_CHAINS_CHAIN_LASH_BASE"
GRAPPLING = "tianxia.talent.chains.grappling_chain"
COUNTER = "tianxia.talent.chains.chain_counter"
SOVEREIGN = "tianxia.talent.chains.chain_sovereign_incarnation"
HOOK = "tianxia.talent.chains.restraining_hook"
LOCK = "tianxia.talent.chains.meridian_chain_lock"
BINDING = "choice:needle.chains_grappling_binding"
FAILING_SAVE_DC = 100      # the owner's Cultivation Save DC: the target always fails its save
PASSING_SAVE_DC = 1        # ... and always succeeds it
AUTHORITY = "authority/Tianxia_Typed_Mechanics_Authority_R1.json"


def mechanic(mechanic_id):
    with open(AUTHORITY, encoding="utf-8") as handle:
        return json.load(handle)["mechanics"][mechanic_id]


def lash(tmp_path, *, dc=FAILING_SAVE_DC, cl=17, option=0, positions=None):
    """A Chains owner with the Grappling Chain enabled on one Chain Lash option.

    The printed talent rides the Lash as a paid on-hit modifier, so the owner first turns the
    modifier on (the shared attack-modifier setting) and then uses the printed variant.
    """
    # A high attack bonus keeps every swing a hit, so the printed clauses (and not the dice)
    # decide what these cases show.
    combat, table, mid = fight(tmp_path, [LASH, GRAPPLING], left_save_dc=dc, cl=cl,
                               left_attack_bonus=20,
                               positions=positions or {LEFT: {"x": 3, "y": 6}, RIGHT: {"x": 8, "y": 6}})
    turn(table, mid, LEFT)
    engine = reload(combat, mid)
    toggle = next(c for c in engine.legal_candidates()
                  if f"#opt{option}.rider." in c.source_definition_id and c.source_definition_id.endswith("on.toggle"))
    state = table.state(mid)
    menu = state["menu"]
    result = table.act(mid, toggle.candidate_id, menu["decision_id"], menu["state_version"],
                       state["last_sequence"], [])
    assert result["status"] == "COMMITTED", result
    return combat, table, mid


def modifier_hash(combat, mid, option=0):
    """The modifier's own hash, read off the compiled settings of that Chain Lash option."""
    engine = reload(combat, mid)
    setting = next(c for c in engine.legal_candidates()
                   if f"#opt{option}.rider." in c.source_definition_id and c.source_definition_id.endswith("on.toggle"))
    return setting.source_definition_id.split(".rider.")[1].split(".")[0]


def swing(table, mid, option=0, pick=None, limit=12):
    """Use the printed Grappling Chain variant, answering every question it raises.

    Returns the prompts so a test can read what the owner was told. ``pick`` chooses one option
    of the printed choice by its id.
    """
    engine = reload(table.combat, mid)
    variant = next(c for c in engine.legal_candidates()
                   if f"#opt{option}+" in c.source_definition_id and ".rider." not in c.source_definition_id)
    answers, prompts = [], []
    for _ in range(limit):
        state = table.state(mid)
        menu = state["menu"]
        result = table.act(mid, variant.candidate_id, menu["decision_id"], menu["state_version"],
                           state["last_sequence"], answers)
        if result["status"] != "REACTION_REQUIRED":
            assert result["status"] == "COMMITTED", result
            return prompts
        prompt = result["reaction"]
        prompts.append(prompt)
        options = [o["id"] for o in (prompt.get("choice") or {}).get("options", [])]
        chosen = [o for o in options if pick and pick(o)] or options[:1]
        answers.append({**prompt["context"], "selection": "USE", "option_ids": chosen})
    raise AssertionError("the swing never finished")


def asked(prompts):
    """The prompts of the printed Grappling Chain choice."""
    return [p for p in prompts if str(p["context"].get("reaction_source_id") or "") == BINDING]


def conditions(actor):
    return {str(c.condition_id).removeprefix("condition:typed.") for c in actor.conditions.values()}


def forced_moves(engine):
    """The forced movements of this fight, in order, as the feet each one covered."""
    out = []
    for event in engine.events:
        if event.event_type != "MOVEMENT_COMMITTED":
            continue
        payload = event.payload or {}
        path = payload.get("path") or []
        out.append((len(path) - 1) * 5 if path else int(payload.get("cost_ft") or 0))
    return out


def test_grappling_chain_asks_the_printed_choice_after_a_failed_save(tmp_path):
    combat, table, mid = lash(tmp_path)
    prompts = swing(table, mid)
    question = asked(prompts)
    assert question, "Grappling Chain never asked for its printed choice"
    assert {o["id"] for o in question[0]["choice"]["options"]} == {"pull", "prone", "bound", "reaction"}
    said = str(question[0])
    assert "Grappling Chain" in said, said
    assert "Strength save" in said, said


def test_grappling_chain_pulls_the_target_fifteen_feet(tmp_path):
    combat, table, mid = lash(tmp_path)
    before = reload(combat, mid).state.actors[RIGHT].position
    assert (before.x, before.y) == (8, 6), before
    swing(table, mid, pick=lambda option: option == "pull")
    engine = reload(combat, mid)
    after = engine.state.actors[RIGHT].position
    # The Lash's own option pulls 5 feet first, then the printed choice pulls 15.
    assert (after.x, after.y) == (4, 6), after
    assert forced_moves(engine) == [5, 15], forced_moves(engine)


def test_grappling_chain_binds_the_target_until_the_start_of_your_next_turn(tmp_path):
    combat, table, mid = lash(tmp_path)
    swing(table, mid, pick=lambda option: option == "bound")
    engine = reload(combat, mid)
    foe = engine.state.actors[RIGHT]
    assert "bound" in conditions(foe), conditions(foe)
    bound = next(c for c in foe.conditions.values() if c.condition_id.endswith("bound"))
    assert bound.expires_on == "START_OF_SOURCE_NEXT_TURN", bound.expires_on


def test_grappling_chain_denies_the_targets_reactions(tmp_path):
    combat, table, mid = lash(tmp_path)
    swing(table, mid, pick=lambda option: option == "reaction")
    engine = reload(combat, mid)
    foe = engine.state.actors[RIGHT]
    assert "reaction_denied" in conditions(foe), conditions(foe)


def test_grappling_chain_knocks_the_target_prone(tmp_path):
    combat, table, mid = lash(tmp_path)
    swing(table, mid, pick=lambda option: option == "prone")
    engine = reload(combat, mid)
    assert "prone" in conditions(engine.state.actors[RIGHT]), conditions(engine.state.actors[RIGHT])


def test_grappling_chain_offers_the_immediate_grapple_only_within_reach(tmp_path):
    # 25 feet away: the printed "if it is within your reach" is not met.
    combat, table, mid = lash(tmp_path / "far")
    far = asked(swing(table, mid))
    assert far, "Grappling Chain never asked for its printed choice"
    assert "grapple" not in {o["id"] for o in far[0]["choice"]["options"]}

    # 5 feet away: the owner's own Grapple reach, so the printed outcome is offered.
    combat, table, mid = lash(tmp_path / "near", positions={LEFT: {"x": 3, "y": 6}, RIGHT: {"x": 4, "y": 6}})
    near = asked(swing(table, mid))
    assert near, "Grappling Chain never asked for its printed choice"
    assert "grapple" in {o["id"] for o in near[0]["choice"]["options"]}


def test_grappling_chain_attempts_its_own_grapple_when_the_owner_asks_for_it(tmp_path):
    combat, table, mid = lash(tmp_path, positions={LEFT: {"x": 3, "y": 6}, RIGHT: {"x": 4, "y": 6}})
    prompts = swing(table, mid, pick=lambda option: option == "grapple")
    assert asked(prompts), "Grappling Chain never asked for its printed choice"
    engine = reload(combat, mid)
    saves = [e for e in engine.events if e.event_type == "SAVE_ROLLED" and "grapple" in str(e.payload).lower()]
    assert saves, [(e.event_type, e.payload) for e in engine.events if e.event_type == "SAVE_ROLLED"]


def test_grappling_chain_successful_save_pulls_five_feet(tmp_path):
    # "Chain Lash: Attach a Link" pulls nothing of its own, so the only movement is the
    # printed successful save.
    combat, table, mid = lash(tmp_path, dc=PASSING_SAVE_DC, option=4)
    swing(table, mid, option=4)
    engine = reload(combat, mid)
    after = engine.state.actors[RIGHT].position
    assert (after.x, after.y) == (7, 6), after
    assert forced_moves(engine) == [5], forced_moves(engine)
    assert "bound" not in conditions(engine.state.actors[RIGHT])


def test_grappling_chain_adds_the_printed_realm_damage():
    bundle = compile_character(sheet([LASH, GRAPPLING], cl=17, dc=10, primary="Qi"), actor_id=LEFT)
    variant = next(a for a in bundle["action_catalog"]
                   if "+30b9c11197" in a["source_definition_id"])
    rows = [row for effect in variant["parameters"]["typed"]["effects"] for row in effect.get("on_hit") or []]
    damage = next(row for row in rows if row.get("type") == "extra_damage")
    assert damage["damage_label"] == "Grappling Chain", damage
    # Foundation +2d6, Core Formation +3d6, Nascent Soul +4d6, and nothing below Foundation.
    assert damage["dice_by_cl"] == [[5, 10, 2, 6], [11, 16, 3, 6], [17, 20, 4, 6]], damage["dice_by_cl"]


def test_chain_counter_no_longer_leaves_the_successful_save_to_the_game_master():
    counter = mechanic(COUNTER)
    assert counter["coverage"] == "FULL", counter["coverage"]
    assert not counter["riders"], counter["riders"]
    # The printed choice itself is covered by tests/test_auto98_chains_counter.py.
    option = next(o for o in counter["options"] if o["label"] == "Pull 10 Feet")
    assert option["effects"][0]["on_success"][0]["type"] == "chains_counter_success", option


def test_chain_sovereign_incarnation_is_a_typed_long_rest_limit():
    sovereign = mechanic(SOVEREIGN)
    assert sovereign["coverage"] == "FULL", sovereign["coverage"]
    assert not sovereign["riders"], sovereign["riders"]
    assert sovereign["use_limit"] == "once_per_long_rest", sovereign["use_limit"]


def test_restraining_hook_is_a_reaction_and_never_the_opportunity_attack():
    hook = mechanic(HOOK)
    assert hook["coverage"] == "FULL", hook["coverage"]
    assert not hook["riders"], hook["riders"]
    bundle = compile_character(sheet([HOOK], cl=15, dc=10, primary="Qi"), actor_id=LEFT)
    reactions = [r for r in bundle["typed_reactions"] if r["feature_id"] == HOOK]
    assert reactions, "the Restraining Hook stopped compiling as a reaction"
    assert all(not r["opportunity_only"] for r in reactions), reactions
    # The engine's own opportunity attack is a different action: using the Hook never spends it.
    opportunity = next(a for a in bundle["action_catalog"]
                       if a["source_definition_id"].endswith(".opportunity_attack"))
    assert opportunity["economy"] == "REACTION", opportunity["economy"]
    assert not any(r.get("action") == opportunity["source_definition_id"] for r in reactions), reactions


def test_meridian_chain_lock_types_its_prerequisite_and_its_clauses():
    lock = mechanic(LOCK)
    assert lock["coverage"] == "CORE_WITH_RIDERS", lock["coverage"]
    # Compiler admission does not evaluate activation.requirement: preserve the prerequisite
    # as an explicit reminder rather than presenting an unenforced gate.
    assert lock["activation"]["requirement"] is None
    assert any("Prerequisite:" in rider and "Tethers" in rider for rider in lock["riders"]), lock["riders"]
    save = lock["effects"][0]
    assert save["type"] == "save" and save["ability"] == "con"
    assert {row["type"] for row in save["on_fail"]} == {"reaction_denied", "disadvantage"}
    assert save["on_success"][0]["type"] == "reaction_denied"
    # The deferred first-spend tax is a rider, never a typed drain on the failed save.
    assert len(lock["riders"]) == 1 and "spends 2 additional" in lock["riders"][0], lock["riders"]


def test_meridian_chain_lock_never_charges_the_deferred_spend_on_the_failed_save():
    lock = mechanic(LOCK)
    rows = [row for effect in lock["effects"] for branch in ("on_fail", "on_success", "on_hit", "on_miss")
            for row in effect.get(branch, [])]
    assert not [row for row in rows if row["type"] == "spend_resource"], rows
    assert not [row for row in rows if "spends" in str(row.get("evidence", ""))], rows


def test_meridian_chain_lock_denies_the_targets_reactions(tmp_path):
    combat, table, mid = fight(tmp_path, [LOCK], left_save_dc=FAILING_SAVE_DC, cl=15,
                               positions={LEFT: {"x": 3, "y": 6}, RIGHT: {"x": 4, "y": 6}})
    turn(table, mid, LEFT)
    engine = reload(combat, mid)
    action = next(c for c in engine.legal_candidates() if "Meridian Chain Lock" in c.display_name)
    state = table.state(mid)
    menu = state["menu"]
    result = table.act(mid, action.candidate_id, menu["decision_id"], menu["state_version"],
                       state["last_sequence"], [])
    assert result["status"] == "COMMITTED", result
    engine = reload(combat, mid)
    assert "reaction_denied" in conditions(engine.state.actors[RIGHT]), conditions(engine.state.actors[RIGHT])


def test_no_converted_chains_mechanic_still_asks_the_game_master_for_its_printed_lines():
    for talent in (COUNTER, SOVEREIGN, HOOK, GRAPPLING):
        record = mechanic(talent)
        assert record["coverage"] == "FULL", (talent, record["coverage"])
        assert not record["riders"], (talent, record["riders"])
    # Meridian Chain Lock is the honest exception: its deferred CP tax is a kept rider (PARTIAL).
    assert mechanic(LOCK)["coverage"] == "CORE_WITH_RIDERS"
    assert mechanic(LOCK)["riders"]
