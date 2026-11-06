"""Sect Stewardship runs the shared substrate its printed rules lean on: the Merit Dice pool, the Sect Check, and the
printed arithmetic on a Merit Die.  Table-level: compile a character, commit through TabletopService, reload
from disk.
"""
import pytest

from canonical_catalog.service import CanonicalCatalogAuthorityService
from combat.ext.sect_stewardship import (MERIT, MERIT_SIZE, SECT_KEY, BASE_DIE, LARGEST_DIE, held_merit,
                                          merit_die_size, merit_maximum, petition_band, petition_groups,
                                          reduction_percent)
from combat.gate4_context import build_decision_context
from combat.gate4_policy import PolicyLibrary
from tests.h1_support import ROOT
from tests.hunt12_support import ME, candidate, fight as unchosen_fight, reload, send
from tests.test_journey_activities_native import A, game as journey_game
from tests.test_lock2_persistence import act

@pytest.fixture(scope="module")
def catalog():
    return CanonicalCatalogAuthorityService(ROOT)


SPHERE = "SECT_STEWARDSHIP_BASE_SECT_CHECK"  # a base rule of the sphere; the sheet pulls in the sphere with it
LEARN = "SECT_STEWARDSHIP_BASE_LEARNING_SECT_STEWARDSHIP"
PETITION_BASE = "SECT_STEWARDSHIP_BASE_PETITIONING_THE_HALL"
RICE_BOWL = "TAL_SECT_STEWARDSHIP_COMMUNAL_RICE_BOWL"
MEDICINE_QUEUE = "TAL_SECT_STEWARDSHIP_MEDICINE_HALL_QUEUE"
CONTRIBUTION = "TAL_SECT_STEWARDSHIP_CONTRIBUTION_EXCHANGE"
DEPARTMENT = "TAL_SECT_STEWARDSHIP_DEPARTMENT_LEDGER"
BRANCH_HALL = "tianxia.talent.sect_stewardship.found_a_branch_hall"

PB = 4  # the harness sheet's proficiency bonus
KEY_MOD = 4  # and its key ability modifier (a score of 18 is +4)
SECT_CHECK = "Sect Check"
PAID_CHECK = "Sect Check (spend 1 Merit Die)"


TRAINING = {"ability": "INT", "skill": "History"}  # the journey learning intent's projected choice


def fight(tmp_path, mids=(), **kwargs):
    """A fighter whose Journey learning choice has already been projected into the native sheet.

    Learning is a Journey intent, so the key choice reaches a fresh fight the way the native sheet carries it; the
    checks wait for that recorded choice exactly as before.
    """
    if mids:
        mids = [LEARN, *mids]
        kwargs.setdefault("training", TRAINING)
    return unchosen_fight(tmp_path, mids, **kwargs)


def test_sect_checks_wait_for_the_spheres_own_choice(tmp_path, monkeypatch, catalog):
    combat, table, mid = unchosen_fight(tmp_path, [LEARN, SPHERE])
    engine = reload(tmp_path, mid)
    assert not [c for c in engine.legal_candidates() if c.display_name in (SECT_CHECK, PAID_CHECK)]
    assert not [c for c in engine.legal_candidates() if c.display_name.startswith("Sect Stewardship: choose")]
    policy = PolicyLibrary(ROOT).for_actor(ME)[0]
    assert not [c for c in build_decision_context(engine, policy, for_ai=True).legal_candidates
                if "sect_key" in c.source_definition_id], "the choice is not a combat row for any seat"
    assert not last_check_or_none(engine)
    cold, jid, act, world = journey_game(tmp_path, monkeypatch, catalog)
    menu = cold().journey_menu(jid, A)
    learn = [o for o in menu["options"] if o["kind"] == "sect_learn"]
    assert learn, "the key choice is offered on the Journey learning intent"
    assert all("key ability" in o["label"] for o in learn)


def last_check_or_none(engine):
    return [e for e in engine.events if e.event_type == "CHECK_ROLLED"]


SECT_CHECK_REMINDER = ("The engine rolls the check and adds at most one Merit Die, spent either before the d20 (the "
                       "paid Sect Check) or after it but before the result is declared (asked once the d20 is "
                       "visible). The table sets what the check is for, its Difficulty, and what the result means.")


def send_declining(combat, table, mid, chosen):
    """Take an action, and decline the after-d20 Merit Die offer the bare Sect Check now opens.

    The bare Sect Check offers one Merit Die once its d20 exists (the "or after rolling the d20" half of the printed
    window). Tests here that are about other rows decline it, so they still see the bare printed roll.
    """
    result = send(combat, table, mid, chosen)
    prompt = result.get("reaction") or {}
    if prompt.get("context", {}).get("reaction_source_id") == "choice:needle.sect_stewardship.add_merit_die":
        send(combat, table, mid, chosen, answers=[{**prompt["context"], "selection": "DECLINE"}])
    return result


