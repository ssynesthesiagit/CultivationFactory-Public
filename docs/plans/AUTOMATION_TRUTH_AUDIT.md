# Automation truth audit — P20261005-12

## Scope and evidence

This is a static audit of the committed typed authority, compile-time rider filter, trigger classifier, executor dispatch, and registered plug-in source. It does not change game behavior, data, plug-ins, saved fights, or lock files. It does not instantiate a fight or call a model.

The authority contains 4,943 mechanics. The JSON records every one and preserves UNKNOWN results. Engine registration is necessary but not sufficient: the dispatcher falls back to a GM rider for absent handlers (`APP/combat/typed_executor.py:4809`), while feature compilation can replace ordinary actions (`APP/combat/factory_compiler.py:2382`).

### What the reminder count means

The primary count applies `_gm_lines` to each included source branch (`APP/combat/factory_compiler.py:766`). It respects whole-entry feature overrides in sorted shard order (`APP/combat/typed_reactions.py:38`), exact normalized sentence covers, option-specific riders, choice labels, and the action menu cap (`APP/combat/factory_compiler.py:2461`). Identical text on several options counts once for its mechanic; the JSON also reports the number before this deduplication.

A generic reaction stores its effect tree but does not copy the mechanic's rider list (`APP/combat/factory_compiler.py:1648`). Skipped passives, modifiers, and feature block replacements likewise are not ordinary action rider surfaces. Their retained source reminders are labelled projection-only in each result. The direct-action subtotal excludes those unresolved routes. Conditional GM_RIDER calls inside plug-ins are inventoried separately when statically visible; no transcript frequency is inferred.

A single exact per-fight line total cannot be obtained without a party, build, choices, and event sequence. Reporting the whole catalogue sum as an actual fight log would repeat the original metric error. The useful static owner metric is the reminder backlog, alongside its direct-action subtotal, silent/unresolved gaps, and plug-in reminder inventory.

### Boundaries of REAL_FULL

REAL_FULL uses conservative, parameter-aware effect validators and a proven ordinary action route. It is a bounded static result, not a semantic proof that typing preserved every sentence of the print. No registered plug-in, ID match, empty reminder list, stored coverage label, or already_applied declaration earns full credit on its own. Unknown effect parameters, contextual reactions, modifiers, activation requirements, and replacement blocks retain explicit uncertainty. This audit does not execute extension hooks.

The input universe also contains build choices and outside-combat procedures. Their presence in the manual/unknown totals is not evidence of a broken combat action. Every record's economy and source remain visible for review; none is silently dropped from the denominator.

The authority JSON is intentionally stored on one line. Its source references therefore correctly use `:1`; each record also includes an exact JSON pointer and mechanic ID. No artificial line numbers are assigned.

## Stored FULL findings

There are 1,299 stored-FULL records not verified as REAL_FULL. Categories below overlap; counts are mechanics, not effect rows. An unresolved case is not automatically a proven false claim. Each example lists its actual result, ability ID, authority location, and the relevant engine evidence.

### Activation requirement — 2

- `TAL_AXES_HEWING_STRIKE` — **PARTIAL**. The printed activation requirement needs a character/target-specific check before full coverage can be claimed. Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/factory_compiler.py:2385`.
- `tianxia.subpath.body.adamant_thunderbolt_body.feature.adamantine_descent` — **UNKNOWN**. The printed activation requirement needs a character/target-specific check before full coverage can be claimed. Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/factory_compiler.py:2385`.
Only 2 example(s) exist in this category; no additional examples are invented.

### Already applied declaration — 5

- `SHIELD_BASE_SHIELD_TRAINING` — **UNKNOWN**. already_applied skips generic compilation without producing a reaction or passive row here; its external implementation requires separate proof. Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/typed_reactions.py:223`.
- `TAL_FENCING_FEINT` — **UNKNOWN**. already_applied skips generic compilation without producing a reaction or passive row here; its external implementation requires separate proof. Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/typed_reactions.py:223`.
- `TAL_WRESTLING_TACKLE` — **UNKNOWN**. already_applied skips generic compilation without producing a reaction or passive row here; its external implementation requires separate proof. Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/typed_reactions.py:223`.

### Area or trigger context — 11

- `TAL_DEATH_WITHERING_HAND` — **PARTIAL**. The area or conditional activation needs compiled geometry/eligibility beyond the effect-kind proof. Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/factory_compiler.py:862`.
- `TAL_UNMAKING_RUIN_WAVE` — **UNKNOWN**. The area or conditional activation needs compiled geometry/eligibility beyond the effect-kind proof. Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/factory_compiler.py:862`.
- `TAL_UNMAKING_THIRD_RUIN_FORM_SEVERING_WAVE` — **UNKNOWN**. The area or conditional activation needs compiled geometry/eligibility beyond the effect-kind proof. Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/factory_compiler.py:862`.

### Compiled spec unproven — 79

