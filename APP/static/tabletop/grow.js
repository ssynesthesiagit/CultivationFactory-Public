// The sheet's Grow tab (owner 2026-09-27): "the character sheets be updated with new spheres etc so when the player is
// playing theres a way to interact with the sheets", and "composite techniques ... created and added" (PHB ch. 18
// Forged Techniques). Rules-checked, with a GM override; the server decides legality (combat/table_advance.py) and
// builds each technique (character_creation/constructed_arts/forged_technique.py). Additions apply to new fights.

let deps = null;          // {h, $, fetchJson, toast, reloadSheet, projectId}
let data = null;          // GET /advancement
let query = { sphere: "", talent: "", legalOnly: true };
let forge = { name: "", base_form: "", primary_talent_id: "", secondary_talent_ids: [], augment_ids: [], drawback_ids: [], choices: {} };
let preview = null;       // POST /forge result or {error}
let busy = false;
let learning = {};
let learningSource = "campaign";
let levelDraft = {target: null, rows: {}, filters: {}, addPath: {path_id: "", access: "", source_id: "", confirmed: false}};
let insightDraft = { query: "", note: "From play", choice: "" };
let artDraft = { name: "", source_record_id: "", aspect_id: "", factor_ids: [], burdens: [] };
let artProof = { die: 1, research_hours: 0, materials_gp: 0 };
let artNote = "From play";
// The CL15 realm feature whose printed use closes the window to replace a first Golden Core Form.
let artPreview = null;

export function initGrow(options) {
  deps = options;
  const root = deps.$("grow-root");
  root.addEventListener("click", onClick);
  root.addEventListener("change", onChange);
  root.addEventListener("input", onInput);
}

export async function loadGrow() {
  const { $, fetchJson, h } = deps;
  try {
    data = await fetchJson(`/api/tabletop/characters/${encodeURIComponent(deps.projectId())}/advancement`);
    methodPreview=null;methodDraft={method_id:"",source:"",note:"",opportunity:"",completed:false};
    render();
  } catch (error) {
    $("grow-root").replaceChildren(h("p", { class: "muted" }, `Could not load what this character can learn: ${error.message}`));
  }
}

function gm() { return Boolean(deps.$("grow-gm")?.checked); }

async function post(path, body) {
  const session = await deps.fetchJson("/api/session");
  return deps.fetchJson(`/api/tabletop/characters/${encodeURIComponent(deps.projectId())}/${path}`, {
    method: "POST", headers: { "Content-Type": "application/json", "X-Foundry-Token": session.token }, body: JSON.stringify(body),
  });
}

function why(row) {
  if (row.legal) return null;
  return (row.reasons || []).join("; ") || "not legal now";
}

function learnButton(kind, row) {
  const { h } = deps;
  const allowed = row.legal || gm();
  return h("button", { type: "button", class: `btn ${row.legal ? "btn-accent" : ""}`, disabled: !allowed || busy || null,
                       dataset: { growAdd: kind, id: row.id },
                       title: row.legal ? "Learn it" : gm() ? "Add it anyway as a GM grant" : "Turn on the GM override to add it anyway" },
           row.legal ? "Learn" : "GM add");
}


// Ability scores (combat/table_advance.py): a GM respec sets all six scores under point-buy; a level increase adds
// bounded deltas at CL 4+. The server decides legality; this panel previews the modifiers the change would give.
let abilityDraft = { mode: "level_increase", values: {} };
const ABILITY_ORDER = ["STR", "DEX", "CON", "INT", "WIS", "CHA"];
const ABILITY_NAMES = { STR: "Strength", DEX: "Dexterity", CON: "Constitution", INT: "Intelligence", WIS: "Wisdom", CHA: "Charisma" };
const modOf = (score) => Math.floor((score - 10) / 2);
const signed = (n) => (n >= 0 ? `+${n}` : `${n}`);

function abilityDefaults() {
  const panel = data.ability_panel || {};
  if (abilityDraft.mode === "gm_respec") return { ...(panel.default_spread || {}) };
  return Object.fromEntries(ABILITY_ORDER.map((a) => [a, 0]));
}

function abilityPreview() {
  const panel = data.ability_panel || {};
  const current = panel.scores || {};
  const values = { ...abilityDefaults(), ...abilityDraft.values };
  if (abilityDraft.mode === "gm_respec") {
    // Only the server's authority may price a score; missing costs fail closed.
    const costs = panel.point_buy_cost || {};
    const spent = ABILITY_ORDER.reduce((s, a) => s + (costs[values[a]] ?? 0), 0);
    const cap = (panel.level_increase || {}).cap || 20;
    const rows = ABILITY_ORDER.map((a) => ({ a, from: current[a], base: values[a],
      bonus: (panel.respec_bonuses || {})[a] || 0,
      to: values[a] + ((panel.respec_bonuses || {})[a] || 0) }));
    const baseLegal = ABILITY_ORDER.every((a) => costs[values[a]] !== undefined) && spent === (panel.point_buy_budget || 27);
    const finalLegal = rows.every((r) => r.to >= 1 && r.to <= cap);
    return { legal: baseLegal && finalLegal, spent, rows,
      note: !baseLegal ? `Point-buy must be 8–15 and spend exactly ${panel.point_buy_budget || 27} points (now ${spent}).`
        : !finalLegal ? `Final scores, including earned increases, must be between 1 and ${cap}. A higher score requires the GM override.`
        : `Point-buy legal: ${panel.point_buy_budget} points. Earned Background and level increases are retained in the final scores.` };
  }
  const spent = ABILITY_ORDER.reduce((s, a) => s + (Number(values[a]) || 0), 0);
  const budget = (panel.level_increase || {}).budget || 2;
  const rule = panel.level_increase || {};
  const legal = (rule.cl || []).includes(data.cl) && !(rule.recorded_cls || []).includes(data.cl) &&
    spent === budget && ABILITY_ORDER.every((a) => {
      const increase = Number(values[a]) || 0;
      return (increase === 0 || (rule.deltas || []).includes(increase)) &&
        (current[a] ?? 0) + increase <= (rule.cap || 20);
    });
  return { legal, spent, rows: ABILITY_ORDER.map((a) => ({ a, from: current[a], to: (current[a] ?? 0) + (Number(values[a]) || 0) })),
    note: legal ? "Level increase legal: 2 points, +1 or +2 each." : `A level increase needs an unused opportunity at cultivation level ${(rule.cl || []).join(", ")}, exactly ${budget} points, and scores no higher than ${rule.cap || 20} (now ${spent} points).` };
}

function abilityBlock() {
  const { h } = deps;
  const panel = data.ability_panel || {};
  const isRespec = abilityDraft.mode === "gm_respec";
  const values = { ...abilityDefaults(), ...abilityDraft.values };
  const pv = abilityPreview();
  const rows = (data.added && data.added.abilities) || [];
  return h("details", { class: "def-block def-details", id: "grow-abilities", open: true },
    h("summary", null, h("span", { class: "def-label" }, `Ability scores (${rows.length} change${rows.length === 1 ? "" : "s"})`)),
    h("div", { class: "powering-row" },
      h("label", null, h("input", { type: "radio", name: "grow-ability-mode", value: "level_increase", id: "grow-ability-mode-level", checked: !isRespec || null, dataset: { growAbilityMode: "level_increase" } }), " Level increase (cultivation level ", (panel.level_increase || {}).cl?.join(", ") || "4", ")"),
      h("label", null, h("input", { type: "radio", name: "grow-ability-mode", value: "gm_respec", id: "grow-ability-mode-respec", checked: isRespec || null, dataset: { growAbilityMode: "gm_respec" } }), " GM score reset (set six base scores; spend exactly 27 points)"),
      isRespec ? h("button", { type: "button", class: "btn", disabled: busy || null, dataset: { growAbilitySpread: "1" } }, "Optimized starting scores") : null),
    h("div", { class: "grow-list" }, ...ABILITY_ORDER.map((a) => h("div", { class: "grow-row" },
      h("span", null, `${ABILITY_NAMES[a]} `, h("span", { class: "def-note" }, `score ${(panel.scores || {})[a] ?? "—"}${isRespec ? "" : ` (modifier ${signed(modOf((panel.scores || {})[a] ?? 10))})`}`)),
      h("input", { type: "number", class: "input", id: `grow-ability-${a}`, min: isRespec ? 8 : 0, max: isRespec ? 15 : 2, step: 1, value: values[a], dataset: { growAbility: a } })))),
    h("p", { class: `def-note${pv.legal ? "" : " grow-why"}` }, pv.note),
    h("p", { class: "def-note" }, "A higher score improves checks and saves using that ability; its modifier also affects attacks, defenses, or other numbers that use it."),
    h("p", { class: "def-note" }, pv.rows.map((r) => isRespec
      ? `${ABILITY_NAMES[r.a]}: base ${r.base} ${signed(r.bonus)} earned = final ${r.to} (current ${r.from ?? "—"})`
      : `${ABILITY_NAMES[r.a]} ${r.from ?? "—"}→${r.to ?? "—"}`).join(" · ")),
    h("div", { class: "powering-row" },
      h("button", { type: "button", class: "btn", disabled: busy || null, dataset: { growAbilitySave: "1" } }, "Record change"),
      h("span", { class: "def-note" }, "Recording updates ability modifiers, hit points, Armor Class, saving throws, initiative, skills, and technique attack and save numbers.")),
    rows.length ? h("div", { class: "grow-list" }, ...rows.map((row) => h("div", { class: "grow-row" },
      h("span", null, `${row.reason === "gm_respec" ? "GM respec" : "Level increase"} at CL ${row.cl}: ${Object.entries(row.changes || {}).map(([a, v]) => `${ABILITY_NAMES[a]} ${row.reason === "gm_respec" ? v : signed(v)}`).join(", ")}`,
        row.gm ? h("span", { class: "badge badge-gm", title: "Past the rules, by the GM" }, "GM") : null),
      h("button", { type: "button", class: "btn", disabled: busy || null, dataset: { growAbilityRemove: String(row.index) } }, "Remove"))))
      : null);
}

