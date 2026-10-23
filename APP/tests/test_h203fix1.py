"""HUNT203 SEVERE 1-4: real owned rows, table commit, cold reload.

Printed rules are from authority/typed_mechanics/rules_text.json:
Erode: 'A creature within 60 feet gains Temporary HP, damage reduction, an AC
bonus, a Speed bonus, Resistance, Invisible, or a cost reduction from an ordinary
temporary effect.' 'reduce Temporary HP gained by your Proficiency Bonus'.
Grave Tax: 'Reduce the healing or Temporary HP gained by an amount equal to
3d8 + your key ability modifier.' Cost: 4 CP.
Ward: 'Whenever a hostile creature starts its turn in Sand Terrain you control,
you may deal Slashing damage to it equal to your Proficiency Bonus.'
'A creature can take this damage from you only once per round.'
Countermeasure: 'If it does not use a roll, its damage reduction, AC bonus,
shield value, or movement prevention is reduced by your Proficiency Bonus.'
"""
import pytest
from combat import typed_reactions as tr
from combat.reaction_triggers import classify_mechanic_all
from combat.factory_compiler import TYPED_AUTHORITY
import json
from tests.worker2_support import fixture, reload, settle, OWNER, FOE, ALLY
from tests.test_tabletop_hunt6 import on_hold, HOLD
from tests.h1_support import script

ERODE = "TAL_VOID_ERODE_TECHNIQUE"
GRAVE = "TAL_DEATH_GRAVE_TAX"
WARD = "TAL_SAND_ABRADING_WARD"
CM = "TAL_LIGHTNING_CHARGED_COUNTERMEASURE"


def _definition(engine, source_id, name, *, owner, typed=None):
    """A catalog entry a table test can aim a grant through (also exercises one resolvable source)."""
    from combat.gate2_runtime_models import ActionDefinition

    engine.action_catalog[source_id] = ActionDefinition(source_definition_id=source_id, display_name=name,
        owner_id=owner, economy="ACTION", resolution_kind="TYPED", target_kind="SELF", costs=[],
        parameters={"typed": dict(typed or {})})
    return source_id


def run_hold(monkeypatch, tmp_path, talents, callback, **kwargs):
    combat, table, mid = fixture(tmp_path, talents, ask=False, **kwargs)
    on_hold(monkeypatch, callback)
    settle(table, mid, next(c.candidate_id for c in combat._load_session(mid).engine.legal_candidates()
                          if c.source_definition_id == HOLD), choices={"reaction:typed." + talent: "first" for talent in talents})
    return reload(tmp_path, mid)


@pytest.mark.parametrize("talent,kinds", [(ERODE, {"temp_hp_gained", "benefit_gained"}),
                                         (GRAVE, {"healed", "temp_hp_gained"})])
def test_printed_recovery_alternatives_are_distinct(talent, kinds):
    record = json.loads(TYPED_AUTHORITY.read_text())["mechanics"][talent]
    assert {m.kind for m in classify_mechanic_all(record)} == kinds


def test_gain_classification_preserves_reviewed_mixed_event_alternatives():
    records = json.loads(TYPED_AUTHORITY.read_text())["mechanics"]
    row = records["TAL_YANG_APPLYING_A_RISING_MARK#force_the_rising"]
    assert {m.kind for m in classify_mechanic_all(row)} == {
        "ally_hit", "temp_hp_gained", "moved", "healed", "technique_used", "became_hidden"}


@pytest.mark.parametrize("kind", ["hp", "temp_hp"])
def test_erode_answers_temp_hp_never_immortal_regeneration(monkeypatch, tmp_path, kind):
    def grant(e):
        target = e.state.actors[FOE]
        if kind == "hp":
            target.current_hp = 10
        (e._heal if kind == "hp" else e._grant_temp_hp)(target, 20, "test:regeneration", FOE,
            **({"notify_healed": True} if kind == "hp" else {}))
    e = run_hold(monkeypatch, tmp_path, [ERODE], grant)
    target = e.state.actors[FOE]
    reactions = [x for x in e.events if x.event_type == "REACTION_RESOLVED" and x.source_definition_id == ERODE]
    assert len(reactions) == (kind == "temp_hp")
    assert target.current_hp == (30 if kind == "hp" else target.maximum_hp)
    assert target.temporary_hp == (20 - e.state.actors[OWNER].proficiency_bonus if kind == "temp_hp" else 0)
    assert not any(c.condition_id.endswith("no_invisible") for c in target.conditions.values())


@pytest.mark.parametrize("kind", ["hp", "temp_hp"])
def test_grave_tax_reduces_before_commit_once_and_pays_four_cp(monkeypatch, tmp_path, kind):
    def grant(e):
        target = e.state.actors[FOE]
        if kind == "hp":
            target.current_hp = 10
        script(e, [2, 3, 4])
        (e._heal if kind == "hp" else e._grant_temp_hp)(target, 20, "test:regeneration", FOE,
            **({"notify_healed": True} if kind == "hp" else {}))
    e = run_hold(monkeypatch, tmp_path, [GRAVE], grant)
    row = next(r for r in e.typed_reaction_rows[OWNER] if r["feature_id"] == GRAVE)
    expected = max(0, 20 - 9 - row["numbers"]["key_mod"])
    grant = next(x for x in reversed(e.events) if x.event_type in {"HEALING_APPLIED", "TEMP_HP_GRANTED"}
                 and x.source_definition_id == "test:regeneration")
    assert grant.payload["offered"] == expected
    spent = [x for x in e.events if x.event_type == "RESOURCE_SPENT" and x.source_definition_id == GRAVE]
    assert [x.payload["amount"] for x in spent] == [4]
    assert not any(x.event_type == "GM_RIDER" and "Reduce the healing" in str(x.payload) for x in e.events)


