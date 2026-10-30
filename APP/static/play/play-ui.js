// DOM rendering shared by the phone entry point and its deterministic DOM regressions.
import {renderVariantGroups} from '../tabletop/attack-groups.js?v=variants1';
import {rulesTextFor, renderReadableRules, actionSummary, cleanRules} from '../tabletop/rules.js';
import {resourceText, glossaryDefinitions} from '../tabletop/newcomer.js';
import {layoutText} from '../tabletop/presentation.js';
import {durationText} from '../tabletop/zone-text.js';
import {optionText, reactionAnswer, reactionMenuAnswers, spaceOptionText, suggestedOption} from './play-model.js';

export function node(doc, tag, text = '', cls = '') {
  const n = doc.createElement(tag);
  if (text) n.textContent = String(text);
  if (cls) n.className = cls;
  return n;
}
export function button(doc, text, press) {
  const b = node(doc, 'button', text); b.type = 'button'; b.addEventListener('click', press); return b;
}
export function rulesDetails(doc, text, label = 'Full rules text') {
  const d = node(doc, 'details'); d.append(node(doc, 'summary', label), renderReadableRules(doc, text || 'No additional rules text was supplied for this option.')); return d;
}

function resourceDetails(text) {
  const seen=new Set();
  return cleanRules(text).split(/\n+|(?<=[.!?])\s+/).filter(line => {
    const key=line.trim().toLowerCase().replace(/\s+/g, ' ');
    if (!key || seen.has(key)) return false;
    seen.add(key); return true;
  }).join('\n');
}

export function renderActions(host, menu, sheet, {choose, move, end, families = []}) {
  const doc = host.ownerDocument || document;
  host.replaceChildren();
  if (!menu) { host.append(node(doc, 'p', 'Waiting for your character’s turn.')); return; }
  if (menu.moves?.length) host.append(button(doc, 'Move — tap a square or choose from all destinations', move));
  if (menu.moves?.length && menu.movement_preview) host.append(node(doc, 'p', menu.movement_preview));
  // Display every group, including item actions, free settings, talents and augments.
  // Ranking changes order only; no options_shown or top-N limit makes a row unreachable.
  const groups = [...(menu.actions || [])];
  // Standing choices can make a family affordable even when its saved
  // configuration has no legal activation in this menu. Keep an aiming entry
  // for every owned family with a server-issued composition contract. Only the
  // scoped preview supplies legal candidates; these entries invent none.
  for (const family of families) {
    if (!Object.values(menu.composition || {}).some(c => c.family === family.base)) continue;
    const activations = [{source:family.base,label:family.name}, ...(family.choices || [])
      .filter(c => c.activation && c.button_id?.startsWith('act:'))
      .map(c => ({source:c.button_id.slice(4),label:c.label}))];
    for (const activation of activations) {
      if (groups.some(g => (g.alias_of || g.source_definition_id) === activation.source)) continue;
      groups.push({label:activation.label,source_definition_id:activation.source,options:[],composition_only:true,
        cost_label:'Choose options, then aim. Costs and legal targets are checked before use.'});
    }
  }
  const sections = renderVariantGroups(doc, groups, (group, action = group) => {
    const section = node(doc, 'div', '', 'play-action');
    const row = sheet?.buttons?.find(b => b.combat?.source_definition_id === group.source_definition_id
      || b.combat?.source_definition_id === group.alias_of);
    const b = button(doc, group.label, () => choose(action));
    if (group.composition_only) { b.setAttribute('data-draft-only',''); b.disabled=true; }
    if (group.options?.length===1 && menu.composition?.[group.options[0].candidate_id]) {
      b.dataset.optionSource=group.source_definition_id;
      b.setAttribute('aria-pressed','false');
    }
    b.append(node(doc, 'small', group.cost_label || actionSummary(row || group)));
    section.append(b, rulesDetails(doc, [layoutText(group.hover) || group.description, rulesTextFor(sheet, row)].filter(Boolean).join('\n\n')));
    return section;
  });
  for (const section of sections) host.append(section);
  if (menu.end_turn) host.append(button(doc, 'End turn', end));
}

