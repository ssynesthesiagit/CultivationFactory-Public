"""Scoundrel talents the table used to hand to the GM (AUTO11, round 24 lane, 2026-10-04; review fixes AUTO11f1).

Table/service level: each test plays the printed button in a real fight and reads what the engine did -- the cover an
attack resolves against, the condition that landed, the check that was rolled, the Martial Focus that was spent and the
object that changed hands. The questions these talents ask are answered the way the real controller answers them: with
option ids inside the bounds of the choice the engine published (``tests/auto11_service_support.py`` drives the same
questions through TabletopService).

  Bob and Weave        "You gain Half Cover while you remain adjacent to that anchor" (combat/ext/scoundrel_riders.py)
  Quick Thievery       "Expend Martial Focus to use Dirty Trick or Steal as a Bonus Action ... only once per turn"
  Impossible Fastening "expend Martial Focus to extend it to 1 minute" (the general condition_state expiry seam)
  Master Thief         "expend Martial Focus to ignore Disadvantage caused by an object being ... held in two hands"
  Filthy Distraction   "Disadvantage on Wisdom (Perception) checks ... Its Passive Perception is reduced by 5"
  Steal / Steal Equipment  "Choose one accessible object ... take it ... cause it to fall ... plant one Tiny object"
"""

from pathlib import Path

from combat import directional_cover, stealth
from combat.ext import effect_durations, scoundrel_riders
from combat.ext.eye_common import passive_perception
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN, BAI
from combat.gate2_runtime_models import ActionIntent, Position, ReactionDecision
from combat.gate4_engine import Gate4ControllerEngine
from tests.auto11_service_support import offered
from tests.test_carry import KIT
from tests.test_zones import SHEET

ROOT = Path(__file__).resolve().parents[1]
ME = "actor:factory.scoundrel"
FOE = "actor:factory.foe"  # a second compiled fighter, holding a Two-Handed weapon
ALLY = BAI  # a second fighter on the Scoundrel's side, for Bob and Weave's anchor
FOCUS = scoundrel_riders.FOCUS
BASE = ["TAL_SCOUNDREL_DIRTY_TRICK", "TAL_SCOUNDREL_STEAL"]
# A Two-Handed weapon the compiler will build an attack for, so Steal's printed "held in two hands" disadvantage
# (and Master Thief's waiver of it) can actually be reached in a test.
GREATSWORD = {"items": [{"item_id": "tianxia.mortal.weapon.qiang", "name": "Qiang (Spear)", "quantity": 1}]}


def _sheet(talents: list[str], kit: dict | None = None) -> dict:
    stats = {**SHEET["ability_scores_and_statistics"],
             "abilities": [{"ability": a, "score": 16, "modifier": 3} for a in ("STR", "DEX", "CON", "INT", "WIS", "CHA")]}
    return {**SHEET, "identity": {**SHEET["identity"], "cultivation_level": 12, "key_ability": "DEX"},
            "ability_scores_and_statistics": stats, "equipment": [{"starting_kit": kit or KIT}],
            "spheres_and_talents": {"sphere_record_ids": ["tianxia.sphere.scoundrel"],
                                    "automatic_sphere_component_record_ids": ["TAL_SCOUNDREL_SCOUNDREL_TRAINING"],
                                    "learned_talent_record_ids": list(talents)}}


def _fight(talents: list[str], *, foe_at=(4, 6), ally_at=(3, 7), ally=True, seed="AUTO11",
           foe_kit: dict | None = None, kit: dict | None = None, foe_talents: list[str] | None = None
           ) -> Gate4ControllerEngine:
    ids = [ME, FOE] if not ally else [ME, ALLY, FOE]
    team = {ME: "team:a", FOE: "team:b", **({ALLY: "team:a"} if ally else {})}
    where = {ME: {"x": 3, "y": 6}, FOE: {"x": foe_at[0], "y": foe_at[1]},
             **({ALLY: {"x": ally_at[0], "y": ally_at[1]}} if ally else {})}
    bundles = (compile_character(_sheet(talents, kit), actor_id=ME),
               compile_character(_sheet(list(foe_talents or ()), kit=foe_kit or GREATSWORD), actor_id=FOE))
    engine = Gate4ControllerEngine(ROOT, match_seed=seed, typed_bundles=bundles,
                                   roster_setup={"primary_actor_ids": ids, "team_by_actor": team, "starting_positions": where})
    _my_turn(engine)
    return engine


def _my_turn(engine, actor_id=ME) -> None:
    engine.state.current_slot_index = engine.state.initiative_order.index(actor_id)
    engine.state.current_actor_id = actor_id
    engine._system_start_turn()


def _offered(engine, name, *, actor=ME):
    return any(c.actor_id == actor and c.display_name.split(" at ")[0] == name for c in engine.legal_candidates())


class _Table:
    """Answers the questions a fight raises the way the controller does, and remembers every request.

    An extension choice (a menu with real options) must be answered with option ids inside its own bounds; an
    ordinary reaction window keeps the plain Use/Pass answer. Answers that are not legal for the choice the engine
    published are a test failure, never silently ignored.
    """

    def __init__(self, answer=None, engine=None):
        self.requests: list[dict] = []
        self.engine = engine
        self._answer = answer

    def __call__(self, request):
        self.requests.append(request)
        if self.engine is not None:
            request["events_at_ask"] = len(self.engine.events)  # for ordering: this question came before the roll
        choice = request.get("extension_choice") or {}
        legal = tuple(choice.get("option_ids") or ())
        picked = self._answer(request) if callable(self._answer) else self._answer
        if not legal:
            return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                    reaction_source_id=request["reaction_source_id"], selection="USE",
                                    option_ids=tuple(picked or ())), None
        if picked is not None:
            # A fighter names the object it means; the table may spell that name with the object's own identity
            # when two fighters carry the same thing (tests.auto11_service_support.offered).
            picked = tuple(offered(legal, want) for want in picked)
        if picked is None and choice.get("allow_decline"):
            return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                    reaction_source_id=request["reaction_source_id"], selection="DECLINE"), None
        chosen = tuple(picked or (choice.get("preferred_option_ids") or legal)[:int(choice.get("minimum_selections") or 1)])
        assert set(chosen) <= set(legal), f"{chosen} is not one of the options the table offered: {legal}"
        return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                reaction_source_id=request["reaction_source_id"], selection="USE",
                                option_ids=chosen), None

    def asked(self, suffix):
        return [request for request in self.requests if str(request["reaction_source_id"]).endswith(suffix)]

    def source(self, suffix):
        return [request["reaction_source_id"] for request in self.asked(suffix)]


def _do(engine, name, *, actor=ME, target=None, answers=None, table=None):
    """Play the printed button. ``answers`` is a callable taking the request and returning option ids (or None)."""
    table = table if table is not None else (answers if isinstance(answers, _Table) else _Table(answers))
    if answers is not None or table is not None:
        table.engine = engine
        engine.set_reaction_provider(table)
    candidate = next(c for c in engine.legal_candidates()
                     if c.actor_id == actor and c.display_name.split(" at ")[0] == name
                     and (target is None or not c.target_ids or target in c.target_ids))
    engine.execute_intent(ActionIntent(intent_id=f"{name}{engine.state.event_sequence}", decision_id=candidate.decision_id,
                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                       actor_id=actor, target_ids=candidate.target_ids, destination=candidate.destination))
    return table


def _instance(engine, creature_id, condition_id):
    creature = engine.state.actors[creature_id]
    rows = {key: row for key, row in creature.conditions.items() if row.condition_id == condition_id}
    assert len(rows) == 1, f"expected one {condition_id} on {creature_id}, found {sorted(rows)}"
    return next(iter(rows.values()))


def _instance_exists(engine, creature_id, condition_id) -> bool:
    return any(row.condition_id == condition_id for row in engine.state.actors[creature_id].conditions.values())


def _cover_against(engine, attacker_id, target_id, *, ranged=False):
    """The cover one attack against that creature resolves with: the same reader ATTACK_ROLLED's cover_bonus uses."""
    return directional_cover.cover_bonus(engine, engine.state.actors[attacker_id], engine.state.actors[target_id],
                                         ranged=ranged, base=0)


def _scoundrel_checks(engine, actor_id=ME):
    return [event for event in engine.events if event.event_type == "CHECK_ROLLED" and event.actor_id == actor_id
            and (event.payload or {}).get("skill") == "Sleight of Hand"]


