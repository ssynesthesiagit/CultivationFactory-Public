"""A2GTRECON — purchased Treasure Consumables fight as real actions.

Lane A2GTRECON (2026-10-11). Treasure consumables bought at creation were, until this lane, rendered as text
on the sheet with no combat representation at all: ``combat/factory_compiler.py`` read
``resolved_treasure_purchases`` for ``wondrous`` only, so every printed combat effect of the 87 consumables
was a GM-only note. These cases drive the highest-combat-impact family (Combat Pellets, "Action; throw to N
feet") through a live CombatService table: an action is published from the purchase, a chosen point detonates
it, the printed saving throw resolves, damage and conditions commit, the batch is charged, and a cold reload
plus mechanical replay retain all of it.

Every assertion reads the reloaded engine, never the live one.
"""
import pytest

from tests.h1_support import sheet
from tests.worker2_support import ALLY, FOE, OWNER, candidate, fixture, reload, settle

from combat.ext import treasure_consumables as tc

DRAGON = "tianxia.treasure.consumable.011.dragon_furnace_explosive_pellet"
THUNDER = "tianxia.treasure.consumable.014.thunderclap_pellet"
CALAMITY = "tianxia.treasure.consumable.019.calamity_star_pellet"
BLAST_POINT = (5, 3)  # a point whose 10-foot sphere reaches the foe at (5,5)


def _consumable_kit(consumable_id, name, quantity=2):
    """A starting kit whose only treasure purchase is one consumable batch of ``quantity`` uses."""
    return {"starting_kit": {"items": [], "resolved_treasure_purchases": {"consumables": [
        {"consumable_id": consumable_id, "name": name, "family": "Combat Pellets", "grade": "Spiritual",
         "activation": "Action; throw to 60 feet", "batch_quantity": quantity, "batch_unit": "pellets",
         "batch_price_gt": 200, "text": "printed text is not read by the engine"}]}}}


def _fixture(tmp_path, consumable_id, name, *, quantity=2):
    return fixture(tmp_path, [], seed="A2GTRECON",
                   owner_kit=_consumable_kit(consumable_id, name, quantity),
                   positions={OWNER: {"x": 3, "y": 6}, FOE: {"x": 5, "y": 5}})


def _saves(engine, actor_id):
    return [e for e in engine.events if e.event_type == "SAVE_ROLLED" and e.actor_id == actor_id]


def test_purchased_consumable_compiles_a_thrown_action(tmp_path):
    combat, table, mid = _fixture(tmp_path, DRAGON, "Dragon-Furnace Explosive Pellet")
    engine = reload(tmp_path, mid)
    action = engine.action_catalog.get(f"action:typed.{OWNER.split(':')[-1]}.consumable.{DRAGON}")
    if action is None:  # the compiled key uses the actor's short id, so find it by its own source
        action = next(a for a in engine.action_catalog.values()
                      if (((a.parameters or {}).get("typed") or {}).get("source")) == f"consumable.{DRAGON}")
    assert action.display_name == "Dragon-Furnace Explosive Pellet"
    assert action.range_ft == 60, "the printed 60-foot throw"
    assert action.parameters["consumable_batch_quantity"] == 2
    # The printed DC rides on this action only; it does not change the fighter's own save DC.
    assert (action.parameters["typed"]["numbers"])["save_dc"] == 13
    assert engine.state.actors[OWNER].current_hp > 0


def test_burst_resolves_the_printed_save_and_damage(tmp_path):
    combat, table, mid = _fixture(tmp_path, DRAGON, "Dragon-Furnace Explosive Pellet")
    foe_before = combat._load_session(mid).engine.state.actors[FOE].current_hp
    action = candidate(combat, mid, "Dragon-Furnace Explosive Pellet", at=BLAST_POINT)
    settle(table, mid, action.candidate_id)
    after = reload(tmp_path, mid)
    assert _saves(after, FOE), "the printed DC 13 Dexterity save is rolled for the creature in the area"
    save = _saves(after, FOE)[0]
    assert save.payload["dc"] == 13
    damage = [e for e in after.events if e.event_type == "DAMAGE_COMMITTED" and FOE in e.target_ids]
    assert damage, "a failed save takes 4d6 fire damage"
    if not save.payload["success"]:
        assert after.state.actors[FOE].current_hp < foe_before
    else:
        assert 0 < foe_before - after.state.actors[FOE].current_hp <= 12, "a successful save takes half damage"


def test_using_a_pellet_charges_one_use_of_the_batch(tmp_path):
    combat, table, mid = _fixture(tmp_path, DRAGON, "Dragon-Furnace Explosive Pellet", quantity=2)
    settle(table, mid, candidate(combat, mid, "Dragon-Furnace Explosive Pellet", at=BLAST_POINT).candidate_id)
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert owner.turn_flags[tc.SPENT_PREFIX + DRAGON] == 1, "one use of the purchased batch is charged"
    # Two were bought, so a second detonation remains available for this batch.
    assert tc.remaining(owner, DRAGON, 2) == 1


