"""Spirit Companions check benefits on existing roll and ownership hooks.

compile_block seals owned spirit_counsel rows and enrolls their manual owners
in off-turn choices. d20_bonus applies Independent Counsel once per fight;
contest_check_mode applies Ethical Exorcist only to a declared qualifying
Cultivation procedure. No core patch, global roll change or new engine seam.

Nature relevance is the owner's optional Counsel declaration, not a fact
inferred from hidden creature data. AI owners conservatively decline Counsel
when the table has no recorded Nature/check relationship. Ethical Exorcist's
purpose is a prospective player decision, never a guess about a spirit's secrets.
An expressly referring Source Rule can set typed.spirit_procedure to one of the
three canonical procedure IDs; that does not create or execute the procedure.

The printed limit is once per short rest. Use the engine's short-rest expiry so the choice
can be used again after the rest transition.
"""
from . import hook
from .choice_prompt import action_context
from .needle import ask, checkpoint_id
from .passive_rows import row_of

P = "tianxia.talent.spirit_companions."
COUNSEL = P + "independent_counsel"
ETHICAL = "insight.ethical-exorcist"
BLOCK = "spirit_counsel"
USED = "condition:typed.spirit_counsel_used"
PROCEDURES = frozenset({P + "break_the_cruel_seal", P + "exorcist_s_mercy",
                        P + "true_name_mercy"})


@hook("compile_block")
def spirit_check_row(block, spec, row, numbers):
    if block == BLOCK:
        return [{**row, "block": BLOCK, "kind": spec["kind"], "choice_owner": True}]


def _owns(engine, actor, kind):
    return row_of(engine, actor.entity_id, BLOCK, kind) is not None


@hook("d20_bonus")
def independent_counsel(engine, roll, intent):
    actor = engine.state.actors.get(roll.actor_id)
    if actor is None or not _owns(engine, actor, "counsel"):
        return None
    context = engine.d20_context(roll) or {}
    if context.get("kind") != "check" or any(c.condition_id == USED for c in actor.conditions.values()):
        return None
    from ..ability_checks import roll_skill_proficiency

    # Explicit ranks, not numeric totals: Expertise also counts as adding PB.
    # Kind-only Cultivation checks add PB; ordinary unskilled checks do not.
    kind = context.get("check_kind")
    rank = (1 if kind == "cultivation" else
            0 if not context.get("skill") and kind in {"check", "key_ability"} else
            roll_skill_proficiency(engine, actor, roll))
    pb = int(actor.proficiency_bonus)
    amounts = {"nature": pb // 2 if rank else pb} if rank is not None else {
        "untrained": pb, "proficient": pb // 2}
    labels = {key: f"This check involves my bonded spirit's Nature: add {amount}"
              + (" (already adding Proficiency)" if key == "proficient" else
                 " (not already adding Proficiency)" if key == "untrained" else "")
              for key, amount in amounts.items()}
    source = str(context.get("source_id") or "")
    initiator = engine.state.actors.get(context.get("source_actor_id")) or actor
    picked = ask(engine, intent, checkpoint_id(engine, "SPIRIT_COUNSEL", roll.roll_id), actor,
        "choice:needle.spirit_counsel", list(amounts), labels=labels,
        allow_decline=True, default="decline", automatic=False,
        name="Independent Counsel", feature_id=COUNSEL, target_id=actor.entity_id,
        prompt=(f"Independent Counsel: for {actor.display_name}'s ability check during "
                f"{getattr(engine.action_catalog.get(source), 'display_name', 'this action')}, "
                "use your bonded spirit's advice only if the check involves its Nature. "
                "Add your Proficiency Bonus, or half if the roll already adds Proficiency. "
                "No action or CP; once per short rest. Decline if the check does not involve its Nature."),
        prompt_context=action_context(engine, initiator, source, actor))
    if not picked:
        return None
    amount = amounts[picked[0]]
    engine._apply_condition(actor, USED, COUNSEL, actor.entity_id,
        expires_on="UNTIL_SHORT_REST",
        data={"label": "Independent Counsel used: once per short rest"})
    return {"source_id": COUNSEL, "user_id": actor.entity_id, "bonus": amount}


@hook("contest_check_mode")
def ethical_exorcist(ctx, subject, opponent, spec):
    if (subject is not ctx.actor or spec.get("kind") != "cultivation"
            or not _owns(ctx.engine, subject, "ethical")):
        return None
    typed = (ctx.action.parameters.get("typed") or {})
    procedure = (ctx.typed.get("spirit_procedure") or typed.get("spirit_procedure")
                 or ctx.typed.get("source") or typed.get("source")
                 or ctx.action.source_definition_id)
    if procedure not in PROCEDURES:
        return None
    picked = ask(ctx.engine, ctx.intent,
        checkpoint_id(ctx.engine, "ETHICAL_EXORCIST", subject.entity_id, opponent.entity_id,
                      ctx.source, ctx.engine.roller.counter),
        subject, "choice:needle.ethical_exorcist",
        ["free", "calm", "separate", "release", "coerce"],
        labels={"free": "Free the spirit from coercive control: Advantage",
                "calm": "Calm a maddened, frightened, wounded or contaminated spirit: Advantage",
                "separate": "Separate spirit and host without destroying either: Advantage",
                "release": "Release to a state permitted by the spirit's source rule: Advantage",
                "coerce": "Enslave, force service, destroy a soul, steal a vessel or Name, or take an unwilling companion: no bonus"},
        preferred=["free" if procedure == P + "break_the_cruel_seal" else "separate"],
        allow_decline=True, default="decline", name="Ethical Exorcist", feature_id=ETHICAL,
        target_id=opponent.entity_id,
        prompt=(f"Ethical Exorcist: declare {subject.display_name}'s purpose for "
                f"{ctx.action.display_name} affecting {opponent.display_name}. "
                "A listed merciful purpose grants Advantage on this Cultivation Check, at no extra cost. "
                "Coercion, theft and destroying a complete soul never qualify."),
        prompt_context=action_context(ctx.engine, subject, ctx.source, opponent, action=ctx.action))
    return "ADVANTAGE" if picked and picked[0] != "coerce" else None
