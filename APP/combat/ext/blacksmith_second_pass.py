"""Shared helper module: combat/ext/blacksmith_forge.py uses current_item and hammer_item.

Blacksmith combat responses on the existing equipment-carrier chassis.

Shared public helper: consumed by blacksmith_forge.py. Its exported functions are
the stable cross-plugin API; private helpers stay private.

Quench binds independently marked allied items to physical inventory and native
attack/tool provenance. The older personal equipment declaration is retained for
existing personal-workpiece actions; it never qualifies an allied carrier's item.

Steady Hammer reads explicit persisted Smith's Tools proficiency, never a total.
Incarnation's repeated benefits require its own timed activation condition.
"""
from . import effect, hook
from .blacksmith_forge import held_condition, mark_count, set_marks, FORGE_MARK, INCARNATION

K = "tianxia.talent.blacksmith."
QUENCH = K + "quench_against_the_grain"
STEADY = K + "steady_hammer_breathing"
BLOCK = "blacksmith_second_pass"
EQUIPMENT = "condition:typed.blacksmith_quench_equipment"
LIVING = "condition:typed.blacksmith_living_forge"
EXPERT_USED = "condition:typed.blacksmith_steady_expertise_used"
EXPERT_PENDING = "condition:typed.blacksmith_steady_expertise_pending"
WORKPIECE = "condition:typed.blacksmith_current_item"
QUENCH_ROUND = "condition:typed.blacksmith_quench_round"


@hook('compile_action')
def hammer_item_targets(action, info):
    """Seal a carrier target for an explicitly selected physical workpiece."""
    typed = action.parameters.get('typed') or {}
    if (typed.get('source') != 'BLACKSMITH_BASE_HAMMER_THE_MARK'
            or not {QUENCH, STEADY}.intersection(info['owned_ids'])):
        return None
    return action.model_copy(update={'target_kind': 'ANY_CREATURE', 'parameters': {
        **action.parameters, 'blacksmith_original_target': action.target_kind}})


@hook("compile_block")
def compile_block(block, spec, row, numbers):
    if block == BLOCK:
        return [{**row, "block": BLOCK, "kind": spec["kind"]}]
    return None


def owns(engine, actor, kind):
    from .passive_rows import row_of
    return row_of(engine, actor.entity_id, BLOCK, kind) is not None


@hook("compile_actions")
def actions(info):
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    made = []
    if ({QUENCH, STEADY}.intersection(info['owned_ids'])
            and any(str(a.source_definition_id).endswith('BLACKSMITH_BASE_HAMMER_THE_MARK') for a in info['actions'])):
        for kind in ('equipment', 'tool', 'none'):
            made.append(ActionDefinition(
                source_definition_id=f"action:typed.{info['short']}.blacksmith.current_item.{kind}",
                display_name='Set current workpiece: ' + ('a carried tool' if kind == 'tool' else 'a carried item' if kind == 'equipment' else 'clear item selection'),
                owner_id=info['actor_id'], economy=EconomyKind.NONE, resolution_kind='TYPED', target_kind='SELF',
                parameters={'setting_only': True, 'expected_damage': 0, 'player_only': kind == 'tool',
                            'setting_description': 'Choose an actual carried item within reach. This does not equip it or place a Forge Mark. Hammer the Mark places marks on the selected item; clear this selection to use the original workpiece.',
                            'typed': {'numbers': info['numbers'], 'effects': [{'type': 'blacksmith_current_item', 'kind': kind}], 'riders': []}}))
    if QUENCH in info["owned_ids"]:
        for kind, label in [("weapon", "weapon"), ("armor", "armor or shield"), ("tool", "tool"), ("none", "unspecified equipment")]:
            made.append(ActionDefinition(
                source_definition_id=f"action:typed.{info['short']}.blacksmith.quench_equipment.{kind}",
                display_name="Quench Against the Grain: my marked workpiece is " + label,
                owner_id=info["actor_id"], economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
                parameters={"setting_only": True, "player_only": True, "expected_damage": 0,
                            "setting_description": "Declare the equipment actually bearing your Forge Marks. This does not equip or mark an item. The declaration ends when the last mark is gone.",
                            "typed": {"numbers": info["numbers"], "effects": [{"type": "blacksmith_quench_equipment", "kind": kind}], "riders": []}}))
    if INCARNATION in info["owned_ids"]:
        made.append(ActionDefinition(
            source_definition_id=f"action:typed.{info['short']}.blacksmith.living_forge_mark",
            display_name="Living Forge: place a Forge Mark (once this turn)", owner_id=info["actor_id"],
            economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
            parameters={"expected_damage": 0, "typed": {"numbers": info["numbers"], "effects": [{"type": "blacksmith_living_mark"}], "riders": []}}))
    return made


