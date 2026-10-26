"""A rewritten summon button must keep what the creature's attack actually does (MMX116f1, finding 5).

``combat/ext/summon_ability_costs.py`` replaces a summon button's whole help text, because the text it
used was the printed rules of the ability that *called the creature out* -- "**Cost: 8 CP**" on Grave
Assault, an entry of the creature's own stat block that charges nothing.  The first version of that fix
replaced the description with the attack roll and the damage and nothing else, so a Living Painting's
form rider disappeared from the button: the Tiger's Pouncing Stroke and the Serpent's Coiling Stroke
(``combat/summons.py:82-84`` puts them on the strike's on-hit effects, ``combat/ext/painting_forms.py``
works them) were nowhere in the help.  A player pressing it had no way to learn that the Serpent
grapples, that the grip lasts until the start of their next turn, or that it cannot strike a second
creature while it holds one.

These are real persisted tables, played as a player through ``TabletopService``.
"""

from combat.canonical import canonical_sha256
from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests.hunt23_support import act, fight
from tests.worker2_support import settle

SUMMONER, FOE = "actor:factory.h15-left", "actor:factory.h15-right"
PAINTING = "tianxia.subpath.qi.painting_cultivator.feature.living_painting"


def _table(tmp_path):
    """A real table: the painter stands next to a foe whose Armor Class is 1, so any roll hits."""
    def unarmoured(bundle):
        if bundle["actor_id"] == FOE:
            bundle["actor_template"]["armor_class"] = 1

    return fight(tmp_path, [PAINTING], prepare_bundle=unarmoured,
                 positions={SUMMONER: {"x": 4, "y": 6}, FOE: {"x": 6, "y": 6}})


def _engine(combat, mid):
    return combat._load_session(mid).engine


def _digest(combat, mid):
    return canonical_sha256(_engine(combat, mid).state.model_dump(mode="json"))


def _button(table, mid):
    return {group["label"]: group for group in table.state(mid)["menu"]["actions"]}


def _summon(combat, mid, group):
    return next(actor for actor in _engine(combat, mid).state.actors.values()
                if (actor.summon or {}).get("group") == group)


def _turn(table, mid, actor_id, limit=8):
    for _ in range(limit):
        if table.state(mid)["menu"].get("actor_id") == actor_id:
            return
        assert act(table, mid, "end")["status"] == "COMMITTED"
    raise AssertionError(f"{actor_id} never took a turn")


def _paint(table, mid, form, group):
    """Summon the Living Painting, command it, then read the button for that form's own strike.

    The painter may maintain one Living Painting and the ability brings the whole family out, so the
    form under test is chosen by its summon group rather than by which button summoned it.
    """
    _turn(table, mid, SUMMONER)
    buttons = _button(table, mid)
    settle(table, mid, buttons[f"Living Painting: {form}"]["options"][0]["candidate_id"])
    for _ in range(10):
        creature = _summon(table.combat, mid, group)
        if table.state(mid)["menu"].get("actor_id") == creature.entity_id:
            strike = next((group_row for group_row in table.state(mid)["menu"]["actions"]
                           if group_row["label"] == "Painted Strike"), None)
            if strike is not None:
                return strike
        commands = sorted(name for name in _button(table, mid) if name.startswith("Command "))
        if table.state(mid)["menu"].get("actor_id") == SUMMONER and commands:
            assert act(table, mid, commands[0])["status"] == "COMMITTED"
        assert act(table, mid, "end")["status"] == "COMMITTED"
    raise AssertionError(f"the {form} never got a turn to strike")


def test_the_serpent_button_still_says_it_grapples_and_why(tmp_path):
    """The finding: the replacement help said "roll, damage" and dropped the Coiling Stroke entirely."""
    combat, table, mid = _table(tmp_path)
    strike = _paint(table, mid, "Serpent", "living_painting_serpent")
    description = strike["description"]

    assert "Coiling Stroke" in description, description
    assert "Grappled" in description, "the Strength save and what it does on a failure must be in the help"
    assert "Strength saving throw" in description, description
    assert "start of your next turn" in description, "how long the grip lasts must be in the help"
    assert "cannot use Painted Strike against another" in description, \
        "the restriction the player has to plan around must be in the help"
    # The correction of the cost is kept, and reads plainly.
    assert "Cost:" not in description, description
    assert "costs no cultivation points" in description
    for internal in ("action:typed", "resource:", "form_rider", "tianxia."):
        assert internal not in description, f"player text must not leak {internal}: {description!r}"

    # Presentation only: reading the table again must not move a single saved byte.
    settled = _digest(combat, mid)
    _button(table, mid)
    assert _digest(combat, mid) == settled, "a fight saved before this change must replay byte-identically"

    # A player's press: the strike still runs, hits, and spends nothing.  (The painter's own 4 Qi
    # summoning cost was spent before this, which is the ability that calls the creature out.)
    before = dict(_engine(combat, mid).state.actors[SUMMONER].resources)
    spent_before = len([event for event in _engine(combat, mid).events if event.event_type == "RESOURCE_SPENT"])
    assert act(table, mid, strike["source_definition_id"])["status"] == "COMMITTED"
    events = _engine(combat, mid).events
    assert [event for event in events if event.event_type == "DAMAGE_COMMITTED" and FOE in (event.target_ids or ())], \
        "the form's own strike must still land"
    assert len([event for event in events if event.event_type == "RESOURCE_SPENT"]) == spent_before, \
        "a stat-block action charges nothing"
    assert dict(_engine(combat, mid).state.actors[SUMMONER].resources) == before
    assert CombatService(ROOT, tmp_path)._load_session(mid).mechanical.replay()["status"] == "PASS"


def test_the_tiger_button_still_says_it_knocks_prone_and_why(tmp_path):
    """The Pouncing Stroke: the 20-foot approach, the save, and Prone."""
    combat, table, mid = _table(tmp_path)
    description = _paint(table, mid, "Tiger", "living_painting_tiger")["description"]

    assert "Pouncing Stroke" in description, description
    assert "20 feet" in description, "the approach the rider keys on must be in the help"
    assert "Strength saving throw" in description and "Prone" in description, description
    assert "Cost:" not in description and "costs no cultivation points" in description
    assert CombatService(ROOT, tmp_path)._load_session(mid).mechanical.replay()["status"] == "PASS"


def test_a_form_with_no_rider_still_gets_its_attack_and_its_damage_choice(tmp_path):
    """The Crane and the Tortoise have no form rider; they still lose nothing, and gain the choice.

    Their stat block offers four damage types, chosen when created (Shared Living Painting Statistics).
    """
    combat, table, mid = _table(tmp_path)
    description = _paint(table, mid, "Crane", "living_painting_crane")["description"]

    assert "Painted Strike" in description or "attacks" in description, description
    assert "chose when creating it" in description, f"the creation-time damage choice must be in the help: {description!r}"
    assert "Coiling Stroke" not in description and "Pouncing Stroke" not in description
    assert "costs no cultivation points" in description
