""""Is this fighter wielding a Shield right now?" -- the one question every Shield talent asks (AUTO55, 2026-10-05).

Sphere Compendium, Shield (owner's text: APP/authority/typed_mechanics/rules_text.json):

* Active Defense, ``SHIELD_BASE_ACTIVE_DEFENSE``: "Requirement: Wielding a Shield."
* Guarded Stance, ``TAL_SHIELD_GUARDED_STANCE``: "You may use Active Defense when you are not equipped with a
  Shield. Choose one weapon you are wielding. Treat that weapon as a Shield for talents that reference your Shield.
  The chosen weapon has a Shield Bonus of 0 unless another feature grants it a Shield Bonus."
* Orbiting Shield Disc, ``TAL_SHIELD_ORBITING_SHIELD_DISC``: "For the duration: count as wielding the Shield;
  retain its Shield Bonus; keep both hands free; may use Shield talents normally."

Before this module the table never asked: a fighter who owned Active Defense answered with the +2 AC whether or not
a Shield was in their hands (the printed "Requirement" rode in the record and was read by nothing), so Guarded
Stance's printed permission and Orbiting Shield Disc's "count as wielding" had nothing to switch on.

:func:`wielding_a_shield` is the shared answer. Three things satisfy it, in the printed order:

1. a Shield in the fighter's hands -- compiled inventory plus recorded possession and broken state;
2. a released Shield that is still orbiting its owner (Orbiting Shield Disc): the Shield is counted as wielded and
   its Shield Bonus is retained;
3. a weapon the fighter has chosen as their Shield through Guarded Stance. That weapon is a Shield only for
   talents that reference a Shield (it has a Shield Bonus of 0 and is not a Shield for armour rules), which is
   what :func:`shield_bonus` and the printed-Requirement gate below express.

:func:`shield_presented` is the same answer for Active Defense's printed "does not function while you cannot
present the Shield toward the incoming attack": a held Shield must also occupy its own hand in the shared hand
occupancy (``combat/ext/hand_occupancy.py``), while an orbiting Shield or a Guarded Stance weapon keeps counting
as presented because the printed talent says so.

Shared helper module. ``wielding_a_shield`` / ``shield_bonus`` / ``guarded_weapon`` / ``wielded_weapons`` are the
shared names other Shield plug-ins read: ``shield_mobility`` (Shield Skate's withheld Shield Bonus),
``shield_uncbroken`` (Unbroken Rim's "the Shield remains intact"), ``shield_possession`` (the Shield Bonus while a
Shield orbits) and ``shield_faces`` (Seal the Breach ends when the Shield leaves the hands).

Saved-state note: the Guarded Stance choice is the item key of the chosen weapon -- a string -- inside the
condition's ``data``, so it survives a table commit and reload like any other recorded condition.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, note
from .needle import CHOICE, ask, checkpoint_id

BLOCK = "shield_wielding"
GUARDED = "TAL_SHIELD_GUARDED_STANCE"
ORBITING = "TAL_SHIELD_ORBITING_SHIELD_DISC"
ACTIVE_DEFENSE = "SHIELD_BASE_ACTIVE_DEFENSE"
COVER_ALLY = "TAL_SHIELD_COVER_ALLY"
REACTIVE_DEFENSE = "TAL_SHIELD_REACTIVE_DEFENSE"
BLOCKADE = "TAL_SHIELD_BLOCKADE"
GUARDED_CONDITION = "condition:typed.guarded_stance"
FOCUS = "resource:core.martial_focus"
ORBITING_CONDITION = "condition:typed.orbiting_shield_disc"

#: The printed Shield talents that need a Shield in hand before they work ("Requirement: Wielding a Shield").
NEEDS_A_SHIELD = frozenset({ACTIVE_DEFENSE, COVER_ALLY, REACTIVE_DEFENSE, BLOCKADE})


@hook("compile_block")
def compile_rows(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Guarded Stance and Orbiting Shield Disc's own compiled markers (combat/rules/feature_blocks.d/auto55_shield.json)."""
    if block != BLOCK:
        return None
    return [{**row, "block": BLOCK, "kind": str(spec.get("kind") or ""), "pb": int(numbers.get("pb") or 0),
             "cl": int(numbers.get("cl") or 1), **({"keeps_compiling": True} if spec.get("keeps_compiling") else {})}]


def _row(engine: Any, actor: Any, kind: str) -> dict[str, Any] | None:
    return next((row for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, ())
                 if row.get("block") == BLOCK and row.get("kind") == kind), None)


