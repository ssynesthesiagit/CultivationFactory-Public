// Payload reader shared by the table harnesses Python drives through stdin.
//
// `node --test` (the public CI node job, ci/public_test_shard.py) gives every test
// file a stdin pipe that never closes. A module-scope readFileSync(0) or
// `for await (const chunk of process.stdin)` therefore waits forever and stalls
// the whole job (six files did exactly that on 2026-10-21). Python instead pipes
// one JSON payload and closes stdin, so EOF arrives at once. Read until EOF, but
// treat a pipe that stays silent as "no payload": the file's own skip guard then
// reports a skip instead of hanging.
const DEFAULT_TIMEOUT_MS = 2000;

export async function readStdinPayload(timeoutMs = DEFAULT_TIMEOUT_MS) {
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