# ------------------------------------------------------------------------- Bob and Weave: Half Cover while the anchor is beside you
def test_bob_and_weave_gives_half_cover_while_the_chosen_ally_stays_beside_you():
    engine = _fight([*BASE, "TAL_SCOUNDREL_BOB_AND_WEAVE"])
    me, ally = engine.state.actors[ME], engine.state.actors[ALLY]
    assert _cover_against(engine, FOE, ME) == 0  # nothing is covering it yet
    table = _Table(lambda request: (ALLY,) if request["reaction_source_id"].endswith("bob_and_weave") else None)
    _do(engine, "BOB AND WEAVE", table=table)
    filed = _instance(engine, ME, scoundrel_riders.ANCHOR)
    assert filed.data["anchor"] == ALLY  # the adjacent ally was asked for and filed
    assert filed.expires_on == "START_OF_SELF_NEXT_TURN"  # "Until the start of your next turn"
    assert _cover_against(engine, FOE, ME) == 2  # Half Cover: +2 AC against a melee attack ...
    assert _cover_against(engine, FOE, ME, ranged=True) == 2  # ... and against a ranged one
    assert ally.conditions == {}  # "The chosen ally spends no action and gains no benefit from this talent"
    me.position = Position(x=me.position.x + 30, y=me.position.y)  # no longer adjacent to the anchor
    assert _cover_against(engine, FOE, ME) == 0  # "The benefit ends early if you are no longer adjacent"
    me.position = Position(x=3, y=6)  # back beside it: the printed gain is a live "while you remain adjacent"
    assert _cover_against(engine, FOE, ME) == 2


def test_bob_and_weave_asks_the_printed_questions_and_files_nothing_when_the_ally_refuses_or_cannot_cover():
    engine = _fight([*BASE, "TAL_SCOUNDREL_BOB_AND_WEAVE"])
    ally = engine.state.actors[ALLY]
    refused = _Table(lambda request: ("refuse",) if request["reaction_source_id"].endswith("bob_and_weave_willing") else None)
    _do(engine, "BOB AND WEAVE", table=refused)
    assert not _instance_exists(engine, ME, scoundrel_riders.ANCHOR), "a willing ally is required"
    assert refused.source("bob_and_weave_willing"), "the ally was asked whether it agrees"
    assert not _instance_exists(engine, ALLY, scoundrel_riders.ANCHOR), "the anchor gains nothing"

    engine = _fight([*BASE, "TAL_SCOUNDREL_BOB_AND_WEAVE"], seed="AUTO11b")
    cannot = _Table(lambda request: ("no",) if request["reaction_source_id"].endswith("bob_and_weave_covers") else None)
    _do(engine, "BOB AND WEAVE", table=cannot)
    assert cannot.source("bob_and_weave_covers"), "\"must plausibly cover at least half your body\" was asked"
    assert not _instance_exists(engine, ME, scoundrel_riders.ANCHOR), "an ally that cannot cover you is no anchor"
    assert _cover_against(engine, FOE, ME) == 0


def test_bob_and_weave_stops_covering_once_the_anchor_can_no_longer_stand_in_it():
    engine = _fight([*BASE, "TAL_SCOUNDREL_BOB_AND_WEAVE"])
    _do(engine, "BOB AND WEAVE",
        table=_Table(lambda request: (ALLY,) if request["reaction_source_id"].endswith("bob_and_weave") else None))
    assert _cover_against(engine, FOE, ME) == 2
    engine.state.actors[ALLY].active = False  # "the anchor is destroyed or removed"
    assert _cover_against(engine, FOE, ME) == 0
    engine.state.actors[ALLY].active = True
    assert _cover_against(engine, FOE, ME) == 2, "the printed gain is a live 'while it can still stand in it'"
    engine._apply_condition(engine.state.actors[ALLY], "condition:typed.incapacitated", "test:down",
                            engine.state.actors[ME].entity_id, expires_on="UNTIL_REMOVED")
    assert _cover_against(engine, FOE, ME) == 0, \
        "\"it can no longer plausibly cover at least half your body\": an Incapacitated ally cannot"


def test_bob_and_weave_without_an_adjacent_ally_leaves_the_creature_uncovered():
    engine = _fight([*BASE, "TAL_SCOUNDREL_BOB_AND_WEAVE"], ally=False)
    _do(engine, "BOB AND WEAVE")
    assert [row for row in engine.state.actors[ME].conditions.values() if row.condition_id == scoundrel_riders.ANCHOR] == []
    assert _cover_against(engine, FOE, ME) == 0


def test_bob_and_weave_is_inert_for_a_fighter_who_does_not_own_it():
    engine = _fight([*BASE])
    assert not _offered(engine, "BOB AND WEAVE")
    assert _cover_against(engine, FOE, ME) == 0


# ------------------------------------------------------------------------- Quick Thievery: the printed abilities as a Bonus Action
def test_quick_thievery_publishes_a_bonus_action_for_dirty_trick_and_steal_that_costs_martial_focus():
    engine = _fight([*BASE, "TAL_SCOUNDREL_QUICK_THIEVERY"])
    twins = {row.display_name: row for row in engine.action_catalog.values()
             if row.owner_id == ME and (row.parameters or {}).get("quick_thievery")}
    assert set(twins) == {"Dirty Trick (Quick Thievery: Bonus Action)", "Steal (Quick Thievery: Bonus Action)"}
    for twin in twins.values():
        assert twin.economy.value == "BONUS_ACTION" and twin.costs == ((FOCUS, 1),)
        assert twin.target_kind == "HOSTILE_ENTITY"  # the printed ability's own target
        assert twin.range_ft == 5  # Dirty Trick and Steal both print "Range: Natural reach"
    me = engine.state.actors[ME]
    me.resources[FOCUS] = 0
    assert not _offered(engine, "Dirty Trick (Quick Thievery: Bonus Action)")  # nothing to spend
    me.resources[FOCUS] = 1
    _my_turn(engine)
    assert _offered(engine, "Dirty Trick (Quick Thievery: Bonus Action)")


def test_quick_thievery_runs_the_chosen_dirty_trick_result_and_only_once_a_turn():
    sheet = [*BASE, "TAL_SCOUNDREL_QUICK_THIEVERY"]
    asked = []
    engine = None
    for attempt in range(12):  # a Scoundrel Check can fail; try a few fights until it succeeds
        engine = _fight(sheet, seed=f"QT{attempt}")
        me = engine.state.actors[ME]
        table = _Table(lambda request: (asked.append(request["reaction_source_id"]) or ("Eyes Spoiled",))
                       if request["reaction_source_id"].endswith("quick_thievery") else None)
        _do(engine, "Dirty Trick (Quick Thievery: Bonus Action)", target=FOE, table=table)
        if _instance_exists(engine, FOE, "condition:typed.blinded"):
            break
    assert asked == ["choice:scoundrel.quick_thievery"] * len(asked) and asked, "the ability's own result menu was asked"
    assert _instance_exists(engine, FOE, "condition:typed.blinded"), "the chosen printed result landed"
    assert _scoundrel_checks(engine), "the Bonus Action ran the printed Scoundrel Check"
    assert me.resources[FOCUS] == 0  # "Expend Martial Focus"
    assert not _offered(engine, "Steal (Quick Thievery: Bonus Action)")  # "only once per turn"
    _my_turn(engine)
    assert not _offered(engine, "Steal (Quick Thievery: Bonus Action)")  # the Focus is spent, so still nothing to pay
    me.resources[FOCUS] = 1
    _my_turn(engine)
    assert _offered(engine, "Steal (Quick Thievery: Bonus Action)")  # next turn, next Focus


def test_quick_thievery_runs_steal_itself_rather_than_spending_the_focus_for_nothing():
    """Steal has no "Choose one" menu of its own, so the twin must run the ability itself, not an empty one."""
    sheet = [*BASE, "TAL_SCOUNDREL_QUICK_THIEVERY"]
    for attempt in range(12):  # a Scoundrel Check can fail; try a few fights until one succeeds
        engine = _fight(sheet, seed=f"QTS{attempt}", foe_kit=PACK)
        asked = []
        table = _Table(lambda request: (asked.append(request["reaction_source_id"]) or ("nothing",))
                       if request["reaction_source_id"].endswith("steal_objects") else None)
        _do(engine, "Steal (Quick Thievery: Bonus Action)", target=FOE, table=table)
        if _scoundrel_checks(engine):
            break
    assert asked == ["choice:scoundrel.steal_objects"], "Steal's own object menu was asked through the twin"
    assert _scoundrel_checks(engine), "the printed Scoundrel Check ran: the Bonus Action is not a no-op"
    assert engine.state.actors[ME].resources[FOCUS] == 0, "1 Martial Focus was expended"
    assert _offered(engine, "Steal (Quick Thievery: Bonus Action)") is False, "only once per turn"


def test_quick_thievery_is_inert_for_a_fighter_who_does_not_own_it():
    engine = _fight([*BASE])
    assert not any((row.parameters or {}).get("quick_thievery") for row in engine.action_catalog.values() if row.owner_id == ME)


