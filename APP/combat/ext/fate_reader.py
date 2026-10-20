"""Fate Reader (Spirit Awakening Tradition; rider lane C8, 2026-09-30: "i want everything we can automated").

Source: the owner's text (authority/typed_mechanics/rules_text.json; LocalSources/03_paths/Spirit/
Tianxia_Spirit_Awakening_Tradition_Compendium_R7.md, Fate Reader: Fate Tension, CL3 Omen Glimpse, CL6 Read the Thread, CL10 Nudge
Consequence, CL14 Borrowed Ending, CL18 Sever One Thread). No Spheres 5e or D&D 5.5e counterpart. Invoke the Omen and Sever One
Thread are d20 rewrites in combat/ext/d20_rewrite_fate.py (automation lane H1). Ownership: the ``spirit_tradition`` rows of
combat/rules/feature_blocks.d/riders_c8.json (Nudge Consequence, Borrowed Ending).

Fate Tension (tradition text): a pool on the sheet (resource:named.fate_tension), 0 at the start, maximum = Proficiency Bonus; at
its maximum you are Fate-Tangled (the pool full is the state -- no second condition).

What runs:
  * Nudge Consequence (Reaction, 4 Resonance): when a creature you can see within 60 feet makes an attack roll, ability check or saving
    throw whose outcome the table knows, before the outcome you may add or subtract 1d8 (asked; the AI helps its side's rolls and
    hinders its foes' when 8 could turn them). Worsening an unwilling creature's roll: it makes a Charisma save against your DC --
    failed, the full die; success, only 1d4 and your chosen Spiritual Pressure. If the modifier turns a success into a failure or a
    failure into a success, you gain 1 Fate Tension.
  * Borrowed Ending (Reaction, 6 Resonance and 1 Fate Tension taken on -- you cannot while Fate-Tangled): when you or an ally within 30
    feet would drop to 0 Hit Points, or would become Charmed or Frightened by a hostile creature (asked), the consequence is delayed
    until the end of that creature's next turn: it stays at 1 Hit Point / the condition has not taken hold. A visible Ending Token
    (an object: AC your Cultivation Save DC, 6 x PB Hit Points, immune Poison and Psychic) is attached to it. At the end of its next
    turn the Ending dissolves if the cause changed -- it regained Hit Points, or the creature that would have Charmed or Frightened it
    is gone -- otherwise the original consequence occurs (it drops to 0 Hit Points; the condition lands). Destroying the token makes
    the consequence occur at once. One Borrowed Ending from you at a time on a creature.

Plug-in surface: effects none; hooks d20_bonus, would_drop, condition_attempt, turn_end, event. Public helper: ``gain_tension``.
Shared helpers used: spirit_traditions (row/context/numbers/feature_action/can_react/remove), needle.ask, d20_rewrite.context_of,
stealth.sees, typed_executor (run_effects); spirit_traditions delay_condition/land_delayed_condition/landing.
"""

from __future__ import annotations

from ..paid_relocation import activation

from typing import Any

from . import effect, hook, note
from . import spirit_traditions as st

TRADITION = "tianxia.tradition.spirit.fate_reader.feature."
NUDGE = TRADITION + "nudge_consequence"
BORROWED = TRADITION + "borrowed_ending"
TENSION = "resource:named.fate_tension"
RESONANCE = "resource:core.resonance"
ENDING = "condition:typed.borrowed_ending"
TOKEN = "object:typed.borrowed_ending:"
_NUDGING = "_c8_nudging"
_RESOLVING = "_c8_borrowed_resolving"


def _te() -> Any:
    from .. import typed_executor

    return typed_executor


def gain_tension(engine: Any, actor: Any, amount: int, source: str) -> None:
    """Fate Tension up to its maximum (Proficiency Bonus)."""
    room = int(actor.resource_maximums.get(TENSION, 0) or 0) - int(actor.resources.get(TENSION, 0) or 0)
    if room > 0 and amount > 0:
        engine._gain_resource(actor, TENSION, min(room, amount), source)


def tangled(actor: Any) -> bool:
    return int(actor.resource_maximums.get(TENSION, 0) or 0) > 0 and actor.resources.get(TENSION, 0) >= actor.resource_maximums.get(TENSION, 0)


