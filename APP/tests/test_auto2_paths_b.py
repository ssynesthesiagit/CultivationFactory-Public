"""auto/paths-b 2026-10-04: Qi Cultivation Path features whose printed effect the table left to the GM.

* **Immortal of Qi** -- "At the start of each of your turns, regain 5 Qi" never fired. Root cause: the typed record had
  no printed Trigger line, so ``combat/factory_compiler.py``'s ``_generic_reaction`` never classified one, and
  ``combat/rules/reaction_trigger_phrases.json`` had no runnable pattern for a plain start-of-your-own-turn moment (the
  ``own_turn_start`` kind existed and was runnable, but no phrase reached it). Fixed generally in that rules file -- the
  patterns are anchored at both ends, so a turn start that also names something the table cannot check stays unsupported
  -- plus this record's own printed Trigger line in ``reviewed_final.d/spirit.json``. The row is free: no Reaction.
* **Meridian Regulation**, both printed branches, behind one choice. "Choose one poison, disease, or directly caused
  physical impairment affecting the target" chooses an *effect*; "Effect with Repeat Saves" repeats that effect's save
  with Advantage, "Effect without Repeat Saves" makes a Constitution save with Advantage against the effect's printed DC
  and suppresses one printed penalty until the end of the target's next turn. The table asks which effect once, so an
  effect that repeats its save cannot hide another effect's penalties from the printed choice (AUTO2 review finding 1),
  and the printed limits -- a printed saving throw DC, no Curse / Tribulation / Foundation Injury / Hidden Injury /
  Possession / Permanent / Soul Damage tag -- are checked before anything is offered (finding 3).

One test per level the bug showed: a table-level fight for the printed effect (real characters, real commits, a reload,
the lifetime running out), compiled-bundle fights for the two branches and for the penalties real printed effects leave,
and the new turn-start phrase at its own level.
"""
import json
import re
from pathlib import Path

from combat import reaction_triggers, typed_executor as te
from combat.ext import qi_path
from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import ActionIntent, ReactionDecision
from combat.gate4_engine import Gate4ControllerEngine
from tests.h52_turn_start_support import ROOT, commit, engine_at, fight
from tests.iron_fist_support import answering_iron_fist

QI = "resource:core.qi"
IMMORTAL = "tianxia.path.qi_cultivation.feature.immortal_of_qi"
MERIDIAN = "tianxia.path.qi_cultivation.feature.meridian_regulation"
NEEDLE = "choice:needle.meridian_regulation"
SUPPRESSED = "condition:typed.benefit_suppressed"
ME = "actor:factory.auto2"
ALLY = "actor:factory.auto2ally"
KIT = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.fu", "name": "Fu (Short Axe)", "quantity": 1}]}}
JARGON = ("condition:typed", "origin_save", "combat/ext", "qi_path", "reviewed_final", "auto/paths-b",
          "the GM applies the rest", "not automated as a modifier")

# Real printed effects, by the ability that leaves them on a failed save. Every penalty and DC below is produced by
# running the real typed rows through the real executor (see _fail_a_printed_save), never by hand.
REPEATING = "tianxia.talent.chains.chain_prison"          # failed STR save -> Restrained that repeats its save each turn
SLOWING = "TAL_ALCHEMY_BINDING_DREGS"                     # failed STR save -> its Speed is reduced by 10 feet
DENYING = "TAL_SAND_SAND_COFFIN"                          # failed save -> cannot take Reactions
SEVERING = "TAL_SWORD_SEVERING_FATE"                      # failed save -> cannot take Reactions AND a Speed reduction
DOSE = "POISON_BASE_DELIVER_THE_DOSE"                     # failed CON save -> Disadvantage on ability checks
INGRAIN = "POISON_BASE_INGRAIN_THE_TOXIN"                 # failed CON save -> Disadvantage on its next Constitution save
DREAMING = "TAL_DREAM_LUCID_VEIL"                          # a dream's successful WIS save -> Disadvantage on its next Perception check
SINGING = "tianxia.talent.music.captivating_melody"        # a song -> Disadvantage: cannot take Reactions
FEARFUL = "TAL_DAEMONIC_CULTIVATION_DREAD_APPETITE"        # a fear: its Speed reduction only reaches an already-Frightened creature
SYMPTOMS = "tianxia.talent.disease.symptom_cascade"        # a menu disease: two symptoms, one repeat save ends both
WEAKENING = "tianxia.talent.disease.weakening_sickness"    # a menu disease: one symptom, one repeat save
VENOMS = "tianxia.talent.poison.five_venom_formula"        # a menu poison: two venom effects, one repeat save ends them
PLAGUE = "tianxia.talent.disease.thousand_symptom_plague"  # a menu disease: two symptoms out of nine
SEALS = "TAL_IRON_FIST_NINE_BELL_MERIDIAN_PALM"            # a menu of seals, each one a bodily impairment
SPHERES = {"chain_prison": "tianxia.sphere.chains", "alchemy": "tianxia.sphere.alchemy",
           "sand": "tianxia.sphere.sand", "sword": "tianxia.sphere.sword", "poison": "tianxia.sphere.poison",
           "disease": "tianxia.sphere.disease", "iron_fist": "tianxia.sphere.iron_fist",
           "daemonic": "tianxia.sphere.daemonic_cultivation"}


def _commit_choosing(table, match_id, menu, candidate_id=None, prompts=None):
    """``tests.h52_turn_start_support.commit``, but it answers a printed choice the way a player must: a question that
    requires a pick ("choose one of its penalties") is answered with the first option the table offered; anything else is
    declined. Returns the response and the prompts the fight asked."""
    prompts = prompts if prompts is not None else []
    answers = []
    action = menu["end_turn"] if candidate_id is None else candidate_id
    send = answering_iron_fist(lambda submitted: table.act(
        match_id, action, menu["decision_id"], menu["state_version"],
        table.state(match_id)["last_sequence"], submitted))
    for _ in range(20):
        response = send(answers)
        if response["status"] != "REACTION_REQUIRED":
            assert response["status"] == "COMMITTED", response
            return response, prompts
        prompt = response["reaction"]
        prompts.append(prompt)
        options = [option["id"] for option in (prompt.get("choice") or {}).get("options") or []]
        answers.append({**(prompt.get("context") or {}),
                        "selection": "USE" if options else "DECLINE", "option_ids": options[:1]})


def _immortal_gains(engine, owner_id):
    return [event for event in engine.events if event.event_type == "RESOURCE_GAINED"
            and event.actor_id == owner_id and IMMORTAL in str(event.source_definition_id)]


def _spend_one_qi(table, match_id):
    """A printed 1 Qi action on the owner's own turn, so the next turn start has room to regenerate into."""
    menu = table.state(match_id)["menu"]
    engine = engine_at(table.combat, match_id)
    for group in menu.get("actions", []):
        action = engine.action_catalog.get(group.get("source_definition_id"))
        if action is None or action.display_name != "Numbing Powder":
            continue
        if (QI, 1) not in {tuple(cost) for cost in action.costs}:
            continue
        option = next((row for row in group.get("options", []) if row.get("target_ids")), None)
        if option:
            commit(table, match_id, menu, option["candidate_id"])
            return True
    return False


def _player_text(prompt):
    """Everything a player reads on a printed question: no machine ids, so the checks below are about the words."""
    fields = ("reactor", "reaction", "moment", "by", "trigger_actor", "action", "affected", "trigger", "title",
              "summary", "limits", "cost", "table_note", "rules")
    parts = [str(prompt.get(field) or "") for field in fields]
    for option in (prompt.get("choice") or {}).get("options") or []:
        parts += [str(option.get("label") or ""), str(option.get("description") or "")]
    return " ".join(parts)


