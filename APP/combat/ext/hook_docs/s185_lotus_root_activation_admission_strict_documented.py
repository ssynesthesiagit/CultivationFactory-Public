"""Lotus-Root activation admission (strict, documented):
activation_admission(engine, user, action, candidate, intent, phase) -> None | dict
  Runs strictly in technique_interception.prepare before economy/resource payment.
  phase='before_interception' checks source permissions/recipient willingness
  before counters can spend; refusal can cancel without paying. The existing
  technique_declared providers then resolve their native counters/redirections.
  phase='after_interception' checks the actual final action and recipient, unless
  a counter already canceled it. Replies accept only source_id, readable label,
  cancel(bool) and spend_activation(bool, defaultFalse). They cannot redirect,
  roll back another source's counter payment, or rewrite catalog/state schemas.
  None is exactly default-inert: absent opinions add no event or action clone.
  Existing explicit spend-on-cancellation is retained. Lotus-Root uses both
  phases: original controller-owned intent/consent, then new recipient consent
  after a real redirection. The valid original cast remains paid if its new
  recipient refuses, as with an intercepted miss; no unwilling creature benefits."""
