// Bind extracted tabletop.js functions to the same named imports as the page.
// Explicit fixture bindings spread after this map override production imports.
import {readFileSync} from 'node:fs';

const url = new URL('../static/tabletop/tabletop.js', import.meta.url);
const source = readFileSync(url, 'utf8');
const bindings = {};
for (const match of source.matchAll(/import\s*\{([^}]+)\}\s*from\s*['"]([^'"]+)['"]\s*;/g)) {
  const module = await import(new URL(match[2], url));
  for (const entry of match[1].split(',')) {
    const [exported, local = exported] = entry.trim().split(/\s+as\s+/);
    if (!(exported in module)) throw new Error(`Missing tabletop import: ${exported}`);
    bindings[local] = module[exported];
  }
}
export const tabletopBindings = bindings;
