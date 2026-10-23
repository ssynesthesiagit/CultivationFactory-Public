"""Sect Stewardship runs the shared substrate its printed rules lean on: the Merit Dice pool, the Sect Check, and the
printed arithmetic on a Merit Die.  Table-level: compile a character, commit through TabletopService, reload
from disk.
"""
import pytest

from combat.ext.sect_stewardship import (MERIT, MERIT_SIZE, SECT_KEY, BASE_DIE, LARGEST_DIE, PETITION_TALENTS, held_merit,
                                          merit_die_size, merit_maximum, petition_band, petition_groups,
                                          reduction_percent)
from combat.gate4_context import build_decision_context
from combat.gate4_policy import PolicyLibrary
from tests.h1_support import ROOT
from tests.hunt12_support import ME, candidate, fight as unchosen_fight, reload, send
from tests.test_lock2_persistence import act

SPHERE = "SECT_STEWARDSHIP_BASE_SECT_CHECK"  # a base rule of the sphere; the sheet pulls in the sphere with it
RICE_BOWL = "TAL_SECT_STEWARDSHIP_COMMUNAL_RICE_BOWL"
MEDICINE_QUEUE = "TAL_SECT_STEWARDSHIP_MEDICINE_HALL_QUEUE"
CONTRIBUTION = "TAL_SECT_STEWARDSHIP_CONTRIBUTION_EXCHANGE"
DEPARTMENT = "TAL_SECT_STEWARDSHIP_DEPARTMENT_LEDGER"
BRANCH_HALL = "tianxia.talent.sect_stewardship.found_a_branch_hall"

PB = 4  # the harness sheet's proficiency bonus
KEY_MOD = 4  # and its key ability modifier (a score of 18 is +4)
SECT_CHECK = "Sect Check"
PAID_CHECK = "Sect Check (spend 1 Merit Die)"


def fight(tmp_path, mids=(), **kwargs):
    """Existing arithmetic cases explicitly choose the printed Intelligence option."""
    combat, table, mid = unchosen_fight(tmp_path, mids, **kwargs)
    if mids:
        choices = [c for c in combat._load_session(mid).engine.legal_candidates()
                   if c.display_name == "Sect Stewardship: choose Intelligence"]
        if choices:
            assert send(combat, table, mid, choices[0])["status"] == "COMMITTED"
    return combat, table, mid


def test_sect_checks_wait_for_the_spheres_own_choice(tmp_path):
    combat, table, mid = unchosen_fight(tmp_path, [SPHERE])
    engine = reload(tmp_path, mid)
    assert not [c for c in engine.legal_candidates() if c.display_name in (SECT_CHECK, PAID_CHECK)]
    assert {c.display_name for c in engine.legal_candidates() if c.display_name.startswith("Sect Stewardship: choose")} == {
        "Sect Stewardship: choose Intelligence", "Sect Stewardship: choose Wisdom", "Sect Stewardship: choose Charisma"}
    policy = PolicyLibrary(ROOT).for_actor(ME)[0]
    assert not [c for c in build_decision_context(engine, policy, for_ai=True).legal_candidates
                if "sect_key" in c.source_definition_id], "the player records their own learning choice"
    assert not last_check_or_none(engine)


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


def test_learning_choice_assembled_sheet_tooltips_are_once_per_fight(tmp_path):
    """Check the sheet's assembled text, including the shared setting-choice footer."""
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from tests.hunt12_support import sheet
    from tests.test_status_text import _install

    project = "97000000-0000-0000-0000-000000000002"
    document = sheet([SPHERE])
    _install(tmp_path, project, document)
    table = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    buttons = table.sheet(project)["buttons"]
    if isinstance(buttons, dict):
        buttons = buttons["buttons"]
    choices = [button for button in buttons if button["label"].startswith("Sect Stewardship: choose")]
    assert len(choices) == 3
    for button in choices:
        text = button["description"]
        assert "Sect Checks use that ability's modifier" in text
        assert "You can record this choice only once per fight" in text
        assert "cannot be changed here" in text
        assert "takes no action and costs nothing" in text
        assert "until you change" not in text


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
    combat, table, mid = unchosen_fight(tmp_path, [SPHERE])
    chosen = candidate(combat, mid, lambda c: c.display_name == (PAID_CHECK if paid else SECT_CHECK))
    send_declining(combat, table, mid, chosen)
    engine = reload(tmp_path, mid)
    event = last_check(engine)
    roll = event.payload["actor"]
    assert roll["total"] == roll["natural_result"] + PB + KEY_MOD + event.payload["merit_die"]
    assert held_merit(engine, engine.state.actors[ME]) == PB - int(paid)


