"""A fight button states the cost it is really charged, and an Ask me prompt names the creature it is about.

Hunt 90 findings (two P2 and a P3), all read off a real table at ``fa5e61b5``:

  * A composed augment -- the base ability with any number of augments on one use (owner 2026-09-27:
    "Yes, any number") -- is charged its augments on top of the base ability, but its button showed the
    BASE ability's printed rules.  H90-P19 step 1 read "Ye Yi spent 2 Resonance for Lightning-God Body +
    True Lightning-God Mantle" under a button that said "Cost: 1 CP"; 800 augment-style labels carried no
    figure at all.  In the darkness fixture the gap is wider: the base really is free, so it printed
    "Cost: no resource cost" under buttons that charged 1 Qi.
  * 73 of 106 recorded Ask me prompts had no usable ``affected``: the key was absent in 50 and blank in
    23, across whole families of reaction (Flowing Response, Chain Counter, Chain Bolt), because the
    shared prompt builder returned no such field at all.  Change standard item 9 requires the ability,
    the triggering action AND the creature affected.
  * The rules print a Path resource as "CP" while the fight log names the pool it is taken from ("Zou
    Chenzhen spent 8 Stamina" beside a "Cost: 8 CP" button).  Both were correct -- "CP means the
    character's current Path resource" (Core Rules Reference v0_2C, Terms) -- but a newcomer met two names
    for one pool on one button.

The first fights through a real service, a real compiled fight and the real menu answer the browser
receives; the last goes through the shared prompt builder with a real fight's real reaction contexts.
Display only throughout: no cost, gate, candidate id or state hash is touched, so saved fights and AI
replays are unchanged.
"""

import re
from pathlib import Path

from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate5_service import CombatService
from combat.tabletop import engine_button_description
from combat.tabletop_service import TabletopService
from tests.test_zones import SHEET

ROOT = Path(__file__).resolve().parents[1]
ME = "actor:factory.mmx80"
#: Display names for the two creatures of the Ask me fixture. They must differ: a roster where both are
#: called the same thing cannot tell a correct subject from the wrong one.
MINE = "Ashen Healer"
THEIRS = "Iron Reaver"


def _corrector():
    """The printed-cost corrector, imported here rather than at module scope.

    The table-level tests below must run on the base commit, where this seam does not exist yet: a
    module-level import would fail collection and hide the very behaviour they are the regression for.
    """
    from combat.decision_text import cost_as_charged

    return cost_as_charged

DARK = "tianxia.sphere.dark"
#: Enough augments that the compiler composes real multi-augment variants.  The pool is capped at
#: MAX_AUGMENTS_COMBINED, so the buttons checked below are ones the table can actually offer.
AUGMENTS = ("TAL_DARK_CLINGING_DARKNESS", "TAL_DARK_DIRECTIONAL_DARKNESS", "TAL_DARK_ETERNAL_DARKNESS",
            "TAL_DARK_GREATER_DARKNESS", "TAL_DARK_MIDNIGHT", "TAL_DARK_OBFUSCATION")


def _sheet(*talents: str) -> dict:
    return {**SHEET, "spheres_and_talents": {"sphere_record_ids": [DARK],
                                            "learned_talent_record_ids": list(talents)}}


def _bundle(*talents: str) -> dict:
    """The compiled character: the same definitions the service registers in the fight."""
    return compile_character(_sheet(*talents), actor_id=ME)


def _charges_by_label(*talents: str) -> dict:
    """What the engine really charges for each button, keyed by the label the menu shows."""
    return {row["display_name"]: row.get("costs") or []
            for row in _bundle(*talents)["action_catalog"]}


