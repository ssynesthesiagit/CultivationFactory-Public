// Prints the editor's centre-plus squares for one fixture ({doc, presets}); tests/test_editor_object_sight.py reads it.
import {readFileSync} from 'node:fs';
import {mapCenterlines} from '../static/tabletop/vision.js';
const fixture = JSON.parse(readFileSync(process.argv[2], 'utf-8'));
process.stdout.write(JSON.stringify(mapCenterlines(fixture.doc, fixture.presets)));