def test_learning_choice_is_one_journey_offer_per_ability_and_skill(tmp_path, monkeypatch, catalog):
    """The learning intent's own player-facing text, and that it can be recorded only once."""
    cold, jid, act, world = journey_game(tmp_path, monkeypatch, catalog)
    learn = [o for o in cold().journey_menu(jid, A)["options"] if o["kind"] == "sect_learn"]
    assert len(learn) == 24, "three printed abilities times eight printed skills and tools"
    for option in learn:
        text = option["label"]
        assert "fixed key ability" in text
        assert "gain proficiency" in text
        assert "No action or Merit Die cost" in text
        assert "until you change" not in text
        assert text.count("Sect Stewardship") == 1
    state = act("sect_learn", {"ability": "INT", "proficiency": "History", "approval": ""})
    assert state["actors"][A]["resources"][SECT_KEY] == 1
    with pytest.raises(ValueError):
        act("sect_learn", {"ability": "WIS", "proficiency": "Religion", "approval": ""})
    assert not [o for o in cold().journey_menu(jid, A)["options"] if o["kind"] == "sect_learn"]


@pytest.mark.parametrize("paid", [False, True])
def test_complete_sect_reminder_is_recorded_after_reload(tmp_path, paid):
    combat, table, mid = fight(tmp_path, [SPHERE])
    chosen = candidate(combat, mid, lambda c: c.display_name == (PAID_CHECK if paid else SECT_CHECK))
    send_declining(combat, table, mid, chosen)
    engine = reload(tmp_path, mid)
    reminders = [e.payload["rider"] for e in engine.events if e.event_type == "GM_RIDER"]
    assert reminders[-1] == SECT_CHECK_REMINDER


@pytest.mark.parametrize("paid", [False, True])
def test_prior_sect_catalog_preserves_its_saved_expression(tmp_path, monkeypatch, paid):
    """Old catalogues have no sphere-choice fields; preserve their committed legacy expression."""
    from combat.ext import sect_stewardship
    original = sect_stewardship._sect_check_action

    def prior_action(info, paid):
        action = original(info, paid)
        parameters = dict(action.parameters)
        parameters.pop("sect_key_required")
        typed = dict(parameters["typed"])
        numbers = dict(typed["numbers"])
        numbers.pop("ability_mods")
        typed["numbers"] = numbers
        parameters["typed"] = typed
        return action.model_copy(update={"parameters": parameters})

    monkeypatch.setattr(sect_stewardship, "_sect_check_action", prior_action)
    combat, table, mid = fight(tmp_path, [SPHERE])
    chosen = candidate(combat, mid, lambda c: c.display_name == (PAID_CHECK if paid else SECT_CHECK))
    send_declining(combat, table, mid, chosen)
    engine = reload(tmp_path, mid)
    event = last_check(engine)
    roll = event.payload["actor"]
    assert roll["total"] == roll["natural_result"] + PB + KEY_MOD + event.payload["merit_die"]
    assert held_merit(engine, engine.state.actors[ME]) == PB - int(paid)


@pytest.mark.parametrize("ability,modifier", [("Intelligence", 1), ("Wisdom", 0), ("Charisma", -1)])
@pytest.mark.parametrize("paid", [False, True])
def test_projected_sect_choice_and_complete_reminder_survive_table_reload(tmp_path, monkeypatch, ability, modifier, paid):
    from tests import hunt12_support
    original = hunt12_support.sheet

    def unequal_sheet(*args, **kwargs):
        doc = original(*args, **kwargs)
        for row in doc["ability_scores_and_statistics"]["abilities"]:
            if row["ability"] in {"INT", "WIS", "CHA"}:
                row["modifier"] = {"INT": 1, "WIS": 0, "CHA": -1}[row["ability"]]
                row["score"] = 10 + 2 * row["modifier"]
        return doc

    monkeypatch.setattr(hunt12_support, "sheet", unequal_sheet)
    # The learning intent writes the projected choice onto the native sheet; a fresh fight reads it from there.
    combat, table, mid = unchosen_fight(tmp_path, [LEARN, SPHERE],
        training={"ability": {"Intelligence": "INT", "Wisdom": "WIS", "Charisma": "CHA"}[ability],
                  "skill": "History"})
    engine = reload(tmp_path, mid)
    assert engine.state.actors[ME].resources[SECT_KEY] == {"Intelligence": 1, "Wisdom": 2, "Charisma": 3}[ability]
    assert type(engine.state.actors[ME].resources[SECT_KEY]) is int
    assert not [c for c in engine.legal_candidates() if c.display_name.startswith("Sect Stewardship: choose")]
    # A new service must use the persisted native sheet, rather than the original session cache.
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    chosen = candidate(combat, mid, lambda c: c.display_name == (PAID_CHECK if paid else SECT_CHECK))
    send_declining(combat, table, mid, chosen)
    engine = reload(tmp_path, mid)
    event = last_check(engine)
    roll = event.payload["actor"]
    assert roll["total"] == roll["natural_result"] + PB + modifier + event.payload["merit_die"]
    assert held_merit(engine, engine.state.actors[ME]) == PB - int(paid)
    reminders = [e.payload["rider"] for e in engine.events if e.event_type == "GM_RIDER"]
    assert reminders[-1] == SECT_CHECK_REMINDER