def test_a_negative_key_modifier_cannot_turn_grave_tax_into_extra_healing(monkeypatch, tmp_path):
    from tests.cw2_service_support import seal
    def bundles(packets):
        for row in packets[0]["typed_reactions"]:
            if row["feature_id"] == GRAVE:
                row["numbers"]["key_mod"] = -5
        seal(packets[0])
    def grant(e):
        e.state.actors[FOE].current_hp = 10
        script(e, [1, 1, 1])
        e._heal(e.state.actors[FOE], 20, "test:regeneration", FOE, notify_healed=True)
    e = run_hold(monkeypatch, tmp_path, [GRAVE], grant, bundle_transform=bundles)
    assert e.state.actors[FOE].current_hp == 30
    assert next(x.payload["offered"] for x in e.events
                if x.event_type == "HEALING_APPLIED" and x.source_definition_id == "test:regeneration") == 20


@pytest.mark.parametrize("field,value,expected", [("armor_class", 3, 2), ("speed_ft", 20, 10),
    ("damage_reduction", 9, "pb"), ("damage_resistance", "FIRE", None)])
def test_erode_scopes_to_new_temporary_benefit(monkeypatch, tmp_path, field, value, expected):
    def grant(e):
        e._add_modifier(e.state.actors[FOE], "test:buff", field, "ADD", value, "SELF",
                        expires_on="START_OF_SOURCE_NEXT_TURN", source_actor_id=FOE)
    e = run_hold(monkeypatch, tmp_path, [ERODE], grant)
    target = e.state.actors[FOE]
    rows = [m for m in target.modifiers.values() if m.target_field == field]
    if expected == "pb":
        expected = value - e.state.actors[OWNER].proficiency_bonus
    assert [m.value for m in rows] == ([] if expected is None else [expected])
    assert any(x.event_type == "REACTION_RESOLVED" and x.source_definition_id == ERODE for x in e.events)


def test_erode_prevents_only_new_temporary_invisible(monkeypatch, tmp_path):
    def grant(e):
        e._apply_condition(e.state.actors[FOE], "condition:typed.invisible", "test:veil", FOE,
                           expires_on="START_OF_SOURCE_NEXT_TURN")
    e = run_hold(monkeypatch, tmp_path, [ERODE], grant)
    assert not any(c.condition_id == "condition:typed.invisible" for c in e.state.actors[FOE].conditions.values())
    assert any(x.event_type == "REACTION_RESOLVED" and x.source_definition_id == ERODE for x in e.events)


def test_erode_reduced_bonus_cannot_outlive_original_buff(monkeypatch, tmp_path):
    from tests.worker2_support import turn
    combat, table, mid = fixture(tmp_path, [ERODE], ask=False)
    def grant(e):
        e._add_modifier(e.state.actors[FOE], "test:buff", "armor_class", "ADD", 3, "SELF",
                        expires_on="START_OF_SOURCE_NEXT_TURN", source_actor_id=FOE)
    on_hold(monkeypatch, grant)
    cid = next(c.candidate_id for c in combat._load_session(mid).engine.legal_candidates() if c.source_definition_id == HOLD)
    settle(table, mid, cid, choices={"reaction:typed." + ERODE: "first"})
    assert [m.value for m in reload(tmp_path, mid).state.actors[FOE].modifiers.values() if m.target_field == "armor_class"] == [2]
    turn(table, mid, FOE)
    assert not any(m.target_field == "armor_class" for m in reload(tmp_path, mid).state.actors[FOE].modifiers.values())


@pytest.mark.parametrize("kind", ["hp", "temp_hp"])
def test_grave_tax_does_not_spend_on_a_grant_that_cannot_add_hp(monkeypatch, tmp_path, kind):
    def grant(e):
        target = e.state.actors[FOE]
        if kind == "temp_hp":
            target.temporary_hp = 25
        (e._heal if kind == "hp" else e._grant_temp_hp)(target, 20, "test:no_gain", FOE,
            **({"notify_healed": True} if kind == "hp" else {}))
    e = run_hold(monkeypatch, tmp_path, [GRAVE], grant)
    assert not any(x.event_type == "RESOURCE_SPENT" and x.source_definition_id == GRAVE for x in e.events)


@pytest.mark.parametrize("use", [False, True])
def test_grave_tax_ask_me_pauses_before_hp_commit(monkeypatch, tmp_path, use):
    from tests.test_r9i_karma_persistence import act
    combat, table, mid = fixture(tmp_path, [GRAVE], ask=True)
    def grant(e):
        e.state.actors[FOE].current_hp = 10
        script(e, [2, 3, 4])
        e._heal(e.state.actors[FOE], 20, "test:regeneration", FOE, notify_healed=True)
    on_hold(monkeypatch, grant)
    cid = next(c.candidate_id for c in combat._load_session(mid).engine.legal_candidates() if c.source_definition_id == HOLD)
    before = reload(tmp_path, mid).state.model_dump(mode="json")
    paused = act(table, mid, cid)
    assert paused["status"] == "REACTION_REQUIRED"
    assert reload(tmp_path, mid).state.model_dump(mode="json") == before
    prompt = paused["reaction"]
    assert "Grave Tax" in str(prompt)
    answer = {**prompt["context"], "selection": "USE" if use else "DECLINE"}
    result = act(table, mid, cid, [answer])
    assert result["status"] == "COMMITTED", result
    e = reload(tmp_path, mid)
    gain = next(x for x in reversed(e.events) if x.event_type == "HEALING_APPLIED" and x.source_definition_id == "test:regeneration")
    assert (gain.payload["offered"] < 20) is use
    assert len([x for x in e.events if x.event_type == "RESOURCE_SPENT" and x.source_definition_id == GRAVE]) == int(use)


