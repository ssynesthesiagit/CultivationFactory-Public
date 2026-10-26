// Which creatures' eyes the table shows you (owner 2026-10-04, live round 25: "I want the
// default vision mode to not share vision with your allies, but keep that as an option as
// allies view").
//
// The engine decides what each creature perceives (TabletopService.state's fog_perception,
// built from combat/senses.perception); nothing here decides a rule, a square or a token.
// This module only answers one question -- whose perception is the table showing -- so the
// drawn fog (tabletop.js visibility / fogGeometry), the hidden tokens (viewerIds) and the Fog
// picker cannot drift apart.  Which creatures the player owns is the page's call (tabletop.js
// isOwnedActor: this tab's explicitly bound, eligible fighters and summons), and `fogViewers` turns that ownership
// plus a chosen view into the tokens to look through.  Shared by those callers and by
// tests/fog_view.test.mjs.

export const FOG_VIEWS = [
  {
    value: "own",
    label: "My character's view",
    help: "You see only through the fighters chosen in My fighters and their summoned creatures while you play them manually. "
      + "Squares you have already looked at stay dimly visible as memory; what only an ally can see stays hidden. "
      + "While all of your fighters are down, you look through your allies' eyes.",
  },
  {
    value: "team",
    label: "Allies' view (shared)",
    help: "You see everything your whole side can see: your fighter's sight and your allies' sight combined, "
      + "so the map opens up wherever an ally is looking.",
  },
  {
    value: "selected",
    label: "Chosen tokens",
    help: "You see only through tokens you choose. Pick a fighter in the Fighters list or on the map, "
      + "or Shift-click to add more. This does not change My fighters or which roofs open for you.",
  },
  {
    value: "off",
    label: "Off (Game Master view)",
    help: "No fog of war: you see the whole map, including what foes are doing out of sight. Use this to run the fight as the Game Master.",
  },
];

export const DEFAULT_FOG_VIEW = "own";
export const NO_FOG_VIEW = "off";

const BY_VALUE = new Map(FOG_VIEWS.map(view => [view.value, view]));
const teamOf = actor => Number(actor?.team_index ?? 0);
const sidesOf = rows => new Set(rows.map(teamOf));

// The view a stored choice names, or null when it is missing or from another version.
export function fogView(value) {
  return BY_VALUE.get(value) || null;
}

// Whether this view hides anything at all. The Game Master's view shows every square.
export function fogOn(value) {
  return value !== NO_FOG_VIEW;
}

// The creatures whose perception a view shows. `owned` is the fight's rows the player owns (the
// page's own ownership test, which includes their summons and can include several fighters),
// `selected` the token ids picked on the map, and `team` the side index "Allies' view" shares. The
// Game Master's view has no viewers: it shows everything. Returns [] for an unknown value, which the
// player caller reads as fully fogged. Only an explicit Game Master role lifts fog.
//
// "own" whose owned fighters are all down (defeated, or a fight that has only just been created)
// falls back to the sides those fighters fight on rather than lifting the fog: a player whose
// character has fallen must not start seeing what the enemy is doing out of sight. The side is read
// off the fighters themselves, so it follows ownership instead of assuming the first side, and it is
// never the enemy's. A fight with nothing of yours in it has no viewer at all and
// stays fully fogged. The page validates identity before calling this helper.
export function fogViewers(value, actors, {owned = [], selected, team = 0} = {}) {
  if (!fogOn(value)) return [];
  const rows = (actors || []).filter(Boolean);
  const onMap = rows.filter(actor => actor.active !== false);
  if (value === "own") {
    const here = new Set(rows.map(actor => actor.entity_id));
    const mine = (owned || []).filter(actor => actor && here.has(actor.entity_id));
    const standing = mine.filter(actor => actor.active !== false);
    if (standing.length) return standing;
    return mine.length ? onMap.filter(actor => sidesOf(mine).has(teamOf(actor))) : [];
  }
  if (value === "team") return onMap.filter(actor => teamOf(actor) === Number(team ?? 0));
  if (value === "selected") return onMap.filter(actor => Boolean(selected && selected.has(actor.entity_id)));
  return [];
}