@pytest.mark.parametrize("ability,modifier", [("Intelligence", 1), ("Wisdom", 0), ("Charisma", -1)])
@pytest.mark.parametrize("paid", [False, True])
def test_sect_choice_and_complete_reminder_survive_table_reload(tmp_path, monkeypatch, ability, modifier, paid):
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
    combat, table, mid = unchosen_fight(tmp_path, [SPHERE])
    choice = candidate(combat, mid, lambda c: c.display_name == f"Sect Stewardship: choose {ability}")
    assert send(combat, table, mid, choice)["status"] == "COMMITTED"
    engine = reload(tmp_path, mid)
    assert engine.state.actors[ME].action_available, "recording a learning choice costs no combat action"
    assert engine.state.actors[ME].resources[SECT_KEY] == {"Intelligence": 1, "Wisdom": 2, "Charisma": 3}[ability]
    assert type(engine.state.actors[ME].resources[SECT_KEY]) is int
    assert not [c for c in engine.legal_candidates() if c.display_name.startswith("Sect Stewardship: choose")]
    # A new service must use the persisted choice, rather than the original session cache.
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


# --------------------------------------------------------------------------- Petitioning the Hall and its riders
@pytest.mark.parametrize("topic", ["ordinary", "household", "medical"])
def test_petition_costs_one_die_and_reports_a_printed_band(tmp_path, topic):
    '''"spend one Merit Die to petition ... Roll the Merit Die", banded 1-2 / 3-4 / 5+.'''
    combat, table, mid = fight(tmp_path, [SPHERE, RICE_BOWL, MEDICINE_QUEUE])
    start = held_merit(reload(tmp_path, mid), reload(tmp_path, mid).state.actors[ME])
    chosen = candidate(combat, mid, lambda c: str(c.source_definition_id).endswith(f"petition.{topic}"))
    assert send(combat, table, mid, chosen)["status"] == "COMMITTED"
    engine = reload(tmp_path, mid)
    event = last_check(engine)
    assert event.payload["check"] == "Petitioning the Hall"
    assert event.payload["topic"] == topic
    assert held_merit(engine, engine.state.actors[ME]) == start - 1
    number = event.payload["merit_die"]
    assert 1 <= number <= BASE_DIE
    assert petition_band(number) in petition_logs(engine)[-1]


@pytest.mark.parametrize("rolled,read", [(1, 3), (2, 2), (3, 3)])
def test_communal_rice_bowl_replaces_only_a_one(tmp_path, monkeypatch, rolled, read):
    '''"treat a Merit Die result of 1 as a 3": the 1 becomes a 3; a 2 stays a 2 and its band.'''
    force_merit_die(monkeypatch, rolled)
    combat, table, mid = fight(tmp_path, [SPHERE, RICE_BOWL])
    chosen = candidate(combat, mid, lambda c: str(c.source_definition_id).endswith("petition.household"))
    assert send(combat, table, mid, chosen)["status"] == "COMMITTED"
    engine = reload(tmp_path, mid)
    event = last_check(engine)
    assert list(merit_rolls(engine)[0].dice) == [rolled], "the die itself rolled what was forced"
    assert event.payload["one_becomes"] == 3
    assert event.payload["merit_die"] == read, "only the printed 1 is replaced"
    assert event.payload["rolled_twice"] is False
    assert petition_band(read) in petition_logs(engine)[-1]
    if read == 2:
        assert "minimum help" in petition_logs(engine)[-1]


