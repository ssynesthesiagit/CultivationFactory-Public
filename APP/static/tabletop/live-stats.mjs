/** Prefer the table's current engine values when the sheet is connected. */
export function liveStats(actor, summary) {
  return {
    armorClass: actor?.armor_class ?? summary?.armor_class ?? null,
    speedFt: actor?.speed_ft ?? summary?.speed_ft ?? null,
  };
}
