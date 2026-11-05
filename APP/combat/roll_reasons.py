"""Display-only d20 provenance shared by resolution, targeting and table views.

Receipts live in the current engine d20 frame, so nested reactions cannot borrow
the outer roll's reasons. Readers never resolve, consume or alter a roll mode.
"""

MODES = {'ADVANTAGE', 'DISADVANTAGE'}
ABILITIES = dict(STR='Strength', DEX='Dexterity', CON='Constitution', INT='Intelligence', WIS='Wisdom', CHA='Charisma', ALL='all')


def unique_sources(rows):
    """Stable receipt order across processes, including set-based contributions."""
    unique = []
    for row in rows:
        if row not in unique:
            unique.append(row)
    return sorted(unique, key=lambda row: (row['kind'], row['effect'], row['owner'], row['why']))


class ExplainedMode(str):
    """Ordinary mode value with transient receipts for auxiliary direct d20s."""
    def __new__(cls, mode, rows):
        value = super().__new__(cls, mode)
        value.mode_sources = unique_sources(rows)
        return value

    def __reduce__(self):
        return type(self), (str(self), self.mode_sources)


def owner_name(owner):
    """Display name for a receipt owner: a string, an actor (display_name or name), or str()."""
    if owner is None or isinstance(owner, str):
        return owner or ''
    return getattr(owner, 'display_name', None) or getattr(owner, 'name', None) or str(owner)


def source(engine, mode, *, effect='Active effect', owner=None, why=''):
    if mode not in MODES:
        return None
    return {'effect': effect, 'owner': owner_name(owner),
            'kind': mode.lower(), 'why': why or 'applies to this roll'}


def remember(engine, rows):
    frames = getattr(engine, '_d20_scopes', ())
    if frames:
        receipts = frames[-1].setdefault('mode_sources', [])
        for row in rows:
            if row and row not in receipts:
                receipts.append(row)


def remember_reaction(engine, reactor_id, reaction_id, target):
    """Receipts for an accepted Reaction's roll effect, supplied by plug-ins (ext hook reaction_roll_reasons).

    Core only records that the Reaction was accepted; the owning plug-in names the
    effect, owner and reason. Rows go into the current d20 frame like remember().
    """
    from . import ext
    rows = [row for reply in ext.run_strict('reaction_roll_reasons', engine, reactor_id, reaction_id, target)
            for row in reply]
    remember(engine, rows)


def later_source(engine, row):
    """One receipt for a composition-step contribution, or None when inert.

    Declaration checkpoints and accepted Reactions add roll modes after the
    masked attack-mode query ran; each contribution must also be recorded so a
    later cancelling answer explains the final mode (review 2026-10-16
    finding 2). A dict row naming itself with effect and why keeps that
    attribution; a bare ``{'mode': ...}`` row stays visible with a plain,
    newcomer-readable choice label instead of silently disappearing.
    """
    mode = row.get('mode') if isinstance(row, dict) else None
    if mode not in MODES:
        return None
    if isinstance(row.get('effect'), str) and isinstance(row.get('why'), str):
        return source(engine, mode, effect=row['effect'], owner=row.get('owner'), why=row['why'])
    return source(engine, mode, effect='Choice before the roll',
                  why='an answer chosen after the action was declared applies to this roll')


def effect_name(engine, source_id, fallback='Active effect'):
    action = engine.action_catalog.get(source_id)
    return getattr(action, 'display_name', None) or fallback


def condition_source(engine, actor, row, mode, why, *, condition=None):
    if mode not in MODES:
        return None
    from .typed_executor import condition_rule_instances
    candidates = [(condition, row)] if condition is not None else condition_rule_instances(actor, engine=engine)
    for instance, rule in candidates:
        if all(rule.get(k) == v for k, v in row.items() if not k.startswith('_')):
            label = instance.condition_id.rsplit('.', 1)[-1].replace('_', ' ').capitalize()
            for code, name in ABILITIES.items():
                why = why.replace(code, name)
            return source(engine, mode, effect=effect_name(engine, instance.source_definition_id, label),
                          owner=engine.state.actors.get(instance.source_actor_id), why=why)
    return source(engine, mode, why=why)


def text(mode, rows):
    if not rows:
        return '' if mode == 'NORMAL' else f'with {mode.capitalize()}'
    groups = {kind: [f"{r['effect']}{' (' + r['owner'] + ')' if r.get('owner') else ''}: {r['why']}"
                     for r in rows if r['kind'] == kind] for kind in ('advantage', 'disadvantage')}
    if mode == 'NORMAL' and all(groups.values()):
        return ('normal roll: Advantage from ' + '; '.join(groups['advantage'])
                + ' cancels Disadvantage from ' + '; '.join(groups['disadvantage']))
    return f"with {mode.capitalize()} (" + '; '.join(groups['advantage'] + groups['disadvantage']) + ')'


def attach(engine, roll):
    context = engine.d20_context(roll)
    rows = list((context or {}).get('mode_sources', ()))
    # Legacy action-specific contributions must stay visible without guessing
    # which ability supplied an otherwise unattributed mode.
    if roll.mode in MODES and not any(r['kind'] == roll.mode.lower() for r in rows):
        rows.append(source(engine, roll.mode, effect='Roll-specific effect', why='applies to this roll'))
    return roll.model_copy(update={'mode_sources': unique_sources(rows)}) if rows else roll


