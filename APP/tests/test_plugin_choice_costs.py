"""A choice prompt must quote the payment the table makes for that choice -- and only its own.

Two different payments meet at a choice prompt, and the round-2 fix for "Cost now: none"
confused them. The *enclosing action's* price is already committed: it is charged whether or
not the choice is answered. The *choice's own* price is what answering spends (Bloodletting
Strike's 1 Cultivation Point). Reading one number for both made a 1-point rider advertise the
attacking action's 2 Stamina, and choosing "Not now" does not refund the attack.

So every price now comes from one shared quote (combat/ext/choice_costs.py), used by all three
ways a choice can cost something:

* a choice with no payment of its own quotes the action it rides (Spinning Shot's target pick
  commits the Barrage's Martial Focus) -- ext.needle.ask;
* a plug-in that pays for itself states one Payment, quoted and spent by the same object
  (Bloodletting Strike, Crimson Feast);
* a substituted payment quotes the amount being covered, leaving each option's own price to
  its label (Blood Armor's Crimson Sacrifice, which pays HP for Stamina).

Coverage below is per kind, at the table where the bug showed, plus a fresh-service reload and
the paid/skip pair for a rider.
"""
import json
import re
from pathlib import Path

import pytest

from combat.ext.choice_costs import Payment, covering, quote, separating
from combat.ext.needle import riding_cost
from tests.test_c10_review_fixup import PREFIX, make_table, end_until_hero, reload_check

SPINNING = "TAL_BARRAGE_SPINNING_SHOT"
BARRAGE_SPHERE = "tianxia.sphere.barrage"
BLOOD_SPHERE = "tianxia.sphere.blood"
FOCUS = "resource:core.martial_focus"
QI = "resource:core.qi"
BL = "tianxia.talent.blood."
BOW = "Gong Jian (Bow and Arrow)"
HERO = PREFIX + "aaaaaaaa"


# ------------------------------------------------------------------------------ kind 1: the action the choice rides
def test_spinning_shot_choice_prompt_names_the_martial_focus_the_table_spends(tmp_path, monkeypatch):
    """Table level: the prompt says what accepting commits, and the table charges exactly that."""
    service, table, mid = make_table(tmp_path, [SPINNING], BARRAGE_SPHERE, "MANUAL", foes=3, body=True)
    end_until_hero(table, mid)
    before = reload_check(service, mid).state.actors[HERO].resources[FOCUS]

    prompts = _act(service, table, mid, f"Barrage: {BOW} + Spinning Shot")

    assert len(prompts) == 1
    prompt = prompts[0]
    assert prompt["reaction"] == "Spinning Shot"
    # What the player is told, in words a player who knows only basic D&D can read.
    assert prompt["cost"] == "1 Martial Focus"
    assert prompt["title"] == "Spinning Shot"  # an Action choice, not a Reaction
    # ...and exactly that is what the table charges: one Martial Focus and nothing else.
    # Every payment this decision caused, not just the one the bug was about.
    engine = reload_check(service, mid)
    spent = [(e.payload.get("resource_id"), e.payload["amount"], e.payload["remaining"]) for e in engine.events
             if e.event_type == "RESOURCE_SPENT" and e.actor_id == HERO]
    assert spent == [(FOCUS, 1, 0)]
    assert before == 1 and engine.state.actors[HERO].resources[FOCUS] == 0


def test_a_free_choice_still_reports_no_cost(tmp_path, monkeypatch):
    """The Spinning Shot Bonus Action itself is free, so its own choice must keep saying none."""
    service, table, mid = make_table(tmp_path, [SPINNING], BARRAGE_SPHERE, "MANUAL", foes=4, body=True)
    end_until_hero(table, mid)
    _act(service, table, mid, f"Barrage: {BOW} + Spinning Shot")

    prompts = _act(service, table, mid, f"Spinning Shot: {BOW}")

    assert len(prompts) == 1
    assert prompts[0]["reaction"] == "Spinning Shot"
    assert prompts[0]["cost"] == "none"