- `DISEASE_BASE_RAISE_THE_QUARANTINE_VEIL` — **UNKNOWN**. This handler needs a compiled zone/summon specification and a matching lifecycle route. Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/typed_executor.py:4728`, `APP/combat/typed_executor.py:4590`.
- `EARTH_BASE_SET_FOUNDATION` — **UNKNOWN**. This handler needs a compiled zone/summon specification and a matching lifecycle route. Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/typed_executor.py:4728`, `APP/combat/typed_executor.py:4590`.
- `FIRE_BASE_CONFLAGRATION` — **UNKNOWN**. This handler needs a compiled zone/summon specification and a matching lifecycle route. Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/typed_executor.py:4728`, `APP/combat/typed_executor.py:4590`.

### Compiler special case — 3

- `TAL_DUAL_WIELDING_AMBIDEXTERITY` — **UNKNOWN**. The compiler lists this mechanic as handled in code; the owning build and weapon combination are required to prove its behavior. Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/factory_compiler.py:3908`.
- `TAL_DUAL_WIELDING_GREATER_BLADES` — **UNKNOWN**. The compiler lists this mechanic as handled in code; the owning build and weapon combination are required to prove its behavior. Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/factory_compiler.py:3908`.
- `TAL_DUAL_WIELDING_PAIRED_RHYTHM` — **UNKNOWN**. The compiler lists this mechanic as handled in code; the owning build and weapon combination are required to prove its behavior. Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/factory_compiler.py:3908`.

### Context only effect — 54

- `FIRE_BASE_IGNITE` — **PARTIAL**. This kind requires a specific reaction/checkpoint or extension reader; its registration alone is not execution proof. Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/typed_executor.py:4767`.
- `TAL_AIR_CLOUD_SLEEVE_GUARD` — **UNKNOWN**. This kind requires a specific reaction/checkpoint or extension reader; its registration alone is not execution proof. Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/typed_executor.py:4767`.
- `TAL_AXES_HAFT_GUARD` — **UNKNOWN**. This kind requires a specific reaction/checkpoint or extension reader; its registration alone is not execution proof. Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/typed_executor.py:4767`.

### Cost or use limit — 46

- `BLOOD_BASE_COAGULATE` — **PARTIAL**. The printed payment or use limit requires a character resource/reset context that this static validator does not prove. Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/factory_compiler.py:1529`.
- `TAL_BERSERKER_COURT_OF_THE_UNBROKEN_WARPATH` — **UNKNOWN**. The printed payment or use limit requires a character resource/reset context that this static validator does not prove. Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/factory_compiler.py:1529`.
- `TAL_BERSERKER_WAR_GOD_INCARNATION` — **UNKNOWN**. The printed payment or use limit requires a character resource/reset context that this static validator does not prove. Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/factory_compiler.py:1529`.

### Deferred route unproven — 18

- `TAL_FATE_CONSEQUENCE_EDICT` — **UNKNOWN**. Deferred effects need an admitted registration/watch or compiler rewrite; ordinary dispatch skips them. Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/typed_executor.py:4767`, `APP/combat/typed_executor.py:2408`, `APP/combat/typed_executor.py:2431`.
- `TAL_FATE_PURITY_EDICT` — **UNKNOWN**. Deferred effects need an admitted registration/watch or compiler rewrite; ordinary dispatch skips them. Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/typed_executor.py:4767`, `APP/combat/typed_executor.py:2408`, `APP/combat/typed_executor.py:2431`.
- `TAL_FATE_SOOTHE_WORD` — **UNKNOWN**. Deferred effects need an admitted registration/watch or compiler rewrite; ordinary dispatch skips them. Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/typed_executor.py:4767`, `APP/combat/typed_executor.py:2408`, `APP/combat/typed_executor.py:2431`.

### Effect parameters unproven — 219

- `ASH_BASE_CINDER_BRAND` — **PARTIAL**. Exact damage support requires one known type; absent, combined or choice types need separate proof. Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/typed_executor.py:4681`, `APP/combat/typed_executor.py:1560`.
- `ASH_TAL_ASHEN_BURIAL` — **UNKNOWN**. Unreviewed or unconsumed effect field(s): dc Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/typed_executor.py:4679`, `APP/combat/typed_executor.py:1735`.
- `ASH_TAL_CINDER_BURST` — **UNKNOWN**. Unreviewed or unconsumed effect field(s): dc Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/typed_executor.py:4679`, `APP/combat/typed_executor.py:1735`.

### Empty effects — 357

- `ASH_BASE_ASHFALL` — **MANUAL**. The selected authority branches contain no executable effect rows; stored coverage is not execution evidence. Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/factory_compiler.py:1691`, `APP/combat/factory_compiler.py:2507`.
- `BRUTE_BASE_SPECIAL_ATTACKS` — **MANUAL**. The selected authority branches contain no executable effect rows; stored coverage is not execution evidence. Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/factory_compiler.py:1691`, `APP/combat/factory_compiler.py:2507`.
- `DREAMS_BASE_DREAMSCAPE` — **MANUAL**. The selected authority branches contain no executable effect rows; stored coverage is not execution evidence. Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/factory_compiler.py:1691`, `APP/combat/factory_compiler.py:2507`.

### Empty variant — 361

- `ASH_BASE_ASHFALL` — **MANUAL**. Included branch base has no effect rows; other options cannot supply its implementation. Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/factory_compiler.py:2461`.
- `BRUTE_BASE_SPECIAL_ATTACKS` — **MANUAL**. Included branch base has no effect rows; other options cannot supply its implementation. Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/factory_compiler.py:2461`.
- `DREAMS_BASE_DREAMSCAPE` — **MANUAL**. Included branch base has no effect rows; other options cannot supply its implementation. Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/factory_compiler.py:2461`.

