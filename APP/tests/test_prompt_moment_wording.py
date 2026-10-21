"""Ask-me prompt "moment" text reads as plain English for every trigger kind.

Hunt 78 finding #1 (P2): two prompts read as broken English and one asserted a creature healed by
itself. ``combat/decision_text.py``'s shared moment builder spliced the raw checkpoint word into a
sentence ("Corpse Servant 2 healed from Corpse Servant 2.", "Lan Hongmu initiative from Lian Feng.").

The engine raises a trigger *kind* and the builder reads it as the change it describes, so one
table serves every ability: healed / damaged / moved / targeted, whether the creature caused it or
another did, and whether the healing or action is known or missing.
"""
import pytest

from combat.decision_text import build_decision_text, trigger_text
from combat.tabletop_service import _rules_texts
from tests.test_lock2_persistence import act
from tests.test_tabletop_hunt6 import table_fight, on_hold, LEFT, ALLY, RIGHT, HOLD


def ask(moment, *, target="Left", actor="", action="", reactor="Left", said=None, named_target=True):
    """One Ask-me prompt as combat/tabletop_service.py hands it to the shared builder.

    ``target`` is the creature the moment happened to (choice_trigger.affected_id) and ``actor`` is
    the one that did it (choice_trigger.actor_id) -- the two are the same creature in a self-source.
    """
    actors = {"actor:owner": reactor, "actor:target": target, "actor:actor": actor}
    trigger = {"affected_id": "actor:target"} if named_target else {}
    if actor:
        trigger["actor_id"] = "actor:actor"
    context = {"reactor_id": "actor:owner", "choice_trigger": trigger, "recent_events": [],
               "checkpoint": f"TYPED:{moment}@205"}
    prompt = {"reactor": reactor, "reaction": "Grave Tax", "action": action,
              "moment": said if said is not None else moment.replace("_", " ").lower(),
              "by": actor, "affected": target if named_target else ""}
    return trigger_text(context, prompt, actors, {})


# ------------------------------------------------------------------ the two reported prompts
def test_a_creature_is_never_named_as_its_own_healer():
    """Hunt 78 H78-03: "Corpse Servant 2 healed from Corpse Servant 2." The healer is a different
    creature, so naming the healed one as the source was untrue, not merely clumsy."""
    assert ask("HEALED", target="Corpse Servant 2", actor="Corpse Servant 2") == \
        "Corpse Servant 2 regained hit points."


def test_initiative_reads_as_a_roll_not_a_bare_noun():
    """Hunt 78 H78-13: "Lan Hongmu initiative from Lian Feng." -> the creature rolled for initiative."""
    assert ask("INITIATIVE", target="Lan Hongmu", actor="Lian Feng") == "Lian Feng rolled for initiative."


# ------------------------------------------------------------------ every trigger kind
@pytest.mark.parametrize("moment,expected", [
    ("HEALED", "Left regained hit points"),
    ("TEMP_HP_GAINED", "Left gained Temporary hit points"),
    ("CP_RESTORED", "Left regained cultivation points (its Path resource)"),
    ("BECAME_HIDDEN", "Left became Hidden"),
    ("DAMAGED", "Left took damage"),
    ("BLOODIED", "Left fell to half its hit points"),
    ("DROP_TO_ZERO", "Left fell to 0 hit points"),
    ("CONDITION_GAINED", "Left gained a condition"),
    ("CRITICAL_HIT", "Left was hit by a critical hit"),
    ("NATURAL_1", "Left was missed by a natural 1"),
    ("ATTACKED", "Left was targeted by an attack"),
    ("HIT", "Left was hit"),
    ("MISSED", "Left missed with an attack"),
    ("SAVE", "Left failed a saving throw"),
    ("SAVE_RESULT_BEFORE_DECLARED", "Left failed a saving throw"),
    ("GRAPPLE_FAILED", "Left was not grabbed"),
    ("OWN_ACTION", "Left used an ability"),
    ("OWN_TURN_START", "Left started its turn"),
    ("OWN_HIT", "Left hit a creature with an attack"),
    ("OWN_KILL", "Left defeated a creature with an attack"),
    ("OWN_SAVE_SUCCEEDED", "Left passed a saving throw"),
    ("OWN_D20_FAIL", "Left failed a d20 roll"),
    ("LEAVES_REACH", "Left moved out of reach"),
    ("FORCED_MOVED", "Left was pushed or pulled"),
    ("TECHNIQUE_USED", "Left was targeted by a technique"),
    ("TECHNIQUE_TARGETS", "Left was targeted by a technique"),
    ("ATTACK_RESOLVED", "Left finished an attack"),
])
def test_each_trigger_kind_reads_as_a_sentence(moment, expected):
    assert ask(moment) == f"{expected}."


