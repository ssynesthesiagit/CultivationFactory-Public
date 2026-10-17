// Presentation only. Shared by table, sheet and map editor; no fight state writes.
import {RESOURCE_RULES} from "./newcomer-data.js?v=r25x2";
import {suppressNativeTooltip} from "./hovercard.js?v=tipdelay-1";

// Summaries of owner rules_text.json: source ids below are documentation, not
// dispatch keys. Variants retain their own printed effect/cost/target/duration.
export const GLOSSARY = [
  {terms: ["CP", "cultivation point", "cultivation points"], text: "CP means cultivation points, the energy spent on cultivation abilities. The paying pool is Stamina (Body Refining), Qi (Qi Cultivation), or Resonance (Spirit Awakening); an ability can specify a different cost."},
  {terms: ["Qi"], text: "Qi is the Qi Cultivation energy pool. Abilities spend it when their cost says so. Short rest: regain your cultivation level in Qi, once per long rest. Long rest: regain half your maximum. A 2-hour cultivation session restores all missing Qi, once per long rest, with a calm environment and sufficient spiritual energy or a suitable substitute."},
  {terms: ["Stamina"], text: "Stamina is the Body Refining energy pool, spent on abilities that list its cost. Short rest: regain half your maximum, rounded down, twice between long rests. Long rest: restore all missing Stamina. A 2-hour uninterrupted cultivation session restores all missing Stamina, once per long rest."},
  {terms: ["Resonance"], text: "Resonance is the Spirit Awakening energy pool, spent on abilities that list its cost. Short rest: regain your Spirit Awakening cultivation level, once per long rest. Long rest: regain half your maximum, rounded down. A 2-hour uninterrupted cultivation session restores all missing Resonance, once per long rest, in a safe spiritual environment with a suitable practice."},
  // RETRIBUTION_BASE_MARTIAL_FOCUS; TAL_BARRAGE_MARTIAL_FOCUS
  {terms: ["Martial Focus"], text: "Martial Focus is one available use of martial readiness. Some talents spend it; spending it is not an Action. You cannot spend it when absent or hold more than one. A talent's stated trigger can restore it when absent."},
  // EARTH_BASE_SPENDING_A_BURDEN_MARK; TAL_LIGHTNING_GATHER_CHARGE
  {terms: ["Mark", "Marks"], text: "A Mark is a named effect placed on a creature, object, or location. Each ability defines what its Mark does, how it is spent, and when it ends; different Marks do not share one effect."},
  // TAL_DARK_MELD; TAL_DARK_RAPID_MELD; TAL_DARK_PERSISTENT_MELD
  {terms: ["Meld", "Melds"], text: "A Meld takes one Action to grant a Dark-sphere talent you know to a creature you touch. It lasts up to 1 hour while you maintain Concentration; an unwilling creature can resist with a Wisdom save. Meld costs no CP. Persistent Meld costs 2 CP and removes Concentration for the rest of its duration. Each talent describes its benefit or harm."},
  // TAL_LIGHTNING_COURT_OF_CHARGED_PATHS and other printed Domain rules
  {terms: ["Court", "Courts", "Domain", "Domains"], text: "Courts and Domains are named cultivation effects, often an area around their creator. Their abilities specify the area, who benefits or suffers, cost and duration. A Court of Charged Paths changes Lightning Charge; it does not create Weather. Other Courts and Domains have their own rules."},
  // SMOKE_BASE_SMOKE_TRACE; SMOKE_BASE_SMOKE_RESPONSES
  {terms: ["Trace", "Traces", "Smoke Trace"], text: "A Trace is a named residue or tracking effect with ability-specific rules. A Smoke Trace can mark a creature, object or 5-foot space after a listed event in your Smoke Veil. You can hold up to your proficiency bonus; it lasts until the end of your next turn. Spending one enables a Smoke Response, normally once per round."},
  // TAL_LIGHTNING_GATHER_CHARGE
  {terms: ["Charge", "Charges", "Charged"], text: "Lightning Charge is a temporary effect placed by Gather Charge: Bonus Action, no CP, range 30 feet, until the start of your next turn. On your held weapon, spend it on a hit for extra lightning damage equal to your proficiency bonus. On yourself, it gives Advantage on the next qualifying Dexterity save. A charged space can damage its first entrant. Other abilities specify their own Charge rules."},
  // TAL_FATE_BORROWED_LIFESPAN_TALISMAN, TAL_FATE_CALAMITY_FINDS_A_PATH
  {terms: ["Heaven's Notice", "Heaven’s Notice", "Heavens Notice"], text: "Heaven's Notice is a counter increased by some Fate techniques. Those abilities specify the amount. The glossary has no general penalty or removal rule to display; if the table supplies no consequence, the GM resolves that part."},
  // TAL_BRUTE_ROOTED_STANCE; tianxia.subpath.body.kensei.feature.flowing_blade_stance
  {terms: ["Stance", "Stances"], text: "A Stance is a fighting posture whose ability lists its benefits and requirements. Some are always active while holding Martial Focus; others require a Bonus Action, a resource cost and a stated duration. Entering one does not grant the rules of a different Stance."},
  {terms: ["CL", "cultivation level"], text: "CL means cultivation level. An ability uses the level and Path specified in its rules to determine its strength."},
];

