// Shared by the flight/scenery opt-in browser checks and the browser-free HTTP regression.
import {readFile} from 'node:fs/promises';
import {resolve, sep, extname} from 'node:path';
import {fileURLToPath} from 'node:url';

export const appRoot = resolve(fileURLToPath(new URL('../', import.meta.url)));

export function flightStaticHandler(root = appRoot) {
  // URL directory paths have a trailing separator; normalize before containment checks.
  const normalizedRoot = resolve(root);
  return async (request, response) => {
    const path = new URL(request.url, 'http://localhost').pathname;
    if (path === '/') {
      response.setHeader('content-type', 'text/html');
      response.end('<link rel="stylesheet" href="/static/tabletop/hovercard.css"><link rel="stylesheet" href="/static/tabletop/tabletop.css"><div id="controls"></div><div id="board" style="width:640px;height:480px"></div>');
      return;
    }
    const entry = /^\/module-check\/(tabletop|sheet)\.html$/.exec(path);
    const file = resolve(normalizedRoot, `.${entry ? `/static/tabletop/${entry[1]}.html` : path}`);
    if (!file.startsWith(normalizedRoot + sep)) { response.writeHead(404); response.end(); return; }
    try {
      const contents = await readFile(file);
      const types = {'.html': 'text/html', '.css': 'text/css', '.js': 'text/javascript', '.mjs': 'text/javascript', '.json': 'application/json'};
      response.setHeader('content-type', types[extname(file)] || 'application/octet-stream');
      // Real page DOM, with explicit imports below instead of automatic script execution.
      response.end(entry ? contents.toString().replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, '') : contents);
    } catch { response.writeHead(404); response.end(); }
  };
}