# ------------------------------------------------------------------------- Impossible Fastening: a hindrance that lasts a minute
def test_impossible_fastening_keeps_a_dirty_trick_hindrance_for_a_minute_when_the_focus_is_spent():
    engine = _fight([*BASE, "TAL_SCOUNDREL_IMPOSSIBLE_FASTENING"])
    me = engine.state.actors[ME]
    _do(engine, "DIRTY TRICK: Eyes Spoiled", target=FOE,
        table=_Table(lambda request: ("extend",) if request["reaction_source_id"].endswith("impossible_fastening") else None))
    filed = _instance(engine, FOE, "condition:typed.blinded")
    assert effect_durations.parse_round(filed.expires_on) == (engine.state.round_number + scoundrel_riders.ONE_MINUTE,
                                                               engine.state.current_slot_index)
    assert me.resources[FOCUS] == 0


def test_impossible_fastening_is_asked_and_a_declined_answer_keeps_the_printed_duration():
    engine = _fight([*BASE, "TAL_SCOUNDREL_IMPOSSIBLE_FASTENING"])
    me = engine.state.actors[ME]
    table = _Table(lambda request: None)  # the table declines to spend the Focus
    _do(engine, "DIRTY TRICK: Eyes Spoiled", target=FOE, table=table)
    assert table.source("impossible_fastening"), "the question was asked with declining allowed"
    filed = _instance(engine, FOE, "condition:typed.blinded")
    assert filed.expires_on == "START_OF_SOURCE_NEXT_TURN"  # "until the start of your next turn"
    assert me.resources[FOCUS] == 1  # nothing spent


def test_impossible_fastening_without_the_talent_leaves_the_printed_duration_alone():
    engine = _fight([*BASE])
    _do(engine, "DIRTY TRICK: Eyes Spoiled", target=FOE)
    assert _instance(engine, FOE, "condition:typed.blinded").expires_on == "START_OF_SOURCE_NEXT_TURN"
    assert engine.state.actors[ME].resources[FOCUS] == 1


def test_the_target_or_an_adjacent_creature_can_undo_the_fastening_with_the_utilize_action():
    # "The target or an adjacent creature can take the Utilize action to end the hindrance early": the marked creature is an
    # enemy of the one undoing it, so the Action must be offered to either side.
    for helper in (ME, FOE):
        for attempt in range(12):  # a Scoundrel Check can fail; try a few fights until it succeeds
            engine = _fight([*BASE, "TAL_SCOUNDREL_IMPOSSIBLE_FASTENING"], seed=f"FAST{helper[-1]}{attempt}")
            _do(engine, "DIRTY TRICK: Eyes Spoiled", target=FOE,
                table=_Table(lambda request: ("extend",) if request["reaction_source_id"].endswith("impossible_fastening") else None))
            if _instance_exists(engine, FOE, scoundrel_riders.FASTENING_MARK):
                break
        _my_turn(engine, helper)
        assert _offered(engine, "Undo the fastening (hindrance from a Dirty Trick)", actor=helper), helper
        _do(engine, "Undo the fastening (hindrance from a Dirty Trick)", actor=helper, target=FOE)
        assert not [row for row in engine.state.actors[FOE].conditions.values()
                    if row.condition_id == "condition:typed.blinded"], "the hindrance the marker names ended"


def test_undoing_the_fastening_ends_only_the_hindrance_it_named():
    engine = _fight([*BASE, "TAL_SCOUNDREL_IMPOSSIBLE_FASTENING"])
    _do(engine, "DIRTY TRICK: Eyes Spoiled", target=FOE,
        table=_Table(lambda request: ("extend",) if request["reaction_source_id"].endswith("impossible_fastening") else None))
    engine._apply_condition(engine.state.actors[FOE], "condition:typed.blinded", "test:other", engine.state.actors[ME].entity_id,
                            expires_on="UNTIL_REMOVED")
    _my_turn(engine)
    _do(engine, "Undo the fastening (hindrance from a Dirty Trick)", target=FOE)
    assert [row for row in engine.state.actors[FOE].conditions.values()
            if row.condition_id == "condition:typed.blinded"], "only the instance the marker names ended"


def test_no_creature_is_offered_the_undo_when_the_fastening_was_not_extended():
    engine = _fight([*BASE, "TAL_SCOUNDREL_IMPOSSIBLE_FASTENING"])
    _do(engine, "DIRTY TRICK: Eyes Spoiled", target=FOE, table=_Table(lambda request: None))
    assert not _offered(engine, "Undo the fastening (hindrance from a Dirty Trick)")
    assert [row for row in engine.state.actors[FOE].conditions.values()
            if row.condition_id == scoundrel_riders.FASTENING_MARK] == []


def test_a_later_condition_on_the_same_creature_earns_no_undo_it_was_never_extended_for():
    engine = _fight([*BASE, "TAL_SCOUNDREL_IMPOSSIBLE_FASTENING"])
    _do(engine, "DIRTY TRICK: Eyes Spoiled", target=FOE,
        table=_Table(lambda request: ("extend",) if request["reaction_source_id"].endswith("impossible_fastening") else None))
    assert _instance_exists(engine, FOE, scoundrel_riders.FASTENING_MARK)
    me = engine.state.actors[ME]
    engine._apply_condition(me, "condition:typed.jammed", "test:later", me.entity_id, expires_on="START_OF_SELF_NEXT_TURN")
    marker = _instance(engine, FOE, scoundrel_riders.FASTENING_MARK)
    linked = [str(was) for was in marker.data["linked"]]
    assert len(linked) == 1, "the marker names only the hindrance Impossible Fastening extended"
    assert all(engine.state.actors[FOE].conditions[was].condition_id == "condition:typed.blinded" for was in linked), \
        "no other condition was marked"
    assert not _instance_exists(engine, ME, scoundrel_riders.FASTENING_MARK), \
        "a condition applied later, to anyone, is not a fastening"
    assert scoundrel_riders.EXTENDING not in me.turn_flags, "the pending extension is consumed by the condition it was about"


def test_two_fastenings_in_one_turn_keep_one_undo_naming_both():
    def reply(request):
        source = str(request["reaction_source_id"])
        if source.endswith("quick_thievery"):
            return ("Eyes Spoiled",)
        return ("extend",) if source.endswith("impossible_fastening") else None

    for attempt in range(8):  # both printed checks have to land for there to be two hindrances to fasten
        engine = _fight([*BASE, "TAL_SCOUNDREL_IMPOSSIBLE_FASTENING", "TAL_SCOUNDREL_QUICK_THIEVERY"], seed=f"F{attempt}")
        me = engine.state.actors[ME]
        me.resource_maximums[FOCUS] = 3  # a Bonus Action twin plus the Action, each with its own printed cost
        me.resources[FOCUS] = 3
        _do(engine, "Dirty Trick (Quick Thievery: Bonus Action)", target=FOE, table=_Table(reply))
        _do(engine, "DIRTY TRICK: Ears Ringing", target=FOE, table=_Table(reply))
        markers = [row for row in engine.state.actors[FOE].conditions.values()
                   if row.condition_id == scoundrel_riders.FASTENING_MARK]
        named = {(engine.state.actors[FOE].conditions[iid].condition_id)
                 for iid in (markers[0].data["linked"] if markers else ())}
        if named == {"condition:typed.blinded", "condition:typed.deafened"}:
            break
    # Two hindrances, one turn: both must be undoable and neither may lose its undo link.
    assert len(markers) == 1, "one marker names every fastening it can undo"
    assert named == {"condition:typed.blinded", "condition:typed.deafened"}, named


def test_impossible_fastening_never_extends_prone_or_exploited_opening():
    engine = _fight([*BASE, "TAL_SCOUNDREL_IMPOSSIBLE_FASTENING"])
    _do(engine, "DIRTY TRICK: Low Sweep", target=FOE,
        table=_Table(lambda request: ("extend",) if request["reaction_source_id"].endswith("impossible_fastening") else None))
    prone = _instance(engine, FOE, "condition:typed.prone")
    assert not effect_durations.parse_round(prone.expires_on)  # "Impossible Fastening cannot extend Prone"


# ------------------------------------------------------------------------- Master Thief: ignore the printed Disadvantage
def test_master_thief_ignores_the_two_handed_disadvantage_and_spends_the_focus():
    engine = _fight([*BASE, "TAL_SCOUNDREL_MASTER_THIEF"])  # the foe holds a Two-Handed weapon
    me = engine.state.actors[ME]
    assert scoundrel_riders.owns(engine, me, scoundrel_riders.MASTER)
    table = _Table(lambda request: ("ignore",) if request["reaction_source_id"].endswith("master_thief")
                    else (f"take:{SPEAR_KEY}",) if request["reaction_source_id"].endswith("steal_objects") else None)
    _do(engine, "STEAL", target=FOE, table=table)
    assert _scoundrel_checks(engine), "the Steal check was rolled"
    assert _scoundrel_checks(engine)[-1].payload["actor"]["mode"] == "NORMAL"
    assert me.resources[FOCUS] == 0