# What Communal Rice Bowl's printed list names: "food, lodging, work clothes, common tools, a bath, or safe storage".
# A button whose text offers any of them must be a button that carries the printed "treat a 1 as a 3".
COVERED_MARKERS = ("a meal", "safe sleeping space", "robes or work clothes", "tools for a duty", "a bath",
                   "store your ordinary possessions")


# ------------------------------------------------------------------------------- reading a committed fight back
def last_check(engine):
    checks = [e for e in engine.events if e.event_type == "CHECK_ROLLED"]
    assert checks, "no check was rolled"
    return checks[-1]


def merit_rolls(engine):
    return [roll for roll in engine.rolls if str(roll.reason).startswith("MERIT_DIE:")]


def logs_starting(engine, prefix):
    return [e.payload.get("log", "") for e in engine.events
            if e.event_type == "PASSIVE_TRIGGERED" and str(e.payload.get("log", "")).startswith(prefix)]


def petition_logs(engine):
    """Every petition line, which names what was petitioned for: "Petitioning the Hall for ..."."""
    return logs_starting(engine, "Petitioning the Hall for ")


def description(combat, mid, endswith):
    """The player-facing description of the compiled action whose source id ends with ``endswith``."""
    engine = combat._load_session(mid).engine
    action = next(row for row in engine.action_catalog.values()
                  if str(row.source_definition_id).endswith(endswith))
    return str(action.parameters.get("description") or "")


def merit_spent_events(engine, source_ending=""):
    """Every Merit Die the fight has paid for, optionally only the ones this action paid for."""
    return [e for e in engine.events if e.event_type == "RESOURCE_SPENT" and e.payload.get("resource_id") == MERIT
            and e.actor_id == ME and str(e.source_definition_id).endswith(source_ending)]


def petition_rows(combat, mid):
    """Every petition button the committed fight's catalog holds, keyed by its printed topic."""
    found = {}
    for row in combat._load_session(mid).engine.action_catalog.values():
        source_id = str(row.source_definition_id)
        if "petition." not in source_id:
            continue
        topic = source_id.rsplit("petition.", 1)[1]
        assert topic not in found, f"two compiled buttons share the topic {topic}"
        found[topic] = row
    return found


def offered_petition_topics(engine):
    """The printed topics of the petition buttons the table actually offers this character right now."""
    return sorted(str(row.source_definition_id).rsplit("petition.", 1)[1]
                  for row in engine.legal_candidates() if "petition." in row.source_definition_id)


# ------------------------------------------------------------------------------ driving the table's own turns
def end_and_come_back(table, mid):
    """End whatever turn the table is on until this character is the one deciding again."""
    while table.state(mid)["menu"]["actor_id"] != ME:
        assert act(table, mid, "end")["status"] == "COMMITTED"


def use(combat, table, mid, chosen):
    """One action for this character, then hand the turn on."""
    assert send(combat, table, mid, chosen)["status"] == "COMMITTED"
    assert act(table, mid, "end")["status"] == "COMMITTED"
    end_and_come_back(table, mid)


def hold_merit_dice(tmp_path, combat, table, mid, left):
    """Really spend Merit Dice on paid Sect Checks until only ``left`` remain.

    "Your maximum number of Merit Dice is equal to your Proficiency Bonus" means a fresh character holds four, so the
    printed "the last die" case is reached by spending the others through the real menu.
    """
    while held_merit(reload(tmp_path, mid), reload(tmp_path, mid).state.actors[ME]) > left:
        use(combat, table, mid, candidate(combat, mid, lambda c: c.display_name == PAID_CHECK))
    engine = reload(tmp_path, mid)
    assert held_merit(engine, engine.state.actors[ME]) == left
    return engine


def force_merit_die(monkeypatch, *dice):
    """Every Merit Die this fight rolls reads its dice from ``dice`` by position.

    The printed arithmetic on a die (a 1 reads as a 3, two rolls keep the higher) can only be tested with a known
    result. The table resolves its action in its own session and re-derives the same rolls when it reloads, so the
    roller's class is patched for the whole test and every Merit Die roll takes the same dice -- which also keeps the
    table's own prediction of the action equal to what it commits.
    """
    from combat.gate2_rolls import DeterministicRollAuthority

    original = DeterministicRollAuthority.roll

    def roll(self, spec, *, actor_id, reason, mode="NORMAL", critical=False, fixed_damage=None):
        record = original(self, spec, actor_id=actor_id, reason=reason, mode=mode, critical=critical,
                          fixed_damage=fixed_damage)
        if not str(reason).startswith("MERIT_DIE:") or fixed_damage is not None:
            return record
        values = tuple(min(int(dice[index % len(dice)]), spec.sides) for index in range(len(record.dice)))
        return record.model_copy(update={"dice": values, "total": sum(values) + record.modifier})

    monkeypatch.setattr(DeterministicRollAuthority, "roll", roll)