def test_an_exhausted_batch_stops_offering_the_action(tmp_path):
    combat, table, mid = _fixture(tmp_path, DRAGON, "Dragon-Furnace Explosive Pellet", quantity=1)
    settle(table, mid, candidate(combat, mid, "Dragon-Furnace Explosive Pellet", at=BLAST_POINT).candidate_id)
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert owner.turn_flags[tc.SPENT_PREFIX + DRAGON] == 1
    assert tc.remaining(owner, DRAGON, 1) == 0, "the single purchased use is spent"
    # The stock gate itself refuses the action, independent of this turn's Action economy.
    action = next(a for a in engine.action_catalog.values() if a.display_name == "Dragon-Furnace Explosive Pellet")
    assert tc._stock_gate(engine, owner, None, action) is False


def test_the_stock_gate_answers_only_about_purchased_consumables(tmp_path):
    """An ordinary ability is untouched by the gate, so no existing fighter loses a choice."""
    combat, table, mid = _fixture(tmp_path, DRAGON, "Dragon-Furnace Explosive Pellet", quantity=2)
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    others = [a for a in engine.action_catalog.values() if a.owner_id == OWNER and "consumable_batch_quantity" not in (a.parameters or {})]
    assert others, "the fighter has ordinary actions besides the consumable"
    assert all(tc._stock_gate(engine, owner, None, a) is None for a in others)


def test_a_burst_hits_the_hostile_in_the_area_and_never_its_thrower(tmp_path):
    """Unscoped damaging areas resolve against the hostiles in the area; the caster is never caught in its own burst."""
    combat, table, mid = fixture(tmp_path, [], seed="A2GTRECON",
                                 owner_kit=_consumable_kit(DRAGON, "Dragon-Furnace Explosive Pellet", 2),
                                 positions={OWNER: {"x": 5, "y": 3}, ALLY: {"x": 4, "y": 3},
                                            FOE: {"x": 5, "y": 5}})
    live = combat._load_session(mid).engine
    owner_before, ally_before = live.state.actors[OWNER].current_hp, live.state.actors[ALLY].current_hp
    settle(table, mid, candidate(combat, mid, "Dragon-Furnace Explosive Pellet", at=(5, 3)).candidate_id)
    after = reload(tmp_path, mid)
    assert _saves(after, FOE), "the hostile in the area makes the printed save"
    assert not _saves(after, OWNER) and not _saves(after, ALLY), "only the hostile is a burst recipient"
    assert after.state.actors[OWNER].current_hp == owner_before, "the thrower is not hit by its own burst"
    assert after.state.actors[ALLY].current_hp == ally_before


@pytest.mark.parametrize("consumable_id,name,dc", [
    (THUNDER, "Thunderclap Pellet", 13),
    (CALAMITY, "Calamity-Star Pellet", 17),
], ids=["thunderclap-dc13", "calamity-star-dc17"])
def test_each_pellet_uses_its_own_printed_dc(tmp_path, consumable_id, name, dc):
    combat, table, mid = _fixture(tmp_path, consumable_id, name)
    settle(table, mid, candidate(combat, mid, name, at=BLAST_POINT).candidate_id)
    after = reload(tmp_path, mid)
    save = _saves(after, FOE)
    assert save and save[0].payload["dc"] == dc, f"{name} prints DC {dc}"


def test_thunderclap_failed_save_deafens_and_denies_reactions(tmp_path):
    combat, table, mid = _fixture(tmp_path, THUNDER, "Thunderclap Pellet")
    settle(table, mid, candidate(combat, mid, "Thunderclap Pellet", at=BLAST_POINT).candidate_id)
    after = reload(tmp_path, mid)
    conditions = {c.condition_id.rsplit(".", 1)[-1] for c in after.state.actors[FOE].conditions.values()}
    if not _saves(after, FOE)[0].payload["success"]:
        assert "deafened" in conditions
        assert after.state.actors[FOE].reaction_available is False


def test_a_saved_burst_halves_its_damage_and_applies_no_condition(tmp_path):
    combat, table, mid = _fixture(tmp_path, THUNDER, "Thunderclap Pellet", quantity=4)
    foe_before = combat._load_session(mid).engine.state.actors[FOE].current_hp
    settle(table, mid, candidate(combat, mid, "Thunderclap Pellet", at=BLAST_POINT).candidate_id)
    after = reload(tmp_path, mid)
    if _saves(after, FOE)[0].payload["success"]:
        conditions = {c.condition_id.rsplit(".", 1)[-1] for c in after.state.actors[FOE].conditions.values()}
        assert "deafened" not in conditions, "a successful save suffers no other effect"
        assert after.state.actors[FOE].reaction_available is True
        assert 0 < foe_before - after.state.actors[FOE].current_hp <= 12