def test_food_lodging_and_clothes_read_a_one_as_a_three(tmp_path, monkeypatch):
    '''The printed benefit, proved through the table and read back from disk: "When you Petition the Hall for food,
    lodging, work clothes, common tools, a bath, or safe storage ... treat a Merit Die result of 1 as a 3".

    A forced 1 on a petition for those requests is the printed 1, so without the rider it would report the
    "minimum help your Standing allows" band. It must read as a 3 and report useful help instead, and the die is
    paid exactly once.
    '''
    force_merit_die(monkeypatch, 1)
    combat, table, mid = fight(tmp_path, [SPHERE, RICE_BOWL])
    start = held_merit(reload(tmp_path, mid), reload(tmp_path, mid).state.actors[ME])
    chosen = candidate(combat, mid, lambda c: str(c.source_definition_id).endswith("petition.household"))
    assert send(combat, table, mid, chosen)["status"] == "COMMITTED"
    engine = reload(tmp_path, mid)
    event = last_check(engine)
    assert list(merit_rolls(engine)[0].dice) == [1], "the printed die rolled a 1"
    assert event.payload["requests"] == ["a meal", "a bed", "work clothes", "common tools for a duty", "a bath",
                                         "a safe place to store your ordinary possessions"], \
        "the request being made is the printed one"
    assert event.payload["one_becomes"] == 3
    assert event.payload["merit_die"] == 3, "a petition for food, lodging or clothes reads its 1 as a 3"
    assert event.payload["useful_help"] is True
    line = petition_logs(engine)[-1]
    assert petition_band(3) in line and "minimum help" not in line
    assert "Communal Rice Bowl" in line, "the log names the printed talent that does this"
    assert held_merit(engine, engine.state.actors[ME]) == start - 1, "one Merit Die paid for it"
    assert len(merit_spent_events(engine, source_ending="petition.household")) == 1


def test_every_covered_request_receives_the_printed_benefit(tmp_path, monkeypatch):
    """Every button a player can press, committed and read back from disk, with the die forced to a 1.

    Communal Rice Bowl's rider is printed for the requested benefit, not for a button's name, so a forced 1 must read
    as a 3 on every button that offers one of the requests it names -- food, lodging, work clothes, common tools, a
    bath, safe storage -- and must stay a 1 on a button offering none of them. Under the routing this replaces, a
    covered request also sat on the ordinary button, which carried no rider: the owner spent the same die and was
    told only the minimum help their Standing allows.
    """
    force_merit_die(monkeypatch, 1)
    combat, table, mid = fight(tmp_path, [SPHERE, RICE_BOWL])
    start = held_merit(reload(tmp_path, mid), reload(tmp_path, mid).state.actors[ME])
    topics = [str(row.source_definition_id).rsplit("petition.", 1)[1]
              for row in reload(tmp_path, mid).legal_candidates() if "petition." in row.source_definition_id]
    assert sorted(topics) == ["household", "ordinary"], "a base steward and a rice-bowl owner have two buttons"
    covered_seen = False
    for topic in topics:
        covers = any(marker in description(combat, mid, f"petition.{topic}") for marker in COVERED_MARKERS)
        covered_seen = covered_seen or covers
        use(combat, table, mid,
            candidate(combat, mid, lambda c: str(c.source_definition_id).endswith(f"petition.{topic}")))
        event = last_check(reload(tmp_path, mid))
        if covers:
            assert event.payload["one_becomes"] == 3, f"petition.{topic} offers a covered request without the 3"
            assert event.payload["merit_die"] == 3, f"petition.{topic} read the printed 1 as a 1"
            assert event.payload["useful_help"] is True
            assert "Communal Rice Bowl" in petition_logs(reload(tmp_path, mid))[-1]
        else:
            assert event.payload["one_becomes"] is None, "a request Rice Bowl does not name carries no replacement"
            assert event.payload["merit_die"] == 1
    assert covered_seen, "no button offered a covered request, so this proved nothing"
    assert held_merit(reload(tmp_path, mid), reload(tmp_path, mid).state.actors[ME]) == start - len(topics), \
        "each button costs exactly one Merit Die"


def test_a_covered_request_is_never_offered_without_its_benefit(tmp_path):
    '''"treat a Merit Die result of 1 as a 3" is printed for the requested benefit, not for a button's name.

    The base rule also offers a meal and safe sleeping space, robes or work clothes, tools and storage, so an owner
    asking the ordinary-help button for one of those must still get the printed 3. The only honest way to offer both is
    to route each covered request onto the button that carries the rider, which is what these buttons do: the
    ordinary line offers none of them and no replacement, the line that has the replacement offers all of them.
    '''
    combat, table, mid = fight(tmp_path, [SPHERE, RICE_BOWL])
    ordinary = description(combat, mid, "petition.ordinary")
    household = description(combat, mid, "petition.household")
    for request in ("a meal", "a bed", "work clothes", "common tools for a duty", "a bath",
                    "a safe place to store your ordinary possessions"):
        assert request in household, f"{request} is on the line that carries the replacement"
    for request in ("a meal", "safe sleeping space", "robes or work clothes", "tools for a duty", "storage"):
        assert request not in ordinary, f"{request} is a covered request and must not be on a line without the 3"
    assert "A roll of 1 counts as a 3 (Communal Rice Bowl)" in household
    assert "counts as a 3" not in ordinary