# ---------------------------------------------------------------------------------------------------------- Nudge Consequence
def _succeeded(rc: Any, total: int) -> bool | None:
    if rc.kind == "attack":
        if rc.ac is None:
            return None
        return rc.natural != 1 and (rc.natural == 20 or total >= rc.ac)
    if rc.dc is None:
        return None
    return total >= rc.dc


@hook("d20_bonus")
def nudge(engine: Any, roll: Any, intent: Any) -> dict[str, Any] | None:
    if engine.__dict__.get(_NUDGING) or roll.natural_result is None:
        return None
    from .d20_rewrite import context_of

    rc = context_of(engine, roll)
    if rc is None or rc.kind not in ("attack", "save", "check"):
        return None
    now = _succeeded(rc, int(roll.total))
    if now is None:
        return None
    from .. import stealth

    for reader in list(engine.state.actors.values()):
        if (not reader.active or st.row(engine, reader, "nudge_consequence") is None or not st.can_react(reader)
                or reader.resources.get(RESONANCE, 0) < 4):
            continue
        roller = rc.roller
        if roller is not reader and (engine._distance_actor_to_actor(reader, roller) > 60 or not stealth.sees(engine, reader, roller)):
            continue
        ours = roller.team_id == reader.team_id
        # the AI's aim: help its own side's failing roll, hinder a foe's succeeding one, when 8 could turn it
        target_number = rc.ac if rc.kind == "attack" else rc.dc
        helpful = ours and not now and int(target_number) - int(roll.total) <= 8
        harmful = not ours and now and int(roll.total) - int(target_number) < 8 and rc.natural != 20
        from . import needle

        options = ["add", "subtract"]
        labels = {"add": "Add 1d8 to the roll", "subtract": "Subtract 1d8 from the roll"}
        preferred = ["add"] if helpful else ["subtract"] if harmful else []
        chosen = needle.ask(engine, intent, needle.checkpoint_id(engine, "NUDGE", roll.roll_id), reader, "choice:needle.fate_reader.nudge", options,
                            labels=labels, preferred=preferred, allow_decline=True, automatic=bool(preferred),
                            default="first" if preferred else "decline", name="Nudge Consequence", feature_id=NUDGE, target_id=roller.entity_id,
                            prompt=f"Nudge Consequence (Reaction, 4 Resonance): {roller.display_name}'s {rc.kind} roll is {roll.total} "
                                   f"({'succeeding' if now else 'failing'}). Add or subtract 1d8 before the outcome?")
        if not chosen or chosen[0] not in options:
            continue
        engine.__dict__[_NUDGING] = True
        try:
            return _apply_nudge(engine, reader, rc, roll, chosen[0] == "add", ours, now)
        finally:
            engine.__dict__.pop(_NUDGING, None)
    return None


def _apply_nudge(engine: Any, reader: Any, rc: Any, roll: Any, add: bool, ours: bool, before: bool) -> dict[str, Any]:
    from ..gate2_runtime_models import DiceSpec

    with activation(engine, reader, NUDGE):
        engine._spend_resource(reader, RESONANCE, 4, NUDGE)
        reader.reaction_available = False
        engine._append_event("REACTION_RESOLVED", NUDGE, actor_id=reader.entity_id, target_ids=(rc.roller.entity_id,),
                             payload={"checkpoint": "D20_BONUS", "reaction_name": "Nudge Consequence"})
        sides = 8
        worsens = not add
        if worsens and not ours and rc.roller.active:
            # "If the target is unwilling and you worsen its result, it makes a Charisma saving throw."
            dc = int(st.numbers(engine, reader).get("save_dc") or 10)
            saved = engine._roll_save(rc.roller, "CHA", dc, NUDGE)
            if saved is not None and saved.total >= dc:
                sides = 4
                ctx = st.context(engine, reader, st.feature_action(engine, reader, NUDGE), [rc.roller], st.numbers(engine, reader))
                _te().run_effects(ctx, [{"type": "spiritual_pressure", "applies_to": "target", "evidence": "the target suffers one ordinary Spiritual Pressure effect"}])
        die = engine.roller.roll(DiceSpec(count=1, sides=sides, modifier=0), actor_id=reader.entity_id, reason=f"D20_BONUS:{NUDGE}")
        engine._record_roll(die)
        bonus = int(die.total) if add else -int(die.total)
        after = _succeeded(rc, int(roll.total) + bonus)
        if after is not None and after != before:
            gain_tension(engine, reader, 1, NUDGE)  # "gain 1 Fate Tension if the modifier changed success to failure or failure to success"
        note(engine, NUDGE, reader, f"Nudge Consequence: {'+' if add else '-'}{die.total} on {rc.roller.display_name}'s roll.", (rc.roller,))
        return {"source_id": NUDGE, "bonus": bonus}


