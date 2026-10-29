"""Reviewed Hidden Eye combat opt-ins: Lurker and Wind Reader.

Ownership is the existing eye_rider_rule compilation, never an ability case in
the Search or attack resolver. Search reactions use the holder's controller.
"""
from . import hook
from .eye_common import FOCUS
from .riders14_eye import has

LURKER = "TAL_THE_HIDDEN_EYE_LURKER"
SOURCE = "reaction:eye.lurker"


@hook("stealth_search_before_roll")
def lurker(engine, searcher, target, source):
    from .. import stealth
    from .needle import CHOICE, ask, checkpoint_id, incapacitated
    from .choice_costs import payable
    from .choice_prompt import action_context
    from ..paid_relocation import activation
    from ..typed_reactions import can_use_reaction, open_reaction
    from .riders14_eye import rule

    row = rule(engine, target, "lurker")
    if row is None or not target.active or incapacitated(target) or not stealth.hidden(target):
        return None
    # The ordinary Reaction admission, asked of the holder against this very searcher: the economy, the
    # no-Reactions conditions and any "cannot take Reactions against you" prohibition are decided once, in
    # combat/typed_reactions.py, instead of here re-checking only the economy flag and Incapacitated. A
    # creature barred from Reactions is never offered Lurker and never pays for it.
    if not can_use_reaction(engine, target, searcher, row):
        return None
    payment = payable(target, FOCUS, 1)
    if payment is None:
        return None
    # The question is about the Search that is actually resolving now, so it names that action, the
    # creature taking it and the hidden creature it is searching for. Search and a multi-target sweep
    # are different actions at this checkpoint, and the service deliberately reads this explicit
    # metadata rather than recovering the outer turn (tabletop_service extension choices).
    moment = action_context(engine, searcher, source, target)
    action = moment["action_name"] or "Search"
    checkpoint = checkpoint_id(engine, "EYE_LURKER", target.entity_id, searcher.entity_id, source)
    picked = ask(engine, getattr(engine, "_active_intent", None), checkpoint,
                 target, CHOICE + "eye_lurker", ["lurker"],
                 automatic=searcher.team_id != target.team_id, allow_decline=True,
                 feature_id=LURKER, name="Lurker", payment=payment,
                 target_id=target.entity_id, prompt_context=moment,
                 prompt=f"Lurker: {searcher.display_name} is using {action} to search for you. Use your Reaction "
                        "and expend Martial Focus (your combat readiness) to give this Perception check Disadvantage?")
    if not picked:
        return None
    with activation(engine, target, SOURCE, independent=True):
        payment.pay(engine, target, SOURCE)
        # The shared Reaction lifecycle, after consent and payment: it spends the holder's Reaction through
        # the same waiver path as every other reaction, journals the window against this checkpoint, and
        # publishes the "a creature uses a Reaction" moment exactly once. Abilities that answer that moment
        # (a qualifying Charged Countermeasure) therefore see Lurker's use and their own choice and effects
        # resolve inside this same paused action.
        open_reaction(engine, row, target, (searcher.entity_id,), checkpoint)
        engine._append_event("REACTION_RESOLVED", SOURCE, actor_id=target.entity_id,
                             target_ids=(searcher.entity_id,), payload={"feature_id": LURKER,
                             "check_source": source, "mode": "DISADVANTAGE"})
    return "DISADVANTAGE"


@hook("attack_mode_removed")
def wind_reader(engine, attacker, target, ranged):
    if ranged is True and attacker.resources.get(FOCUS, 0) > 0 and has(engine, attacker, "wind_reader"):
        return ["DISADVANTAGE:weather"]
    return None


@hook("status_description")
def physical_examination(engine, holder, row, data):
    """A live band on this analyzer's own mark, without disclosing exact HP.

    Unrepresented narrative wounds remain in the reviewed record. Ordinary
    combat damage/healing changes the band automatically, including on reload.

    The analyzer is resolved through the shared ``analyzer_id`` reader rather than by testing for the
    ordinary Analyze mark alone, so the reading also covers the one record Heaven Keeps No Secret from
    the Patient Eye files: that Inheritance Analyzes its target "even if it would normally be protected
    from Analyze", so a creature the Analyze mark cannot reach still earns this reading for the minute
    its record is open.
    """
    from .mind_hidden_eye import analyzer_id
    from .eye_common import has as eye_has

    owner = engine.state.actors.get(analyzer_id(row, data))
    if owner is None or not (has(engine, owner, "physical_examination")
                             or eye_has(engine, owner.entity_id, "physical_examination")):
        return None
    if holder.current_hp <= 0:
        band = "Weak"
    elif holder.current_hp * 10 >= holder.maximum_hp * 9:
        band = "Normal"
    elif holder.current_hp * 10 >= holder.maximum_hp * 3:
        band = "Fair"
    else:
        band = "Poor"
    return {"text": f"Physical Examination: {holder.display_name}'s physical condition is {band}. "
                    "This reading gives a health band, not exact Hit Points."}