@effect('blacksmith_current_item')
def select_item(ctx, row):
    from ..item_uses import inventory
    from .needle import ask, checkpoint_id
    import json
    if row['kind'] == 'none':
        ctx.engine._remove_condition(ctx.actor, WORKPIECE, ctx.source)
        return
    found = [item for item in inventory(ctx.engine)
             if ctx.engine._distance_actor_to_actor(ctx.actor, ctx.engine.state.actors[item['carrier']]) <= 5
             and (row['kind'] != 'tool' or item['kind'] == 'object')]
    options = {json.dumps([item['owner'], item['key']]): item for item in found}
    chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'BLACKSMITH_ITEM', ctx.source), ctx.actor,
                 'choice:needle.blacksmith_item', list(options),
                 labels={key: item['name'] + ' carried by ' + ctx.engine.state.actors[item['carrier']].display_name for key, item in options.items()},
                 name='Current workpiece', prompt='Choose the actual item you can work on. Selecting a tool confirms this item is a tool; it does not place marks or equip it.',
                 allow_decline=True, default='decline', automatic=row['kind'] != 'tool')
    if not chosen:
        return
    item = options[chosen[0]]
    ctx.engine._remove_condition(ctx.actor, WORKPIECE, ctx.source)
    ctx.engine._apply_condition(ctx.actor, WORKPIECE, ctx.source, ctx.actor.entity_id, expires_on='UNTIL_REMOVED',
        data={'owner': item['owner'], 'key': item['key'], 'kind': 'tool' if row['kind'] == 'tool' else item['kind'],
              'label': 'Current workpiece: ' + item['name']})


def current_item(engine, smith):
    from ..item_uses import carried_item
    selected = held_condition(smith, WORKPIECE)
    if selected is None:
        return None
    found = carried_item(engine, selected.data['owner'], selected.data['key'])
    if found is None:
        return None
    return {**found, 'kind': selected.data['kind']}


@hook('candidate_allowed')
def hammer_current_target(engine, actor, candidate, action):
    typed = (getattr(action, 'parameters', None) or {}).get('typed') or {}
    if typed.get('source') != 'BLACKSMITH_BASE_HAMMER_THE_MARK':
        return None
    if not held_condition(actor, WORKPIECE):
        original = (action.parameters or {}).get('blacksmith_original_target')
        if original == 'ALLY_OR_SELF':
            from ..relations import ALLY, relation
            return all(relation(engine, actor, engine.state.actors[key]) == ALLY for key in candidate.target_ids)
        if original == 'SELF':
            return candidate.target_ids == (actor.entity_id,)
        return None
    item = current_item(engine, actor)
    if item is None:
        return False
    return (engine._distance_actor_to_actor(actor, engine.state.actors[item['carrier']]) <= 5
            and (action.target_kind == 'SELF' or candidate.target_ids == (item['carrier'],)))


def hammer_step(ctx, item, timing):
    from .granted_moves import destinations, commit
    from .needle import ask, checkpoint_id, cell_id
    from . import ai_controlled
    routes = {cell_id(cell): (cell, path, cost) for cell, path, cost in
              destinations(ctx.engine, ctx.actor, 5, lambda cell: cell != ctx.actor.position)}
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'BLACKSMITH_STEP', ctx.source), ctx.actor,
                 'choice:needle.blacksmith_step', list(routes),
                 labels={key: f'Move 5 feet to {cell.x},{cell.y}' for key, (cell, _, _) in routes.items()},
                 name='Steady Hammer Breathing', feature_id=STEADY, target_id=item['carrier'],
                 prompt=f'Steady Hammer Breathing: choose one legal step {timing} Hammer the Mark on {item["name"]}. Only {ctx.engine.state.actors[item["carrier"]].display_name}, who carries this workpiece, cannot make an opportunity attack against this step. Other creatures can.',
                 allow_decline=True, default='first' if ai_controlled(ctx.engine, ctx.actor) else 'decline', automatic=True)
    if picked:
        commit(ctx.engine, ctx.actor, routes[picked[0]][1], STEADY, budget_ft=5, provokes=True,
               ignore_oa_from=(item['carrier'],), intent=ctx.intent)


