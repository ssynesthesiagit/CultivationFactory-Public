// Payload reader shared by the table harnesses Python drives through stdin.
//
// `node --test` (the public CI node job, ci/public_test_shard.py) gives every test
// file a stdin pipe that never closes. A module-scope readFileSync(0) or
// `for await (const chunk of process.stdin)` therefore waits forever and stalls
// the whole job (six files did exactly that on 2026-10-21). Python instead pipes
// one JSON payload and closes stdin, so EOF arrives at once. Read until EOF, but
// treat a pipe that stays silent as "no payload": the file's own skip guard then
// reports a skip instead of hanging.
import {readFileSync} from 'node:fs';

const DEFAULT_TIMEOUT_MS = 2000;

// Python's run_node_test (tests/node_support.py) names the payload file in PI_NODE_TEST_FIXTURE. It is used first
// because a file run by `node --test` without an isolation flag (Node 20) is a child process that never receives
// the caller's stdin, so a stdin payload would be lost and the file would skip. The child inherits the variable.
export async function readStdinPayload(timeoutMs = DEFAULT_TIMEOUT_MS) {
  const fixture = process.env.PI_NODE_TEST_FIXTURE;
  if (fixture) return readFileSync(fixture, 'utf8');
  if (process.stdin.isTTY || process.stdin.destroyed || process.stdin.readableEnded) return "";
  process.stdin.setEncoding("utf8");
  let input = "";
  let timer;
  const quiet = new Promise(resolve => {
    const done = () => resolve();
    process.stdin.on("data", chunk => { input += chunk; });
    process.stdin.once("end", done);
    process.stdin.once("error", done);
    timer = setTimeout(done, timeoutMs);
    process.stdin.resume();
  });
  await quiet;
  clearTimeout(timer);
  process.stdin.pause();
  process.stdin.destroy();
  return input;
}
