"""A summon button must not print a resource cost its own action never charges (HUNT 114 finding 3).

At the table on 2026-10-04 Jia Fengshan's Grave Formation offered "Grave Assault" described as
"**Cost: 8 CP**" (the Legion's as "**Cost: 15 CP**"), and the attack plainly ran -- with no
``RESOURCE_SPENT`` anywhere in the journal.  Every button about a summoned creature is built from the
rules text of the ability that *called it out*, so that ability's printed cost was shown on the
creature's own attack: 39 of the 43 summon-creature actions in ``combat/rules/summons.json``.

Owner text first.  ``combat/rules/summons.json`` note: "``sources`` says which ability brings which
creature: arrives ``start`` (already with the summoner when the fight begins: rituals that last until
destroyed, a manifested spirit, tamed beasts) or ``action`` (the ability itself calls it mid-fight)."
Grave Formation (``authority/typed_mechanics/rules_text.json``) prints "Action Type: Ritual Procedure
/ Timing Detail: Ritual / Time: 1 hour / Duration: 24 hours, or until the formation is destroyed or
dismissed / Cost: 8 CP" and its own rider "A single command causes it to take one action from its stat
block"; the printed Grave Assault entry in that stat block prints no cost.  So the printed cost is paid
once, and an action the creature takes is an entry of its own stat block, not another use of the
ability.  ``combat/ext/summon_ability_costs.py`` encodes exactly that.

These are real persisted tables, played as a player through ``TabletopService``.
"""
from combat.canonical import canonical_sha256
from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests.hunt23_support import act, fight

SUMMONER, FOE = "actor:factory.h15-left", "actor:factory.h15-right"
SERVANT, GRAVE = "TAL_DEATH_CORPSE_SERVANT", "TAL_DEATH_GRAVE_FORMATION"
BEAST = "tianxia.talent.ink.painted_beast"


def _table(tmp_path, talents, *, near=(4, 6)):
    """A real table: the necro stands next to a foe whose Armor Class is 1, so any roll hits."""
    def unarmoured(bundle):
        if bundle["actor_id"] == FOE:
            bundle["actor_template"]["armor_class"] = 1

    return fight(tmp_path, list(talents), prepare_bundle=unarmoured,
                 positions={SUMMONER: {"x": near[0], "y": near[1]}, FOE: {"x": near[0] + 2, "y": near[1]}})


def _engine(combat, mid):
    return combat._load_session(mid).engine


def _saved_digest(combat, mid):
    """The bytes a saved fight keeps. Reading the table must not move them."""
    return canonical_sha256(_engine(combat, mid).state.model_dump(mode="json"))


def _summoner(combat, mid):
    return _engine(combat, mid).state.actors[SUMMONER]


def _summon(combat, mid, group):
    return next(actor for actor in _engine(combat, mid).state.actors.values()
                if (actor.summon or {}).get("group") == group)


def _button(table, mid):
    """The buttons the table is showing the current actor right now."""
    return {group["label"]: group for group in table.state(mid)["menu"]["actions"]}


def _turn(table, mid, actor_id, limit=6):
    """Wait for a creature's own turn the way a player does: end turns until it arrives."""
    for _ in range(limit):
        if table.state(mid)["menu"].get("actor_id") == actor_id:
            return
        assert act(table, mid, "end")["status"] == "COMMITTED"
    raise AssertionError(f"{actor_id} never took a turn")


def _command_and_wait(table, mid, group, label):
    """The summoner spends the Bonus Action that commands the group, then the creature acts."""
    for _ in range(6):
        buttons = _button(table, mid)
        if table.state(mid)["menu"].get("actor_id") == _summon(table.combat, mid, group).entity_id:
            return buttons[label]
        commands = sorted(name for name in buttons if name.startswith("Command "))
        if table.state(mid)["menu"].get("actor_id") == SUMMONER and commands:
            # Commands now ask for a next-turn directive. Keep this cost regression
            # on the player's full-turn path so it can inspect and press Grave Assault.
            answers = []
            for _ in range(12):
                result = act(table, mid, commands[0], answers)
                if result["status"] == "COMMITTED":
                    break
                assert result["status"] == "REACTION_REQUIRED", result
                prompt = result["reaction"]
                answer = {**prompt["context"], "selection": "DECLINE"}
                if prompt.get("choice"):
                    ids = [option["id"] for option in prompt["choice"]["options"]]
                    assert {"manual", "attack", "hold", "guard", "use", "hide", "follow"} <= set(ids)
                    answer.update(selection="USE", option_ids=["manual"])
                answers.append(answer)
            else:
                raise AssertionError("manual summon command did not finish")
            assert result["status"] == "COMMITTED"
            commanded = _summon(table.combat, mid, group)
            assert commanded.summon["commanded"]
            assert "directive" not in commanded.summon
        assert act(table, mid, "end")["status"] == "COMMITTED"
    raise AssertionError(f"{group} never reached a turn of its own")