@pytest.mark.parametrize("moment,expected", [
    ("CREATURE_ACTED", "Right used an ability"),
    ("CREATURE_ATTACK_MISSED", "Right missed with an attack"),
    ("MULTI_DAMAGE", "Right damaged two or more creatures with one effect"),
    ("CREATURE_TURN_START", "Right started its turn"),
    ("CREATURE_D20", "Right rolled a d20"),
    ("CREATURE_NAT", "Right rolled a d20"),
    ("CREATURE_SAVE_FAILED", "Right failed a saving throw"),
    ("CREATURE_SAVE_SUCCEEDED", "Right passed a saving throw"),
    ("INITIATIVE", "Right rolled for initiative"),
])
def test_a_kind_whose_subject_is_the_acting_creature_names_that_creature(moment, expected):
    assert ask(moment, actor="Right") == f"{expected}."


@pytest.mark.parametrize("moment", [
    "ALLY_ATTACKED", "ALLY_HIT", "ALLY_MISSED", "ALLY_DAMAGED", "ALLY_DROP_TO_ZERO",
    "ALLY_CONDITION_GAINED", "ALLY_FORCED_MOVED", "ALLY_TURN_START", "ALLY_GRAPPLE_SUCCEEDED",
])
def test_an_ally_kind_names_the_ally_and_never_a_second_source(moment):
    """An ally_* kind is fired by the ally's own event, so the ally is the subject: name the ally the
    engine names, and never credit a separate "from ..." source for the ally's own act.

    The old wording said only "An ally ...", which left a player with several allies unable to tell
    which one's turn started or which one was hit (MMX55r finding 3)."""
    said = ask(moment, target="Right", actor="Right")
    assert said.startswith("Right ") and said.endswith("."), said
    assert " from " not in said
    # Nothing known about the ally: say an ally rather than name the reactor wrongly.
    assert ask(moment, target="Left", actor="").startswith("An ally "), moment


# ------------------------------------------------------------------ self vs other, named vs missing
def test_a_healing_from_another_creature_names_that_creature():
    assert ask("HEALED", target="Right", actor="Ding Shanlan") == "Right regained hit points from Ding Shanlan."


def test_a_named_action_is_attributed_to_the_creature_that_used_it():
    assert ask("HEALED", target="Right", actor="Ding Shanlan", action="Healing Word") == \
        "Right regained hit points from Ding Shanlan's Healing Word."


def test_an_unknown_healer_is_not_invented():
    """A missing action name must not become a blank or a doubled name; the sentence still reads."""
    assert ask("HEALED", target="Right", actor="Ding Shanlan", action="") == \
        "Right regained hit points from Ding Shanlan."


def test_damage_still_names_the_attacker():
    assert ask("DAMAGED", target="Left", actor="Right", action="Gun (Staff) attack") == \
        "Left took damage from Right's Gun (Staff) attack."


# ------------------------------------------------------------------ the guarded fallback
def test_an_unknown_checkpoint_is_never_spliced_into_a_sentence():
    """A plugin checkpoint has no plain wording here. Say what is true rather than print
    "Left toward the grave from Right"."""
    said = ask("TOWARD_THE_GRAVE", target="Left", actor="Right")
    assert "toward the grave" not in said.casefold()
    assert said.endswith(".")


def test_owner_wording_that_is_already_a_sentence_is_kept():
    """The table's own Ask-me wording (TabletopService._ASK_MOMENTS) is owner prose; keep it."""
    assert ask("FOUNDATION_SPEND", target="Left", actor="Right", said="may spend its Foundation resource") == \
        "Left may spend its Foundation resource from Right."