# ---------------------------------------------------------------------------------------------------------- Borrowed Ending
def _endings(creature: Any, reader_id: str | None = None) -> list[Any]:
    return [c for c in creature.conditions.values() if c.condition_id == ENDING and (reader_id is None or c.source_actor_id == reader_id)]


def _readers(engine: Any, subject: Any) -> list[Any]:
    """Fate Readers who may borrow this creature's ending: it is them or an ally within 30 feet."""
    out = []
    for reader in engine.state.actors.values():
        if (reader.active and reader.team_id == subject.team_id and st.row(engine, reader, "borrowed_ending") is not None and st.can_react(reader)
                and reader.resources.get(RESONANCE, 0) >= 6 and not tangled(reader) and not _endings(subject, reader.entity_id)
                and (reader is subject or engine._distance_actor_to_actor(reader, subject) <= 30)):
            out.append(reader)
    return out


def _ask(engine: Any, reader: Any, subject: Any, what: str, intent: Any) -> bool:
    from . import needle

    chosen = needle.ask(engine, intent, needle.checkpoint_id(engine, "BORROWED_ENDING", subject.entity_id), reader, "choice:needle.fate_reader.borrowed_ending",
                        ["borrow"], labels={"borrow": f"Borrowed Ending (Reaction, 6 Resonance, +1 Fate Tension): delay it until the end of {subject.display_name}'s next turn"},
                        prompt=f"{subject.display_name} would {what}.", preferred=["borrow"], allow_decline=True, name="Borrowed Ending",
                        feature_id=BORROWED, target_id=subject.entity_id)
    return bool(chosen)


def _borrow(engine: Any, reader: Any, subject: Any, data: dict[str, Any]) -> None:
    from ..gate2_runtime_models import RuntimeObjectState

    with activation(engine, reader, BORROWED):
        engine._spend_resource(reader, RESONANCE, 6, BORROWED)
        gain_tension(engine, reader, 1, BORROWED)
        reader.reaction_available = False
        engine._append_event("REACTION_RESOLVED", BORROWED, actor_id=reader.entity_id, target_ids=(subject.entity_id,),
                             payload={"checkpoint": "CONSEQUENCE", "reaction_name": "Borrowed Ending"})
        numbers = st.numbers(engine, reader)
        hp = 6 * int(numbers.get("pb") or 2)
        token = RuntimeObjectState(object_id=f"{TOKEN}{reader.entity_id}:{subject.entity_id}:{engine.state.event_sequence}", object_kind="BORROWED_ENDING_TOKEN",
                                   position=subject.position, unattended=False, flammable=False, owner_id=reader.entity_id,
                                   ac=int(numbers.get("save_dc") or 10), current_hp=hp, maximum_hp=hp, damage_immunities=("POISON", "PSYCHIC"),
                                   component={"ending_of": subject.entity_id, "label": "Ending Token"})
        engine._update_object(token, BORROWED, reader.entity_id)
        engine._apply_condition(subject, ENDING, BORROWED, reader.entity_id, expires_on="UNTIL_REMOVED",
                                data={**data, "token": token.object_id, "turn": int(subject.turns_started),
                                      "label": f"Borrowed Ending: {data.get('what')} is delayed until the end of its next turn"})
        note(engine, BORROWED, reader, f"Borrowed Ending: {subject.display_name}'s fate is delayed ({data.get('what')}).", (subject,))