# --------------------------------------------------------------------------- the shared answer
def shield_in_hand(engine: Any, actor: Any) -> bool:
    """Recorded possession wins; unmarked historical bundles retain their old permission."""
    from .. import armour, carry

    if actor is None or any(c.condition_id == armour.BROKEN_SHIELD for c in actor.conditions.values()):
        return False
    key = armour.shield_item_key(engine, actor)
    if key is not None:
        return not carry.lost_to_another_hand(actor, key)
    carrying = carry.carrying_of(engine, actor.entity_id)
    # Old saved inventories can lack a marker while retaining a compiled Shield
    # bonus. Unknown inventories and that positive legacy evidence keep permission.
    return carrying is None or armour.compiled_shield_bonus(engine, actor) > 0


def orbiting(engine: Any, actor: Any) -> bool:
    """Whether a released Shield is still orbiting its owner (so it counts as wielded)."""
    return actor is not None and any(c.condition_id == ORBITING_CONDITION for c in actor.conditions.values())


def guarded_weapon(engine: Any, actor: Any) -> str | None:
    """The item key of the weapon Guarded Stance is treating as a Shield, while it is still held, or None."""
    held = next((c for c in actor.conditions.values() if c.condition_id == GUARDED_CONDITION), None)
    if held is None:
        return None
    from .. import carry

    key = str(held.data.get("weapon") or "")
    return key if key and carry.holds(engine, actor, key) else None


def wielding_a_shield(engine: Any, actor: Any) -> bool:
    """Whether ``actor`` counts as wielding a Shield for a talent that references one."""
    if actor is None or not actor.active:
        return False
    if shield_in_hand(engine, actor):
        return True
    if orbiting(engine, actor) and _row(engine, actor, "orbiting") is not None:
        from .. import armour

        key = armour.shield_item_key(engine, actor)
        broken = any(c.condition_id == armour.BROKEN_SHIELD for c in actor.conditions.values())
        taken = any(c.data.get('item_key') == key and c.data.get('held_by')
                    and c.data.get('held_by') != actor.entity_id
                    for c in actor.conditions.values()) if key else False
        return not broken and not taken  # orbiting permits release, not destruction or theft
    return _row(engine, actor, "guarded") is not None and guarded_weapon(engine, actor) is not None


def shield_bonus(engine: Any, actor: Any) -> int:
    """The Shield Bonus this fighter is earning right now.

    A held (or orbiting) Shield's, straight from ``combat/armour.py``. Zero for a Guarded Stance weapon: "The
    chosen weapon has a Shield Bonus of 0 unless another feature grants it a Shield Bonus."
    """
    from .. import armour

    if actor is None:
        return 0
    if shield_in_hand(engine, actor):
        return armour.shield_bonus_earning(engine, actor)
    if orbiting(engine, actor) and wielding_a_shield(engine, actor):
        return armour.compiled_shield_bonus(engine, actor)
    return 0


def shield_presented(engine: Any, actor: Any) -> bool:
    """Whether ``actor`` can present its Shield toward an incoming attack.

    Active Defense prints "does not function while you cannot present the Shield toward the incoming attack".
    The fight has no facing, so presenting a Shield means holding it ready: :func:`shield_in_hand` (possession,
    not dropped, taken or broken) and the shared hand occupancy (``combat/ext/hand_occupancy.py``) must give the
    Shield its own hand, rather than leaving it in overflow because every hand is already used for something else.
    Orbiting Shield Disc and Guarded Stance remain the printed "unless a talent says otherwise" exceptions,
    because they keep counting as wielding through :func:`wielding_a_shield`.

    Default-inert: asked only by the Shield talents that print a Shield requirement.
    """
    if actor is None or not actor.active:
        return False
    if not shield_in_hand(engine, actor):
        return wielding_a_shield(engine, actor)
    from .. import armour, carry
    from . import hand_occupancy

    if carry.carrying_of(engine, actor.entity_id) is None:
        return True  # a legacy bundle with no recorded inventory kept shield_in_hand's old permission
    key = armour.shield_item_key(engine, actor)
    if key is None:
        return True
    occupied = hand_occupancy.occupancy(engine, actor)
    parts = hand_occupancy.hand_parts(engine, actor)
    return any(part in parts for part, owners in occupied.items() if f"shield:{key}" in owners)


# --------------------------------------------------------------------------- the printed Requirement
@hook("row_allowed")
def needs_a_shield(engine: Any, actor: Any, row: dict[str, Any]) -> bool | None:
    """Active Defense's printed "Requirement: Wielding a Shield", and the talents that inherit it.

    Without this a fighter with no Shield answered every attack with the +2 AC for free, while Guarded Stance's
    printed "you may use Active Defense when you are not equipped with a Shield" sat on the table as a GM line for
    something the engine already did. Inert for a fighter whose compiled rows carry no Shield talent, and for a
    fighter whose talent is already answered by an orbiting Shield or a Guarded Stance weapon. A reviewed row may
    also carry the general typed flag ``requires_shield``, which this keeps for every talent that prints it.
    """
    if str(row.get("feature_id") or "") not in NEEDS_A_SHIELD and row.get("requires_shield") is not True:
        return None
    return None if shield_presented(engine, actor) else False