def test_a_grave_formations_own_attack_does_not_print_the_rituals_cost(tmp_path):
    """The reported bug: "Cost: 8 CP" on Grave Assault, which charged nothing and refused nothing."""
    combat, table, mid = _table(tmp_path, [SERVANT, GRAVE])

    # The summonerer's own bonus action, "Command Death servants", is the same defect and is free.
    _turn(table, mid, SUMMONER)
    command = _button(table, mid)["Command Death servants"]["description"]
    assert "Cost:" not in command, f"a command that charges nothing must not print a cost: {command!r}"
    assert "costs no Qi, Stamina or other resource" in command and "Bonus action" in command
    assert "Each one in range of the order follows your chosen order on its next turn" in command

    button = _command_and_wait(table, mid, "grave_formation", "Grave Assault")
    description = button["description"]

    # Presentation only: reading the table again, descriptions and all, must not move a single saved byte.
    settled = _saved_digest(combat, mid)
    _button(table, mid)
    assert _saved_digest(combat, mid) == settled, "a fight saved before this change must replay byte-identically"

    assert "Cost:" not in description, f"a button that charges nothing must not print a cost: {description!r}"
    assert "costs no cultivation points" in description
    assert "Grave Formation" in description and "Grave Assault" in description
    assert "8 CP" not in description
    for internal in ("TAL_", "summons.json", "action:typed", "resource:"):
        assert internal not in description, f"player text must not leak {internal}: {description!r}"

    # A player's press. The attack still runs and hits (the foe's Armor Class is 1), and spends nothing.
    before = dict(_summoner(combat, mid).resources)
    assert act(table, mid, button["source_definition_id"])["status"] == "COMMITTED"
    events = _engine(combat, mid).events
    assert [event for event in events if event.event_type == "DAMAGE_COMMITTED" and FOE in (event.target_ids or ())], \
        "the formation's own attack must still land"
    assert not [event for event in events if event.event_type == "RESOURCE_SPENT"]
    assert dict(_summoner(combat, mid).resources) == before
    assert CombatService(ROOT, tmp_path)._load_session(mid).mechanical.replay()["status"] == "PASS"


def test_a_summon_the_ability_calls_mid_fight_is_corrected_and_a_paid_button_is_not(tmp_path):
    """A Painted Beast's Ink Fang is corrected; the summoner's own paid summon still shows and pays."""
    combat, table, mid = _table(tmp_path, [BEAST])
    assert table.state(mid)["menu"].get("actor_id") == FOE
    _turn(table, mid, SUMMONER)

    paid = _button(table, mid)["Painted Beast"]
    # LIVE's shared formatter names the pool actually charged, rather than bare CP.
    assert "Cost: 4 Qi" in paid["description"], "a paid button states its exact amount and pool"
    before = _summoner(combat, mid).resources["resource:core.qi"]
    assert act(table, mid, paid["source_definition_id"])["status"] == "COMMITTED"
    assert [event for event in _engine(combat, mid).events if event.event_type == "RESOURCE_SPENT"], \
        "the summoner's own summon still pays its printed cost"
    assert _summoner(combat, mid).resources["resource:core.qi"] == before - 4

    fang = _command_and_wait(table, mid, "painted_beast", "Ink Fang")
    assert "Cost:" not in fang["description"], fang["description"]
    assert "costs no cultivation points" in fang["description"]
    assert "Painted Beast" in fang["description"] and "Ink Fang" in fang["description"]


def test_a_fighter_who_owns_no_summon_keeps_every_button_it_had(tmp_path):
    """Inert for everyone else: without a summon there is nothing to correct."""
    combat, table, mid = _table(tmp_path, [])
    _turn(table, mid, SUMMONER)
    buttons = _button(table, mid)
    assert buttons and "Command Death servants" not in buttons
    assert all("costs no cultivation points" not in group.get("description", "") for group in buttons.values())
    assert all("Grave Assault" not in label and "Ink Fang" not in label for label in buttons)