def test_the_two_handed_disadvantage_is_rolled_without_master_thief_and_waived_with_it():
    """"Make your check with Disadvantage if the object is ... held in two hands": the object you chose is the one
    that decides, so the two-handed weapon has to be the object named before the check."""
    def play(talents):
        engine = _fight([*BASE, *talents])
        table = _Table(lambda request: ("ignore",) if request["reaction_source_id"].endswith("master_thief")
                       else (f"take:{SPEAR_KEY}",) if request["reaction_source_id"].endswith("steal_objects") else None)
        _do(engine, "STEAL", target=FOE, table=table)
        return engine, table

    plain, asked = play(())
    assert _scoundrel_checks(plain)[-1].payload["actor"]["mode"] == "DISADVANTAGE"
    assert plain.state.actors[ME].resources[FOCUS] == 1
    assert not asked.source("master_thief"), "a fighter without the talent is never asked to waive anything"

    waived, asked = play(("TAL_SCOUNDREL_MASTER_THIEF",))
    assert asked.source("master_thief"), "the talent is asked about the two-handed object that was chosen"
    assert _scoundrel_checks(waived)[-1].payload["actor"]["mode"] == "NORMAL"
    assert waived.state.actors[ME].resources[FOCUS] == 0


def test_master_thief_declining_keeps_the_disadvantage_and_the_focus():
    engine = _fight([*BASE, "TAL_SCOUNDREL_MASTER_THIEF"])
    table = _Table(lambda request: (f"take:{SPEAR_KEY}",) if request["reaction_source_id"].endswith("steal_objects")
                   else None)  # declining the waiver is a legal answer
    _do(engine, "STEAL", target=FOE, table=table)
    assert table.source("master_thief"), "the waiver was asked"
    assert _scoundrel_checks(engine)[-1].payload["actor"]["mode"] == "DISADVANTAGE"
    assert engine.state.actors[ME].resources[FOCUS] == 1


def test_master_thief_is_never_asked_to_waive_a_disadvantage_the_chosen_object_does_not_cause():
    """The Focus may only be spent against an object that is fastened, worn tightly or held in two hands."""
    engine = _fight([*BASE, "TAL_SCOUNDREL_MASTER_THIEF"], kit=GREATSWORD, foe_kit=PACK)
    table = _Table(lambda request: (f"take:{PACK_KEY}",) if request["reaction_source_id"].endswith("steal_objects") else None)
    _do(engine, "STEAL", target=FOE, table=table)
    assert not table.source("master_thief"), "an ordinary pack in a bag is not a difficult object"
    assert engine.state.actors[ME].resources[FOCUS] == 1, "no Focus was spent"
    assert _scoundrel_checks(engine)[-1].payload["actor"]["mode"] == "NORMAL"


def test_master_thief_is_asked_when_the_chosen_object_is_the_two_handed_weapon():
    engine = _fight([*BASE, "TAL_SCOUNDREL_MASTER_THIEF"], foe_kit=GREATSWORD)
    table = _Table(lambda request: ("take:tianxia.mortal.weapon.qiang",) if request["reaction_source_id"].endswith("steal_objects") else None)
    _do(engine, "STEAL", target=FOE, table=table)
    assert table.source("master_thief"), "a two-handed weapon is one of the printed three"
    assert _scoundrel_checks(engine)[-1].payload["actor"]["mode"] == "DISADVANTAGE", "declining keeps it"


# ------------------------------------------------------------------------- Filthy Distraction: a real Perception penalty
def _distracted_fight(seed: str, *, order=None) -> Gate4ControllerEngine:
    """A fight where a Dirty Trick has just succeeded against a creature that could not see the thief.

    ``order`` puts the initiative the way the case needs it (a list of actor ids), because "until the end of your
    next turn" has to hold whichever slot the thief has in the round.
    """
    sheet = [*BASE, "TAL_SCOUNDREL_FILTHY_DISTRACTION"]
    for attempt in range(12):  # a Scoundrel Check can fail; try a few fights until it succeeds
        engine = _fight(sheet, seed=f"{seed}{attempt}")
        _unaware(engine, FOE)  # the printed trigger is a creature that was unaware of the thief
        _do(engine, "DIRTY TRICK: Eyes Spoiled", target=FOE)
        if not _instance_exists(engine, FOE, scoundrel_riders.FILTHY_CONDITION):
            continue
        if order is not None:
            assert sorted(order) == sorted(engine.state.initiative_order), "the case needs every creature slotted"
            engine.state.initiative_order = list(order)
            engine.state.current_actor_id = ME
            engine.state.current_slot_index = list(order).index(ME)
        return engine
    raise AssertionError("the Dirty Trick check never succeeded on these seeds")


def test_filthy_distraction_leaves_a_real_perception_penalty_instead_of_a_line_for_the_gm():
    plain = _fight([*BASE])
    engine = _distracted_fight("FD")
    filed = _instance(engine, FOE, scoundrel_riders.FILTHY_CONDITION)
    assert filed.data["rule"]["check_mode"] == {"Perception": "DISADVANTAGE"}, \
        "the printed line is a Wisdom (PERCEPTION) check, not every Wisdom check"
    assert effect_durations.parse(filed.expires_on) == ("end", ME, engine.state.actors[ME].turns_started + 1)
    assert passive_perception(engine, engine.state.actors[FOE]) == (
        passive_perception(plain, plain.state.actors[FOE]) - scoundrel_riders.FILTHY_PENALTY)
    assert "DISADVANTAGE" in stealth.search_modes(engine, engine.state.actors[FOE])
    assert "DISADVANTAGE" not in stealth.search_modes(plain, plain.state.actors[FOE])


def test_filthy_distraction_leaves_other_wisdom_checks_alone():
    from combat.typed_executor import check_modes

    distracted = _distracted_fight("FDW").state.actors[FOE]
    assert check_modes(distracted, "WIS", "Perception") == {"DISADVANTAGE"}
    assert check_modes(distracted, "WIS", "Insight") == set(), "Insight is a Wisdom check, but not the printed one"
    assert check_modes(distracted, "WIS", "Survival") == set()


def test_filthy_distraction_uses_the_thiefs_next_turn_end():
    """Both penalties use the thief's clock: Filthy ends at the end, hindrances at the start."""
    engine = _distracted_fight("FDT")
    filthy = _instance(engine, FOE, scoundrel_riders.FILTHY_CONDITION)
    edge, who, turn = effect_durations.parse(filthy.expires_on)
    assert (edge, who, turn) == ("end", ME, int(engine.state.actors[ME].turns_started) + 1), \
        "\"your next turn\": the thief's clock"
    blinded = [row for row in engine.state.actors[FOE].conditions.values()
               if row.condition_id == "condition:typed.blinded" and row.expires_on == "START_OF_SOURCE_NEXT_TURN"]
    assert len(blinded) == 1 and blinded[0].source_actor_id == ME, \
        "\"until the start of your next turn\" is the thief's own turn, and is a different clock"


def test_filthy_distraction_ends_at_the_end_of_the_thiefs_next_turn_whoever_acts_first():
    """"until the end of your next turn": walked through the real initiative, in both initiative orders.

    This used to be asserted by reading the expiry name, which the file itself computes, so it proved nothing
    about when the condition actually leaves the creature.
    """
    for label, order in (("the distracted creature acts first", [FOE, ME, ALLY]),
                         ("the distracted creature acts last", [ME, ALLY, FOE])):
        engine = _distracted_fight("FDE", order=order)
        assert _instance_exists(engine, FOE, scoundrel_riders.FILTHY_CONDITION)
        thief_turn = effect_durations.parse(_instance(engine, FOE, scoundrel_riders.FILTHY_CONDITION).expires_on)[2]
        while _instance_exists(engine, FOE, scoundrel_riders.FILTHY_CONDITION):
            ending = engine.state.current_actor_id
            engine.end_turn(f"FDE-{ending}")
            if not _instance_exists(engine, FOE, scoundrel_riders.FILTHY_CONDITION):
                assert ending == ME, f"{label}: it ended with the wrong creature's turn ({ending})"
                assert engine.state.actors[ME].turns_started == thief_turn
                break
        assert passive_perception(engine, engine.state.actors[FOE]) == \
            passive_perception(_fight([*BASE], seed=order[0]), engine.state.actors[FOE]), \
            f"{label}: the -5 goes when the condition does"


def test_a_fighter_without_filthy_distraction_leaves_no_perception_penalty():
    engine = _fight([*BASE])
    _unaware(engine, FOE)
    _do(engine, "DIRTY TRICK: Eyes Spoiled", target=FOE)
    assert [row for row in engine.state.actors[FOE].conditions.values()
            if row.condition_id == scoundrel_riders.FILTHY_CONDITION] == []


