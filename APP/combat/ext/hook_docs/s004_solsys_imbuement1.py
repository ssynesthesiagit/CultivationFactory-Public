"""Equipment and save property systems (SOLSYS-IMBUEMENT1):
  attack_materials(engine, source_actor_id, typed) -> list[str] | None is a
  strict pure packet query. Materials supplement typed.materials; defense rows
  may declare bypass_materials (canonical strings). An intersection bypasses
  only that row, whether Resistance or Immunity, never unrelated defenses.
  Default-inert with no matching packet/condition; no guessed weapon identity.
  combat.equipment_properties.packet_weapon and enhancement_delta are shared
  by Imbuement's attack/AC hooks and damage-defense consumers. magic_channels
  selects attack/damage/ac; magic_bonus uses the greater compiled/granted
  value; suppress_magic removes that numeric bonus without deleting other
  properties. Factory bundles seal equipment_magic per body/shield slot.
  Imbuement's existing mandate_vessel effect can explicitly opt into natural,
  unarmed and improvised attack Vessels via attack_vessels=true. Existing
  weapon-only rows retain their restrictions. Armor magic rows choose one
  body/shield slot; loss of a shield removes its live AC benefit.
  save_proficiency is a generic effect handled by save_bonus_status's existing
  save(ctx, subject, ability, named) and native save_bonus hooks. abilities is
  a canonical ability list; already_proficient is an integer bonus (default 0).
  Proficiency adds the recipient's own PB once, never the caster's. Identical
  grants do not stack. New bundles seal explicit save_proficiencies; absent
  declarations are not inferred from totals. combat.save_proficiencies shares
  live proficiency queries with Lightning Grounding. All temporary state is
  stored through ordinary source-owned conditions and normal expiry/replay."""
