// The shipped Combat log renderer (tabletop.js feedClass .. appendTableLine) on a small DOM stand-in; no browser.
// renderLog() calls appendFeed once per increment, exactly as the table receives `events?after=N`, and returns each
// entry as the player reads it. Run directly (tests/test_feed_summary.py), it reads
// {increments: [[row, ...], ...], detail: false, open: false, grouped: false} on stdin and prints the entries as JSON.
import {readFileSync} from 'node:fs';
import {pathToFileURL} from 'node:url';
import {foldSummary, mapObjectFeed, summaryPieces} from '../static/tabletop/feed-presentation.js';
import {rollModeHover, rollModeLabel} from '../static/tabletop/roll_mode_display.js';

const node = () => ({
  children: [], className: '', dataset: {}, style: {}, title: '', textContent: '', hidden: false,
  addEventListener() {}, appendChild(child) { this.children.push(child); return child; },
  replaceChildren(...kids) { this.children = kids; this.textContent = ''; },
  prepend(...kids) { this.children.unshift(...kids); },
  get lastElementChild() { return this.children.at(-1) || null; },
});
const document = {createElement: node, createTextNode: text => ({textContent: String(text), children: []})};
const LINES = 'tt-feed-lines';
const text = item => (item.children || []).filter(kid => kid.className !== LINES).map(text).join('') + (item.textContent || '');
const source = readFileSync(new URL('../static/tabletop/tabletop.js', import.meta.url), 'utf8');
const start = source.indexOf('function feedClass(row)');
const code = source.slice(start, source.indexOf('\nfunction appendTableLine', start));

export function renderLog(increments, {detail = false, open = false, grouped = false} = {}) {
  if (grouped) increments = increments.map(rows => mapObjectFeed(rows));
  globalThis.document = document;  // rollModeLabel builds its label in its own module scope
  const feed = node();
  const {appendFeed, renderSummaryEntry} = new Function('$', 'document', 'settleFeed', 'mapObjectFeed', 'foldSummary',
    'summaryPieces', 'rollModeHover', 'rollModeLabel', code + '; return {appendFeed, renderSummaryEntry};')(
    id => id === '#ttFeed' ? feed : {checked: detail}, document, () => {}, mapObjectFeed, foldSummary, summaryPieces,
    rollModeHover, rollModeLabel);
  const original = JSON.stringify(increments);
  for (const rows of increments) appendFeed(rows);
  if (JSON.stringify(increments) !== original) throw new Error('the log changed the rows it was given');
  return feed.children.map(item => {
    const entry = item.summaryEntry;
    if (open && entry && entry.kind !== 'turn') {
      entry.open = true;
      renderSummaryEntry(entry);
    }
    const lines = item.children.find(kid => kid.className === LINES);
    return {text: text(item).trim(), hidden: item.hidden, className: item.className, title: item.title,
      type: item.dataset.type, sequences: entry ? entry.rows.map(row => row.event_sequence) : [],
      lines: lines ? lines.children.map(line => text(line).trim()) : []};
  });
}

if (import.meta.url === pathToFileURL(process.argv[1] || '').href) {
  const {increments, detail, open, grouped} = JSON.parse(readFileSync(0, 'utf8'));
  console.log(JSON.stringify(renderLog(increments, {detail, open, grouped})));
}
