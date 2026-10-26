"""Spirit Companions: the Binding Seal family (AUTO5, round 24 live 42e43e14).

Rules text (owner's Sphere Compendium, "Sphere of Spirit Companions"; authority/typed_mechanics/rules_text.json):

  Binding Seal           "The spirit makes a Wisdom saving throw against your Cultivation Save DC. On a failure, the
                         Binding Seal takes hold. ... While Binding Seal holds: - the spirit cannot willingly move
                         beyond the bond's range or vessel limits; - the spirit cannot directly attack you unless the
                         seal cracks; - you may command limited service through Manifest the Spirit Nature; - each
                         coercive command that violates the spirit's Nature or Taboo increases Bond Strain by 1".
                         -> the Wisdom saving throw and the Binding Seal mark are typed data
                         (authority/typed_mechanics/reviewed_final.d/auto5_spirit.json). This module carries the
                         clauses that hold *while* the seal does: the movement tether and the ban on attacking the
                         binder (mark_applied / candidate_allowed), and the coercive-command Bond Strain (the
                         printed questions after Command Bonded Spirit). The condition is written only while its mark
                         stands, and a suppressed seal holds nothing at all (Break the Cruel Seal, Exorcist's Mercy).
  Bind the Violent Ghost "you have Advantage on the Binding check or the spirit has Disadvantage on its saving throw"
                         -> the saving throw's own row reads `disadvantage_if_marked: "Violent Ghost"`, the engine's
                         named-mark reader, so the disadvantage is qualified by the binder who placed it; this module
                         places that mark on every spirit that attacked the binder's side -- the binder or one of
                         their allies, whoever swung -- before any seal exists ("during the current scene").
  Painful Binding Seal  "A spirit bound this way gains Bond Strain 1 immediately. When you command the spirit to act
                         against its desire, increase Bond Strain by 1 unless the command aligns with its Nature or the
                         spirit fears a greater consequence." -> the seal taking hold charges the first; that printed
                         "unless" is its own question, asked only of an owner of this talent, because it is the only
                         one of the two sentences that excuses an order. Bond Strain itself is spirit_bond_state's
                         shared counter.
  Punishing Seal        "When a spirit bound by your Binding Seal disobeys a command that the seal can lawfully
                         enforce, you may use your Reaction to punish it. The spirit takes Psychic or Force damage
                         equal to one roll of your sphere die plus your key ability modifier ... Using this talent
                         increases Bond Strain by 1." -> no engine event reports a summon disobeying, so this module
                         asks the owner, right after the command, what the spirit did with the order and, when it
                         refused, whether the seal can lawfully enforce it, and offers the Reaction there; the talent
                         produced no button at all before, because nothing could see its trigger. Refusing and serving
                         unwillingly are separate answers: no Bond Strain is charged for service that never happened,
                         and a spirit that served is never punished for a disobedience it did not commit.
  Break the Cruel Seal   "Make a Cultivation Check against the binder's Cultivation Save DC ... you may instead suppress
                         the Binding Seal until the end of your next turn" -> one contest whose success nests the
                         printed outcome, and this module's `seal_binder` DC provider reads the binder's DC.
  Exorcist's Mercy       "Make a Cultivation Check against the spirit's Cultivation Save DC or the binder's DC" /
                         "remove one layer of a Binding Seal if the spirit wants to leave" / "suppress the Hosting
                         Bond for 1 minute" -> one contest per printed outcome; each outcome nests under a successful
                         check, so a failed check changes nothing. "force the spirit to manifest adjacent to the host"
                         names a hosting relationship the table cannot see (no engine state records which spirit is
                         hosted in which creature), so that line stays the record's rider rather than moving the
                         caster's own companion.
  Name-Binding           "Every time the standing command forces unwilling service, increase Bond Strain by 1." ->
                           charged by the unwilling-service answer alone, which is that printed sentence exactly.

Hooks: compile_block (block "spirit_seal"), compile_action, mark_applied, candidate_allowed, check_dc,
command_reachable, event. Effects: seal_suppress, seal_release, seal_strain.
Every hook returns early unless the creature owns the row or the creature wears this plug-in's own condition, so
other characters and fights saved before are unaffected. The seal condition holds one integer tether length and the
printed clauses are read from it, never keyed on an ability id. Public helpers: owns, sealed_by, sealed_creatures,
suppressed, command_gate, seal_marks. Nothing stored is a float or an object: the seal condition carries tether_ft (an
integer), binder (an entity id) and label (a string), so a saved fight reloads it unchanged. The Bind the Violent
Ghost mark lasts until the fight ends, which is this engine's scene (see combat/ext/banner.py:460, "the fight is the
scene"). Bond Strain and its recovery are spirit_bond_state's shared counter.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, move_limits, note
from .spirit_bond_state import STRAIN, add_strain, strain

PREFIX = "tianxia.talent.spirit_companions."
SEAL = "TAL_SPIRIT_COMPANIONS_BINDING_SEAL"
VIOLENT = PREFIX + "bind_the_violent_ghost"
PAINFUL = PREFIX + "painful_binding_seal"
PUNISH = PREFIX + "punishing_seal"
NAME = PREFIX + "name_binding"
BLOCK = "spirit_seal"
CONDITION = "condition:typed.spirit_sealed"
VIOLENT_MARK_NAME = "Violent Ghost"
SUPPRESSED = "condition:typed.spirit_seal_suppressed"
MARK = "Binding Seal"
NAMES = {PAINFUL: "Painful Binding Seal", PUNISH: "Punishing Seal", NAME: "Name-Binding"}
BINDER_DC = "seal_binder"
DEFAULT_TETHER_FT = 60  # a spirit's printed command range; spirit_bonds reads the per-creature record when it has one
STRAIN_HINT = "Bond Strain is stress on the bond (0 to 3); at 3 the GM runs a crisis."


# ------------------------------------------------------------------------------------------------ ownership
@hook("compile_block")
def seal_rows(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    """The seal talents whose whole trigger this module runs. A row that carries ``trigger_owner`` claims its
    feature, so the compiler omits the generic reaction row it could never deliver; the printed damage stays the
    talent's own typed row, read from the built authority so there is one copy of it. Every row is inert without
    the owning feature, and choice_owner keeps a player controlling the binder asked on the spirit's own turn."""
    if block != BLOCK:
        return None
    kind = str(spec.get("kind") or "")
    if kind not in {"violent", "painful", "punish", "name"}:
        return None
    from ..typed_numbers import authority_mechanics

    record = authority_mechanics().get(row["feature_id"]) or {}
    out = {**row, "kind": kind, "numbers": dict(numbers), "choice_owner": True,
           "effects": [dict(effect_row) for effect_row in record.get("effects") or []]}
    if kind == "punish":
        out["trigger_owner"] = "spirit_seals"
    return [out]