### Explicit rider — 1

- `tianxia.talent.disease.world_of_pestilence` — **UNKNOWN**. An explicit rider is narrated through the fallback, not resolved mechanically. Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/typed_executor.py:4146`, `APP/combat/typed_executor.py:4767`.
Only 1 example(s) exist in this category; no additional examples are invented.

### Extension or unknown kind — 230

- `ASH_BASE_CINDER_BRAND` — **PARTIAL**. An extension registers this kind, but its parameter semantics and admitting route are unproved. Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/ext/ash_core.py:156`, `APP/combat/ext/ash_core.py:157`.
- `BLOOD_BASE_BLOOD_THREAD` — **PARTIAL**. An extension registers this kind, but its parameter semantics and admitting route are unproved. Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/ext/blood_bloodied.py:55`, `APP/combat/ext/blood_bloodied.py:56`.
- `BLOOD_BASE_COAGULATE` — **PARTIAL**. An extension registers this kind, but its parameter semantics and admitting route are unproved. Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/ext/blood_riders.py:133`, `APP/combat/ext/blood_riders.py:134`.

### Feature block context — 432

- `ATHLETICS_BASE_COORDINATED_MOVEMENT` — **UNKNOWN**. Feature block 'motion' may replace or supplement normal compilation; declarations and covers alone do not prove its complete behavior. Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/factory_compiler.py:2382`, `APP/combat/rules/feature_blocks.json:51`, `APP/combat/typed_reactions.py:89`.
- `BEASTMASTERY_BASE_RIDER_PACKAGE` — **UNKNOWN**. Feature block 'mounts' may replace or supplement normal compilation; declarations and covers alone do not prove its complete behavior. Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/factory_compiler.py:2382`, `APP/combat/rules/feature_blocks.d/mounts.json:3`, `APP/combat/typed_reactions.py:89`.
- `FIRE_TAL_BURNING_WEAPON` — **UNKNOWN**. Feature block 'auto77_fire' may replace or supplement normal compilation; declarations and covers alone do not prove its complete behavior. Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/factory_compiler.py:2382`, `APP/combat/rules/feature_blocks.d/auto77_fire.json:5`, `APP/combat/typed_reactions.py:89`.

### Instant effect duration unproven — 11

- `HUNGER_BASE_DIGESTIVE_MANTLE` — **UNKNOWN**. This handler does not itself consume a noninstant effect duration; expiry/repetition needs a separate lifecycle proof. Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/typed_executor.py:4696`, `APP/combat/typed_executor.py:3419`.
- `LIFE_BASE_BORROWED_BREATH` — **UNKNOWN**. This handler does not itself consume a noninstant effect duration; expiry/repetition needs a separate lifecycle proof. Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/typed_executor.py:4696`, `APP/combat/typed_executor.py:3419`.
- `TAL_FATE_MARKED_BY_THE_LEDGER` — **UNKNOWN**. This handler does not itself consume a noninstant effect duration; expiry/repetition needs a separate lifecycle proof. Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/typed_executor.py:4679`, `APP/combat/typed_executor.py:1735`.

### Malformed effect tree — 1

- `TAL_THREAD_MERIDIAN_STITCH` — **PARTIAL**. An effect branch is not a list. Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/typed_executor.py:4767`.
Only 1 example(s) exist in this category; no additional examples are invented.

### Modifier context — 304

- `BEASTMASTERY_BASE_RIDER_PACKAGE` — **UNKNOWN**. This modifier needs an owned destination, attachment timing, and variant selection; its standalone effects do not establish execution. Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/factory_compiler.py:5394`.
- `FIRE_TAL_BURNING_WEAPON` — **UNKNOWN**. This modifier needs an owned destination, attachment timing, and variant selection; its standalone effects do not establish execution. Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/factory_compiler.py:5394`.
- `TAL_AIR_CUTTING_WIND` — **UNKNOWN**. This modifier needs an owned destination, attachment timing, and variant selection; its standalone effects do not establish execution. Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/factory_compiler.py:5394`.

### No direct action — 446

- `ATHLETICS_BASE_COORDINATED_MOVEMENT` — **UNKNOWN**. Economy 'passive' does not produce an ordinary typed action; a feature, modifier, or hook is required. Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/factory_compiler.py:2385`.
- `BRUTE_BASE_SPECIAL_ATTACKS` — **MANUAL**. Economy 'passive' does not produce an ordinary typed action; a feature, modifier, or hook is required. Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/factory_compiler.py:2385`.
- `DREAMS_BASE_DREAM_SEED` — **MANUAL**. Economy 'passive' does not produce an ordinary typed action; a feature, modifier, or hook is required. Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/factory_compiler.py:2385`.

### Parent route unproven — 615

- `ASH_TAL_ASHEN_BURIAL` — **UNKNOWN**. The parent at effects[0] does not prove delivery of this on_fail branch. Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/typed_executor.py:4767`.
- `ASH_TAL_CINDER_BURST` — **UNKNOWN**. The parent at effects[0] does not prove delivery of this on_fail branch. Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/typed_executor.py:4767`.
- `ASH_TAL_CREMATION_PRISON` — **UNKNOWN**. The parent at effects[0] does not prove delivery of this on_fail branch. Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/typed_executor.py:4767`.