def test_ward_has_one_implementation_and_only_controller_turn_start_damage(monkeypatch, tmp_path):
    from tests.test_auto50_sand import prepare_sand
    from tests.worker2_support import candidate, turn
    combat, table, mid = fixture(tmp_path, [WARD], bundle_transform=prepare_sand)
    settle(table, mid, candidate(combat, mid, "Prepare Sand Terrain").candidate_id)
    e = reload(tmp_path, mid)
    assert not any(r["feature_id"] == WARD for rows in e.typed_reaction_rows.values() for r in rows)
    assert not any(a.source_definition_id.endswith(WARD) for a in e.action_catalog.values())
    from tests.test_auto2_sand import foe_turn
    foe_turn(table, mid, {"choice:needle.sand_ward": "use"})
    e = reload(tmp_path, mid)
    hits = [x for x in e.events if x.event_type == "DAMAGE_COMMITTED" and x.source_definition_id == WARD]
    assert len(hits) == 1 and hits[0].actor_id == OWNER and hits[0].target_ids == (FOE,)
    assert hits[0].payload["damage_type"] == "SLASHING"


@pytest.mark.parametrize("defense,incoming", [("damage", 20), ("damage", 3), ("ac", 20), ("shield", 20), ("movement", 20)])
def test_countermeasure_changes_actual_answered_defense(monkeypatch, tmp_path, defense, incoming):
    """Failing its save reduces only the accepted no-roll reaction's defense."""
    from combat.ext.states import context
    from combat.typed_executor import run_effects
    from tests.cw2_service_support import seal
    kinds = {"damage": "damaged", "ac": "hit", "shield": "missed", "movement": "forced_moved"}
    effects = {"damage": {"type": "damage_modifier", "flat": 12, "applies_to": "self"},
               "ac": {"type": "ac_bonus", "amount": 12, "applies_to": "self"},
               "shield": {"type": "temp_hp", "flat": 12, "applies_to": "self"},
               "movement": {"type": "forced_movement", "distance_ft": 12, "evidence": "reduce that movement by 12 feet"}}
    def bundles(packets):
        packets[2]["actor_template"]["saving_throws"]["CON"] = -100
        packets[2]["typed_reactions"].append({"feature_id": "test:defense", "block": "generic",
            "name": "Test defensive reaction", "kind": kinds[defense], "effects": [effects[defense]],
            "numbers": {}, "free": False, "costs": [], "range_ft": 60})
        seal(packets[2])
    def counter(e):
        reactor, target = e.state.actors[FOE], e.state.actors[OWNER]
        run_effects(context(e, target, "test:charge", [reactor], {}),
                    [{"type": "mark", "mark": "Charged", "applies_to": "target"}])
        script(e, [1])
        if defense == "damage":
            e._commit_damage(reactor, incoming, "FORCE", "test:damage", OWNER, e._active_intent, reaction_depth=0)
        elif defense == "ac":
            base = reactor.armor_class
            ac, hit = tr.on_attack_hit(e, target, reactor, {"range_ft": 30}, base + 9, 15, base)
            assert hit and ac == base + 12 - target.proficiency_bonus
        elif defense == "movement":
            assert tr.on_forced_movement(e, reactor, target, 20) == 20 - (12 - target.proficiency_bonus)
        else:
            tr.on_attack_missed(e, target, reactor, {"range_ft": 30})
        # A later ordinary shield from another source is not penalized.
        run_effects(context(e, reactor, "test:other", [reactor], {}).with_source("test:other"),
                    [{"type": "temp_hp", "flat": 2, "applies_to": "self"}])
    e = run_hold(monkeypatch, tmp_path, [CM], counter, bundle_transform=bundles)
    amount = 12 - e.state.actors[OWNER].proficiency_bonus
    if defense == "shield":
        assert e.state.actors[FOE].temporary_hp == amount
    elif defense == "ac":
        assert next(m.value for m in e.state.actors[FOE].modifiers.values() if m.source_definition_id == "test:defense") == amount
    elif defense == "movement":
        event = next(x for x in e.events if x.event_type == "REACTION_RESOLVED" and x.source_definition_id == "test:defense")
        assert event.payload["distance_after"] == 20 - amount
    else:
        event = next(x for x in e.events if x.source_definition_id == "test:damage" and x.event_type == "DAMAGE_COMMITTED")
        assert event.payload["hp_damage"] == max(0, incoming - amount)
    assert not any("apply it by hand" in str(x.payload) for x in e.events)
    assert next(x.payload["offered"] for x in e.events
                if x.event_type == "TEMP_HP_GRANTED" and x.source_definition_id == "test:other") == 2


# ------------------------------------------------------------------------------------
# H203FIX1F1 pre-merge review F1-F5. Printed rules (owner rider, typed authority):
# "reduce Temporary HP gained by your Proficiency Bonus; reduce one damage reduction
# by your Proficiency Bonus until the start of your next turn; reduce one AC bonus by
# 1 until the start of your next turn; reduce one Speed bonus by 10 feet until the
# start of your next turn; suppress one temporary Resistance until the start of your
# next turn; prevent Invisible from that effect until the start of your next turn"
# and "Erode Technique cannot affect artifacts, Domains, Secret Inheritances,
# Formation cores, Realm-defining transformations, or permanent features."


def test_erode_leaves_an_allied_temporary_hp_gain_alone(monkeypatch, tmp_path):
    """F1: the pending Temporary-HP reduction is harm aimed at the gaining creature, so an ally's
    grant is never answered -- not even by a fully automatic owner."""
    def grant(e):
        e._grant_temp_hp(e.state.actors[ALLY], 20, "test:regeneration", ALLY)
    e = run_hold(monkeypatch, tmp_path, [ERODE], grant)
    reactions = [x for x in e.events if x.event_type == "REACTION_RESOLVED" and x.source_definition_id == ERODE]
    assert reactions == []
    assert e.state.actors[ALLY].temporary_hp == 20
    assert not any(x.event_type == "RESOURCE_SPENT" and x.source_definition_id == ERODE for x in e.events)




def _held(monkeypatch, tmp_path, talents, callback, **kwargs):
    """The ask-less fixtures return only the reloaded engine; keep the match id for a second reload."""
    combat, table, mid = fixture(tmp_path, talents, ask=False, **kwargs)
    on_hold(monkeypatch, callback)
    settle(table, mid, next(c.candidate_id for c in combat._load_session(mid).engine.legal_candidates()
                            if c.source_definition_id == HOLD))
    return mid