# ------------------------------------------------------------------ the shared builder, at the table boundary
def test_grave_tax_heal_prompt_at_the_table_reads_as_plain_english(monkeypatch, tmp_path):
    """The reported bug at the level it showed: a real "Ask me" Grave Tax prompt in a table fight.

    Grave Tax's printed trigger is "A creature within 60 feet regains HP or gains Temporary HP", so
    the healed creature is never the healer.
    """
    combat, table, mid = table_fight(tmp_path, ["TAL_DEATH_GRAVE_TAX"], ask=True, ally_talents=[])

    def heal_foe(engine):
        from combat import typed_reactions
        engine.state.actors[LEFT].reaction_available = True
        typed_reactions.on_creature_event(engine, engine.state.actors[RIGHT], "healed")

    on_hold(monkeypatch, heal_foe)
    result = act(table, mid, HOLD)
    assert result["status"] == "REACTION_REQUIRED"
    prompt = result["reaction"]
    assert prompt["context"]["reaction_source_id"] == "reaction:typed.TAL_DEATH_GRAVE_TAX"
    moment = prompt["moment"]
    assert moment == "Right regained hit points.", moment
    assert "healed" not in moment and " from " not in moment
    assert moment == prompt["trigger"]  # the table shows the shared builder's sentence
    # Nothing internal leaks into player-facing text.
    assert "TAL_DEATH" not in moment and "actor:" not in moment and "TYPED:" not in moment


def test_every_runnable_trigger_kind_builds_a_readable_sentence():
    """No engine trigger kind may fall back to a bare checkpoint word in an English sentence.

    The old builder produced exactly "<creature> <checkpoint word> from <creature>."; the
    checkpoint word is never the whole predicate now.
    """
    from combat.reaction_triggers import RUNNABLE_KINDS

    for kind in sorted(RUNNABLE_KINDS):
        said = ask(kind.upper(), target="Left", actor="Right", action="")
        assert said.endswith("."), (kind, said)
        # The checkpoint word is never the whole predicate ("Left multi damage." / "Right moved.").
        predicate = said.split(" ", 1)[1].removesuffix(".")
        assert predicate != kind.replace("_", " ").lower(), (kind, said)


def test_build_decision_text_reports_the_same_sentence_for_a_healed_prompt():
    """The table's one decision builder is the only place the sentence is produced."""
    context = {"reactor_id": "actor:owner", "reaction_source_id": "reaction:typed.TAL_DEATH_GRAVE_TAX",
               "checkpoint": "TYPED:HEALED@205", "recent_events": [],
               "choice_trigger": {"actor_id": "actor:healed", "affected_id": "actor:healed"}}
    prompt = {"reactor": "Ding Shanlan", "reaction": "Grave Tax", "moment": "healed",
              "by": "Corpse Servant 2", "action": "", "affected": "Corpse Servant 2"}
    actors = {"actor:owner": "Ding Shanlan", "actor:healed": "Corpse Servant 2"}
    result = build_decision_text(None, context, prompt, actors, {}, _rules_texts())
    assert result["trigger"] == "Corpse Servant 2 regained hit points."


# ------------------------------------------------------------------ the metadata the engine actually raises
def raised_requests(monkeypatch, fire):
    """Every trigger request the engine raises from a real hook, captured as it is raised.

    ``combat/typed_reactions.py``'s ``_consent`` opens the trigger transport
    (``combat/reaction_trigger.py``) once per moment, and ``contextual_request`` turns that scope
    into the request ``combat/gate5_service.py`` hands the table. Recording it here checks the
    sentences below against what the engine actually raised -- which creature it names as the actor
    and which as the target -- rather than against a hand-written approximation of it. A hook that
    raises no request at all is itself engine truth, so the empty list is returned as it is.
    """
    from contextlib import contextmanager
    from combat import reaction_trigger

    seen = []
    original = reaction_trigger.trigger_scope

    @contextmanager
    def capture(engine, checkpoint, **details):
        with original(engine, checkpoint, **details):
            seen.append(reaction_trigger.contextual_request(engine, {"checkpoint": f"TYPED:{checkpoint}@0"}))
            yield

    monkeypatch.setattr(reaction_trigger, "trigger_scope", capture)
    fire()
    return seen


def raised_request(monkeypatch, fire):
    """The one request a moment raised."""
    requests = raised_requests(monkeypatch, fire)
    assert requests, "the hook raised no trigger metadata"
    return requests[0]


