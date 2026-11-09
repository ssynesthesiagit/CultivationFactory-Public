"""Private source input contracts (the seam lives in combat/table_facts.py).

table_source_inputs(engine) -> list[form] | None supplies owner-only forms,
each with source_id, actor_id, label, description and fields (name, label,
options; an empty options list requests private text). Default adds no forms.
table_source_document(engine, source_id, actor_id, values) -> dict | None
validates an owned source input and returns a table_facts.TableFact for native
commit. Exactly one provider must handle an input; None leaves it unhandled.
This runs strictly: validation errors abort without a journal entry or payment.
table_fact_validate(engine, fact) -> None strictly validates source semantics
during authoring and replay. No subscriber adds restrictions. Facts and their
authoring envelopes stay out of public history/model recent_events; consumers
query table_facts.records(engine, viewer) for witnessed current input only.
Any owner/GM-run source fact may supply and validate its own form; a character
without that source gets no form, no fact and no changed behavior. These hooks
authorize no AI to invent GM facts or owner intent.

The start-turn checkpoint also supports GM adjudication: a hook may ask through
needle.ask(..., gm_adjudication=True), which pauses even an automatic turn for
an external table fact instead of letting local or model AI invent it.
"""
