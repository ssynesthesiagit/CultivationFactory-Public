// Small presentation helpers for the pop-out sheet.
export function compactFlightCard(text) {
  if (!text) return null;
  const height = text.match(/Height: (\d+) ft/)?.[1];
  if (height == null) return null;
  const speed = text.match(/Fly speed: (\d+) ft(?: \(can hover\))?/)?.[1];
  return {label: "HEIGHT", value: `${height} ft`, detail: speed ? `fly ${speed} ft` : "no fly speed", title: text};
}

export function unavailableRowsHidden(connected, count, showUnavailable) {
  return connected === true && count > 0 && !showUnavailable;
}