def _unaware(engine, creature_id):
    """Put the creature in the printed state Filthy Distraction names: unable to perceive the thief at all.

    Blinded is an ordinary printed condition the table already applies, so this needs no test-only machinery.
    """
    engine._apply_condition(engine.state.actors[creature_id], "condition:typed.blinded", "test:unaware",
                            engine.state.actors[ME].entity_id, expires_on="UNTIL_REMOVED")


# ------------------------------------------------------------------------- Steal: the printed object comes before the check
PACK = {"items": [{"item_id": "tianxia.mortal.weapon.qiang", "name": "Qiang (Spear)", "quantity": 1},
                  {"item_id": "tianxia.mortal.gear.explorer_s_pack", "name": "Explorer's Pack", "quantity": 1}]}
PACK_KEY = "tianxia.mortal.gear.explorer_s_pack"
SPEAR_KEY = "tianxia.mortal.weapon.qiang"
STEALERS = ["TAL_SCOUNDREL_DIRTY_TRICK", "TAL_SCOUNDREL_STEAL"]
ARMORED = {"items": [*PACK["items"],
                     {"item_id": "tianxia.mortal.armor.lacquered_lamellar", "name": "Lacquered Lamellar", "quantity": 1}]}
ARMOR_KEY = "tianxia.mortal.armor.lacquered_lamellar"
EQUIP = "Steal Equipment (take one worn thing)"
# Seeds whose printed Scoundrel Check succeeds against this opponent, so these tests read one resolution, not a lottery.
STEAL_SEEDS = ("S0", "S1", "S2", "S3", "S4", "S5")


def _with(engine, creature_id, item_key, where):
    return [row for row in engine.state.actors[creature_id].conditions.values()
            if (row.data or {}).get("item_key") == item_key and (row.data or {}).get(where)]


def _stolen(engine, creature_id, item_key):
    """The items a creature no longer has because somebody else took them, or planted, or set them down."""
    return _with(engine, creature_id, item_key, "held_by")


def _in_hand_of(engine, thief_id, item_key):
    """What the thief is now carrying: recorded on the creature it came off, carrying ``held_by`` (the thief)."""
    return [row for row in _stolen(engine, FOE, item_key) if row.data["held_by"] == thief_id]


def _resolve_steal(answer, *, talents=(), kit=None, foe_kit=PACK, seeds=STEAL_SEEDS, success=True, before=None, spot=None,
                   tiny="yes"):
    """Play Steal until the printed check resolves as asked, answering the object menu with ``answer``.

    ``spot`` answers the printed square question that "let it fall" raises; by default the table declines it, which
    leaves the object where it was. ``tiny`` answers the printed "plant one Tiny object" question, which is only
    asked once a planted object has actually been chosen.
    """
    sheet = [*STEALERS, *talents]
    for seed in seeds:  # a Scoundrel Check can fail; try the seeds where it resolves as needed
        engine = _fight(sheet, seed=seed, foe_kit=foe_kit, kit=kit)
        if before is not None:
            before(engine)  # an earlier successful use of the same printed ability, this turn

        def reply(request, answer=answer, spot=spot, tiny=tiny):
            source = str(request["reaction_source_id"])
            if source.endswith("steal_objects"):
                return answer
            if source.endswith("steal_tiny"):
                return (tiny,)
            if source.endswith("steal_spot"):
                legal = tuple(request["extension_choice"]["option_ids"])
                return legal[:1] if spot == "first" else spot
            return None

        table = _Table(reply)
        _do(engine, "STEAL", target=FOE, table=table)
        check = _scoundrel_checks(engine)
        if check and bool(check[-1].payload.get("success")) is bool(success):
            return engine, table, check[-1]
    raise AssertionError(f"the Steal check never resolved with success={success}")


def test_the_object_is_chosen_before_the_check_that_depends_on_it():
    """"Choose one accessible object" is the printed first line, and the difficulty is that object's."""
    engine, table, check = _resolve_steal((f"take:{SPEAR_KEY}",))
    assert table.source("steal_objects") == ["choice:scoundrel.steal_objects"]
    asked_at = table.asked("steal_objects")[0]["events_at_ask"]
    rolled_at = next(index for index, event in enumerate(engine.events) if event is check)
    assert asked_at <= rolled_at, "the object was chosen before the check rolled, not after it"
    prompt = table.asked("steal_objects")[0]["choice_trigger"]
    assert prompt["prompt"].startswith("Steal:") and "to take from" in prompt["prompt"], \
        "the question names the ability and what it asks for"
    assert engine.state.actors[FOE].display_name in prompt["prompt"], "and the creature it lands on"
    assert "check is made against it" in prompt["prompt"], "and says why the object comes first"


def test_a_steal_asks_for_at_most_the_one_object_it_prints():
    engine, table, _check = _resolve_steal((f"take:{PACK_KEY}",))
    request = table.asked("steal_objects")[0]
    spec = request["extension_choice"]
    assert spec["maximum_selections"] == 1, "Steal prints one object; Cleaned Out is the only way to two"
    labels = request["choice_trigger"]["labels"]
    assert all(labels[option] and "tianxia.mortal" not in labels[option] for option in spec["option_ids"]), \
        "options are named for the player, not raw ids"
    assert _stolen(engine, FOE, PACK_KEY), "the pack came out of the target's hands into the thief's"
    assert _stolen(engine, ME, PACK_KEY) == [], "and it is the thief who now has it"


def test_cleaned_out_allows_exactly_two_objects_and_both_change_hands():
    engine, table, _check = _resolve_steal((f"take:{SPEAR_KEY}", f"take:{PACK_KEY}"),
                                            talents=("TAL_SCOUNDREL_CLEANED_OUT",), foe_kit=ARMORED, spot="first")
    spec = table.asked("steal_objects")[0]["extension_choice"]
    assert spec["maximum_selections"] == 2, "\"up to two accessible objects instead of one\""
    assert _stolen(engine, FOE, SPEAR_KEY), "the first printed object went into a free hand"
    fallen = _with(engine, FOE, PACK_KEY, "dropped_at")
    assert fallen, "\"You still need free hands or legal spaces for the objects\": the second went into a square"
    assert table.source("steal_spot"), "and that square was asked for, not invented"
    assert not _with(engine, FOE, ARMOR_KEY, "held_by"), "and no third object was taken"


def test_a_failed_steal_check_takes_nothing_even_with_a_valid_object_chosen():
    cases = (
        ((f"take:{PACK_KEY}",), ()),  # Steal's own one object
        ((f"take:{SPEAR_KEY}", f"plant:{PACK_KEY}"), ("TAL_SCOUNDREL_CLEANED_OUT",)),  # both printed slots
    )
    for answer, talents in cases:
        engine, table, check = _resolve_steal(answer, talents=talents, foe_kit=ARMORED, success=False)
        assert check.payload.get("success") is False, "this case needs a check that failed"
        assert table.asked("steal_objects"), "a legal object was chosen before it rolled"
        assert not _with(engine, FOE, PACK_KEY, "held_by") and not _with(engine, FOE, SPEAR_KEY, "held_by"), \
            "a failed check hands over nothing"
        assert not _with(engine, ME, PACK_KEY, "held_by"), "and plants nothing either"
        assert engine.state.actors[ME].resources[FOCUS] == 1, "no Focus was spent"


def test_steal_never_offers_a_complete_suit_of_worn_armor_to_a_scoundrel_who_cannot_reach_it():
    """\"Master Thief does not make ... a complete suit of worn armor ordinarily accessible.\""""
    plain = _fight(STEALERS, foe_kit=ARMORED)
    table = _Table(lambda request: None)
    _do(plain, "STEAL", target=FOE, table=table)
    offered = table.asked("steal_objects")[0]["choice_trigger"]["labels"]
    assert not any(ARMOR_KEY in option for option in offered), "a suit of armor is not an ordinary accessible object"
    assert any(SPEAR_KEY in option for option in offered), "but what it holds in its hands is"


def test_master_thief_does_not_reach_a_worn_suit_of_armor_either():
    """\"Master Thief does not make ... a complete suit of worn armor ordinarily accessible.\"

    Master Thief spends Martial Focus on Disadvantage and nothing else, so the talent must not widen what Steal
    can reach; only Steal Equipment's own printed list names \"suit of armor\".
    """
    engine = _fight([*STEALERS, "TAL_SCOUNDREL_MASTER_THIEF"], foe_kit=ARMORED)
    table = _Table(lambda request: None)
    _do(engine, "STEAL", target=FOE, table=table)
    offered = table.asked("steal_objects")[0]["choice_trigger"]["labels"]
    assert not any(ARMOR_KEY in option for option in offered), \
        "the printed line is the talent's own limit, so it must not be offered to a thief who owns it"
    assert any(SPEAR_KEY in option for option in offered), "the rest of what it wears is still on offer"