def test_a_character_without_the_purchase_gets_no_consumable_action(tmp_path):
    combat, table, mid = fixture(tmp_path, [], seed="A2GTRECON",
                                 positions={OWNER: {"x": 3, "y": 6}, FOE: {"x": 5, "y": 5}})
    engine = reload(tmp_path, mid)
    consumables = [a for a in engine.action_catalog.values()
                   if str((((a.parameters or {}).get("typed") or {}).get("source")) or "").startswith("consumable.")]
    assert not consumables, "an unbought consumable invents no action"


def test_an_unautomated_consumable_stays_inert(tmp_path):
    """A purchased batch whose family is not automated yet compiles no action rather than invented behaviour."""
    combat, table, mid = fixture(
        tmp_path, [], seed="A2GTRECON",
        owner_kit=_consumable_kit("tianxia.treasure.consumable.079.life_saving_golden_cicada",
                                  "Life-Saving Golden Cicada", quantity=1),
        positions={OWNER: {"x": 3, "y": 6}, FOE: {"x": 5, "y": 5}})
    engine = reload(tmp_path, mid)
    assert not [a for a in engine.action_catalog.values()
                if str((((a.parameters or {}).get("typed") or {}).get("source")) or "").startswith("consumable.")]

from combat.canonical import canonical_sha256
from combat import ext
from combat.gate2_runtime_models import Position, RuntimeObjectState
from tests.worker2_support import turn


def _forced_fixture(tmp_path, cid, name, *, success=False, quantity=1, kits=None, setup=None, positions=None, foe_hp=1000):
    def seal(bundles):
        for b in bundles:
            if b["actor_id"] == FOE:
                b["actor_template"]["saving_throws"] = {a: (100 if success else -100) for a in ("STR", "DEX", "CON", "INT", "WIS", "CHA")}
                b["actor_template"]["maximum_hp"] = foe_hp
            if b["actor_id"] == OWNER and setup:
                action = {"source_definition_id": "action:test.treasure.setup", "display_name": "Prepare consumable test",
                          "owner_id": OWNER, "economy": "NONE", "resolution_kind": "TYPED", "target_kind": "SELF",
                          "parameters": {"typed": {"source": "test:treasure.setup", "effects": [{"type": "test_treasure_setup"}]}}}
                b["action_catalog"].append(action)
                b["actor_template"]["action_ids"].append(action["source_definition_id"])
            b.pop("bundle_sha256", None)
            b["bundle_sha256"] = canonical_sha256(b)
    return fixture(tmp_path, [], seed="A2GTRECON-CERTIFIED", owner_kit=kits or _consumable_kit(cid, name, quantity),
                   positions=positions or {OWNER: {"x": 3, "y": 6}, ALLY: {"x": 4, "y": 6}, FOE: {"x": 5, "y": 5}}, bundle_transform=seal)