### Range context — 15

- `GLASS_BASE_FAULTLINE_STRIKE` — **PARTIAL**. This range requires character-, weapon-, or level-specific resolution outside the reviewed literal range forms. Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/factory_compiler.py:862`.
- `PUPPETRY_BASE_PUPPET_STRIKE` — **PARTIAL**. This range requires character-, weapon-, or level-specific resolution outside the reviewed literal range forms. Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/factory_compiler.py:862`.
- `SPEAR_BASE_SPEAR_THRUST` — **PARTIAL**. This range requires character-, weapon-, or level-specific resolution outside the reviewed literal range forms. Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/factory_compiler.py:862`.

### Reaction context — 112

- `BEAUTY_BASE_TURN_THE_BLADE_ASIDE` — **UNKNOWN**. The trigger is runnable, but character resources, recipient context, and hook-specific effect handling are not proved by this static audit. Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/factory_compiler.py:1648`, `APP/combat/factory_compiler.py:1697`.
- `RADIANCE_TAL_DAWNLIT_REBUKE` — **UNKNOWN**. The trigger is runnable, but character resources, recipient context, and hook-specific effect handling are not proved by this static audit. Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/factory_compiler.py:1648`, `APP/combat/factory_compiler.py:1697`.
- `SHIELD_BASE_ACTIVE_DEFENSE` — **UNKNOWN**. The trigger is runnable, but character resources, recipient context, and hook-specific effect handling are not proved by this static audit. Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/factory_compiler.py:1648`, `APP/combat/factory_compiler.py:1697`.

### Resource binding unproven — 21

- `TAL_ALCHEMY_QI_INFUSION_PILL` — **UNKNOWN**. Resource effects require compiler resolution and an actually held recipient resource; raw effect type is insufficient. Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/typed_executor.py:4720`, `APP/combat/typed_executor.py:4162`.
- `TAL_ALCHEMY_STAMINA_BOILING_PILL` — **UNKNOWN**. Resource effects require compiler resolution and an actually held recipient resource; raw effect type is insufficient. Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/typed_executor.py:4720`, `APP/combat/typed_executor.py:4162`.
- `TAL_DAEMONIC_CULTIVATION_BLOODLESS_DEVOURING` — **UNKNOWN**. Resource effects require compiler resolution and an actually held recipient resource; raw effect type is insufficient. Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/typed_executor.py:4720`, `APP/combat/typed_executor.py:4162`.

### Retained gm lines — 7

- `TAL_DREAM_DREAM_MIRROR` — **UNKNOWN**. The compiler's rider filter retains 2 distinct reminder texts for this mechanic. Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/factory_compiler.py:766`.
- `THREAD_BASE_DRAW_THE_LINE` — **PARTIAL**. The compiler's rider filter retains 2 distinct reminder texts for this mechanic. Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/factory_compiler.py:766`.
- `tianxia.subpath.qi.calligraphy_cultivator.feature.great_character` — **UNKNOWN**. The compiler's rider filter retains 4 distinct reminder texts for this mechanic. Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/factory_compiler.py:766`.

### Special target — 10

- `GLASS_BASE_FAULTLINE_STRIKE` — **PARTIAL**. The printed target is a special entity or equipment; a generic effect handler does not establish that target's support. Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/factory_compiler.py:862`.
- `GLASS_BASE_GLASS_SHARD` — **PARTIAL**. The printed target is a special entity or equipment; a generic effect handler does not establish that target's support. Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/factory_compiler.py:862`.
- `ICE_BASE_SHARD_NEEDLE` — **PARTIAL**. The printed target is a special entity or equipment; a generic effect handler does not establish that target's support. Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/factory_compiler.py:862`.

### Unbound half damage — 9

- `SAND_BASE_SCOURING_HAND` — **PARTIAL**. half_damage has no standalone effect; only a matching save-success or reaction reduction path consumes it. Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/typed_executor.py:1581`, `APP/combat/typed_executor.py:1585`.
- `TAL_UNMAKING_RUIN_WAVE` — **UNKNOWN**. half_damage has no standalone effect; only a matching save-success or reaction reduction path consumes it. Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/typed_executor.py:1581`, `APP/combat/typed_executor.py:1585`.
- `TAL_UNMAKING_THIRD_RUIN_FORM_SEVERING_WAVE` — **UNKNOWN**. half_damage has no standalone effect; only a matching save-success or reaction reduction path consumes it. Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/typed_executor.py:1581`, `APP/combat/typed_executor.py:1585`.

### Uncompiled reaction — 31

- `ASH_TAL_SMOTHERING_CLOUD` — **MANUAL**. No trigger reading passes the engine's runnable gate; a generic reaction is not compiled. Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/factory_compiler.py:1676`.
- `ASH_TAL_SOOT_IN_LUNGS` — **MANUAL**. No trigger reading passes the engine's runnable gate; a generic reaction is not compiled. Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/factory_compiler.py:1676`.
- `PROTECTION_BASE_SUCCOR` — **MANUAL**. No trigger reading passes the engine's runnable gate; a generic reaction is not compiled. Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/factory_compiler.py:1676`.

