import test from "node:test";
import assert from "node:assert/strict";
import {rulesTextFor} from "../static/tabletop/rules.js";

const printed = "Manifest the armament beside you. It lasts until dismissed.";

test("generated action modes use their own printed text or name the parent mode", () => {
  const sheet = {library: {groups: [{entries: [{name: "Domain Armament", text: printed}]}]}};
  assert.match(rulesTextFor(sheet, {id: "act:generated.manifest", label: "Domain Armament: Manifest"}),
    /^For Manifest:\n\nManifest the armament/);

  const variant = {library: {groups: [{entries: [
    {name: "Domain Armament: Manifest", text: "Create the armament."},
    {name: "Domain Armament", text: printed},
  ]}]}};
  assert.equal(rulesTextFor(variant, {label: "Domain Armament: Manifest"}), "Create the armament.");
});

test("action source and variant IDs resolve their library button text", () => {
  const sheet = {library: {groups: [{entries: [{name: "Reservoir", text: printed, button_id: "act:source.reservoir"}]}]}};
  assert.equal(rulesTextFor(sheet, {label: "Reservoir: Golden Core", variant_of: "act:source.reservoir"}), printed);
  assert.equal(rulesTextFor(sheet, {label: "Golden Core", combat: {source_definition_id: "act:source.reservoir"}}), printed);
});

// A row's own help is shown first, and distinct printed library rules still follow it.
test("contextual help supplements the printed library rules instead of replacing them", () => {
  const sheet = {library: {groups: [{entries: [{button_id: "act:armament", name: "Domain Armament", text: printed}]}]}};
  const row = {id: "act:armament", label: "Domain Armament", description: "Choose which armament to manifest."};
  const combined = rulesTextFor(sheet, row);
  assert.match(combined, /^Choose which armament to manifest\./);
  assert.match(combined, /Manifest the armament beside you\./);
  assert.equal(combined, "Choose which armament to manifest.\n\n" + printed);

  // Generated modes keep their own printed text, with contextual help still in front.
  const mode = rulesTextFor(sheet, {label: "Domain Armament: Manifest", description: "Free choice, kept until you change it."});
  assert.match(mode, /^Free choice, kept until you change it\./);
  assert.match(mode, /For Manifest:\n\nManifest the armament beside you\./);

  // Identical text is shown once rather than doubled.
  assert.equal(rulesTextFor(sheet, {id: "act:armament", label: "Domain Armament", description: printed}), printed);
  // With no library entry at all, only the contextual help is shown.
  assert.equal(rulesTextFor({library: {groups: []}}, {label: "Unknown", description: printed}), printed);
});
