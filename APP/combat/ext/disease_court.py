"""Court of the Crawling Fever (Disease; owner 2026-09-28: "make sure all the talents ... is applied"). It had compiled as
one save on cast with all of its choose-one results at once and an aura that never triggered.

Now: a 30-foot aura centered on its maker that moves with it (Concentration, up to 1 minute). When a hostile creature
starts its turn inside, it makes a Constitution save: on a failure the chosen result ("Crawling Fever: <result>", a free
choice kept until changed, fixed when the Court is raised; 2d8 Necrotic unless chosen otherwise, or no Reactions, or
Speed -10 feet, until the start of the maker's next turn); on a success its healing is reduced by the maker's PB until
the start of the maker's next turn. Once per turn per creature. "You and allies you choose gain" is asked when the aura
is raised (combat/ext/disease.py choose_court_allies stores the answer on the aura); Disease saves and damage and the
Contagion Token shed follow that choice, and Sickened and the halved healing inside are GM lines: the table has no
Disease tokens.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook

COURT = "tianxia.talent.disease.court_of_the_crawling_fever"
CHOICE = "condition:typed.crawling_fever_choice"
OPTIONS = {"damage": "2d8 Necrotic", "reactions": "No Reactions", "speed": "Speed -10", "sickened": "Sickened", "token": "Contagion Token"}
UNTIL = "START_OF_SOURCE_NEXT_TURN"
FAILED = {"damage": [{"type": "damage", "applies_to": "target", "dice": {"count": 2, "sides": 8}, "damage_types": ["necrotic"],
                      "evidence": "the enemy takes 2d8 Necrotic, Poison, or Psychic damage"}],
          "reactions": [{"type": "condition", "condition": "reaction_denied", "applies_to": "target", "expires_on": UNTIL,
                         "evidence": "the enemy cannot take Reactions until the start of your next turn"}],
          "speed": [{"type": "speed", "flat": -10, "applies_to": "target", "expires_on": UNTIL,
                     "evidence": "the enemy's Speed is reduced by 10 feet until the start of your next turn"}],
          # rider lane 10: the two choices the table had left to the GM (combat/ext/disease.py keeps the tokens)
          "sickened": [{"type": "condition", "condition": "sickened", "applies_to": "target", "expires_on": UNTIL,
                        "evidence": "the enemy becomes Sickened until the start of your next turn"}],
          "token": [{"type": "disease_tokens", "applies_to": "target", "count": 1, "evidence": "the enemy gains one Contagion Token"}]}


@hook("compile_actions")
def fever_choices(info: dict[str, Any]) -> list[Any] | None:
    if COURT not in info["owned_ids"]:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    from ..action_variants import choice, with_variant

    # One Crawling Fever setting with a fever axis.
    return [with_variant(ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.crawling_fever.{key}", display_name=f"Crawling Fever: {label}",
        owner_id=info["actor_id"], economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
        parameters={"setting_only": True, "typed": {"effects": [{"type": "crawling_fever_choice", "choice": key}], "numbers": info["numbers"],
                              "duration": {"kind": "instant"}, "riders": []}, "expected_damage": 0, "player_only": True}),
        f"action:typed.{info['short']}.crawling_fever", "Crawling Fever", [choice("fever", key, label)])
        for key, label in OPTIONS.items()]


@effect("crawling_fever_choice")
def fever_choice(ctx: Any, eff: dict[str, Any]) -> None:
    ctx.engine._remove_condition(ctx.actor, CHOICE, ctx.source)
    ctx.engine._apply_condition(ctx.actor, CHOICE, ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
                                data={"choice": eff.get("choice"), "label": f"Crawling Fever: {OPTIONS.get(str(eff.get('choice')), '')}"})


START_TRIGGER_ID = f"{COURT}:start"


def _already_standing(zone: Any) -> bool:
    """Whether this aura has already been set up.

    The printed "When an enemy starts its turn in the aura, it makes a Constitution saving throw" is compiled into
    the area's own ``:own`` start trigger (``factory_compiler`` gives a zone the ability's own effects), so this
    effect runs again on every enemy turn start inside the aura -- not only when the maker raises it. Raising the
    Court is a one-time act: its start trigger and its maker's answer to "you and allies you choose" are made once
    and then stand, so a turn trigger re-entering setup would append a second copy of the trigger and put a second
    question to the maker on somebody else's turn, replacing the answer that was already saved.

    An aura carries its own setup marker: the Court's start trigger, or -- for a fight saved before the choice was
    stored -- the stored answer itself. Either means the aura is already standing.
    """
    from .disease import COURT_ALLIES

    profile = zone.trigger_profile or {}
    if any(str(trigger.get("id")) == START_TRIGGER_ID for trigger in profile.get("triggers") or []):
        return True
    return COURT_ALLIES in profile


@effect("crawling_fever")
def crawling_fever(ctx: Any, eff: dict[str, Any]) -> None:
    """Runs after the aura is made (typed_executor makes an ability's area before its effects).

    Only when the maker raises the Court: see ``_already_standing`` for why an enemy starting its turn inside the
    aura must not re-run any of this.
    """
    from .tabik_dark import republish, zone_made_now

    zone = zone_made_now(ctx)
    if zone is None or _already_standing(zone):
        return
    choice = next((str((c.data or {}).get("choice")) for c in ctx.actor.conditions.values() if c.condition_id == CHOICE), "damage")
    trigger = {"id": START_TRIGGER_ID, "name": "Court of the Crawling Fever", "on": ["start"], "who": "hostile",
               "effects": [{"type": "save", "ability": "con", "applies_to": "target", "on_fail": FAILED.get(choice, FAILED["damage"]),
                            "on_success": [{"type": "healing_reduction", "applies_to": "target", "expires_on": UNTIL,
                                            "evidence": "Healing the enemy receives is reduced by your Proficiency Bonus until the start of your next turn."}],
                            "evidence": "When an enemy starts its turn in the aura, it makes a Constitution saving throw."}]}
    # "Enemies in the aura cannot regain more than half the normal Hit Points from healing" (rider lane 10: the zone's inside rule).
    inside = [*(zone.trigger_profile.get("inside") or []), {"id": "crawling_healing", "who": "hostile", "name": "Court of the Crawling Fever",
                                                             "reading": "Healing is halved inside the Court of the Crawling Fever", "rule": {"healing_halved": True}}]
    zone.trigger_profile = {**zone.trigger_profile, "follows_owner": True, "triggers": [*(zone.trigger_profile.get("triggers") or []), trigger],
                            "inside": inside}
    # "You and allies you choose gain: ..." -- the maker is asked which allies standing in the aura share its benefits
    # (combat/ext/disease.py owns the reading of the answer for all four printed benefits).
    from . import disease

    disease.choose_court_allies(ctx, zone)
    republish(ctx.engine, zone, ctx.source)
