"""Counterstrike after-hit seam (A2RETRIBUT):
  ext.run_strict('counterstrike_hit', engine, actor, variant, target, intent) fires from
  combat/ext/counterstrike.py once a prepared Counterstrike has hit and that strike's own
  "After a Counterstrike hits, you regain your Reaction" has already set reaction_available.
  Arguments: the engine, the fighter, the compiled Counterstrike variant they prepared, the
  creature the strike hit, and the resolving intent. Return: ignored; a provider acts in place.
  It exists for printed Counter talents that SPEND that restored Reaction in the same beat
  (Retribution's Clinch), which cannot be an ordinary typed effect because effect rows run inside
  the strike, before the restore. Default-inert: with no registered provider nothing runs and no
  state, event, action, intent, candidate or saved-fight schema changes. A provider reads the
  compiled variant for its own reviewed modifier row rather than a hard-coded ability id.
Counterstrike preparation seam (A2RETRIBUT):
  counterstrike_prepare(engine, actor, variant, intent, reflexive) -> None fires once the
  chosen variant has been recorded for an ordinary Action preparation. It is not called by Bonus
  Action Reflexive Preparation. Providers inspect their own reviewed modifier and resolve optional
  replacement-attack choices there. Return values are ignored; default-inert with no providers.
Counterstrike after-hit seam (A2RETRIBUT):
  The dispatch point counterstrike_hit(engine, actor, variant, target, intent) is read by
  ext.run_strict('counterstrike_hit', engine, actor, variant, target, intent) from
  combat/ext/counterstrike.py, once a prepared Counterstrike has hit and that strike's own
  "After a Counterstrike hits, you regain your Reaction" has already set reaction_available.
  Arguments: the engine, the fighter, the compiled Counterstrike variant they prepared, the
  creature the strike hit, and the resolving intent. Return: ignored; a provider acts in place.
  It exists for printed Counter talents that SPEND that restored Reaction in the same beat
  (Retribution's Clinch), which cannot be an ordinary typed effect because effect rows run inside
  the strike, before the restore. Default-inert: with no registered provider nothing runs and no
  state, event, action, intent, candidate or saved-fight schema changes. A provider reads the
  compiled variant for its own reviewed modifier row rather than a hard-coded ability id."""