def test_steal_equipment_reaches_a_worn_suit_of_armor_because_that_is_what_it_prints():
    engine, table, check = _steal_equipment((f"take:{ARMOR_KEY}",))
    assert check.payload["actor"]["mode"] == "DISADVANTAGE", "the printed Disadvantage is really rolled"
    assert _stolen(engine, FOE, ARMOR_KEY), "the worn thing came away"
    assert not _stolen(engine, FOE, PACK_KEY), "and only what was chosen"
    assert engine.state.actors[ME].resources[FOCUS] == 0, "1 Martial Focus was expended"


def test_steal_planting_puts_one_of_the_thiefs_own_objects_into_the_targets_hands():
    engine, table, _check = _resolve_steal((f"plant:{PACK_KEY}",))
    assert _stolen(engine, ME, PACK_KEY), "the thief's own pack is in the target's hands"
    assert table.source("steal_tiny"), "\"plant one Tiny object\" is asked, because this table keeps no item sizes"
    log = "\n".join(str(event.payload.get("log") or "") for event in engine.events
                    if event.event_type == "PASSIVE_TRIGGERED")
    assert "plants Explorer's Pack in" in log and "takes Explorer's Pack from" not in log, \
        "the log says the object was planted, not that the thief took it from itself"


def test_a_planted_object_that_is_not_tiny_is_not_planted():
    """"plant one Tiny object in an accessible location on the target": the printed size is enforced, not just stated."""
    engine, table, check = _resolve_steal((f"plant:{PACK_KEY}",), tiny="no")
    assert check.payload.get("success"), "the check still happened; the printed result is what fails"
    assert table.source("steal_tiny"), "the fighter was asked whether the object really is Tiny"
    assert not _stolen(engine, ME, PACK_KEY), "a bigger object is not planted"
    assert any(str(row.get("key")) == PACK_KEY for row in scoundrel_riders.possessions(engine, engine.state.actors[ME])), \
        "and the thief still carries it"


def test_a_stolen_object_keeps_one_record_and_its_own_identity_through_every_handover():
    """"the object" is one object: one record, wherever it is, named the same way whoever holds it.

    A pack taken from the victim and then planted back in the victim's hands is the victim's pack again, so the
    record that followed it away is taken off, the thief's hand is free again, and the victim's load is whole. Two
    records for one object left the pack invisible to the victim, kept a hand busy with an object nobody held, and
    let the object ping-pong between two owners for ever.
    """
    from combat.ext import hand_occupancy

    def every_record(engine, key):
        return [(who, row.data.get("held_by"), row.data.get("dropped_at"))
                for who, creature in engine.state.actors.items()
                for row in creature.conditions.values() if (row.data or {}).get("item_key") == key]

    engine = None
    for seed in ("S0", "S1", "S2", "S3", "S4", "S5"):  # both printed checks have to succeed for this case
        fight = _fight(STEALERS, seed=seed, foe_kit=ARMORED, kit=PACK)
        _do(fight, "STEAL", target=FOE, table=_Table(_take(PACK_KEY)))
        first = _scoundrel_checks(fight)
        if not first or not first[-1].payload.get("success"):
            continue
        # after the theft: one record, filed on the victim, naming the thief and carrying the object's identity
        assert every_record(fight, PACK_KEY) == [(FOE, ME, None)], \
            f"one record per object: {every_record(fight, PACK_KEY)}"
        record = _with(fight, FOE, PACK_KEY, "held_by")[0]
        assert record.data["owner"] == FOE and record.data["item_name"] == "Explorer's Pack", \
            "the record carries the object's own identity for every later reader"
        assert hand_occupancy.free_hands(fight, fight.state.actors[ME]) == (), \
            "and the hand it went into is really occupied"
        _my_turn(fight)
        # the object that came from the victim, named as its own copy now the thief holds two of the same thing
        _do(fight, "STEAL", target=FOE, table=_Table(_plant(PACK_KEY, owner=FOE)))
        second = _scoundrel_checks(fight)
        if second and second[-1].payload.get("success"):
            engine = fight
            break
    assert engine is not None, "no seed where both printed checks succeeded"
    me, victim = engine.state.actors[ME], engine.state.actors[FOE]

    assert every_record(engine, PACK_KEY) in ([], [(FOE, FOE, None)]), \
        f"still one record at most, and none for an object that is home: {every_record(engine, PACK_KEY)}"
    assert hand_occupancy.free_hands(engine, me), "the hand it went into is free again"
    assert any(str(row.get("key")) == PACK_KEY for row in scoundrel_riders.possessions(engine, victim)), \
        "and the object is in the victim's own possession again"
    from combat import carry

    plain = _fight(STEALERS, foe_kit=ARMORED, kit=PACK, seed="ID0")
    assert carry.weight(engine, victim) == carry.weight(plain, plain.state.actors[FOE]), \
        "so the victim's load is whole again too"
    assert carry.weight(engine, me) == carry.weight(plain, plain.state.actors[ME]), \
        "and the thief carries what it started with"


def _take(key, owner=""):
    """"Take its <object> into a free hand". ``owner`` names whose copy, when two fighters carry the same thing."""
    option = f"take:{scoundrel_riders.object_id(owner, key)}" if owner else f"take:{key}"
    return lambda request: (option,) if request["reaction_source_id"].endswith("steal_objects") else None


def _plant(key, tiny="yes", owner=""):
    """Plant one object; ``owner`` names whose copy, when two fighters carry the same thing."""
    option = f"plant:{scoundrel_riders.object_id(owner, key)}" if owner else f"plant:{key}"

    def reply(request):
        source = request["reaction_source_id"]
        if source.endswith("steal_objects"):
            return (option,)
        if source.endswith("steal_tiny"):
            return (tiny,)
        return None
    return reply


def test_a_planted_object_is_named_for_the_creature_it_was_planted_in():
    """"plant one Tiny object in an accessible location on the target": the planted object is that creature's now."""
    engine, _table, _check = _resolve_steal((f"take:{SPEAR_KEY}", f"plant:{PACK_KEY}"),
                                            talents=("TAL_SCOUNDREL_CLEANED_OUT",), foe_kit=ARMORED, kit=PACK)
    victim = engine.state.actors[FOE]
    mine = {(str(row.data.get("item_key")), str(row.data.get("held_by")))
            for who, creature in engine.state.actors.items()
            for row in creature.conditions.values() if (row.data or {}).get("item_key")}
    assert mine == {(SPEAR_KEY, ME), (PACK_KEY, FOE)}, f"one record per object, each naming its holder: {sorted(mine)}"
    planted = next(row for row in scoundrel_riders.possessions(engine, victim) if str(row.get("key")) == PACK_KEY)
    assert str(planted.get("name")) == "Explorer's Pack", \
        "the victim's own possession list still calls it what it is, though its bundle never listed it"
    assert not any(str(row.get("key")) == PACK_KEY for row in scoundrel_riders.possessions(engine, engine.state.actors[ME])), \
        "and the thief no longer has it"


def test_an_object_a_thief_has_taken_can_be_planted_on_its_next_attempt():
    engine, _table, _check = _resolve_steal((f"take:{PACK_KEY}",), foe_kit=PACK, kit=PACK)
    assert _in_hand_of(engine, ME, PACK_KEY), "the thief holds what it took"
    assert any(str(row.get("key")) == PACK_KEY for row in scoundrel_riders.possessions(engine, engine.state.actors[ME])), \
        "a received object is current possession, so it can be used again"
    me = engine.state.actors[ME]
    engine._apply_condition(me, "condition:typed.blinded", "test:x", me.entity_id, expires_on="UNTIL_REMOVED")
    assert any(str(row.get("key")) == PACK_KEY for row in scoundrel_riders.possessions(engine, me)), \
        "an unrelated condition never hides inventory"


def test_a_weapon_that_is_really_gone_is_still_gone_while_the_rest_of_the_inventory_is_not_hidden():
    from combat import carry

    engine = _fight(STEALERS, seed="S1", foe_kit=PACK, kit=PACK)
    me = engine.state.actors[ME]
    weapon = next(item["weapon_action"] for item in carry.carrying_of(engine, ME)["items"] if item.get("weapon_action"))
    engine._apply_condition(me, "condition:typed.disarmed", "test:gone", me.entity_id, expires_on="UNTIL_REMOVED",
                            data={"disables_action": weapon, "item_key": weapon.rsplit(".", 1)[-1],
                                  "held_by": "actor:factory.somebody-else"})
    keys = [str(row.get("key")) for row in scoundrel_riders.possessions(engine, me)]
    assert PACK_KEY in keys, "inventory is filtered by real weapon identities, not by 'has no weapon action'"
    assert weapon.rsplit(".", 1)[-1] not in keys, "the weapon that is really gone is not on offer again"