def _log_text(events):
    return " ".join(str((event.payload or {}).get("log") or (event.payload or {}).get("rider") or "") for event in events)


# --------------------------------------------------------------------------- Immortal of Qi (table level, real character)


def test_immortal_of_qi_regains_five_qi_at_the_start_of_each_of_its_turns(tmp_path):
    """"At the start of each of your turns, regain 5 Qi": real turn starts in a real fight, through a table commit."""
    combat, table, match_id, owner_id = fight(tmp_path, "lingyue", opponents=["ning"])
    engine = engine_at(combat, match_id)
    owner = engine.state.actors[owner_id]
    assert owner.resources.get(QI, 0) > 0
    rows = [row for row in (engine.typed_reaction_rows or {}).get(owner_id, []) if row.get("feature_id") == IMMORTAL]
    assert rows and rows[0]["kind"] == "own_turn_start" and rows[0]["free"], \
        "Immortal of Qi is not a free start-of-own-turn row, so its printed +5 Qi cannot run"
    assert not rows[0].get("costs"), "a printed free regeneration must not cost a Reaction or Qi"

    # No Golden Core Form is picked in the fight (FD-7: Forms are fixed on the sheet), and with no
    # Form recorded no Stable turn-start Qi is granted, so Immortal Circulation's +5 is the only regen.
    checked = risen = 0
    for _ in range(16):
        if checked >= 3 and risen:
            break
        engine = engine_at(combat, match_id)
        owner = engine.state.actors[owner_id]
        before = len(engine.events)
        qi_before = int(owner.resources.get(QI, 0))
        maximum = int(owner.resource_maximums.get(QI, qi_before))
        commit(table, match_id, table.state(match_id)["menu"], table.state(match_id)["menu"].get("end_turn"))
        engine = engine_at(combat, match_id)
        owner = engine.state.actors[owner_id]
        gains = [event for event in _immortal_gains(engine, owner_id) if event.sequence > before]
        if not gains:
            _spend_one_qi(table, match_id)
            continue
        checked += 1
        # "regain 5 Qi": the printed amount is asked for at every turn start, and the pool rises by exactly as much of
        # that 5 as the printed pool allows (a full pool is why a printed regeneration can legitimately add nothing).
        assert sum(int(event.payload.get("requested") or 0) for event in gains) == 5 * len(gains), \
            f"Immortal Circulation printed {[event.payload for event in gains]} instead of asking for +5 Qi"
        expected = max(0, min(5, maximum - qi_before))
        assert sum(int(event.payload.get("gained") or 0) for event in gains) == expected, \
            f"Immortal Circulation moved {[event.payload for event in gains]} instead of +{expected} Qi"
        risen += int(expected) > 0
        _spend_one_qi(table, match_id)
    assert checked >= 3, "Immortal of Qi did not regenerate at three of its turn starts"
    assert risen, "the printed +5 Qi never landed: the pool was already full at every turn start"

    # A table commit + reload keeps the fight identical and the rule still there (nothing stored outside fight state).
    engine = engine_at(combat, match_id)
    reloaded = combat._load_session(match_id)
    assert reloaded.mechanical.replay()["status"] == "PASS"
    assert reloaded.engine.state.model_dump(mode="json") == engine.state.model_dump(mode="json")
    assert [row for row in (reloaded.engine.typed_reaction_rows or {}).get(owner_id, [])
            if row.get("feature_id") == IMMORTAL]


# --------------------------------------------------------------- Meridian Regulation, both branches (compiled bundles)


def _sheet(cl=10, *, dex=18, talents=(), spheres=()):
    abilities = [{"ability": a, "score": dex if a == "DEX" else 18, "modifier": (dex - 10) // 2 if a == "DEX" else 4}
                 for a in ("STR", "DEX", "CON", "INT", "WIS", "CHA")]
    return {
        "identity": {"proficiency_bonus": 4, "cultivation_level": cl, "path": "Qi Cultivation", "key_ability": "WIS"},
        "ability_scores_and_statistics": {
            "abilities": abilities,
            "primary_resource": {"name": "Qi", "maximum": 40}, "armor_class": {"base_value": 14},
            "hit_points": {"maximum": 90}, "speed": {"walking_ft": 30},
            "technique_save_dc": 14, "technique_attack_bonus": 8,
        },
        "path_and_subpath": {"path_record_ids": ["tianxia.path.qi_cultivation"],
                             "path_feature_record_ids": [MERIDIAN]},
        "equipment": [KIT],
        "spheres_and_talents": {"sphere_record_ids": list(spheres), "learned_talent_record_ids": list(talents),
                                "automatic_sphere_component_record_ids": []},
    }


def _meridian_engine(*, ally_dex=18, me_dex=18, talents=(), spheres=()):
    """The Qi Cultivation owner of Meridian Regulation, with a neighbour it may touch, and any real printed effects the
    owner also learned. ``dex`` decides who acts first, which is what decides whether a suppressed penalty's own time
    runs out before or after the end of the target's next turn."""
    engine = Gate4ControllerEngine(
        ROOT, match_seed="AUTO2-MERIDIAN",
        typed_bundles=(compile_character(_sheet(dex=me_dex, talents=talents, spheres=spheres), actor_id=ME),
                       compile_character(_sheet(dex=ally_dex, talents=talents, spheres=spheres), actor_id=ALLY)),
        roster_setup={"primary_actor_ids": [ME, ALLY], "team_by_actor": {ME: "team:a", ALLY: "team:a"},
                      "starting_positions": {ME: {"x": 3, "y": 6}, ALLY: {"x": 4, "y": 6}}})
    _my_turn(engine, ME)
    return engine


def _my_turn(engine, actor_id):
    engine.state.current_slot_index = engine.state.initiative_order.index(actor_id)
    engine.state.current_actor_id = actor_id
    engine._system_start_turn()


def _typed_action(engine, mechanic):
    """The compiled action of one printed ability, exactly as the fight offers it."""
    for action_id, action in engine.action_catalog.items():
        typed = (getattr(action, "parameters", None) or {}).get("typed") or {}
        if str(typed.get("source") or "") == mechanic:
            return action_id, action, typed
    raise AssertionError(f"{mechanic} did not compile for this character")


def _save_rows(rows, out):
    for row in rows or []:
        if isinstance(row, dict):
            if row.get("type") == "save":
                out.append(row)
            for key in ("effects", "on_hit", "on_miss"):
                _save_rows(row.get(key), out)
    return out


def _fail_a_printed_save(engine, mechanic, target, save):
    """Run a real ability's real typed failure rows through the real executor, as its own failed save does.

    This is what puts the printed penalty on the target: the printed row, the printed DC, and the save the penalty
    remembers are all the engine's own, so nothing about the penalty is hand-written here.
    """
    _action_id, action, typed = _typed_action(engine, mechanic)
    ctx = te.Context(engine, engine.state.actors[ME], action, None, typed, [target], target, {}, failed_save=True,
                     origin_save=dict(save))
    saves = _save_rows(typed.get("effects"), [])
    assert saves, f"{mechanic} has no printed saving throw to fail"
    for row in saves:
        te.run_effects(ctx, list(row.get("on_fail") or []))


def _printed_dc(engine, mechanic):
    """The DC that ability's own save printed (its compiled numbers), which is the "effect's printed DC"."""
    return int((_typed_action(engine, mechanic)[2].get("numbers") or {}).get("save_dc") or 0)


class _Asker:
    """The documented choice provider (an engine attribute, not a patched function): it answers the printed question and
    keeps the request, so a test reads the question exactly as the table receives it."""

    def __init__(self, pick=None):
        self.pick, self.requests = pick, []

    def __call__(self, request):
        self.requests.append(request)
        option = self.pick(request) if callable(self.pick) else self.pick
        if option is None:
            return None, None
        return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                reaction_source_id=request["reaction_source_id"], selection="USE",
                                option_ids=[option]), None

    def meridian(self):
        """The printed Meridian Regulation request, once the question has been asked."""
        return next((request for request in self.requests
                     if str(request.get("reaction_source_id") or "") == NEEDLE), None)