def read(engine, request, reactor_id, *, action=""):
    """The sentence the table reads out of a real engine request.

    The context and prompt fields are the ones ``combat/tabletop_service.py`` passes
    (``_reaction_prompt_fields`` and ``combat/gate4_context.py``); the trigger metadata is the
    engine's own, captured above.
    """
    actors = {actor_id: fighter.display_name for actor_id, fighter in engine.state.actors.items()}
    definitions = {source_id: getattr(row, "display_name", source_id)
                   for source_id, row in engine.action_catalog.items()}
    context = {"reactor_id": reactor_id, "checkpoint": request["checkpoint"],
               "choice_trigger": request.get("choice_trigger") or {},
               "recent_events": request.get("recent_events") or [],
               "attacking_actor_id": request.get("attacking_actor_id"),
               "protected_target_id": request.get("protected_target_id")}
    prompt = {"reactor": actors[reactor_id], "reaction": "Test moment", "action": action,
              "moment": "", "by": "", "affected": ""}
    return trigger_text(context, prompt, actors, definitions)


def test_multi_damage_reads_as_the_creature_that_dealt_the_damage(monkeypatch):
    """MMX55r finding 1. ``after_technique`` raises ``multi_damage`` for the creature whose one
    effect damaged two or more creatures, and ``on_creature_event`` raises it with that creature as
    the actor, so the prompt must not tell the player it was hit."""
    from combat import typed_reactions
    from combat.gate2_runtime_content import AN, LEE
    from tests.test_reaction_moments import _engine, _row, REACTOR

    engine = _engine([_row("multi_damage")])
    damager = engine.state.actors[AN]
    request = raised_request(monkeypatch, lambda: typed_reactions.after_technique(engine, damager, {LEE, AN}))
    # The damager is the actor; the victims are not named, because the engine does not pass them.
    assert request["choice_trigger"]["actor_id"] == AN
    assert read(engine, request, REACTOR) == \
        f"{damager.display_name} damaged two or more creatures with one effect."


def test_an_ally_grapple_succeeded_names_the_ally_and_what_it_grabbed(monkeypatch):
    """MMX55r finding 2. ``on_grapple_outcome`` raises ``ally_grapple_succeeded`` for the allied
    grappler who succeeded, with the grabbed creature as the target, so the prompt names both and
    never says anyone escaped."""
    from combat import typed_reactions
    from combat.gate2_runtime_content import AN, LEE
    from tests.test_reaction_moments import _engine, _row, REACTOR

    engine = _engine([_row("ally_grapple_succeeded")])
    ally, grabbed = engine.state.actors[LEE], engine.state.actors[AN]
    request = raised_request(monkeypatch, lambda: typed_reactions.on_grapple_outcome(engine, ally, grabbed, True))
    assert (request["choice_trigger"]["actor_id"], request["choice_trigger"]["target_id"]) == (LEE, AN)
    said = read(engine, request, REACTOR)
    assert said == f"{ally.display_name} grabbed {grabbed.display_name}.", said
    assert "escaped" not in said.lower() and "grapple" not in said.lower(), said


def test_a_failed_grapple_reads_as_not_being_grabbed(monkeypatch):
    """MMX55r finding 2. ``on_grapple_outcome(..., grabbed=False)`` answers the reactor's own event
    through ``on_own_event``, whose frame names the defender first and the grappler second.
    The creature that defended is the one not grabbed, and "escaped a grapple" would claim a grapple was
    already on it, which nothing in the event says."""
    from combat import typed_reactions
    from combat.gate2_runtime_content import AN
    from tests.test_reaction_moments import _engine, _row, REACTOR

    engine = _engine([_row("grapple_failed")])
    reactor = engine.state.actors[REACTOR]
    grappler = engine.state.actors[AN]
    requests = raised_requests(monkeypatch, lambda: typed_reactions.on_grapple_outcome(
        engine, grappler, reactor, False))
    assert any(r.get("choice_trigger", {}).get("actor_id") == REACTOR
               and r.get("choice_trigger", {}).get("target_id") == AN for r in requests)
    said = read(engine, {"checkpoint": "TYPED:GRAPPLE_FAILED@0"}, REACTOR)
    assert said == f"{reactor.display_name} was not grabbed.", said
    assert "escaped" not in said.lower(), said
    # A prompt that does know who tried the grab names that creature as the one who tried.
    named = read(engine, {"checkpoint": "TYPED:GRAPPLE_FAILED@0", "choice_trigger":
                          {"actor_id": AN, "affected_id": REACTOR, "action_name": "Grapple"}}, REACTOR)
    assert named == f"{reactor.display_name} was not grabbed by {grappler.display_name}'s Grapple.", named