def hammer_item(ctx):
    """Resolve the real Hammer mark once, bracketed by one native optional step."""
    selected = held_condition(ctx.actor, WORKPIECE)
    if selected is None:
        return False
    item = current_item(ctx.engine, ctx.actor)
    if item is None or ctx.engine._distance_actor_to_actor(ctx.actor, ctx.engine.state.actors[item['carrier']]) > 5:
        ctx.rider('Your current workpiece is not carried within reach; no Forge Mark is placed.')
        return True
    from .blacksmith_forge import limit, two_beat_count, item_lock_id, workpiece_locked, TWO_BEAT
    holder = ctx.engine.state.actors[item['owner']]
    if mark_count(holder, ctx.actor.entity_id, item_key=item['key']) >= limit(ctx.engine, ctx.actor):
        ctx.rider('This item already holds your maximum Forge Marks; no mark or step is granted.')
        return True
    if workpiece_locked(ctx.actor, holder, item_key=item['key']):
        ctx.rider('Two-Beat Temper prevents further marks on this item until your next turn.')
        return True
    timing = []
    if owns(ctx.engine, ctx.actor, 'steady'):
        from .needle import ask, checkpoint_id
        from . import ai_controlled
        timing = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'BLACKSMITH_STEP_TIMING', ctx.source), ctx.actor,
                     'choice:needle.blacksmith_step_timing', ['before', 'after'],
                     labels={'before': 'One 5-foot step before the work', 'after': 'One 5-foot step after the work'},
                     prompt=f'Steady Hammer Breathing: move once before or after Hammer the Mark on {item["name"]}? The work is performed once.',
                     name='Steady Hammer Breathing', feature_id=STEADY, target_id=item['carrier'],
                     allow_decline=True, default='first' if ai_controlled(ctx.engine, ctx.actor) else 'decline', automatic=True)
    if timing == ['before']:
        hammer_step(ctx, item, 'before')
    # A step/OA can invalidate the actual work; never mark an out-of-reach item.
    item = current_item(ctx.engine, ctx.actor)
    if (not ctx.actor.active or item is None
            or ctx.engine._distance_actor_to_actor(ctx.actor, ctx.engine.state.actors[item['carrier']]) > 5):
        ctx.rider('The workpiece is no longer within reach; no Forge Mark is placed.')
        return True
    number = two_beat_count(ctx, holder, item_key=item['key'])
    placed = set_marks(ctx.engine, ctx.actor, holder, number, ctx.source, item_key=item['key'])
    if placed > 0 and number == 2:
        from .effect_durations import token
        ctx.engine._apply_condition(holder, item_lock_id(ctx.actor.entity_id, item['key']), TWO_BEAT,
            ctx.actor.entity_id, expires_on=token('start', ctx.actor.entity_id, ctx.actor.turns_started + 1),
            data={'label': 'Two-Beat Temper: no further Forge Marks on ' + item['name'] + ' until your next turn'})
    if timing == ['after'] and ctx.actor.active:
        hammer_step(ctx, item, 'after')
    return True


def item_smiths(engine, item, kind, opponent):
    """All distinct smiths with a qualifying mark on this exact used item."""
    if item is None or item['kind'] not in kind:
        return []
    from .spirit_traditions import can_react
    from ..typed_reactions import reaction_permitted_against
    holder = engine.state.actors[item['owner']]
    return [smith for smith in engine.state.actors.values()
            if owns(engine, smith, 'quench') and can_react(smith)
            and reaction_permitted_against(engine, smith, opponent)
            and not quench_used(engine, smith)
            and mark_count(holder, smith.entity_id, item_key=item['key']) > 0]


def quench_used(engine, smith):
    receipt = held_condition(smith, QUENCH_ROUND)
    return bool(receipt and receipt.data.get('round') == engine.state.round_number)