def test_the_ordinary_line_still_answers_the_requests_rice_bowl_does_not_name(tmp_path, monkeypatch):
    '''Rice Bowl names food, lodging, clothes, tools, a bath and safe storage. A public hall, a map, an introduction,
    public notices, a shared room and a receipt are not named, so that line's die is read as rolled.'''
    force_merit_die(monkeypatch, 1)
    combat, table, mid = fight(tmp_path, [SPHERE, RICE_BOWL])
    chosen = candidate(combat, mid, lambda c: str(c.source_definition_id).endswith("petition.ordinary"))
    send(combat, table, mid, chosen)
    event = last_check(reload(tmp_path, mid))
    assert event.payload["one_becomes"] is None
    assert event.payload["merit_die"] == 1, "a petition for a public hall or a map reads a 1 as a 1"
    assert event.payload["talents"] == []
    assert "minimum help" in petition_logs(reload(tmp_path, mid))[-1]


def test_every_printed_request_is_offered_exactly_once(tmp_path):
    """Routing must neither drop a printed request nor offer it on two buttons that answer it differently."""
    for case, talents in enumerate(([], [RICE_BOWL], [MEDICINE_QUEUE], [RICE_BOWL, MEDICINE_QUEUE])):
        # One fight per case: a match id is derived from the sheet, so two different sheets cannot share a directory.
        case_dir = tmp_path / f"case{case}"
        combat, table, mid = fight(case_dir, [SPHERE, *talents])
        groups = petition_groups(frozenset(talents))
        labels, requests = [], []
        for group in groups:
            labels.append(group.label)
            requests.extend(group.texts)
            text = description(combat, mid, f"petition.{group.topic}")
            for request in group.texts:
                assert request in text, "the button says what it is asking for"
        assert len(labels) == len(set(labels)), f"two buttons share a name: {labels}"
        assert len(requests) == len(set(requests)), f"a request is offered twice: {requests}"
        covered = {request.text for rider in PETITION_TALENTS if rider.feature_id in talents
                   for request in rider.requests}
        assert covered <= set(requests), "a talent's own printed requests are all offered"
    # A character with no such talent gets the base rule's whole list on the single ordinary button.
    combat, table, mid = fight(tmp_path / "base", [SPHERE])
    assert not [row for row in reload(tmp_path / "base", mid).legal_candidates()
                if "petition." in row.source_definition_id and "petition.ordinary" not in row.source_definition_id]


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
def test_each_ownership_offers_exactly_the_printed_requests(tmp_path, case):
    '''Every ownership combination gets exactly the printed buttons, checked against the lists written above.

    Nothing here is read from the plug-in's request tables, so a printed request dropped from ``BASE_REQUESTS``, or an
    uncovered base request misrouted onto a rider's button, fails this test instead of quietly taking an option away
    from the player. All four combinations are covered because they are the only four a sheet can produce: neither
    talent, Rice Bowl only, Medicine Hall Queue only, and both.
    '''
    talents = OWNERSHIP_CASES[case]
    combat, table, mid = fight(tmp_path, [SPHERE, *talents])
    expected = EXPECTED_MENUS[case]
    topics = [entry[0] for entry in expected]
    assert offered_petition_topics(reload(tmp_path, mid)) == sorted(topics), \
        f"the table offers exactly {sorted(topics)} and nothing else"
    rows = petition_rows(combat, mid)
    assert sorted(rows) == sorted(topics), f"the catalog compiles exactly {sorted(topics)} and nothing else"
    for topic, label, requests, talent_names, one_becomes, twice in expected:
        row = rows[topic]
        assert row.display_name == label, f"the {topic} button is named for what it buys"
        effect = row.parameters["typed"]["effects"][0]
        assert tuple(effect["requests"]) == requests, \
            f"the {topic} button offers the printed requests, in the printed order, none dropped and none invented"
        assert tuple(effect["talents"]) == talent_names, f"the {topic} button names its printed talents"
        assert effect.get("one_becomes") == one_becomes, f"the {topic} button's printed change to a 1"
        assert bool(effect.get("twice", False)) == twice, f"the {topic} button's printed double roll"
        text = str(row.parameters.get("description") or "")
        for request in requests:
            assert request in text, f"the {topic} button says out loud that it is asking for {request!r}"