def _kinds(engine: Any, actor_id: str) -> dict[str, dict[str, Any]]:
    return {str(row.get("kind")): row for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor_id, [])
            if row.get("block") == BLOCK and row.get("kind")}


def owns(engine: Any, actor: Any, kind: str) -> bool:
    return kind in _kinds(engine, actor.entity_id)


def seal_marks(subject: Any) -> list[tuple[str, str, str]]:
    """``(binder entity id, condition instance id, condition id)`` for every Binding Seal mark ``subject`` wears.

    Read through the engine's own public mark id helper (``typed_executor.mark_requirement_ids``), so a mark
    placed before this module existed -- a fight saved by an earlier build -- is recognised too.
    """
    from ..typed_executor import mark_requirement_ids

    out = []
    for instance_id, row in subject.conditions.items():
        condition_id = str(row.condition_id)
        if not condition_id.startswith("condition:typed.mark."):
            continue
        binder = str(row.source_actor_id or condition_id.rsplit(".", 1)[-1])
        if condition_id in mark_requirement_ids(MARK, binder):
            out.append((binder, instance_id, condition_id))
    return out


def sealed_by(engine: Any, binder: Any, creature: Any) -> dict[str, Any] | None:
    """The seal condition ``binder`` holds on ``creature``, when it still does.

    A suppressed seal (Break the Cruel Seal, Exorcist's Mercy) holds nothing: while it lasts the spirit may be
    commanded, may attack and may leave the bond, which is what "suppress the Binding Seal" says.
    """
    if suppressed(creature):
        return None
    return next((row for row in creature.conditions.values()
                 if row.condition_id == CONDITION and row.source_actor_id == binder.entity_id), None)


def seal_held(creature: Any) -> list[dict[str, Any]]:
    """Every unsealed Binding Seal condition the creature wears, whatever binder placed it."""
    if suppressed(creature):
        return []
    return [row for row in creature.conditions.values() if row.condition_id == CONDITION]


def sealed_creatures(engine: Any, binder: Any) -> list[Any]:
    """Every creature this binder currently holds under a Binding Seal."""
    return [creature for creature in engine.state.actors.values()
            if creature.active and creature is not binder and sealed_by(engine, binder, creature) is not None]


def suppressed(creature: Any) -> bool:
    """True while a printed "the spirit cannot be commanded" window holds (Exorcist's Mercy, Break the Cruel Seal)."""
    return any(row.condition_id == SUPPRESSED for row in creature.conditions.values())


