"""Native flight condition data: fly_speed_reduction_ft is nonnegative integer
feet, subtracted after percentage reductions. Independent rows stack; equal
fly_speed_reduction_key values describe one effect and contribute only their
largest penalty. Zero/absent reductions are inert. Native falling remains the
single settlement path when Fly Speed reaches zero without Hover.

"""