# ------------------------------------------------------------------------------------- the printed resource
def test_merit_dice_pool_is_pb_sized_and_survives_reload(tmp_path):
    '''"Your maximum number of Merit Dice is equal to your Proficiency Bonus, minimum 1", as a real held pool.'''
    combat, table, mid = fight(tmp_path, [SPHERE])
    engine = reload(tmp_path, mid)
    before = engine.state.actors[ME]
    assert before.resources[MERIT] == merit_maximum({"pb": PB}) == PB
    assert before.resource_maximums[MERIT] == PB
    assert before.resources[MERIT_SIZE] == BASE_DIE == merit_die_size(engine, before)


def test_a_character_without_the_sphere_holds_no_pool_and_gets_no_action(tmp_path):
    """The plug-in is inert for a character who printed neither the sphere nor one of its records."""
    combat, table, mid = fight(tmp_path, [])
    engine = reload(tmp_path, mid)
    assert MERIT not in engine.state.actors[ME].resources
    assert SECT_KEY not in engine.state.actors[ME].resources
    mine = [row for row in engine.legal_candidates() if "sect_check" in row.source_definition_id
            or "petition" in row.source_definition_id or "sect_key" in row.source_definition_id]
    assert not mine, "and no Sect Stewardship button at all"


@pytest.mark.parametrize("mids", [[SPHERE], [SPHERE, BRANCH_HALL]])
def test_the_die_stays_a_d4_until_a_branch_hall_is_actually_present(tmp_path, mids):
    '''"your Merit Die increases by one step" needs the branch AND acting by its purpose; owning the talent is
    neither, so the die stays the printed d4.'''
    combat, table, mid = fight(tmp_path, mids)
    actor = reload(tmp_path, mid).state.actors[ME]
    assert actor.resources[MERIT_SIZE] == BASE_DIE
    assert actor.resource_maximums[MERIT_SIZE] == LARGEST_DIE


def test_the_die_size_pool_is_the_die_size_not_decoration(tmp_path):
    """The pool is read as the die's size in faces, so the branch-hall step has exactly one place to write."""
    combat, table, mid = fight(tmp_path, [SPHERE])
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[ME]
    actor.resources[MERIT_SIZE] = BASE_DIE + 2
    assert merit_die_size(engine, actor) == BASE_DIE + 2
    actor.resources[MERIT_SIZE] = 40
    assert merit_die_size(engine, actor) == LARGEST_DIE, "the printed maximum of d10 holds"


# ------------------------------------------------------------------------------- the printed Sect Check roll
def test_bare_sect_check_rolls_d20_plus_pb_plus_key(tmp_path):
    '''"d20 + Proficiency Bonus + Sect Stewardship key ability modifier", with no die spent.'''
    combat, table, mid = fight(tmp_path, [SPHERE])
    chosen = candidate(combat, mid, lambda c: c.display_name == SECT_CHECK)
    send_declining(combat, table, mid, chosen)
    engine = reload(tmp_path, mid)
    event = last_check(engine)
    actor_roll = event.payload["actor"]
    assert event.payload["check"] == SECT_CHECK
    assert event.payload["merit_die"] == 0
    assert actor_roll["natural_result"] == actor_roll["dice"][0]
    assert actor_roll["total"] == actor_roll["natural_result"] + PB + KEY_MOD, "the sum is d20 + PB + key ability"
    assert held_merit(engine, engine.state.actors[ME]) == PB, "no die was spent"


def test_paid_sect_check_spends_one_die_and_adds_it(tmp_path, monkeypatch):
    '''"You may spend one Merit Die ... Roll the Merit Die and add it to the check."  Only one die may be added.'''
    force_merit_die(monkeypatch, 3)
    combat, table, mid = fight(tmp_path, [SPHERE])
    start = held_merit(reload(tmp_path, mid), reload(tmp_path, mid).state.actors[ME])
    paid = candidate(combat, mid, lambda c: c.display_name == PAID_CHECK)
    assert send(combat, table, mid, paid)["status"] == "COMMITTED"
    engine = reload(tmp_path, mid)
    event = last_check(engine)
    rolled = merit_rolls(engine)
    assert len(rolled) == 1 and list(rolled[0].dice) == [3], "exactly one Merit Die reached the check"
    assert event.payload["merit_die"] == 3
    actor_roll = event.payload["actor"]
    assert actor_roll["total"] == actor_roll["natural_result"] + PB + KEY_MOD + 3
    assert held_merit(engine, engine.state.actors[ME]) == start - 1, "the paid line must cost exactly one Merit Die"


