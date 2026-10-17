// These transport/DOM tests inject a fake board into createPlay. Avoid loading
// the unused drawing dependencies (art-kit.js, object-art-catalog.js and object-arrange.js)
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
  if (specifier.startsWith('./object-art-catalog.js')) {
    return {shortCircuit:true,url:'data:text/javascript,'+encodeURIComponent(`
      export const CATALOG_KNOWN=[];
      export const CATALOG_FACE={};
      export function catalogProp() { throw new Error('Decorative prop drawing is outside these fake-board DOM tests'); }
    `)};
  }
  if (specifier.startsWith('./object-arrange.js')) {
    return {shortCircuit:true,url:'data:text/javascript,'+encodeURIComponent(`
      export function arrangeObjects(objects) {
        if (objects?.length) throw new Error('Object layout is outside these fake-board DOM tests');
        return new Map();
      }
      export function layoutTokenFields() { throw new Error('Object layout is outside these fake-board DOM tests'); }
    `)};
  }
  return nextResolve(specifier,context);
}});