@effect("blacksmith_quench_equipment")
def declare(ctx, row):
    ctx.engine._remove_condition(ctx.actor, EQUIPMENT, QUENCH)
    if row["kind"] != "none" and mark_count(ctx.actor, ctx.actor.entity_id):
        ctx.engine._apply_condition(ctx.actor, EQUIPMENT, QUENCH, ctx.actor.entity_id,
            expires_on="UNTIL_REMOVED", data={"kind": row["kind"], "label": "Quench Against the Grain: marked " + row["kind"]})


@hook("candidate_allowed")
def living_candidate(engine, actor, candidate, action):
    if action is None or not action.source_definition_id.endswith("blacksmith.living_forge_mark"):
        return None
    from .blacksmith_forge import limit, TWO_BEAT_LOCK
    return bool(held_condition(actor, LIVING) and not actor.turn_flags.get("blacksmith_living_mark")
                and mark_count(actor, actor.entity_id) < limit(engine, actor)
                and not held_condition(actor, TWO_BEAT_LOCK + actor.entity_id))


@effect("blacksmith_living_mark")
def living_mark(ctx, row):
    if held_condition(ctx.actor, LIVING) and not ctx.actor.turn_flags.get("blacksmith_living_mark"):
        if set_marks(ctx.engine, ctx.actor, ctx.actor, 1, INCARNATION) > 0:
            ctx.actor.turn_flags["blacksmith_living_mark"] = True


@effect("blacksmith_living_forge")
def living_forge(ctx, row):
    from ..typed_executor import clock_expiry
    ctx.engine._apply_condition(ctx.actor, LIVING, ctx.source, ctx.actor.entity_id,
        expires_on=clock_expiry(ctx.engine, "one_minute"), data={"label": "Incarnation of the Living Forge"})


@hook("mark_spent")
def living_spend(ctx, name, subject):
    if name == FORGE_MARK and held_condition(ctx.actor, LIVING):
        ctx.engine._grant_temp_hp(ctx.actor, int(ctx.actor.proficiency_bonus), INCARNATION, ctx.actor.entity_id)
    if name == FORGE_MARK and subject is ctx.actor and mark_count(subject, ctx.actor.entity_id) == 0:
        ctx.engine._remove_condition(ctx.actor, EQUIPMENT, QUENCH)


@hook("turn_start")
@hook("turn_end")
def retire_declaration(engine, actor):
    if held_condition(actor, EQUIPMENT) and not mark_count(actor, actor.entity_id):
        engine._remove_condition(actor, EQUIPMENT, QUENCH)


def quench_available(engine, smith, kind, opponent):
    """Answer only the triggering opponent the shared reaction gate permits."""
    from .spirit_traditions import can_react
    from ..typed_reactions import reaction_permitted_against
    row = held_condition(smith, EQUIPMENT)
    return (owns(engine, smith, "quench") and can_react(smith) and row is not None
            and reaction_permitted_against(engine, smith, opponent)
            and row.data.get("kind") == kind and mark_count(smith, smith.entity_id) > 0
            and not quench_used(engine, smith))


