"""Shieldhook Adept chooses one ally for Shield-Catching Beard's opening.

The general guard_break_profile seam preserves caster-owned expiry while
selecting a different beneficiary. Ordinary guard breaks remain unchanged.
"""
from . import hook
from .needle import ask, checkpoint_id, option_spec
from .passive_rows import row_of
from ..relations import ALLY, relation

FEATURE = "insight.shieldhook-adept"
BEARD = "TAL_AXES_SHIELD_CATCHING_BEARD"
BLOCK = "shieldhook_adept"
CHOICE = "choice:insights7.shieldhook_adept"


@hook("compile_block")
def compile_rows(block, spec, row, numbers):
    if block == BLOCK:
        return [{**row, "kind": BLOCK, "player_outcome":
                 "Shield-Catching Beard may open the shield for one ally's next attack instead of your own."}]
    return None


@hook("choice_options")
def choices(engine, intent, checkpoint, reactor_id, choice_id, context):
    return option_spec(choice_id, context, CHOICE)


@hook("choice_reactors")
def choosers(engine):
    return tuple(a.entity_id for a in engine.state.actors.values()
                 if row_of(engine, a.entity_id, BLOCK, BLOCK))


@hook("guard_break_profile")
def opening(ctx, target, profile):
    if ctx.source.removeprefix("passive:") != BEARD or not row_of(ctx.engine, ctx.actor.entity_id, BLOCK, BLOCK):
        return None
    allies = [a for a in ctx.engine.state.actors.values() if a.entity_id != ctx.actor.entity_id
              and a.active and relation(ctx.engine, ctx.actor, a) == ALLY]
    if not allies:
        return None
    ids = [ctx.actor.entity_id] + [a.entity_id for a in allies]
    labels = {ctx.actor.entity_id: "Keep Shield-Catching Beard's ordinary benefit for yourself"}
    labels.update({a.entity_id: f"{a.display_name}'s next attack against {target.display_name} ignores Shield AC"
                   for a in allies})
    failed = not bool(profile.get("next"))
    until = "the start of your next turn" if failed else "the end of your current turn"
    # AI knows its own team, but never inspects enemy defenses or ally plans.
    chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "SHIELDHOOK_ADEPT", target.entity_id),
        ctx.actor, CHOICE, ids, labels=labels, preferred=[ctx.actor.entity_id], allow_decline=False,
        prompt=f"Shieldhook Adept during Shield-Catching Beard against {target.display_name}: keep your normal "
               f"benefit, or let one ally's next attack against that creature ignore Shield AC before {until}. "
               "No extra action or resource cost.")
    if not chosen or chosen[0] == ctx.actor.entity_id:
        return None
    ally = ctx.engine.state.actors[chosen[0]]
    return {"beneficiary_id": ally.entity_id, "next": True, "axe": False,
            "expires_on": "START_OF_SOURCE_NEXT_TURN" if failed else f"END_OF_SOURCE_TURN_AT:{ctx.actor.turns_started}",
            "label": f"Shieldhook Adept: {ally.display_name}'s next attack against {target.display_name} "
                     f"ignores Shield AC before {until} of {ctx.actor.display_name}."}