@pytest.mark.parametrize("cid,name,dc,count,sides,kinds", [
    (DRAGON, "Dragon-Furnace Explosive Pellet", 13, 4, 6, ["FIRE"]),
    (THUNDER, "Thunderclap Pellet", 13, 3, 8, ["THUNDER"]),
    (CALAMITY, "Calamity-Star Pellet", 17, 6, 8, ["LIGHTNING", "FORCE"]),
])
@pytest.mark.parametrize("success", [False, True], ids=["failed-save", "successful-save"])
def test_both_outcomes_deliver_every_printed_damage_packet(tmp_path, cid, name, dc, count, sides, kinds, success):
    combat, table, mid = _forced_fixture(tmp_path, cid, name, success=success)
    before = reload(tmp_path, mid)
    hp = before.state.actors[FOE].current_hp
    chosen = candidate(combat, mid, name, at=BLAST_POINT)
    settle(table, mid, chosen.candidate_id)
    after = reload(tmp_path, mid)
    saves = _saves(after, FOE)
    assert len(saves) == 1 and saves[0].payload["dc"] == dc
    assert saves[0].payload["success"] is success
    rolls = [e for e in after.events if e.event_type == "DAMAGE_ROLLED" and e.source_definition_id == chosen.source_definition_id]
    commits = [e for e in after.events if e.event_type == "DAMAGE_COMMITTED" and FOE in e.target_ids]
    assert len(rolls) == len(commits) == len(kinds)
    assert [e.payload["damage_type"] for e in commits] == kinds
    assert all(len(e.payload["dice"]) == count and all(1 <= d <= sides for d in e.payload["dice"]) for e in rolls)
    divisor = 2 if success else 1
    expected = [int(e.payload["total"]) // divisor for e in rolls]
    assert [e.payload["hp_damage"] for e in commits] == expected
    assert hp - after.state.actors[FOE].current_hp == sum(expected) > 0
    conditions = {c.condition_id.rsplit(".", 1)[-1] for c in after.state.actors[FOE].conditions.values()}
    if cid == THUNDER:
        assert ("deafened" in conditions) is (not success)
        assert after.state.actors[FOE].reaction_available is success
    if cid == CALAMITY:
        assert ("prone" in conditions) is (not success)
    assert not _saves(after, OWNER) and not _saves(after, ALLY)
    assert after.state.actors[OWNER].turn_flags[tc.SPENT_PREFIX + cid] == 1
    assert not any(e.event_type == "GM_RIDER" and e.source_definition_id == chosen.source_definition_id for e in after.events)


def test_calamity_star_reaches_the_printed_twenty_foot_radius(tmp_path):
    combat, table, mid = _forced_fixture(tmp_path, CALAMITY, "Calamity-Star Pellet", positions={
        OWNER: {"x": 3, "y": 6}, ALLY: {"x": 4, "y": 6}, FOE: {"x": 5, "y": 6}})
    settle(table, mid, candidate(combat, mid, "Calamity-Star Pellet", at=BLAST_POINT).candidate_id)
    assert _saves(reload(tmp_path, mid), FOE)


def test_purchased_stock_does_not_return_on_the_next_turn(tmp_path):
    combat, table, mid = _forced_fixture(tmp_path, DRAGON, "Dragon-Furnace Explosive Pellet", quantity=1)
    settle(table, mid, candidate(combat, mid, "Dragon-Furnace Explosive Pellet", at=BLAST_POINT).candidate_id)
    settle(table, mid, table.state(mid)["menu"]["end_turn"])
    turn(table, mid, OWNER)
    after = reload(tmp_path, mid)
    assert after.state.actors[OWNER].turn_flags[tc.SPENT_PREFIX + DRAGON] == 1
    assert not any(getattr(combat._load_session(mid).engine.action_catalog.get(c.source_definition_id), "display_name", None) == "Dragon-Furnace Explosive Pellet"
                   for c in combat._load_session(mid).engine.legal_candidates())


def test_repeated_purchases_pool_stock_and_publish_one_action(tmp_path):
    kit = _consumable_kit(DRAGON, "Dragon-Furnace Explosive Pellet", 2)
    kit["starting_kit"]["resolved_treasure_purchases"]["consumables"].append(
        dict(kit["starting_kit"]["resolved_treasure_purchases"]["consumables"][0], batch_quantity=3))
    combat, table, mid = _forced_fixture(tmp_path, DRAGON, "Dragon-Furnace Explosive Pellet", kits=kit)
    settle(table, mid, candidate(combat, mid, "Dragon-Furnace Explosive Pellet", at=BLAST_POINT).candidate_id)
    after = reload(tmp_path, mid)
    actions = [a for a in after.action_catalog.values() if a.display_name == "Dragon-Furnace Explosive Pellet"]
    assert len(actions) == 1 and actions[0].parameters["consumable_batch_quantity"] == 5
    assert tc.remaining(after.state.actors[OWNER], DRAGON, 5) == 4


def _install_setup(monkeypatch, setup):
    ext.effects()
    monkeypatch.setitem(ext._EFFECTS, "test_treasure_setup", setup)


def _objects_setup(ctx, row):
    for oid, x, y, flammable, unattended in (("wood", 6, 3, True, True), ("held", 4, 3, True, False), ("stone", 5, 4, False, True)):
        ctx.engine._update_object(RuntimeObjectState(object_id="object:test.treasure." + oid,
            object_kind="custom", position=Position(x=x, y=y), unattended=unattended, flammable=flammable,
            ac=0, current_hp=200, maximum_hp=200, component={"blocks": False}), ctx.source, ctx.actor.entity_id)


@pytest.mark.parametrize("cid,name", [(DRAGON, "Dragon-Furnace Explosive Pellet"), (CALAMITY, "Calamity-Star Pellet")])
def test_printed_object_clauses_are_persisted(tmp_path, monkeypatch, cid, name):
    _install_setup(monkeypatch, _objects_setup)
    combat, table, mid = _forced_fixture(tmp_path, cid, name, setup=True)
    settle(table, mid, candidate(combat, mid, "Prepare consumable test").candidate_id)
    settle(table, mid, candidate(combat, mid, name, at=BLAST_POINT).candidate_id)
    after = reload(tmp_path, mid)
    wood, held, stone = [after.state.objects["object:test.treasure." + n] for n in ("wood", "held", "stone")]
    if cid == DRAGON:
        assert wood.ignited and not held.ignited and not stone.ignited
    else:
        assert wood.current_hp == stone.current_hp == 152 and held.current_hp == 200


@pytest.mark.parametrize("administer", [False, True], ids=["self-bonus-action", "dying-ally-action"])
def test_recovery_pill_heals_and_charges_the_buyers_batch(tmp_path, monkeypatch, administer):
    def injure(ctx, row):
        target = ctx.engine.state.actors[ALLY if administer else OWNER]
        ctx.engine._commit_damage(target, target.current_hp if administer else 40, "FORCE", ctx.source, FOE, ctx.intent, reaction_depth=3)
    _install_setup(monkeypatch, injure)
    combat, table, mid = _forced_fixture(tmp_path, tc.RECOVERY, "Nine-Breath Recovery Pill", setup=True)
    settle(table, mid, candidate(combat, mid, "Prepare consumable test").candidate_id)
    before = reload(tmp_path, mid)
    aid = ALLY if administer else OWNER
    action = candidate(combat, mid, "Administer Nine-Breath Recovery Pill" if administer else "Nine-Breath Recovery Pill", target=aid if administer else None)
    settle(table, mid, action.candidate_id)
    after = reload(tmp_path, mid)
    gained = after.state.actors[aid].current_hp - before.state.actors[aid].current_hp
    assert 4 <= gained <= 18
    assert after.state.actors[OWNER].turn_flags[tc.SPENT_PREFIX + tc.RECOVERY] == 1
    assert after.state.actors[OWNER].action_available is (not administer)
    assert after.state.actors[OWNER].bonus_action_available is administer
    assert after.state.actors[aid].active and after.state.actors[aid].life_state in (None, "CONSCIOUS")


@pytest.mark.parametrize("object_target", [False, True], ids=["creature", "object"])
def test_firebolt_uses_fixed_attack_bonus_and_consumes_on_hit_or_miss(tmp_path, monkeypatch, object_target):
    _install_setup(monkeypatch, _objects_setup)
    combat, table, mid = _forced_fixture(tmp_path, tc.FIREBOLT, "Firebolt Talisman", setup=True)
    settle(table, mid, candidate(combat, mid, "Prepare consumable test").candidate_id)
    tid = "object:test.treasure.wood" if object_target else FOE
    chosen = candidate(combat, mid, "Firebolt Talisman", target=tid)
    settle(table, mid, chosen.candidate_id)
    after = reload(tmp_path, mid)
    rolls = [e for e in after.events if e.event_type == "ATTACK_ROLLED" and e.source_definition_id == chosen.source_definition_id]
    assert rolls and rolls[0].payload["modifier"] == 5
    assert after.state.actors[OWNER].turn_flags[tc.SPENT_PREFIX + tc.FIREBOLT] == 1
    damages = [e for e in after.events if e.event_type == "DAMAGE_ROLLED" and e.source_definition_id == chosen.source_definition_id]
    hit = rolls[0].payload["provisional_hit"]
    assert bool(damages) is hit
    if hit:
        assert len(damages[0].payload["dice"]) in (4, 8)
        if object_target:
            assert after.state.objects[tid].current_hp < 200
        else:
            assert after.state.actors[FOE].current_hp < 1000


@pytest.mark.parametrize("cid,name", [
    (tc.FIREBOLT, "Firebolt Talisman"),
    (tc.CORROSIVE, "Bone-Melting Corrosive Pellet"),
])
def test_empty_remembered_square_attack_spends_owned_consumable_after_cold_reload(tmp_path, monkeypatch, cid, name):
    def hide_and_move_target(ctx, row):
        target = ctx.engine.state.actors[FOE]
        observed = target.position.model_copy()
        ctx.engine.state.observations[ctx.actor.team_id][FOE] = observed
        ctx.engine._apply_condition(target, "condition:typed.invisible", ctx.source, FOE,
                                    expires_on="UNTIL_REMOVED")
        target.position = Position(x=observed.x, y=observed.y - 1)

    _install_setup(monkeypatch, hide_and_move_target)
    combat, table, mid = _forced_fixture(tmp_path, cid, name, setup=True, quantity=1)
    settle(table, mid, candidate(combat, mid, "Prepare consumable test").candidate_id)
    chosen = candidate(combat, mid, name, target=FOE)
    assert chosen.destination == Position(x=5, y=5), "the attack uses only the last observed square"
    settle(table, mid, chosen.candidate_id)

    after = reload(tmp_path, mid)
    actor = after.state.actors[OWNER]
    misses = [event for event in after.events
              if event.event_type == "ATTACK_LOCATION_MISSED" and event.source_definition_id == chosen.source_definition_id]
    assert misses and misses[0].payload["reason"] == "EMPTY_REMEMBERED_SQUARE"
    assert not [event for event in after.events
                if event.event_type == "DAMAGE_COMMITTED" and event.source_definition_id == chosen.source_definition_id]
    assert actor.turn_flags[tc.SPENT_PREFIX + cid] == 1
    assert not [candidate for candidate in after.legal_candidates()
                if after.action_catalog.get(candidate.source_definition_id)
                and after.action_catalog[candidate.source_definition_id].display_name == name]


def test_swift_step_is_a_chosen_physical_route_without_opportunities(tmp_path):
    combat, table, mid = _forced_fixture(tmp_path, tc.SWIFT, "Swift-Step Talisman")
    before = reload(tmp_path, mid).state.actors[OWNER].movement_remaining_ft
    prompts = settle(table, mid, candidate(combat, mid, "Swift-Step Talisman").candidate_id,
                     picks={"choice:treasure.free_step": "cell:3,4"})
    prompt = prompts[0]["moment"]
    assert "one talisman" in prompt
    assert "Bonus Action" in prompt
    assert "staying here" in prompt and "still spends both" in prompt
    after = reload(tmp_path, mid)
    actor = after.state.actors[OWNER]
    assert (actor.position.x, actor.position.y) == (3, 4)
    assert actor.movement_remaining_ft == before
    assert actor.turn_flags[tc.SPENT_PREFIX + tc.SWIFT] == 1
    assert actor.action_available and not actor.bonus_action_available
    options = {o["id"] for p in prompts for o in (p.get("choice") or {}).get("options", [])}
    assert "cell:5,5" not in options and "cell:3,1" not in options
    moves = [e for e in after.events if e.event_type == "MOVEMENT_COMMITTED" and e.source_definition_id.endswith(tc.SWIFT)]
    assert len(moves) >= 2 and all(e.payload["without_provoking"] for e in moves)


def test_swift_step_decline_still_spends_the_talisman_and_bonus_action(tmp_path):
    combat, table, mid = _forced_fixture(tmp_path, tc.SWIFT, "Swift-Step Talisman")
    before = reload(tmp_path, mid).state.actors[OWNER]
    prompts = settle(table, mid, candidate(combat, mid, "Swift-Step Talisman").candidate_id,
                     picks={"choice:treasure.free_step": None})
    assert "still spends both" in prompts[0]["moment"]
    after = reload(tmp_path, mid).state.actors[OWNER]
    assert after.position == before.position, "declining the optional movement leaves the fighter in place"
    assert after.turn_flags[tc.SPENT_PREFIX + tc.SWIFT] == 1
    assert after.action_available and not after.bonus_action_available


@pytest.mark.parametrize("object_target", [False, True])
def test_corrosive_pellet_damage_and_maximum_object_damage(tmp_path, monkeypatch, object_target):
    _install_setup(monkeypatch, _objects_setup)
    combat, table, mid = _forced_fixture(tmp_path, tc.CORROSIVE, "Bone-Melting Corrosive Pellet", setup=True)
    settle(table, mid, candidate(combat, mid, "Prepare consumable test").candidate_id)
    tid = "object:test.treasure.wood" if object_target else FOE
    chosen = candidate(combat, mid, "Bone-Melting Corrosive Pellet", target=tid)
    settle(table, mid, chosen.candidate_id)
    after = reload(tmp_path, mid)
    attack = next(e for e in after.events if e.event_type == "ATTACK_ROLLED" and e.source_definition_id == chosen.source_definition_id)
    assert attack.payload["modifier"] == 5
    assert after.state.actors[OWNER].turn_flags[tc.SPENT_PREFIX + tc.CORROSIVE] == 1
    if attack.payload["provisional_hit"]:
        if object_target:
            assert after.state.objects[tid].current_hp == 176
        else:
            damaged = [e for e in after.events if e.event_type == "DAMAGE_COMMITTED" and FOE in e.target_ids]
            assert damaged and damaged[0].payload["damage_type"] == "ACID"
            assert 4 <= damaged[0].payload["hp_damage"] <= 48


def test_automatic_consumable_recipients_follow_printed_sides(tmp_path):
    combat, table, mid = _forced_fixture(tmp_path, tc.FIREBOLT, "Firebolt Talisman")
    chosen = candidate(combat, mid, "Firebolt Talisman", target=FOE)
    settle(table, mid, chosen.candidate_id)
    after = reload(tmp_path, mid)
    # Query against the same frozen, service-created roster using explicit AI mode;
    # the transaction and cold reload above establish the actual owned action.
    after.typed_control_modes[OWNER] = "LOCAL_AUTO"
    action = after.action_catalog[chosen.source_definition_id]
    actor = after.state.actors[OWNER]
    actor.turn_flags[tc.SPENT_PREFIX + tc.FIREBOLT] = 0
    from types import SimpleNamespace
    assert tc._stock_gate(after, actor, SimpleNamespace(target_ids=(ALLY,)), action) is False
    assert tc._stock_gate(after, actor, SimpleNamespace(target_ids=(FOE,)), action) is True


@pytest.mark.parametrize("success", [False, True])
def test_frost_bloom_initial_save_and_persistent_start_damage(tmp_path, success):
    from combat import zones
    combat, table, mid = _forced_fixture(tmp_path, tc.FROST, "Frost-Bloom Pellet", success=success)
    chosen = candidate(combat, mid, "Frost-Bloom Pellet", at=BLAST_POINT)
    settle(table, mid, chosen.candidate_id)
    initial = reload(tmp_path, mid)
    save = _saves(initial, FOE)[0]
    assert save.payload["dc"] == 13 and save.payload["success"] is success
    damage = [e for e in initial.events if e.event_type == "DAMAGE_COMMITTED" and FOE in e.target_ids]
    assert len(damage) == 1 and damage[0].payload["hp_damage"] > 0 and damage[0].payload["damage_type"] == "COLD"
    zone = next(z for z in zones.typed_zones(initial) if z.source_definition_id == chosen.source_definition_id)
    assert zone.duration_rounds == 10
    assert zones.zone_is_difficult(initial, zone, initial.state.actors[FOE])
    hp = initial.state.actors[FOE].current_hp
    # Start the target's turn via real Table session end-turn intents.
    settle(table, mid, table.state(mid)["menu"]["end_turn"])
    turn(table, mid, FOE)
    after = reload(tmp_path, mid)
    assert 1 <= hp - after.state.actors[FOE].current_hp <= 6
    assert not _saves(after, OWNER) and not _saves(after, ALLY)
    assert after.state.actors[OWNER].turn_flags[tc.SPENT_PREFIX + tc.FROST] == 1
    assert zone.zone_id in after.state.zones


@pytest.mark.parametrize("cid,name", [(DRAGON, "Dragon-Furnace Explosive Pellet"), (THUNDER, "Thunderclap Pellet"),
    (CALAMITY, "Calamity-Star Pellet"), (tc.FROST, "Frost-Bloom Pellet")])
def test_areas_protect_allies_and_owner_inside_the_actual_blast(tmp_path, cid, name):
    combat, table, mid = _forced_fixture(tmp_path, cid, name, positions={
        OWNER: {"x": 5, "y": 3}, ALLY: {"x": 4, "y": 3}, FOE: {"x": 5, "y": 4}})
    before = reload(tmp_path, mid)
    settle(table, mid, candidate(combat, mid, name, at=BLAST_POINT).candidate_id)
    after = reload(tmp_path, mid)
    assert _saves(after, FOE)
    for aid in (OWNER, ALLY):
        assert not _saves(after, aid)
        assert after.state.actors[aid].current_hp == before.state.actors[aid].current_hp


def test_thunderclap_denial_lasts_through_the_targets_next_turn(tmp_path):
    combat, table, mid = _forced_fixture(tmp_path, THUNDER, "Thunderclap Pellet")
    settle(table, mid, candidate(combat, mid, "Thunderclap Pellet", at=BLAST_POINT).candidate_id)
    settle(table, mid, table.state(mid)["menu"]["end_turn"])
    turn(table, mid, FOE)
    during = reload(tmp_path, mid)
    assert any(c.condition_id.endswith("deafened") for c in during.state.actors[FOE].conditions.values())
    assert any(c.condition_id.endswith("reaction_denied") for c in during.state.actors[FOE].conditions.values())
    settle(table, mid, table.state(mid)["menu"]["end_turn"])
    after = reload(tmp_path, mid)
    assert not any(c.condition_id.endswith(("deafened", "reaction_denied")) for c in after.state.actors[FOE].conditions.values())


def test_corrosive_object_destruction_records_dissolution(tmp_path, monkeypatch):
    def objects(ctx, row):
        _objects_setup(ctx, row)
        obj = ctx.engine.state.objects["object:test.treasure.wood"]
        ctx.engine._update_object(obj.model_copy(update={"maximum_hp": 12, "current_hp": 12}), ctx.source, ctx.actor.entity_id)
    _install_setup(monkeypatch, objects)
    combat, table, mid = _forced_fixture(tmp_path, tc.CORROSIVE, "Bone-Melting Corrosive Pellet", setup=True)
    settle(table, mid, candidate(combat, mid, "Prepare consumable test").candidate_id)
    chosen = candidate(combat, mid, "Bone-Melting Corrosive Pellet", target="object:test.treasure.wood")
    settle(table, mid, chosen.candidate_id)
    after = reload(tmp_path, mid)
    obj = after.state.objects["object:test.treasure.wood"]
    assert obj.destroyed and obj.current_hp == 0 and obj.component["dissolved"]


@pytest.mark.parametrize("cid,name", [
    (tc.RECOVERY, "Nine-Breath Recovery Pill"),
    (tc.SWIFT, "Swift-Step Talisman"),
])
def test_ai_owner_can_select_self_consumable_through_service_and_reload(tmp_path, monkeypatch, cid, name):
    setup = None
    if cid == tc.RECOVERY:
        def injure(ctx, row):
            owner = ctx.engine.state.actors[OWNER]
            ctx.engine._commit_damage(owner, 40, "FORCE", ctx.source, FOE, ctx.intent, reaction_depth=3)
        setup = injure
        _install_setup(monkeypatch, setup)
    combat, table, mid = _forced_fixture(tmp_path, cid, name, setup=bool(setup))
    if setup:
        settle(table, mid, candidate(combat, mid, "Prepare consumable test").candidate_id)
    hp_before_choice = reload(tmp_path, mid).state.actors[OWNER].current_hp
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode="LOCAL_AUTO")
    ai_engine = reload(tmp_path, mid)
    chosen = [c for c in ai_engine.legal_candidates()
              if ai_engine.action_catalog.get(c.source_definition_id)
              and ai_engine.action_catalog[c.source_definition_id].display_name == name]
    assert chosen, f"AI owner sees its legal {name} self action"
    assert all(c.target_ids in ((), (OWNER,)) for c in chosen)
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode="MANUAL")
    settle(table, mid, candidate(combat, mid, name).candidate_id,
           picks={"choice:treasure.free_step": "cell:3,4"} if cid == tc.SWIFT else None)
    after = reload(tmp_path, mid)
    actor = after.state.actors[OWNER]
    assert actor.turn_flags[tc.SPENT_PREFIX + cid] == 1
    if cid == tc.RECOVERY:
        assert actor.current_hp > hp_before_choice
    else:
        assert (actor.position.x, actor.position.y) == (3, 4)