def pay_quench(engine, smith, opponent, intent, prompt, provenance, *, item=None):
    """Offer the correction, naming the action that asked and the creature it concerns.

    ``provenance`` is choice_prompt.action_context for the triggering attack, so the
    table reads "who struck, with what, landing on whom" instead of a bare sentence.
    """
    from . import ai_controlled
    from ..typed_reactions import reaction_permitted_against
    if not reaction_permitted_against(engine, smith, opponent):
        return False
    from .needle import ask, checkpoint_id
    chosen = ask(engine, intent, checkpoint_id(engine, "BLACKSMITH_QUENCH", smith.entity_id), smith,
        "choice:needle.blacksmith_quench", ["quench"], labels={"quench": "Spend your Reaction and 1 Forge Mark"},
        prompt=prompt, name="Quench Against the Grain", feature_id=QUENCH,
        allow_decline=True, default="first" if ai_controlled(engine, smith) else "decline", automatic=True,
        prompt_context={**provenance, "cost": "1 Reaction and 1 Forge Mark", "duration": "This roll only"})
    if not chosen:
        return False
    from ..typed_reactions import spend_reaction
    from .spirit_traditions import context, feature_action, numbers
    from .blacksmith_forge import spend_marks, spend_item_marks
    ctx = context(engine, smith, feature_action(engine, smith, QUENCH), [smith], numbers(engine, smith), intent)
    holder = engine.state.actors[item['owner']] if item else smith
    key = item['key'] if item else ''
    if not can_pay_item(engine, smith, holder, key):
        return False
    spend_reaction(engine, smith, {"feature_id": QUENCH})
    # Not an assert: python -O would strip the payment itself.
    if item:
        spent = spend_item_marks(ctx, smith, item['owner'], key, 1, QUENCH)
    else:
        spent = spend_marks(ctx, smith, 1, QUENCH)
    if spent != 1:
        raise RuntimeError("Quench resolved without spending its Forge Mark")
    smith.turn_flags["blacksmith_quench_round_used"] = int(engine.state.round_number)
    engine._remove_condition(smith, QUENCH_ROUND, QUENCH)
    engine._apply_condition(smith, QUENCH_ROUND, QUENCH, smith.entity_id,
        expires_on=f'START_OF_SLOT_AT:{int(engine.state.round_number) + 1}:0',
        data={'round': int(engine.state.round_number), 'label': 'Quench Against the Grain: used this round'})
    engine._append_event("REACTION_RESOLVED", QUENCH, actor_id=smith.entity_id,
                        target_ids=(smith.entity_id,), payload={"text": prompt})
    return True


def can_pay_item(engine, smith, holder, key):
    from .spirit_traditions import can_react
    return (can_react(smith) and mark_count(holder, smith.entity_id, item_key=key) > 0
            and not quench_used(engine, smith))


def attack_context(engine, attacker, target, spec):
    """Name the attack that asked for the correction, and the creature it lands on.

    Both Quench corrections answer one attack, so both describe it the same way: the
    creature whose strike triggered the question, and the creature that strike concerns.
    ``spec`` is the engine's own attack record, so a native and a typed attack name
    themselves identically.
    """
    from .choice_prompt import action_context
    return action_context(engine, attacker, str(spec.get("source_definition_id") or ""), target)


@hook("attack_miss_outcome")
def correct_miss(engine, attacker, target, spec, roll, intent, total, armor_class):
    # A parent can carry a weapon identity while this particular packet is
    # explicitly unarmed/other. Identity alone must not override native use.
    packet_kind = (spec.get('parameters') or {}).get('attack_kind')
    if 1 <= armor_class - total <= 2 and (packet_kind is None or str(packet_kind).lower() == 'weapon'):
        from ..item_uses import attack_item
        item = attack_item(engine, attacker, spec)
        for smith in item_smiths(engine, item, {'weapon'}, target):
            from . import ai_controlled
            from ..relations import ENEMY, relation
            if ai_controlled(engine, smith) and (relation(engine, smith, attacker) == ENEMY
                    or relation(engine, smith, target) != ENEMY):
                continue
            if pay_quench(engine, smith, target, intent,
                    f'{attacker.display_name} missed {target.display_name} by {armor_class - total} using {item["name"]}, which bears your Forge Mark. Turn this miss into a hit?',
                    attack_context(engine, attacker, target, spec), item=item):
                return {'source_id': QUENCH, 'label': 'Quench Against the Grain', 'force_hit': True}
    if (not quench_available(engine, attacker, "weapon", target) or not 1 <= armor_class - total <= 2
            or str((spec.get("parameters") or {}).get("attack_kind") or "").lower() != "weapon"):
        return None
    from . import ai_controlled
    from ..relations import ENEMY, relation
    if ai_controlled(engine, attacker) and relation(engine, attacker, target) != ENEMY:
        return None
    if pay_quench(engine, attacker, target, intent, f"Your marked weapon missed {target.display_name} by {armor_class - total}. Turn this miss into a hit?",
                  attack_context(engine, attacker, target, spec)):
        return {"source_id": QUENCH, "label": "Quench Against the Grain", "force_hit": True}
    return None