# ------------------------------------------------------------------------------ kind 2: the choice pays for itself
def test_bloodletting_quotes_its_own_point_not_the_triggering_action_price(tmp_path, monkeypatch):
    """A rider's own 1 CP, quoted as its own -- never the price of the action that raised it.

    Before the fix this prompt inherited the enclosing action's cost, so a choice spending 1
    point could advertise a dearer action and "Not now" still left the action paid.
    """
    service, table, mid = _bleeder_table(tmp_path)
    engine = reload_check(service, mid)
    before = {pool: engine.state.actors[HERO].resources[pool] for pool in (QI, FOCUS)}

    prompts = _act(service, table, mid, "Blood Thread", pick="bloodletting")

    assert len(prompts) == 1
    prompt = prompts[0]
    assert prompt["reaction"] == "Bloodletting Strike"
    # The rider's own price, leading the line, on its own.
    assert prompt["cost"] == "1 Qi"
    # ...and the table charges exactly the point it named, and nothing else.
    engine = reload_check(service, mid)
    spent = [(e.payload.get("resource_id"), e.payload["amount"]) for e in engine.events
             if e.event_type == "RESOURCE_SPENT" and e.actor_id == HERO]
    assert spent == [(QI, 1)]
    assert engine.state.actors[HERO].resources[QI] == before[QI] - 1


def test_skipping_a_rider_charges_only_the_action_it_rode(tmp_path, monkeypatch):
    """"Not now" must cost the rider nothing; the action it rode keeps whatever it cost."""
    service, table, mid = _bleeder_table(tmp_path)
    _act(service, table, mid, "Blood Thread", pick="skip")

    engine = reload_check(service, mid)
    spent = [(e.payload.get("resource_id"), e.payload["amount"]) for e in engine.events
             if e.event_type == "RESOURCE_SPENT" and e.actor_id == HERO]
    # The Blood Thread action itself is free in this build, so declining the rider spends nothing.
    assert spent == []
    assert not any(c.condition_id.startswith("condition:typed.bloodletting")
                   for c in engine.state.actors[PREFIX + "00000001"].conditions.values())


# ------------------------------------------------------------- a rider on a *paid* action, at the table
def _paid_thread_table(tmp_path, monkeypatch, amount):
    """A Blood cultivator whose Blood Thread really costs ``amount`` Qi, compiled and at the table.

    Blood Thread and every stock weapon attack compile free in this build, so on a stock table the
    rider's own point is the *only* price in play and the defect under repair cannot show at all: any
    quote that merely repeated the rider's price would pass. Paying the action forces the two payments
    to coexist, which is the case a player actually has to read.

    The price is set in the typed authority the compiler reads (``TYPED_AUTHORITY`` is resolved at call
    time), so the cost is compiled into the persisted action bundle exactly as a printed cost would be
    -- every later reload, the spending code and the replay all see the same charged figure. Nothing is
    patched onto a live engine or a core class.
    """
    import combat.factory_compiler as compiler

    document = json.loads(Path(compiler.TYPED_AUTHORITY).read_text(encoding="utf-8"))
    # Printed costs are a list of payment alternatives, each a list of parts.
    document["mechanics"]["BLOOD_BASE_BLOOD_THREAD"]["cost"] = [[{"resource": "qi", "amount": amount}]]
    authority = tmp_path / f"authority_thread_costs_{amount}.json"
    authority.write_text(json.dumps(document), encoding="utf-8")
    monkeypatch.setattr(compiler, "TYPED_AUTHORITY", authority)

    service, table, mid = _bleeder_table(tmp_path)
    return service, table, mid


def _qi_spends(service, mid):
    """Every Qi this hero has been charged, in the order the table charged it."""
    return [e.payload["amount"] for e in reload_check(service, mid).events
            if e.event_type == "RESOURCE_SPENT" and e.actor_id == HERO and e.payload.get("resource_id") == QI]