function render(inPlace = false) {
  const { h, $ } = deps;
  if (!data) return;
  const gmOn = gm();
  const added = data.added || { spheres: [], talents: [], forged: [] };
  const addedRows = [
    ...added.spheres.map((row) => ["sphere", row.id, `${row.name} (Sphere)`, row.gm, row.learning_benefit_labels, false]),
    ...added.talents.map((row) => ["talent", row.id, `${row.name}${row.cl ? ` · cultivation level ${row.cl}` : ""}${row.source ? ` · ${row.source}` : ""}`, row.gm, row.learning_benefit_labels, row.source === "level"]),
    ...added.forged.map((row) => ["forged", row.technique_id, `${row.name} — ${row.form}, ${row.cp} CP, Complexity ${row.complexity}${row.source ? ` · ${row.source}` : ""}`, row.gm, row.learning_benefit_labels, false]),
  ];
  const head = h("div", { class: "def-block" },
    h("div", { class: "powering-row" },
      h("span", null, `CL ${data.cl} · ${data.realm} · ${(data.paths || []).map((p) => p.split(".").pop().replace(/_/g, " ")).join(" + ")}`),
      h("label", { class: "grow-gm", title: "Add what the rules don't allow; it is marked as a GM grant" },
        h("input", { type: "checkbox", id: "grow-gm", checked: gmOn || null }), " GM override")),
    h("p", { class: "def-note" }, "What you add here is laid over the finished character for the table and every new fight; " +
      "the Factory's sealed character is not changed. Legal means a Path can learn the Sphere, or the talent's Sphere is " +
      "known and its prerequisites hold."));
  const addedBlock = h("details", { class: "def-block def-details", open: true },
    h("summary", null, h("span", { class: "def-label" }, `Added at the table (${addedRows.length})`)),
    addedRows.length ? h("div", { class: "grow-list" }, ...addedRows.map(([kind, id, label, isGm, benefits, isLevel]) => h("div", { class: "grow-row" },
      h("span", null, label, isGm ? h("span", { class: "badge badge-gm", title: "Added past the rules by the GM" }, "GM") : null,
        ...(benefits || []).map((benefit) => h("span", { class: "def-note" }, benefit))),
      isLevel ? h("span", { class: "def-note" }, "Use Undo last level to remove")
        : h("button", { type: "button", class: "btn", disabled: busy || null, dataset: { growRemove: kind, id } }, "Remove"))))
      : h("p", { class: "def-note" }, "Nothing yet."));

  const sq = query.sphere.trim().toLowerCase();
  const spheres = (data.spheres || []).filter((row) => !sq || row.name.toLowerCase().includes(sq));
  const sphereBlock = h("details", { class: "def-block def-details", id: "grow-spheres", open: $("grow-spheres")?.open || null },
    h("summary", null, h("span", { class: "def-label" }, `Learn a Sphere (${(data.spheres || []).filter((r) => r.legal).length} open)`)),
    h("input", { type: "search", class: "input", id: "grow-sphere-q", placeholder: "Find a Sphere…", value: query.sphere }),
    h("div", { class: "grow-list" }, ...spheres.map((row) => h("div", { class: "grow-row" },
      h("span", null, row.name, why(row) ? h("span", { class: "def-note grow-why" }, ` — ${why(row)}`) : null), learningFields(row), learnButton("sphere", row)))));

  const tq = query.talent.trim().toLowerCase();
  const talents = (data.talents || []).filter((row) => (!query.legalOnly || row.legal || (gmOn && row.gm))
    && (!tq || `${row.name} ${row.sphere}`.toLowerCase().includes(tq)));
  const talentBlock = h("details", { class: "def-block def-details", id: "grow-talents", open: $("grow-talents")?.open ?? true },
    h("summary", null, h("span", { class: "def-label" }, `Learn a talent (${(data.talents || []).filter((r) => r.legal).length} legal now)`)),
    h("div", { class: "powering-row" },
      h("input", { type: "search", class: "input", id: "grow-talent-q", placeholder: "Find a talent or Sphere…", value: query.talent }),
      h("label", null, h("input", { type: "checkbox", id: "grow-legal-only", checked: query.legalOnly || null }), " legal only")),
    h("div", { class: "grow-list" }, ...talents.map((row) => h("div", { class: "grow-row", title: row.summary || "" },
      h("span", null, h("strong", null, row.name), ` · ${row.sphere}${row.minimum_cl ? ` · CL ${row.minimum_cl}` : ""}`,
        why(row) ? h("span", { class: "def-note grow-why" }, ` — ${why(row)}`) : null),
      learningFields(row), learnButton("talent", row)))),
    null);

  const sourcePicker = h("label", { class: "powering-row" }, "Learning source ",
    h("select", { id: "grow-source", class: "input" }, ...(data.sources || ["campaign", "manual", "jade tablet"]).map((value) =>
      h("option", { value, selected: learningSource === value || null }, value === "campaign" ? "Campaign reward or training" : value === "manual" ? "Martial manual" : "Jade tablet"))));
  const children = [head, methodBlock(), levelBlock(), abilityBlock(), goldenCoreBlock(), addedBlock, insightBlock(), immortalArtBlock(), sourcePicker, forgeBlock(), talentBlock, sphereBlock].filter(Boolean);
  if (inPlace) patchGrowNode($("grow-root"), h("div", {id:"grow-root"}, ...children));
  else $("grow-root").replaceChildren(...children);
  refreshForgeInPlace();
}

// Method changes are cultivation events. Only the server calculates a preview.
let methodDraft = {method_id:"",source:"",note:"",opportunity:"",completed:false};
let methodPreview = null;

function methodBlock() {
  const {h}=deps, info=data.method_change;
  if (!info) return null;
  const selected=info.options.find(r=>r.id === methodDraft.method_id);
  const select=(key,label,rows)=>h("label",null,label," ",h("select",{class:"input",dataset:{methodField:key}},
    h("option",{value:""},"Choose…"),...rows.map(r=>h("option",{value:r.id,selected:methodDraft[key] === r.id || null},r.name))));
  return h("section",{id:"grow-method",class:"def-block"},h("h3",null,"Change Primary Method"),
    h("p",null,"Primary Method: "+info.primary.name),
    h("p",{class:"def-note"},"Only your Primary Method changes resource limits, breakthroughs, and Foundation relationships. Old Methods remain Known but inactive. Attainment Points (AP) advance a Path; only your Primary Method routes future points. PB means your proficiency bonus. Existing Path attainment, required choices, Foundation choices, scars, injuries, and deviations remain. No resources are restored."),
    h("p",{class:"def-note"},info.free_replacement
      ? "Your blank starting sect Method can be replaced freely for the first time; this is not a risky change."
      : "Requires a campaign source and completed downtime or story training. Not during combat, a short rest, or a daily loadout change."),
    select("method_id","New Primary Method",info.options.map(r=>({...r,name:r.name+(r.current ? " (current)" : "")+(!r.legal ? " — "+r.reasons.join("; ") : "")}))),
    selected ? h("div",null,h("p",null,selected.summary),
      ...[selected.resource,selected.breakthrough,selected.foundation,selected.future_ap].map(t=>h("p",{class:"def-note"},t)),
      !selected.legal ? h("p",{class:"grow-why"},selected.reasons.join("; ")+" Requires GM override; recorded as a GM grant.") : null) : null,
    select("source","Campaign source",info.sources.map(s=>({id:s,name:s === "gm" ? "GM override" : s}))),
    h("label",null,"Name the source or permission ",h("input",{class:"input",value:methodDraft.note,maxLength:500,dataset:{methodField:"note"}})),
    select("opportunity","Completed cultivation opportunity",info.opportunities.map(s=>({id:s,name:s}))),
    h("label",null,h("input",{type:"checkbox",checked:methodDraft.completed || null,dataset:{methodField:"completed"}}),
      " Training or story event is complete; not a short rest or routine daily change."),
    h("div",{class:"powering-row"},h("button",{type:"button",class:"btn",disabled:busy || !selected || selected.current || (!selected.legal && !gm()) || null,dataset:{methodAction:"preview"}},"Preview Method change"),
      methodPreview ? h("button",{type:"button",class:"btn btn-accent",disabled:busy || null,dataset:{methodAction:"save"}},"Record Primary Method change") : null),
    methodPreview ? h("div",null,h("p",null,"New Primary Method: "+methodPreview.method.display_name+(methodPreview.change.gm ? " — GM grant" : "")),
      ...((methodPreview.statistics.primary_resource?.definitions) || []).map(p=>h("p",null,p.name+": "+p.current+" current / "+p.max+" maximum; no refill."))) : null,
    info.known.length ? h("p",{class:"def-note"},"Known Methods: "+info.known.map(r=>r.display_name+(r.state === "active" ? " (Primary)" : " (inactive)")).join(", ")) : null,
    ...info.history.map(r=>h("p",{class:"def-note"},r.name+" — "+r.source+(r.note ? ": "+r.note : "")+(r.gm ? " — GM grant" : "")+(r.free_replacement ? " — free starting sect replacement" : ""))),
    info.history.length ? h("button",{type:"button",class:"btn",disabled:busy || null,dataset:{methodAction:"undo"},title:"Undo later levels or remove later gains first."},"Undo last Method change") : null);
}

// Draft choices stay local until one atomic save. No request per pick.
function levelMenus() {
  const info = data.level_up || {};
  return info.planning || (info.cl ? [info] : []);
}

function abilityAllocations(info, scores) {
  const rule = info.ability_rule || {};
  const order = [info.key_ability, ...ABILITY_ORDER].filter((a,i,all) => a && all.indexOf(a) === i);
  const result = [];
  function visit(at, left, changes) {
    if (!left) {
      result.push({id:JSON.stringify(changes), name:Object.entries(changes).map(([a,n]) => ABILITY_NAMES[a]+" +"+n).join(", "),
        summary:"Permanent increase; maximum score "+rule.cap+".", legal:true, changes:{...changes}});
      return;
    }
    for (let i=at; i<order.length; i++) for (const n of [...(rule.allowed_deltas || [])].sort((a,b) => b-a)) {
      const a=order[i];
      if (n<=left && scores[a]+n<=rule.cap) visit(i+1,left-n,{...changes,[a]:n});
    }
  }
  if (rule.budget) visit(0,rule.budget,{});
  return result;
}

function talentLegal(row, known, cl) {
  if (known.has(row.id) || row.unresolved) return false;
  const holds = (r) => {
    if (r.kind === "minimum_cl") return cl>=Number(r.value);
    if (["talent","sphere","owning_sphere","path"].includes(r.kind)) return known.has(r.target_id);
    if (r.kind === "realm") {
      const realms=["mortal","foundation","core formation","nascent soul","immortal"];
      const mine=cl>=20 ? 4 : cl>=15 ? 3 : cl>=10 ? 2 : cl>=5 ? 1 : 0;
      const want=String(r.value || r.target_id || "").toLowerCase().replaceAll("_"," ");
      const index=realms.findIndex((name) => want.includes(name));
      return index>=0 && mine>=index;
    }
    return false;
  };
  const rules=(row.constraints || []).filter((r) => !r.scope || r.scope === "acquisition");
  if (!rules.length) return row.legal;
  if (!rules.filter((r) => !r.alternative_id).every(holds)) return false;
  return (row.clauses || []).filter((r) => !r.scope || r.scope === "acquisition").every((c) =>
    (c.alternatives || []).some((a) => {
      const rs=rules.filter((r) => r.alternative_id === a.alternative_id);
      return rs.length && rs.every(holds);
    }));
}

