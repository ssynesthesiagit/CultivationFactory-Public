"""Spoken-technique reaction seam (combat/speech.py, typed_reactions.on_technique_start):
  speech.record_needs_voice(record, option="") answers from combat/rules/speech.json whether an
  ability named by (record id, option label) needs its user's own voice -- a shout, kanji-style
  battle cry, chant, song, spoken command or Verbal component; it is the test the owner's own list
  records, and needs_voice(action) is the same test for a whole action. A reaction whose printed
  trigger is "a creature ... speaks a command word, uses a Voice talent, casts a spell with a
  verbal component, or begins a supernatural chant" is offered only when the ability that just
  started was spoken: either its targets must hear it (the parsed requires_hearing) or it needs its
  user's own voice. Both tests read the compiled row, so no ability id appears in the engine; the
  list stays inert for a character with no such ability and for an ability that is not spoken. No
  new state, event or saved field."""