def test_accepting_a_rider_on_a_paid_action_charges_the_action_and_the_rider_both(tmp_path, monkeypatch):
    """Two payments, two entries in the ledger: the paid attack's Qi and the rider's own Qi."""
    service, table, mid = _paid_thread_table(tmp_path, monkeypatch, 2)
    before = reload_check(service, mid).state.actors[HERO].resources[QI]

    prompts = _act(service, table, mid, "Blood Thread", pick="bloodletting")

    # The prompt names both prices, each one saying which payment it is.
    assert len(prompts) == 1
    assert prompts[0]["cost"] == ("1 Qi to answer this choice; "
                                  "the action you are already paying for costs 2 Qi separately")
    # ...and the table charged both: 2 for the attack it rides, 1 for answering the choice.
    assert _qi_spends(service, mid) == [2, 1]
    assert reload_check(service, mid).state.actors[HERO].resources[QI] == before - 3


def test_skipping_a_rider_on_a_paid_action_charges_the_action_but_not_the_rider(tmp_path, monkeypatch):
    """"Not now" cannot refund the attack: the action is still paid, the rider is not.

    The same fixture as the accept case, so the only difference is the answer. A prompt that quoted a
    single blended figure would satisfy one arm and lie in the other.
    """
    service, table, mid = _paid_thread_table(tmp_path, monkeypatch, 2)
    before = reload_check(service, mid).state.actors[HERO].resources[QI]

    prompts = _act(service, table, mid, "Blood Thread", pick="skip")

    # The price the player was shown is still both prices, even when declining.
    assert prompts[0]["cost"] == ("1 Qi to answer this choice; "
                                  "the action you are already paying for costs 2 Qi separately")
    # Declining spends the action's 2 Qi and nothing else; the rider's 1 Qi was never charged.
    assert _qi_spends(service, mid) == [2]
    assert reload_check(service, mid).state.actors[HERO].resources[QI] == before - 2
    assert not any(c.condition_id.startswith("condition:typed.bloodletting")
                   for c in reload_check(service, mid).state.actors[PREFIX + "00000001"].conditions.values())


def test_two_payments_of_the_same_price_are_still_two_payments(tmp_path, monkeypatch):
    """The equal-price case, at the table: a 1 Qi action and a 1 Qi rider, from the same pool.

    Matching numbers make this the easiest prompt to get wrong -- and the least acceptable to get wrong,
    because the two payments are indistinguishable from the figure alone while actually behaving
    differently: accepting spends 2 Qi, declining spends 1. Naming one number for both promises a total
    that no answer produces, which is the collapse this case exists to prevent.
    """
    service, table, mid = _paid_thread_table(tmp_path, monkeypatch, 1)
    before = reload_check(service, mid).state.actors[HERO].resources[QI]

    prompts = _act(service, table, mid, "Blood Thread", pick="bloodletting")

    # Both are spelled "1 Qi", and both are still named separately.
    assert prompts[0]["cost"] == ("1 Qi to answer this choice; "
                                  "the action you are already paying for costs 1 Qi separately")
    assert prompts[0]["cost"].count("1 Qi") == 2
    # Accepting spends both of them; the ledger shows two separate charges, not one merged one.
    assert _qi_spends(service, mid) == [1, 1]
    assert reload_check(service, mid).state.actors[HERO].resources[QI] == before - 2


def test_an_equal_price_rider_declined_still_pays_only_the_action(tmp_path, monkeypatch):
    """The other arm of the equal-price case: 1 Qi declined, not 2."""
    service, table, mid = _paid_thread_table(tmp_path, monkeypatch, 1)
    before = reload_check(service, mid).state.actors[HERO].resources[QI]

    prompts = _act(service, table, mid, "Blood Thread", pick="skip")

    assert prompts[0]["cost"] == ("1 Qi to answer this choice; "
                                  "the action you are already paying for costs 1 Qi separately")
    assert _qi_spends(service, mid) == [1]
    assert reload_check(service, mid).state.actors[HERO].resources[QI] == before - 1