def _match(tmp_path, *talents):
    """A real saved fight through the real service: the same bundles, arena and control modes the table
    registers, so the menu answers below are the ones a player's browser receives."""
    combat = CombatService(ROOT, tmp_path)
    match_id = combat._finish_factory_match(
        [compile_character(_sheet(*talents), actor_id=ME, reaction_plan={"ask": False}),
         compile_character(_sheet(), actor_id=AN)], [ME, AN], {ME: "team:a", AN: "team:b"},
        {ME: {"x": 3, "y": 6}, AN: {"x": 4, "y": 6}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [ME], [AN],
        control_modes={ME: "MANUAL", AN: "MANUAL"}, match_seed="MMX80", display_name="MMX80 costs",
        maximum_rounds=5)["match_id"]
    return combat, match_id


def _menu(tmp_path, *talents) -> dict:
    """The fight menu exactly as a player's browser receives it: a real service, a real compiled fight,
    a real state answer -- not the engine's candidates seen from the side."""
    combat, match_id = _match(tmp_path, *talents)
    return TabletopService(combat, tmp_path).state(match_id)["menu"]


def _printed_cost(description: str) -> list[str]:
    """Every cost the description states, one entry per cost header.

    A compiled record arrives with its header block run together ("... Cost: 2 Qi Create a sphere of
    ..."), so the count of headers is read off the text itself rather than off line starts.
    """
    return re.findall(r"\bCost:", str(description or ""))


def _cost_figure(description: str):
    """(amount, pool name) as the button states them, or None when it states no figure."""
    match = re.search(r"Cost:\s*(\d+)\s*([A-Za-z]+)", str(description or ""))
    return (int(match.group(1)), match.group(2)) if match else None


def _charged_amount(costs) -> int:
    return sum(amount for resource, amount in (costs or [])
               if not str(resource).startswith("resource:uses."))


# ------------------------------------------------------------------ a button shows the cost it charges
def test_a_composed_augment_button_shows_the_cost_it_is_charged(tmp_path):
    """The bug as an owner sees it: buttons charging 1, 2 and 4 Qi all read "Cost: no resource cost",
    the free base ability's printed wording.  Every composed-augment button now states its own charge,
    and states it once."""
    charges = _charges_by_label("DARK_BASE_DARKNESS", *AUGMENTS)
    menu = _menu(tmp_path, "DARK_BASE_DARKNESS", *AUGMENTS)
    composed = [group for group in menu["actions"] if " + " in group["label"]]
    assert composed, f"the menu offered no composed-augment button: {[g['label'] for g in menu['actions']]}"

    charged_seen = 0
    for group in composed:
        shown = _printed_cost(group.get("description"))
        assert len(shown) == 1, f"{group['label']} states its cost {len(shown)} times: {shown}"
        charged = _charged_amount(charges.get(group["label"]))
        if charged <= 0:
            continue
        charged_seen += 1
        figure = _cost_figure(group["description"])
        assert figure, f"{group['label']} shows no figure for the {charged} it is charged: {group['description'][:200]!r}"
        assert figure[0] == charged, f"{group['label']} says {figure} but is charged {charged}"
        hover_figure = _cost_figure(group["hover"]["text"])
        assert hover_figure == figure, "the structured hover and flat menu must state the same charge"
    assert charged_seen, "no composed-augment button in this menu carries a resource charge to check"


def test_the_base_button_keeps_its_own_free_cost(tmp_path):
    """The base ability really is free, so its button must not have been given a cost by the same rule:
    a free button that grew a cost would be the next version of this bug."""
    groups = {group["label"]: group for group in _menu(tmp_path, "DARK_BASE_DARKNESS")["actions"]}
    description = str(groups["Darkness"].get("description") or "")
    assert _printed_cost(description) == ["Cost:"], description[:200]
    assert "no resource cost" in description, description[:200]


# ------------------------------------------------------------------ the CP / pool name gap
def test_a_printed_CP_cost_reads_as_the_pool_the_log_names():
    """P3: the rules print "Cost: 8 CP" and the log says "spent 8 Stamina".  The cost now names the pool
    the log names, so a newcomer meets one name for one pool."""
    assert _corrector()("### Cut\nAction Type: Action\nCost: 8 CP\nProse.",
                           [("resource:core.stamina", 8)]) == "### Cut\nAction Type: Action\nCost: 8 Stamina\nProse."


def test_a_printed_free_cost_reads_as_the_cost_the_engine_charges():
    """The same rule where the printed figure is missing entirely: a free base ability with an augment on
    it is charged the augment, so the button must not keep claiming the ability is free."""
    assert _corrector()("Cost: no resource cost Create a sphere of Darkness.",
                           [["resource:core.qi", 2]]) == \
        "Cost: 2 Qi Create a sphere of Darkness."


def test_the_owner_own_choices_are_never_overwritten():
    """Only a cost printed as a single figure is corrected.  An either/or cost and an "up to N" spend are
    decisions for the player, and a compiled total would erase them."""
    for printed in ("Cost: 2 CP or 2 Stamina", "Cost: up to 5 Stamina", "Cost: 1 CP, or 1 Stamina instead"):
        text = f"### Keep\n{printed}\nProse."
        assert _corrector()(text, [("resource:core.stamina", 2)]) == text, printed


def test_a_free_button_and_a_costless_record_are_untouched():
    """A button that really costs nothing keeps its printed words, and a record with no printed cost header
    is not given an invented one."""
    assert _corrector()("### Free\nCost: no resource cost\nProse.", []) == \
        "### Free\nCost: no resource cost\nProse."
    assert _corrector()("### No header\nAction Type: Action\nProse.", [("resource:core.qi", 2)]) == \
        "### No header\nAction Type: Action\nProse."


def test_a_limited_use_and_a_two_pool_charge_keep_the_owners_words():
    """A limited-use charge stays a separate clause the owner wrote, never folded into one total; a charge
    spread over two pools has no single figure to state, so it is left exactly as printed.

    "Cost: 1 CP plus a use" is left whole rather than restated: replacing its first amount with the
    composed total would state the use a second time. (MMX80 review, finding 1: a printed additive is not
    one figure, so this lane no longer rewrites any part of it.)
    """
    assert _corrector()("Cost: 1 CP plus a use", [["resource:core.qi", 1], ["resource:uses.darkness", 1]]) == \
        "Cost: 1 CP plus a use"
    assert _corrector()("Cost: 1 CP", [["resource:core.qi", 1], ["resource:core.stamina", 1]]) == "Cost: 1 CP"


# ------------------------------------------------------------------ costs that are not one figure
#: Real cost lines from authority/typed_mechanics/rules_text.json, quoted exactly. Every one of them was
#: mispriced by the first version of this correction, which recognised "or"/"and" and nothing else and
#: therefore restated the free branch of a conditional or folded an added cost into the figure (MMX80
#: review, finding 1).
CONDITIONAL_OR_ADDITIVE = (
    "Cost: 0 CP if drawing from an existing Sand Source; 1 CP if creating sand where no Sand Source exists",
    "Cost: 0 CP unless the Mandate talent says otherwise",
    "Cost: 0 CP for passive awareness; 1 CP to inspect actively.",
    "Cost: 1 CP if cast as an Action; 0 CP if cast as a 10-minute ritual",
    "Cost: None for mundane thread; 1 CP to create or reinforce Qi Thread for combat use.",
    "Cost: None for mundane thread if you have thread stock; 1 CP for Qi Thread or to ignore mundane stock.",
    "Cost: 1 CP plus the Modulation’s cost",
    "Cost: 1 CP, plus the ingredient",
    "Cost: 3 CP plus the talismans used",
    "Cost: 6 CP plus consumed talismans",
    "**Cost:** 8 Qi from you and 4 Cultivation Points from the patient, when the patient has them",
    "Cost: 15 CP during the final rite, plus 25,000 gp or campaign-equivalent in rare ore, crystal",
    "Cost: 2 CP (or 1 Stamina)",
    "Cost: 1 CP + 1 Stamina",
)


def test_a_conditional_or_additive_printed_cost_keeps_the_owners_wording():
    """A cost that is not one plain figure is never restated, whatever the fight charges for it.

    Each row is a real printed cost. Restating any of them prices a branch that costs nothing ("0 CP if
    drawing from an existing Sand Source" is free; a composed total would make it 1 Qi), or describes
    an added cost twice ("1 CP plus the Modulation’s cost" would become "2 Qi plus the Modulation’s
    cost", which charges the modulation through the figure as well). Leaving the owner's words is the
    only answer that cannot be wrong, so that is what this keeps.
    """
    for printed in CONDITIONAL_OR_ADDITIVE:
        text = f"### Ability\n{printed}\nProse."
        for charge in ([["resource:core.qi", 1]], [["resource:core.stamina", 2]], []):
            assert _corrector()(text, charge) == text, f"{printed!r} was rewritten for {charge}"


def test_a_rate_limit_and_the_next_paragraph_are_not_another_cost():
    """The guard reads the cost's OWN line, so the words a following paragraph opens with stay prose.

    A record's effect very often opens "When the target rolls..." or "While mounted...", and a rate
    limit ("once per long rest") or a run-together header ("Uses:", "Concentration:") is metadata, not
    a second cost. A first version of this guard read across the newline and refused to correct those
    buttons, which would have left the reported hunt 90 bug unfixed for a large part of the corpus.
    """
    for printed, wanted in (
        ("Cost: 3 CP; once per short or long rest", "Cost: 1 Qi; once per short or long rest"),
        ("Cost: 5 CP Uses: Once per long rest", "Cost: 1 Qi Uses: Once per long rest"),
        ("Cost: 5 CPConcentration: Required", "Cost: 1 QiConcentration: Required"),
        ("Cost: 1 CP\nWhen the target rolls a natural 1, it is stunned.", "Cost: 1 Qi\nWhen the target rolls a natural 1, it is stunned."),
        ("Cost: 1 CP\nWhile mounted on a larger creature, choose one edge.", "Cost: 1 Qi\nWhile mounted on a larger creature, choose one edge."),
        ("Cost: 1 CP\nInstead of applying a Point, read the response.", "Cost: 1 Qi\nInstead of applying a Point, read the response."),
    ):
        assert _corrector()(printed, [["resource:core.qi", 1]]) == wanted, printed


def test_a_pool_the_owner_named_in_its_own_words_is_left_alone():
    """A record that names a pool the fight is not charging from keeps the owner's wording; the correction
    only speaks for the pool actually charged."""
    assert _corrector()("Cost: 1 Devotion", [["resource:core.stamina", 1]]) == "Cost: 1 Devotion"


def test_a_bold_printed_cost_is_corrected_in_place():
    """The owner's records write the header in markdown bold ("**Cost:** 2 CP"), so the correction has to
    read through that markup and write it back rather than flattening the owner's own emphasis."""
    assert _corrector()("**Cost:** 2 CP\nProse.", [["resource:core.stamina", 2]]) == \
        "**Cost:** 2 Stamina\nProse."
    assert _corrector()("**Cost:** None Prose.", [["resource:core.qi", 1]]) == "**Cost:** 1 Qi Prose."


def test_a_zero_or_absent_charge_keeps_the_printed_words():
    """A cost the fight does not actually charge is left alone rather than restated: "Cost: 0 CP" really
    does cost nothing, and a printed figure with nothing behind it is the owner's, not the table's."""
    assert _corrector()("Cost: 0 CP", [["resource:core.stamina", 0]]) == "Cost: 0 CP"
    assert _corrector()("Cost: 1 CP", [["resource:core.qi", 0]]) == "Cost: 1 CP"


def test_a_real_button_names_its_pool_the_way_the_log_does():
    """The same rule on a real compiled button: a Qi-pool spend reads "Qi", the pool the fight log names,
    not the generic "CP"."""
    row = next(row for row in _bundle("DARK_BASE_DARKNESS", *AUGMENTS)["action_catalog"]
               if " + " in row["display_name"] and row.get("costs"))
    description = engine_button_description(dict(row))
    assert _printed_cost(description) == ["Cost:"], f"{row['display_name']} states its cost twice: {description[:200]!r}"
    stated = _cost_figure(description)
    assert stated, f"{row['display_name']} shows no figure: {description[:200]!r}"
    assert stated[1] == "Qi", f"{row['display_name']} still names the generic CP: {description[:200]!r}"
    assert stated[0] == _charged_amount(row["costs"]), f"{row['display_name']} says {stated}"


# ------------------------------------------------------------------ Ask me prompts name the creature
def _named_fight(tmp_path):
    """The same real Ask me fight as ``_fight``, with the two creatures given different display names.

    ``_fight``'s two creatures are both called "Factory character", which is why a test could only assert
    that ``affected`` was non-empty and not an id: with one name for the whole roster, naming the wrong
    creature is invisible. MMX80's review (finding 2) asked for the exact subject to be asserted.
    """
    from tests.test_reaction_ask_binding import FOE, ME, _fight

    service, engine = _fight(tmp_path)
    engine.state.actors[ME].display_name = MINE
    engine.state.actors[FOE].display_name = THEIRS
    return service, engine


def _prompt_for(table, engine, context, *, cache=None, match="mmx80"):
    """The prompt exactly as the table builds it, with ``cache`` standing in for the lifetime name map.

    ``cache=None`` primes it from the live roster, which is what the table does on its first read. A
    partial ``cache`` is the state a fight is in when a creature joined it after that read.
    """
    table._names[match] = cache if cache is not None else (
        {actor.entity_id: actor.display_name for actor in engine.state.actors.values()}, {})
    fields = context.model_dump(mode="json", by_alias=True) if hasattr(context, "model_dump") else dict(context)
    return table._reaction_prompt(match, fields, engine=engine)


def test_the_prompt_names_the_exact_creature_it_is_about(tmp_path):
    """Change standard item 9 at the level the bug showed, on a real fight's real prompts, and asserting
    the exact creature rather than merely a non-empty string.

    Both families the hunt found (Flowing Response on an attack being declared, Stamina Guard as the
    damage lands) are about the creature being attacked, and both name the attacker separately, so the
    field and the sentence a player reads have to agree on which creature is which.
    """
    from tests.test_reaction_ask_binding import _ask_all, _foe_attack

    service, engine = _named_fight(tmp_path)
    _answers, asked = _ask_all(service, engine, _foe_attack(engine), lambda ctx: "DECLINE")
    assert len(asked) >= 2, f"this fight raised {[c.reaction_source_id for c in asked]}, not both families"

    table = TabletopService(service, tmp_path)
    for context in asked:
        prompt = _prompt_for(table, engine, context)
        assert prompt["affected"] == MINE, \
            f"{context.reaction_source_id} names {prompt['affected']!r} as the creature it is about: {prompt}"
        assert prompt["trigger_actor"] == THEIRS, \
            f"{context.reaction_source_id} names the wrong triggering creature: {prompt['trigger_actor']!r}"
        assert prompt["affected"] in str(prompt.get("moment") or ""), \
            f"the field and the sentence name different creatures: {prompt}"
        assert MINE not in (str(prompt.get("reaction") or ""),) or ":" not in str(prompt.get("reaction") or ""), \
            f"a raw id reached the reaction name: {prompt}"


def test_a_creature_missing_from_the_cached_names_is_read_from_the_live_roster(tmp_path):
    """A creature that joined the fight after the names were cached is still named, not shown as an id.

    ``_names_for`` keeps a match's display names for the life of the service, so a creature that is not
    in the cached map is one the fight gained later. The live engine's roster is the authority for who
    is in the fight now, so it is read for these fields; the cached map is only a floor. Before the fix
    the first case answered with the raw actor id and the second with a blank.
    """
    from tests.test_reaction_ask_binding import FOE, ME, _ask_all, _foe_attack

    service, engine = _named_fight(tmp_path)
    _answers, asked = _ask_all(service, engine, _foe_attack(engine), lambda ctx: "DECLINE")
    assert asked, "this fight raised no reaction, so the prompt text is unchecked"
    table = TabletopService(service, tmp_path)

    for cached, affected, triggering in (({ME: MINE}, MINE, THEIRS), ({FOE: THEIRS}, MINE, THEIRS)):
        prompt = _prompt_for(table, engine, asked[0], cache=(cached, {}))
        assert prompt["affected"] == affected, \
            f"with only {list(cached.values())} cached, the prompt shows {prompt['affected']!r} instead of a creature's name"
        assert prompt["trigger_actor"] == triggering, \
            f"with only {list(cached.values())} cached, the prompt shows {prompt['trigger_actor']!r} instead of a creature's name"


def test_a_creature_that_resolves_to_nobody_reads_as_words_not_an_id(tmp_path):
    """A prompt whose creature id belongs to nobody reads as words: a player never sees "actor:...".

    Change standard item 13. The field exists to name a creature, so an id nobody answers to has to be
    readable English rather than leaking the engine's own addressing into the page.
    """
    from tests.test_reaction_ask_binding import _ask_all, _foe_attack

    service, engine = _named_fight(tmp_path)
    _answers, asked = _ask_all(service, engine, _foe_attack(engine), lambda ctx: "DECLINE")
    assert asked, "this fight raised no reaction, so the prompt text is unchecked"
    table = TabletopService(service, tmp_path)

    fields = asked[0].model_dump(mode="json", by_alias=True)
    fields.setdefault("choice_trigger", {})["target_id"] = "actor:gone.long.ago"
    table._names["mmx80"] = ({}, {})
    prompt = table._reaction_prompt("mmx80", fields, engine=engine)
    shown = str(prompt.get("affected") or "")
    assert shown and "actor:" not in shown and ":" not in shown, \
        f"a prompt shows an id instead of readable words: {prompt}"


def test_every_ask_me_prompt_names_the_creature_it_is_about(tmp_path):
    """Change standard item 9 for every family, not one: no Ask me prompt may arrive without the
    creature it is about, and none may answer with a raw id.
    """
    from tests.test_reaction_ask_binding import _ask_all, _fight, _foe_attack

    service, engine = _fight(tmp_path)
    _answers, asked = _ask_all(service, engine, _foe_attack(engine), lambda ctx: "DECLINE")
    assert asked, "this fight raised no reaction, so the prompt text is unchecked"

    table = TabletopService(service, tmp_path)
    for context in asked:
        # The service renders the prompt from the context as a plain dict, so hand it the same shape.
        fields = context.model_dump(mode="json") if hasattr(context, "model_dump") else dict(context)
        table._names["mmx80"] = ({actor.entity_id: actor.display_name
                                  for actor in engine.state.actors.values()}, {})
        prompt = table._reaction_prompt("mmx80", fields, engine=engine)
        assert str(prompt.get("affected") or "").strip(), \
            f"an Ask me prompt ({fields.get('reaction_source_id')}) does not name the creature it is about: {prompt}"
        assert str(prompt.get("affected") or "").strip() not in {str(actor.entity_id) for actor in engine.state.actors.values()}, \
            f"an Ask me prompt shows a raw id instead of a creature name: {prompt}"


# ------------------------------------------------------------------ the cost wording survives a save
def test_the_button_cost_survives_a_table_commit_and_reload(tmp_path):
    """The table-level regression: a real commit through the real service, then a fight re-opened by a
    brand new service reading the save from disk.

    Two things have to hold.  The saved fight still loads and still verifies and replays, because the
    correction is display only and must not have changed what the fight does.  And the button text still
    states the cost the reloaded catalog charges -- the wording is computed from the compiled costs, so a
    catalog rebuilt from a save is exactly where a lost charge would show up.
    """
    combat, match_id = _match(tmp_path, "DARK_BASE_DARKNESS", *AUGMENTS)
    table = TabletopService(combat, tmp_path)
    menu = table.state(match_id)["menu"]
    assert menu["actor_id"] == ME, f"the owner did not get the opening turn: {menu['actor_id']}"

    # Commit one composed augment the way the browser does: the group label's own candidate, answered
    # through the reaction loop if the table asks.
    group = next(group for group in menu["actions"] if " + " in group["label"] and group["options"])
    candidate_id = group["options"][0]["candidate_id"]
    answers: list[dict] = []
    for _ in range(20):
        result = table.act(match_id, candidate_id, menu["decision_id"], menu["state_version"], 0, answers)
        if result["status"] == "COMMITTED":
            break
        assert result["status"] == "REACTION_REQUIRED", result
        prompt = result["reaction"]
        answer = {**prompt["context"], "selection": "DECLINE"}
        if prompt.get("choice"):
            answer.update(selection="USE", option_ids=(prompt["choice"].get("preferred")
                                                       or [prompt["choice"]["options"][0]["id"]])[:1])
        answers.append(answer)
    else:
        raise AssertionError("the composed augment never committed")

    # A brand new service, reading only what the commit wrote to disk.
    reloaded = CombatService(ROOT, tmp_path)._load_session(match_id)
    assert reloaded.verify()["status"] == "PASS", "the committed fight no longer verifies"
    assert reloaded.mechanical.replay()["status"] == "PASS", "the committed fight no longer replays"

    checked = 0
    for action in reloaded.engine.action_catalog.values():
        if action.owner_id != ME or not action.costs or " + " not in action.display_name:
            continue
        figure = _cost_figure(engine_button_description(action.model_dump(mode="json")))
        assert figure, f"a reloaded button states no cost: {action.display_name}"
        assert figure[0] == _charged_amount([tuple(c) for c in action.costs]), \
            f"{action.display_name} says {figure} but is charged {action.costs}"
        checked += 1
    assert checked, "the reloaded fight offered no composed-augment button to check"