### Unreviewed core form — 91

- `ASH_BASE_CINDER_BRAND` — **PARTIAL**. Core registration exists, but this effect's parameter semantics are outside the audited subset. Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/typed_executor.py:4714`, `APP/combat/typed_executor.py:3500`.
- `DISEASE_BASE_RAISE_THE_QUARANTINE_VEIL` — **UNKNOWN**. Core registration exists, but this effect's parameter semantics are outside the audited subset. Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/typed_executor.py:4718`, `APP/combat/typed_executor.py:4056`.
- `FIRE_BASE_IGNITE` — **PARTIAL**. Core registration exists, but this effect's parameter semantics are outside the audited subset. Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/typed_executor.py:4692`, `APP/combat/typed_executor.py:2981`.

### Verified plugin component — 7

- `STARS_TAL_HEAVEN_FALLING_STAR` — **PARTIAL**. A reviewed plug-in component has a compiled ownership route and a source-backed runtime consumer; its full printed ability remains only partly established. Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/ext/__init__.py:7286`, `APP/combat/ext/__init__.py:7458`, `APP/combat/ext/__init__.py:7572`, `APP/combat/ext/objects.py:209`, `APP/combat/ext/objects.py:218`, `APP/combat/ext/objects.py:678`, `APP/combat/ext/objects.py:691`, `APP/combat/ext/objects.py:707`, `APP/combat/ext/objects.py:713`, `APP/combat/ext/objects.py:724`, `APP/combat/object_rules.py:136`, `APP/combat/object_rules.py:157`, `APP/combat/rules/feature_blocks.d/sysv2_objects.json:101`, `APP/combat/typed_executor.py:5104`, `APP/combat/typed_reactions.py:242`, `APP/combat/typed_reactions.py:38`, `APP/combat/typed_reactions.py:89`.
- `TAL_BERSERKER_WORLD_BREAKING_RAMPAGE` — **PARTIAL**. A reviewed plug-in component has a compiled ownership route and a source-backed runtime consumer; its full printed ability remains only partly established. Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/ext/__init__.py:7286`, `APP/combat/ext/__init__.py:7458`, `APP/combat/ext/__init__.py:7572`, `APP/combat/ext/objects.py:209`, `APP/combat/ext/objects.py:218`, `APP/combat/ext/objects.py:678`, `APP/combat/ext/objects.py:691`, `APP/combat/ext/objects.py:707`, `APP/combat/ext/objects.py:713`, `APP/combat/ext/objects.py:724`, `APP/combat/object_rules.py:136`, `APP/combat/object_rules.py:157`, `APP/combat/rules/feature_blocks.d/sysv2_objects.json:153`, `APP/combat/typed_executor.py:5104`, `APP/combat/typed_reactions.py:242`, `APP/combat/typed_reactions.py:38`, `APP/combat/typed_reactions.py:89`.
- `TAL_DAEMONIC_CULTIVATION_DEMON_BONE_REGENERATION` — **PARTIAL**. A reviewed plug-in component has a compiled ownership route and a source-backed runtime consumer; its full printed ability remains only partly established. Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/ext/__init__.py:7286`, `APP/combat/ext/__init__.py:7458`, `APP/combat/ext/__init__.py:7572`, `APP/combat/ext/ironroot_daemonic.py:28`, `APP/combat/ext/ironroot_daemonic.py:35`, `APP/combat/ext/ironroot_daemonic.py:40`, `APP/combat/ext/spend_choice.py:30`, `APP/combat/rules/feature_blocks.d/ironroot.json:3`, `APP/combat/typed_reactions.py:242`, `APP/combat/typed_reactions.py:3223`, `APP/combat/typed_reactions.py:38`, `APP/combat/typed_reactions.py:89`.

### Weapon profile unproven — 5

- `SPEAR_BASE_SPEAR_THRUST` — **PARTIAL**. weapon_damage needs proof of the compiler-selected weapon profile. Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/typed_executor.py:1259`, `APP/combat/typed_executor.py:1968`, `APP/combat/typed_executor.py:1188`.
- `TAL_SPEAR_INTERCEPTING_THRUST` — **UNKNOWN**. weapon_damage needs proof of the compiler-selected weapon profile. Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/typed_executor.py:1259`, `APP/combat/typed_executor.py:1968`, `APP/combat/typed_executor.py:1188`.
- `TAL_SPEAR_ONE_LINE_CANNOT_BE_CROSSED` — **UNKNOWN**. weapon_damage needs proof of the compiler-selected weapon profile. Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/typed_executor.py:1259`, `APP/combat/typed_executor.py:1968`, `APP/combat/typed_executor.py:1188`.

### Weapon damage type override — 0 in this authority

The brief names this risk, but no current effect combines weapon_damage with a damage_types override in this snapshot. The regression is synthetic. The auditor checks the field interaction instead of inventing three examples.

## Plug-in automation omitted by the stored label