def standing(engine, actor):
    from .ext.standard_conditions import roll_rules
    rows = []
    fields = {'attacks_have': 'Your attacks', 'melee_attacks_have': 'Your melee attacks',
              'attacks_others_have': 'Your attacks against creatures other than your grappler',
              'attacked_with': 'Attacks against you', 'attacked_with_if_attacker_visible': 'Attacks against you when you see the attacker',
              'attacked_within_5ft': 'Attacks against you from within 5 feet',
              'attacked_beyond_5ft': 'Attacks against you from beyond 5 feet'}
    for condition, rule in roll_rules(engine, actor, with_sources=True):
        for key, scope in fields.items():
            if rule.get(key) in MODES:
                rows.append(scope + ': ' + text(rule[key], [condition_source(engine, actor, rule, rule[key], 'while this effect lasts', condition=condition)]))
        for field, scope in (('save_mode', 'saving throws'), ('check_mode', 'checks')):
            for ability, mode in (rule.get(field) or {}).items():
                if mode in MODES:
                    rows.append(f'Your {ABILITIES.get(ability, ability)} {scope}: ' + text(mode, [condition_source(engine, actor, rule, mode, 'while this effect lasts', condition=condition)]))
        if rule.get('concentration_mode') in MODES:
            mode = rule['concentration_mode']
            rows.append('Your saving throws to maintain Concentration: ' + text(mode,
                [condition_source(engine, actor, rule, mode, 'while this effect lasts', condition=condition)]))
    from .concentration import MODE
    for condition in actor.conditions.values():
        rule = (condition.data or {}).get('rule') or {}
        if condition.condition_id == MODE and rule.get('concentration_mode') in MODES:
            mode = rule['concentration_mode']
            rows.append('Your ' + ('next ' if rule.get('next') else '') + 'saving throw to maintain Concentration: '
                        + text(mode, [source(engine, mode, effect=effect_name(engine, condition.source_definition_id),
                                            why='while this effect lasts')]))
    from . import ext
    for reply in ext.run_strict('standing_roll_reasons', engine, actor):
        rows.extend(reply)
    for modifier in actor.modifiers.values():
        if not modifier.consumed and modifier.target_field in ('attack_mode', 'incoming_attack_mode', 'attack_mode_vs'):
            mode, _, target_id = str(modifier.value).partition(':')
            if mode in MODES:
                scope = 'Attacks against you' if modifier.target_field == 'incoming_attack_mode' else 'Your attacks'
                why = 'while this effect lasts'
                if modifier.target_field == 'attack_mode_vs':
                    # Resolution keeps this modifier restricted to its named
                    # target (engine _attack_mode matches the suffix), so the
                    # standing text must say the same thing instead of reading
                    # as a benefit on every attack (review 2026-10-16 finding 4).
                    target = engine.state.actors.get(target_id) if engine is not None else None
                    name = getattr(target, 'display_name', '') or ''
                    scope = (f'Your attacks against {name} only' if name
                             else 'Your attacks against the chosen creature only')
                    why = 'only while attacking this creature; while this effect lasts'
                rows.append(scope + ': ' + text(mode, [source(engine, mode,
                    effect=effect_name(engine, modifier.source_definition_id), why=why)]))
    return list(dict.fromkeys(rows))


def attack_preview(engine, actor, target, action):
    """Current automatic sources only; reactions and later choices can change it."""
    from .attack_delivery import is_ranged
    parameters = action.parameters or {}
    typed = parameters.get('typed') or {}
    attack = next((e for e in typed.get('effects', ()) if e.get('type') == 'attack'), None)
    profile = parameters.get('attack_kind') or parameters.get('attack_profile')
    if not attack and not profile and getattr(action, 'attack_bonus', None) is None:
        return None
    profile = (attack or {}).get('attack_kind') or profile
    ranged = is_ranged(profile, typed.get('range_ft', getattr(action, 'range_ft', None)), typed.get('weapon'))
    rows = []
    from . import attack_modes
    from .ext.ability_source import combine_modes
    removed = attack_modes.removed(engine, actor, target, ranged)
    modes = set()
    engine._attack_mode(actor, target, ranged=ranged, reasons=rows, contributions=modes,
                        removed=removed, chosen_modes=attack_modes.chosen(engine, action.source_definition_id, attack))
    if typed:
        from .typed_executor import Context, ranged_attack_crowded
        from .shot_geometry import attack_distance
        ctx = Context(engine, actor, action, None, typed, [target], target, {})
        beyond = typed.get('long_range_ft') and attack_distance(engine, actor, target) > int(typed.get('range_ft') or 0)
        if beyond and 'DISADVANTAGE:long_range' not in removed:
            modes.add('DISADVANTAGE')
            rows.append(source(engine, 'DISADVANTAGE', effect='Long range', why='target is beyond the weapon’s normal range'))
        if typed.get('disadvantage') or ranged_attack_crowded(ctx):
            modes.add('DISADVANTAGE')
            rows.append(source(engine, 'DISADVANTAGE', effect=action.display_name,
                               why='the action imposes Disadvantage' if typed.get('disadvantage')
                               else 'a nearby hostile creature can see the attacker'))
    mode = combine_modes(modes)
    return {'mode': mode, 'mode_sources': rows,
            'text': (text(mode, rows) or 'Normal roll: no Advantage or Disadvantage')
                    + '. Action-specific effects, reactions and choices may change this.'}