# --------------------------------------------------------------------------- Guarded Stance
def wielded_weapons(engine: Any, actor: Any) -> list[tuple[str, str]]:
    """(item key, display name) for every weapon this fighter is still holding."""
    from .. import carry

    carrying = carry.carrying_of(engine, actor.entity_id) or {}
    out = []
    for item in carrying.get("items") or []:
        if not isinstance(item, dict) or not item.get("weapon_action"):
            continue
        key = str(item.get("key") or "")
        if key and carry.holds(engine, actor, key):
            out.append((key, str(item.get("name") or key)))
    return out


@effect("guarded_stance")
def choose_weapon(ctx: Any, eff: dict[str, Any]) -> None:
    """Guarded Stance's printed choice: "Choose one weapon you are wielding" (stored as the item key, so it saves)."""
    engine, actor = ctx.engine, ctx.actor
    if shield_in_hand(engine, actor):
        ctx.rider("Guarded Stance is for a fighter with no Shield in hand; your Shield already counts.")
        return
    weapons = wielded_weapons(engine, actor)
    if not weapons:
        ctx.rider("Guarded Stance needs a weapon you are wielding.")
        return
    engine._remove_condition(actor, GUARDED_CONDITION, str(ctx.source))
    options = [key for key, _ in weapons]
    labels = dict(weapons)
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "GUARDED_STANCE", actor.entity_id), actor,
                 CHOICE + "guarded_stance", options, labels=labels, allow_decline=True, target_id=actor.entity_id,
                 prompt="Guarded Stance: choose the weapon that counts as your Shield from now on",
                 name="Guarded Stance", feature_id=GUARDED)
    if not picked:
        return
    chosen = labels[picked[0]]
    engine._apply_condition(actor, GUARDED_CONDITION, str(ctx.source), actor.entity_id, expires_on="UNTIL_REMOVED",
                            data={"weapon": picked[0],
                                  "label": f"Guarded Stance: {chosen} counts as your Shield for Shield talents (it adds no +2 Armor Class)"})
    note(engine, GUARDED, actor, f"Guarded Stance: {chosen} counts as {actor.display_name}'s Shield for Shield talents. "
                                f"It adds no +2 Armor Class of its own.")


# --------------------------------------------------------------------------- Orbiting Shield Disc
@effect("orbiting_shield_disc")
def orbit(ctx: Any, eff: dict[str, Any]) -> None:
    """"Release your Shield into a controlled orbit around you." Then, for the duration, "count as wielding the
    Shield; retain its Shield Bonus; keep both hands free; may use Shield talents normally" -- the first, third and
    fourth of those are this module's shared answer; the second is the compiled +2 Armor Class, which an orbiting
    Shield never takes back (combat/armour.py)."""
    engine, actor = ctx.engine, ctx.actor
    from ..typed_executor import effect_expiry

    engine._remove_condition(actor, ORBITING_CONDITION, str(ctx.source))
    engine._apply_condition(actor, ORBITING_CONDITION, str(ctx.source), actor.entity_id,
                            expires_on=effect_expiry(ctx, eff, actor, condition=True) or "UNTIL_REMOVED",
                            data={"label": "Orbiting Shield Disc: the Shield counts as wielded and stays in reach"})
    from .. import armour

    note(engine, ORBITING, actor, f"{actor.display_name}'s Shield orbits them: Shield talents keep working and its "
                                 f"+{armour.shield_bonus_earning(engine, actor)} Armor Class is retained.")


# --------------------------------------------------------------------------- Active Defense for Martial Focus
@hook("reaction_spend")
def focus_instead_of_reaction(engine: Any, reactor: Any, row: dict[str, Any], commit: bool) -> str | None:
    """"You may expend Martial Focus to use Active Defense without spending a Reaction."

    A manual player may preserve an available Reaction. The trigger-local row
    carries that consent and price through normal transactional payment; an AI
    uses its Reaction first. Incarnation grants keep their existing precedence.
    """
    if not _is_active_defense(engine, reactor, row):
        return None
    from .reaction_economy import owns_paid_payment, waive

    if owns_paid_payment(engine, reactor, row):
        return None

    selected = bool(row.get('shield_focus_payment'))
    if not selected and waive(engine, reactor, row, False) is not None:
        return None  # the owning economy provider also owns consumption of its grant
    if not selected and (reactor.reaction_available or (not commit and int(reactor.resources.get(FOCUS, 0)) < 1)):
        return None
    if commit:
        from . import note as write

        write(engine, ACTIVE_DEFENSE, reactor,
              f"Active Defense: {reactor.display_name} spends 1 Martial Focus instead of a Reaction.")
    return "free"