def test_an_object_taken_into_a_hand_keeps_that_hand_busy():
    """"take the object into a free hand": once it is in the hand, the next object needs a square, not that hand."""
    from combat.ext import hand_occupancy

    engine, _table, _check = _resolve_steal((f"take:{PACK_KEY}",), foe_kit=ARMORED)
    me = engine.state.actors[ME]
    taken = _in_hand_of(engine, ME, PACK_KEY)
    assert taken, "the pack went into a hand"
    assert taken[0].data["hand"] in hand_occupancy.hand_parts(engine, me), "and the hand is named in the record"
    assert hand_occupancy.free_hands(engine, me) == (), "so no hand is free any more"

    engine2 = _fight(STEALERS, seed="S1", foe_kit=ARMORED)
    offered = _Table(lambda request: None)
    offered.engine = engine2
    engine2.set_reaction_provider(offered)
    _do(engine2, "STEAL", target=FOE, answers=offered)
    labels = offered.asked("steal_objects")[0]["choice_trigger"]["labels"]
    assert any(option.startswith("take:") for option in labels), "with both hands free the hand result is on offer"


def test_two_takes_in_one_turn_both_move_the_load():
    from combat import carry

    plain = _fight(STEALERS, foe_kit=ARMORED)
    engine, _table, _check = _resolve_steal((f"take:{SPEAR_KEY}", f"take:{PACK_KEY}"),
                                            talents=("TAL_SCOUNDREL_CLEANED_OUT",), foe_kit=ARMORED)
    assert carry.weight(engine, engine.state.actors[FOE]) < carry.weight(plain, plain.state.actors[FOE])
    assert carry.weight(engine, engine.state.actors[ME]) > carry.weight(plain, plain.state.actors[ME])


def test_with_both_hands_full_the_object_is_set_down_in_a_chosen_square_instead_of_a_hand():
    """"You still need free hands or legal spaces for the objects": a full pair of hands means a legal square."""
    two_hands = {"items": [{"item_id": "tianxia.mortal.weapon.qiang", "name": "Qiang (Spear)", "quantity": 1},
                           {"item_id": "tianxia.mortal.weapon.bi_shou", "name": "Bi Shou (Dagger)", "quantity": 1}]}
    engine = _fight(STEALERS, seed="S0", kit=two_hands, foe_kit=ARMORED)
    from combat.ext import hand_occupancy

    assert hand_occupancy.free_hands(engine, engine.state.actors[ME]) == (), "both hands are full"
    offered = _Table(lambda request: None)
    offered.engine = engine
    engine.set_reaction_provider(offered)
    _do(engine, "STEAL", target=FOE, answers=offered)
    labels = offered.asked("steal_objects")[0]["choice_trigger"]["labels"]
    assert not any(option.startswith("take:") for option in labels), \
        "\"take the object into a free hand\" is not on offer when no hand is free"
    assert any(option.startswith("fall:") for option in labels), "the printed square result is"


def test_with_both_hands_full_the_object_is_set_down_in_the_square_the_table_chose():
    two_hands = {"items": [{"item_id": "tianxia.mortal.weapon.qiang", "name": "Qiang (Spear)", "quantity": 1},
                           {"item_id": "tianxia.mortal.weapon.bi_shou", "name": "Bi Shou (Dagger)", "quantity": 1}]}
    engine, table, _check = _resolve_steal((f"fall:{PACK_KEY}",), kit=two_hands, foe_kit=ARMORED, spot="first")
    assert table.source("steal_spot"), "the square was chosen, not invented"
    assert table.asked("steal_spot")[0]["extension_choice"]["option_ids"], "and it was a real choice of square"
    spot = _with(engine, FOE, PACK_KEY, "dropped_at")
    assert spot and spot[0].data["dropped_at"], "the object is recorded where it landed"
    assert spot[0].condition_id == "condition:typed.dropped_item", \
        "as this table records anything set down: the same Drop record, so it can be picked up again"
    assert not spot[0].data.get("held_by"), "and it is not charged to the thief's load as carried"
    from combat import carry

    plain = _fight(STEALERS, kit=two_hands, foe_kit=ARMORED)
    assert carry.weight(engine, engine.state.actors[FOE]) < carry.weight(plain, plain.state.actors[FOE]), \
        "the victim no longer carries it"
    assert carry.weight(engine, engine.state.actors[ME]) == carry.weight(plain, plain.state.actors[ME]), \
        "and it is on the ground, not in the thief's hands"


def test_with_a_free_hand_the_printed_result_is_the_hand_the_check_asked_for():
    engine, table, _check = _resolve_steal((f"take:{PACK_KEY}",), foe_kit=ARMORED)
    assert not table.source("steal_spot"), "no square question when there is a free hand"
    assert _in_hand_of(engine, ME, PACK_KEY), "\"take the object into a free hand\""


def test_taking_nothing_leaves_the_targets_other_belongings_alone():
    """"Take nothing", and declining, are answers: the check is still made and no object moves.

    This used to answer with an empty selection, which the harness read as "the first option on offer", so it took
    the victim's spear and then asserted the pack was untouched -- the opposite of what it claimed. It also missed
    the table's own default: with nothing chosen the Scoundrel Check fell back to Steal's local disarm rule and
    took the victim's best weapon, so "take nothing" still cost them a weapon.
    """
    for answer, label in ((("nothing",), "take nothing"), (None, "decline the question")):
        engine, table, check = _resolve_steal(answer, foe_kit=ARMORED, kit=PACK)
        assert check.payload.get("success"), f"{label}: the check is still made; it is what the action is"
        assert check.payload["actor"]["mode"] == "NORMAL", f"{label}: no object was named, so no object's difficulty"
        assert table.asked("steal_objects"), f"{label}: the question was really put and answered"
        assert not [row for row in engine.state.actors.values() for row in row.conditions.values()
                    if (row.data or {}).get("item_key")], \
            f"{label}: no object changed hands, including the victim's own default disarm"
        assert not [row for row in engine.state.actors[FOE].conditions.values()
                    if row.condition_id == "condition:typed.disarmed"], \
            f"{label}: and nothing was disarmed"


def test_the_object_menu_is_not_asked_when_neither_creature_carries_anything():
    for seed in STEAL_SEEDS:
        engine = _fight(STEALERS, seed=seed, kit={"items": []}, foe_kit={"items": []})
        asked = _Table(lambda request: None)
        engine.set_reaction_provider(asked)
        _do(engine, "STEAL", target=FOE, answers=asked)
        if _scoundrel_checks(engine):
            break
    assert not asked.source("steal_objects"), "nothing was on offer, so nothing was asked"


def test_the_scoundrel_choice_transport_publishes_the_options_it_will_be_answered_with():
    """"choice:scoundrel.*" must reach the real controller as a menu, not as an empty Use/Pass window."""
    engine, table, _check = _resolve_steal((f"take:{PACK_KEY}",))
    request = table.asked("steal_objects")[0]
    spec = request["extension_choice"]
    assert spec["option_ids"] and spec["allow_decline"] is True
    assert (spec["minimum_selections"], spec["maximum_selections"]) == (0, 1)
    assert spec["automatic_use"] is False, "a player is asked; its own controller answers for an AI fighter"
    assert request["legal_option_ids"] == list(spec["option_ids"]), "the legacy window carries no empty option list"
    trigger = request["choice_trigger"]
    assert trigger["labels"] and all(trigger["labels"][option] for option in spec["option_ids"])


# ------------------------------------------------------------------------- Steal Equipment: the same check, for a worn thing
def _steal_equipment(pick=None, *, talents=(), need_success=True, foe_kit=ARMORED, seed=None, equipment=True):
    """Play Steal Equipment (or plain Steal, ``equipment=False``) until the printed check resolves as asked."""
    sheet = [*STEALERS, *(("TAL_SCOUNDREL_STEAL_EQUIPMENT",) if equipment else ()), *talents]
    for candidate_seed in ((seed,) if seed else STEAL_SEEDS):
        engine = _fight(sheet, seed=candidate_seed, foe_kit=foe_kit)
        table = _Table(lambda request: pick if request["reaction_source_id"].endswith("steal_objects") else None)
        _do(engine, EQUIP if equipment else "STEAL", target=FOE, table=table)
        checks = _scoundrel_checks(engine)
        if checks and bool(checks[-1].payload.get("success")) is bool(need_success):
            return engine, table, checks[-1]
    raise AssertionError(f"the Steal Equipment check never resolved with success={need_success}")


def test_steal_equipment_offers_the_printed_attempt_instead_of_compiling_to_nothing():
    engine = _fight([*STEALERS, "TAL_SCOUNDREL_STEAL_EQUIPMENT"], foe_kit=ARMORED)
    button = next(row for row in engine.action_catalog.values() if (row.parameters or {}).get("steal_equipment"))
    assert button.economy.value == "ACTION" and button.costs == ((FOCUS, 1),)  # "Cost: Expend Martial Focus"
    assert _offered(engine, EQUIP)