def test_erode_answers_a_nested_benefit_receipt(monkeypatch, tmp_path):
    """F2: Iron Shirt's +1 AC is created inside its own REACTION_RESOLVED handler
    (combat/ext/iron_shirt.py:86-100), so the MODIFIER_APPLIED that carries it is a nested child
    event. Erode must be able to answer that legal receipt before it lands, or neither the human
    nor the AI ever can, and the print order's reduction costs a CP it must return."""
    from tests.test_riders_c7 import SHIRT, STAMINA_GUARD, bundle as shirt_bundle, hostile_packet

    def packets(bundles):
        bundles[2] = shirt_bundle([SHIRT + "iron_shirt", STAMINA_GUARD], actor_id=FOE)
    def stop_the_hit(e):
        hostile_packet(e, FOE, 8, "SLASHING", attacker_id=OWNER)
    mid = _held(monkeypatch, tmp_path, [ERODE], stop_the_hit, bundle_transform=packets)
    e = reload(tmp_path, mid)
    reactions = [x for x in e.events if x.event_type == "REACTION_RESOLVED" and x.source_definition_id == ERODE]
    assert len(reactions) == 1
    spent = [x.payload["amount"] for x in e.events if x.event_type == "RESOURCE_SPENT" and x.source_definition_id == ERODE]
    assert spent == [1]
    bonus = [m for m in e.state.actors[FOE].modifiers.values() if m.target_field == "armor_class"]
    # Profile Bonus >= 1 reduces a +1 AC bonus to nothing; the holding suppression keeps it parked
    # until the start of the user's next turn, exactly as the printed reduction reads.
    assert bonus == []
    assert any(c.condition_id == "condition:typed.benefit_suppressed"
               and c.source_definition_id == ERODE for c in e.state.actors[FOE].conditions.values())


def test_erode_reduced_buff_ends_with_a_lost_concentration(monkeypatch, tmp_path):
    """F3: a reduced replacement has Erode's own source and expiry, so the concentration cleanup
    cannot see it. The original buff's concentration ending mid-turn must take the replacement (and
    the parked original) with it before the next action uses the reduced bonus, and the removals
    must survive a replay."""
    def cascade(e):
        _definition(e, "test:beam", "Reading Beam", owner=FOE)
        foe = e.state.actors[FOE]
        e._start_concentration(foe, "test:beam")
        # The printed AC option reduces by 1: the 9-point bonus leaves an 8-point
        # replacement that the target would keep using until the concentration ends.
        e._add_modifier(foe, "test:beam", "armor_class", "ADD", 9, "SELF", expires_on="CONCENTRATION_END")
        e._end_concentration(foe, "REPLACED")  # concentration lost in the middle of the round
        e._heal(foe, 5, "test:tap", foe.entity_id)  # another action before anyone's turn ends
    mid = _held(monkeypatch, tmp_path, [ERODE], cascade)
    e = reload(tmp_path, mid)
    assert len([x for x in e.events if x.event_type == "REACTION_RESOLVED" and x.source_definition_id == ERODE]) == 1
    assert [m.value for m in e.state.actors[FOE].modifiers.values() if m.target_field == "armor_class"] == []
    assert not any(c.condition_id == "condition:typed.benefit_suppressed" and c.source_definition_id == ERODE
                   for c in e.state.actors[FOE].conditions.values())
    assert any(x.event_type == "MODIFIER_REMOVED" and x.source_definition_id == ERODE
               and x.payload.get("reason") == "CONCENTRATION_ENDED" for x in e.events)
    assert any(x.event_type == "CONDITION_REMOVED" and x.source_definition_id == ERODE
               and x.payload.get("reason") == "CONCENTRATION_ENDED" for x in e.events)


def test_erode_temp_hp_respects_a_reviewed_source_exclusion(monkeypatch, tmp_path):
    """F13 finding 1: the printed exclusion is read from the source's own reviewed record
    through the shared source-eligibility decision, not from action flags no compiled row
    carries. Printed: "Erode Technique cannot affect artifacts, Domains, Secret
    Inheritances, Formation cores, Realm-defining transformations, or permanent features."
    TAL_DEATH_COURT_OF_THE_NINTH_GRAVE's owner record is headed "Court of the Ninth Grave -
    Domain", so a Temporary-HP grant from it is untouched."""
    source = "action:typed.TAL_DEATH_COURT_OF_THE_NINTH_GRAVE"
    def grant(e):
        _definition(e, source, "Court of the Ninth Grave", owner=FOE,
                    typed={"source": "TAL_DEATH_COURT_OF_THE_NINTH_GRAVE"})
        e._grant_temp_hp(e.state.actors[FOE], 20, source, FOE)
    e = run_hold(monkeypatch, tmp_path, [ERODE], grant)
    assert not any(x.event_type == "REACTION_RESOLVED" and x.source_definition_id == ERODE for x in e.events)
    assert e.state.actors[FOE].temporary_hp == 20
    assert not any(x.event_type == "RESOURCE_SPENT" and x.source_definition_id == ERODE for x in e.events)


def test_erode_modifier_receipt_respects_the_same_reviewed_exclusion(monkeypatch, tmp_path):
    """F13 finding 1, the stored-receipt path: the same printed Domain source grants an AC
    bonus, and Erode leaves it alone exactly as it leaves its Temporary HP alone."""
    source = "action:typed.TAL_DEATH_COURT_OF_THE_NINTH_GRAVE"
    def grant(e):
        _definition(e, source, "Court of the Ninth Grave", owner=FOE,
                    typed={"source": "TAL_DEATH_COURT_OF_THE_NINTH_GRAVE"})
        e._add_modifier(e.state.actors[FOE], source, "armor_class", "ADD", 3, "SELF",
                        expires_on="START_OF_SOURCE_NEXT_TURN", source_actor_id=FOE)
    e = run_hold(monkeypatch, tmp_path, [ERODE], grant)
    assert not any(x.event_type == "REACTION_RESOLVED" and x.source_definition_id == ERODE for x in e.events)
    assert [m.value for m in e.state.actors[FOE].modifiers.values() if m.target_field == "armor_class"] == [3]