These are evidence categories, not automatic FULL promotions. A compile_block registration must still return applicable rows and have a reachable consumer; the engine explicitly checks returned rows (`APP/combat/typed_reactions.py:231`). Covers are a separate declaration (`APP/combat/factory_compiler.py:778`).

| Evidence among records not labelled FULL | Mechanics |
|---|---:|
| non full with covers suppression | 6 |
| non full with feature block | 481 |
| non full with plugin evidence | 1241 |
| non full with verified plugin component | 6 |

### Covered rider sentences

- `BLACKSMITH_BASE_HAMMER_THE_MARK` (Hammer the Mark): stored CORE_WITH_RIDERS; audit PARTIAL; 1 covered sentence(s), 16 claim record(s). Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/rules/feature_blocks.d/blacksmith.json:13`, `APP/combat/ext/blacksmith_forge.py:1049`, `APP/combat/typed_executor.py:506`, `APP/combat/typed_executor.py:507`, `APP/combat/ext/blacksmith_forge.py:1051`.
- `TAL_BERSERKER_CULTIVATION_SUNDER` (Cultivation Sunder): stored RIDERS_ONLY; audit UNKNOWN; 5 covered sentence(s), 5 claim record(s). Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/rules/feature_blocks.d/body.json:28`, `APP/combat/ext/gu_berserker.py:179`, `APP/combat/typed_executor.py:506`, `APP/combat/typed_executor.py:507`, `APP/combat/ext/gu_berserker.py:242`.
- `TAL_SWORD_LIFE_SEVERING_SWORD` (Life-Severing Sword): stored CORE_WITH_RIDERS; audit UNKNOWN; 1 covered sentence(s), 15 claim record(s). Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/rules/feature_blocks.d/sword.json:33`, `APP/combat/ext/sword_core.py:83`, `APP/combat/ext/sword_core.py:84`, `APP/combat/ext/sword_core.py:88`, `APP/combat/ext/sword_core.py:114`, `APP/combat/ext/sword_core.py:121`, `APP/combat/ext/sword_core.py:152`, `APP/combat/ext/sword_core.py:153`, `APP/combat/ext/sword_core.py:157`, `APP/combat/ext/sword_core.py:161`, `APP/combat/ext/sword_core.py:58`, `APP/combat/ext/sword_core.py:98`.

### Registered effect, hook, or block claims

- `AIR_BASE_GATHER_CURRENT` (Gather Current): stored CORE_WITH_RIDERS; audit UNKNOWN; 0 covered sentence(s), 1 claim record(s). Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/ext/altitude_abilities.py:130`, `APP/combat/ext/altitude_abilities.py:131`, `APP/combat/ext/altitude_abilities.py:132`, `APP/combat/ext/altitude_abilities.py:36`.
- `AIR_BASE_WIND_LASH` (Wind Lash): stored CORE_WITH_RIDERS; audit UNKNOWN; 0 covered sentence(s), 1 claim record(s). Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/ext/air_currents.py:443`, `APP/combat/ext/air_currents.py:444`, `APP/combat/ext/air_currents.py:450`, `APP/combat/ext/air_currents.py:79`.
- `ALCHEMY_BASE_FIELD_FORMULA` (Field Formula): stored CORE_WITH_RIDERS; audit PARTIAL; 0 covered sentence(s), 12 claim record(s). Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/ext/alchemy_riders.py:339`, `APP/combat/typed_executor.py:506`, `APP/combat/typed_executor.py:507`, `APP/combat/ext/alchemy_riders.py:361`.

### Feature blocks outside stored FULL

- `EARTH_BASE_SPENDING_A_BURDEN_MARK` (Spending a Burden Mark): stored CORE_WITH_RIDERS; audit UNKNOWN; 0 covered sentence(s), 21 claim record(s). Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/rules/feature_blocks.d/riders_lane9.json:327`, `APP/combat/ext/earth_responses.py:69`, `APP/combat/ext/earth_responses.py:70`, `APP/combat/ext/earth_responses.py:71`, `APP/combat/ext/earth_responses.py:284`, `APP/combat/ext/earth_responses.py:285`, `APP/combat/ext/earth_responses.py:286`, `APP/combat/ext/earth_responses.py:54`, `APP/combat/ext/earth_responses.py:66`, `APP/combat/ext/earth_responses.py:91`.
- `GLASS_BASE_FAULTLINE_MARKS` (Faultline Marks): stored CORE_WITH_RIDERS; audit UNKNOWN; 0 covered sentence(s), 4 claim record(s). Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/rules/feature_blocks.d/elements.json:3`, `APP/combat/ext/elements_marks.py:34`, `APP/combat/ext/elements_marks.py:35`, `APP/combat/ext/elements_marks.py:36`, `APP/combat/ext/glass_refraction.py:373`, `APP/combat/ext/glass_refraction.py:374`, `APP/combat/ext/glass_refraction.py:383`, `APP/combat/ext/glass_refraction.py:634`.
- `GLASS_BASE_REFRACTION_RESPONSES` (Refraction Responses): stored CORE_WITH_RIDERS; audit UNKNOWN; 0 covered sentence(s), 14 claim record(s). Evidence: `APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json:1`, `APP/combat/rules/feature_blocks.d/riders_lane9.json:261`, `APP/combat/ext/glass_refraction.py:78`, `APP/combat/ext/glass_refraction.py:79`, `APP/combat/ext/glass_refraction.py:80`, `APP/combat/ext/glass_pane.py:561`, `APP/combat/ext/glass_pane.py:568`, `APP/combat/ext/glass_pane.py:592`, `APP/combat/ext/glass_pane.py:593`, `APP/combat/ext/glass_pane.py:600`.