@hook("hit_response")
def correct_hit(engine, attacker, target, spec, total, natural, effective_ac):
    if 0 <= total - effective_ac <= 2:
        from ..item_uses import inventory
        from ..armour import shield_item_key
        from .shield_wielding import wielding_a_shield
        for item in inventory(engine):
            if item['carrier'] != target.entity_id or item['kind'] not in {'armor', 'shield'}:
                continue
            if item['kind'] == 'shield' and (item['owner'] != target.entity_id
                    or shield_item_key(engine, target) != item['key'] or not wielding_a_shield(engine, target)):
                continue
            for smith in item_smiths(engine, item, {'armor', 'shield'}, attacker):
                from . import ai_controlled
                from ..relations import ENEMY, relation
                if ai_controlled(engine, smith) and relation(engine, smith, target) == ENEMY:
                    continue
                if pay_quench(engine, smith, attacker, engine._active_intent,
                        f'{attacker.display_name} hit {target.display_name} by {total - effective_ac}. Spend your Forge Mark on {item["name"]} to turn this hit into a miss?',
                        attack_context(engine, attacker, target, spec), item=item):
                    from ..attack_outcomes import unconditional_miss
                    return unconditional_miss()
    # Printed hit-by-two includes a tie. This is an explicit forced outcome,
    # including a natural 20 whose final total is within the printed margin.
    if not quench_available(engine, target, "armor", attacker) or not 0 <= total - effective_ac <= 2:
        return None
    if pay_quench(engine, target, attacker, engine._active_intent, f"{attacker.display_name} hit you by {total - effective_ac}. Use your marked armor or shield to turn this hit into a miss?",
                  attack_context(engine, attacker, target, spec)):
        from ..attack_outcomes import unconditional_miss
        return unconditional_miss()
    return None


def smiths_tools(name):
    return str(name or "").replace("’", "'").replace("_", " ").casefold() in {"smith's tools", "smiths tools"}


@hook('d20_bonus')
def quench_tool(engine, roll, intent):
    context = engine.d20_context(roll) or {}
    used = context.get('used_tool')
    if context.get('kind') != 'check' or not used:
        return None
    from ..item_uses import carried_item
    item = carried_item(engine, used['owner'], used['key'])
    if item is None or item['carrier'] != roll.actor_id:
        return None
    # Explicit native tool-use provenance supplies kind, never a skill label.
    item = {**item, 'kind': 'tool'}
    actor = engine.state.actors[roll.actor_id]
    from .choice_prompt import action_context, initiating_actor
    source = str(context.get('source_id') or '')
    trigger_actor = initiating_actor(engine, actor, engine.action_catalog.get(source))
    for smith in item_smiths(engine, item, {'tool'}, actor):
        from . import ai_controlled
        from ..relations import ENEMY, relation
        if ai_controlled(engine, smith) and relation(engine, smith, actor) == ENEMY:
            continue
        if pay_quench(engine, smith, actor, intent,
                f'{actor.display_name} is making {context.get("skill") or "an ability check"} using {item["name"]}. Add your Proficiency Bonus to this check?',
                action_context(engine, trigger_actor, source, actor), item=item):
            return {'source_id': QUENCH, 'bonus': int(smith.proficiency_bonus)}
    return None


@hook("d20_bonus")
def steady_bonus(engine, roll, intent):
    actor = engine.state.actors.get(roll.actor_id)
    if actor is None or not owns(engine, actor, "steady") or not str(roll.reason).startswith("CHECK:"):
        return None
    context = engine.d20_context(roll) or {}
    if not smiths_tools(context.get("skill") or str(roll.reason).rpartition(":")[2]):
        return None
    if smith_proficiency(engine, actor) == 1:
        return {"source_id": STEADY, "bonus": int(actor.proficiency_bonus)}
    return None


