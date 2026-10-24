// Small presentation helpers for the pop-out sheet.
export function unavailableRowsHidden(connected, count, showUnavailable) {
  return connected === true && count > 0 && !showUnavailable;
}