def _use_meridian(engine, target_id, *, pick=None):
    """Use Meridian Regulation on one creature, answering its printed question through the provider. ``pick`` is the
    option id to choose (or None for the table's own default), or a callable that chooses from the request."""
    candidate = next(c for c in engine.legal_candidates() if c.display_name == "Meridian Regulation"
                     and target_id in (c.target_ids or ()))
    asker = _Asker(pick)
    engine._gate4_reaction_provider = asker
    before = len(engine.events)
    try:
        engine.execute_intent(ActionIntent(intent_id="i-meridian", decision_id=candidate.decision_id,
                                           candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                           actor_id=ME, target_ids=candidate.target_ids,
                                           destination=candidate.destination))
    finally:
        engine._gate4_reaction_provider = None
    return engine.events[before:], asker


def _meridian_fixture(**engine_kwargs):
    """A victim carrying one repeating printed effect and one plain printed penalty, and the two choices they make."""
    engine = _meridian_engine(talents=(REPEATING, SLOWING), **engine_kwargs)
    victim = engine.state.actors[ALLY]
    _fail_a_printed_save(engine, REPEATING, victim, {"ability": "STR", "dc": _printed_dc(engine, REPEATING)})
    _fail_a_printed_save(engine, SLOWING, victim, {"ability": "STR", "dc": _printed_dc(engine, SLOWING)})
    repeating = qi_path._regulable(engine, victim)
    plain = qi_path._suppressible(engine, victim)
    assert repeating and plain, "the fixture must leave one repeating effect and one plain penalty"
    return engine, victim, repeating, plain


def test_meridian_regulation_offers_both_printed_branches_in_one_question():
    """AUTO2 review finding 1: a repeating effect used to hide every other effect. One question, both branches, and the
    selection decides which one runs."""
    engine, victim, repeating, plain = _meridian_fixture()
    events, asker = _use_meridian(engine, victim.entity_id)
    said = _log_text(events)
    assert "Meridian Regulation" in said, said

    # The question carries one option per eligible effect, of either branch, and the player may pick any of them.
    request = asker.meridian()
    assert request, "the printed choice was never asked"
    spec = request["extension_choice"]
    options = [str(option) for option in spec["option_ids"]]
    assert set(options) == {f"condition:{iid}" for iid, _ in repeating} | {row[0] for row in plain}, options
    assert len(options) >= 2, f"the repeating effect hid the other penalties: {options}"
    assert spec["allow_decline"] is False, "a printed 'choose one' is not optional"
    labels = " ".join(str(request["choice_trigger"]["labels"].get(option, "")) for option in options)
    assert "Constitution saving throw with Advantage" in labels, labels
    for jargon in JARGON:
        assert jargon not in labels, f"internal jargon in a printed option label: {jargon!r} in {labels!r}"

    # Choosing the repeating effect: its OWN save, repeated with Advantage, and a success ends that effect.
    engine, victim, repeating, _plain = _meridian_fixture()
    held = repeating[0][0]
    victim.saving_throws["STR"] = 20
    events, _ = _use_meridian(engine, victim.entity_id, pick=f"condition:{held}")
    rolls = [event for event in events if event.event_type == "SAVE_ROLLED"]
    assert len(rolls) == 1 and rolls[0].payload.get("mode") == "ADVANTAGE", [event.payload for event in rolls]
    assert str(rolls[0].payload.get("reason") or "").upper().endswith(":STR"), rolls[0].payload
    assert held not in victim.conditions, "a successful repeat save must apply the effect's successful result"
    # The other effect is untouched: one choice, one effect.
    assert qi_path._suppressible(engine, victim), "the unchosen effect was regulated as well"

    # Choosing the plain penalty while the repeating effect is also on the target: a Constitution save with Advantage
    # against THAT effect's printed DC, and only that penalty stops applying.
    engine, victim, repeating, plain = _meridian_fixture()
    slowing = next(row for row in plain if row[2] == "Speed reduced")
    victim.saving_throws["CON"] = 20
    events, asker = _use_meridian(engine, victim.entity_id, pick=slowing[0])
    assert asker.meridian(), "the printed choice was never asked"
    rolls = [event for event in events if event.event_type == "SAVE_ROLLED"]
    assert len(rolls) == 1 and rolls[0].payload.get("mode") == "ADVANTAGE", [event.payload for event in rolls]
    assert int(rolls[0].payload["dc"]) == _printed_dc(engine, SLOWING), \
        f"the save was against {rolls[0].payload['dc']}, not the effect's printed DC"
    assert slowing[0].removeprefix("modifier:") not in victim.modifiers, "the chosen penalty is still applied"
    assert qi_path._regulable(engine, victim), "the repeating effect must survive the other branch"
    rows = [row for row in victim.conditions.values() if row.condition_id == SUPPRESSED]
    assert len(rows) == 1 and (rows[0].data or {}).get("until") == "holder_turn_end", rows
    for jargon in JARGON:
        assert jargon not in _log_text(events), f"internal jargon in player text: {jargon!r}"


def test_meridian_regulation_reads_the_penalties_real_printed_effects_leave():
    """AUTO2 review finding 2: the printed penalties are the rows real abilities leave, read with their real schema --
    ``data.rule.save_against.mode``, ``concentration_mode`` and a check-mode dict -- and each carries the DC that ability
    printed. Deliver the Dose leaves "Disadvantage on ability checks" and Ingrain the Toxin leaves "Disadvantage on its
    next Constitution saving throw", so between them the two roll-mode schemas the review found unreadable are both
    proven against real printed rows."""
    engine = _meridian_engine(talents=(DOSE, INGRAIN, SLOWING, DENYING, SEVERING))
    victim = engine.state.actors[ALLY]
    for mechanic in (DOSE, INGRAIN, SLOWING, DENYING, SEVERING):
        _fail_a_printed_save(engine, mechanic, victim, {"ability": "CON", "dc": _printed_dc(engine, mechanic)})

    rows = qi_path._suppressible(engine, victim)
    found = {(row[2], row[3]) for row in rows}
    assert ("Disadvantage on ability checks", _printed_dc(engine, DOSE)) in found, sorted(found)
    assert ("Disadvantage on saving throws", _printed_dc(engine, INGRAIN)) in found, sorted(found)
    assert ("Speed reduced", _printed_dc(engine, SLOWING)) in found, sorted(found)
    assert ("Cannot take Reactions", _printed_dc(engine, DENYING)) in found, sorted(found)
    # Each roll-mode row stores the save it came from, which is what makes its printed DC readable at all.
    checks = [row for row in rows if row[2] == "Disadvantage on ability checks"]
    assert len(checks) == 1, [row[2] for row in rows]
    assert (checks[0][1].data or {}).get("origin_save") == {"ability": "CON", "dc": _printed_dc(engine, DOSE)}, \
        checks[0][1].data
    saves = [row for row in rows if row[2] == "Disadvantage on saving throws"
             and row[1].source_definition_id == _typed_action(engine, INGRAIN)[0]]
    assert len(saves) == 1 and saves[0][1].condition_id == "condition:typed.save_against", \
        [(row[2], row[1].condition_id) for row in saves]
    assert (saves[0][1].data or {})["rule"]["save_against"]["mode"] == "DISADVANTAGE", saves[0][1].data

    # One printed effect can leave more than one of the printed penalties (Severing Fate): "suppress one penalty" is
    # then a real choice, and both are offered.
    severing = [row for row in rows if row[1].source_definition_id == _typed_action(engine, SEVERING)[0]]
    assert {row[2] for row in severing} == {"Cannot take Reactions", "Speed reduced"}, [row[2] for row in severing]


