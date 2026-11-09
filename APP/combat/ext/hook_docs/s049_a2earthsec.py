"""Contact-based location query (A2EARTHSEC):
  pinpoint_target(engine, viewer, target) -> bool | None is a strict pure,
  additive query. True grants current location only, never sight, condition
  masks or Line of Effect. None/False contribute nothing; without a provider,
  native location behavior is unchanged. Invalid values fail the query.
  Providers must gate ownership, live duration, range and contact geometry,
  and must not mutate state, roll, emit events or ask a controller.
  The shared surface_contact.connected query models native floor, finite
  solid-column and solid-roof contact; airborne targets do not acquire projected contact.

"""