### Source-reviewed components (partial credit)

13 mechanics have a component whose block shape, winning feature row, and compiler/consumer implementation have been reviewed. These proofs are bound to exact source SHA-256 values. Source changes invalidate the proof until reviewed; a matching registration by itself is insufficient. All of these remain PARTIAL because complete print fidelity and all contexts are outside the proof.

| Component family | Mechanics | Below stored FULL |
|---|---:|---:|
| grounding_breath | 1 | 1 |
| ironroot_demon_bone_regen | 1 | 0 |
| object_damage | 11 | 5 |

- `TAL_LIGHTNING_GROUNDING_BREATH`: The matching feature compiles an ownership marker. The typed-save dispatcher supplies named failed-save effects; the registered consumer checks that marker and the usage flag, recognizes supported shock/condition cases, and adds the subject's proficiency bonus through the save-modifier accumulator. Evidence: `APP/combat/ext/__init__.py:7286`, `APP/combat/ext/__init__.py:7458`, `APP/combat/ext/__init__.py:7572`, `APP/combat/ext/lightning_grounding.py:32`, `APP/combat/ext/lightning_grounding.py:36`, `APP/combat/ext/lightning_grounding.py:48`, `APP/combat/rules/feature_blocks.d/auto_lane5.json:25`, `APP/combat/typed_executor.py:1639`, `APP/combat/typed_executor.py:1741`, `APP/combat/typed_reactions.py:242`, `APP/combat/typed_reactions.py:38`, `APP/combat/typed_reactions.py:89`. Limits: A component implementation is verified in eligible ordinary contexts; complete printed-rule fidelity is not established. No fight was run. Availability, all choices, all plug-in interactions, and every saved character configuration remain unverified. Covers text is not execution proof and residual reminders are not retired by this component assessment. Only named typed-save cases supported by the dispatcher are covered; damage types still awaiting a choice may not qualify. Optional consent, prevention of an already-counted proficiency bonus and all flag-reset/lifecycle cases are not certified by this component proof.
- `TAL_DAEMONIC_CULTIVATION_DEMON_BONE_REGENERATION`: The matching feature compiles an ownership marker with the character's key modifier. The strict turn-start dispatcher reaches a consumer that checks living/injured state, one available Devoured Essence and the Demon Seed stance; an accepted spend choice invokes one resource spend and 1d8-plus-key-modifier healing. Evidence: `APP/combat/ext/__init__.py:7286`, `APP/combat/ext/__init__.py:7458`, `APP/combat/ext/__init__.py:7572`, `APP/combat/ext/ironroot_daemonic.py:28`, `APP/combat/ext/ironroot_daemonic.py:35`, `APP/combat/ext/ironroot_daemonic.py:40`, `APP/combat/ext/spend_choice.py:30`, `APP/combat/rules/feature_blocks.d/ironroot.json:3`, `APP/combat/typed_reactions.py:242`, `APP/combat/typed_reactions.py:3223`, `APP/combat/typed_reactions.py:38`, `APP/combat/typed_reactions.py:89`. Limits: A component implementation is verified in eligible ordinary contexts; complete printed-rule fidelity is not established. No fight was run. Availability, all choices, all plug-in interactions, and every saved character configuration remain unverified. Covers text is not execution proof and residual reminders are not retired by this component assessment. An eligible owned stance/resource configuration and the ordinary choice transport are prerequisites. Out-of-combat limb regrowth, narrative consequences and interactions with other healing interceptors remain outside this proof.
- `STARS_TAL_FALLING_STAR`: The matching feature compiles an object_damage passive while keeping the ordinary action. After an eligible area technique runs, the consumer matches its exact source to that passive, finds reachable map objects, and applies a double-damage multiplier for the declared structure/unattended tags. Evidence: `APP/combat/ext/__init__.py:7286`, `APP/combat/ext/__init__.py:7458`, `APP/combat/ext/__init__.py:7572`, `APP/combat/ext/objects.py:209`, `APP/combat/ext/objects.py:218`, `APP/combat/ext/objects.py:678`, `APP/combat/ext/objects.py:691`, `APP/combat/ext/objects.py:707`, `APP/combat/ext/objects.py:713`, `APP/combat/ext/objects.py:724`, `APP/combat/object_rules.py:136`, `APP/combat/object_rules.py:157`, `APP/combat/rules/feature_blocks.d/sysv2_objects.json:92`, `APP/combat/typed_executor.py:5104`, `APP/combat/typed_reactions.py:242`, `APP/combat/typed_reactions.py:38`, `APP/combat/typed_reactions.py:89`. Limits: A component implementation is verified in eligible ordinary contexts; complete printed-rule fidelity is not established. No fight was run. Availability, all choices, all plug-in interactions, and every saved character configuration remain unverified. Covers text is not execution proof and residual reminders are not retired by this component assessment. Limited to nonweapon area techniques and living map-object records with HP/AC in the resolved area; wall areas and abstract barriers are outside this proof. Damage thresholds, immunities and other defenses can still reduce damage to zero; this is not unconditional HP loss. Terrain creation, clearing, creature effects, exact damage-type choice semantics and every printed object category remain separately unverified.