// Read-only arithmetic over the server's SafeFormula AST, never expression strings.
function levelFormula(n, cl, pb, scores) {
  if (n.op === "constant") return n.value;
  if (n.op === "cl") return cl;
  if (n.op === "pb") return pb;
  if (n.op === "ability_score") return scores[n.ability];
  if (n.op === "ability_modifier") return modOf(scores[n.ability]);
  const f=(x) => levelFormula(x,cl,pb,scores);
  if (n.op === "subtract") return f(n.left)-f(n.right);
  if (n.op === "clamp") return Math.min(n.maximum ?? Infinity,Math.max(n.minimum ?? -Infinity,f(n.value)));
  const values=(n.terms || []).map(f);
  if (n.op === "add") return values.reduce((a,b) => a+b,0);
  if (n.op === "multiply") return values.reduce((a,b) => a*b,1);
  if (n.op === "minimum") return Math.min(...values);
  if (n.op === "maximum") return Math.max(...values);
  throw Error("The level preview contains an unsupported formula.");
}

function levelStatistics(menu,scores,owned) {
  const stat=JSON.parse(JSON.stringify(menu.statistics || {})), cl=menu.cl, pb=stat.pb;
  const baseline=menu.scores || scores, f=(root,s) => levelFormula(root,cl,pb,s);
  if (stat.hp && Number.isInteger(scores.CON) && Number.isInteger(baseline.CON)) stat.hp.maximum+=cl*(modOf(scores.CON)-modOf(baseline.CON));
  if (stat.resource) stat.resource.maximum+=(menu.resource_formulas || []).reduce((sum,r) => sum+f(r,scores)-f(r,baseline),0);
  const info=data.level_up || {};
  if (info.ac_baseline) {
    const rules=(info.ac_rules || []).filter((r) => owned.has(r.feature_id));
    const options=[{feature_id:null,value:f(info.ac_baseline,scores)},...rules.filter((r) => r.kind === "base_ac_calculation")
      .map((r) => ({feature_id:r.feature_id,value:f(r.formula.root,scores)}))];
    const chosen=options.reduce((a,b) => b.value>a.value ? b : a);
    const bonus=rules.filter((r) => r.kind === "ac_bonus" && (!r.requires_base_calculation_feature_id || r.requires_base_calculation_feature_id === chosen.feature_id))
      .reduce((sum,r) => sum+(r.bonus || 0),0);
    stat.ac={base_value:chosen.value,value:chosen.value+bonus+(menu.ac_residual || 0)};
  }
  return stat;
}

function draftInsights(menu,known,counts) {
  return (menu.insights || []).map((r) => {
    const grouped=new Set((r.requirements || []).filter((p) => p.kind === "any_of").flatMap((p) => p.value || []));
    const required=(r.requirements || []).every((p) => p.kind === "any_of" ? (p.value || []).some((id) => known.has(id)) :
      grouped.has(p.target_id) || !["sphere","path","talent","insight","subpath_or_tradition"].includes(p.kind) || known.has(p.target_id));
    const count=(r.known_count || 0)+(counts[r.id] || 0);
    const blockers=(r.reasons || []).filter((v) => !v.startsWith("Needs ") && !v.startsWith("GM confirmation needed:")
      && !v.startsWith("Record the choice required") && !(r.needs_choice && v.includes("Available:")));
    const allowed=r.selectable !== false && required && menu.cl>=r.minimum_cl && (r.maximum == null || count<r.maximum) && !blockers.length;
    return {...r,legal:allowed,requires_confirmation:r.gm || (r.reasons || []).some((v) => v.startsWith("GM confirmation needed:"))};
  });
}

function levelPlan() {
  const info=data.level_up || {}, a=levelDraft.addPath || {}, tmpl=a.path_id ? info.add_templates?.[a.path_id] : null;
  // The pending Path's Subpath and feature choices apply at the first level being planned.
  // The template lists every held Path's rows too; keep one row per Path Subpath group and per feature choice.
  const all=levelMenus().map((m,i) => {
    if (!tmpl) return m;
    if (i !== 0) return {...m, foundation:m.foundation ? tmpl.foundation_options : null};
    const groups=new Set((m.subpaths || []).map((g) => g.path_id)), picks=new Set((m.feature_choices || []).map((r) => r.feature_id));
    return {...m, foundation:m.foundation ? tmpl.foundation_options : null, subpaths:[...(m.subpaths || []), ...(tmpl.subpaths || []).filter((g) => !groups.has(g.path_id))],
      feature_choices:[...(m.feature_choices || []), ...(tmpl.feature_choices || []).filter((r) => !picks.has(r.feature_id))]};
  });
  const target=Math.max(info.cl || 2,Math.min(20,levelDraft.target || info.cl || 2));
  levelDraft.rows ||= {};
  const known=new Set(Object.values(info.known || {}).flat()), selectedSubpaths={}, owned=new Set(), counts={};
  const scores={...(all[0]?.scores || {})}, result=[];
  let previous=all[0]?.before_statistics || {}, acquiredFoundation=null;
  for (const menu of all.filter((m) => m.cl<=target)) {
    Object.values(menu.known || {}).flat().forEach((id) => known.add(id));
    const d=levelDraft.rows[menu.cl] ||= {cl:menu.cl,talent_ids:[],subpaths:{},feature_choices:{},changes:{}};
    const talents=(menu.talents || []).map((r) => ({...r,legal:talentLegal(r,known,menu.cl)}));
    if (!d.talent_ids.length) d.talent_ids=talents.filter((r) => r.legal).slice(0,menu.talent_count).map((r) => r.id);
    for (const group of menu.subpaths || []) {
      d.subpaths[group.path_id] ??= group.options.find((r) => r.legal && !r.requires_confirmation)?.id || "";
      if (d.subpaths[group.path_id]) selectedSubpaths[group.path_id]=d.subpaths[group.path_id];
    }
    let features=[...(menu.features || [])], build=[...(menu.feature_choices || [])];
    for (const id of Object.values(selectedSubpaths)) {
      const prog=(info.subpath_progressions?.[id] || []).find((p) => p.cl === menu.cl);
      if (prog) {features.push(...prog.features);build.push(...prog.build_choices);}
      else {
        const opt=(menu.subpaths || []).flatMap((g) => g.options).find((r) => r.id === id);
        if (opt) {features.push(...(opt.feature_rows || []));build.push(...(opt.build_choices || []));}
      }
    }
    features=features.filter((r,i,a) => a.findIndex((v) => v.id === r.id) === i);
    build=build.filter((r,i,a) => a.findIndex((v) => v.feature_id === r.feature_id) === i);
    const required=new Set(build.map((r) => r.feature_id));
    for (const id of Object.keys(d.feature_choices)) if (!required.has(id)) delete d.feature_choices[id];
    for (const r of build) d.feature_choices[r.feature_id] ??= r.options[0]?.id || "";
    Object.values(selectedSubpaths).forEach((id) => known.add(id));
    d.talent_ids.forEach((id) => known.add(id));
    const insights=draftInsights(menu,known,counts);
    const allocations=abilityAllocations(menu,scores);
    let insightAbilities=[];
    if (menu.advancement_choice) {
      d.advancement ||= "ability";
      if (d.advancement === "ability") {
        if (!Object.keys(d.changes).length) d.changes={...(allocations[0]?.changes || {})};
        for (const [a,n] of Object.entries(d.changes)) scores[a]+=n;
      } else {
        d.insight_id ||= insights.find((r) => r.legal)?.id || "";
        const rule=insights.find((r) => r.id === d.insight_id)?.ability_rule;
        insightAbilities=(rule?.allowed_abilities || []).map((a) => ({id:a,name:ABILITY_NAMES[a]+" +"+rule.amount,
          summary:"Permanent ability increase from this Insight.",legal:scores[a]+rule.amount<=rule.cap}));
        d.insight_ability ||= insightAbilities.find((r) => r.legal)?.id || "";
        if (d.insight_ability && rule) scores[d.insight_ability]+=rule.amount;
      }
    }
    [...(menu.owned_features || []),...features.map((r) => r.id)].forEach((id) => owned.add(id));
    const foundationOffered=Boolean(menu.foundation && !acquiredFoundation);
    if (!foundationOffered) {delete d.foundation_id;delete d.foundation_initial_stage;}
    else if (d.foundation_id) {
      const chosen=menu.foundation.options.find((r) => r.id === d.foundation_id);
      if (!chosen?.legal) {delete d.foundation_id;delete d.foundation_initial_stage;}
      else {
        if (chosen.stage_options.length === 1) d.foundation_initial_stage=chosen.stage_options[0];
        acquiredFoundation={row:chosen,stage:d.foundation_initial_stage};
      }
    }
    const statistics=levelStatistics(menu,scores,owned);
    const extra=acquiredFoundation?.row.preview_by_stage?.[acquiredFoundation.stage];
    if (extra) for (const field of ["hp","resource"]) {
      if (statistics[field]) statistics[field].maximum+=(extra[field] || []).reduce((n,r) => n+levelFormula(r,menu.cl,statistics.pb,scores),0);
    }
    result.push({menu,d,foundationOffered,talents,features,build,allocations,insights,insightAbilities,statistics,previous});
    previous=statistics;
    d.talent_ids.forEach((id) => known.add(id));
    if (d.advancement === "insight" && d.insight_id) {known.add(d.insight_id);counts[d.insight_id]=(counts[d.insight_id] || 0)+1;}
  }
  return result;
}

