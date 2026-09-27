"""Bounded manual commands; navigation observations do not lock out reverse."""
import math

def manual_command(message, distance, connected):
    if not connected:
        return None, 'Arduino offline. Check USB and car power.'
    try:
        values = [float(message.get(k, 0)) for k in ('lin','ang','strafe')]
        if not all(math.isfinite(v) and -1 <= v <= 1 for v in values):
            raise ValueError()
    except (ValueError, TypeError):
        return None, 'Invalid manual command.'
    lin, ang, strafe = values
    if strafe:
        return None, 'Use arrow keys; sideways motion is disabled for this test mode.'
    if lin > 0 and (distance is None or not math.isfinite(distance) or distance <= 0 or distance < 25):
        return None, 'Forward blocked: front distance must be at least 25 cm. Reverse or turn under supervision.'
    power = abs(lin) * 40
    return (0 if lin >= 0 else 180, power, ang * 40), None