def test_erode_temp_hp_keeps_answering_an_ordinary_resolvable_source(monkeypatch, tmp_path):
    """F4, the other branch: excluding unresolvable provenance would make ordinary grants
    unanswerable, so a catalog source without the flags is still reduced (it is the shared
    eligibility decision, not a second rule)."""
    source = "action:test.healer_shrine"
    def grant(e):
        _definition(e, source, "Healer's Shrine", owner=FOE)
        e._grant_temp_hp(e.state.actors[FOE], 20, source, FOE)
    e = run_hold(monkeypatch, tmp_path, [ERODE], grant)
    assert any(x.event_type == "REACTION_RESOLVED" and x.source_definition_id == ERODE for x in e.events)
    assert e.state.actors[FOE].temporary_hp == 20 - e.state.actors[OWNER].proficiency_bonus




@pytest.mark.parametrize("use", [False, True])
@pytest.mark.parametrize("benefit,granted,label,option", [
    ("AC", lambda e, source: e._add_modifier(e.state.actors[FOE], source, "armor_class", "ADD", 3, "SELF",
                                             expires_on="START_OF_SOURCE_NEXT_TURN", source_actor_id=FOE),
     "AC bonus +3 from Mage Light", "reduce that AC bonus by 1"),
    ("RES", lambda e, source: e._add_modifier(e.state.actors[FOE], source, "damage_resistance", "ADD", "FIRE", "SELF",
                                              expires_on="START_OF_SOURCE_NEXT_TURN", source_actor_id=FOE),
     "Resistance FIRE from Mage Light", "suppress that Resistance"),
    ("INVIS", lambda e, source: e._apply_condition(e.state.actors[FOE], "condition:typed.invisible", source, FOE,
                                                   expires_on="START_OF_SOURCE_NEXT_TURN"),
     "Invisible from Mage Light", "prevent the Invisible condition")])
def test_erode_benefit_decision_names_benefit_option_and_deadline(monkeypatch, tmp_path, use, benefit, granted, label, option):
    """F5: the offered decision names the gaining creature, the triggering ability, the exact
    benefit, the printed option Use runs, and its deadline -- "Something just happened ..." says
    none of those. The answer then does what it says: Use takes the benefit, Decline keeps it."""
    from tests.test_r9i_karma_persistence import act
    combat, table, mid = fixture(tmp_path, [ERODE], ask=True, named=True)
    def offer(e):
        source = _definition(e, "action:test.mage_light", "Mage Light", owner=FOE)
        granted(e, source)
    on_hold(monkeypatch, offer)
    cid = next(c.candidate_id for c in combat._load_session(mid).engine.legal_candidates() if c.source_definition_id == HOLD)
    paused = act(table, mid, cid)
    assert paused["status"] == "REACTION_REQUIRED", paused
    prompt = paused["reaction"]
    assert "Mara" in prompt["trigger"] and "Mage Light" in prompt["trigger"]  # gainer and triggering ability
    summary = prompt["summary"]
    assert "Something just happened" not in summary + prompt["trigger"]
    assert "Mara" in summary and label in summary      # the exact benefit on whom
    assert option in summary                           # the one printed option Use runs
    assert "start of Wren's next turn" in summary      # the deadline
    answer = {**prompt["context"], "selection": "USE" if use else "DECLINE"}
    result = act(table, mid, cid, [answer])
    assert result["status"] == "COMMITTED", result
    e = reload(tmp_path, mid)
    foe = e.state.actors[FOE]
    if benefit == "INVIS":
        assert any(c.condition_id == "condition:typed.invisible" for c in foe.conditions.values()) is not use
    else:
        granted_rows = [m for m in foe.modifiers.values() if m.source_definition_id == "action:test.mage_light"]
        assert bool(granted_rows) is not use
    spent = [x for x in e.events if x.event_type == "RESOURCE_SPENT" and x.source_definition_id == ERODE]
    assert len(spent) == int(use)


def test_pending_gain_is_a_typed_authority_field_not_prose():
    """F3R finding 4: an instantaneous recovery reduction is identified by a typed row
    field. Rewording the evidence must not change combat behavior, and matching prose
    without the field must not make a stored reduction a pending one."""
    from combat.typed_reactions import pending_healing_effect
    records = json.loads(TYPED_AUTHORITY.read_text())["mechanics"]
    assert any(e.get("pending_gain") is True for e in records[GRAVE]["effects"])
    erode_temp = next(o for o in records[ERODE]["options"] if o["label"] == "Reduce Temporary HP")
    assert erode_temp["effects"][0]["pending_gain"] is True
    assert pending_healing_effect({"type": "healing_reduction", "duration": "instant", "pending_gain": True,
                                   "evidence": "rewritten owner wording"})
    assert not pending_healing_effect({"type": "healing_reduction", "duration": "instant",
                                       "evidence": "Reduce the healing or Temporary HP gained"})
    assert not pending_healing_effect({"type": "healing_reduction", "duration": "until_start_of_your_next_turn",
                                       "pending_gain": True,
                                       "evidence": "Reduce the healing or Temporary HP gained"})


def test_charged_countermeasure_rider_asks_for_no_manual_work():
    """F3R finding 6: the failed-save rider must describe the automated reduction, not
    tell the GM to apply it by hand."""
    records = json.loads(TYPED_AUTHORITY.read_text())["mechanics"]
    riders = records[CM]["riders"]
    assert riders
    assert not any("by hand" in rider.casefold() or "gm settles" in rider.casefold() for rider in riders)
    assert any("reduced by your Proficiency Bonus" in rider for rider in riders)


def test_benefit_gained_moment_reads_plainly():
    """The benefit_gained decision (a temporary AC/Speed/Resistance/Invisible receipt) says what
    happened and what granted it. Without its own moment entry the offer fell back to "Something
    just happened", which names neither the creature nor the ability (H203FIX1F14R note)."""
    from combat.decision_text import _moment_sentence
    assert _moment_sentence("BENEFIT_GAINED", "Foe", "Owner", "Erode Technique") == \
        "Foe gained a temporary benefit from Owner's Erode Technique."
    assert _moment_sentence("BENEFIT_GAINED", "Foe", "", "") == "Foe gained a temporary benefit."