def test_a_failed_steal_equipment_check_hands_over_nothing():
    engine, table, check = _steal_equipment((f"take:{ARMOR_KEY}",), need_success=False)
    assert table.asked("steal_objects"), "a legal worn thing was chosen before it rolled"
    assert check.payload.get("success") is False, "this case needs a check that failed"
    assert not _with(engine, FOE, ARMOR_KEY, "held_by"), "the Focus is spent; the object stays on the victim"
    assert engine.state.actors[ME].resources[FOCUS] == 0


def test_a_failed_steal_equipment_check_after_an_earlier_success_still_hands_over_nothing():
    """An object taken by an earlier success this turn is not re-taken, and a later failure adds nothing.

    Quick Thiecery buys the earlier success: Steal as a Bonus Action leaves the Action for Steal Equipment.
    """
    sheet = [*STEALERS, "TAL_SCOUNDREL_STEAL_EQUIPMENT", "TAL_SCOUNDREL_QUICK_THIEVERY"]
    for attempt in range(8):  # find a seed where the Bonus Action succeeds and the Action that follows fails
        engine = _fight(sheet, seed=f"AE{attempt}", foe_kit=ARMORED)
        engine.state.actors[ME].resource_maximums[FOCUS] = 2  # the Bonus Action twin is paid for out of the same pool
        engine.state.actors[ME].resources[FOCUS] = 2
        table = _Table(lambda request: ((f"take:{PACK_KEY}",) if request["reaction_source_id"].endswith("steal_objects")
                                       else None))
        _do(engine, "Steal (Quick Thievery: Bonus Action)", target=FOE, table=table)
        first = _scoundrel_checks(engine)
        if not first or not first[-1].payload.get("success"):
            continue
        _do(engine, EQUIP, target=FOE,
            table=_Table(lambda request: (f"take:{ARMOR_KEY}",) if request["reaction_source_id"].endswith("steal_objects") else None))
        second = _scoundrel_checks(engine)[-1]
        if second.payload.get("success"):
            continue
        break
    assert first[-1].payload.get("success") and second.payload.get("success") is False, \
        "this case needs an earlier success and a later failure in the same turn"
    assert len(_in_hand_of(engine, ME, PACK_KEY)) == 1, "the earlier success took the pack, exactly once"
    assert not _with(engine, FOE, ARMOR_KEY, "held_by"), \
        "the failed use of the printed ability hands its own object over nothing"
    assert engine.state.actors[ME].resources[FOCUS] == 0, "Steal Equipment's printed cost is still paid"


def test_steal_equipment_never_offers_a_worn_thing_the_target_is_not_wearing():
    """\"attempt to remove one worn item\": with nothing worn there is nothing this talent can remove."""
    engine = _fight([*STEALERS, "TAL_SCOUNDREL_STEAL_EQUIPMENT"], foe_kit=PACK, kit=PACK)
    table = _Table(lambda request: None)
    _do(engine, EQUIP, target=FOE, table=table)
    assert not table.asked("steal_objects"), \
        "a pack and a spear are not worn, and this talent never plants, so there is nothing to ask about"
    check = _scoundrel_checks(engine)[-1]
    assert check.payload["actor"]["mode"] == "DISADVANTAGE", "the printed Disadvantage is still rolled"
    assert not [row for row in engine.state.actors[FOE].conditions.values()
                if row.condition_id == "condition:typed.disarmed"], "and no weapon is disarmed by it"
    assert engine.state.actors[ME].resources[FOCUS] == 0, "the printed cost is still paid"


def test_steal_equipment_prints_one_worn_item_even_with_cleaned_out():
    """"attempt to remove one worn item ... the object appears in your free hand or one legal unoccupied space".

    Cleaned Out's second slot belongs to Steal's own printed result ("take or reposition up to two accessible
    objects instead of one"); Steal Equipment names a single worn item and a single place for it to appear.
    """
    engine = _fight([*STEALERS, "TAL_SCOUNDREL_STEAL_EQUIPMENT", "TAL_SCOUNDREL_CLEANED_OUT"], foe_kit=ARMORED, kit=PACK)
    table = _Table(lambda request: None)
    _do(engine, EQUIP, target=FOE, table=table)
    request = table.asked("steal_objects")[0]
    assert request["extension_choice"]["maximum_selections"] == 1, \
        "one worn item, and no second slot from Cleaned Out"
    assert not any(option.startswith("plant:") for option in request["extension_choice"]["option_ids"]), \
        "and this talent never plants"
    prompt = request["choice_trigger"]["prompt"]
    assert "plant" not in prompt.lower(), f"the question does not offer planting: {prompt}"
    assert "wearing" in prompt, "and says the object has to be one it is wearing"


def test_steal_equipment_leaves_the_targets_unworn_belongings_where_they_are_after_a_success():
    """A worn thing comes away; what the target merely carries does not (checked together, one fight)."""
    engine, _table, check = _steal_equipment((f"take:{ARMOR_KEY}",), foe_kit=ARMORED)
    assert check.payload.get("success")
    assert _stolen(engine, FOE, ARMOR_KEY), "the worn thing came away"
    assert not _stolen(engine, FOE, PACK_KEY) and not _stolen(engine, FOE, SPEAR_KEY), \
        "and the pack and the spear it merely carries did not"


def test_master_thief_does_not_remove_steal_equipments_own_disadvantage():
    engine, table, check = _steal_equipment(talents=("TAL_SCOUNDREL_MASTER_THIEF",), need_success=False)
    assert check.payload["actor"]["mode"] == "DISADVANTAGE", "\"Master Thief does not remove this Disadvantage\""
    assert not table.source("master_thief"), "Master Thief was never asked to waive it"
    assert engine.state.actors[ME].resources[FOCUS] == 0, "the 1 Martial Focus is Steal Equipment's own printed cost"


def test_steal_equipments_own_disadvantage_cancels_advantage_like_any_other_source():
    """"Master Thief does not remove this" is not "Advantage never cancels this": the roll's own sources cancel."""

    def exploited(seed, button, *, equipment):
        engine = _fight([*STEALERS, *(("TAL_SCOUNDREL_STEAL_EQUIPMENT",) if equipment else ())], seed=seed, foe_kit=ARMORED)
        _do(engine, button, target=FOE, table=_Table(lambda request: None))  # decline the object: the check alone
        _my_turn(engine)
        # Exploited Opening lasts until the start of its source's next turn, so it is applied after the turn starts.
        engine._apply_condition(engine.state.actors[FOE], "condition:typed.exploited_opening", "test:opening",
                                ME, expires_on="START_OF_SOURCE_NEXT_TURN")
        engine.state.actors[ME].resources[FOCUS] = 1
        _do(engine, button, target=FOE, table=_Table(lambda request: None))
        return _scoundrel_checks(engine)[-1]

    plain = exploited("S0", "STEAL", equipment=False)
    assert plain.payload["actor"]["mode"] == "ADVANTAGE", "Exploited Opening alone gives Advantage"
    equipped = exploited("S0", EQUIP, equipment=True)
    assert equipped.payload["actor"]["mode"] == "NORMAL", \
        "Advantage and the printed Disadvantage are two sources of one roll, and they cancel"


# ------------------------------------------------------------------------- Steal Voice: the silenced condition the engine enforces
def test_steal_voice_actually_silences_the_target_so_it_cannot_use_what_needs_speech():
    """The victim is a Berserker, so its roster really has a voice-needing action (Rift Strike) to be refused."""
    from combat import speech
    from combat.ext.condition_events import drop_condition

    for attempt in range(12):  # a Scoundrel Check, then the target's own save, can both fail
        engine = _fight([*BASE, "TAL_SCOUNDREL_STEAL_VOICE"], seed=f"VO{attempt}",
                         foe_talents=["TAL_BERSERKER_RIFT_STRIKE"])
        says = [row.display_name.split(" at ")[0] for row in engine.action_catalog.values()
                if row.owner_id == FOE and speech.needs_voice(row)]
        assert says, "the victim's roster really has an action that needs audible speech"
        # Ears Ringing, not Eyes Spoiled: a blinded creature is silenced by its own blindness, and this case is
        # about the Steal Voice save.
        _do(engine, "DIRTY TRICK: Ears Ringing + STEAL VOICE", target=FOE)
        if speech.silenced(engine.state.actors[FOE]):
            break
    assert speech.silenced(engine.state.actors[FOE]), "the failed Constitution save silenced it"
    _my_turn(engine, FOE)
    for button in says:
        assert not _offered(engine, button, actor=FOE), f"{button} needs its user's own voice"
        # the same roster, with the Silenced conditions taken off, offers it: the refusal is about silencing
        for instance_id, row in list(engine.state.actors[FOE].conditions.items()):
            if row.condition_id == speech.SILENCED:
                drop_condition(engine, engine.state.actors[FOE], instance_id, "test:unsilence")
        assert not speech.silenced(engine.state.actors[FOE])
        assert _offered(engine, button, actor=FOE)