@hook("generic_reaction_costs")
def focus_cost(engine: Any, reactor: Any, other: Any, row: dict[str, Any], costs: Any) -> list[dict[str, Any]] | None:
    """The 1 Martial Focus the printed line is spent on, quoted and charged on the same use."""
    if not _is_active_defense(engine, reactor, row):
        return None
    from .reaction_economy import owns_paid_payment, waive

    if owns_paid_payment(engine, reactor, row):
        return []

    if waive(engine, reactor, row, False) is not None:
        return []
    if reactor.reaction_available:
        return []  # prepare a fresh row: consent may select its alternative price
    if int(reactor.resources.get(FOCUS, 0)) < 1:
        return None
    return [{"resource_id": FOCUS, "amount": 1}]


@hook('reaction_consent')
def choose_defense_payment(engine: Any, row: dict[str, Any], reactor: Any, checkpoint: str) -> bool | None:
    """One Ask-me decision chooses both whether to defend and its legal payment.

    Only the fresh row supplied by generic_reaction_costs is changed; no compiled
    or persisted row is rewritten, and the native caller owns spending/effects.
    """
    if not _is_active_defense(engine, reactor, row) or not reactor.reaction_available or reactor.resources.get(FOCUS, 0) < 1:
        return None
    from .reaction_economy import owns_paid_payment, waive

    if owns_paid_payment(engine, reactor, row):
        return None

    if waive(engine, reactor, row, False) is not None:
        return None
    from .choice_prompt import action_context

    trigger = getattr(engine, '_reaction_trigger', None) or {}
    attacker = engine.state.actors.get(trigger.get('actor_id') or '')
    source = trigger.get('source_definition_id') or ''
    context = action_context(engine, attacker, source, reactor)
    context['cost'] = 'Choose: 1 Reaction, or 1 Martial Focus (your readiness point) and keep your Reaction'
    action_name = context.get('action_name') or trigger.get('action_name') or 'attack'
    picked = ask(engine, getattr(engine, '_active_intent', None), checkpoint_id(engine, checkpoint, reactor.entity_id),
                 reactor, CHOICE + 'active_defense_payment', ['reaction', 'focus'],
                 labels={'reaction': 'Spend your Reaction: +2 Armor Class against this attack',
                         'focus': 'Spend 1 Martial Focus (your readiness point), keep your Reaction: +2 Armor Class against this attack'},
                 allow_decline=True, preferred=['reaction'], target_id=reactor.entity_id,
                 name='Active Defense', feature_id=ACTIVE_DEFENSE, prompt_context=context,
                 prompt=f"Active Defense: {attacker.display_name if attacker else 'A creature'} uses {action_name} against {reactor.display_name}. Raise your Shield for +2 Armor Class against this attack; choose how to pay, or decline.")
    if not picked:
        return False
    if picked[0] == 'focus':
        row['shield_focus_payment'] = 1
        row['costs'] = [{'resource_id': FOCUS, 'amount': 1}]
    return True


def _is_active_defense(engine: Any, reactor: Any, row: dict[str, Any]) -> bool:
    if str(row.get("feature_id") or "") != ACTIVE_DEFENSE:
        return False
    return reactor.active and shield_presented(engine, reactor)

@hook("compile_actions")
def guarded_stance_action(info: dict[str, Any]) -> list[Any] | None:
    """Guarded Stance prints no Action Type -- it is a standing choice of a weapon -- so it needs a free action to
    be taken through, the same shape ``shield_riders.extensive_action`` gives Extensive Defense. Offered only while
    no Shield is in hand and no weapon has been chosen yet (``candidate_allowed``)."""
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    if "TAL_SHIELD_GUARDED_STANCE" not in (info.get("owned_ids") or []):
        return None
    typed = {"effects": [{"type": "guarded_stance", "evidence": "Choose one weapon you are wielding. Treat that weapon as a Shield for talents that reference your Shield."}],
             "numbers": dict(info["numbers"]), "duration": {"kind": "instant"}, "riders": [],
             "source": "TAL_SHIELD_GUARDED_STANCE", "coverage": "FULL"}
    return [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.shield.guarded_stance",
                             display_name="Guarded Stance: choose the weapon that counts as your Shield (costs no Action)",
                             owner_id=info["actor_id"], economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
                             costs=(), parameters={"typed": typed, "expected_damage": 0, "player_only": True})]


@hook("candidate_allowed")
def guarded_stance_offered(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """Not offered once a real Shield is in hand, or once a weapon has been chosen; changing the weapon is taking
    the talent again, which the printed "Choose one weapon you are wielding" allows at any time."""
    if action is None or not str(action.source_definition_id).endswith(".shield.guarded_stance"):
        return None
    if shield_in_hand(engine, actor):
        return False
    return None