def test_a_creature_that_acted_is_named_as_the_subject_of_its_own_moment(monkeypatch):
    """MMX55r finding 3. ``on_action_completed`` raises ``creature_acted`` with the acting creature
    as the actor, so the sentence names that creature and its ability rather than "an ability"."""
    from combat import typed_reactions
    from combat.gate2_runtime_content import AN
    from tests.test_reaction_moments import _engine, _row, REACTOR

    engine = _engine([_row("creature_acted", range_ft=60, economies=["ACTION"])])
    actor = engine.state.actors[AN]
    request = raised_request(monkeypatch,
                             lambda: typed_reactions.on_action_completed(engine, actor, "ACTION", "action:x"))
    assert request["choice_trigger"]["actor_id"] == AN
    assert read(engine, request, REACTOR) == f"{actor.display_name} used an ability."
    # The action the table has already resolved from the log is named when it is known.
    assert read(engine, request, REACTOR, action="Dodge") == f"{actor.display_name} used Dodge."


def test_forced_movement_reads_as_being_moved_by_the_pusher(monkeypatch):
    """MMX55r finding 4. A typed push opens the FORCED_MOVEMENT checkpoint with the pusher as the
    actor and the moved creature as the target; "is being moved by from Right's Shove" was broken."""
    from combat import gate2_runtime_content
    from tests.test_forced_movement_reactions import _engine, _row, _push, REACTOR

    engine = _engine([_row("forced_moved")])
    pusher = engine.state.actors[gate2_runtime_content.AN]
    _push_source = next(engine.action_catalog[a] for a in pusher.action_ids)
    engine.__dict__["_active_action_source_id"] = _push_source.source_definition_id
    request = raised_request(monkeypatch, lambda: _push(engine, REACTOR, 10))
    assert request["choice_trigger"]["actor_id"] == gate2_runtime_content.AN
    assert request["choice_trigger"]["affected_id"] == REACTOR
    assert request["checkpoint"].startswith("TYPED:FORCED_MOVEMENT")
    said = read(engine, request, REACTOR, action=_push_source.display_name)
    assert said == f"{engine.state.actors[REACTOR].display_name} is being moved by " \
                  f"{pusher.display_name}'s {_push_source.display_name}.", said
    assert " by from " not in said and "  " not in said, said
    # Nothing known about the pusher: the sentence still reads, and still says what is being done.
    assert read(engine, {"checkpoint": "TYPED:FORCED_MOVEMENT@0"}, REACTOR) == \
        f"{engine.state.actors[REACTOR].display_name} is being moved by an effect."


# ------------------------------------------------------------------ the live table, committed and reloaded
def test_failed_grapple_save_at_the_table_never_names_the_defender_as_doer(tmp_path, monkeypatch):
    """A real Grapple save supplies the defender as SAVE_ROLLED.actor_id, not the doer.

    Execute the compiled save inside an accepted table action so the prompt receives the real
    recent events even though the failed-Grapple hook supplies no choice_trigger metadata.
    """
    from combat import decision_text, typed_executor
    from combat.gate5_service import CombatService
    from tests.h1_support import ROOT, script

    combat, table, mid = table_fight(tmp_path, [], ask=True, ally_talents=[])
    seen = []
    original = decision_text.trigger_text

    def capture(context, *args):
        if str(context.get("checkpoint", "")).startswith("TYPED:GRAPPLE_FAILED@"):
            seen.append(context)
        return original(context, *args)

    monkeypatch.setattr(decision_text, "trigger_text", capture)

    def attempt_grapple(engine):
        engine.typed_reaction_rows[LEFT] = [ask_row("grapple_failed")]
        grappler, defender = engine.state.actors[RIGHT], engine.state.actors[LEFT]
        action = next(a for a in engine.action_catalog.values()
                      if a.owner_id == RIGHT and a.display_name == "Grapple")
        typed = action.parameters["typed"]
        ctx = typed_executor.Context(engine, grappler, action, engine._active_intent,
                                     typed, [defender], defender, {})
        script(engine, [20])  # The defender succeeds, so the incoming Grapple fails.
        typed_executor.block_save(ctx, typed["effects"][0])

    on_hold(monkeypatch, attempt_grapple)
    result = act(table, mid, HOLD)
    assert result["status"] == "REACTION_REQUIRED"
    prompt = result["reaction"]
    assert seen
    context = seen[-1]
    assert context["checkpoint"].startswith("TYPED:GRAPPLE_FAILED@")
    assert context["choice_trigger"]["actor_id"] == LEFT
    assert context["choice_trigger"]["target_id"] == RIGHT
    save = next(e for e in reversed(context["recent_events"]) if e["event_type"] == "SAVE_ROLLED")
    assert save["actor_id"] == LEFT
    assert not save["target_ids"]
    assert save["source_definition_id"].endswith(".unarmed.grapple")
    assert save["payload"]["success"] is True
    assert prompt["moment"] == prompt["trigger"] == "Left was not grabbed by Right's Grapple."
    assert answer(table, mid, result)["status"] == "COMMITTED"
    reloaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert reloaded.engine.state.actors[LEFT].temporary_hp == 3
    assert not any(c.condition_id == "condition:typed.grappled"
                   for c in reloaded.engine.state.actors[LEFT].conditions.values())
    assert reloaded.mechanical.replay()["status"] == "PASS"