@hook("would_drop")
def borrow_the_fall(engine: Any, target: Any, pending: int, source_actor_id: str | None) -> int | None:
    if engine.__dict__.get(_RESOLVING) == target.entity_id:
        return None
    from ..damage_allocation import available_temporary_hp
    available_temp = available_temporary_hp(engine, target, pending, source_actor_id)
    if any((held.data or {}).get("kind") == "zero_hp" for held in _endings(target)):
        return max(0, target.current_hp + available_temp - 1)  # "During the delay: The target remains at a minimum of 1 Hit Point"
    if target.current_hp <= 1:
        return None
    for reader in _readers(engine, target):
        if not _ask(engine, reader, target, "drop to 0 Hit Points", engine._active_intent):
            continue
        _borrow(engine, reader, target, {"kind": "zero_hp", "what": "dropping to 0 Hit Points", "source_actor": source_actor_id})
        return max(0, target.current_hp + available_temp - 1)  # "The target remains at a minimum of 1 Hit Point"
    return None


@hook("condition_attempt")
def borrow_the_condition(ctx: Any, subject: Any, effect_row: dict[str, Any]) -> bool | None:
    name = str(effect_row.get("condition") or "").lower()
    engine = ctx.engine
    if (name not in ("charmed", "frightened") or subject is None or ctx.actor.team_id == subject.team_id
            or engine.__dict__.get(_RESOLVING) == subject.entity_id or st.landing(engine, subject)):
        return None
    for reader in _readers(engine, subject):
        if not _ask(engine, reader, subject, f"become {name.title()}", ctx.intent):
            continue
        _borrow(engine, reader, subject, {"kind": "condition", "what": f"becoming {name.title()}", **st.delay_condition(ctx, effect_row, name)})
        return False  # "has not yet taken hold"
    return None


@hook("turn_end")
def ending_arrives(engine: Any, actor: Any) -> None:
    for held in list(_endings(actor)):
        if actor.turns_started > int((held.data or {}).get("turn") or 0):
            _resolve(engine, actor, held, at_once=False)


