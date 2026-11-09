(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.TianxiaSheetViewModel = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  // Normalized working names that must never win over a real finalized name.
  // "AI-proposed character" is the literal stored working_name of delegated-name
  // projects; it stays a builder-status label only.
  const PLACEHOLDER_NAMES = Object.freeze(["", "ai-proposed character", "unnamed character"]);

  function normalizeName(value) {
    return typeof value === "string" ? value.trim() : "";
  }

  function isPlaceholderName(value) {
    return PLACEHOLDER_NAMES.includes(normalizeName(value).toLowerCase());
  }

  /**
   * Deterministic final-name precedence for the Character Sheets library and
   * sheet header. Inputs arrive from payloads the Factory already returns:
   * - characterListName: GET /api/characters row `name` (the server already
   *   overlays the resolved workflow identity name onto placeholder names).
   * - resolvedWorkflowName: workflow.latest_run.owner_descriptive_fields
   *     .resolved.identity.name joined client-side when available.
   * - libraryName: GET /api/character-library row `name` (projects.working_name).
   * The first non-placeholder candidate wins; otherwise the empty string is
   * returned so callers can render an honest unnamed state without inventing one.
   */
  function resolveOwnerFinalName(inputs) {
    const source = inputs && typeof inputs === "object" ? inputs : {};
    for (const candidate of [source.characterListName, source.resolvedWorkflowName, source.libraryName]) {
      if (isPlaceholderName(candidate)) continue;
      return normalizeName(candidate);
    }
    return "";
  }

  function signed(value) {
    const num = Number(value);
    if (!Number.isFinite(num)) return null;
    return num >= 0 ? `+${num}` : String(num);
  }

  function firstNonEmpty(values) {
    for (const value of values) {
      if (value !== null && value !== undefined && value !== "") return value;
    }
    return null;
  }

  function readableLabel(value) {
    const text = normalizeName(value).replace(/[_.-]+/g, " ").replace(/\s+/g, " ");
    if (!text) return "";
    return text.replace(/\b\w/g, letter => letter.toUpperCase());
  }

  const COMPLETE_CHARACTER_SURFACE_IDS = Object.freeze([
    "overview_core_stats",
    "leveling",
    "background",
    "paths_subpaths",
    "spheres_talents",
    "insights",
    "actions",
    "forged_techniques",
    "manuals_recorded_arts",
    "immortal_arts",
    "foundation",
    "method",
    "companions",
    "equipment",
    "resources_states_suppression",
    "dao_i_ching",
    "diagnostics",
  ]);

  const COMPLETE_CHARACTER_SURFACE_LABELS = Object.freeze({
    overview_core_stats: "Overview & Core Stats",
    leveling: "Leveling",
    background: "Background",
    paths_subpaths: "Paths & Subpaths",
    spheres_talents: "Spheres & Talents",
    insights: "Insights",
    actions: "Actions",
    forged_techniques: "Forged Techniques",
    manuals_recorded_arts: "Manuals & Recorded Arts",
    immortal_arts: "Immortal Arts",
    foundation: "Foundation",
    method: "Method",
    companions: "Companions",
    equipment: "Equipment",
    resources_states_suppression: "Resources, States & Suppression",
    dao_i_ching: "Dao & I Ching",
    diagnostics: "Diagnostics",
  });

  function buildCompleteCharacterViewModel(envelope) {
    if (!envelope || typeof envelope !== "object" || Array.isArray(envelope)) return null;
    const rawSurfaces = envelope.surfaces && typeof envelope.surfaces === "object" && !Array.isArray(envelope.surfaces)
      ? envelope.surfaces
      : {};
    const rawCoverage = envelope.coverage && typeof envelope.coverage === "object" ? envelope.coverage : {};
    const missingIds = Array.isArray(rawCoverage.missing_ids)
      ? rawCoverage.missing_ids.filter(id => COMPLETE_CHARACTER_SURFACE_IDS.includes(id))
      : COMPLETE_CHARACTER_SURFACE_IDS.filter(id => rawSurfaces[id]?.available !== true);
    const availableCount = Number.isFinite(Number(rawCoverage.available_count))
      ? Number(rawCoverage.available_count)
      : COMPLETE_CHARACTER_SURFACE_IDS.length - missingIds.length;
    const requiredCount = Number.isFinite(Number(rawCoverage.required_count))
      ? Number(rawCoverage.required_count)
      : COMPLETE_CHARACTER_SURFACE_IDS.length;
    const surfaces = {};
    for (const id of COMPLETE_CHARACTER_SURFACE_IDS) {
      const source = rawSurfaces[id] && typeof rawSurfaces[id] === "object" ? rawSurfaces[id] : {};
      surfaces[id] = {
        id,
        label: COMPLETE_CHARACTER_SURFACE_LABELS[id],
        available: envelope.available === true && source.available === true,
        status: normalizeName(source.status) || (source.available === true ? "available" : "unavailable"),
        data: source.data === undefined ? null : source.data,
        reason: normalizeName(source.reason),
      };
    }
    const sourceKind = envelope.source_kind === "candidate" || envelope.source_kind === "finalized"
      ? envelope.source_kind
      : null;
    return {
      available: envelope.available === true,
      sourceKind,
      finalized: envelope.finalized === true,
      sourceLabel: sourceKind === "finalized"
        ? "Verified finalized portable package"
        : sourceKind === "candidate"
          ? "Verified current Command 5 candidate"
          : "Verified source unavailable",
      coverage: {
        requiredCount,
        availableCount,
        missingIds,
        complete: rawCoverage.complete === true && missingIds.length === 0,
      },
      reason: normalizeName(envelope.reason),
      surfaces,
    };
  }

  function presentationText(value) {
    if (typeof value === "string" || typeof value === "number") return String(value).trim();
    return "";
  }

  function noteEntry(value) {
    if (typeof value === "string" || typeof value === "number") {
      const summary = presentationText(value);
      return summary ? {name: "Note", summary, quantity: null, category: null} : null;
    }
    if (!value || typeof value !== "object") return null;
    const summary = presentationText(firstNonEmpty([
      value.text, value.note, value.notes, value.summary, value.description, value.content,
    ]));
    const name = presentationText(firstNonEmpty([value.title, value.label, value.name])) || "Note";
    if (!summary && name === "Note") return null;
    return {name, summary, quantity: null, category: null};
  }

  function gearEntry(value, sourceLabel) {
    if (typeof value === "string" || typeof value === "number") {
      const name = presentationText(value);
      return name ? {name, summary: "", quantity: null, category: sourceLabel} : null;
    }
    if (!value || typeof value !== "object") return null;
    // Raw record IDs and provenance are intentionally not presentation fallbacks.
    // Records without a human-facing name remain available in Advanced / Developer.
    const name = presentationText(firstNonEmpty([
      value.display_name, value.name, value.title, value.label, value.item_name, value.equipment_name,
    ]));
    if (!name) return null;
    const summary = presentationText(firstNonEmpty([
      value.one_line_description, value.summary, value.description, value.note, value.notes,
    ]));
    const quantityValue = firstNonEmpty([value.quantity, value.count, value.amount]);
    const quantity = quantityValue === null ? null : presentationText(quantityValue);
    const categoryValue = presentationText(firstNonEmpty([value.category, value.type, value.kind]));
    return {
      name,
      summary,
      quantity: quantity || null,
      category: categoryValue ? readableLabel(categoryValue) : sourceLabel,
    };
  }

  function asRows(value) {
    if (Array.isArray(value)) return value;
    return value === null || value === undefined || value === "" ? [] : [value];
  }

  function uniquePresentationEntries(rows) {
    const seen = new Set();
    return rows.filter(row => {
      if (!row) return false;
      const key = [row.name, row.summary, row.quantity, row.category].map(value => String(value || "").toLowerCase()).join("|");
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  }

  function notesGear(snapshot) {
    const surface = snapshot && typeof snapshot === "object" ? snapshot : {};
    const selected = surface.selected_record_sections && typeof surface.selected_record_sections === "object"
      ? surface.selected_record_sections
      : {};
    const notes = uniquePresentationEntries(asRows(surface.notes).map(noteEntry));
    const items = uniquePresentationEntries([
      ...asRows(surface.equipment).map(row => gearEntry(row, "Equipment")),
      ...asRows(surface.gear).map(row => gearEntry(row, "Gear")),
      ...asRows(surface.inventory).map(row => gearEntry(row, "Inventory")),
      ...asRows(selected.items).map(row => gearEntry(row, "Item")),
      ...asRows(selected.equipment).map(row => gearEntry(row, "Equipment")),
    ]);
    return {notes, items, hasContent: notes.length > 0 || items.length > 0};
  }

  const ABILITY_ORDER = Object.freeze(["STR", "DEX", "CON", "INT", "WIS", "CHA"]);

  // Human labels for selected_record_sections groups. Groups missing here are
  // rendered under Advanced / Developer instead of being invented into a tab.
  const GROUP_LABELS = Object.freeze({
    spheres: "Spheres",
    talents: "Learned Talents",
    background_talent: "Background Talent",
    insights: "Cultivation Insights",
    background_origin: "Background & Origin",
    path_features: "Path Features",
    advancement_features: "Advancement Features",
    sphere_automatic_components: "Automatic Sphere Components",
    path_subpath: "Paths & Subpaths",
  });

  // Groups that belong to the Abilities tab (learned content first).
  const ABILITY_TAB_GROUPS = Object.freeze([
    "talents",
    "background_talent",
    "path_features",
    "advancement_features",
    "spheres",
    "insights",
    "sphere_automatic_components",
  ]);

  function abilityGroups(selectedRecordSections) {
    const sections = selectedRecordSections && typeof selectedRecordSections === "object" ? selectedRecordSections : {};
    const groups = [];
    for (const key of ABILITY_TAB_GROUPS) {
      const rows = Array.isArray(sections[key]) ? sections[key] : [];
      if (!rows.length) continue;
      groups.push({
        key,
        label: GROUP_LABELS[key] || key,
        cards: rows.map(card => ({
          recordId: card && card.record_id ? String(card.record_id) : "",
          name: firstNonEmpty([card && card.display_name, card && card.record_id]) || "Recorded detail",
          source: firstNonEmpty([card && card.subsection, card && card.section]) || "Source-backed",
          timing: firstNonEmpty([card && card.timing_or_category]) || null,
          acquiredAtCL: Number.isFinite(Number(card && card.acquisition_cl)) ? Number(card.acquisition_cl) : null,
          parentSphereId: firstNonEmpty([card && card.parent_sphere_id]) || null,
          summary: firstNonEmpty([card && card.one_line_description]) || "",
          fullText: firstNonEmpty([card && card.full_description]) || "",
          combatNote: firstNonEmpty([card && card.combat_execution_note]) || null,
        })),
      });
    }
    return groups;
  }

  // Display only: never evaluate rules or infer a bonus from a condition's name.
  // Shared by the owner sheet, tabletop inspector and connected pop-out sheet.
  function armorBreakdown(ac = {}, live = null) {
    const names = {DEX: "Dexterity", STR: "Strength", CON: "Constitution", INT: "Intelligence", WIS: "Wisdom", CHA: "Charisma"};
    const number = value => typeof value === "number" && Number.isFinite(value);
    const terms = node => {
      if (!node) return [];
      if (node.op === "add") return (node.terms || []).flatMap(terms);
      if (!number(node.value)) return [];
      const source = node.op === "ability_modifier" ? `${names[node.ability] || "Ability"} modifier`
        : node.op === "constant" ? "base" : "recorded calculation";
      return [{source, value: node.value}];
    };
    const equation = rows => rows.map((row, i) => `${i ? (row.value < 0 ? "− " : "+ ") : (row.value < 0 ? "−" : "")}${Math.abs(row.value)} ${row.source}`).join(" ");
    const value = ac.effective_value ?? ac.value;
    const lines = ["Armor Class (AC)", "An attack hits when its attack roll equals or exceeds your AC."];
    if (number(value)) lines.push(`Sheet AC: ${value}.`);
    if (ac.calculation) lines.push(`Base calculation: ${ac.calculation}`);
    const root = ac.formula_trace?.root;
    const rows = terms(root);
    if (rows.length) lines.push(`Recorded base: ${equation(rows)} = ${root.value}.`);
    else if (number(ac.base_value)) lines.push(`Recorded base AC: ${ac.base_value}. Individual terms were not recorded.`);
    const standing = (ac.generation?.always_on_bonuses || []).filter(row => row.display_name && number(row.bonus))
      .map(row => ({source: row.display_name, value: row.bonus}));
    const equipped = (ac.combat_terms || []).flatMap(row => {
      if (row.source === "unarmored calculation" && row.value === root?.value && rows.length) return rows;
      if (row.source === "standing bonuses" && standing.length && standing.reduce((sum, term) => sum + term.value, 0) === row.value) return standing;
      return [row];
    });
    if (equipped.length) lines.push(`Equipped calculation: ${equation(equipped)} = ${value}.`);
    else if (number(value) && number(root?.value) && value !== root.value) lines.push(`Other equipment or standing bonuses: ${value - root.value >= 0 ? "+" : ""}${value - root.value} AC in total. Individual sources were not recorded.`);
    if (ac.worn_note) lines.push(ac.worn_note);
    if (ac.tooltip) lines.push(ac.tooltip);
    lines.push("Use one base calculation; alternate calculations replace it rather than stacking.");
    lines.push(`Conditional bonuses (only when their requirements are met): ${ac.conditional_note || "No conditional bonus was recorded."}`);
    if (number(live?.armor_class)) {
      lines.push(`Current AC in this fight: ${live.armor_class}.`);
      for (const row of live.armor_modifiers || []) lines.push(`${row.source}: ${row.value >= 0 ? "+" : ""}${row.value} AC.`);
      if (number(live.armor_base)) {
        const known = (live.armor_modifiers || []).reduce((sum, row) => sum + row.value, 0);
        const remaining = live.armor_class - live.armor_base - known;
        lines.push(`Before active effects: ${live.armor_base} AC.`);
        if (remaining) lines.push(`Other active defenses: ${remaining >= 0 ? "+" : ""}${remaining} AC. The engine does not expose their individual sources.`);
      }
      lines.push("Cover and defenses against a particular attack are checked when that attack resolves.");
    }
    return lines.join("\n\n");
  }

  // The compact Armor Class card (owner 2026-10-08, SOL192): one equation a basic-D&D player reads at a glance,
  // e.g. "AC 17 = 10 + 2 Dex + 5 Shield spell (this fight)", the conditional bonuses in a line, and the complete
  // calculation above (armorBreakdown) under "Full calculation". Same numbers as armorBreakdown; nothing recomputed
  // beyond the sums it already prints.
  function armorCard(ac = {}, live = null) {
    const short = {"Dexterity modifier": "Dex", "Strength modifier": "Str", "Constitution modifier": "Con",
      "Intelligence modifier": "Int", "Wisdom modifier": "Wis", "Charisma modifier": "Cha", base: "", "unarmored calculation": "unarmored"};
    const number = value => typeof value === "number" && Number.isFinite(value);
    const names = {DEX: "Dexterity", STR: "Strength", CON: "Constitution", INT: "Intelligence", WIS: "Wisdom", CHA: "Charisma"};
    const terms = node => {
      if (!node) return [];
      if (node.op === "add") return (node.terms || []).flatMap(terms);
      if (!number(node.value)) return [];
      return [{source: node.op === "ability_modifier" ? `${names[node.ability] || "Ability"} modifier`
        : node.op === "constant" ? "base" : "recorded calculation", value: node.value}];
    };
    const root = ac.formula_trace?.root;
    const baseRows = terms(root);
    const standing = (ac.generation?.always_on_bonuses || []).filter(row => row.display_name && number(row.bonus))
      .map(row => ({source: row.display_name, value: row.bonus}));
    const sheetValue = ac.effective_value ?? ac.value;
    let rows = (ac.combat_terms || []).flatMap(row => {
      if (row.source === "unarmored calculation" && row.value === root?.value && baseRows.length) return baseRows;
      if (row.source === "standing bonuses" && standing.length && standing.reduce((sum, t) => sum + t.value, 0) === row.value) return standing;
      return [row];
    });
    if (!rows.length && baseRows.length) rows = baseRows;
    const current = number(live?.armor_class) ? live.armor_class : sheetValue;
    if (number(live?.armor_class)) {
      for (const row of live.armor_modifiers || []) rows.push({source: `${row.source} (this fight)`, value: row.value});
      const known = rows.reduce((sum, row) => sum + (number(row.value) ? row.value : 0), 0);
      if (rows.length && current - known) rows.push({source: "other active defenses", value: current - known});
    }
    const abbreviate = source => String(source).replace(/\b(Strength|Dexterity|Constitution|Intelligence|Wisdom|Charisma) modifier\b/,
      ability => ability.slice(0, 3)).replace(/\(armor caps the bonus at ([+−-]?\d+)\)/, "(max $1 in this armor)");
    const term = (row, i) => {
      const name = row.source in short ? short[row.source] : abbreviate(row.source);
      const sign = i ? (row.value < 0 ? " − " : " + ") : (row.value < 0 ? "−" : "");
      return `${sign}${Math.abs(row.value)}${name ? ` ${name}` : ""}`;
    };
    const sum = rows.reduce((total, row) => total + (number(row.value) ? row.value : 0), 0);
    const headline = number(current)
      ? (rows.length && sum === current ? `AC ${current} = ${rows.map(term).join("")}.` : `AC ${current}.`)
      : "AC unavailable.";
    const lines = [];
    const conditional = String(ac.conditional_note || "").trim();
    if (conditional && !/^no conditional/i.test(conditional)) lines.push(`Only sometimes: ${conditional}`);
    if (number(live?.armor_class)) lines.push("Cover and defenses against one attack are checked when that attack resolves.");
    return {title: "Armor Class", headline, lines,
            full: {label: "Full calculation", text: armorBreakdown(ac, live), open: false}};
  }

  function statTiles(stats, identity) {
    const tiles = [];
    if (!stats || typeof stats !== "object") return tiles;
    const hasCombatAC = Object.prototype.hasOwnProperty.call(stats, "combat_armor_class");
    const ac = hasCombatAC ? (stats.combat_armor_class || {}) : (stats.armor_class || {});
    if (hasCombatAC && (ac.value === null || ac.value === undefined)) {
      tiles.push({id: "ac", label: "Armor Class", value: "Unavailable", tooltip: ac.tooltip || "AC from combat unavailable."});
    } else if (ac.value !== null && ac.value !== undefined) {
      tiles.push({id: "ac", label: "Armor Class", value: String(ac.effective_value ?? ac.value), tooltip: armorBreakdown({...stats.armor_class, ...ac.breakdown, ...ac}),
                  card: armorCard({...stats.armor_class, ...ac.breakdown, ...ac})});
    }
    const hp = stats.hit_points || {};
    if (hp.maximum !== null && hp.maximum !== undefined) {
      const current = hp.build_state_current;
      tiles.push({id: "hp", label: "Hit Points", value: current === null || current === undefined ? String(hp.maximum) : `${current}/${hp.maximum}`});
    }
    const init = stats.initiative || {};
    if (init.bonus !== null && init.bonus !== undefined) {
      tiles.push({id: "initiative", label: "Initiative", value: signed(init.bonus)});
    }
    const speed = stats.speed || {};
    if (speed.walking_ft !== null && speed.walking_ft !== undefined) {
      tiles.push({id: "speed", label: "Speed", value: `${speed.walking_ft} ft`});
    }
    if (identity && identity.proficiency_bonus !== null && identity.proficiency_bonus !== undefined) {
      tiles.push({id: "pb", label: "Proficiency", value: signed(identity.proficiency_bonus)});
    }
    const resource = stats.primary_resource || {};
    if (resource.maximum !== null && resource.maximum !== undefined) {
      const label = resource.name ? `${resource.name}` : "Primary resource";
      const current = resource.build_state_current;
      tiles.push({id: "resource", label, value: current === null || current === undefined ? String(resource.maximum) : `${current}/${resource.maximum}`});
    }
    if (stats.technique_attack_bonus !== null && stats.technique_attack_bonus !== undefined) {
      tiles.push({id: "technique_attack", label: "Technique Attack", value: signed(stats.technique_attack_bonus)});
    }
    if (stats.technique_save_dc !== null && stats.technique_save_dc !== undefined) {
      tiles.push({id: "save_dc", label: "Technique DC", value: String(stats.technique_save_dc)});
    }
    return tiles.filter(tile => tile.value !== null);
  }

  function abilityChips(stats) {
    const rows = Array.isArray(stats && stats.abilities) ? stats.abilities : [];
    const byAbility = new Map();
    for (const row of rows) {
      if (row && typeof row.ability === "string") byAbility.set(row.ability.toUpperCase(), row);
    }
    const chips = [];
    for (const ability of ABILITY_ORDER) {
      const row = byAbility.get(ability);
      if (!row) continue;
      chips.push({ability, score: row.score, modifier: signed(row.modifier)});
    }
    return chips;
  }

  function readinessTone(sheet) {
    const status = String(sheet && sheet.build_status || "").toUpperCase();
    const activeRun = sheet && sheet.workflow && sheet.workflow.active_run;
    const blockers = activeRun && Array.isArray(activeRun.blockers) ? activeRun.blockers : [];
    if (blockers.length) return {tone: "attention", label: "Needs attention"};
    if (activeRun) return {tone: "progress", label: "Build in progress"};
    if (status === "CHARACTER_SHEET_READY" || status === "GM_READY") return {tone: "ready", label: "Ready"};
    if (status === "TEMPORARY" || status === "SAVED_DRAFT" || status === "BLUEPRINT" || status === "ADVANCEMENT_READY") {
      return {tone: "progress", label: "In progress"};
    }
    return {tone: "progress", label: "Saved character"};
  }

  /**
   * Deterministic owner-sheet model. The mechanics tab list is the stable
   * eighteen-surface contract; each surface carries availability so the
   * renderer can state missing evidence without inventing a section.
   * `names` optionally carries the client-side final-name join inputs
   * ({characterListName, resolvedWorkflowName, libraryName}); without it the
   * sheet payload's own name field is used.
   */
  function buildSheetViewModel(sheet, names) {
    const payload = sheet && typeof sheet === "object" ? sheet : {};
    const identity = payload.identity && typeof payload.identity === "object" ? payload.identity : {};
    const snapshot = payload.display_owner_character_sheet && typeof payload.display_owner_character_sheet === "object"
      ? payload.display_owner_character_sheet
      : payload.owner_character_sheet && typeof payload.owner_character_sheet === "object"
        ? payload.owner_character_sheet
        : {};
    const stats = payload.sections && payload.sections.abilities_statistics && payload.sections.abilities_statistics.data
      ? payload.sections.abilities_statistics.data
      : snapshot.ability_scores_and_statistics || {};
    const pathSurface = snapshot.path_and_subpath || {};
    const method = snapshot.method || {};
    const foundation = snapshot.foundation || {};
    const sphereSurface = snapshot.spheres_and_talents || {};
    const groups = abilityGroups(snapshot.selected_record_sections);
    const notesGearSurface = notesGear(snapshot);

    const tone = readinessTone(payload);
    const snapshotIdentity = snapshot.identity && typeof snapshot.identity === "object" ? snapshot.identity : {};
    // The compact service identity projection omits some snapshot fields such
    // as proficiency_bonus; prefer the payload and fall back to the snapshot.
    const mergedIdentity = {...snapshotIdentity, ...identity};
    const cl = firstNonEmpty([identity.current_cl, snapshotIdentity.cultivation_level]);
    const realm = firstNonEmpty([identity.current_realm, snapshotIdentity.realm]);
    const concept = firstNonEmpty([identity.concept, snapshotIdentity.concept]) || "";

    const counts = {
      spheres: Array.isArray(sphereSurface.sphere_record_ids) ? sphereSurface.sphere_record_ids.length : 0,
      talents: Array.isArray(sphereSurface.learned_talent_record_ids) ? sphereSurface.learned_talent_record_ids.length : 0,
      insights: Array.isArray(sphereSurface.cultivation_insight_record_ids) ? sphereSurface.cultivation_insight_record_ids.length : 0,
      automaticComponents: Array.isArray(sphereSurface.automatic_sphere_component_record_ids)
        ? sphereSurface.automatic_sphere_component_record_ids.length
        : 0,
    };

    // The owner sheet has one stable mechanics navigation.  Availability is
    // carried by each verified service surface; the tab itself remains
    // reachable so an unavailable source is stated explicitly rather than
    // silently disappearing from the character record.
    const completeCharacter = buildCompleteCharacterViewModel(payload.complete_character);
    const tabs = COMPLETE_CHARACTER_SURFACE_IDS.map(id => ({
      id,
      label: COMPLETE_CHARACTER_SURFACE_LABELS[id],
      available: Boolean(completeCharacter && completeCharacter.surfaces[id]?.available),
    }));

    const backgroundOrigin = snapshot.background_and_origin || {};
    return {
      name: resolveOwnerFinalName({
        characterListName: names && names.characterListName !== undefined ? names.characterListName : payload.name,
        resolvedWorkflowName: names && names.resolvedWorkflowName,
        libraryName: names && names.libraryName,
      }),
      title: firstNonEmpty([identity.title, snapshotIdentity.title]),
      concept,
      cl,
      realm,
      realmLabel: realm ? `${realm} Realm` : null,
      pathLabel: firstNonEmpty([identity.path, snapshotIdentity.path]),
      pathSummary: payload.path_summary || null,
      subpathLabel: firstNonEmpty([identity.subpath, snapshotIdentity.subpath_name]),
      species: firstNonEmpty([identity.species, snapshotIdentity.species]),
      keyAbility: firstNonEmpty([identity.key_ability, snapshotIdentity.key_ability]),
      methodLabel: firstNonEmpty([method.display_name, method.name]),
      foundationLabel: firstNonEmpty([foundation.display_name, foundation.name]),
      backgroundLabel: firstNonEmpty([
        backgroundOrigin.background && backgroundOrigin.background.name,
        backgroundOrigin.background && backgroundOrigin.background.display_name,
      ]),
      originLabel: firstNonEmpty([
        backgroundOrigin.origin_insight && backgroundOrigin.origin_insight.name,
        backgroundOrigin.origin_insight && backgroundOrigin.origin_insight.display_name,
      ]),
      state: tone,
      plainSummary: payload.plain_summary || "",
      nextAction: payload.next_legal_action || null,
      blockers: (() => {
        const run = payload.workflow && payload.workflow.active_run;
        return run && Array.isArray(run.blockers) ? run.blockers : [];
      })(),
      counts,
      tiles: statTiles(stats, mergedIdentity),
      abilityChips: abilityChips(stats),
      skills: Array.isArray(stats.skills) ? stats.skills : [],
      actionsIndex: Array.isArray(snapshot.owner_facing_action_feature_index) ? snapshot.owner_facing_action_feature_index : [],
      pathsSummary: {
        paths: Array.isArray(pathSurface.paths) ? pathSurface.paths : [],
        subpaths: Array.isArray(pathSurface.subpaths) ? pathSurface.subpaths : [],
      },
      advancementLevels: snapshot.advancement_history && Array.isArray(snapshot.advancement_history.levels)
        ? snapshot.advancement_history.levels
        : [],
      abilityGroups: groups,
      notesGear: notesGearSurface,
      completeCharacter,
      tabs,
    };
  }

  return {
    ABILITY_ORDER,
    GROUP_LABELS,
    PLACEHOLDER_NAMES,
    COMPLETE_CHARACTER_SURFACE_IDS,
    COMPLETE_CHARACTER_SURFACE_LABELS,
    abilityChips,
    abilityGroups,
    buildCompleteCharacterViewModel,
    buildSheetViewModel,
    isPlaceholderName,
    normalizeName,
    notesGear,
    readableLabel,
    readinessTone,
    resolveOwnerFinalName,
    statTiles,
    armorBreakdown,
    armorCard,
  };
});