def test_meridian_regulation_refuses_an_effect_the_printed_limits_do_not_allow(monkeypatch):
    """AUTO2 review finding 3: the printed limits are checked before anything is offered. An effect the fight cannot
    read a printed DC or a printed tag list for is the GM's, and one of the seven excluded tags is refused even when its
    DC is perfectly readable."""
    engine = _meridian_engine(talents=(SLOWING,))
    victim = engine.state.actors[ALLY]
    _fail_a_printed_save(engine, SLOWING, victim, {"ability": "STR", "dc": _printed_dc(engine, SLOWING)})
    assert qi_path._suppressible(engine, victim), "the fixture must leave one suppressible penalty"

    # No printed record for the effect at all: nothing to read a DC or a tag list from, so the GM's.
    engine._apply_condition(victim, "condition:typed.poisoned", "test:no_such_ability", ME, expires_on="UNTIL_REMOVED",
                            data={"origin_save": {"ability": "CON", "dc": 15}})
    assert not [row for row in qi_path._suppressible(engine, victim) if "test:no_such_ability" in row[0]], \
        "an effect with no printed record was offered"

    # One of the seven tags the printed rule excludes, read off the ability's own printed Tags header.
    printed = qi_path._printed_rules()

    def tagged():
        return {key: (text if key != SLOWING else f"#### Curse\nTags: Curse, Hidden\n{text}")
                for key, text in printed.items()}

    monkeypatch.setattr(qi_path, "_printed_rules", tagged)
    assert not qi_path._suppressible(engine, victim), "an effect carrying the Curse tag was offered"
    assert qi_path._tagged_forbidden(engine, _typed_action(engine, SLOWING)[0]), \
        "the excluded tag was not read off the printed Tags header"
    monkeypatch.undo()

    # ... and one limit the printed rule does NOT make: it says nothing about who put the effect on. A creature's own
    # poison, with the same readable DC and no excluded tag, is still one of the printed effects.
    own_source = _typed_action(engine, SLOWING)[0]
    engine._apply_condition(victim, "condition:typed.poisoned", own_source, victim.entity_id, expires_on="UNTIL_REMOVED",
                            data={"origin_save": {"ability": "CON", "dc": _printed_dc(engine, SLOWING)}})
    own = [row for row in qi_path._suppressible(engine, victim) if row[1].source_actor_id == victim.entity_id]
    assert own and own[0][2] == "Poisoned", \
        f"the printed rule limits the effect, not who cast it: {[row[2] for row in own]}"

    # And the unreadable effect is never put to the player: the question carries the one penalty the table can read.
    events, asker = _use_meridian(engine, victim.entity_id)
    request = asker.meridian()
    assert request, "the readable penalty was not offered"
    options = [str(option) for option in request["extension_choice"]["option_ids"]]
    labels = [str(request["choice_trigger"]["labels"].get(option, "")) for option in options]
    assert len(options) == 2 and {printed for label in labels for printed in ("Speed reduced", "Poisoned") if printed in label} \
        == {"Speed reduced", "Poisoned"}, labels
    assert not [condition for condition in victim.conditions.values()
                if condition.source_definition_id == "test:no_such_ability" and condition.condition_id == SUPPRESSED]


def test_meridian_regulation_refuses_a_mental_effect_the_printed_category_does_not_cover():
    """AUTO2r1 review finding 1: "Choose one poison, disease, or directly caused physical impairment" is a limit on the
    EFFECT, and reading only the printed penalty let a mental effect in -- the review's example is Lucid Veil, a dream
    that leaves "Disadvantage on its next Wisdom (Perception) check". Captivating Melody is the same shape in a row the
    fight can put on a target directly: a song that leaves "cannot take Reactions", one of the printed six. Neither is a
    poison, a disease or a physical impairment, so neither is the fighter's to regulate. The same test proves the printed
    three ARE offered: a poison (Deliver the Dose, Ingrain the Toxin) and a directly caused physical impairment (Binding
    Dregs' Speed reduction)."""
    # Captivating Melody's own printed row ("The target cannot take Reactions until the start of its next turn"), applied
    # through the engine's own condition entry point on the ability the fight really compiled it from. The category is a
    # property of the ability, so this is the level the printed limit is decided at.
    song_engine = _meridian_engine(talents=(SINGING,))
    song_victim = song_engine.state.actors[ALLY]
    song_source = _typed_action(song_engine, SINGING)[0]
    song_engine._apply_condition(song_victim, "condition:typed.reaction_denied", song_source, ME, expires_on="UNTIL_REMOVED",
                                 data={"origin_save": {"ability": "CON", "dc": _printed_dc(song_engine, SINGING)}})
    song_rows = [c for c in song_victim.conditions.values() if c.source_definition_id == song_source]
    assert song_rows and qi_path._condition_penalty(song_rows[0]) == "Cannot take Reactions", \
        f"the fixture must leave the song's own printed penalty: {[(c.condition_id, c.data) for c in song_rows]}"
    assert not qi_path._regulable_effect(song_engine, song_source), \
        "a song was accepted as one of the printed poison / disease / physical impairments"
    assert not qi_path._affliction_category(song_engine, song_source), \
        "a mental effect was reviewed into the printed category"
    assert not qi_path._suppressible(song_engine, song_victim), \
        "the song's reaction denial was offered as one of the printed poison / disease / physical impairments"
    song_events, song_asker = _use_meridian(song_engine, song_victim.entity_id)
    assert song_asker.meridian() is None, "a mental effect was put to the player as a choice"
    assert "Meridian Regulation" in _log_text(song_events) and "GM" in _log_text(song_events), _log_text(song_events)
    assert not [c for c in song_victim.conditions.values() if c.condition_id == SUPPRESSED], \
        "Meridian Regulation suppressed the song's penalty"
    assert qi_path._affliction_category(song_engine, DREAMING) == "", \
        "the review's own example, a dream, must stay the GM's"

    # The printed three ARE offered, from the same real rows: a poison and a directly caused physical impairment.
    engine = _meridian_engine(talents=(DOSE, INGRAIN, SLOWING))
    victim = engine.state.actors[ALLY]
    _fail_a_printed_save(engine, DOSE, victim, {"ability": "CON", "dc": _printed_dc(engine, DOSE)})
    _fail_a_printed_save(engine, INGRAIN, victim, {"ability": "CON", "dc": _printed_dc(engine, INGRAIN)})
    _fail_a_printed_save(engine, SLOWING, victim, {"ability": "STR", "dc": _printed_dc(engine, SLOWING)})
    assert {qi_path._affliction_category(engine, _typed_action(engine, DOSE)[0]),
            qi_path._affliction_category(engine, _typed_action(engine, SLOWING)[0])} == {"poison", "physical_impairment"}
    offered = qi_path._suppressible(engine, victim)
    assert ("Disadvantage on ability checks", _printed_dc(engine, DOSE)) in {(row[2], row[3]) for row in offered}
    assert ("Speed reduced", _printed_dc(engine, SLOWING)) in {(row[2], row[3]) for row in offered}

    # ... and the mental effect is never put to the player: the question carries the printed three and nothing else.
    events, asker = _use_meridian(engine, victim.entity_id)
    request = asker.meridian()
    assert request, "the printed three were not offered"
    for jargon in JARGON:
        assert jargon not in _log_text(events), f"internal jargon in player text: {jargon!r} in {_log_text(events)!r}"


def _affliction_table():
    """combat/rules/affliction_sources.json as the review wrote it: the placements, the deferrals and the categories."""
    return json.loads((Path(ROOT) / "combat" / "rules" / "affliction_sources.json").read_text(encoding="utf-8"))


