// Slice A: a browser starts once and observes. Animation never advances combat.
// Status reads contain no engine/menu load; full view/feed arrives at a boundary.
export async function automaticTurn({start, observe, wait, current, status}) {
  let value = await start();
  while (current()) {
    status(value);
    if (!value.running) return value;
    await wait(100);
    if (!current()) return null;
    value = await observe();
  }
  return null;
}