def test_the_paid_line_is_not_offered_once_no_die_is_left(tmp_path):
    """A line that costs a Merit Die is not offered to a character who has none to spend."""
    combat, table, mid = fight(tmp_path, [SPHERE])
    hold_merit_dice(tmp_path, combat, table, mid, 0)
    engine = reload(tmp_path, mid)
    assert held_merit(engine, engine.state.actors[ME]) == 0
    assert not [row for row in engine.legal_candidates() if row.display_name == PAID_CHECK]
    assert [row for row in engine.legal_candidates() if row.display_name == SECT_CHECK], "the free line remains"


# --------------------------------------------------------------- Petitioning the Hall is a Journey intent
JOURNEY_KEY = "sect_stewardship:journey"


def journey_institution(world, names):
    for request in names:
        package = {"description": "Support for " + request, "items": [], "entitlements": []}
        world(LEARN, "support_terms", "hall:" + request,
              {"request": request, "standing": 2, "ordinary": 1,
               "minimum": package,
               "useful": {**package, "description": "Useful help with " + request},
               "exceptional": {**package, "description": "Exceptional help with " + request}})
    world(LEARN, "institution", "hall", {"name": "Records Hall", "authority": "Hall steward",
        "standing": 2, "good_standing": 1, "present": 1, "ordinary_support": list(names)})
    world(LEARN, "recovery_context", "travel", {"away_from_all_institutions": 0,
        "evidence": "The party is at the Records Hall"})


def learn(act):
    return act("sect_learn", {"ability": "INT", "proficiency": "History", "approval": ""})


def force_journey_die(monkeypatch, *dice):
    """Force the Journey Merit Die roll (reason PETITION) without touching the combat roller."""
    from combat.gate2_rolls import DeterministicRollAuthority
    original = DeterministicRollAuthority.roll
    position = [0]

    def roll(self, spec, **kw):
        record = original(self, spec, **kw)
        if kw.get("reason") != PETITION_BASE or kw.get("fixed_damage") is not None:
            return record
        values = []
        for _ in range(len(record.dice)):
            values.append(min(int(dice[position[0] % len(dice)]), spec.sides))
            position[0] += 1
        return record.model_copy(update={"dice": tuple(values), "total": sum(values) + record.modifier})

    monkeypatch.setattr(DeterministicRollAuthority, "roll", roll)


def journey_petition(cold, jid, act, world, request):
    learn(act)
    journey_institution(world, [request])
    before = cold().journey_state(jid)["actors"][A]["resources"][MERIT]
    state = act("sect_petition", {"institution": "hall", "request": request})
    receipt = state["actors"][A]["source_states"][JOURNEY_KEY]["support"][-1]
    return state, receipt, before


def journey_groups(cold, jid):
    from combat.ext.journey_institutions import contract
    return contract(cold().journeys.load(jid), A)["petition_groups"]


def journey_rolls(state):
    return [e for e in state["events"] if e["kind"] == "JOURNEY_ROLL"]


# ------------------------------------------------------------------------------- the printed lists, written out here
# These are written as plain lists on purpose, not read from the plug-in's own request tables. A test that derived the
# expected requests from ``BASE_REQUESTS``/``PETITION_TALENTS`` would agree with the plug-in even if a printed request
# were deleted from it, which is the opposite of what "no printed request is dropped" has to mean: a map, public
# notices, or any uncovered request would vanish from the player's menu and the test would still pass.
ORDINARY_LABEL = "Petition the Hall for ordinary help"
HOUSEHOLD_LABEL = "Petition the Hall for food, lodging, work clothes, tools, a bath or storage"
MEDICAL_LABEL = "Petition the Hall for medical help"

# "Common petitions include:", the base rule's own list, in the printed order.
BASE_LIST = ("a meal and safe sleeping space", "a clean set of robes or work clothes", "mundane tools for a duty",
             "permission to enter a public hall", "a basic map of the sect grounds",
             "an introduction to a clerk, senior, farmer, guard or apprentice", "access to public notices",
             "use of a common room, kitchen, stable, outer library desk or messenger channel",
             "temporary storage for ordinary goods", "a written receipt or witness statement")
# Communal Rice Bowl names "food, lodging, work clothes, common tools, a bath, or safe storage"; where its own list is
# finer than the base rule's wording for the same kind ("a meal and safe sleeping space"), its list is what it prints.
RICE_LIST = ("a meal", "a bed", "work clothes", "common tools for a duty", "a bath",
             "a safe place to store your ordinary possessions")
# Medicine Hall Queue names "ordinary medical treatment, antidotes, bandages, supervised recovery, or a Medicine Hall
# appointment".
MEDICAL_LIST = ("ordinary treatment", "antidotes", "bandages", "supervised recovery", "a Medicine Hall appointment")
# The base rule's requests that Communal Rice Bowl does not name, still in the printed order.
UNCOVERED_LIST = ("permission to enter a public hall", "a basic map of the sect grounds",
                  "an introduction to a clerk, senior, farmer, guard or apprentice", "access to public notices",
                  "use of a common room, kitchen, stable, outer library desk or messenger channel",
                  "a written receipt or witness statement")

