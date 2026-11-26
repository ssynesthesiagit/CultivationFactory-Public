// Remove a placed object by its stable map id; callers wrap this mutation in editor history.
export function removePlacedObject(doc, id) {
  const index = (doc.objects || []).findIndex(object => object.id === Number(id));
  if (index < 0) return false;
  doc.objects.splice(index, 1);
  return true;
}

// Token layers stop pointer propagation, so map tools handle object clicks at this token hook.
export function handleObjectToolClick(tool, doc, id, recordChange) {
  if (!['object', 'erase'].includes(tool) || !(doc.objects || []).some(object => object.id === Number(id))) return false;
  recordChange(current => removePlacedObject(current, id));
  return true;
}

export function createObjectTokenPointerHandler({getTool, getDocument, change, onOtherToken}) {
  return (id, event) => {
    const isObject = String(id).startsWith("object:");
    if (isObject && event.button === 0
        && handleObjectToolClick(getTool(), getDocument(), String(id).slice("object:".length), change)) return;
    if (isObject && ["object", "erase"].includes(getTool())) return;
    onOtherToken?.(id, event);
  };
}