@hook("skill_check_mode")
def steady_expertise(ctx, actor, ability, skill):
    if not smiths_tools(skill) or not owns(ctx.engine, actor, "steady") or held_condition(actor, EXPERT_USED):
        return None
    if smith_proficiency(ctx.engine, actor) != 2:
        return None
    pending = held_condition(actor, EXPERT_PENDING)
    intent_id = str(getattr(ctx.intent, "intent_id", ""))
    if pending and pending.data.get("source") == ctx.source and pending.data.get("intent") == intent_id:
        return "ADVANTAGE"
    if pending:
        ctx.engine._remove_condition(actor, EXPERT_PENDING, STEADY)
    from .needle import ask, checkpoint_id
    from .choice_prompt import action_context, initiating_actor
    # The sheet that carries Steady Hammer is the subject of the check, so it is the
    # creature this question concerns. It is not necessarily the creature whose action
    # asked for the check: on an opposed check's defending side the check rides another
    # creature's action, and the table must say "who acted" and "who is checked" apart.
    action = getattr(ctx, "action", None)
    meta = action_context(ctx.engine, initiating_actor(ctx.engine, actor, action), ctx.source, actor,
                          action=action)
    if not ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "STEADY_HAMMER", actor.entity_id), actor,
        "choice:needle.blacksmith_steady", ["advantage"], labels={"advantage": "Use your once-per-short-rest Advantage"},
        prompt="Use Steady Hammer Breathing on this Smith's Tools check?", name="Steady Hammer Breathing",
        allow_decline=True, default="decline", automatic=True, prompt_context=meta):
        return None
    # The selection keeps its own identity: which check it was chosen for, under which
    # action and intent. Producers disagree about what a roll reason spells out, so the
    # receipt is matched against this rather than against a parsed reason string.
    ctx.engine._apply_condition(actor, EXPERT_PENDING, STEADY, actor.entity_id, expires_on="UNTIL_REMOVED",
        data={"source": ctx.source, "intent": intent_id, "skill": str(skill),
              "label": "Steady Hammer Breathing: Advantage selected for this check"})
    return "ADVANTAGE"


def smith_proficiency(engine, actor):
    """Explicit sealed tool rank, accepting the printed apostrophe spellings.

    Conflicting duplicate ranks are unknown rather than guessed from a total.
    """
    bundle = next((b for b in engine.typed_bundle_documents if b.get("actor_id") == actor.entity_id), {})
    ranks = {v for k, v in (bundle.get("skill_proficiency") or {}).items() if smiths_tools(k)}
    return next(iter(ranks)) if len(ranks) == 1 else None


def receipt_skill(payload, actor_id):
    """The skill a CHECK_ROLLED producer named for this side, or None.

    Producers disagree about what they name: an ordinary skill_check names its skill
    in the payload, while resolve_opposed_check names only the acting side's. A side
    that names none stays unknown here rather than being guessed out of the roll
    reason, which for opposed checks carries the action id instead of a skill.
    """
    for key in ("actor", "roll"):
        roll = payload.get(key)
        if isinstance(roll, dict) and str(roll.get("actor_id") or "") == str(actor_id):
            return payload.get("skill")
    return None


@hook("event")
def steady_check_rolled(engine, event_type, kwargs):
    """Spend the pending Advantage on the die that actually carried it.

    The selection is matched by its own recorded identity -- subject skill, source and
    intent -- plus the roll's own applied mode, both of which a check producer reports
    the same way whether the check was an ordinary skill_check or one side of an
    opposed check. The roll's reason is never parsed, so a producer that spells out a
    skill and one that spells out an action both settle correctly.
    """
    if event_type != "CHECK_ROLLED":
        return
    from .roll_context import check_receipts
    payload = kwargs.get("payload") or {}
    intent_id = str(getattr(engine._active_intent, "intent_id", ""))
    for actor_id, roll in check_receipts(kwargs):
        actor = engine.state.actors.get(actor_id)
        pending = held_condition(actor, EXPERT_PENDING) if actor else None
        if (pending is None or pending.data.get("source") != kwargs.get("source_definition_id")
                or pending.data.get("intent") != intent_id):
            continue
        named = receipt_skill(payload, actor_id)
        if not smiths_tools(str(pending.data.get("skill") or "")) or (named is not None and not smiths_tools(str(named))):
            continue
        # The use belongs to the completed check that received the selection. Advantage
        # and Disadvantage cancel to a NORMAL die, but that check still received the
        # selected benefit by canceling its Disadvantage. Mode queries without a roll
        # never emit this receipt and therefore still spend nothing.
        engine._remove_condition(actor, EXPERT_PENDING, STEADY)
        engine._apply_condition(actor, EXPERT_USED, STEADY, actor.entity_id, expires_on="UNTIL_REMOVED",
            data={"label": "Steady Hammer Breathing: Advantage used until the next short rest"})


@hook("turn_end")
def steady_unused_query(engine, actor):
    if held_condition(actor, EXPERT_PENDING):
        engine._remove_condition(actor, EXPERT_PENDING, STEADY)