# One entry per printed button: (topic, button name, requests it offers, printed talents that changed its die, the
# printed replacement for a 1, whether the die is rolled twice).
EXPECTED_MENUS = {
    0: (("ordinary", ORDINARY_LABEL, BASE_LIST, (), None, False),),
    1: (("ordinary", ORDINARY_LABEL, UNCOVERED_LIST, (), None, False),
        ("household", HOUSEHOLD_LABEL, RICE_LIST, ("Communal Rice Bowl",), 3, False)),
    2: (("ordinary", ORDINARY_LABEL, BASE_LIST, (), None, False),
        ("medical", MEDICAL_LABEL, MEDICAL_LIST, ("Medicine Hall Queue",), None, True)),
    3: (("ordinary", ORDINARY_LABEL, UNCOVERED_LIST, (), None, False),
        ("household", HOUSEHOLD_LABEL, RICE_LIST, ("Communal Rice Bowl",), 3, False),
        ("medical", MEDICAL_LABEL, MEDICAL_LIST, ("Medicine Hall Queue",), None, True)),
}
OWNERSHIP_CASES = {0: [], 1: [RICE_BOWL], 2: [MEDICINE_QUEUE], 3: [RICE_BOWL, MEDICINE_QUEUE]}


@pytest.mark.parametrize("case", sorted(EXPECTED_MENUS))
def test_each_ownership_offers_exactly_the_printed_requests(tmp_path, monkeypatch, catalog, case):
    """Every ownership combination keeps the printed groups and offers each printed request exactly once.

    The Journey contract keeps the groups that carry the printed riders, and the Journey menu offers one petition
    intent per request the appropriate institution declared. Nothing here is read from the plug-in's request tables:
    the expected labels, requests, talents and die changes are the lists written below.
    """
    talents = OWNERSHIP_CASES[case]
    expected = EXPECTED_MENUS[case]
    cold, jid, act, world = journey_game(tmp_path, monkeypatch, catalog, talents=talents)
    learn(act)
    groups = journey_groups(cold, jid)
    assert [tuple(r["text"] for r in group["requests"]) for group in groups] == [entry[2] for entry in expected]
    assert [(group["one_becomes"] or None, bool(group["twice"])) for group in groups] ==         [(entry[4], entry[5]) for entry in expected]
    compiled = petition_groups(frozenset(talents))
    assert [group.label for group in compiled] == [entry[1] for entry in expected], \
        "the plug-in's own groups agree with the printed labels"
    assert [group.talent_names for group in compiled] == [entry[3] for entry in expected]
    if RICE_BOWL in talents:
        covered = set(COVERED_MARKERS)
        for group in groups:
            texts = {request["text"] for request in group["requests"]}
            if any(marker in text for text in texts for marker in covered):
                assert group["one_becomes"] == 3, "a covered request is answered by the group that carries the 3"
    names = [request for entry in expected for request in entry[2]]
    journey_institution(world, names)
    offers = [option for option in cold().journey_menu(jid, A)["options"] if option["kind"] == "sect_petition"]
    assert sorted(option["payload"]["request"] for option in offers) == sorted(names)
    assert len(offers) == len(names) == len(set(names)), "each printed request is offered exactly once"
    assert all(option["payload"]["request"] in option["label"] for option in offers)


def test_common_tools_ride_the_line_that_carries_the_replacement(tmp_path, monkeypatch, catalog):
    cold, jid, act, world = journey_game(tmp_path, monkeypatch, catalog, talents=(RICE_BOWL,))
    learn(act)
    groups = journey_groups(cold, jid)
    household = next(group for group in groups if group["one_becomes"] == 3)
    ordinary = next(group for group in groups if group["one_becomes"] != 3)
    assert "common tools for a duty" in {request["text"] for request in household["requests"]}
    assert "tools for a duty" not in {request["text"] for request in ordinary["requests"]}


def test_the_base_rule_still_offers_ordinary_tools_to_anyone(tmp_path, monkeypatch, catalog):
    cold, jid, act, world = journey_game(tmp_path, monkeypatch, catalog)
    learn(act)
    ordinary = journey_groups(cold, jid)[0]
    texts = {request["text"] for request in ordinary["requests"]}
    assert "mundane tools for a duty" in texts
    assert "temporary storage for ordinary goods" in texts, "the printed list also grants temporary storage"
    assert len(journey_groups(cold, jid)) == 1, "and no household group without the talent"