# ------------------------------------------------------------------------------------------------ while the seal holds
@hook("mark_applied")
def seal_takes_hold(ctx: Any, name: str, subject: Any) -> None:
    """One written clause per printed line that holds while the seal does, plus Painful Binding Seal's charge.

    The condition goes with its mark (the ``event`` subscriber on CONDITION_REMOVED), so the two can never
    disagree, and an old fight that carries the mark without the condition gets the condition on its next seal."""
    if str(name).strip().lower() != MARK.lower():
        return
    engine, owner = ctx.engine, ctx.actor
    _drop_own_seal(engine, subject, owner.entity_id, ctx.source)
    reach = _bond_range(subject)
    engine._apply_condition(subject, CONDITION, ctx.source, owner.entity_id, expires_on="UNTIL_REMOVED",
                            data={"tether_ft": reach, "binder": owner.entity_id,
                                  "label": f"Sealed by {owner.display_name}: it cannot willingly leave the bond, "
                                           f"and it cannot attack {owner.display_name} unless the seal cracks."})
    note(engine, ctx.source, owner,
         f"Binding Seal: {subject.display_name} is bound by {owner.display_name}. It cannot willingly leave the bond "
         f"(more than {reach} feet away) and it cannot attack {owner.display_name}.", (subject.entity_id,))
    if owns(engine, owner, "painful"):
        charge_strain(engine, owner, 1, ctx.source, f"Painful Binding Seal: the seal on {subject.display_name} takes hold.")


def _drop_own_seal(engine: Any, subject: Any, binder_id: str, source: str) -> list[str]:
    """Take off exactly the seal conditions ``binder_id`` placed on ``subject``, and nothing else.

    ``CombatEngine._remove_condition`` clears *every* instance of a condition id, so calling it here would also
    dissolve a second binder's seal while that binder's own mark still stands -- the spirit would keep the mark and
    lose the clauses that mark enforces. This module therefore always goes through the shared public
    ``rider_support.remove_instance`` helper, which pops one named instance and files the engine's own
    CONDITION_REMOVED event for it. Returns the instance ids removed.
    """
    from .rider_support import remove_instance

    gone = [key for key, row in list(subject.conditions.items())
            if row.condition_id == CONDITION and str(row.source_actor_id) == str(binder_id)]
    for key in gone:
        remove_instance(engine, subject, key, source)
    return gone


def _bond_range(subject: Any) -> int:
    """The bond's range: the spirit's own printed command range, else the sphere's 60 feet."""
    return max(1, int((subject.summon or {}).get("command_range_ft") or DEFAULT_TETHER_FT))


def _seal_tether(engine: Any, condition: Any, holder: Any = None) -> tuple[Any, int] | None:
    """The bond's tether, read through the shared reader seam (combat/ext/move_limits.py register_tether).

    A suppressed seal holds nothing, so the spirit may leave the bond while the suppression lasts.
    """
    if holder is not None and suppressed(holder):
        return None
    return move_limits.plain_tether(engine, condition)


move_limits.register_tether(CONDITION, _seal_tether)