function levelPicker(cl,key,title,rows,selected,multiple=false) {
  const {h}=deps, id="level-"+cl+"-"+key;
  const filter=levelDraft.filters?.[id] || {q:"",legal:true};
  return h("fieldset",{id,class:"def-block"},h("legend",null,title),
    h("input",{type:"search",class:"input",id:id+"-q",placeholder:"Search by name or Sphere…",value:filter.q,dataset:{levelFilter:id}}),
    h("label",null,h("input",{type:"checkbox",checked:filter.legal || null,dataset:{levelLegal:id}})," legal only"),
    h("div",{class:"grow-list"},...rows.map((r) => {
      const legal=r.legal !== false, text=(r.name+" "+(r.sphere || "")).toLowerCase();
      const checked=multiple ? selected.includes(r.id) : selected === r.id;
      return h("label",{id:id+"-"+r.id,class:"grow-row",title:r.summary || (r.reasons || []).join("; "),
        hidden:((!legal && filter.legal && !checked) || !text.includes(filter.q.toLowerCase())) || null,
        dataset:{levelSearch:text,levelIsLegal:legal ? "1" : "0"}},
        h("input",{type:multiple ? "checkbox" : "radio",name:id,value:r.id,checked:checked || null,disabled:(!legal && !checked) || null,
          dataset:{levelPick:key,levelCl:String(cl)}}),
        r.name,r.sphere ? " · "+r.sphere : "",!legal ? " — "+((r.reasons || []).join("; ") || "Not available") : "");
    })));
}

function addPathBlock(info) {
  const {h}=deps, a=levelDraft.addPath, candidates=info.add_candidates || [];
  const template=info.add_templates?.[a.path_id] || null;
  const method=info.primary_method || null;
  const accessNames={...(method ? {primary_method:"Primary Method grant"} : {}),phb:"PHB source",gm:"GM override"};
  const notes=(info.duplicate_notes || []).map((n) => h("p",{class:"def-note"},n));
  return h("fieldset",{id:"level-add-path",class:"def-block"},h("legend",null,"Add a Path"),
    h("p",{class:"def-note"},"A second Path advances at this character's cultivation level. Its core features are gained through this level; the Path's mandatory choices and any Subpath are asked here."),
    h("label",null,"Path ",h("select",{id:"level-add-path-id",dataset:{levelAddPath:"path_id"}},
      h("option",{value:""},"Choose a Path to add"),
      ...candidates.map((c) => h("option",{value:c.id,selected:a.path_id === c.id || null},c.name)))),
    h("label",null,"Access source ",h("select",{id:"level-add-access",dataset:{levelAddPath:"access"}},
      h("option",{value:""},"Choose the access source"),
      ...Object.entries(accessNames).map(([k,v]) => h("option",{value:k,selected:a.access === k || null},v)))),
    a.access === "primary_method"
      ? h("p",{class:"def-note",id:"level-add-method-source"},method
          ? ["Access source: ",h("strong",null,method.name),", your recorded Primary Method."]
          : "This character has no recorded Primary Method; choose another access source.")
      : h("label",null,"Source name ",h("input",{class:"input",id:"level-add-source",maxlength:200,value:a.source_id,placeholder:"Teacher, manual, bloodline awakening, spirit event, bodily transformation, cultivation accident, or other",dataset:{levelAddPath:"source_id"}})),
    a.access === "gm" ? h("label",null,h("input",{type:"checkbox",checked:a.confirmed || null,dataset:{levelAddPath:"confirmed"}})," The Game Master confirms this override.") : null,
    template ? h("p",{class:"def-note"},"Its Subpath and mandatory choices are asked in the level rows below.") : null,
    info.add_error ? h("p",{class:"def-note",role:"alert"},info.add_error) : null,
    ...notes);
}

function foundationBlock(menu,d) {
  const {h}=deps, chosen=menu.foundation.options.find((r) => r.id === d.foundation_id);
  return h("fieldset",{id:"level-"+menu.cl+"-foundation",class:"def-block"},
    h("legend",null,"Choose an Orthodox Foundation, or Not yet"),
    h("p",{class:"def-note"},"A Foundation is your deep cultivation structure, not another Path. You gain its published initial-stage benefits; spent points are not refilled. Undoing this level removes the choice."),
    ...[{id:"",name:"Not yet — offer this again at a later Level up",legal:true},...menu.foundation.options].map((r) =>
      h("label",{class:"grow-row",title:r.summary || ""},
        h("input",{type:"radio",name:"foundation-"+menu.cl,value:r.id,checked:(d.foundation_id || "") === r.id || null,
          disabled:!r.legal || null,dataset:{levelPick:"foundation",levelCl:String(menu.cl)}}),
        r.name,r.legal ? "" : " — "+r.reasons.join("; "))),
    chosen ? h("p",{class:"def-note"},chosen.summary) : null,
    chosen?.stage_options.length > 1 ? h("fieldset",null,h("legend",null,"Choose "+chosen.name+"'s initial stage"),
      ...chosen.stage_options.map((stage) => h("label",{class:"grow-row"},
        h("input",{type:"radio",name:"foundation-stage-"+menu.cl,value:stage,checked:d.foundation_initial_stage === stage || null,
          dataset:{levelPick:"foundationStage",levelCl:String(menu.cl)}}),stage)))
      : chosen ? h("p",null,"Initial stage: "+chosen.stage_options[0]) : null);
}

function levelBlock() {
  const {h}=deps, info=data.level_up || {}, content=[];
  const review=(info.history || []).map((r) => h("details",{id:"level-history-"+r.cl},
    h("summary",null,"Cultivation level "+r.cl),
    h("p",null,[...(r.features || []),...(r.talents || [])].map((v) => v.name).join(", ")),
    r.foundation ? h("p",null,"Foundation: "+r.foundation.name+" — "+r.foundation.stage) : null));
  if (info.available) {
    content.push(h("label",null,"Level up to CL ",
      h("input",{id:"level-target",type:"number",min:info.cl,max:20,value:levelDraft.target || info.cl})));
    for (const {menu:m,d,foundationOffered,talents,features,build,allocations,insights,insightAbilities,statistics,previous} of levelPlan()) {
      const rows=[h("h4",null,"Cultivation level "+m.cl),h("p",null,"Path and Subpath features gained automatically:"),
        ...features.map((r) => h("details",{id:"level-feature-"+m.cl+"-"+r.id},h("summary",null,r.name+" — gained"),h("p",{style:"white-space:pre-wrap"},r.text)))];
      if (foundationOffered) rows.push(foundationBlock(m,d));
      for (const b of build) rows.push(levelPicker(m.cl,"feature:"+b.feature_id,b.prompt,b.options,d.feature_choices[b.feature_id]));
      rows.push(levelPicker(m.cl,"talent","Free Sphere talent — choose "+m.talent_count+" from a Sphere you know",talents,m.talent_count === 1 ? d.talent_ids[0] : d.talent_ids,m.talent_count !== 1));
      if (m.advancement_choice) {
        rows.push(levelPicker(m.cl,"advancement","Choose ability scores or a Cultivation Insight",[
          {id:"ability",name:"Improve ability scores",summary:"Choose the published increase to one or two abilities."},
          {id:"insight",name:"Learn a Cultivation Insight",summary:"Gain its cultivation benefit and its listed +1 ability increase."}],d.advancement));
        if (d.advancement === "ability") rows.push(levelPicker(m.cl,"ability","Ability increase",allocations,JSON.stringify(d.changes)));
        else {
          rows.push(levelPicker(m.cl,"insight","Cultivation Insight",insights,d.insight_id));
          rows.push(levelPicker(m.cl,"insightAbility","Insight ability increase",insightAbilities,d.insight_ability));
          const options=insights.find((r) => r.id === d.insight_id)?.choice_options || [];
          if (options.length) {
            d.insight_choice ||= options[0].id;
            rows.push(levelPicker(m.cl,"insightChoice","Choose the Insight's resource",options,d.insight_choice));
          } else rows.push(h("label",null,"Choice required by the Insight (if any) ",
            h("input",{class:"input",value:d.insight_choice || "",maxlength:240,dataset:{levelText:"insight_choice",levelCl:String(m.cl)}})));
        }
      }
      for (const group of m.subpaths || []) rows.push(levelPicker(m.cl,"subpath:"+group.path_id,"Cultivation level "+m.cl+" Subpath — "+group.name,
        group.options.map((r) => ({...r,summary:[r.access,...(r.features || [])].join("; ")})),d.subpaths[group.path_id]));
      if ((m.subpaths || []).some((g) => g.options.find((r) => r.id === d.subpaths[g.path_id])?.requires_confirmation)
          || (d.advancement === "insight" && insights.find((r) => r.id === d.insight_id)?.requires_confirmation))
        rows.push(h("label",null,h("input",{type:"checkbox",checked:d.access_confirmed || null,
          dataset:{levelText:"access_confirmed",levelCl:String(m.cl)}})," The Game Master confirms the printed access and choice requirements."));
      const stat=statistics;
      rows.push(h("p",null,"Maximum HP: "+(previous.hp?.maximum ?? "—")+" → "+stat.hp?.maximum+". Armor Class: "+(previous.ac?.value ?? "—")+" → "+(stat.ac?.value ?? "—")+". Proficiency bonus: +"+stat.pb+"."));
      if (stat.resource) rows.push(h("p",null,stat.resource.name+" maximum: "+(previous.resource?.maximum ?? "—")+" → "+stat.resource.maximum+". These points pay for your Path's abilities."));

      content.push(h("section",{id:"level-row-"+m.cl,class:"def-block"},...rows));
    }
    content.push(addPathBlock(info));
    content.push(h("button",{type:"button",class:"btn btn-accent",disabled:busy || null,dataset:{levelSave:"1"}},"Level up"));
  } else content.push(h("p",null,info.reason || "Level up is unavailable."));
  if (review.length) content.push(h("button",{type:"button",class:"btn",disabled:busy || null,dataset:{levelUndo:"1"},
    title:"Undo one level at a time; remove any later campaign gains first."},"Undo last level"));
  return h("section",{id:"grow-level-panel",class:"def-block"},h("h3",null,"Level up"),
    h("p",{class:"def-note"},"Choose benefits below, then apply them together. New fights use the updated sheet; existing fights and your sealed character package stay unchanged."),
    ...content,...review);
}

function filterLevelList(id) {
  const filter=levelDraft.filters[id], block=deps.$(id);
  for (const row of block?.querySelectorAll("[data-level-search]") || []) {
    row.hidden=(filter.legal && row.dataset.levelIsLegal !== "1" && !row.querySelector("input")?.checked)
      || !row.dataset.levelSearch.includes(filter.q.toLowerCase());
  }
}

// Re-mark keyed panel nodes in place: retain focus, scroll and open sections.
function patchLevelPanel() {
  const current=deps.$("grow-level-panel");
  if (current) patchGrowNode(current,levelBlock());
}