export function renderGuidedActions(host, menu, sheet, state, view, handlers, expanded = false) {
  const doc = host.ownerDocument || document;
  const proposal = suggestedOption(menu, state, view);
  host.replaceChildren();
  const card = node(doc, 'section', '', 'play-action');
  card.append(node(doc, 'h3', 'Suggested plan — next step'));
  if (proposal) {
    if (proposal.fallback) card.append(node(doc, 'p', 'No ranked suggestion is available. This is the first available step in the menu; use Change to compare every alternative.'));
    if (proposal.unresolved) card.append(node(doc, 'p', `${proposal.label}: check the available targets before confirming.`));
    else card.append(node(doc, 'p', `${proposal.label}: ${optionText(proposal.option, state, view)}`));
    if (proposal.group) {
      const row = sheet?.buttons?.find(b => b.combat?.source_definition_id === proposal.group.source_definition_id);
      card.append(node(doc, 'p', proposal.group.cost_label || actionSummary(row || proposal.group)),
        rulesDetails(doc, [layoutText(proposal.group.hover) || proposal.group.description, rulesTextFor(sheet, row)].filter(Boolean).join('\n\n')));
    }
    if (proposal.unresolved || (proposal.option?.deferred_route && !proposal.option.route_checked))
      card.append(button(doc, proposal.unresolved ? 'Check targets for this step' : 'Check route for this step', () => handlers.inspect(proposal)));
    else card.append(button(doc, 'Confirm this step', () => handlers.confirm(proposal.option.candidate_id)));
  } else card.append(node(doc, 'p', 'No ranked suggestion is available. Choose any legal action with Change.'));
  card.append(node(doc, 'p', 'You confirm each step. After it resolves, the app reads the fight again before suggesting the next step.'),
    button(doc, 'Change — edit target, move or choose any alternative', handlers.change));
  host.append(card);
  if (expanded) {
    const all = node(doc, 'div');
    renderActions(all, menu, sheet, handlers);
    host.append(all);
  }
}

export function renderOptions(host, options, state, view, choose, cancel) {
  const doc = host.ownerDocument || document;
  host.replaceChildren(button(doc, 'Cancel — choose another action', cancel));
  for (const option of options) {
    const label = mode => {
      if (!option.deferred_route) return optionText(option, state, view);
      const checked = option.route_checked && option.route_mode === mode;
      const display = {...option, movement_mode: mode,
        path: checked ? option.path : [], hazard_exposure: checked && option.hazard_exposure};
      return (checked ? 'Confirm move — ' : 'Check route — ') + optionText(display, state, view);
    };
    const b = button(doc, label(option.movement_mode || 'walk'), () => choose(option));
    b.dataset.candidate = option.candidate_id;
    host.append(b);
    if (option.can_jump_down) host.append(button(doc, `${label('jump_down')} · Jump down (falling can hurt you)`, () => choose(option, 'jump_down')));
  }
}

export function renderReaction(host, prompt, {answer, error, selected: initial = [], onSelect = () => {}}) {
  const doc = host.ownerDocument || document;
  host.replaceChildren();
  if (prompt.alternatives) {
    host.append(node(doc, 'p', 'Choose your reaction. Compare every option and its cost before choosing.'));
    prompt.alternatives.forEach((row, index) => {
      const section = node(doc, 'section', '', 'play-action');
      section.append(node(doc, 'h3', `${row.reactor || 'Your character'} · ${row.reaction}`));
      for (const [label, value] of [['Trigger', row.trigger || row.moment], ['Cost now', row.cost], ['What happens', row.summary],
        ['Limits', row.limits], ['At this table', row.table_note]]) if (value) section.append(node(doc, 'p', `${label}: ${value}`));
      if (row.rules) section.append(rulesDetails(doc, row.rules));
      section.append(button(doc, `Choose ${row.reaction}`, () => {
        if (row.choice) {
          renderReaction(host, row, {error, answer: selected => answer(reactionMenuAnswers(prompt, index, selected))});
          host.append(button(doc, 'Back — compare all reactions', () => renderReaction(host, prompt, {answer, error})));
        } else return answer(reactionMenuAnswers(prompt, index, reactionAnswer(row, [])));
      }));
      host.append(section);
    });
    host.append(button(doc, 'Pass — keep your Reaction and resources', () => answer(reactionMenuAnswers(prompt, -1))));
    return;
  }
  host.append(node(doc, 'p', `${prompt.reactor || 'Your character'} · ${prompt.reaction || prompt.title || 'Decision'}`));
  for (const [label, text] of [['Trigger', prompt.trigger || prompt.moment], ['Cost now', prompt.cost], ['What happens', prompt.summary],
    ['Limits', prompt.limits], ['At this table', prompt.table_note]]) if (text) host.append(node(doc, 'p', `${label}: ${text}`));
  if (prompt.rules) host.append(rulesDetails(doc, prompt.rules, 'Full rules, targets and duration'));
  const choice = prompt.choice;
  const selected = new Set(initial);
  const use = ids => { try { return answer(reactionAnswer(prompt, ids)); } catch (e) { return error(e.message); } };
  const options = node(doc, 'div', '', 'play-options');
  if (choice) {
    host.append(node(doc, 'p', `Choose ${choice.minimum === choice.maximum ? choice.maximum : `${choice.minimum}–${choice.maximum}`} options.`));
    for (const option of choice.options || []) {
      const labelText = spaceOptionText(option, choice.space_map);
      const description = option.description && option.description !== option.label ? spaceOptionText({...option, label: option.description}, choice.space_map) : '';
      const text = `${labelText}${description ? ` — ${description}` : ''}`;
      if (choice.maximum > 1) {
        const label = node(doc, 'label'), input = node(doc, 'input'); input.type = 'checkbox'; input.value = option.id;
        input.checked = selected.has(option.id);
        input.addEventListener('change', () => { if (input.checked) selected.add(option.id); else selected.delete(option.id); onSelect(option.id, input.checked); });
        label.append(input, node(doc, 'span', text));
        options.append(label);
      } else options.append(button(doc, text, () => use([option.id])));
    }
    if (choice.maximum > 1 || choice.minimum === 0) options.append(button(doc, 'Confirm choices', () => use([...selected])));
  } else options.append(button(doc, `Use ${prompt.reaction || 'reaction'}`, () => use([])));
  if (!choice || choice.allow_decline) options.append(button(doc, 'Decline — do not use this ability', () => answer({...prompt.context, selection: 'DECLINE'})));
  host.append(options);
}

