# Combat automation: what still needs the GM

**9,258 reminder texts remain across 4,943 mechanics after the compiler's current filtering.** Of these, 2,995 belong to direct action/menu routes this audit can establish. The remaining texts belong to unresolved or other routes; they are retained as a visible backlog, not claimed as lines that definitely reach a fight log.

This uses the actual rider filter and its covers rules (`APP/combat/factory_compiler.py:766`, `APP/combat/factory_compiler.py:778`). Shared reminders on several options count once per mechanic. It is a count of reminder templates across the catalogue. The number shown during a particular fight depends on the characters, choices, repeats, and conditional plug-in messages; this static tool does not run a fight.

| Result | Mechanics |
|---|---:|
| REAL_FULL | 2 |
| PARTIAL | 216 |
| MANUAL | 1,237 |
| UNKNOWN | 3,488 |

**Full** means the audit can establish a direct route and every effect it validates. **Partial** means there is a working component with manual or unresolved parts. **Manual** means no supported generic execution or specific alternative was found. **Unknown** means more evidence is needed. Unknowns are never counted as full.

These totals measure what this bounded static audit can prove. The large Unknown group needs additional implementation contracts or runtime evidence; this report does not claim an overall automation percentage.

1,299 mechanics labelled FULL in the authority are not verified full by this audit. This includes proven gaps and unresolved cases, which the detailed report distinguishes. It is not a count of proven broken abilities.

Feature covers hide 14 distinct sentences. Hiding a reminder alone is not evidence that the rule runs (`APP/combat/factory_compiler.py:778`, `APP/combat/typed_reactions.py:231`). Plug-in claims and conditional reminder emitters are recorded separately in the JSON.

The audit verifies limited plug-in components on 13 mechanics, including 6 whose stored label is below FULL. Their proofs identify the implemented component, source files, and remaining limitations in the detailed records.

## Where the reminder backlog is largest

| Sphere / Path / Foundation | Mechanics | Full | Partial | Manual | Unknown | Reminders |
|---|---:|---:|---:|---:|---:|---:|
| Unassigned (authority has no group) | 219 | 0 | 0 | 198 | 21 | 237 |
| Spirit Companions | 62 | 0 | 0 | 35 | 27 | 178 |
| Sect Stewardship | 52 | 0 | 0 | 45 | 7 | 160 |
| Harvesting Gathering | 58 | 0 | 0 | 43 | 15 | 147 |
| Blacksmith | 44 | 0 | 2 | 18 | 24 | 139 |
| Alchemy | 58 | 0 | 2 | 23 | 33 | 127 |
| Chains | 47 | 0 | 0 | 13 | 34 | 121 |
| Sniper | 51 | 0 | 1 | 10 | 40 | 121 |
| Karma | 48 | 0 | 0 | 15 | 33 | 119 |
| Magma | 40 | 0 | 3 | 9 | 28 | 111 |
| Hunger | 49 | 0 | 0 | 11 | 38 | 106 |
| The Hidden Eye | 65 | 0 | 0 | 11 | 54 | 105 |
| Drunken Style | 53 | 0 | 0 | 11 | 42 | 102 |
| Space | 42 | 1 | 1 | 12 | 28 | 101 |
| Imbuement | 48 | 0 | 0 | 8 | 40 | 99 |
| Scoundrel | 42 | 0 | 0 | 6 | 36 | 98 |
| Air | 51 | 0 | 0 | 12 | 39 | 97 |
| Death | 49 | 0 | 3 | 13 | 33 | 97 |
| Thread | 55 | 0 | 7 | 15 | 33 | 96 |
| Daemonic Cultivation | 42 | 0 | 3 | 12 | 27 | 95 |

## Read and rerun

- Per-mechanic index and all group totals: `AUTOMATION_TRUTH_R1.json`. Its `detail_parts` link to the complete records, exact remaining text, and evidence in `AUTOMATION_TRUTH_R1.d/`.
- Findings, examples, limits, and proposed automation work: `AUTOMATION_TRUTH_AUDIT.md`.
- From `APP`: `python -m tools.automation_truth`. Add `--check` to verify the checked-in reports without writing them.

Input fingerprint: `df050496e9fdc21733901caea21be4a195e2cf11e10dae53d4b9f2cebccf969e`. Reports contain no clock or machine-specific paths.