@hook("event")
def token_destroyed(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """"Destroying the token by hostile action causes the original consequence to occur immediately"."""
    if event_type != "OBJECT_UPDATED":
        return
    obj = (kwargs.get("payload") or {}).get("object") or {}
    if not str(obj.get("object_id") or "").startswith(TOKEN) or not (obj.get("destroyed") or int(obj.get("current_hp") or 0) <= 0):
        return
    holder = engine.state.actors.get(str((obj.get("component") or {}).get("ending_of") or ""))
    if holder is None:
        return
    for held in _endings(holder):
        if (held.data or {}).get("token") == obj.get("object_id") and kwargs.get("actor_id") != held.source_actor_id:
            _resolve(engine, holder, held, at_once=True)


def _resolve(engine: Any, holder: Any, held: Any, *, at_once: bool) -> None:
    data = dict(held.data or {})
    st.remove(engine, holder, held, "RESOLVED")
    token = engine.state.objects.get(str(data.get("token") or ""))
    if token is not None and not token.destroyed:
        engine._update_object(token.model_copy(update={"destroyed": True, "current_hp": 0}), BORROWED, held.source_actor_id)
    source = engine.state.actors.get(str(data.get("source_actor") or ""))
    if data.get("kind") == "zero_hp":
        if not at_once and holder.current_hp > 1:
            note(engine, BORROWED, holder, f"Borrowed Ending dissolves: {holder.display_name} was healed.")
            return
        engine.__dict__[_RESOLVING] = holder.entity_id
        engine.__dict__["_damage_unreduced"] = holder.entity_id
        try:
            engine._commit_damage(holder, holder.current_hp + holder.temporary_hp, "UNTYPED", BORROWED, str(data.get("source_actor") or held.source_actor_id),
                                  engine._active_intent, reaction_depth=1)
        finally:
            engine.__dict__.pop(_RESOLVING, None)
            if engine.__dict__.get("_damage_unreduced") == holder.entity_id:
                engine.__dict__.pop("_damage_unreduced", None)
        note(engine, BORROWED, holder, f"The borrowed ending arrives: {holder.display_name} drops to 0 Hit Points.")
        return
    if data.get("kind") == "condition":
        if st.land_delayed_condition(engine, holder, data):
            note(engine, BORROWED, holder, f"The borrowed ending arrives: {holder.display_name} becomes {str(data.get('condition')).title()}.")
        else:
            note(engine, BORROWED, holder, f"Borrowed Ending dissolves: the creature that would have {data.get('condition')} {holder.display_name} is gone.")

READ = TRADITION + "read_the_thread"
BRANCH = "condition:typed.fate_reader_branch"
THREAD_ANSWER = 'condition:typed.fate_reader_answer'
THREAD_QUESTIONS = {
    'danger': 'What is the most likely immediate danger if the observed plan proceeds unchanged?',
    'cause': 'Which observed creature, object, location, or Anchor is most causally important to the next stage?',
    'improve': "What visible action would most directly improve the observed plan's chance of success?",
    'fail': 'What visible action would most directly cause the observed plan to fail?',
    'authority': 'Is the imminent event primarily protected by lower, equal, or higher Source CL?',
    'branch': 'Is the observed branch being concealed, redirected, willingly accepted, or fixed by another authority?',
}


@hook('feature_access_policy')
def thread_access_policy(feature_id):
    if feature_id == READ:
        return {'path': 'tianxia.path.spirit_awakening', 'minimum_cl': 6,
                'classification': 'Secret',
                'source_kinds': ('scripture', 'inheritance', 'revelation', 'scar', 'teacher', 'event')}


@hook('compile_action')
def thread_subject_picker(action, info):
    if st.feature_of(action) != READ or (action.parameters or {}).get('fate_record_branch'):
        return None
    from ..feature_access import effective_cl
    parameters = dict(action.parameters)
    parameters['typed'] = {**parameters['typed'], 'thread_source_cl': effective_cl(info['owner_sheet'], 'tianxia.path.spirit_awakening')}
    # Subjects include plans/events/locations, not just creature targets. The
    # effect presents the personally observed source records at resolution.
    return action.model_copy(update={'target_kind': 'SELF', 'parameters': {
        **parameters, 'description': 'Read the Thread (Action, 3 Resonance): choose one meaningfully observed subject within 60 feet and one Thread Question. Learn a currently knowable fact; protected fate may require a Cultivation Check. Then you may mark one involved creature if it knowingly takes the exact predicted action before your next turn ends.'}})


def thread_subjects(engine, actor):
    from ..table_facts import records, observable
    return {key: fact for key, fact in records(engine, actor).items()
            if observable(engine, actor, fact, 60)}


@effect('fate_read_thread')
def answer_thread(ctx, row):
    from . import needle
    from .ability_source import cultivation_check
    if (st.feature_of(ctx.action) != READ or ctx.action.owner_id != ctx.actor.entity_id
            or ctx.action.source_definition_id not in ctx.actor.action_ids):
        return
    subjects = thread_subjects(ctx.engine, ctx.actor)
    if not subjects:
        note(ctx.engine, READ, ctx.actor, 'Read the Thread: record a meaningful observation and its currently knowable facts at the table before asking a question.')
        return
    chosen = needle.ask(ctx.engine, ctx.intent, needle.checkpoint_id(ctx.engine, 'THREAD_SUBJECT', ctx.actor.entity_id), ctx.actor,
        'choice:needle.fate_reader.subject', list(subjects),
        labels={key: f'{fact.subject_name} ({fact.subject_kind})' for key, fact in subjects.items()},
        name='Read the Thread', feature_id=READ,
        prompt='Read the Thread (Action, 3 Resonance): which observed subject within 60 feet do you read?')
    if not chosen:
        return
    fact = subjects[chosen[0]]
    question = needle.ask(ctx.engine, ctx.intent, needle.checkpoint_id(ctx.engine, 'THREAD_QUESTION', fact.record_id), ctx.actor,
        'choice:needle.fate_reader.question', list(THREAD_QUESTIONS), labels=THREAD_QUESTIONS,
        name='Read the Thread', feature_id=READ, prompt=f'Read the Thread: choose one question about {fact.subject_name}.')
    if not question:
        return
    answer = fact.answers.get(question[0])
    if answer is None:
        # No invented intention, statistic or future event. The owner can add a
        # source-backed answer; an absent fact cannot arm a prediction.
        text = 'No currently knowable answer is recorded for that question.'
        predictions = []
        success = False
    else:
        success = True
        # The compiled numbers use actual CL; the explicit effective Path
        # boundary is sealed by the acquisition compiler policy.
        source_cl = int((ctx.typed.get('thread_source_cl') or ctx.numbers.get('cl')) or 1)
        if answer.source_cl >= source_cl and answer.check_dc is not None:
            success = cultivation_check(ctx.engine, ctx.actor, dict(ctx.numbers), answer.check_dc, READ,
                                        f'Read the Thread: {fact.subject_name}')
        text = ((f'{answer.condition}: ' if answer.condition else '') + answer.fact) if success else (
            f'{answer.category} is obscured. Visible sign: {answer.visible_sign}.')
        predictions = [p.model_dump(mode='json') for p in answer.predictions] if success else []
    import json
    for old in list(ctx.actor.conditions.values()):
        if old.condition_id == THREAD_ANSWER:
            st.remove(ctx.engine, ctx.actor, old, 'NEW_ANSWER')
    if predictions:
        from ..canonical import canonical_sha256
        ctx.engine._apply_condition(ctx.actor, THREAD_ANSWER, ctx.source, ctx.actor.entity_id,
            expires_on=f'END_OF_SOURCE_TURN_AT:{int(ctx.actor.turns_started) + 1}',
            data={'predictions': json.dumps(predictions, sort_keys=True), 'record_id': fact.record_id,
                  'record_hash': canonical_sha256(fact.model_dump(mode='json')),
                  'label': 'Read the Thread: choose a creature involved in the answered branch before your next turn ends'})
    ctx.engine._append_event('OBSERVATION_ANSWERED', READ, actor_id=ctx.actor.entity_id,
        payload={'record_id': fact.record_id, 'question': question[0], 'answer': text, 'success': success,
                 'audience_actor_ids': [ctx.actor.entity_id],
                 'log': f'Read the Thread — {fact.subject_name}: {text}'})


def thread_predictions(actor):
    import json
    return [(held, prediction) for held in actor.conditions.values() if held.condition_id == THREAD_ANSWER
            for prediction in json.loads(held.data['predictions'])]

@hook("compile_actions")
def branch_action(info):
    if READ not in info["owned_ids"]:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    return [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.mark_predicted_branch", display_name="Mark the Branch: record a prediction",
        owner_id=info["actor_id"], economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF", range_ft=None,
        parameters={"typed": {"effects": [{"type": "fate_record_branch", "applies_to": "self"}], "numbers": info["numbers"],
                              "duration": {"kind": "instant"}, "riders": [], "source": READ},
                    "expected_damage": 0, "fate_record_branch": True,
                    "description": "After Read the Thread's answer, choose a creature involved in that branch and its exact predicted action. If it knowingly takes that action before the end of your next turn, it becomes Resonance Marked by you and you or one ally within 30 feet may move 10 feet without provoking that creature."})]