def test_grave_tax_answer_never_outlives_its_heal(monkeypatch, tmp_path):
    """H203FIX1F7R findings 1-2: an answer given before a heal that never notifies must not
    swallow a later bare "healed" notification. Everything runs on one live engine (a reload
    would clear the transient marker and hide the defect). Answers: the first heal (no
    notify_healed) is answered before commit; its HEALING_APPLIED makes that answer stale; a
    bare healed notification for the same creature is then offered Grave Tax again; the last
    notifying heal is answered once before commit and its notification is not re-offered."""
    def sequence(e):
        foe, owner = e.state.actors[FOE], e.state.actors[OWNER]
        script(e, [2, 3, 4, 2, 3, 4, 2, 3, 4])
        foe.current_hp = 10
        e._heal(foe, 20, "test:regeneration", FOE)  # no notify_healed: nothing announces this gain
        # Grave Tax spends the owner's one Reaction; a later round gives them another.
        owner.reaction_available = True
        tr.on_creature_event(e, foe, "healed")  # a later, unrelated recovery notification
        owner.reaction_available = True
        foe.current_hp = 10
        e._heal(foe, 20, "test:regeneration2", FOE, notify_healed=True)

    e = run_hold(monkeypatch, tmp_path, [GRAVE], sequence)
    spent = [x for x in e.events if x.event_type == "RESOURCE_SPENT" and x.source_definition_id == GRAVE]
    assert len(spent) == 3, [x.payload for x in spent]  # first heal, bare notification, notifying heal
    row = next(r for r in e.typed_reaction_rows[OWNER] if r["feature_id"] == GRAVE)
    expected = max(0, 20 - 9 - row["numbers"]["key_mod"])
    for source in ("test:regeneration", "test:regeneration2"):
        gain = next(x for x in reversed(e.events) if x.event_type == "HEALING_APPLIED" and x.source_definition_id == source)
        assert gain.payload["offered"] == expected, (source, gain.payload)


def test_erode_temp_hp_decision_names_the_offer(monkeypatch, tmp_path):
    """F5: the offered Temporary-HP decision states the creature, the amount, the Proficiency
    Bonus reduction and the resulting amount."""
    from tests.test_r9i_karma_persistence import act
    combat, table, mid = fixture(tmp_path, [ERODE], ask=True, named=True)
    def offer(e):
        e._grant_temp_hp(e.state.actors[FOE], 20, "test:regeneration", FOE)
    on_hold(monkeypatch, offer)
    cid = next(c.candidate_id for c in combat._load_session(mid).engine.legal_candidates() if c.source_definition_id == HOLD)
    paused = act(table, mid, cid)
    assert paused["status"] == "REACTION_REQUIRED", paused
    prompt = paused["reaction"]
    prof = combat._load_session(mid).engine.state.actors[OWNER].proficiency_bonus
    assert "Mara" in prompt["trigger"]
    summary = prompt["summary"]
    assert "Mara" in summary and "Temporary Hit Points" in summary
    assert f"20 becomes {20 - prof}" in summary and "reduce" in summary
    assert "Mara is about to gain 20 Temporary Hit Points" in summary
    answer = {**prompt["context"], "selection": "DECLINE"}
    assert act(table, mid, cid, [answer])["status"] == "COMMITTED"


# ------------------------------------------------------------------------------------
# H203FIX1F14 (review H203FIX1F13R). Grave Tax: "If this reduces the healing or
# Temporary HP to 0, choose one: you regain CP equal to your Proficiency Bonus, not
# exceeding your maximum CP; one Death servant you control regains HP equal to the
# prevented amount; the target gains a Grave Mark until the end of your next turn;
# the target cannot regain HP until the start of its next turn."
# The reward is a player-owned decision (checklist 9), automated from typed data.


def test_grave_tax_reward_is_typed_and_not_a_deferred_gm_rider():
    """F13 finding 3: the four rewards are one typed choice effect, not deferred
    effects plus a "The GM chooses" rider."""
    record = json.loads(TYPED_AUTHORITY.read_text())["mechanics"][GRAVE]
    assert any(e.get("type") == "grave_tax_reward" and not e.get("deferred") for e in record["effects"])
    assert not any(e.get("deferred") for e in record["effects"])
    assert not any("GM chooses" in rider or "No automatic" in rider for rider in record["riders"])
    assert any("choose one" in rider for rider in record["riders"])


def test_gain_classification_keeps_a_mixed_unread_trigger():
    """Optional F13 note: the mixed-alternative guard covered a reviewed reading.
    tianxia.talent.pressure_points.reversing_pulse has no reviewed reading, so the
    phrase classifier itself must keep both printed events."""
    from combat.reaction_triggers import readings_for

    records = json.loads(TYPED_AUTHORITY.read_text())["mechanics"]
    mixed = records["tianxia.talent.pressure_points.reversing_pulse"]
    assert readings_for(mixed) is None
    assert {m.kind for m in classify_mechanic_all(mixed)} == {"healed", "temp_hp_gained"}


def run_hold_rewards(monkeypatch, tmp_path, callback, reward=None, **kwargs):
    combat, table, mid = fixture(tmp_path, [GRAVE], ask=False, **kwargs)
    on_hold(monkeypatch, callback)
    choices = {"reaction:typed." + GRAVE: "first"}
    if reward is not None:
        choices["choice:needle.grave_tax_reward"] = reward
    settle(table, mid, next(c.candidate_id for c in combat._load_session(mid).engine.legal_candidates()
                            if c.source_definition_id == HOLD), choices=choices)
    return reload(tmp_path, mid)