### Conditional plug-in reminder sources

There are 26 explicit GM_RIDER event sites and 394 possible rider-method sites. 257 messages are dynamic and cannot be rendered as one fixed static string. The complete inventory gives each site's exact source and marks uncertain method receivers and mechanic associations. These site counts are not added to the catalogue reminder count.

- `combat.ext.alchemy_riders.solid_surface_qualification` — POSSIBLE_GM_EMISSION_SITE; UNKNOWN_DYNAMIC_TEMPLATE. Evidence: `APP/combat/ext/alchemy_riders.py:339`, `APP/combat/typed_executor.py:506`, `APP/combat/typed_executor.py:507`.
- `combat.ext.alchemy_riders.healing_pill` — POSSIBLE_GM_EMISSION_SITE; UNKNOWN_DYNAMIC_TEMPLATE. Evidence: `APP/combat/ext/alchemy_riders.py:361`, `APP/combat/typed_executor.py:506`, `APP/combat/typed_executor.py:507`.
- `combat.ext.alchemy_riders.furnace_target` — POSSIBLE_GM_EMISSION_SITE; UNKNOWN_DYNAMIC_TEMPLATE. Evidence: `APP/combat/ext/alchemy_riders.py:487`, `APP/combat/typed_executor.py:506`, `APP/combat/typed_executor.py:507`.

## Top 20 spheres / Paths by remaining reminders

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

All 85 spheres and every authority Path, subpath, and Foundation are separately totalled in the JSON. Missing sphere IDs are grouped by their actual authority IDs, not collapsed into a misleading question-mark bucket.

## General fixes to send to the automation lanes

1. **Make covers conditional on an implementation contract.** Connect each retired sentence to a compiled block/effect, applicable runtime consumer, and targeted regression. Keep a reminder when that contract cannot be established. The current filter trusts the text list directly (`APP/combat/factory_compiler.py:778`); no such behavior change is made here.
2. **Preserve unresolved reaction rules visibly.** Route failures and missing effect branches need explicit diagnostics/reminders, including a reaction's source riders. Share the current trigger classifier and check the complete compile gate, not only a phrase label (`APP/combat/factory_compiler.py:1676`, `APP/combat/factory_compiler.py:1691`, `APP/combat/factory_compiler.py:1697`).
3. **Publish parameter-aware effect contracts.** A dispatcher key should declare supported fields, nested branches, contexts, and fallback behavior. Validate deferred effects and context-only handlers against that contract (`APP/combat/typed_executor.py:4809`). A registry membership test alone is too weak.
4. **Audit modifier attachments as combinations.** Build bounded, deterministic fixtures for destination matching, optional payment, nested branches, and option caps. A standalone modifier record cannot show whether it attaches (`APP/combat/factory_compiler.py:5394`, `APP/combat/factory_compiler.py:2461`).
5. **Retire already_applied declarations only with traceable readers.** Distinguish sheet statistics, compiler changes, and runtime hooks, with a source reference and a test for each (`APP/combat/typed_reactions.py:223`, `APP/combat/factory_compiler.py:2382`).
6. **Prioritize by the measured reminder backlog.** Use the top-20 table to choose a bounded set of repeated rider patterns. Track retained templates, known silent gaps, and UNKNOWN separately; a lower reminder count is progress only when the retired rules have validated implementations.

These are proposed follow-up changes, not implemented engine changes. The per-mechanic JSON identifies exact source records for lane assignment.

## Verification and reproducibility

From `APP`:

```sh
python -m unittest discover -s tests -p 'test_automation_truth*.py'
python -m tools.automation_truth --check
```

The tests cover real mechanics and adversarial fixtures, source evidence, option handling, covers, conservative plug-in claims, and byte-for-byte repeatability. One test reruns `--check` in a second process with a different `PYTHONHASHSEED`, so a differing report cannot be blamed on set or dictionary ordering; another asserts that no rendered report byte contains a repository path, interpreter path, or timestamp. No live-machine, saved-fight, provider, or combat simulation result is claimed by these commands. Runtime integration and printed-text fidelity remain separate reviewer work.

Every report embeds the `input_sha256` fingerprint of all audited sources listed in `inputs`. A tree whose combat sources differ from the ones a committed report was built from therefore fails `--check` for all files at once; the failure message names the added, missing, and changed input files rather than only the reports that differ. Regenerate only from the commit whose sources the report describes.

Input fingerprint: `df050496e9fdc21733901caea21be4a195e2cf11e10dae53d4b9f2cebccf969e`. Exact source file SHA-256 values, static diagnostics, and the per-mechanic index are in `AUTOMATION_TRUTH_R1.json`; its hash-checked `detail_parts` contain every complete decision in `AUTOMATION_TRUTH_R1.d/`.
