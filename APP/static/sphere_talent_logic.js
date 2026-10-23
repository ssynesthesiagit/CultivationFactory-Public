(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.TianxiaSphereTalentLogic = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  function uniqueIds(values) {
    const result = [];
    const seen = new Set();
    for (const value of Array.isArray(values) ? values : []) {
      if (typeof value !== "string" || !value || seen.has(value)) continue;
      seen.add(value);
      result.push(value);
    }
    return result;
  }

  function uniqueChoices(choices) {
    const result = [];
    const seen = new Set();
    for (const choice of Array.isArray(choices) ? choices : []) {
      const choiceId = choice && typeof choice.choice_id === "string" ? choice.choice_id : "";
      if (!choiceId || seen.has(choiceId)) continue;
      seen.add(choiceId);
      result.push(choice);
    }
    return result;
  }

  function talentSphereIds(index, talentId) {
    return uniqueIds(index && index.by_talent ? index.by_talent[talentId] : []);
  }

  function talentIdsForSphere(index, sphereId) {
    return uniqueIds(index && index.by_sphere ? index.by_sphere[sphereId] : []);
  }

  function removeSphereSelection(sphereIds, talentIds, sphereId, index) {
    const remainingSpheres = uniqueIds(sphereIds).filter(id => id !== sphereId);
    const remainingSphereSet = new Set(remainingSpheres);
    const keptTalents = [];
    const removedTalentIds = [];
    for (const talentId of uniqueIds(talentIds)) {
      const supports = talentSphereIds(index, talentId);
      if (supports.includes(sphereId) && supports.length && !supports.some(id => remainingSphereSet.has(id))) {
        removedTalentIds.push(talentId);
      } else {
        keptTalents.push(talentId);
      }
    }
    return {
      sphere_ids: remainingSpheres,
      talent_ids: keptTalents,
      removed_talent_ids: removedTalentIds,
    };
  }

  function normalizeLockedSelections(locked) {
    const result = {};
    if (!locked || typeof locked !== "object") return result;
    for (const [slotId, values] of Object.entries(locked)) {
      const normalized = uniqueIds(values);
      if (normalized.length) result[slotId] = normalized;
    }
    return result;
  }

  return {
    normalizeLockedSelections,
    removeSphereSelection,
    talentIdsForSphere,
    talentSphereIds,
    uniqueChoices,
    uniqueIds,
  };
});