@hook("candidate_allowed")
def branch_gate(engine, actor, candidate, action):
    if action is None or not (action.parameters or {}).get("fate_record_branch"):
        return None
    return None if thread_predictions(actor) else False

@effect("fate_record_branch")
def record_branch(ctx, row):
    from . import needle
    predictions = thread_predictions(ctx.actor)
    creatures = {p['actor_id']: ctx.engine.state.actors[p['actor_id']] for _, p in predictions
                 if p['actor_id'] in ctx.engine.state.actors and ctx.engine.state.actors[p['actor_id']].active}
    if not creatures:
        return
    chosen = needle.ask(ctx.engine, ctx.intent, needle.checkpoint_id(ctx.engine, 'THREAD_BRANCH_CREATURE', ctx.actor.entity_id), ctx.actor,
        'choice:needle.fate_reader.branch_creature', list(creatures), labels={key: actor.display_name for key, actor in creatures.items()},
        name='Read the Thread', feature_id=READ, prompt='Read the Thread: choose one creature involved in the answered branch.')
    if not chosen:
        return
    target = creatures[chosen[0]]
    predictions = [(held, p) for held, p in predictions if p['actor_id'] == target.entity_id]
    options = {str(index): p for index, (_, p) in enumerate(predictions)}
    picked = needle.ask(ctx.engine, ctx.intent, needle.checkpoint_id(ctx.engine, "PREDICTED_BRANCH", target.entity_id), ctx.actor,
                        "choice:needle.fate_reader.prediction", list(options), labels={key: p['description'] for key, p in options.items()},
                        prompt=f"Read the Thread: choose {target.display_name}'s answered action before your next turn ends.", name="Read the Thread", feature_id=READ)
    if picked:
        import json
        held = predictions[int(picked[0])][0]
        ctx.engine._apply_condition(target, BRANCH, ctx.source, ctx.actor.entity_id,
            expires_on=held.expires_on, data={'prediction': json.dumps(options[picked[0]], sort_keys=True),
                'record_id': held.data['record_id'], 'record_hash': held.data['record_hash'],
                'label': 'Predicted branch: ' + options[picked[0]]['description']})
        st.remove(ctx.engine, ctx.actor, held, 'BRANCH_CHOSEN')