export function renderCharacter(host, actor, sheet, conditionInfo = {}) {
  const doc = host.ownerDocument || document;
  host.replaceChildren();
  if (!actor) { host.append(node(doc, 'p', 'Choose your character first.')); return; }
  const shownRules=new Set();
  const appendRules=(text,label) => {
    // Sheet buttons can repeat the same library entry. Keep distinct abilities,
    // but present an identical named card just once in this phone panel.
    const key=`${label}\n${cleanRules(text)}`.toLowerCase().replace(/\s+/g,' ').trim();
    if (shownRules.has(key)) return;
    shownRules.add(key); host.append(rulesDetails(doc,text,label));
  };
  const hp = actor.hit_points || {};
  host.append(node(doc, 'h3', actor.display_name), node(doc, 'p', `HP ${hp.current ?? '—'} / ${hp.maximum ?? '—'}${hp.temporary ? ` · ${hp.temporary} temporary HP` : ''}`));
  if (actor.life_status_text) host.append(node(doc, 'p', actor.life_status_text));
  for (const res of actor.resources || []) {
    const name=res.display_name || 'Resource';
    const summary=(glossaryDefinitions(name, false)[0] || 'Use this counter when one of your abilities names it.').split(/(?<=[.!?])\s+/)[0];
    const section=node(doc, 'section', '', 'play-resource');
    section.append(node(doc, 'h3', `${name}: ${res.current} / ${res.maximum}`), node(doc, 'p', summary),
      rulesDetails(doc, resourceDetails(resourceText(res).replace(`${name}: ${res.current} current / ${res.maximum} maximum.`, '').replace(summary, '')), 'Details'));
    host.append(section);
  }
  host.append(node(doc, 'h3', 'Conditions'));
  if (!actor.conditions?.length) host.append(node(doc, 'p', 'No conditions.'));
  for (const condition of (actor.conditions || []).filter(c=>!c.hidden)) {
    const info = conditionInfo[String(condition.condition_id || '').split('.').pop()] || {};
    const text = condition.detail || condition.description || condition.rules_text || [(info.mechanics || []).join('; '),info.reading].filter(Boolean).join('. ');
    appendRules(`${text}${condition.expires_on ? `\nDuration: ${durationText(condition.expires_on)}.` : ''}`,
      `${condition.display_name || 'Condition'}${condition.stacks > 1 ? ` ×${condition.stacks}` : ''}`);
  }
  host.append(node(doc, 'h3', 'Full rules text'));
  if (!sheet) host.append(node(doc, 'p', 'Character rules are unavailable. Try reopening Character.'));
  for (const group of sheet?.library?.groups || []) {
    host.append(node(doc, 'h3', group.name || group.label || 'Character abilities'));
    for (const sphere of group.spheres || []) {
      appendRules(layoutText(sphere.hover) || sphere.text || sphere.summary, sphere.name);
      for (const entry of sphere.entries || []) appendRules(layoutText(entry.hover) || entry.text || entry.summary, entry.name);
    }
    for (const entry of group.entries || []) appendRules(layoutText(entry.hover) || entry.text || entry.summary, entry.name);
  }
  for (const row of sheet?.buttons || []) appendRules(rulesTextFor(sheet, row), row.label || 'Ability');
}
