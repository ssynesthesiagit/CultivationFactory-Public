"""Roll direction shared by typed mode execution and area-risk previews."""
import re


def roll_mode_target(effect):
    """Return normalized roll description and whether attacks target the recipient."""
    on = str(effect.get('on') or '').lower()
    if re.fullmatch(r'(?:the next |one )?attacks? (?:made )?against (?:it|the target|you|them|that creature)', on.strip()):
        on = on.replace('attack', 'attack roll', 1)
    incoming = 'attack roll' in on and any(word in on for word in ('against it', 'against the target', 'against you'))
    return on, incoming


def roll_mode_harmful(effect):
    """Incoming Advantage harms; incoming Disadvantage protects. Outgoing is inverse."""
    _, incoming = roll_mode_target(effect)
    return (effect.get('type') == 'advantage') if incoming else (effect.get('type') == 'disadvantage')
