// These transport/DOM tests inject a fake board into createPlay. Avoid loading
// the unused SVG drawing dependency tree, whose art-kit.js is intentionally
// absent from public CI snapshots. Keep the two renderer constants/helpers used
// by phone map presentation; no combat, ownership, UI or transport is mocked.
import {registerHooks} from 'node:module';

registerHooks({resolve(specifier, context, nextResolve) {
  if (specifier === '../tabletop/board.js') {
    return {shortCircuit:true,url:'data:text/javascript,'+encodeURIComponent(`
      export const CELL=64;
      export const initials=name=>String(name).split(/\\s+/).filter(Boolean).slice(0,2).map(word=>word[0]).join('');
    `)};
  }
  return nextResolve(specifier,context);
}});