@pytest.mark.parametrize("petition_request", [BASE_LIST[0], RICE_LIST[0], MEDICAL_LIST[0]])
def test_petition_costs_one_die_and_reports_a_printed_band(tmp_path, monkeypatch, catalog, petition_request):
    """The printed non-combat petition spends one Merit Die and reports its 1-2 / 3-4 / 5+ band."""
    force_journey_die(monkeypatch, 3)
    cold, jid, act, world = journey_game(tmp_path, monkeypatch, catalog)
    state, receipt, before = journey_petition(cold, jid, act, world, petition_request)
    assert receipt["die"] == 3
    assert receipt["band"] == petition_band(3)
    assert receipt["request"] == petition_request
    assert state["actors"][A]["resources"][MERIT] == before - 1
    assert len(journey_rolls(state)) == 1, "the petition rolls exactly one Merit Die"


@pytest.mark.parametrize("rolled,read", [(1, 3), (2, 2), (3, 3)])
def test_communal_rice_bowl_replaces_only_a_one(tmp_path, monkeypatch, catalog, rolled, read):
    """Communal Rice Bowl's printed "treat a Merit Die result of 1 as a 3"; a 2 stays a 2 and its band."""
    force_journey_die(monkeypatch, rolled)
    cold, jid, act, world = journey_game(tmp_path, monkeypatch, catalog, talents=(RICE_BOWL,))
    state, receipt, before = journey_petition(cold, jid, act, world, RICE_LIST[0])
    assert list(journey_rolls(state)[0]["roll"]["dice"]) == [rolled], "the die itself rolled what was forced"
    assert receipt["die"] == read
    assert receipt["band"] == petition_band(read)
    assert state["actors"][A]["resources"][MERIT] == before - 1


@pytest.mark.parametrize("petition_request", RICE_LIST)
def test_every_request_rice_bowl_names_reads_a_one_as_three(tmp_path, monkeypatch, catalog, petition_request):
    """The printed benefit is for the requested benefit, whichever of its named requests is asked for."""
    force_journey_die(monkeypatch, 1)
    cold, jid, act, world = journey_game(tmp_path, monkeypatch, catalog, talents=(RICE_BOWL,))
    state, receipt, before = journey_petition(cold, jid, act, world, petition_request)
    assert list(journey_rolls(state)[0]["roll"]["dice"]) == [1], "the printed die rolled a 1"
    assert receipt["request"] == petition_request
    assert receipt["die"] == 3, "a covered request reads its 1 as a 3"
    assert receipt["band"] == petition_band(3)
    assert state["actors"][A]["resources"][MERIT] == before - 1


def test_the_ordinary_line_still_answers_the_requests_rice_bowl_does_not_name(tmp_path, monkeypatch, catalog):
    """A public hall, a map, an introduction, notices, a shared room and a receipt are not named; the die is read as rolled."""
    request = "a basic map of the sect grounds"
    force_journey_die(monkeypatch, 1)
    cold, jid, act, world = journey_game(tmp_path, monkeypatch, catalog, talents=(RICE_BOWL,))
    state, receipt, before = journey_petition(cold, jid, act, world, request)
    assert receipt["die"] == 1, "a petition for a map reads a 1 as a 1"
    assert receipt["band"] == petition_band(1)
    assert receipt["fulfillment"]["description"] == "Support for " + request, "the die bought the minimum package"
    assert "Useful" not in receipt["fulfillment"]["description"]
    assert state["actors"][A]["resources"][MERIT] == before - 1


def test_every_printed_request_is_offered_exactly_once(tmp_path, monkeypatch, catalog):
    """The base steward's single group holds the whole printed list, and the menu offers each request once."""
    cold, jid, act, world = journey_game(tmp_path, monkeypatch, catalog)
    learn(act)
    groups = journey_groups(cold, jid)
    assert len(groups) == 1
    assert tuple(request["text"] for request in groups[0]["requests"]) == BASE_LIST
    journey_institution(world, BASE_LIST)
    offers = [option for option in cold().journey_menu(jid, A)["options"] if option["kind"] == "sect_petition"]
    assert sorted(option["payload"]["request"] for option in offers) == sorted(BASE_LIST)
    assert len(offers) == len(BASE_LIST) == len(set(BASE_LIST))


def test_medicine_hall_queue_rolls_twice_and_keeps_the_higher(tmp_path, monkeypatch, catalog):
    """Medicine Hall Queue's "roll your Merit Die twice and use the higher result", only on the medical petition."""
    force_journey_die(monkeypatch, 1, 4)
    cold, jid, act, world = journey_game(tmp_path, monkeypatch, catalog, talents=(MEDICINE_QUEUE,))
    state, receipt, before = journey_petition(cold, jid, act, world, MEDICAL_LIST[0])
    rolled = journey_rolls(state)
    assert [list(event["roll"]["dice"]) for event in rolled] == [[1], [4]], "two real dice were rolled"
    assert receipt["die"] == 4 == max(event["roll"]["dice"][0] for event in rolled)
    assert state["actors"][A]["resources"][MERIT] == before - 1