@pytest.mark.parametrize("cid,name", [
    (DRAGON, "Dragon-Furnace Explosive Pellet"),
    (tc.FROST, "Frost-Bloom Pellet"),
    (THUNDER, "Thunderclap Pellet"),
    (CALAMITY, "Calamity-Star Pellet"),
    (tc.CORROSIVE, "Bone-Melting Corrosive Pellet"),
    (tc.FIREBOLT, "Firebolt Talisman"),
])
def test_ai_damage_estimate_reaches_normal_typed_candidate_scoring(tmp_path, cid, name):
    combat, table, mid = _forced_fixture(tmp_path, cid, name)
    engine = reload(tmp_path, mid)
    action = next(a for a in engine.action_catalog.values() if a.display_name == name)
    assert action.parameters["expected_damage"] > 0
    rows = [c for c in engine.legal_candidates() if c.source_definition_id == action.source_definition_id]
    assert rows and max(int(c.metadata.get("expected_damage") or 0) for c in rows) > 0
    from combat.gate4_context import build_decision_context
    from combat.gate4_controller import LocalDeterministicController
    policy, _ = combat.policies.for_actor(OWNER)
    context = build_decision_context(engine, policy, for_ai=True)
    scored = LocalDeterministicController()._score_candidate(
        context, max(rows, key=lambda c: int(c.metadata.get("expected_damage") or 0)), ())
    assert scored.total > 0, "the purchased action receives immediate value in the stock AI scorer"


