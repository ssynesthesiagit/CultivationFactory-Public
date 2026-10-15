"""Pure harm contract for recipient policy, Forge delivery, reactions and area risk.

True means harmful, False means beneficial/nonharmful, None means unclassified.
Plug-ins declare their leaf semantics with ext.effect(..., harmful=True/False).
Unknown leaves retain the caller's conservative fallback; classification never
chooses recipients. Containers use the same child traversal, including zones.
"""

CHILD_KEYS = ('effects', 'on_hit', 'on_miss', 'on_fail', 'on_success', 'triggers', 'inside')


def children(row):
    """Immediate typed payloads, including zone triggers/inside rows and branches."""
    for key in CHILD_KEYS:
        for child in row.get(key) or ():
            if isinstance(child, dict):
                yield child


def rows(effects):
    """Walk typed effects and trigger records without discarding containers."""
    for row in effects or ():
        if isinstance(row, dict):
            yield row
            yield from rows(children(row))


def classify_effect(row, *, saving_throw=False, recursive=True, ignore_self=False, numbers=None,
                    ability_mods=None, weapon=None):
    """Classify a payload; recursive=False classifies only its own operation.

    Save/zone containers defer to their children. An attack roll is itself an
    adverse operation, even when its riders are benefits or it deals no damage.
    Recipient consumers still enforce the enclosing scope before its children.
    Helpful stance and once-per-creature usage marks override apparent harm.
    Signed native modifiers use amount_bounds without rolling. An input the caller did not
    supply is bounded by what the rules fix about it (PB/CL nonnegative, unbounded above)
    or left open when its sign is the creature's own, so a penalty an offset can push across
    zero stays harmful and a benefit whose sign no input can cross does not. Attack modifiers
    are hostile when positive, AC/save/speed modifiers when negative. Native
    speed halving and set rows are hostile. ignore_self excludes activation
    costs at any depth for area membership.
    """
    kind = row.get('type')
    if ((ignore_self and row.get('applies_to') == 'self') or row.get('stance') == 'helpful' or
            (kind == 'mark' and row.get('once_per_creature'))):
        return False
    from . import ext
    declared = ext.effect_harm(kind)
    nested = list(children(row))
    if row.get('harmful') is not None:
        own = bool(row['harmful'])
    elif declared is not None:
        own = declared
    elif kind == 'attack':
        own = True
    elif kind == 'save':
        own = not nested
    elif kind == 'zone':
        # Opaque saving-throw outcomes retain the existing conservative risk;
        # outside a save, callers still choose the unknown enemy fallback.
        own = False if nested else (True if saving_throw else None)
    elif kind is None and (row.get('rule') or row.get('muffles')):
        # Continuous zone rows are operations too. Classify their rule semantics,
        # not their saved roster (an owner may widen hostile harm to everyone).
        # Helpful rows stay helpful, and unknown rule keys remain unclassified.
        rule = row.get('rule') or {}
        adverse = {'silenced', 'cant_hear', 'no_reactions', 'no_cp_regain',
                   'temp_hp_denied', 'healing_halved', 'healing_denied'}
        modes = [rule.get(key) for key in ('save_mode', 'check_mode', 'save_against', 'concentration_mode')]
        def disadvantage(value):
            return value == 'DISADVANTAGE' or (isinstance(value, dict) and
                                              any(disadvantage(v) for v in value.values()))
        own = True if (row.get('muffles') or any(rule.get(key) for key in adverse) or
                       any(map(disadvantage, modes)) or rule.get('attacked_with_if_sight') == 'ADVANTAGE') else None
        if own is None and rule.get('attacked_with_if_sight') == 'DISADVANTAGE':
            own = False  # Incoming Disadvantage protects the recipient.
    elif kind is None and nested:
        own = False
    elif kind in {'advantage', 'disadvantage'}:
        from .roll_mode_semantics import roll_mode_harmful
        own = roll_mode_harmful(row)
    elif kind in {'damage', 'extra_damage', 'condition', 'reaction_denied',
                  'forced_movement', 'healing_reduction', 'spend_resource',
                  'mark', 'vulnerability', 'deny_temp_hp', 'deny_invisible',
                  'deny_reactions_against', 'suppress_resistance', 'take_weapon', 'drop_item'}:
        own = True
    elif kind in {'speed', 'ac_bonus', 'attack_modifier', 'save_modifier'}:
        # These native rows encode magnitude differently from most typed effects:
        # speed uses `amount` (including halved/becomes), while AC can use amount
        # or flat. Keep that execution vocabulary in the shared harm contract.
        amount_row = ({**row, 'flat': row.get('amount')} if 'amount' in row else row)
        if kind == 'speed' and (row.get('halved') or row.get('becomes') is not None):
            own = True
        else:
            from .typed_amounts import amount_bounds
            low, high = amount_bounds(amount_row, numbers, ability_mods=ability_mods, weapon=weapon)
            # ``low``/``high`` are the ends of the range the row's own amount can take, not one
            # reading of it. ``None`` is an unbounded end: some input (an ability modifier, an
            # unknown formula) was not supplied and the rules fix no sign for it, so only the
            # conservative reading is available. An attack_modifier harms when it can *rise* above
            # zero; AC/save/speed harm when it can *fall* below it.
            own = (high is None or high > 0) if kind == 'attack_modifier' else (low is None or low < 0)
    elif kind == 'next_damage_taken_bonus':
        own = True
    elif kind in {'healing', 'temp_hp', 'gain_resource', 'remove_condition',
                  'resistance', 'immunity', 'half_damage'}:
        own = False
    else:
        own = True if saving_throw and not nested else None
    if not recursive or not nested:
        return own
    values = [classify_effect(child, saving_throw=saving_throw or kind == 'save', ignore_self=ignore_self,
                              numbers=numbers, ability_mods=ability_mods, weapon=weapon)
              for child in nested]
    if own is True or True in values:
        return True
    if own is None or None in values:
        return None
    return False
