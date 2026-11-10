"""Weapon hit chains (A2BERSERKE): weapon_hit_chain is a sealed on-hit marker
  read at the existing strict attack_completed boundary. It offers a new,
  currently perceived enemy within the selected readied implement's melee reach after
  each settled hit, including lethal hits. Each follow-up lets the player choose any possessed, readied melee weapon
  (including a natural or unarmed strike); automatic choices prefer the original
  implement. Each follow-up uses ordinary attack
  targeting, defenses, damage and hooks with its own attack_aim scope and a
  fresh damage cache. Only weapon/numbers/proficiency/duration and physical equipment binding
  metadata carries;
  Batter, Exertion, extra attack counts and variant riders do not. Its integer
  attack_bonus applies to every follow-up. Miss/decline/no legal enemy or an
  unable attacker ends the chain. The visited set and final-hit capture are
  resolution-local; errors/pauses restore scratch in finally. Markerless saves
  are inert. No new core seam, schema or saved policy is added.
Adrenaline status (A2BERSERKE): new choices stamp adrenaline_status_receipt=1
  and emit ordinary PASSIVE_TRIGGERED acknowledgements. Markerless saved choices
  keep their historical GM_RIDER acknowledgements; unresolved talent riders remain.
Bell-Ringer (A2BERSERKE): newly compiled owned gu_berserker_exertion rows
  opt in with bell_runtime=1. Existing nested DAMAGE_COMMITTED event
  places the chosen Exertion's positive primary-packet condition before its
  own Concentration save. Native condition rule data enforces INT check and
  Concentration disadvantage separately from ordinary CON saves. The ordinary
  after-hit path reuses the same condition and Beat Down/source-turn expiry.
  Old sealed rows retain their old manual reminder and save behavior.
Lock round 27 native opportunity policy:
  movement_steps.opportunity_policy(engine, actor, ignore_oa_from) scopes the
  COMPLETE native _resolve_movement call, including validation, attempt checks,
  leave-reach reactions, entry checks, final movement records and early exits.
  Every nested native route restores the enclosing exemptions and step snapshot
  in finally, including exceptions and ControllerPause. The transient snapshot
  is captured before movement_attempt, before free OA distance can be spent.
  movement_steps.opportunity_exempt(engine, mover, reactor_id) -> bool is a pure
  query for entry-attack consumers: Disengage, this step's free OA allowance,
  explicit per-creature exemptions and the existing mover exemption flag.
  It returns False for a different mover or outside a native movement scope.
  No consumer means identical movement, events and saved state; no ability IDs,
  engine replacement, stored policy or new player decision is introduced."""