@hook("event")
def seal_follows_its_mark(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """A Binding Seal that leaves (broken by Exorcist's Mercy or Break the Cruel Seal, or cleared by anything else)
    takes its own binder's condition with it, so no creature is left sealed with nothing holding it.

    The mark is recognised by the engine's public mark id, not by a re-spelled slug, so every binder's mark is
    recognised; only that binder's own condition instances go, and they go one instance at a time, so a second
    binder's seal on the same creature survives with its clauses intact.
    """
    if event_type != "CONDITION_REMOVED":
        return
    from ..typed_executor import mark_requirement_ids

    payload = kwargs.get("payload") or {}
    removed = str(payload.get("condition_id") or "")
    binder = str(kwargs.get("actor_id") or "")
    if not removed or removed not in mark_requirement_ids(MARK, binder):
        return
    for target_id in kwargs.get("target_ids") or ():
        target = engine.state.actors.get(target_id)
        if target is None:
            continue
        _drop_own_seal(engine, target, binder, "system:spirit_seal.released")


@hook("compile_action")
def widen_any_side(action: Any, info: dict[str, Any]) -> Any | None:
    """A reviewed ``target: {"any_side": true}`` widens one owned action to any creature.

    The compiler reads a harmful saving throw or contest as hostile-only (``_target_kind``), but the Spirit
    Companions seal family prints no side at all -- "A Binding Seal restrains or compels a spirit", "target one
    spirit, vessel, host, or seal", "target one creature, object, or location hosting a spirit" -- and the sphere's
    own coercive half (Painful Binding Seal, Punishing Seal) commands the binder's OWN bonded spirit. Hostile-only
    would hide the printed flow. The flag lives in the talent's own typed record, so any ability can use it; range,
    costs and effects are untouched."""
    typed = (action.parameters or {}).get("typed") or {}
    record = (info.get("mechanics") or {}).get(str(typed.get("source") or "")) or {}
    target = record.get("target")
    if not (isinstance(target, dict) and target.get("any_side")) or action.target_kind == "ANY_CREATURE":
        return None
    return action.model_copy(update={"target_kind": "ANY_CREATURE"})


# ------------------------------------------------------------------------------------------------ the sealed attack and the suppressed command
def _strikes(action: Any) -> bool:
    """Whether this action is an attack at all: a typed attack row, or a native attack the summon takes from its
    stat block (resolution kind or an attack bonus), which carries no typed effect to look for."""
    if action is None:
        return False
    if getattr(action, "attack_bonus", None) is not None:
        return True
    if str(getattr(action, "resolution_kind", "")) in ("ATTACK", "MULTI_ATTACK", "ATTACK_THEN_SAVE"):
        return True
    return any(isinstance(row, dict) and row.get("type") == "attack"
               for row in ((getattr(action, "parameters", None) or {}).get("typed") or {}).get("effects") or ())


@hook("candidate_allowed")
def seal_limits(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """Two printed limits, both read from this plug-in's own conditions rather than from any ability id.

    "the spirit cannot directly attack you unless the seal cracks": a creature wearing the seal condition never has
    a binder among the targets of one of its own attacks -- the seal binds the attacker, whoever is swinging (only
    attacks; breaking, suppressing and exorcising the seal are exactly what the other three talents are for).
    "cannot be commanded while the seal is suppressed" (Break the Cruel Seal, Exorcist's Mercy): the commander's
    Command choice leaves the menu for a spirit carrying that condition, and the ``command_reachable`` seam keeps a
    mixed group honest at execution time.

    The printed list of states an unwilling spirit may be sealed in is deliberately NOT filtered at the menu. Half of
    it is a fact the table cannot read -- a willing spirit, a vessel, a shrine, a GM-declared trap -- so a filter would
    hide a legal target and make the button disappear on a board where nothing happens to be defeated. The list stays
    as the ability's own rider, in the words the player needs to choose."""
    typed = (getattr(action, "parameters", None) or {}).get("typed") or {}
    if str(typed.get("source") or "") == SEAL:
        if any(target_id == actor.entity_id for target_id in candidate.target_ids or ()):
            return False  # you cannot bind yourself
    elif _strikes(action):
        binders = {str(row.source_actor_id) for row in seal_held(actor)}
        if binders and binders & {str(target_id) for target_id in candidate.target_ids or ()}:
            return False  # a sealed spirit cannot attack the creature that sealed it
    group = _command_group(typed)
    if group is not None and not _commandable(engine, actor, group):
        return False  # every spirit this order would reach has its seal suppressed
    return None


def _command_group(typed: dict[str, Any]) -> str | None:
    return next((str(row.get("group")) for row in typed.get("effects") or ()
                 if isinstance(row, dict) and row.get("type") == "command_summons" and row.get("group")), None)


def _commandable(engine: Any, actor: Any, group: str) -> list[Any]:
    """The creatures this order would actually reach, minus any whose seal is suppressed."""
    from .. import summons

    return [creature for creature in summons.commandable(engine, actor, group) if not suppressed(creature)]


@hook("command_reachable")
def command_gate(engine: Any, owner: Any, group: str, creature: Any) -> bool | None:
    """"the spirit cannot be commanded" (Exorcist's Mercy, Break the Cruel Seal).

    The printed window keeps a spirit out of an order at execution time, not only out of the menu: one group command
    reaches every member the summons module would command, so the check lives on the shared command seam as well."""
    return False if suppressed(creature) else None


def suppression_window(creature: Any) -> dict[str, Any] | None:
    """The printed window that keeps a spirit out of a commander's Command choice, or None."""
    return next((row for row in creature.conditions.values() if row.condition_id == SUPPRESSED), None)


# ------------------------------------------------------------------------------------------------ the printed Difficulty Classes
@hook("check_dc")
def seal_binder_dc(ctx: Any, target: Any, spec: dict[str, Any]) -> int | None:
    """``{"kind": "dc", "of": "seal_binder"}``: the seal's own Difficulty Class.

    Break the Cruel Seal is checked "against the binder's Cultivation Save DC" and Exorcist's Mercy "against the
    spirit's Cultivation Save DC or the binder's DC". The binder of the seal the target wears is the printed DC for
    both; a target that wears no seal (nothing to break, nothing to suppress) falls back to the engine's ordinary
    target DC, which is the spirit's own. Only a target whose stored condition names a live binder answers here, so
    a fight that saved the old ``cultivation_save_dc`` name keeps its old reading.

    Which binder's DC: the very layer ``_one_layer`` will release, chosen the same way. Reading "the first binder in
    condition order" instead would measure the check against one binder and let another binder's seal go, so two
    cultivators with different DCs could have a release allowed or refused by a number that is not the one on the
    table. When that layer's binder is no longer in the fight the answer is None, which is the printed fallback --
    the spirit's own Cultivation Save DC, exactly as the mercy sentence allows.
    """
    if str(spec.get("of") or "") != BINDER_DC:
        return None
    from .end_effect import cultivation_dc

    if not seal_held(target):
        return None
    chosen = _one_layer(_seal_layers(target), ctx.actor.entity_id)
    binder = ctx.engine.state.actors.get(chosen) if chosen else None
    if binder is not None and binder.active and binder is not target:
        return int(cultivation_dc(ctx.engine, binder))
    return None


# ------------------------------------------------------------------------------------------------ Bind the Violent Ghost
def _binders_of(engine: Any, victim: Any, attacker: Any) -> list[Any]:
    """Whose "you or your allies" includes ``victim``: everyone on the victim's own side, the victim included, since
    the printed words are "attacked you or your allies".

    The precondition is about a side, not about a stat block, so an allied character counts exactly as much as one of
    the binder's own summoned creatures. The attacker itself is never one of them: a spirit that attacked its own
    allies has attacked nobody."""
    return [other for other in engine.state.actors.values()
            if other.active and other.team_id == victim.team_id and other.entity_id != attacker.entity_id]


@hook("event")
def violent_ghost_marked(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """"a spirit that has attacked you or your allies during the current scene", marked on the attacker.

    An attack is an attack whether it hit: this reads ATTACK_ROLLED, so a miss and a fully prevented blow count too,
    and it runs before any seal exists (the printed precondition is about the scene, not about the seal). The side is
    the *victim's*, which is what the printed words mean: "a spirit that has attacked you or your allies" is true of an
    enemy spirit that struck the binder or one of the binder's allies -- the ordinary case -- and of a spirit that
    struck a member of the binder's own side. Who the attacker belongs to is not part of the test, so an attack on a
    third party's side never marks (that binder simply has no talent owner on the victim's side). The mark is the
    engine's own named mark for the binder who owns the talent, so Binding Seal's own save row reads it through
    ``disadvantage_if_marked`` and no other binder, without the talent, is affected. It lasts until the fight ends,
    which is this engine's scene (combat/ext/banner.py:460)."""
    if event_type != "ATTACK_ROLLED":
        return
    from ..typed_executor import mark_condition_id

    attacker = engine.state.actors.get(kwargs.get("actor_id") or "")
    if attacker is None:
        return
    for target_id in kwargs.get("target_ids") or ():
        victim = engine.state.actors.get(target_id)
        if victim is None or victim is attacker or not victim.active:
            continue
        for binder in _binders_of(engine, victim, attacker):
            if not owns(engine, binder, "violent"):
                continue
            mark_id = mark_condition_id(VIOLENT_MARK_NAME, binder.entity_id)
            if any(row.condition_id == mark_id for row in attacker.conditions.values()):
                continue
            engine._apply_condition(attacker, mark_id, VIOLENT, binder.entity_id, expires_on="UNTIL_REMOVED",
                                    data={"label": f"It attacked {binder.display_name} or their allies this scene "
                                                   f"(Bind the Violent Ghost): its next Binding Seal save is "
                                                   f"Disadvantage"})
            note(engine, VIOLENT, binder,
                 f"Bind the Violent Ghost: {attacker.display_name} attacked {victim.display_name} this scene, so the "
                 f"next Binding Seal {binder.display_name} places on it is resolved at Disadvantage.",
                 (attacker.entity_id,))


# ------------------------------------------------------------------------------------------------ commands against a sealed spirit
@hook("event")
def commanded_sealed_spirit(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """The printed questions a command against a sealed spirit asks, one per printed clause.

    Nothing in the engine can see a summon disobey, and a spirit's Nature and Taboo are not table facts, so the
    binder answers in the words of the rules:
      1. what the spirit did with the order -- served it willingly, served it against its will, or refused it
         outright (Binding Seal's "coercive command", Name-Binding's "forces unwilling service", Punishing Seal's
         "disobeys a command");
      2. does that coercive order break the spirit's Nature or its Taboo? (the seal's own clause, "violates the
         spirit's Nature or Taboo");
      3. does it still charge an owner of Painful Binding Seal? (that talent's own printed "unless the command aligns
         with its Nature or the spirit fears a greater consequence");
      4. may you punish a spirit that refused an order the seal can lawfully enforce? (Punishing Seal's Reaction, its
         damage and 1 Bond Strain).
    Refusing and serving unwillingly are different printed facts, so they are different answers: a refusal is charged
    no Bond Strain for service that never happened, and a spirit that served against its will never has the
    disobedience punishment rides on punished, because it disobeyed nothing.
    No printed rule cancels the order, so the command still goes out; what the answers decide is what it costs and
    whether the Reaction is spent. Asked on the binder's own turn and on an AI turn alike, with no answer nobody
    being charged.
    """
    if event_type != "SUMMONS_COMMANDED":
        return
    owner = engine.state.actors.get(kwargs.get("actor_id") or "")
    if owner is None or not owner.active:
        return
    kinds = _kinds(engine, owner.entity_id)
    painful, punish, named = "painful" in kinds, "punish" in kinds, "name" in kinds
    for spirit_id in kwargs.get("target_ids") or ():
        spirit = engine.state.actors.get(spirit_id)
        if spirit is None or not spirit.active or sealed_by(engine, owner, spirit) is None:
            continue
        served = _ask_service(engine, owner, spirit)
        if not served or served == "willing":
            continue  # nobody answered, or it served willingly: no printed clause charges
        refused = served == "refuses"
        if named and not refused:
            charge_strain(engine, owner, 1, NAME,
                          f"Name-Binding: {owner.display_name}'s order forced {spirit.display_name} into unwilling "
                          f"service.")
        # Binding Seal's own printed clause, asked of every binder: it has no exception of its own.
        if _asks_violation(engine, owner, spirit):
            charge_strain(engine, owner, 1, SEAL,
                          f"{MARK}: {owner.display_name}'s order to {spirit.display_name} breaks that spirit's Nature "
                          f"or its Taboo.")
        # Painful Binding Seal's own printed "unless", asked only of an owner of that talent.
        if painful and _asks_painful(engine, owner, spirit):
            charge_strain(engine, owner, 1, PAINFUL,
                          f"{NAMES[PAINFUL]}: {owner.display_name} commanded {spirit.display_name} against its desire, "
                          f"and it neither aligned with its Nature nor feared a greater consequence.")
        # Punishing Seal rides on a refusal only: it punishes a spirit that disobeyed a command the seal can enforce.
        if punish and refused and owner.reaction_available and _punishes(engine, owner, spirit, kinds["punish"]):
            charge_strain(engine, owner, 1, PUNISH, f"Punishing Seal: {owner.display_name} punishes {spirit.display_name}.")


def _ask_service(engine: Any, owner: Any, spirit: Any) -> str | None:
    """Question 1: what ``spirit`` did with this order -- the one fact Binding Seal's "coercive command", Name-Binding's
    "forces unwilling service" and Punishing Seal's "disobeys" each hang on. Refusing is its own answer, so a
    refusal is never charged as service and never punished for disobedience it did not commit. None when nobody
    answered, and then nothing is charged."""
    from .needle import CHOICE, ask, checkpoint_id

    options = ["willing", "unwilling", "refuses"]
    labels = {
        "willing": f"{spirit.display_name} serves this order willingly: no Bond Strain, and there is nothing to punish",
        "unwilling": f"{spirit.display_name} serves this order, but against its will: any talent of yours that charges "
                     f"for unwilling service or for a command against its desire charges on this answer. It served, so "
                     f"it disobeyed nothing and there is nothing to punish",
        "refuses": f"{spirit.display_name} refuses this order and does not serve it at all: no Bond Strain for service "
                   f"that never happened, but a refusal is the disobedience Punishing Seal punishes",
    }
    chosen = ask(engine, getattr(engine, "_active_intent", None),
                 checkpoint_id(engine, "SEAL_SERVICE", owner.entity_id, spirit.entity_id),
                 owner, CHOICE + "seal_service", options, labels=labels, automatic=False, allow_decline=True,
                 default="decline", name=MARK, feature_id=SEAL, target_id=spirit.entity_id,
                 prompt=f"{MARK}: {owner.display_name} orders {spirit.display_name}. Does {spirit.display_name} serve "
                        f"this order, and if it does, willingly?")
    return str(chosen[0]) if chosen else None


def _asks_violation(engine: Any, owner: Any, spirit: Any) -> bool:
    """Question 2: the seal's own clause, "each coercive command that violates the spirit's Nature or Taboo increases
    Bond Strain by 1".

    This sentence has no exception of its own, so the question offers none: a binder without Painful Binding Seal who
    coerces a spirit by threatening a worse fate for it is still charged for the Taboo it broke. True only when the
    player says the order breaks one of the two; "or" is the printed word, so breaking either is enough."""
    from .needle import CHOICE, ask, checkpoint_id

    options = ["violates", "aligns"]
    labels = {
        "violates": f"the order breaks {spirit.display_name}'s Nature or its Taboo: gain 1 Bond Strain ({STRAIN_HINT})",
        "aligns": "the order breaks neither its Nature nor its Taboo: no Bond Strain",
    }
    chosen = ask(engine, getattr(engine, "_active_intent", None),
                 checkpoint_id(engine, "SEAL_VIOLATION", owner.entity_id, spirit.entity_id),
                 owner, CHOICE + "seal_violation", options, labels=labels, automatic=False, allow_decline=True,
                 default="decline", name=MARK, feature_id=SEAL, target_id=spirit.entity_id,
                 prompt=f"{MARK}: {owner.display_name}'s order to {spirit.display_name} -- does that order break "
                        f"{spirit.display_name}'s Nature, or its Taboo?")
    return bool(chosen) and chosen[0] == "violates"


def _asks_painful(engine: Any, owner: Any, spirit: Any) -> bool:
    """Question 3: Painful Binding Seal's own printed "unless the command aligns with its Nature or the spirit fears a
    greater consequence". This is the only one of the two sentences that excuses an order, so it is asked only of an
    owner of that talent and its answer is what this talent charges on. True when the order is not excused."""
    from .needle import CHOICE, ask, checkpoint_id

    options = ["strained", "exempt"]
    labels = {
        "strained": f"the order acts against {spirit.display_name}'s desire, and it neither aligns with its Nature nor "
                    f"finds it fearing a greater consequence: gain 1 Bond Strain ({STRAIN_HINT})",
        "exempt": "the order aligns with its Nature, or the spirit fears a greater consequence: this talent adds no "
                  "Bond Strain",
    }
    chosen = ask(engine, getattr(engine, "_active_intent", None),
                 checkpoint_id(engine, "SEAL_PAINFUL", owner.entity_id, spirit.entity_id),
                 owner, CHOICE + "seal_painful", options, labels=labels, automatic=False, allow_decline=True,
                 default="decline", name=NAMES[PAINFUL], feature_id=PAINFUL, target_id=spirit.entity_id,
                 prompt=f"{NAMES[PAINFUL]}: {owner.display_name}'s order to {spirit.display_name} -- does it align "
                        f"with {spirit.display_name}'s Nature, or does {spirit.display_name} fear a greater "
                        f"consequence?")
    return bool(chosen) and chosen[0] == "strained"


def _punishes(engine: Any, owner: Any, spirit: Any, row: dict[str, Any]) -> bool:
    """Question 4: Punishing Seal's printed Reaction, "when a spirit bound by your Binding Seal disobeys a command that
    the seal can lawfully enforce, you may use your Reaction to punish it".

    Both halves are the binder's to answer and neither is assumed: the second option says outright that the seal
    cannot lawfully enforce this order, so refusing a command the seal may not compel costs nothing."""
    from .needle import CHOICE, ask, checkpoint_id

    options = ["punish", "not_enforceable"]
    labels = {
        "punish": f"this is a command your Binding Seal can lawfully enforce: spend your Reaction, deal one roll of "
                  f"the sphere die (read here as 1d10) plus your key ability modifier as Psychic or Force damage, and "
                  f"gain 1 Bond Strain ({STRAIN_HINT})",
        "not_enforceable": "your Binding Seal cannot lawfully enforce this command (you may only command limited service "
                           "through it), so it is not punished and no Bond Strain is charged",
    }
    chosen = ask(engine, getattr(engine, "_active_intent", None),
                 checkpoint_id(engine, "SEAL_PUNISH", owner.entity_id, spirit.entity_id),
                 owner, CHOICE + "seal_punish", options, labels=labels, automatic=False, allow_decline=True,
                 default="decline", name=NAMES[PUNISH], feature_id=PUNISH, target_id=spirit.entity_id,
                 prompt=f"{NAMES[PUNISH]}: {spirit.display_name} refused an order. Punish a spirit that disobeys a "
                        f"command your Binding Seal can lawfully enforce?")
    if not chosen or chosen[0] != "punish":
        return False
    return _punish(engine, owner, spirit, row)


def _punish(engine: Any, owner: Any, spirit: Any, row: dict[str, Any]) -> bool:
    """The printed punishment, as the talent's own typed damage row: one roll of the sphere die (read as the
    Cultivation percentile die; the printed term is not defined anywhere else in the owner's rules) plus the key
    ability modifier, dealt as Psychic or Force."""
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    from ..typed_executor import Context, run_effects

    rows = [dict(effect_row, applies_to="target") for effect_row in row.get("effects") or []]
    if not rows:
        return False
    from ..paid_relocation import activation as relocation_activation
    with relocation_activation(engine, owner, PUNISH, independent=True):
        owner.reaction_available = False
        action = ActionDefinition(source_definition_id=PUNISH, display_name=NAMES[PUNISH], owner_id=owner.entity_id,
                                  economy=EconomyKind.REACTION, resolution_kind="TYPED", target_kind="ENTITY")
        intent = getattr(engine, "_active_intent", None)
        ctx = Context(engine, owner, action, intent, {"numbers": dict(row.get("numbers") or {}), "effects": rows},
                      [spirit], spirit, {})
        run_effects(ctx, rows)
        note(engine, PUNISH, owner,
             f"Punishing Seal: {owner.display_name}'s Reaction punishes {spirit.display_name} "
             f"(one roll of the sphere die, read here as 1d10, plus the key ability modifier).", (spirit.entity_id,))
        return True


def charge_strain(engine: Any, owner: Any, amount: int, source: str, why: str) -> None:
    """The shared Bond Strain counter, or a plain line for a character that has none."""
    if STRAIN in owner.resources:
        add_strain(engine, owner, amount, source, f"{why} {STRAIN_HINT}")
    elif strain(owner) >= 0:
        note(engine, source, owner, f"{why} This character has no Bond Strain counter; the GM records it.")


# ------------------------------------------------------------------------------------------------ the printed outcomes
def _subjects(ctx: Any, row: dict[str, Any]) -> list[Any]:
    from ..typed_executor import _default_subject

    return [subject for subject in _default_subject(ctx, row, harmful=False) if subject.active]


@effect("seal_strain")
def seal_strain(ctx: Any, row: dict[str, Any]) -> None:
    """Painful Binding Seal's printed charge, on the owner's own counter and never on the spirit's."""
    charge_strain(ctx.engine, ctx.actor, int(row.get("flat") or 1), ctx.source, "Painful Binding Seal: the seal takes hold.")


@effect("seal_release")
def seal_release(ctx: Any, row: dict[str, Any]) -> None:
    """Exorcist's Mercy: "remove one layer of a Binding Seal if the spirit wants to leave".

    One *layer* is one binder's seal: its mark and the clause that mark writes. Two binders can hold the same spirit,
    and the printed sentence releases one of those, not the lot -- so this picks a single binder and removes only that
    binder's mark and condition, by instance id, through the shared public ``remove_instance`` helper. A creature that
    carries an older mark written before this plug-in's condition existed is still released, because the mark -- not
    the condition -- is what the printed rule removes.

    Which layer: the caster's own seal when the caster is one of this creature's binders (the usual case -- an exorcist
    unbinding the spirit it bound), otherwise the oldest remaining seal. The choice is deterministic and needs no
    prompt; the line names the binder whose seal was released and how many others remain. It is the same choice
    ``seal_binder_dc`` measures the printed Cultivation Check against, so the number tested is the number on the layer
    that goes.
    """
    from .rider_support import remove_instance

    for subject in _subjects(ctx, row):
        layers = _seal_layers(subject)
        if not layers:
            ctx.rider(f"{subject.display_name} carries no Binding Seal to remove.")
            continue
        chosen = _one_layer(layers, ctx.actor.entity_id)
        for binder, instance_id, _ in seal_marks(subject):
            if binder == chosen:
                remove_instance(ctx.engine, subject, instance_id, ctx.source)
        for key, instance in list(subject.conditions.items()):
            if instance.condition_id == CONDITION and str(instance.source_actor_id) == chosen:
                remove_instance(ctx.engine, subject, key, ctx.source)
        binder = ctx.engine.state.actors.get(chosen)
        others = len(layers) - 1
        # A binder that is no longer in the fight is still named as one, never as the internal id it is stored under.
        who = binder.display_name if binder is not None else "an unknown binder"
        note(ctx.engine, ctx.source, ctx.actor,
             f"Exorcist's Mercy: one layer of the Binding Seal on {subject.display_name} is broken -- "
             f"{who}'s seal is gone."
             + (f" {others} other binder's seal still holds." if others else ""), (subject.entity_id,))


def _seal_layers(subject: Any) -> list[str]:
    """Every binder whose one Binding Seal layer ``subject`` wears, oldest first.

    A layer is a binder's mark plus the clause that mark writes, and both are read, so a creature carrying only the
    mark -- a fight saved before this plug-in's condition existed -- still shows its binder, which is what the printed
    rule removes. The moment that orders the layers is read off SEAL instances only: an unrelated condition a binder
    placed on the creature earlier (a restraint, one of its own marks) says nothing about how long its seal has held,
    so it must not decide which layer a third-party exorcist breaks.
    """
    ages: dict[str, int] = {}

    def remember(binder: Any, sequence: Any) -> None:
        name = str(binder or "")
        if not name:
            return
        try:
            moment = int(sequence)
        except (TypeError, ValueError):
            moment = 0
        ages[name] = min(ages.get(name, moment), moment)

    for binder, instance_id, _condition_id in seal_marks(subject):
        remember(binder, getattr(subject.conditions.get(instance_id), "applied_sequence", 0))
    for held in seal_held(subject):
        remember(str((held.data or {}).get("binder") or held.source_actor_id or ""),
                 getattr(held, "applied_sequence", 0))
    return [binder for binder, _ in sorted(ages.items(), key=lambda item: (item[1], item[0]))]


def _one_layer(layers: list[str], caster_id: str) -> str:
    """Which binder's single seal layer Exorcist's Mercy releases, out of ``_seal_layers``' oldest-first order: the
    caster's own when the caster is one of the binders, else the oldest seal still standing, so the same board always
    answers the same way."""
    if not layers:
        return ""
    caster = str(caster_id)
    return caster if caster in layers else str(layers[0])


@effect("seal_suppress")
def seal_suppress(ctx: Any, row: dict[str, Any]) -> None:
    """Break the Cruel Seal's "suppress the Binding Seal until the end of your next turn" and Exorcist's Mercy's
    "suppress the Hosting Bond for 1 minute": the spirit cannot be commanded, its tether does not hold and the
    ban on attacking its binder is lifted while it lasts (sealed_by, _seal_tether, command_gate)."""
    from ..typed_executor import effect_expiry

    for subject in _subjects(ctx, row):
        ctx.engine._apply_condition(subject, SUPPRESSED, ctx.source, ctx.actor.entity_id,
                                    expires_on=effect_expiry(ctx, row, subject, condition=True) or "START_OF_TARGET_NEXT_TURN",
                                    data={"label": f"{ctx.actor.display_name}'s seal is suppressed: it cannot be commanded"})
        note(ctx.engine, ctx.source, ctx.actor,
             f"{subject.display_name} cannot be commanded while its seal is suppressed.", (subject.entity_id,))