@hook('intent_resolved')
def predicted_branch_occurs(engine, target, candidate, intent, start_sequence):
    from ..table_facts import action_matches
    if target is None or not target.active:
        return
    for held, prediction in thread_live_branches(engine, target):
        if action_matches(engine, prediction, target, candidate, intent, start_sequence):
            fulfill_thread_branch(engine, target, held, prediction, intent)


@hook('event', nested=True)
def thread_reaction_occurs(engine, event_type, kwargs):
    if event_type != 'REACTION_RESOLVED':
        return
    from ..table_facts import reaction_matches
    target = engine.state.actors.get(kwargs.get('actor_id'))
    if target is None or not target.active:
        return
    for held, prediction in thread_live_branches(engine, target):
        if reaction_matches(engine, prediction, event_type, kwargs):
            fulfill_thread_branch(engine, target, held, prediction, engine._active_intent)


def thread_live_branches(engine, target):
    helds = [held for held in target.conditions.values() if held.condition_id == BRANCH]
    if not helds:
        return
    import json
    from ..table_facts import records, PredictedAction
    from ..canonical import canonical_sha256
    facts = records(engine)
    for held in helds:
        fact = facts.get(held.data['record_id'])
        if fact is not None and canonical_sha256(fact.model_dump(mode='json')) == held.data['record_hash']:
            yield held, PredictedAction.model_validate(json.loads(held.data['prediction']))


def fulfill_thread_branch(engine, target, held, prediction, intent):
    from . import needle
    from ..relations import relation, ALLY
    owner = engine.state.actors.get(held.source_actor_id)
    if owner is None or not owner.active:
        return
    st.remove(engine, target, held, 'PREDICTION_FULFILLED')
    ctx = st.context(engine, owner, st.feature_action(engine, owner, READ), [target], st.numbers(engine, owner), intent)
    _te().block_mark(ctx, {'type': 'mark', 'mark': 'Resonance', 'applies_to': 'target'})
    allies = [a for a in engine.state.actors.values() if a.active and relation(engine, owner, a) == ALLY
              and engine._distance_actor_to_actor(owner, a) <= 30]
    prompt_context = f'{target.display_name} knowingly takes the predicted action: {prediction.description}.'
    mover = st.pick_creature(engine, intent, owner, allies, checkpoint='BRANCH_MOVER', choice_id='choice:needle.fate_reader.branch_mover',
                            prompt=f'Read the Thread: {prompt_context} Who may move 10 feet?', name='Read the Thread', feature_id=READ, preferred=owner, allow_decline=True)
    if mover is None:
        return
    options = st.routes(engine, mover, 10)
    # Reader ownership and every legal route, including on somebody else's turn.
    ids = {needle.cell_id(cell): path for cell, (path, _) in options.items()}
    chosen = needle.ask(engine, intent, needle.checkpoint_id(engine, 'BRANCH_STEP', mover.entity_id), owner,
        'choice:needle.fate_reader.branch_step', list(ids),
        labels={key: f'Move {mover.display_name} to {key.removeprefix("cell:")} (up to 10 feet; no opportunity attack from {target.display_name})' for key in ids},
        preferred=[needle.cell_id(mover.position)], allow_decline=True, name='Read the Thread', feature_id=READ,
        target_id=mover.entity_id, prompt=f'Read the Thread: {prompt_context} Where may {mover.display_name} move up to 10 feet?')
    path = ids[chosen[0]] if chosen else None
    if path:
        from .granted_moves import commit
        commit(engine, mover, list(path), READ, budget_ft=10, provokes=True, ignore_oa_from=(target.entity_id,), intent=intent)