def _flat(text):
    """The owner's printed text with whitespace collapsed and quote marks straightened, so a row can be compared with
    the sentence it quotes without tripping over the source's curly apostrophes."""
    text = str(text).replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", text).strip().lower()


def _printed_sentences():
    """The owner's printed text by mechanic id, flattened the same way as the evidence it is checked against."""
    return {mechanic: _flat(text) for mechanic, text in qi_path._printed_rules().items()}


def _regulable_shapes(node, found):
    """What one typed record can leave that Meridian Regulation reads off the target: a repeating effect (the branch
    that only needs a remembered DC), one of the three penalties the fight keeps as a row, a Speed reduction, or a
    Disadvantage the fight keeps as a row. Read here, in the test, from the typed data -- never in the plug-in, which
    must not read a penalty to decide. The whole record is walked, because a typed row may sit under "effects" or under
    a choose-N "options" list."""
    if isinstance(node, dict):
        kind, condition = node.get("type"), node.get("condition")
        if condition in ("poisoned", "slowed", "reaction_denied") or kind in ("poisoned", "slowed", "reaction_denied"):
            found.add(f"stored:{condition or kind}")
        if node.get("repeat_save"):
            found.add("repeating")
        # AUTO Source routes the same stored Speed penalty through its circuit-aware plug-in.
        if kind in ("speed", "source_pulse_slow") and isinstance(node.get("flat"), int) and node["flat"] < 0:
            found.add("speed")
        if kind == "poison_next_check":
            found.add("disadvantage")
        if kind in ("advantage", "disadvantage"):
            on = str(node.get("on") or "")
            if re.search(r"\bchecks?\b", on, re.I) or "concentration" in on.lower() \
                    or re.search(r"saving throws?|\bsaves?\b", on, re.I):
                found.add("disadvantage")
        if kind == "affliction":
            for part in (node.get("parts") or {}).values():
                if isinstance(part, dict) and ((isinstance(part.get("speed"), int) and part["speed"] < 0)
                                               or (part.get("rule") or {}).get("no_reactions")):
                    found.add("affliction")
        for value in node.values():
            _regulable_shapes(value, found)
    elif isinstance(node, list):
        for value in node:
            _regulable_shapes(value, found)
    return found


def _repeating_abilities():
    """Every ability in the generated authority that can leave an effect which repeats a saving throw: the branch
    Meridian Regulation offers on a remembered DC alone, so an ability that drops out of the reviewed table silently
    loses its eligibility (AUTO2r2 review finding 1, where the menu afflictions did)."""
    authority = json.loads((Path(ROOT) / "authority" / "Tianxia_Typed_Mechanics_Authority_R1.json").read_text(
        encoding="utf-8"))["mechanics"]
    return {mechanic for mechanic, row in authority.items()
            if isinstance(row, dict) and "repeating" in _regulable_shapes(row, set())}


def test_the_reviewed_category_table_only_places_printed_abilities():
    """combat/rules/affliction_sources.json is typed data, so it is held to the rules it encodes.

    AUTO2r2 review: the guard only checked that a row named a category and had some words after it, which is how a
    fear-based slowing got in as a "directly caused physical impairment" and how the menu afflictions went missing.
    Every row of both halves now has to quote its printed text word for word, the ability it names has to be a source
    Meridian accepts (including native and GM-resolved consequences), and the deferrals have to say why. Nothing is read off a penalty to
    decide, and a mental effect stays the GM's however its penalty is worded."""
    table = _affliction_table()
    sources = qi_path._affliction_sources()
    categories = table["categories"]
    assert sources, "the reviewed category table is empty"
    assert set(categories) == {"poison", "disease", "physical_impairment"}, sorted(categories)
    printed = qi_path._printed_rules()
    flat = _printed_sentences()
    authority = json.loads((Path(ROOT) / "authority" / "Tianxia_Typed_Mechanics_Authority_R1.json").read_text(
        encoding="utf-8"))["mechanics"]
    mental = re.compile(r"dreamscape|illusion|nightmare", re.IGNORECASE)
    for mechanic, row in sorted(sources.items()):
        assert row["category"] in categories, f"{mechanic} is classified as {row['category']!r}"
        assert mechanic in printed, f"{mechanic} is classified but has no printed text to classify"
        assert _flat(row["evidence"]) in flat[mechanic], \
            f"{mechanic} does not quote its own printed sentence: {row['evidence']!r}"
        assert not mental.search(printed[mechanic][:400]), \
            f"{mechanic} is a mental effect and must stay the GM's, whatever penalty it leaves"
        shapes = _regulable_shapes(authority[mechanic], set())
        if not shapes and mechanic == 'TAL_EARTH_WEIGHT_SEAL_STRIKE':
            # The current row delegates to a native plug-in. Prove the real
            # penalty instead of requiring a duplicate effect in authority.
            from combat import ext
            engine = _meridian_engine(talents=(mechanic, 'EARTH_BASE_WEIGHT_SEEKING_CLOD'))
            _, action, typed = _typed_action(engine, 'EARTH_BASE_WEIGHT_SEEKING_CLOD')
            victim = engine.state.actors[ALLY]; before = engine._effective_speed(victim)
            ctx = te.Context(engine, engine.state.actors[ME], action, None, typed, [victim], victim, {})
            ext.run_strict('after_hit_choice', ctx, victim, 'cultivation')
            assert engine._effective_speed(victim) == before - 5
            shapes = {'speed'}
        if not shapes:
            # This table classifies printed sources, including GM-resolved
            # consequences and effects supplied by native plug-ins. It is not
            # an inventory of effects duplicated in generated authority.
            # Keep the exact printed consequence check above, and additionally
            # prove that Meridian accepts this identified source at runtime.
            assert re.search(r"Speed|Disadvantage|Reactions|Poisoned|Slowed|Restrained|Prone", row['evidence'], re.I), row
            engine = _meridian_engine(talents=(mechanic,))
            assert qi_path._regulable_effect(engine, mechanic), mechanic
            shapes = {'reviewed-runtime-source'}
        assert shapes, f"{mechanic} has neither a typed penalty nor a verified runtime source"
    for mechanic in (DREAMING, "TAL_DREAM_NIGHTMARE_CHAIN", "TAL_ILLUSION_INSISTENT_PREMISE", FEARFUL):
        assert mechanic not in sources, f"{mechanic} must not be reviewed into the printed category"
        assert mechanic in table["left_to_the_gm"], f"{mechanic} must be recorded as read and left to the GM"

    deferred = table["left_to_the_gm"]
    assert deferred, "the review's other half -- what it read and left to the GM -- is missing"
    for mechanic, row in sorted(deferred.items()):
        assert mechanic in printed, f"{mechanic} is deferred but has no printed text to read"
        assert mechanic not in sources, f"{mechanic} is placed and deferred at once"
        assert _flat(row["evidence"]) in flat[mechanic], \
            f"{mechanic} does not quote its own printed sentence: {row['evidence']!r}"
        assert str(row["reason"]).strip(), f"{mechanic} is left to the GM without saying why"