def test_medicine_hall_queue_does_not_touch_an_ordinary_petition(tmp_path, monkeypatch, catalog):
    """The double roll is printed for a medical petition, not for every petition."""
    force_journey_die(monkeypatch, 1, 4)
    cold, jid, act, world = journey_game(tmp_path, monkeypatch, catalog, talents=(MEDICINE_QUEUE,))
    state, receipt, before = journey_petition(cold, jid, act, world, BASE_LIST[0])
    assert len(journey_rolls(state)[0]["roll"]["dice"]) == 1
    assert receipt["die"] == 1


def test_the_built_in_ai_is_never_offered_one_of_these_lines(tmp_path):
    """Institutional requests remain player-only, while automatic seats can make Sect Checks."""
    combat, table, mid = fight(tmp_path, [SPHERE, RICE_BOWL, MEDICINE_QUEUE, CONTRIBUTION, DEPARTMENT])
    engine = reload(tmp_path, mid)
    policy = PolicyLibrary(ROOT).for_actor(ME)[0]

    def mine(rows):
        return [row.source_definition_id for row in rows
                if "sect_check" in row.source_definition_id or "petition" in row.source_definition_id
                or row.source_definition_id.endswith(".reduce")]

    assert mine(build_decision_context(engine, policy, include_item_actions=True).legal_candidates)
    ai = mine(build_decision_context(engine, policy, for_ai=True).legal_candidates)
    assert len([row for row in ai if "sect_check" in row]) == 2
    assert not [row for row in ai if "petition" in row or row.endswith(".reduce")]


# ------------------------------------------------------------------------------ the printed reduction arithmetic
@pytest.mark.parametrize("number,expected", [(1, 10), (3, 30), (5, 50), (7, 50), (9, 50)])
def test_reduction_is_ten_percent_per_number_capped_at_fifty(number, expected):
    '''"reduce ... by 10 percent per number rolled on the Merit Die, to a maximum reduction of 50 percent".'''
    assert reduction_percent(number) == expected


@pytest.mark.parametrize("feature_id,short,held,die,percent", [
    (CONTRIBUTION, "cost", PB, 3, 30), (CONTRIBUTION, "cost", 1, 4, 40),
    (DEPARTMENT, "time", PB, 4, 40), (DEPARTMENT, "waste", 1, 2, 20),
])
def test_a_reduction_costs_exactly_one_die_and_reports_the_printed_percentage(
        tmp_path, monkeypatch, feature_id, short, held, die, percent):
    '''"spend one Merit Die ... reduce ... by 10 percent per number rolled", paid once whatever the pool holds.

    The die is the action's own cost and the engine spends it before the effects run, so a row must not charge a
    second time: with a full pool that costs two dice for one benefit, and with a single die it spends the last one
    and then rolls nothing.
    '''
    force_merit_die(monkeypatch, die)
    combat, table, mid = fight(tmp_path, [SPHERE, feature_id])
    if held < PB:
        hold_merit_dice(tmp_path, combat, table, mid, held)
    engine = reload(tmp_path, mid)
    start = held_merit(engine, engine.state.actors[ME])
    chosen = candidate(combat, mid, lambda c: str(c.source_definition_id).endswith(f"{short}.reduce"))
    assert send(combat, table, mid, chosen)["status"] == "COMMITTED"
    engine = reload(tmp_path, mid)
    event = last_check(engine)
    spent = merit_spent_events(engine, source_ending=".reduce")
    assert len(spent) == 1 and spent[0].payload["amount"] == 1, "exactly one Merit Die is paid, by the action cost"
    assert held_merit(engine, engine.state.actors[ME]) == start - 1 == held - 1
    assert list(merit_rolls(engine)[-1].dice) == [die]
    assert event.payload["reduction_percent"] == percent == reduction_percent(die)
    line = logs_starting(engine, "Department Ledger:") + logs_starting(engine, "Contribution Exchange:")
    assert len(line) == 1, "one line, and it names the talent"
    assert event.payload["cuts"] in line[0], "the log names what the percentage cuts"


def test_the_reduction_log_says_which_thing_the_percentage_cuts(tmp_path):
    """Department Ledger prints "choose one"; each button and its log say whether the time or the wastage was cut."""
    combat, table, mid = fight(tmp_path, [SPHERE, DEPARTMENT])
    buttons = lambda: [row.display_name for row in reload(tmp_path, mid).legal_candidates()
                       if str(row.source_definition_id).endswith(".reduce")]
    assert len(buttons()) == 2, "one button per printed choice the percentage applies to"
    for name in buttons():
        use(combat, table, mid, candidate(combat, mid, lambda c: c.display_name == name))
    engine = reload(tmp_path, mid)
    assert held_merit(engine, engine.state.actors[ME]) == PB - 2, "each button spends exactly one die"
    lines = logs_starting(engine, "Department Ledger:")
    assert len(lines) == 2
    assert any("the time the project takes" in line for line in lines)
    assert any("ordinary wastage, spoilage or loss" in line for line in lines)
    assert "the time the project takes" in description(combat, mid, "time.reduce")
    assert "ordinary wastage, spoilage or loss" in description(combat, mid, "waste.reduce")
