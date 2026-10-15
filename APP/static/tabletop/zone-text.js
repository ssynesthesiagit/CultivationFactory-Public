// General zone effect text from compiled values, shared by all zone abilities.
// No ability-id dispatch and no rules execution. Missing values are described
// as missing rather than replaced with invented damage, distance or deadlines.
import {MARK_DURATIONS, CONDITION_READINGS as CONDITIONS, GM_RESOLVES} from "./zone-text-data.js?v=r25x2";

const ABILITIES = {STR: "Strength", DEX: "Dexterity", CON: "Constitution", INT: "Intelligence", WIS: "Wisdom", CHA: "Charisma"};
export function saveName(value) {
  const key = String(value || "").toUpperCase();
  if (ABILITIES[key]) return ABILITIES[key];
  const choices = key.split("_OR_");
  return choices.length > 1 && choices.every(choice => ABILITIES[choice])
    ? `${choices.map(choice => ABILITIES[choice]).join(" or ")} (target chooses)` : "Ability not shown";
}

// What each condition does, in the plain words the sheet's own condition hover uses
// (combat/condition_text.py READING plus the engine mechanics it reads from
// combat/rules/typed_conditions.json, served to the sheet by /api/tabletop/conditions).
// The area reader needs its answer synchronously, so it cannot fetch that API: its copy is
// generated from the same two sources by tools/newcomer_text_data.py build_condition_readings()
// (combat.condition_text.zone_readings) and shipped in zone-text-data.js. Re-exported under the old
// name for the coverage guard in tests/test_zone_condition_text.py. A second hand-written dictionary
// here is what let the two surfaces disagree about Stunned and Muffle; do not add one back.
export {CONDITIONS, GM_RESOLVES};

// The area reader's answer for one condition effect: the plain reading, never the internal key.
export function conditionText(row) {
  const key = String(row?.condition ?? "").split(".").pop();
  return CONDITIONS[key] || GM_RESOLVES;
}

// A reading that is about to be continued ("... on a failure") gives up its closing full stop.
const clause = text => String(text || "").replace(/[.;,]\s*$/, "");

export function durationText(duration) {
  const kind = typeof duration === "string" ? duration : duration?.kind;
  const text = {until_start_of_next_turn: "until the start of its creator's next turn",
    until_start_of_your_next_turn: "until the start of its creator's next turn",
    until_end_of_your_next_turn: "until the end of its creator's next turn",
    until_end_of_next_turn: "until the end of the affected creature's next turn",
    target_next_turn: "until the end of the affected creature's next turn",
    until_end_of_turn: "until the end of the current turn", instant: "", this_attack: "for the triggering attack",
    until_removed: "until removed by the ability's stated rules",
    special: "deadline not shown here; ask the GM when it ends",
    concentration: "while its creator concentrates"}[kind];
  if (text !== undefined) return text;
  if (["rounds", "minutes", "hours", "days"].includes(kind) && Number.isInteger(duration?.amount) && duration.amount > 0) {
    return `for ${duration.amount} ${duration.amount === 1 ? kind.slice(0, -1) : kind}${duration.concentration ? ", while its creator concentrates" : ""}`;
  }
  return "deadline not shown here; ask the GM when it ends";
}