# ------------------------------------------------------------- Crimson Feast, whose prompt quotes its own 2 CP
def _bloodied_and_threaded(engine, owner_id, target_id):
    """Leave the target Bloodied and wearing the owner's Blood Thread, through committed events.

    Crimson Feast is offered when a hit lands on a Bloodied creature bearing your Thread. A Thread a
    Blood Thread really plants is applied *after* that Thread's own damage, and lapses at the start of
    your next turn -- so a Thread the table placed that way is never on the target at the moment damage
    is dealt, and the trigger is unreachable by attacking twice. Setting the state up inside a committed
    action is the only way to present the table with the position the printed trigger describes.

    The wound goes through ``_commit_damage`` so it is a real event: the committed fight reloads and
    replays to the identical state, exactly as any damage at the table does.
    """
    import tests.test_riders_c5 as C

    owner, target = engine.state.actors[owner_id], engine.state.actors[target_id]
    C._thread(engine, owner, target)
    engine._commit_damage(target, max(1, target.current_hp - target.maximum_hp // 2), "FORCE", "test:wound",
                          owner.entity_id, None, reaction_depth=0)


def _feast_table(tmp_path, monkeypatch):
    """A Blood cultivator who owns Crimson Feast at a table with a Bloodied, threaded foe."""
    from tests.test_c5_review import _table, _act
    from tests.test_tabletop_hunt6 import on_hold
    import tests.test_riders_c5 as C

    # cp=3 puts 3 Stamina on this fighter: Stamina is this character's cultivation-point pool.
    combat, table, mid = _table(tmp_path, [C.BL + "crimson_feast"], spheres=("tianxia.sphere.blood",), cp=3, hp=60)
    with monkeypatch.context() as setup:
        on_hold(setup, lambda engine: _bloodied_and_threaded(engine, C.ME, C.AN))
        _act(combat, table, mid, "Hold position")
    return combat, table, mid, C, _act


def _feast_prompts(prompts):
    return [p for p in prompts if p["context"]["reaction_source_id"] == "choice:needle.crimson_feast"]


def test_crimson_feast_prompt_names_its_own_two_point_price_and_the_table_charges_it(tmp_path, monkeypatch):
    """The 2 CP the menu offers is a second payment, and it is the one the table takes.

    test_riders_c5 covers Crimson Feast's spending and healing, but it never looked at the prompt, so it
    would still pass with the price removed and the menu reading "none" while quietly charging 2. Here
    the quote and the charge are checked against each other: the prompt names the price, the ledger
    records that same price, and the balance moves by exactly that much.
    """
    import tests.test_riders_c5 as C

    combat, table, mid, C5, act = _feast_table(tmp_path, monkeypatch)

    engine, prompts = act(combat, table, mid, "Blood Thread", target=C.AN)

    asked = _feast_prompts(prompts)
    assert len(asked) == 1, "Crimson Feast was never offered on a Bloodied, threaded foe"
    # The 2 cultivation points this character spends: Stamina is its cultivation-point pool here.
    assert asked[0]["cost"] == "2 Stamina"
    # The words and the charge are the same number: 2 Stamina spent, nothing else.
    spent = [(e.payload.get("resource_id"), e.payload["amount"]) for e in engine.events
             if e.event_type == "RESOURCE_SPENT" and e.actor_id == C.ME]
    assert spent == [("resource:core.stamina", 2)]
    assert engine.state.actors[C.ME].resources["resource:core.stamina"] == 1


def test_declining_crimson_feast_spends_nothing_but_is_still_asked_with_its_price(tmp_path, monkeypatch):
    """"Not now" spends no cultivation points, while the attack that raised the prompt is still paid.

    The armed case for the price being read as the action's: the Blood Thread here is free, so the only
    thing the prompt could ever be quoting is the feast's own 2 points -- and declining must not charge them.
    """
    import tests.test_riders_c5 as C

    combat, table, mid, C5, act = _feast_table(tmp_path, monkeypatch)

    engine, prompts = act(combat, table, mid, "Blood Thread", target=C.AN,
                          choices={"crimson_feast": lambda options: [o for o in options if o.endswith("skip")]})

    asked = _feast_prompts(prompts)
    assert asked, "Crimson Feast was never offered on a Bloodied, threaded foe"
    # A Thread landing on an already-Bloodied target deals a second hit (the printed "if Bloodied,
    # add your Proficiency Bonus" damage), so declining can be offered more than once -- only *taking*
    # it sets the once-per-turn flag. Every one of those offers names the same price.
    assert {p["cost"] for p in asked} == {"2 Stamina"}
    # Declined: the prompt named a price, and no cultivation points left the character.
    assert not [e for e in engine.events if e.event_type == "RESOURCE_SPENT" and e.actor_id == C.ME]
    assert engine.state.actors[C.ME].resources["resource:core.stamina"] == 3


# ------------------------------------------------------------------------------ kind 3: a substituted payment
def _covered_amount(header):
    """The number and pool a substitution header names, read back out of the header's own wording."""
    from combat.factory_compiler import RESOURCE_IDS

    match = re.fullmatch(r"(\d+) ([A-Za-z ]+?) to cover; each option below states what paying it costs you", header)
    assert match, f"the header no longer names the amount it covers: {header!r}"
    return int(match.group(1)), RESOURCE_IDS[match.group(2).strip().lower()]


def _option_price(label):
    """The HP an option says it will cost, and the amount it says that covers."""
    match = re.search(r"pay (\d+) HP", label)
    covered = re.search(r"to cover (\d+) ([A-Za-z ]+)", label)
    assert match and covered, f"option no longer states its own price: {label!r}"
    return int(match.group(1)), int(covered.group(1))


def test_hp_substitution_menu_quotes_the_amount_it_covers(tmp_path, monkeypatch):
    """Crimson Sacrifice pays HP for Cultivation Points the fighter lacks: the menu must not read "none".

    Hunt 69 H69-16 recorded this prompt with cost "none" while its own option read
    "Crimson Sacrifice: pay 15 HP ... to cover 3 Stamina". The header now names the amount
    being covered and leaves the price actually paid to each option's label.

    The numbers are tied to each other here, not merely present. A header that named the wrong
    shortfall, or an "HP really was paid" claim that did not match the HP the fighter actually lost,
    would both pass a test that only looked for the words "to cover" and "Stamina"; neither survives
    being compared against the committed payment.
    """
    from tests.test_c5_review import _table, _act
    from tests.test_tabletop_hunt6 import on_hold
    import tests.test_riders_c5 as C

    combat, table, mid = _table(tmp_path, [C.BL + "heart_seizing_grip"], spheres=("tianxia.sphere.blood",), cp=3, hp=60)
    with monkeypatch.context() as setup:
        on_hold(setup, lambda engine: C._thread(engine, engine.state.actors[C.ME], engine.state.actors[C.AN]))
        _act(combat, table, mid, "Hold position")
    hp_before = combat._load_session(mid).engine.state.actors[C.ME].current_hp
    _act(combat, table, mid, "End turn")
    _act(combat, table, mid, "End turn")
    # Declaring Crimson Sacrifice is what offers the grip for a fighter short of its 6 CP.
    _act(combat, table, mid, "Crimson Sacrifice: pay all the CP you may with HP")
    engine, prompts = _act(combat, table, mid, "Heart-Seizing Grip", target=C.AN)

    asked = [p for p in prompts if p["context"]["reaction_source_id"] == "choice:alternative_payment"]
    assert len(asked) == 1, "the shortfall menu was never raised"
    cost = asked[0]["cost"]
    # The amount being covered, named in the header -- not the literal "none".
    assert cost and cost != "none", f"the payment menu still reads {cost!r}"
    covered_amount, covered_pool = _covered_amount(cost)
    assert covered_amount > 0, "a menu that covers nothing still asks to be paid"

    # The price actually paid is the option's own business, and it is still stated there.
    options = asked[0]["choice"]["options"]
    commits = [e for e in engine.events if e.event_type == "ALTERNATIVE_PAYMENT_COMMITTED"]
    assert len(commits) == 1, "the alternative payment was never committed"
    committed = commits[0].payload
    chosen = [o for o in options if o.get("label", "") in committed["log"]]
    assert len(chosen) == 1, "the committed payment is not one of the options the player was shown"
    hp_quoted, option_covered = _option_price(chosen[0]["label"])

    # The option covers the same amount the header promised, so the two are one price seen twice.
    assert option_covered == covered_amount
    # The table covered exactly the pool and amount the header named, and paid exactly the HP the
    # option quoted -- not merely "some HP".
    assert committed["covered"] == {covered_pool: covered_amount}
    assert committed["hp_paid"] == hp_quoted
    assert committed["hp_before"] - committed["hp_after"] == hp_quoted
    # And the fighter's own body agrees: the HP that left the character is the HP the option named.
    hero = engine.state.actors[C.ME]
    assert hp_before - hero.current_hp == hp_quoted


# ------------------------------------------------------------------------------ one quote, kept apart from the action
@pytest.mark.parametrize("action_cost,own_cost,expected", [
    ("2 Stamina", "1 Qi", "1 Qi to answer this choice; the action you are already paying for costs 2 Stamina separately"),
    ("2 Stamina", "", "2 Stamina"),          # the choice pays nothing: the action's price is the answer
    ("", "1 Qi", "1 Qi"),                    # a free action stays free and the rider still names its point
    # The same number twice is still two payments: accepting spends both, declining spends one.
    ("1 Stamina", "1 Stamina", "1 Stamina to answer this choice; the action you are already paying for costs 1 Stamina separately"),
    ("", "", ""),
])
def test_separating_keeps_a_choice_price_apart_from_its_action_price(action_cost, own_cost, expected):
    """The review's exact case: a 1-point rider after a 2-Stamina attack, in plain words."""
    assert separating(action_cost, own_cost) == expected


def test_quote_uses_the_tables_own_cost_wording():
    """One formatter for every price, so a prompt cannot invent a phrasing the sheet lacks."""
    from combat.decision_text import costs_text

    costs = (("resource:core.stamina", 2), ("resource:core.qi", 1))
    assert quote(costs) == costs_text(costs) == "2 Stamina + 1 Qi"
    assert quote(()) == "" and covering(()) == ""
    assert Payment(QI, 1).quote() == "1 Qi" and Payment(QI, 1).context() == {"cost": "1 Qi", "paying_pool": QI}


@pytest.mark.parametrize("chooser,expected", [("a", "2 Stamina"), ("b", "")])
def test_only_the_action_owner_is_charged_the_running_action_cost(chooser, expected):
    """A choice riding someone else's action must not inherit that action's cost.

    This is what keeps a reactor's Ask-me menu from quoting the attacker's price.
    """
    from types import SimpleNamespace

    action = SimpleNamespace(owner_id="a", costs=(("resource:core.stamina", 2),))
    engine = SimpleNamespace(_active_action_source_id="action:x", action_catalog={"action:x": action})
    assert riding_cost(engine, SimpleNamespace(entity_id=chooser)) == expected
    # A choice with no action under it, and one whose action is unknown, both stay silent.
    quiet = SimpleNamespace(_active_action_source_id=None, action_catalog={"action:x": action})
    assert riding_cost(quiet, SimpleNamespace(entity_id=chooser)) == ""
    unknown = SimpleNamespace(_active_action_source_id="action:gone", action_catalog={})
    assert riding_cost(unknown, SimpleNamespace(entity_id=chooser)) == ""
    free = SimpleNamespace(_active_action_source_id="action:x",
                           action_catalog={"action:x": SimpleNamespace(owner_id="a", costs=())})
    assert riding_cost(free, SimpleNamespace(entity_id="a")) == ""


# ------------------------------------------------------------------------------ the quote is a string, and survives a fresh service
def test_a_pending_prompt_rebuilds_itself_from_saved_state_at_the_same_cost(tmp_path, monkeypatch):
    """A brand-new service loads the saved fight and re-raises the prompt at the same price.

    The quote is written into the choice's persisted trigger as a string, so a cold reload has
    to rebuild the identical prompt. test_prompt_ui.py's reload check only covers an explicitly
    free prompt, which would pass whether or not this fallback exists.
    """
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from tests.test_riders_c10 import ROOT

    service, table, mid = make_table(tmp_path, [SPINNING], BARRAGE_SPHERE, "MANUAL", foes=3, body=True)
    end_until_hero(table, mid)
    state = table.state(mid)
    engine = service._load_session(mid).engine
    candidate = next(c for c in engine.legal_candidates() if c.display_name == f"Barrage: {BOW} + Spinning Shot")
    ids = (candidate.candidate_id, candidate.decision_id, candidate.state_version)
    pending = table.act(mid, *ids, state["last_sequence"], [])
    assert pending["status"] == "REACTION_REQUIRED"
    assert pending["reaction"]["cost"] == "1 Martial Focus"

    # A second service and table over the same saved directory: nothing is carried in memory.
    fresh_service = CombatService(ROOT, tmp_path)
    fresh = TabletopService(fresh_service, tmp_path)
    reloaded = fresh.act(mid, *ids, fresh.state(mid)["last_sequence"], [])

    assert reloaded["status"] == "REACTION_REQUIRED"
    assert reloaded["reaction"]["reaction"] == "Spinning Shot"
    assert reloaded["reaction"]["cost"] == pending["reaction"]["cost"] == "1 Martial Focus"
    # The whole prompt, not just its price, is rebuilt from the saved choice trigger.
    assert reloaded["reaction"]["context"] == pending["reaction"]["context"]


# ------------------------------------------------------------------------------ helpers
def _bleeder_table(tmp_path):
    """A Blood cultivator with Bloodletting Strike at the table, in MANUAL control."""
    service, table, mid = make_table(tmp_path, ["BLOOD_BASE_BLOOD_THREAD", BL + "bloodletting_strike"],
                                     BLOOD_SPHERE, "MANUAL", foes=2, body=True)
    end_until_hero(table, mid)
    return service, table, mid


def _pending_prompt(table, state):
    """The choice the table is waiting on, read from its own menu payload."""
    for group in state["menu"].get("actions", []):
        for option in group.get("options", []):
            if option.get("reaction"):
                return option["reaction"]
    return None


def _act(service, table, mid, name, pick=None):
    """Play ``name``; answer each Ask-me prompt with ``pick`` (its id, else the first option)."""
    state = table.state(mid)
    engine = service._load_session(mid).engine
    candidate = next(c for c in engine.legal_candidates() if c.display_name == name)
    prompts = []
    for _ in range(10):
        result = table.act(mid, candidate.candidate_id, candidate.decision_id, candidate.state_version,
                           state["last_sequence"], [])
        if result["status"] != "REACTION_REQUIRED":
            assert result["status"] == "COMMITTED", result
            return prompts
        reaction = result["reaction"]
        prompts.append(reaction)
        options = reaction.get("choice", {}).get("options", [])
        chosen = next((o for o in options if str(o.get("id")).endswith(str(pick))), options[0] if options else None)
        result = table.act(mid, candidate.candidate_id, candidate.decision_id, candidate.state_version,
                           result["state"]["last_sequence"],
                           [{**reaction["context"], "selection": "USE" if chosen else "DECLINE",
                             "option_ids": [chosen["id"]] if chosen else []}])
        state = result["state"]
        if result["status"] == "COMMITTED":
            return prompts
    raise AssertionError(f"unresolved prompts for {name}")