function patchGrowNode(current,next) {
  function patch(old,fresh) {
    if (old.nodeType !== fresh.nodeType || old.nodeName !== fresh.nodeName) {old.replaceWith(fresh);return;}
    if (old.nodeType === 3) {if(old.nodeValue !== fresh.nodeValue) old.nodeValue=fresh.nodeValue;return;}
    const wasOpen=old.tagName === "DETAILS" ? old.open : null;
    for (const a of [...old.attributes]) if (!fresh.hasAttribute(a.name)) old.removeAttribute(a.name);
    for (const a of [...fresh.attributes]) if (old.getAttribute(a.name) !== a.value) old.setAttribute(a.name,a.value);
    for (const key of ["checked","disabled","hidden"]) if (key in fresh) old[key]=fresh[key];
    if ("value" in fresh && old.value !== fresh.value) old.value=fresh.value;
    const keyed=new Map([...old.childNodes].filter((n) => n.id).map((n) => [n.id,n]));
    let i=0;
    for (const child of [...fresh.childNodes]) {
      let found=child.id ? keyed.get(child.id) : old.childNodes[i];
      if (found?.id && found.id !== child.id) found=null;
      if (!found) old.insertBefore(child,old.childNodes[i] || null);
      else {if(old.childNodes[i] !== found) old.insertBefore(found,old.childNodes[i] || null);patch(found,child);}
      i++;
    }
    while(old.childNodes.length>i) old.lastChild.remove();
    if(wasOpen !== null) old.open=wasOpen;
  }
  const x=globalThis.scrollX,y=globalThis.scrollY;
  patch(current,next);
  globalThis.scrollTo?.(x,y);
}

// Campaign gains use the same persisted record as every other Grow entry.
function insightBlock() {
  const { h, $ } = deps;
  const q = insightDraft.query.toLowerCase().trim();
  const rows = (data.insights || []).filter((row) => !q || (row.name + " " + row.text).toLowerCase().includes(q));
  return h("details", { class: "def-block def-details", id: "grow-insights", open: $("grow-insights")?.open ?? true },
    h("summary", null, h("span", { class: "def-label" }, "Insights gained in play")),
    h("p", { class: "def-note" }, "Record a lesson or reward without gaining a level. You gain the Insight's benefit, not its level-selection ability-score increase. The sheet explains which benefits the fight automates and which need the Game Master."),
    h("label", null, "Where it came from ", h("input", { class: "input", id: "grow-insight-note", maxlength: 240, value: insightDraft.note })),
    h("label", null, "Choice required by the Insight (if any) ", h("input", { class: "input", id: "grow-insight-choice", maxlength: 240, value: insightDraft.choice })),
    h("p", { class: "def-note" }, "The GM override confirms story prerequisites and chosen options; it cannot bypass level, known-feature, or repeat limits."),
    h("input", { class: "input", type: "search", id: "grow-insight-q", placeholder: "Find an Insight…", value: insightDraft.query }),
    h("div", { class: "grow-list" }, ...rows.map((row) => h("details", { class: "grow-row" },
      h("summary", null, row.name),
      h("p", { class: "def-note", style: "white-space:pre-wrap" }, row.text),
      why(row) ? h("p", { class: "grow-why" }, why(row)) : null,
      h("button", { type: "button", class: "btn", disabled: busy || (!row.legal && !gm() && !row.needs_choice) || null,
        dataset: { growInsight: row.id } }, "Record Insight")))),
    ...(data.added.insights || []).map((row) => h("div", { class: "grow-row" },
      h("span", null, row.name, " — ", row.note, row.choice ? " · " + row.choice : "", row.gm ? " (GM confirmed)" : ""),
      h("button", { type: "button", class: "btn", disabled: busy || null,
        dataset: { growRemove: "insight", id: String(row.index) } }, "Remove"))));
}

function immortalArtBlock() {
  const { h, $ } = deps;
  const menu = data.immortal_art || {};
  const aspect = (menu.aspects || []).find((row) => row.id === artDraft.aspect_id);
  const option = (value, label, selected) => h("option", { value, selected: selected || null }, label);
  const picks = (kind, rows) => h("div", { class: "grow-chips" }, ...rows.map((row) => h("label", { title: row.text || "" },
    h("input", { type: "checkbox", dataset: { growArtPick: kind, id: row.id }, checked: artDraft[kind].includes(row.id) || null }), " ", row.name)));
  const preview = artPreview?.art;
  return h("details", { class: "def-block def-details", id: "grow-immortal-art", open: $("grow-immortal-art")?.open ?? true },
    h("summary", null, h("span", { class: "def-label" }, `Custom Immortal Arts (${menu.known || 0} of ${menu.limit || 0} known)`)),
    h("p", { class: "def-note" }, "At cultivation level 15 or higher, elevate a known action with a Dao Aspect (a powerful principle) and Factors (specific upgrades). Burdens are restrictions that reduce the cost or difficulty. Only source actions supported by the character-creation validator are offered; the same construction rules apply here."),
    menu.unavailable ? h("p", { class: "grow-why" }, menu.unavailable + " Install the Immortal Art authoring rules to create an Art here.") : null,
    h("label", null, "Name ", h("input", { class: "input", id: "grow-art-name", maxlength: 80, value: artDraft.name })),
    h("label", null, "Base action ", h("select", { class: "input", id: "grow-art-source" },
      option("", "Choose a known source action", !artDraft.source_record_id),
      ...(menu.sources || []).map((row) => option(row.id, row.name, row.id === artDraft.source_record_id)))),
    h("label", null, "Dao Aspect ", h("select", { class: "input", id: "grow-art-aspect" },
      option("", "Choose a principle", !artDraft.aspect_id),
      ...(menu.aspects || []).map((row) => option(row.id, row.name, row.id === artDraft.aspect_id)))),
    aspect ? h("div", null, h("p", null, "Factors — select upgrades (hover for rules)"), picks("factor_ids", aspect.factors),
      h("p", null, "Burdens — restrictions you must follow"), picks("burdens", aspect.burdens)) : null,
    h("button", { type: "button", class: "btn", disabled: busy || !artDraft.source_record_id || !aspect || null,
      dataset: { growArtCheck: "1" } }, "Check Art"),
    preview ? h("div", { class: "grow-preview" },
      h("p", null, `${artPreview.name}: ${preview.action_surface.action_type}; ${preview.action_surface.range}; ${preview.action_surface.target}; ${preview.action_surface.duration}. Costs ${preview.activation_cp} ${preview.action_surface.resource_name} per use. Complexity ${preview.mandate_complexity}; Refinement Check difficulty ${preview.refinement_dc}.`),
      h("p", { class: "def-note" }, artPreview.combat_note),
      h("p", { class: "def-note" }, `Before recording, complete ${artPreview.required_research_hours} hours of research, pay ${artPreview.required_materials_gp} gp in materials, and succeed on a d20 + proficiency bonus + Path ability modifier check. Record what happened at your table; this does not spend money or pass time automatically.`),
      h("label", null, "Refinement d20 result ", h("input", { class: "input", type: "number", min: 1, max: 20, id: "grow-art-die", value: artProof.die })),
      h("label", null, "Completed research hours ", h("input", { class: "input", type: "number", min: 0, id: "grow-art-hours", value: artProof.research_hours })),
      h("label", null, "Materials already paid (gp) ", h("input", { class: "input", type: "number", min: 0, id: "grow-art-gp", value: artProof.materials_gp })),
      h("label", null, "Where it came from ", h("input", { class: "input", maxlength: 240, id: "grow-art-note", value: artNote })),
      h("button", { type: "button", class: "btn", disabled: busy || null, dataset: { growArtSave: "1" } }, "Record refined Art")) : null,
    ...(data.added.immortal_arts || []).map((row) => h("details", { class: "grow-row" },
      h("summary", null, row.name, " — ", row.note),
      h("p", null, `Costs ${row.art.activation_cp} ${row.art.action_surface.resource_name}; ${row.art.action_surface.action_type}; ${row.art.action_surface.range}; ${row.art.action_surface.duration}.`),
      h("p", { class: "def-note" }, "Full source, upgrade and restriction rules are in the sheet's Immortal Arts library."),
      h("button", { type: "button", class: "btn", disabled: busy || null,
        dataset: { growRemove: "immortal_art", id: row.id } }, "Remove"))));
}

function forgeSphereOf(f, id) {
  return (f.sources || []).find((row) => row.id === id)?.sphere_id;
}

// Complexity and Sphere count of the design as it stands (Base Form + one per extra Sphere + Augments).
function forgeCapacity(f) {
  const form = (f.forms || []).find((row) => row.form_id === forge.base_form);
  const per = Number(f.sphere_complexity) || 1;
  const augment = forge.augment_ids.reduce((sum, id) => sum + (Number((f.augments || []).find((row) => row.augment_id === id)?.complexity) || 0), 0);
  return { complexity: (form ? Number(form.complexity) || 0 : 0) + forge.secondary_talent_ids.length * per + augment,
           spheres: 1 + forge.secondary_talent_ids.length, per };
}

// [fits, reason] from the table built at Grow load; no Base Form or Primary yet means nothing is judged.
function forgeFit(f, id) {
  if (!forge.base_form || !forge.primary_talent_id) return [true, ""];
  return ((f.fit || {})[forge.base_form] || {})[id] || [true, ""];
}

// Greying (not hiding) for Complexity and Sphere limits. Swapping within a picked Sphere stays enabled; GM lifts it.
function secondaryGrey(f, row) {
  if (gm() || forge.secondary_talent_ids.includes(row.id)) return "";
  if (forge.secondary_talent_ids.some((id) => forgeSphereOf(f, id) === row.sphere_id)) return "";
  const cap = forgeCapacity(f);
  if (cap.spheres + 1 > f.max_spheres) return `This Realm allows ${f.max_spheres} Spheres; this would make ${cap.spheres + 1}.`;
  if (cap.complexity + cap.per > f.max_complexity) return `This Realm's Complexity maximum is ${f.max_complexity}; this would make ${cap.complexity + cap.per}.`;
  return "";
}

function augmentGrey(f, row) {
  if (gm() || forge.augment_ids.includes(row.augment_id)) return "";
  const cap = forgeCapacity(f);
  if (cap.complexity + (Number(row.complexity) || 0) > f.max_complexity) return `This Realm's Complexity maximum is ${f.max_complexity}; this would make ${cap.complexity + (Number(row.complexity) || 0)}.`;
  return "";
}

function forgeStatus(f) {
  const cap = forgeCapacity(f);
  return `Complexity ${cap.complexity} of ${f.max_complexity} · ${cap.spheres} of ${f.max_spheres} Spheres`;
}