@pytest.mark.parametrize("cid,name", [
    (DRAGON, "Dragon-Furnace Explosive Pellet"),
    (CALAMITY, "Calamity-Star Pellet"),
    (tc.FROST, "Frost-Bloom Pellet"),
    (THUNDER, "Thunderclap Pellet"),
])
def test_a_finishing_burst_still_pays_for_and_completes_its_printed_effects(tmp_path, monkeypatch, cid, name):
    """The burst's damage defeats the last opposing combatant; payment and printed object/zone clauses still resolve."""
    _install_setup(monkeypatch, _objects_setup)
    combat, table, mid = _forced_fixture(tmp_path, cid, name, setup=True, foe_hp=1, quantity=2)
    settle(table, mid, candidate(combat, mid, "Prepare consumable test").candidate_id)
    chosen = candidate(combat, mid, name, at=BLAST_POINT)
    settle(table, mid, chosen.candidate_id)
    after = reload(tmp_path, mid)
    assert after.state.terminal_result is not None and after.state.terminal_result.winning_team_id == "team:factory"
    assert not after.state.actors[FOE].active
    assert [e for e in after.events if e.event_type == "DAMAGE_COMMITTED" and FOE in e.target_ids
            and e.source_definition_id == chosen.source_definition_id], "the finishing damage is committed"
    assert after.state.actors[OWNER].turn_flags[tc.SPENT_PREFIX + cid] == 1, "exactly one use is spent"
    if cid == DRAGON:
        assert after.state.objects["object:test.treasure.wood"].ignited
    if cid == CALAMITY:
        assert after.state.objects["object:test.treasure.stone"].current_hp == 152
    if cid == tc.FROST:
        from combat import zones
        assert any(z.source_definition_id == chosen.source_definition_id for z in zones.typed_zones(after))