export function effectText(effects, numbers = {}) {
  const out = [];
  const cl = Number(numbers.cl);
  const amount = row => {
    const byCl = Number.isFinite(cl) && (row.dice_by_cl || []).find(([low, high]) => cl >= low && cl <= high);
    const dice = byCl ? {count: byCl[2], sides: byCl[3]} : row.dice;
    const formulaName = {pb: "proficiency bonus", cl: "cultivation level", key_mod: "cultivation ability modifier",
      key_ability_modifier: "cultivation ability modifier"}[row.formula];
    const formula = row.formula && row.formula !== "none" ? (numbers[row.formula]
      ?? (row.formula === "key_ability_modifier" ? numbers.key_mod : undefined) ?? formulaName ?? "amount not shown by the table") : null;
    return [dice?.count ? `${dice.count}d${dice.sides}` : null, formula != null ? String(formula) : null,
      row.flat != null ? String(row.flat) : null].filter(part => part !== null).join(" + ") || "an amount not shown by the table";
  };
  for (const row of effects || []) {
    if (!row || typeof row !== "object") continue;
    const kind = row.type;
    if (kind === "save") {
      const fail = clause(effectText(row.on_fail, numbers)), success = clause(effectText(row.on_success, numbers));
      out.push(`${saveName(row.ability)} save${numbers.save_dc ? ` DC ${numbers.save_dc}` : ""}: ${fail || "no effect"} on a failure${success ? `; ${success} on a success` : ""}`);
    } else if (kind === "damage" || kind === "extra_damage") {
      if (row.applies_to === "self") continue;
      out.push(`${amount(row)} ${(row.damage_types || []).join(" or ")} damage`.replace(/\s+/g, " "));
    } else if (kind === "half_damage") out.push("half damage");
    else if (kind === "mark") {
      const name = String(row.display_name || row.mark || "unnamed Mark").replace(/_/g, " ");
      // block_mark uses these compiled defaults for until_removed marks.
      const duration = row.duration?.kind === "until_removed" && MARK_DURATIONS[name.toLowerCase()] || row.duration;
      const safeName = /[:/]/.test(name) ? "the ability's named Mark" : `the “${name}” Mark`;
      out.push(`gain ${safeName} (${durationText(duration)}). A Mark is a named effect; its ability determines its benefit or harm`);
    } else if (kind === "condition") out.push(conditionText(row));
    else if (kind === "forced_movement") {
      const direction = ["toward", "toward_center"].includes(row.direction) ? "pulled" : "pushed";
      const destination = row.direction === "toward_center" ? " toward the area's center" : row.direction === "away_center" ? " away from the area's center"
        : row.direction === "toward" ? " toward its creator" : " away from its creator";
      out.push(`${direction} ${row.distance_ft ?? row.flat ?? "a distance not shown by the table"}${row.distance_ft != null || row.flat != null ? " feet" : ""}${destination}`);
    } else if (kind === "speed") out.push(`Speed ${Number(row.flat) > 0 ? "+" : ""}${row.flat ?? "change not shown"} feet${row.duration ? ` (${durationText(row.duration)})` : ""}`);
    else if (kind === "temp_hp") out.push(`gain ${amount(row)} temporary hit points`);
    else if (kind === "healing") out.push(`regain ${amount(row)} hit points`);
    else if (kind === "resistance") out.push(`Resistance to ${(row.damage_types || []).join(" or ")} damage`);
    else if (kind === "advantage" || kind === "disadvantage") out.push(`${kind === "advantage" ? "Advantage" : "Disadvantage"} ${String(row.on || "").replace(/_/g, " ")}`.trim());
    else if (kind && !["zone", "spend_resource", "gain_resource", "movement", "teleport"].includes(kind)) {
      const reading = row.reading || row.description || row.evidence;
      out.push(typeof reading === "string" && !/typed\.|combat\/|gate[234]|owner 20|Factory/i.test(reading)
        ? reading : "The Game Master resolves this additional effect.");
    }
  }
  // A condition reading opens with "It" or "Its". After a comma it continues a list someone already
  // started, so it continues in lower case; after a full stop or a colon it starts a sentence of
  // its own, and keeps the capital.
  return out.reduce((soFar, part) => {
    if (!soFar) return part;
    if (/[.!?]$/.test(soFar)) return `${soFar} ${part}`;
    if (soFar.endsWith(", ") || soFar.endsWith(": ") || soFar.endsWith("; ")) {
      const next = /^(It|Its)\b/.test(part) && !soFar.endsWith(": ") ? part[0].toLowerCase() + part.slice(1) : part;
      return soFar.endsWith(": ") || soFar.endsWith("; ") ? `${soFar}${next}` : `${soFar}, ${next}`;
    }
    return `${soFar}, ${/^(It|Its)\b/.test(part) ? part[0].toLowerCase() + part.slice(1) : part}`;
  }, "");
}