// Secondaries grouped by Sphere (Sphere name, then talent name), so the list reads by Sphere.
function secondaryGroups(f, rows, chipFor) {
  const bySphere = new Map();
  for (const row of rows) {
    if (!bySphere.has(row.sphere)) bySphere.set(row.sphere, []);
    bySphere.get(row.sphere).push(row);
  }
  return [...bySphere.keys()].sort((a, b) => String(a).localeCompare(String(b))).flatMap((sphere) => [
    deps.h("div", { class: "def-note grow-sphere-head", dataset: { forgeSphereHead: sphere } }, sphere),
    deps.h("div", { class: "grow-chips", dataset: { forgeSphere: sphere } }, ...bySphere.get(sphere).sort((a, b) => String(a.name).localeCompare(String(b.name))).map(chipFor)),
  ]);
}

function forgeChoiceRows() {
  const { h } = deps;
  return Object.entries((data.forge || {}).choices || {}).filter(([key]) => forge.augment_ids.includes(key)).map(([key, values]) => {
    const options = values.map((value) =>
      h("option", { value, selected: forge.choices[key] === value || null }, value.replace(/_/g, " ")));
    return h("div", { class: "powering-row" }, h("span", null, key.replace(/_/g, " ")),
      h("select", { class: "input", dataset: { forgeChoice: key } }, ...options));
  });
}

function goldenCoreBlock() {
  const { h } = deps;
  // The rule is the Qi plug-in's (combat/ext/qi_path.py). The server lists the recorded Forms and each legal choice with its reason.
  const panel = (data.build_choices || {}).golden_core || { owned: false, forms: [], options: [] };
  // Only a character that owns the Golden Core Form feature gets this block (the panel says so; no false combat claim for others).
  if (!panel.owned) return null;
  const names = { stable: "Stable Golden Core", circulating: "Circulating Golden Core", reservoir: "Golden Core Reservoir" };
  const source = (row) => (row.source === "sheet" ? "on your sheet" : `recorded at cultivation level ${row.cl}`);
  const recorded = panel.forms.map((row) => `${names[row.id] || row.id} (${source(row)})`);
  const replacing = panel.forms.some((row) => row.slot === 1);
  // Every disabled option's reason, once each, so no refusal is hidden behind the first one in its slot.
  const reasons = [...new Set(panel.options.filter((o) => !o.allowed).map((o) => o.reason).filter(Boolean))];
  // Each choice states what it does and what it becomes at Cultivation Level 17, so a permanent
  // choice is never made blind. Only the Form currently being chosen for a free slot is spelled out.
  const choosing = new Set(panel.options.filter((o) => o.allowed).map((o) => o.id));
  const optionRow = (o) => h("div", { class: "grow-form" },
    h("button", {
      type: "button", class: "btn", disabled: busy || !o.allowed || null,
      dataset: { growGoldenForm: o.id, slot: String(o.slot) }, title: o.reason,
    }, `${o.slot === 1 ? (replacing ? "Replace first with " : "Choose first: ") : "Choose second: "}${o.name}`),
    choosing.has(o.id) && o.benefit
      ? h("p", { class: "def-note grow-form-why" }, `${o.benefit}${o.perfected ? ` ${o.perfected}` : ""}`)
      : null);
  return h("details", { class: "def-block def-details", id: "grow-golden-core", open: true },
    h("summary", null, h("span", { class: "def-label" }, "Golden Core Forms")),
    recorded.length ? h("p", { class: "def-note" }, `Recorded Form${recorded.length > 1 ? "s" : ""}: ${recorded.join(" and ")}. These are fixed for combat.`)
      : h("p", { class: "def-note" }, "No Form is recorded yet, so you hold no Golden Core Form in combat until you choose one."),
    // Each recorded Form says what it does in plain words: when it recovers Qi, how often, its costs and its Perfected benefit.
    ...panel.forms.filter((row) => row.benefit).map((row) => h("p", { class: "def-note grow-form-why" },
      `${names[row.id] || row.id}: ${row.benefit}${row.perfected ? ` ${row.perfected}` : ""}`)),
    h("div", { class: "grow-list" }, ...panel.options.map(optionRow)),
    reasons.length ? h("p", { class: "def-note" }, reasons.join(" ")) : null,
    panel.breakthrough && !panel.breakthrough.recorded
      ? h("button", { type: "button", class: "btn", disabled: busy || null, dataset: { growBreakthrough: String(panel.breakthrough.cl) }, title: "Record the successful breakthrough to unlock the replacement" }, "Record breakthrough at Cultivation Level 15")
      : null,
    panel.nascent_used
      ? h("p", { class: "def-note" }, "You have used your Nascent Soul feature, so the printed window to replace your first Form is closed. Your Form stays as it is.")
      : panel.cl === 15 && recorded.length && !panel.nascent_used
        ? h("button", { type: "button", class: "btn", disabled: busy || null,
            dataset: { growFeatureUse: panel.nascent_feature_id }, title: "Recording this closes the printed window to replace your first Form" },
            "I have used my Nascent Soul feature this campaign")
        : null);
}

function learningFields(row) {
  const { h } = deps;
  return h("span", null, ...(row.learning_choices || []).map((choice) => h("label", null, choice.label,
    h("select", { class: "input", dataset: { learningRecord: row.id, learningChoice: choice.id } },
      h("option", { value: "" }, "Choose…"),
      ...choice.options.map((o) => h("option", { value: o.id,
        selected: learning[row.id]?.[choice.id] === o.id || null }, o.name))))));
}

function forgeBlock() {
  const { h, $ } = deps;
  const f = data.forge || {};
  if (!f.available) {
    return h("details", { class: "def-block def-details" }, h("summary", null, h("span", { class: "def-label" }, "Forge a technique")),
      h("p", { class: "def-note" }, `Technique Forging opens at CL ${f.minimum_cl || 5} (Foundation).`));
  }
  const form = (f.forms || []).find((row) => row.form_id === forge.base_form);
  const primary = (f.sources || []).find((row) => row.id === forge.primary_talent_id);
  const secondaries = f.sources || [];
  const option = (value, label, on) => h("option", { value, selected: on || null }, label);
  const chips = (kind, rows, picked, label, extra) => h("div", { class: "grow-chips" }, ...rows.map((row) => {
    const reason = label.grey ? label.grey(row) : "";
    return h("label", { class: "grow-chip", title: reason || extra?.(row) || "" },
      h("input", { type: "checkbox", dataset: { forgePick: kind, id: row[label.id] }, checked: picked.includes(row[label.id]) || null,
                   disabled: ((row.legal === false && !gm()) || reason) || null }),
      ` ${row[label.name]}${label.cost ? ` (${label.cost(row)})` : ""}`);
  }));
  const secondaryChip = (row) => {
    const reason = secondaryGrey(f, row);
    return h("label", { class: "grow-chip", title: reason || row.sphere,
                        hidden: !primary || row.sphere_id === primary.sphere_id || !forgeFit(f, row.id)[0] || null },
      h("input", { type: "checkbox", dataset: { forgePick: "secondary", id: row.id }, checked: forge.secondary_talent_ids.includes(row.id) || null,
                   disabled: reason ? true : null }),
      ` ${row.name}${row.kind === "base_ability" ? " (base ability)" : ""}`);
  };
  // Hidden: they don't work with this Base Form. Only the GM override shows them, in their own group.
  const hidden = secondaries.filter((row) => primary && row.sphere_id !== primary.sphere_id && !forgeFit(f, row.id)[0]);
  const hiddenNote = form && hidden.length && !gm()
    ? (hidden.length === 1 ? `1 effect hidden: it doesn't work with a ${form.display_name}.` : `${hidden.length} effects hidden: they don't work with a ${form.display_name}.`)
    : "";
  const result = preview?.error ? h("p", { class: "def-note grow-error" }, preview.error)
    : preview ? h("div", { class: "grow-preview" },
      h("div", null, h("strong", null, preview.technique.name), ` — ${preview.technique.base_form.display_name}, `,
        `${preview.technique.cp_cost.final} CP, Complexity ${preview.technique.complexity.final} of ${preview.technique.complexity.realm_maximum}, `,
        `${preview.technique.action_type}, forging DC ${preview.technique.technique_forging_dc}`),
      preview.combat ? h("ul", { class: "grow-effects" },
        h("li", null, [preview.combat.range && `Range ${preview.combat.range}`, preview.combat.area, preview.combat.duration].filter(Boolean).join(" · ")),
        ...(preview.combat.effects || []).map((line) => h("li", null, line)),
        ...(preview.combat.gm || []).map((line) => h("li", { class: "def-note" }, `GM: ${line}`))) : null,
      h("button", { type: "button", class: "btn btn-accent", disabled: busy || null, dataset: { forgeSave: "1" } }, "Add to character"))
    : null;
  return h("details", { class: "def-block def-details", id: "grow-forge", open: $("grow-forge")?.open ?? true },
    h("summary", null, h("span", { class: "def-label" }, `Forge a technique (${f.known} of ${f.limit} known · Complexity up to ${f.max_complexity} · up to ${f.max_spheres} Spheres)`)),
    h("div", { class: "powering-rows" },
      h("div", { class: "powering-row" }, h("span", null, "Name"),
        h("input", { class: "input", id: "forge-name", maxlength: "80", placeholder: "(the Forge names it)", value: forge.name })),
      h("div", { class: "powering-row" }, h("span", null, "Base Form"),
        h("select", { class: "input", id: "forge-form" }, option("", "—", !forge.base_form),
          ...(f.forms || []).map((row) => option(row.form_id, `${row.display_name} (Complexity ${row.complexity}, ${row.starting_cp} CP) — ${row.use}`, row.form_id === forge.base_form)))),
      h("div", { class: "powering-row" }, h("span", null, "Primary Sphere Effect"),
        h("select", { class: "input", id: "forge-primary" }, option("", "—", !forge.primary_talent_id),
          ...(f.sources || []).map((row) => option(row.id, `${row.name}${row.kind === "base_ability" ? " (base ability)" : ""} (${row.sphere})`, row.id === forge.primary_talent_id))))),
    h("div", { id: "grow-forge-secondaries", hidden: !primary || null },
      h("div", { class: "def-label" }, "Secondary Sphere Effects (+1 Complexity each, one per Sphere)"),
      h("p", { class: "def-note", id: "grow-forge-status" }, forgeStatus(f)),
      ...secondaryGroups(f, secondaries, secondaryChip),
      h("p", { class: "def-note", id: "grow-forge-hidden", hidden: !hiddenNote || null }, hiddenNote),
      h("div", { id: "grow-forge-gm", hidden: !gm() || !hidden.length || null },
        h("div", { class: "def-label" }, "Doesn't fit this Base Form (GM)"),
        h("div", { class: "grow-chips", id: "grow-forge-gm-chips" }))),
    h("div", { class: "def-label" }, "Augments"),
    chips("augment", f.augments || [], forge.augment_ids, { id: "augment_id", name: "display_name", cost: (row) => `+${row.complexity} Complexity, +${row.cp} CP`, grey: (row) => augmentGrey(f, row) },
      (row) => row.legal === false ? `Needs ${row.minimum_realm}` : row.tier),
    h("div", { id: "grow-forge-choices", dataset: { choiceKey: Object.keys(f.choices || {}).filter((key) => forge.augment_ids.includes(key)).join(",") } }, ...forgeChoiceRows()),
    h("div", { class: "def-label" }, "Drawbacks"),
    chips("drawback", f.drawbacks || [], forge.drawback_ids, { id: "drawback_id", name: "display_name", cost: (row) => `−${row.cp_reduction} CP` }, (row) => row.restriction),
    h("div", { class: "powering-row" },
      h("span", { class: "def-note", id: "grow-forge-use" }, form ? form.use : "Choose a Base Form and a Primary Sphere Effect."),
      h("button", { type: "button", class: "btn", disabled: !form || !primary || busy || null, dataset: { forgePreview: "1" } }, "Check")),
    h("div", { id: "grow-forge-preview" }, result));
}

