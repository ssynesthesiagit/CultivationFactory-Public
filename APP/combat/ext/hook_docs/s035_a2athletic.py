"""Athletics second pass (A2ATHLETIC):
movement_step_capability(engine, actor, previous, destination, mode) -> bool
or None is a strict pure capability query in flight.step_allowed. False vetoes;
True replaces only the ordinary flight/jump/walk capability gate, never volume
collision, obstacles, willing-movement restrictions, hazards, payment or OAs.
Default None preserves the existing modes. Unwilling Boost supplies True only
for a direction-checked vertical 'impulse' during its transient native movement
scope; its persisted round-specific pool caps the granted distance, so no Fly Speed, free Dash or perpetual vertical movement is granted.
movement_end_blocked(engine, actor, grant_ft) -> None or iterable of integer (x, y, z) cells
  grant_ft is the scoped grant's own budget in feet (the feet routes priced; a path check passes the path's
  own length), so a provider searches the area that grant can actually reach, not a guessed radius.
  It is a strict pure query read only by granted_movement._blocked_ends for a scoped
  movement grant. The named cells are endpoints the granted move may NOT end on:
  an endpoint is refused when any cell of the mover's volume there is listed. It
  can only narrow the endpoints of the grant that asks; native legality is kept.
  None or an empty answer leaves every endpoint as native geometry allows. Ordinary
  movement never calls it, so an absent provider is default-inert.
movement_passage_cells(engine, actor, grant_ft) -> None or iterable of integer (x, y, z) cells
  grant_ft is the same grant budget in feet, as for movement_end_blocked.
  It is a strict pure query read only by granted_movement._passage_cells for a scoped
  movement grant. The named cells are matter or creature space that this one grant
  may ENTER as a crossing (granted_movement._crossings), although the map or an
  occupant would otherwise refuse them. Every other step of the route still meets
  the ordinary edge rules, and the endpoint must pass movement_end_blocked and native
  geometry, so a crossing never becomes a legal resting place by itself. None or an
  empty answer opens nothing and leaves ordinary routes unchanged; default-inert.
Granted movement admits the 'impulse' mode for that provider alone: with no
provider every vertical impulse step fails flight.step_allowed, so no creature
gains impulse movement by default.
Scale Foe uses this seam only within its boarding_scope after a won check and
an explicit owned attachment receipt, admitting an adjacent contained entry at
any accessible occupied height. Native collision, payment and reactions remain
in force; the scope restores on pause/exit and grants no lasting movement mode.
typed_reactions.opportunity_profile(engine, actor) -> (row, action, reach) is
the public pure profile for explicit OA consumers; admission, consent and
Reaction payment remain the consumer's responsibility. Unwilling Boost admits
only perceived allies to assistance, then resolves their real paid OA. A
consumer that opens an OA before resolving it may pass
opportunity_reaction_notice(engine, actor, target_ids) as open_reaction's
reaction_notice: the original row still controls admission and payment, while
the notice carries the resolved attack's effects and roll source identity. Its
attack_completed subscriber uses the immutable opportunity_trigger ("movement"
or "assistance") and actual hit, source Strength and current size. Explicit OA
callers use opportunity_permitted_against(engine, reactor, target) as a pure
OA-specific condition/hook query alongside ordinary can_use_reaction admission,
before offering and again before payment. This query neither requires leaving
reach nor asks/spends/invokes optional protection responses. The shared OA
resolver accepts trigger="movement", "assistance", or default "granted"; its
nested participant/source-specific scope is copied to AttackNotice.opportunity and
opportunity_trigger before deferred dispatch. Default grants do not imply the
target provoked the attack by moving. Native and Factory profiles share this
provenance; all temporary frames unwind on pauses and errors. Miss conversions
consume the owner's Bonus Action. Horizontal/vertical movement pools are disjoint, valid
only for the granting round, spent with evented condition updates and native
granted_ft routes. Pauses unwind through the surrounding session transaction.
maintain_grapples_incapacitated(engine, actor) -> bool or None is a strict pure
exception query before grapple_parts' automatic incapacity release. Any True
preserves physical holds; it grants no actions/reactions or immunity to range,
voluntary release, dislodging, or loss of a maintaining body part. Default None
retains ordinary release. Sure Grip contributes only for its sealed owned row.
Sure Grip compiles exactly one ``athletics/sure_grip`` passive: athletics owns
the climbing capability, and athletics_grip_lungs uses athletics.owns for the
same row's hazard checks, catches and physical grapple retention. Neither
provider supplies a second ownership row or a second climbing registration.
ability_check_hazards(engine, actor, ability, skill, hazards) -> roll mode or
None is a strict pure query merged into typed_executor.check_modes even without
an opposing creature. Callers must name the check's actual hazards; omitted or
unmatched metadata is inert. Sure Grip applies only to Athletics checks tagged
climb/prevent_falling; independent Disadvantage still cancels normally.
Strong Lungs uses existing per-save save_categories provenance: inhalation,
suffocation, and (CON only) forced_march_exhaustion. It does not infer delivery
from names or grant Advantage to every Poison/Exhaustion save. Breath duration
remains retained text. Sure Grip's catch check uses an explicitly authored
scene/surface difficulty, its native falling checkpoint and persisted support.
AttackNotice.opportunity (default False) preserves explicit OA provenance at
attack_completion.notify, before a compound effect can defer that notice and
restore the native OA scope. It is transient, never inferred from weapon names
or persisted as a new saved-fight field. Unwilling Boost reads it at completion.
Modules: athletics_momentum and athletics_grip_lungs. The public helper
grapple_parts.maintains_on_incapacity is shared by grapple_parts and
wrestling_framework's physical-hold release consumers; inactive/dead holders
still release holds. It changes no hold's independent range or expiry.
The free momentum buttons are only movement transport for the persisted
allowance; they grant no action economy. AI destination ranking uses
target_knowledge.actors_for, so unseen actors and live hidden positions do not
guide it. Human owners choose a bounded destination through the same transport.
Strong Lungs also consumes Smoke's existing smoke_nonbreather_advantage
context marker: smoke_choke_save publishes it only around Black-Lung Cloud's
actual choking save. No action-name inference or blanket poison immunity.
Half-distance pools store integer half_feet, retaining exact 2.5-foot increments
without binary floats in canonical saved state, including cold reload.
They combine before route pricing; only the usable native grant is an integer.
Thus two minimum vertical grants can pay a 5-foot segment without rounding loss.
Momentum expires on the existing START_OF_SLOT_AT:<next round>:0 clock,
including skipped owner turns. An extra turn in the granting round retains it.
Assistance uses the ally's actual OA profile/reach, requires a currently
perceived ally and a target the ally can see, and revalidates before payment.
"""