def ask_row(kind, **extra):
    """One Ask-me reaction row of the kind the engine raises, compiled into the reactor's rows."""
    return {"block": "generic", "feature_id": f"TEST_{kind.upper()}", "name": f"Test {kind}", "kind": kind,
            "ask": True, "costs": [], "numbers": {"pb": 4}, **extra,
            "effects": [{"type": "temp_hp", "flat": 3, "applies_to": "self", "evidence": "gain 3 temporary HP"}]}


def answer(table, mid, result, source=HOLD):
    """Answer the reaction prompt the table just raised, committing the turn through to disk."""
    prompt = result["reaction"]
    state, menu = result["state"], result["state"]["menu"]
    cid = next(g["options"][0]["candidate_id"] for g in menu["actions"] if g["source_definition_id"] == source)
    return table.act(mid, cid, menu["decision_id"], menu["state_version"], state["last_sequence"],
                     [{**prompt["context"], "selection": "USE"}])


def test_multi_damage_prompt_at_the_table_names_the_damager_and_commits(tmp_path, monkeypatch):
    """The multi-damage moment at the level it showed: a real Ask-me prompt in a table fight, then
    the answer committed and the fight reloaded from disk."""
    from combat import typed_reactions
    from combat.gate5_service import CombatService
    from tests.h1_support import ROOT

    combat, table, mid = table_fight(tmp_path, [], ask=True, ally_talents=[])

    def deal_to_two(engine):
        engine.typed_reaction_rows[LEFT] = [ask_row("multi_damage", range_ft=120)]
        typed_reactions.on_creature_event(engine, engine.state.actors[RIGHT], "multi_damage")

    on_hold(monkeypatch, deal_to_two)
    result = act(table, mid, HOLD)
    assert result["status"] == "REACTION_REQUIRED"
    moment = result["reaction"]["moment"]
    assert moment == "Right damaged two or more creatures with one effect.", moment
    assert moment == result["reaction"]["trigger"]  # the table shows the shared builder's sentence
    assert "hit" not in moment and "actor:" not in moment, moment
    assert answer(table, mid, result)["status"] == "COMMITTED"
    reloaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert reloaded.engine.state.actors[LEFT].temporary_hp == 3
    assert reloaded.mechanical.replay()["status"] == "PASS"


def test_an_ally_grapple_prompt_at_the_table_names_both_creatures_and_commits(tmp_path, monkeypatch):
    """The allied-grapple moment at the table: the ally grabbed a named creature, and the fight
    survives the answer as a commit plus a reload."""
    from combat import typed_reactions
    from combat.gate5_service import CombatService
    from tests.h1_support import ROOT

    combat, table, mid = table_fight(tmp_path, [], ask=True, ally_talents=[])

    def ally_grabs(engine):
        engine.typed_reaction_rows[LEFT] = [ask_row("ally_grapple_succeeded")]
        typed_reactions.on_grapple_outcome(engine, engine.state.actors[ALLY], engine.state.actors[RIGHT],
                                           grabbed=True)

    on_hold(monkeypatch, ally_grabs)
    result = act(table, mid, HOLD)
    assert result["status"] == "REACTION_REQUIRED"
    moment = result["reaction"]["moment"]
    assert moment == "Ally grabbed Right.", moment
    assert "escaped" not in moment.lower(), moment
    assert answer(table, mid, result)["status"] == "COMMITTED"
    reloaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert reloaded.engine.state.actors[LEFT].temporary_hp == 3
    assert reloaded.mechanical.replay()["status"] == "PASS"