const escapeRE = text => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const patterns = GLOSSARY.map(row => new RegExp(`(?:^|[^\\p{L}\\p{N}_])(?:${row.terms.map(escapeRE).join("|")})(?=$|[^\\p{L}\\p{N}_])`, "iu"));
const counterPatterns = Object.keys(RESOURCE_RULES).filter(name => name.includes(" ") && !GLOSSARY.some(row => row.terms.includes(name)))
  .map(name => ({name, pattern: new RegExp(`(?:^|[^\\p{L}\\p{N}_])${escapeRE(name)}(?=$|[^\\p{L}\\p{N}_])`, "iu")}));

export function glossaryDefinitions(text, includeCounters = true) {
  const value = String(text || "");
  const definitions = GLOSSARY.filter((_, i) => patterns[i].test(value)).map(row => row.text);
  if (includeCounters) for (const {name, pattern} of counterPatterns) {
    if (!pattern.test(value)) continue;
    const rules = RESOURCE_RULES[name];
    definitions.push(`${name}: a named counter or effect, governed by its abilities.${rules.length
      ? " Printed examples apply only if you have the named ability:\n" + rules.map(rule => rule.text).join("\n\n")
      : " The table has no spending or recovery summary for it; ask the GM how it changes."}`);
  }
  return definitions;
}

export function glossaryText(text, includeCounters = true) {
  return glossaryDefinitions(text, includeCounters).join("\n\n");
}

export function resourceText(row, abilities = []) {
  const name = String(row.display_name || row.name || "Resource");
  const current = row.current ?? "unknown", maximum = row.maximum ?? "unknown";
  const norm = value => value.toLowerCase().replace(/[^\p{L}\p{N}]/gu, "");
  const genericCP = ["cp", "cultivationpoint", "cultivationpoints"].includes(norm(name));
  const key = Object.keys(RESOURCE_RULES).find(key => norm(key) === norm(name));
  const rules = RESOURCE_RULES[key] || [];
  const core = ["Qi", "Stamina", "Resonance"].includes(key);
  const owned = new Set(abilities.map(value => String(value.label || value.name || value).toLowerCase()));
  const matches = rules.filter(rule => owned.has(rule.name.toLowerCase()));
  const references = core ? rules : matches.length ? matches : rules.filter(rule => rule.name.toLowerCase() === name.toLowerCase());
  const help = glossaryText(name, false);
  const spending = abilities.filter(ability => String(ability.detail?.cost || "").split(",").some(cost => {
    const match = cost.trim().match(/^\d+\s+(.+)$/);
    return match && norm(match[1]) === norm(name);
  }))
    .map(ability => `${ability.label || ability.name}: ${ability.detail.cost}`);
  const examples = !references.length && !core ? rules : [];
  const details = [...references, ...examples].map(rule => `${rule.name}\n${rule.text}`).join("\n\n");
  const fallback = !details && !genericCP ? "The table reports this counter but has no matching spending or recovery summary. Ask the GM which of your abilities changes it; do not assume it recovers on a rest." : "";
  return [`${name}: ${current} current / ${maximum} maximum.`, help,
    core ? "Spend this pool when an ability lists its cost (CP means cultivation points). Printed rest recovery happens outside this fight; the table does not run rests or cultivation sessions."
      : genericCP ? "This label does not identify the paying Path pool. Ask the GM which of Qi, Stamina or Resonance pays before spending it; recovery depends on that Path."
      : "This counter changes only as its abilities specify. Use it for the abilities that name it. Rest and cultivation-session recovery happen outside this fight.",
    examples.length ? "Printed examples below apply only if you have the named ability. They do not grant it or make every part automatic." : "",
    spending.length ? `Your sheet's listed costs:\n${spending.join("\n")}` : "",
    details, fallback].filter(Boolean).join("\n\n");
}

