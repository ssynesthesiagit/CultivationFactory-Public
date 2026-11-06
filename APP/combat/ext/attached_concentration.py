"""Attached attack damage: one Concentration save per hit, after every packet (combat/attached_concentration.py)."""

from . import hook


@hook('attack_damage_final')
def attached_concentration_save(engine, attacker, target, attack_context, intent) -> None:
    from ..attached_concentration import resolve
    resolve(engine, target, attack_context)