def test_common_tools_ride_the_line_that_carries_the_replacement(tmp_path):
    '''"food, lodging, work clothes, common tools, a bath, or safe storage": tools ride the line that carries the
    replacement, so an owner's ordinary line does not offer them either.'''
    combat, table, mid = fight(tmp_path, [SPHERE, RICE_BOWL])
    assert "common tools for a duty" in description(combat, mid, "petition.household")
    assert "tools for a duty" not in description(combat, mid, "petition.ordinary")


def test_the_base_rule_still_offers_ordinary_tools_to_anyone(tmp_path):
    """"mundane tools for a duty" is on the base rule's own list of common petitions."""
    combat, table, mid = fight(tmp_path, [SPHERE])
    assert "mundane tools for a duty" in description(combat, mid, "petition.ordinary")
    assert "temporary storage for ordinary goods" in description(combat, mid, "petition.ordinary"), \
        "the printed list also grants temporary storage"
    assert not [row for row in reload(tmp_path, mid).legal_candidates()
                if "petition.household" in row.source_definition_id], "and no household line without the talent"


def test_medicine_hall_queue_rolls_twice_and_keeps_the_higher(tmp_path, monkeypatch):
    '''"roll your Merit Die twice and use the higher result", only on the medical petition.'''
    force_merit_die(monkeypatch, 1, 4)
    combat, table, mid = fight(tmp_path, [SPHERE, MEDICINE_QUEUE])
    chosen = candidate(combat, mid, lambda c: str(c.source_definition_id).endswith("petition.medical"))
    send(combat, table, mid, chosen)
    engine = reload(tmp_path, mid)
    event = last_check(engine)
    rolled = merit_rolls(engine)
    assert len(rolled) == 1 and list(rolled[0].dice) == [1, 4], "two real dice were rolled"
    assert event.payload["rolled_twice"] is True
    assert event.payload["merit_die"] == 4 == max(rolled[0].dice)
    assert "rolled twice" in petition_logs(engine)[-1]


def test_medicine_hall_queue_does_not_touch_an_ordinary_petition(tmp_path):
    """The double roll is printed for a medical petition, not for every petition."""
    combat, table, mid = fight(tmp_path, [SPHERE, MEDICINE_QUEUE])
    chosen = candidate(combat, mid, lambda c: str(c.source_definition_id).endswith("petition.ordinary"))
    send(combat, table, mid, chosen)
    engine = reload(tmp_path, mid)
    assert last_check(engine).payload["rolled_twice"] is False
    assert len(merit_rolls(engine)[0].dice) == 1


def test_the_built_in_ai_is_never_offered_one_of_these_lines(tmp_path):
    """These are institutional requests with no fight-time Difficulty and no target, so they are ``player_only``: the
    built-in AI's context filters those out (combat/gate4_context.py), and the earlier report's claim that "an AI
    fighter takes the paid line whenever it holds a die" was never true.
    """
    combat, table, mid = fight(tmp_path, [SPHERE, RICE_BOWL, MEDICINE_QUEUE, CONTRIBUTION, DEPARTMENT])
    engine = reload(tmp_path, mid)
    policy = PolicyLibrary(ROOT).for_actor(ME)[0]

    def mine(rows):
        return [row.source_definition_id for row in rows
                if "sect_check" in row.source_definition_id or "petition" in row.source_definition_id
                or row.source_definition_id.endswith(".reduce")]

    # The table's own player context passes include_item_actions (combat/gate5_service.py:2830); the AI's does not.
    assert mine(build_decision_context(engine, policy, include_item_actions=True).legal_candidates)
    assert not mine(build_decision_context(engine, policy, for_ai=True).legal_candidates), "the AI's menu has none"


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