@pytest.mark.parametrize("reward", ["cp", "grave_mark", "no_hp_regain"])
def test_grave_tax_zeroed_gain_applies_the_chosen_printed_reward(monkeypatch, tmp_path, reward):
    """F13 finding 3, service level: a reduction that leaves nothing to gain asks the
    four printed rewards and the chosen one survives the table commit and a cold reload."""
    from combat.typed_executor import mark_condition_id

    def grant(e):
        e.state.actors[FOE].current_hp = 10
        script(e, [8, 8, 8])  # 24 + key mod: the whole 20-point gain is prevented
        e._heal(e.state.actors[FOE], 20, "test:regeneration", FOE, notify_healed=True)
    e = run_hold_rewards(monkeypatch, tmp_path, grant, reward)
    owner, foe = e.state.actors[OWNER], e.state.actors[FOE]
    pb = owner.proficiency_bonus
    gain = next(x for x in e.events if x.event_type == "HEALING_APPLIED" and x.source_definition_id == "test:regeneration")
    assert gain.payload["offered"] == 0
    if reward == "cp":
        gained = [x.payload for x in e.events if x.event_type == "RESOURCE_GAINED" and x.source_definition_id == GRAVE]
        assert [row["gained"] for row in gained] == [pb]
    elif reward == "grave_mark":
        assert any(c.condition_id == mark_condition_id("Grave Mark", OWNER)
                   and c.expires_on == "END_OF_MARKER_NEXT_TURN" for c in foe.conditions.values())
    else:
        row = next(m for m in foe.modifiers.values() if m.target_field == "healing_reduction")
        assert row.value == "none" and row.expires_on == "START_OF_SELF_NEXT_TURN"


def test_grave_tax_reward_heals_the_chosen_death_servant_for_the_prevented_amount(monkeypatch, tmp_path):
    """F13 finding 3: the second printed reward names one Death servant, who regains
    HP equal to the prevented amount (here the whole 20-point gain)."""
    from combat import summons

    def grant(e):
        servant = next(s for s in summons.owned_by(e, OWNER, "death") if s.active)
        e._commit_damage(servant, 10, "SLASHING", "test:chip", OWNER,
                         getattr(e, "_active_intent", None), reaction_depth=0)
        e.state.actors[FOE].current_hp = 10
        script(e, [8, 8, 8])
        e._heal(e.state.actors[FOE], 20, "test:regeneration", FOE, notify_healed=True)
    e = run_hold_rewards(monkeypatch, tmp_path, grant, "servant")
    heal = next(x for x in e.events if x.event_type == "HEALING_APPLIED" and x.source_definition_id == GRAVE)
    servant = next(s for s in summons.owned_by(e, OWNER, "death") if s.active)
    assert heal.target_ids == (servant.entity_id,)
    assert heal.payload["offered"] == 20
    assert heal.payload["before"] == servant.maximum_hp - 10
    assert servant.current_hp == servant.maximum_hp


@pytest.mark.parametrize("restriction,expected", [("none", 0), ("half", 10), ("minus:4", 16)])
def test_grave_tax_servant_reward_obeys_the_servants_healing_reductions(monkeypatch, tmp_path, restriction, expected):
    """H203FIX1F18RSC (blocking): the servant reward is a heal, so it obeys the servant's
    "cannot regain HP" / halved / minus healing reductions, not just the maximum HP. Without
    the shared healing path the servant regains the full 20 prevented HP."""
    from combat import summons

    def grant(e):
        servant = next(s for s in summons.owned_by(e, OWNER, "death") if s.active)
        e._commit_damage(servant, 20, "SLASHING", "test:chip", OWNER,
                         getattr(e, "_active_intent", None), reaction_depth=0)
        e._add_modifier(servant, "test:healing_restriction", "healing_reduction", "ADD", restriction, "SELF",
                        expires_on="UNTIL_REMOVED", source_actor_id=OWNER)
        e.state.actors[FOE].current_hp = 10
        script(e, [8, 8, 8])
        e._heal(e.state.actors[FOE], 20, "test:regeneration", FOE, notify_healed=True)
    e = run_hold_rewards(monkeypatch, tmp_path, grant, "servant")
    servant = next(s for s in summons.owned_by(e, OWNER, "death") if s.active)
    assert servant.current_hp == servant.maximum_hp - 20 + expected


def test_grave_tax_reward_prompt_names_the_creature_ability_and_prevented_amount(monkeypatch, tmp_path):
    """F13 optional note: the Ask-me reward prompt is player-facing and says what
    happened, to whom, from which ability, and how much was prevented."""
    from tests.test_r9i_karma_persistence import act
    combat, table, mid = fixture(tmp_path, [GRAVE], ask=True, named=True)
    def grant(e):
        _definition(e, "action:test.grave_ward", "Grave Ward", owner=FOE)
        e.state.actors[FOE].current_hp = 10
        script(e, [8, 8, 8])
        e._heal(e.state.actors[FOE], 20, "action:test.grave_ward", FOE, notify_healed=True)
    on_hold(monkeypatch, grant)
    cid = next(c.candidate_id for c in combat._load_session(mid).engine.legal_candidates() if c.source_definition_id == HOLD)
    paused = act(table, mid, cid)
    assert paused["status"] == "REACTION_REQUIRED"
    answer = {**paused["reaction"]["context"], "selection": "USE"}
    paused = act(table, mid, cid, [answer])
    assert paused["status"] == "REACTION_REQUIRED", paused  # the reward question, after the reduction
    prompt = paused["reaction"]
    text = str(prompt)
    assert "Grave Tax" in text and "Mara" in text and "Grave Ward" in text
    assert "prevented 20" in text and "20" in text
    assert "test:" not in text  # no internal source id in player-facing wording
    assert {row["id"] for row in prompt["choice"]["options"]} >= {"cp", "grave_mark", "no_hp_regain"}


# ------------------------------------------------------------------------------------
# H203FIX1F15R blocking finding. Printed (Erode Technique rider): "prevent one cost
# reduction from reducing a cost below its listed value." The engine now carries a
# temporary cost reduction as an ordinary modifier (combat/cost_reductions.py) that the
# normal cost quote reads, so the option can occur in play and does what it says.