// Native help is only for targets without an app hover card. When the pointer or
// keyboard reaches something naming a Tianxia term, its title (or SVG <title>)
// gains the plain definitions once, after the existing text. No popup of our own.
const TOOLTIP_LIMIT = 1000; // Chromium truncates native tooltips near 1024 characters.
const GLOSSARY_BINDING = Symbol.for("tianxia.glossary.binding");

export function installGlossary(doc = document) {
  if (doc[GLOSSARY_BINDING]) return doc[GLOSSARY_BINDING];
  const enriched = new WeakMap(); // element -> the title text we last wrote
  function enrich(event) {
    const node = event.target;
    if (!node?.closest) return;
    const card = node.closest("[data-tip],[data-hover-card],.tt-hovercard");
    if (card) {
      // Descendant labels can otherwise grow their own delayed native popup.
      for (let target = node; target; target = target.parentElement) {
        target.removeAttribute?.("title");
        if (target === card) break;
      }
      suppressNativeTooltip(card);
      return;
    }
    const anchor = node.closest("[title],button,label,[role=button],a") || node.closest("g:has(>title)");
    const target = anchor || node;
    if (target === doc.body || target === doc.documentElement) return;
    const svgTitle = target.hasAttribute("title") ? null : target.querySelector?.(":scope > title");
    const current = svgTitle ? svgTitle.textContent : target.getAttribute("title") || "";
    if (enriched.get(target) === current) return; // done, and not re-rendered since
    enriched.set(target, current);
    // Only a control or a bare text label: a title on a container shows on every control inside it (owner 2026-09-30:
    // a prompt's "2 Stamina" put the Stamina definition on each option button). SVG shapes only show a <title> child.
    if ((!anchor && !current && (target.children.length || target.textContent.length > 80))
        || (!svgTitle && target.namespaceURI === "http://www.w3.org/2000/svg")) return;
    const counters = !current.includes("current /") && !current.includes("This counter changes only");
    let text = current;
    // A dropdown's text is every option in it: read only the chosen option (owner 2026-09-30: the fighter picker showed
    // Resonance's definition because one listed fighter was a Spirit Awakener).
    let shown = target.textContent;
    const select = target.closest?.("select");
    if (select) shown = select.selectedOptions?.[0]?.textContent || "";
    else for (const inner of target.querySelectorAll?.("select") || []) {
      shown = shown.replace(inner.textContent, inner.selectedOptions?.[0]?.textContent || "");
    }
    for (const help of glossaryDefinitions(`${shown}\n${current}\n${target.getAttribute("aria-label") || ""}`, counters)) {
      if (current.includes(help) || text.length + help.length + 2 > TOOLTIP_LIMIT) continue;
      text = text ? `${text}\n\n${help}` : help;
    }
    if (text === current) return;
    if (svgTitle) svgTitle.textContent = text;
    else target.setAttribute("title", text);
    enriched.set(target, text);
  }
  doc.addEventListener("pointerover", enrich);
  doc.addEventListener("focusin", enrich);
  return doc[GLOSSARY_BINDING] = {enrich};
}