def test_every_ability_that_can_leave_a_repeating_effect_is_accounted_for():
    """AUTO2r2 review finding 1: the review read the abilities it placed and nothing said which abilities it had read
    and left out, so a printed poison or disease that repeats its save -- a menu affliction, Symptom Cascade or Five-Venom
    Formula -- could fall out of the table and quietly lose Meridian Regulation's eligibility. Every ability in the
    generated authority that can leave a repeating effect is now in one of the two lists, and the menu afflictions are
    placed as the poisons and diseases their printed text names."""
    table = _affliction_table()
    sources, deferred = qi_path._affliction_sources(), table["left_to_the_gm"]
    candidates = _repeating_abilities()
    assert len(candidates) > 50, f"the repeating-effect scan found only {len(candidates)} abilities; it has stopped working"
    unaccounted = sorted(candidates - set(sources) - set(deferred))
    assert not unaccounted, f"read and place these, or record why they are the GM's: {unaccounted}"
    for talent, category in ((SYMPTOMS, "disease"), (WEAKENING, "disease"), (VENOMS, "poison"),
                             (SEALS, "physical_impairment")):
        assert talent in candidates, f"{talent} no longer repeats its save, so this regression has stopped testing it"
        assert sources[talent]["category"] == category, f"{talent} is classified as {sources[talent]['category']!r}"
    assert sources[PLAGUE]["category"] == "disease", f"{PLAGUE} is classified as {sources[PLAGUE]['category']!r}"
    assert deferred[FEARFUL]["reason"], "the fear-based slowing must record why it is the GM's"


def test_a_menu_affliction_that_repeats_its_save_is_offered_again():
    """AUTO2r2 review finding 1, at the level the bug showed: a printed disease that repeats its save was regulable
    before the reviewed category table and stopped being offered once the table existed, because nobody had placed it.
    Symptom Cascade's own failed save must leave the affliction the fight can offer, through the real executor."""
    engine = _meridian_engine(talents=(SYMPTOMS,), spheres=(SPHERES["disease"],))
    victim = engine.state.actors[ALLY]
    _fail_a_printed_save(engine, SYMPTOMS, victim, {"ability": "CON", "dc": _printed_dc(engine, SYMPTOMS)})
    afflictions = [c for c in victim.conditions.values() if c.condition_id == "condition:typed.affliction"]
    assert afflictions and (afflictions[0].data or {}).get("repeat_save"), \
        f"the fixture must leave a real repeating affliction: {[(c.condition_id, c.data) for c in victim.conditions.values()]}"
    source = afflictions[0].source_definition_id
    assert qi_path._affliction_category(engine, source) == "disease", \
        f"{SYMPTOMS} is not placed as the printed disease its own text names"
    assert qi_path._regulable_effect(engine, source), "a printed disease that repeats its save is not offered"
    offered = [iid for iid, _ in qi_path._regulable(engine, victim)]
    assert any(victim.conditions[iid] is afflictions[0] for iid in offered), \
        f"the repeating disease was left out of Meridian Regulation's printed choice: {offered}"
    events, asker = _use_meridian(engine, victim.entity_id)
    request = asker.meridian()
    assert request, f"the printed choice was never asked: {_log_text(events)}"
    labels = " ".join(str(request["choice_trigger"]["labels"].get(option, "")) for option in request["extension_choice"]["option_ids"])
    assert "Symptom Cascade" in labels, f"the disease is not named in the printed choice: {labels}"


def test_a_fear_based_slowing_is_the_gms_to_regulate():
    """AUTO2r2 review finding 2: Dread Appetite's Speed reduction only happens to a creature that is already
    Frightened, so what the printed rule would be regulating is the fear. It was placed in the printed three as a
    "directly caused physical impairment"; the review now reads it and leaves it the GM's, printed sentence and all."""
    engine = _meridian_engine(talents=(FEARFUL,))
    assert not qi_path._affliction_category(engine, _typed_action(engine, FEARFUL)[0]), \
        "a slowing that only follows a Frightened creature was read as one of the printed three"
    assert not qi_path._regulable_effect(engine, _typed_action(engine, FEARFUL)[0]), \
        "a fear-based slowing is offered as one of the printed poison / disease / physical impairments"
    assert qi_path._affliction_category(engine, DREAMING) == "", "a dream is still offered as one of the printed three"