// In-place update after a chip click: no re-render of the Grow page. Returns false when the DOM is not there.
function refreshForgeInPlace() {
  const f = data.forge || {};
  const root = deps.$("grow-forge");
  if (!root || !root.querySelectorAll) return false;
  const sources = new Map((f.sources || []).map((row) => [row.id, row]));
  const primary = sources.get(forge.primary_talent_id);
  const form = (f.forms || []).find((row) => row.form_id === forge.base_form);
  const groups = new Map([...root.querySelectorAll("[data-forge-sphere]")].map((el) => [el.dataset.forgeSphere, el]));
  const gmChips = deps.$("grow-forge-gm-chips");
  let hiddenCount = 0;
  for (const input of root.querySelectorAll("input[data-forge-pick]")) {
    const id = input.dataset.id;
    const kind = input.dataset.forgePick;
    if (kind === "secondary") {
      const row = sources.get(id);
      const eligible = Boolean(row && primary && row.sphere_id !== primary.sphere_id);
      const [fits, fitReason] = forgeFit(f, id);
      if (eligible && !fits) hiddenCount++;
      const reason = row ? secondaryGrey(f, row) : "";
      input.checked = forge.secondary_talent_ids.includes(id);
      input.disabled = Boolean(reason);
      const label = input.parentElement;
      if (label && row) {
        label.title = !fits ? fitReason : reason || row.sphere;
        if (label.dataset) label.dataset.tip = label.title;
        label.hidden = !eligible || (!fits && !gm());
        const container = !fits && gm() ? gmChips : groups.get(row.sphere);
        if (container && label.parentElement !== container) container.appendChild(label);
      }
    } else if (kind === "augment") {
      const row = (f.augments || []).find((x) => x.augment_id === id);
      const reason = row ? augmentGrey(f, row) : "";
      input.checked = forge.augment_ids.includes(id);
      input.disabled = Boolean((row && row.legal === false && !gm()) || reason);
      if (input.parentElement) {
        input.parentElement.title = reason || (row?.legal === false ? `Needs ${row.minimum_realm}` : row?.tier || "");
        if (input.parentElement.dataset) input.parentElement.dataset.tip = input.parentElement.title;
      }
    } else {
      input.checked = forge.drawback_ids.includes(id);
    }
  }
  const choices = deps.$("grow-forge-choices");
  const choiceKey = Object.keys(f.choices || {}).filter((key) => forge.augment_ids.includes(key)).join(",");
  if (choices && choices.replaceChildren && choices.dataset.choiceKey !== choiceKey) {
    choices.replaceChildren(...forgeChoiceRows());
    choices.dataset.choiceKey = choiceKey;
  }
  for (const head of root.querySelectorAll("[data-forge-sphere-head]")) {
    const group = groups.get(head.dataset.forgeSphereHead);
    const empty = !group || ![...group.children].some((label) => !label.hidden);
    head.hidden = empty;
    if (group) group.hidden = empty;
  }
  const section = deps.$("grow-forge-secondaries");
  if (section) section.hidden = !primary;
  const note = deps.$("grow-forge-hidden");
  if (note) {
    note.hidden = !form || !hiddenCount || gm();
    note.textContent = !form ? "" : hiddenCount === 1
      ? `1 effect hidden: it doesn't work with a ${form.display_name}.`
      : `${hiddenCount} effects hidden: they don't work with a ${form.display_name}.`;
  }
  const gmGroup = deps.$("grow-forge-gm");
  if (gmGroup) gmGroup.hidden = !gm() || !hiddenCount;
  const status = deps.$("grow-forge-status");
  if (status) status.textContent = forgeStatus(f);
  const use = deps.$("grow-forge-use");
  if (use) use.textContent = form ? form.use : "Choose a Base Form and a Primary Sphere Effect.";
  const check = root.querySelector("[data-forge-preview]");
  if (check) check.disabled = !form || !primary || busy;
  if (!preview) deps.$("grow-forge-preview")?.replaceChildren();
  return true;
}

function design() {
  return { name: forge.name.trim() || null, base_form: forge.base_form, primary_talent_id: forge.primary_talent_id,
           secondary_talent_ids: forge.secondary_talent_ids, augment_ids: forge.augment_ids, drawback_ids: forge.drawback_ids,
           choices: Object.fromEntries(Object.entries(forge.choices).filter(([key]) => forge.augment_ids.includes(key))) };
}

async function run(label, call, after) {
  busy = true;
  render();
  try {
    const result = await call();
    if (after) await after(result);
  } catch (error) {
    deps.toast("error", label, error.message, 4200);
  } finally {
    busy = false;
    render();
  }
}

function onClick(event) {
  const t = event.target;
  const methodAction=t.closest("[data-method-action]")?.dataset.methodAction;
  if (methodAction) {
    void run("Method change not recorded",()=>post("advancement/method"+(methodAction === "undo" ? "/undo" : ""),
      methodAction === "undo" ? {} : {...methodDraft,gm:gm(),save:methodAction === "save"}),async result=>{
        if (methodAction === "preview") methodPreview=result;
        else {
          data=result;methodPreview=null;methodDraft={method_id:"",source:"",note:"",opportunity:"",completed:false};
          levelDraft={target:null,rows:{},filters:{},addPath:{path_id:"",access:"",source_id:"",confirmed:false}};
          await deps.refreshSheet();deps.invalidateLibrary();
        }
      });
    return;
  }
  if (t.closest("[data-level-save]") || t.closest("[data-level-undo]")) {
    const undo=Boolean(t.closest("[data-level-undo]"));
    const a=levelDraft.addPath;
    const levels=levelPlan().map(({d}) => ({...d, changes:d.advancement === "insight" ? {} : d.changes}));
    if (a.path_id && levels.length) {
      const first=levels[0];
      // The recorded Method is the only legal Primary Method source, so fill its id here even if the draft was stale.
      if (a.access === "primary_method") a.source_id=data.level_up?.primary_method?.id || "";
      Object.assign(first,{add_path_id:a.path_id,add_access:a.access,add_source_id:a.source_id,add_confirmed:Boolean(a.confirmed)});
    }
    busy=true; patchLevelPanel();
    void (async () => {
      let applied=false;
      try {
        data=await post(undo ? "advancement/level/undo" : "advancement/level",undo ? {} : {cl:levels[0].cl,levels});
        levelDraft={target:null,rows:{},filters:{},addPath:{path_id:"",access:"",source_id:"",confirmed:false}};
        await deps.reloadSheet();
        applied=true;
        deps.toast("ok",undo ? "Last level undone" : "Level up recorded","The sheet and new fights use this growth record.",2600);
      } catch (error) {deps.toast("error","Level not recorded",error.message,4200);}
      finally {busy=false;if (applied) render(true);else patchLevelPanel();}
    })();
    return;
  }
  const insight = t.closest("[data-grow-insight]");
  if (insight) {
    void run("Insight not recorded", () => post("advancement/insight", {
      record_id: insight.dataset.growInsight, note: insightDraft.note, choice: insightDraft.choice, gm: gm()
    }), async (result) => { data = result; await deps.reloadSheet(); });
    return;
  }
  if (t.closest("[data-grow-art-check]")) {
    void run("Art is not valid", () => post("advancement/immortal-art", { design: artDraft }),
      (result) => { artPreview = result; });
    return;
  }
  if (t.closest("[data-grow-art-save]")) {
    void run("Art not recorded", () => post("advancement/immortal-art", {
      design: artDraft, note: artNote, proof: artProof, save: true
    }), async (result) => { data = result.advancement; artPreview = null; await deps.reloadSheet(); });
    return;
  }
  const add = t.closest("[data-grow-add]");
  if (add) {
    void run("Not added", () => post("advancement", { kind: add.dataset.growAdd, record_id: add.dataset.id, gm: gm(), source: learningSource, learning_choices: learning[add.dataset.id] || {} }), async (result) => {
      data = result;
      await deps.reloadSheet();
      deps.toast("ok", "Learned", "New fights use it.", 2200);
    });
    return;
  }
  const golden = t.closest("[data-grow-golden-form]");
  if (golden) {
    void run("Form not recorded", () => post("advancement/golden-core", { form: golden.dataset.growGoldenForm, slot: Number(golden.dataset.slot) }), async (result) => {
      data = result;
      await deps.reloadSheet();
      deps.toast("ok", "Golden Core Form recorded", "New fights use this fixed Form.", 2400);
    });
    return;
  }
  const breakthrough = t.closest("[data-grow-breakthrough]");
  if (breakthrough) {
    void run("Breakthrough not recorded", () => post("advancement/breakthrough", { cl: Number(breakthrough.dataset.growBreakthrough) }), async (result) => {
      data = result;
      await deps.reloadSheet();
      deps.toast("ok", "Breakthrough recorded", "You can now replace your first Form.", 2400);
    });
    return;
  }
  const featureUse = t.closest("[data-grow-feature-use]");
  if (featureUse) {
    void run("Feature use not recorded", () => post("advancement/feature-use", { feature_id: featureUse.dataset.growFeatureUse }), async (result) => {
      data = result;
      await deps.reloadSheet();
      deps.toast("ok", "Recorded", "The printed window to replace your first Form is now closed.", 2400);
    });
    return;
  }
  const abilityMode = t.closest("[data-grow-ability-mode]");
  if (abilityMode) {
    abilityDraft = { mode: abilityMode.dataset.growAbilityMode, values: {} };
    render();
    return;
  }
  if (t.closest("[data-grow-ability-spread]")) {
    abilityDraft = { mode: "gm_respec", values: { ...((data.ability_panel || {}).default_spread || {}) } };
    render();
    return;
  }
  if (t.closest("[data-grow-ability-save]")) {
    const pv = abilityPreview();
    const values = { ...abilityDefaults(), ...abilityDraft.values };
    const changes = Object.fromEntries(ABILITY_ORDER.map((a) => [a, Number(values[a]) || 0]));
    const body = abilityDraft.mode === "gm_respec"
      ? { reason: "gm_respec", changes, cl: data.cl, note: "", gm: gm() }
      : { reason: "level_increase", changes: Object.fromEntries(Object.entries(changes).filter(([, v]) => v)), cl: data.cl, note: "", gm: gm() };
    void run("Not recorded", () => post("advancement/ability", body), async (result) => {
      data = result;
      abilityDraft = { mode: abilityDraft.mode, values: {} };
      await deps.reloadSheet();
      deps.toast(pv.legal ? "ok" : "warn", "Ability scores recorded", "The sheet and new fights use the new scores.", 2600);
    });
    return;
  }
  const abilityRemove = t.closest("[data-grow-ability-remove]");
  if (abilityRemove) {
    void run("Not removed", () => post("advancement/remove", { kind: "ability", record_id: abilityRemove.dataset.growAbilityRemove }), async (result) => {
      data = result;
      await deps.reloadSheet();
    });
    return;
  }
  const remove = t.closest("[data-grow-remove]");
  if (remove) {
    void run("Not removed", () => post("advancement/remove", { kind: remove.dataset.growRemove, record_id: remove.dataset.id }), async (result) => {
      data = result;
      await deps.reloadSheet();
    });
    return;
  }
  if (t.closest("[data-forge-preview]")) {
    void run("Not forged", async () => {
      try {
        preview = await post("forge", { design: design(), gm: gm(), save: false, source: learningSource });
      } catch (error) {
        preview = { error: error.message };
      }
    });
    return;
  }
  if (t.closest("[data-forge-save]")) {
    void run("Not forged", () => post("forge", { design: design(), gm: gm(), save: true, source: learningSource }), async (result) => {
      data = result.advancement;
      preview = null;
      forge = { name: "", base_form: "", primary_talent_id: "", secondary_talent_ids: [], augment_ids: [], drawback_ids: [], choices: {} };
      await deps.reloadSheet();
      deps.toast("ok", `${result.technique.name} forged`, "It is on the Actions tab and in new fights.", 2600);
    });
  }
}