STAMINA = "resource:core.stamina"


def _thrifty_formula(e, owner=FOE):
    """A real typed action that grants one ordinary temporary cost reduction."""
    from types import SimpleNamespace
    from combat import typed_executor as te
    from combat.gate2_runtime_models import Position

    source = _definition(e, "action:test.thrifty_formula", "Thrifty Formula", owner=owner,
                         typed={"effects": [{"type": "cost_reduction", "applies_to": "self",
                                             "resource": STAMINA, "amount": 2,
                                             "duration": "until_start_of_next_turn"}]})
    actor = e.state.actors[owner]
    te.resolve_typed(e, actor, None, e.action_catalog[source],
                     SimpleNamespace(destination=Position(x=6, y=6), target_ids=(), option_ids=()),
                     e._active_intent)
    return source


def test_thrifty_formula_is_an_ordinary_benefit_the_quote_reads(monkeypatch, tmp_path):
    """The producer half: a typed ``cost_reduction`` row is a temporary modifier, and the
    ordinary cost quote takes it off (never below zero)."""
    def grant(e):
        _definition(e, "test:formula", "Test Formula", owner=FOE)
        _thrifty_formula(e)
        foe = e.state.actors[FOE]
        assert [(m.target_field, m.value) for m in foe.modifiers.values()
                if m.target_field.startswith("cost_reduction:")] == [("cost_reduction:" + STAMINA, 2)]
        assert e.effective_costs(foe, "test:formula", ((STAMINA, 3),)) == ((STAMINA, 1),)
        assert e.effective_costs(foe, "test:formula", ((STAMINA, 1),)) == ((STAMINA, 0),)
    run_hold(monkeypatch, tmp_path, [], grant)


@pytest.mark.parametrize("use", [False, True])
def test_erode_prevents_a_temporary_cost_reduction(monkeypatch, tmp_path, use):
    """The blocking option, through the table: FOE's Thrifty Formula makes a 3-Stamina
    technique cost 1. Erode is offered "prevent one cost reduction from reducing a cost
    below its listed value"; Use parks the reduction (the technique costs its listed 3
    again) and Decline leaves it (1). The parked benefit survives the commit and reload."""
    from tests.test_r9i_karma_persistence import act

    combat, table, mid = fixture(tmp_path, [ERODE], ask=True, named=True)
    def offer(e):
        _definition(e, "test:formula", "Test Formula", owner=FOE)
        _thrifty_formula(e)
    on_hold(monkeypatch, offer)
    cid = next(c.candidate_id for c in combat._load_session(mid).engine.legal_candidates()
               if c.source_definition_id == HOLD)
    paused = act(table, mid, cid)
    assert paused["status"] == "REACTION_REQUIRED", paused
    prompt = paused["reaction"]
    assert "Mara" in prompt["summary"]                      # the creature whose cost was reduced
    assert "cost reduction (2 points off Stamina) from Thrifty Formula" in prompt["summary"]
    assert "prevent that cost reduction from reducing a cost below its listed value" in prompt["summary"]
    assert "start of Wren's next turn" in prompt["summary"]  # how long Use lasts
    result = act(table, mid, cid, [{**prompt["context"], "selection": "USE" if use else "DECLINE"}])
    assert result["status"] == "COMMITTED", result
    e = reload(tmp_path, mid)
    foe = e.state.actors[FOE]
    assert e.effective_costs(foe, "test:formula", ((STAMINA, 3),)) == ((STAMINA, 3 if use else 1),)
    assert [m.value for m in foe.modifiers.values() if m.target_field == "cost_reduction:" + STAMINA] == \
        ([] if use else [2])
    parked = [c for c in foe.conditions.values() if c.condition_id == "condition:typed.benefit_suppressed"
              and c.source_definition_id == ERODE]
    assert bool(parked) is use
    if use:
        assert "cost reduction is prevented" in parked[0].data["label"]
    assert len([x for x in e.events if x.event_type == "RESOURCE_SPENT"
                and x.source_definition_id == ERODE]) == int(use)


def test_live_cost_reduction_composes_with_a_supplied_discount_and_respects_the_floor(monkeypatch):
    """H203FIX1F17 (review F16R blocking finding): a caller that supplies its own discounted
    proposal must not lose the payer's live temporary cost reduction. The reduction composes
    with that proposal, a separate discount provider still applies when no proposal is supplied,
    and technique_cost_floor prices the composed result (it can only raise it)."""
    from tests.test_auto_tabik import ME, _engine
    from tests.test_lock_choices import install

    engine, _ = _engine([])
    payer = engine.state.actors[ME]
    engine._add_modifier(payer, "test:thrifty_formula", "cost_reduction:" + STAMINA, "ADD", 2, "SELF",
                         expires_on="START_OF_SOURCE_NEXT_TURN", source_actor_id=ME)
    listed = ((STAMINA, 5),)
    # A separate discount provider hands the caller a 5 -> 3 proposal; the live
    # 2-point reduction still comes off it.
    assert engine.effective_costs(payer, "test:formula", listed, reduced_costs=((STAMINA, 3),)) == ((STAMINA, 1),)
    # A floor priced against the composed proposal lifts it: the printed minimum wins.
    install(monkeypatch, "technique_cost_floor",
            lambda engine, actor, source, printed, current: {STAMINA: 2})
    assert engine.effective_costs(payer, "test:formula", listed, reduced_costs=((STAMINA, 3),)) == ((STAMINA, 2),)
    # The sealed discount hook is still asked only without a supplied proposal, and there
    # both it and the ordinary reduction apply: 5 - 2 (reduction) - 1 (provider) = 2.
    install(monkeypatch, "technique_cost_discount", lambda *args: {STAMINA: 1})
    install(monkeypatch, "technique_cost_floor", lambda *args: None)
    assert engine.effective_costs(payer, "test:formula", listed) == ((STAMINA, 2),)
    # Nothing goes below zero.
    assert engine.effective_costs(payer, "test:formula", listed, reduced_costs=((STAMINA, 1),)) == ((STAMINA, 0),)
