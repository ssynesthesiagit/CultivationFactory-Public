"""Pulse reading seam (INS7D):
  pulse_read(ctx, target) -> None runs after the ordinary Read the Pulse
  diagnosis, for each actual patient (including remote/additional patients).
  Strict/transactional: optional choices pause and roll back the activation.
  Default inert; providers own ownership, seal eligibility and disclosure.
  It changes neither target permissions nor the ordinary diagnosis."""