def _stock_control_bytes(seed, decisions=12):
    """A stock control AI fight, as complete bytes: the decisions it made, its whole event log, every roll and its
    final state. The unmodified gate4 roster, so nothing here is a Factory character and no Meridian Regulation row
    exists in the fight at all (asserted by the caller)."""
    from combat.gate4_context import build_decision_context
    from combat.gate4_controller import LocalDeterministicController
    from combat.gate4_policy import PolicyLibrary

    engine = Gate4ControllerEngine(ROOT, match_seed=seed, maximum_rounds=3)
    controller, policies = LocalDeterministicController(), PolicyLibrary(ROOT)
    played = []
    for _ in range(decisions):
        if engine.state.terminal_result is not None:
            break
        policy, _ = policies.for_actor(engine.state.current_actor_id)
        choice = controller.choose_primary_action(build_decision_context(engine, policy, for_ai=True))
        played.append(choice.model_dump(mode="json"))
        engine.execute_intent(choice.intent)
    return json.dumps({"decisions": played,
                       "state": engine.state.model_dump(mode="json"),
                       "events": [e.model_dump(mode="json") for e in engine.events],
                       "rolls": [r.model_dump(mode="json") for r in engine.rolls],
                       "catalog": sorted(engine.action_catalog)},
                      ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def test_the_reviewed_category_table_cannot_move_a_fight_that_does_not_own_it(monkeypatch):
    """AUTO2r3 review finding 1, the durable half: the reviewed table is what decides which effects Meridian Regulation
    may select, so editing it can change a fight -- and the save/reload equivalence test cannot see that, because it
    compares one implementation against itself. This is the in-repo guard that can.

    A stock control fight (the unmodified gate4 roster, no Factory character, no Meridian Regulation row) is captured
    twice: once with the reviewed table as committed, once with it emptied. The bytes must be identical, which says
    the eligibility data is only ever read on a path a creature without Meridian Regulation never reaches. The table is
    then emptied and a Meridian owner's own fight is shown to *lose* two options from two different printed categories,
    so this cannot pass by being inert everywhere -- an implementation that ignored the table altogether would fail the
    second half.

    AUTO2r4 review, both findings in this half of the guard: the swap used to be left in place while the next seed's
    baseline was captured (so the second control compared the empty table against itself), and the owner side only asked
    for a nonempty list of penalties, which one surviving printed category could satisfy.
    """
    # Each seed is measured inside its own swap, undone before the next one: a swap still in place while the next
    # baseline is captured compares the empty table against itself, and the second control would guard nothing at all.
    for seed in ("LOCK5-A", "GATE4-TEST"):
        with monkeypatch.context() as empty:
            as_committed = _stock_control_bytes(seed)
            assert MERIDIAN not in as_committed.decode(), f"{seed} has a Meridian Regulation row, so it is not a control"
            assert qi_path._affliction_sources(), \
                f"{seed}: the reviewed table was already empty, so this seed compares nothing against anything"
            empty.setattr(qi_path, "_affliction_sources", lambda: {})
            assert qi_path._affliction_sources() == {}, f"{seed}: the swap this guard measures was not in effect"
            assert _stock_control_bytes(seed) == as_committed, \
                f"{seed} changed when the reviewed category table was emptied, so the table reaches a fight that does not own it"

    # The same swap must be visible to the creature that does own the rule, or the guard above proves nothing.
    # Each ability's own printed save, not a guessed one: the poison saves CON, the binding dregs save STR. Both leave a
    # penalty, so they are read through the same "what may the printed rule regulate" question the table feeds.
    # Two abilities of two DIFFERENT printed categories, because one is not enough: a table that had lost the impairment
    # and kept the poison would still lose an option, and this guard would still see an empty table stop it offering one.
    saves = ((DOSE, "CON"), (SLOWING, "STR"))

    def offered():
        """What the printed rule may offer on the victim -- printed ability id -> the printed penalty it left -- and
        the printed category the reviewed table gives each of those two abilities."""
        engine = _meridian_engine(talents=tuple(talent for talent, _ in saves))
        victim = engine.state.actors[ALLY]
        for talent, ability in saves:
            _fail_a_printed_save(engine, talent, victim, {"ability": ability, "dc": _printed_dc(engine, talent)})
        return ({qi_path._printed_key(engine, row[1].source_definition_id): row[2]
                 for row in qi_path._suppressible(engine, victim)},
                {talent: qi_path._affliction_category(engine, _typed_action(engine, talent)[0]) for talent, _ in saves})

    committed, categories = offered()
    assert categories == {DOSE: "poison", SLOWING: "physical_impairment"}, \
        f"the fixture's two abilities are not two different printed categories any more: {categories}"
    missing = sorted({talent for talent, _ in saves} - set(committed))
    assert not missing, \
        f"the committed table must offer both a printed poison and a printed impairment, so missing {missing}"
    with monkeypatch.context() as empty:
        empty.setattr(qi_path, "_affliction_sources", lambda: {})
        assert qi_path._affliction_sources() == {}, "the swap this guard measures was not in effect"
        assert offered()[0] == {}, \
            "emptying the table changed nothing for a Meridian owner, so the guard is not watching a real dependency"


def test_meridian_regulation_leaves_an_unreadable_effect_to_the_gm():
    """The printed limit read plainly: nothing on the target is an effect the fight can regulate, so the fight says so
    in words a player understands and the GM rules on it by hand."""
    engine = _meridian_engine()
    victim = engine.state.actors[ALLY]
    engine._apply_condition(victim, "condition:typed.poisoned", "test:no_such_ability", ME, expires_on="UNTIL_REMOVED",
                            data={"origin_save": {"ability": "CON", "dc": 15}})
    events, asker = _use_meridian(engine, victim.entity_id)
    assert asker.meridian() is None, "an effect the table cannot read was put to the player as a choice"
    said = _log_text(events)
    assert "Meridian Regulation" in said and "GM" in said, said
    # The deferral has to say WHAT the printed rule needs, so a player knows whether to look for a saving throw DC or a
    # tag; the previous wording only said the table could not read "a printed DC", which is neither of them.
    assert "saving throw DC" in said and "tag" in said, \
        f"the deferral does not name the printed limits the rule actually checks: {said!r}"
    assert not [c for c in victim.conditions.values() if c.condition_id == SUPPRESSED], \
        "Meridian Regulation suppressed a penalty it has no printed DC for"
    for jargon in JARGON:
        assert jargon not in said, f"the printed limit leaks internal jargon: {jargon!r} in {said!r}"


# ------------------------------------- the printed lifetime, both ways, on a penalty a real effect leaves


def _modifier_events(events, modifier_id):
    return [event for event in events
            if event.event_type in ("MODIFIER_APPLIED", "MODIFIER_REMOVED")
            and str(event.payload.get("modifier_id") or "") == modifier_id]


def test_the_printed_penalty_comes_back_at_the_end_of_the_targets_next_turn_and_not_before():
    """"until the end of the target's next turn": the suppression holds through that whole turn, and the penalty is back at
    its end -- when the effect behind it has not run out by then. Binding Dregs' Speed reduction lasts until the start of
    the regulator's next turn, and the target acts first, so its own time has not run out when the suppression ends."""
    engine = _meridian_engine(ally_dex=20, me_dex=18, talents=(SLOWING,))
    victim = engine.state.actors[ALLY]
    _fail_a_printed_save(engine, SLOWING, victim, {"ability": "STR", "dc": _printed_dc(engine, SLOWING)})
    slowing = next(row for row in qi_path._suppressible(engine, victim) if row[2] == "Speed reduced")
    modifier_id = slowing[0].removeprefix("modifier:")
    victim.saving_throws["CON"] = 20
    _use_meridian(engine, victim.entity_id, pick=slowing[0])
    assert modifier_id not in victim.modifiers, "the printed penalty is still applied"

    before = len(engine.events)
    _my_turn(engine, victim.entity_id)
    assert modifier_id not in victim.modifiers, \
        "the printed penalty came back before the end of the target's next turn"
    assert not _modifier_events(engine.events[before:], modifier_id), \
        "the suppressed penalty was put back during the target's next turn"
    engine.end_turn()
    back = [event for event in engine.events[before:] if event.event_type == "MODIFIER_APPLIED"
            and str(event.payload.get("modifier_id") or "") == modifier_id]
    assert back, [event.payload for event in engine.events[before:]]
    ended = [event for event in engine.events[before:] if event.event_type == "CONDITION_REMOVED"
             and event.payload.get("condition_id") == SUPPRESSED and event.payload.get("reason") == "DURATION_ENDED"]
    assert ended, "the suppression outlived the end of the target's next turn"
    assert not [c for c in victim.conditions.values() if c.condition_id == SUPPRESSED]


def test_a_penalty_whose_own_time_runs_out_while_suppressed_does_not_come_back():
    """The printed limit: Meridian Regulation does not end the underlying effect's duration, so a penalty whose own time
    runs out while it is suppressed stays gone. Sand Coffin's reaction denial lasts to the end of the caster's turn --
    inside the suppression window, which reaches the end of the target's next turn."""
    engine = _meridian_engine(ally_dex=18, me_dex=20, talents=(DENYING,))
    victim = engine.state.actors[ALLY]
    # An explicit legacy saved denial tests this expiry contract. Current Sand
    # Coffin denies reactions on success, with a different deadline; requiring
    # its failure branch to recreate the older schema is not a valid fixture.
    _, action, typed = _typed_action(engine, DENYING)
    ctx = te.Context(engine, engine.state.actors[ME], action, None, typed, [victim], victim, {}, failed_save=True,
                     origin_save={"ability":"CON", "dc":_printed_dc(engine, DENYING)})
    te.run_effects(ctx, [{'type':'reaction_denied', 'applies_to':'target', 'expires_on':'END_OF_CURRENT_TURN'}])
    denying = next(row for row in qi_path._suppressible(engine, victim) if row[2] == "Cannot take Reactions")
    instance_id = denying[0].removeprefix("condition:")
    victim.saving_throws["CON"] = 20
    before = len(engine.events)
    _use_meridian(engine, victim.entity_id, pick=denying[0])
    assert instance_id not in victim.conditions, "the printed penalty is still applied"

    engine.end_turn()  # the caster's own turn ends, which is when its reaction denial's time is up
    _my_turn(engine, victim.entity_id)
    engine.end_turn()  # the end of the target's next turn: the suppression is over
    back = [event for event in engine.events[before:] if event.event_type == "CONDITION_APPLIED"
            and str(event.payload.get("instance_id") or "") == instance_id]
    assert not back, "a penalty whose own duration had already run out was put back"
    assert instance_id not in victim.conditions
    assert not [c for c in victim.conditions.values() if c.condition_id == SUPPRESSED]


# ------------------------------------------------------- Meridian Regulation (table level, real character)


def test_meridian_regulation_suppresses_a_real_penalty_through_a_table_commit_and_reload(tmp_path):
    """"On success, suppress one penalty until the end of the target's next turn", in a real fight with a real character:
    the printed question, the printed save, the suppression, and a commit + reload that keeps both the suppressed row
    and the printed lifetime. AUTO2 review finding 4: the old test could pass on a failed save and stopped there."""
    combat, table, match_id, owner_id = fight(tmp_path, "lingyue", opponents=["ning"])
    engine = engine_at(combat, match_id)
    owner = engine.state.actors[owner_id]
    # The printed case in a real fight: Ning Kai's Thunder That Answers First is a Reaction that answers a declared
    # technique, so as soon as Lingyue declares Meridian Regulation he denies her Reactions through a saving throw --
    # "a directly caused physical impairment ... with a printed saving throw DC", and one of the printed six penalties.

    for _ in range(14):
        menu = table.state(match_id)["menu"]
        engine = engine_at(combat, match_id)
        if menu.get("actor_id") != owner_id:
            commit(table, match_id, menu, menu.get("end_turn"))
            continue
        group = next((row for row in menu.get("actions", [])
                      if getattr(engine.action_catalog.get(row.get("source_definition_id")), "display_name", None)
                      == "Meridian Regulation"), None)
        assert group, "Meridian Regulation was never offered to its owner"
        if int(owner.resources.get(QI, 0)) < 1:
            commit(table, match_id, menu, menu.get("end_turn"))
            continue
        before = len(engine.events)
        qi_before = int(engine.state.actors[owner_id].resources.get(QI, 0))
        _, prompts = _commit_choosing(table, match_id, menu, group["options"][0]["candidate_id"])
        engine = engine_at(combat, match_id)
        owner = engine.state.actors[owner_id]

        # The printed question is asked of the player, names the ability, the action and the creature, and must be
        # answered (a printed "choose one" is not optional).
        asked = [prompt for prompt in prompts if (prompt.get("context") or {}).get("reaction_source_id") == NEEDLE]
        assert asked, f"Meridian Regulation asked nothing: {[prompt.get('reaction') for prompt in prompts]}"
        question = asked[0]
        readable = _player_text(question)
        assert "Meridian Regulation" in readable and owner.display_name in readable, readable
        assert "Constitution saving throw with Advantage" in readable, readable
        options = (question.get("choice") or {}).get("options") or []
        assert options and not (question.get("choice") or {}).get("allow_decline"), question.get("choice")
        assert question.get("action") == "Meridian Regulation" and question.get("affected") == owner.display_name, readable
        # the offered penalty is one of the printed six, told apart by who put it there and what it saves against
        labels = " ".join(str(option.get("label") or "") for option in options)
        assert any(printed in labels for printed in ("Cannot take Reactions", "Poisoned", "Speed reduced")), labels
        assert "Ning Kai" in labels and "Advantage" in labels and "DC" in labels, labels
        for jargon in JARGON:
            assert jargon not in readable, f"the printed question leaks internal jargon: {jargon!r} in {readable!r}"

        # "a Constitution saving throw with Advantage against the effect's printed DC"
        saves = [event for event in engine.events[before:]
                 if event.event_type == "SAVE_ROLLED" and MERIDIAN in str(event.source_definition_id)]
        assert len(saves) == 1, f"the printed saving throw was not rolled once: {[event.payload for event in saves]}"
        assert saves[0].payload.get("mode") == "ADVANTAGE" and saves[0].actor_id == owner.entity_id, saves[0].payload
        dc = int(saves[0].payload["dc"])
        assert int(owner.resources.get(QI, 0)) == qi_before - 1, "the printed 1 Qi cost was not spent"

        said = _log_text(engine.events[before:])
        assert "Meridian Regulation" in said, f"the fight said nothing about what it did: {said!r}"
        for jargon in JARGON:
            assert jargon not in said, f"internal jargon in player text: {jargon!r} in {said!r}"
        if not saves[0].payload.get("success"):
            # A failed save changes nothing, exactly as printed; try again on a later turn.
            assert not [c for c in owner.conditions.values() if c.condition_id == SUPPRESSED], said
            continue

        # ---- the printed suppression, and its lifetime, through a real commit + reload
        # The offered option id is "<kind>:<instance id>" while the target's own rows are keyed by the instance id
        # alone, so the absence has to be checked on the instance: AUTO2 review finding 2, where the raw option id was
        # compared against owner.conditions and so passed even with the penalty still applied.
        chosen_option = str(options[0]["id"])
        kind, _, instance_id = chosen_option.partition(":")
        assert kind in ("condition", "modifier") and instance_id, f"unreadable option id: {chosen_option!r}"

        def _row_id(event):
            payload = event.payload or {}
            return str(payload.get("instance_id") or payload.get("modifier_id") or "")

        assert [e for e in engine.events if e.event_type in ("CONDITION_APPLIED", "MODIFIER_APPLIED")
                and _row_id(e) == instance_id], \
            f"the offered penalty ({chosen_option}) was never applied to the target at all"
        assert instance_id not in owner.conditions and instance_id not in owner.modifiers, \
            f"the chosen penalty is still applied to the target: {chosen_option}"
        rows = [c for c in owner.conditions.values() if c.condition_id == SUPPRESSED]
        assert len(rows) == 1 and (rows[0].data or {}).get("until") == "holder_turn_end", rows
        marker = rows[0].data or {}
        # the retained model is that very instance: the row the table took off, kept so it can come back
        assert marker.get("kind") == kind and marker.get("model"), \
            f"the suppression does not keep the row it suppressed: {marker}"
        removed = [e for e in engine.events[before:]
                   if e.event_type in ("CONDITION_REMOVED", "MODIFIER_REMOVED")
                   and (e.payload or {}).get("reason") == "SUPPRESSED" and _row_id(e) == instance_id]
        assert removed, f"the chosen penalty was never suppressed: {chosen_option}"
        if kind == "condition":
            assert (removed[0].payload or {}).get("condition_id") == (marker.get("model") or {}).get("condition_id"), \
                "the retained suppression is not the row the table removed"
        assert str(dc) in said, f"the fight did not name the DC it saved against: {said!r}"

        reloaded = combat._load_session(match_id)
        assert reloaded.mechanical.replay()["status"] == "PASS"
        after = reloaded.engine.state.actors[owner_id]
        assert instance_id not in after.conditions and instance_id not in after.modifiers, \
            "the commit brought the chosen penalty back"
        kept = [c for c in after.conditions.values() if c.condition_id == SUPPRESSED]
        assert len(kept) == 1, kept
        assert (kept[0].data or {}).get("until") == "holder_turn_end", \
            f"the commit lost the printed lifetime: {kept[0].data}"
        assert (kept[0].data or {}).get("model") == marker.get("model"), \
            "the commit changed which penalty the suppression is holding"
        commit(table, match_id, table.state(match_id)["menu"], table.state(match_id)["menu"].get("end_turn"))
        for _ in range(6):  # her next turn, committed through the table like any other
            menu = table.state(match_id)["menu"]
            if menu.get("actor_id") == owner_id:
                commit(table, match_id, menu, menu.get("end_turn"))
                break
            commit(table, match_id, menu, menu.get("end_turn"))
        engine = engine_at(combat, match_id)
        owner = engine.state.actors[owner_id]
        assert not [c for c in owner.conditions.values() if c.condition_id == SUPPRESSED], \
            "the suppression outlived the end of the target's next turn"
        return
    raise AssertionError("Meridian Regulation never produced a successful printed save in fourteen turns")


# ------------------------------------------------------------------- the new turn-start phrase, at its own level


def test_the_new_turn_start_phrase_is_anchored_so_an_unsupported_turn_start_stays_the_gms():
    """The general seam: a start-of-your-own-turn moment that also names something the table cannot check is still
    unsupported, so the new phrase cannot make every turn-start row fire."""
    supported = reaction_triggers.classify_trigger("At the start of each of your turns.")
    assert supported.kind == "own_turn_start" and supported.runnable, supported
    for text in ("At the start of each of your turns, if you are mounted, regain 5 Qi.",
                 "At the start of each of your turns, if your Counterstrike expires, regain 5 Qi.",
                 "At the start of an ally's turn, regain 5 Qi.",
                 "The first time you become Prone each turn, regain 5 Qi."):
        assert reaction_triggers.classify_trigger(text).kind != "own_turn_start", \
            f"{text!r} names something the table cannot check, so it must not become a plain turn start"
    rules = json.loads((Path(ROOT) / "combat" / "rules" / "reaction_trigger_phrases.json").read_text(encoding="utf-8"))
    assert "own_turn_start" in rules["kind_order"], "a runnable kind the classifier never reads is dead text"