function onChange(event) {
  if (event.target.dataset.methodField) {
    const t=event.target;methodDraft[t.dataset.methodField]=t.type === "checkbox" ? t.checked : t.value;
    methodPreview=null;render(true);return;
  }
  const t = event.target;
  if (t.dataset.learningRecord) {
    const id = t.dataset.learningRecord;
    learning[id] ||= {};
    learning[id][t.dataset.learningChoice] = t.value;
    void run("Could not update learning choices", () => post("learning-preview", {
      kind: "sphere", record_id: id, learning_choices: learning[id],
    }), (result) => {
      const row = [...data.spheres, ...data.talents].find((r) => r.id === id);
      if (row) row.learning_choices = result.learning_choices;
      const keys = new Set(result.learning_choices.map((choice) => choice.id));
      learning[id] = Object.fromEntries(Object.entries(learning[id]).filter(([key]) => keys.has(key)));
    });
    return;
  }
  if (t.id === "grow-source") { learningSource = t.value; return; }
  if (t.id === "level-target") {levelDraft.target=Number(t.value);patchLevelPanel();return;}
  if (t.dataset.levelAddPath) {
    const key=t.dataset.levelAddPath;
    levelDraft.addPath[key]=key === "confirmed" ? t.checked : t.value;
    // A Primary Method grant is the recorded Method itself: send its id automatically, never a typed one.
    if (key === "access") levelDraft.addPath.source_id=t.value === "primary_method" ? (data.level_up?.primary_method?.id || "") : "";
    patchLevelPanel();return;
  }
  if (t.dataset.levelLegal) {
    const id=t.dataset.levelLegal;
    levelDraft.filters[id] ||= {q:"",legal:true};
    levelDraft.filters[id].legal=t.checked;
    filterLevelList(id);return;
  }
  if (t.dataset.levelPick) {
    const d=levelDraft.rows[t.dataset.levelCl], key=t.dataset.levelPick;
    if (key === "talent") d.talent_ids=t.type === "radio" ? [t.value] : t.checked ? [...new Set([...d.talent_ids,t.value])] : d.talent_ids.filter((id) => id !== t.value);
    else if (key.startsWith("subpath:")) d.subpaths[key.slice(8)]=t.value;
    else if (key.startsWith("feature:")) d.feature_choices[key.slice(8)]=t.value;
    else if (key === "foundation") {d.foundation_id=t.value;delete d.foundation_initial_stage;}
    else if (key === "foundationStage") d.foundation_initial_stage=t.value;
    else if (key === "ability") d.changes=JSON.parse(t.value);
    else if (key === "insight") {d.insight_id=t.value;d.insight_ability="";d.insight_choice="";}
    else if (key === "insightAbility") d.insight_ability=t.value;
    else if (key === "insightChoice") d.insight_choice=t.value;
    else if (key === "advancement") d.advancement=t.value;
    patchLevelPanel();return;
  }
  if (t.dataset.levelText) {
    levelDraft.rows[t.dataset.levelCl][t.dataset.levelText]=t.type === "checkbox" ? t.checked : t.value;
    return;
  }
  if (t.id === "grow-gm") { methodPreview=null;render(); return; }
  if (t.id === "grow-art-source" || t.id === "grow-art-aspect") {
    artDraft[t.id === "grow-art-source" ? "source_record_id" : "aspect_id"] = t.value;
    artDraft.factor_ids = []; artDraft.burdens = []; artPreview = null; render(); return;
  }
  if (t.dataset.growArtPick) {
    const key = t.dataset.growArtPick;
    artDraft[key] = t.checked ? [...artDraft[key], t.dataset.id] : artDraft[key].filter((id) => id !== t.dataset.id);
    artPreview = null; render(); return;
  }
  if (t.id === "grow-legal-only") { query.legalOnly = t.checked; render(); return; }
  if (t.id === "forge-form") {
    forge.base_form = t.value;
    // A Secondary that no longer fits the new Base Form is dropped from the design, not kept invisibly.
    if (!gm()) forge.secondary_talent_ids = forge.secondary_talent_ids.filter((id) => forgeFit(data.forge || {}, id)[0]);
    preview = null; refreshForgeInPlace(); return;
  }
  if (t.id === "forge-primary") {
    forge.primary_talent_id = t.value;
    forge.secondary_talent_ids = [];
    preview = null;
    refreshForgeInPlace();
    return;
  }
  if (t.dataset.forgeChoice) { forge.choices[t.dataset.forgeChoice] = t.value; preview = null; refreshForgeInPlace(); return; }
  if (t.dataset.forgePick) {
    const key = { secondary: "secondary_talent_ids", augment: "augment_ids", drawback: "drawback_ids" }[t.dataset.forgePick];
    const id = t.dataset.id;
    forge[key] = t.checked ? [...forge[key].filter((x) => x !== id), id] : forge[key].filter((x) => x !== id);
    if (key === "secondary_talent_ids" && t.checked) {
      // One effect per Sphere: a second pick from the same Sphere replaces the first.
      const sphere = (data.forge.sources || []).find((row) => row.id === id)?.sphere_id;
      forge[key] = forge[key].filter((x) => x === id || (data.forge.sources || []).find((row) => row.id === x)?.sphere_id !== sphere);
    }
    // All Forge edits, including the first edit after Check, preserve the mounted controls.
    preview = null;
    refreshForgeInPlace();
  }
}

let typing = 0;
function onInput(event) {
  if (event.target.dataset.methodField) {
    methodDraft[event.target.dataset.methodField]=event.target.value;methodPreview=null;
    const panel=deps.$("grow-method");if(panel) patchGrowNode(panel,methodBlock());return;
  }
  if (event.target.dataset.levelFilter) {
    const t=event.target,id=t.dataset.levelFilter;
    levelDraft.filters[id] ||= {q:"",legal:true};
    levelDraft.filters[id].q=t.value;filterLevelList(id);return;
  }
  if (event.target.dataset.levelText) {
    levelDraft.rows[event.target.dataset.levelCl][event.target.dataset.levelText]=event.target.value;return;
  }
  if (event.target.dataset.levelAddPath === "source_id") {
    levelDraft.addPath.source_id=event.target.value;return;
  }
  const ab = event.target.dataset && event.target.dataset.growAbility;
  if (ab) {
    const id = event.target.id;
    const start = event.target.selectionStart;
    const end = event.target.selectionEnd;
    abilityDraft.values = { ...abilityDraft.values, [ab]: Number(event.target.value) || 0 };
    render();
    const input = deps.$(id);
    if (input) {
      input.focus();
      if (input.type === "text") input.setSelectionRange(start, end);
    }
    return;
  }
  const t = event.target;
  if (t.id === "grow-insight-note") { insightDraft.note = t.value; return; }
  if (t.id === "grow-insight-choice") { insightDraft.choice = t.value; return; }
  if (t.id === "grow-insight-q") {
    insightDraft.query = t.value;
    clearTimeout(typing);
    typing = setTimeout(() => { const at = t.selectionStart; render(); const again = deps.$("grow-insight-q");
      if (again) { again.focus(); again.setSelectionRange(at, at); } }, 150);
    return;
  }
  if (t.id === "grow-art-name") { artDraft.name = t.value; artPreview = null; return; }
  if (t.id === "grow-art-note") { artNote = t.value; return; }
  const proofField = { "grow-art-die": "die", "grow-art-hours": "research_hours", "grow-art-gp": "materials_gp" }[t.id];
  if (proofField) { artProof[proofField] = Number(t.value); return; }
  if (t.id === "forge-name") { forge.name = t.value; preview = null; deps.$("grow-forge-preview")?.replaceChildren(); return; }
  if (t.id === "grow-sphere-q" || t.id === "grow-talent-q") {
    query[t.id === "grow-sphere-q" ? "sphere" : "talent"] = t.value;
    clearTimeout(typing);
    typing = setTimeout(() => {
      const id = t.id, at = t.selectionStart;
      render();
      const again = deps.$(id);
      if (again) { again.focus(); again.setSelectionRange(at, at); }
    }, 150);
  }
}
