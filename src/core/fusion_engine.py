# import time
# from collections import Counter
# from config.settings import *
# from src.audio.speech_engine import SpiritAudio


# def _summarize_counts(items):
#     if not items:
#         return ""
#     counts = Counter(items)
#     parts = []
#     for name, n in counts.items():
#         label = name.replace("_", " ")
#         if n > 1:
#             label = label + "s" if not label.endswith("s") else label
#         parts.append(f"{n} {label}")
#     if len(parts) == 1:
#         return parts[0]
#     return ", ".join(parts[:-1]) + f" and {parts[-1]}"


# class FusionEngine:
#     def __init__(self):
#         self.audio = SpiritAudio()
#         self.last_spoken_time = 0
        
#         # Repeat suppression timers — each alert type has its own cooldown
#         self._last_tof_critical = 0    # Don't repeat "STOP" for 30 seconds
#         self._last_tof_warning = 0     # Don't repeat "caution" for 15 seconds
#         self._last_vehicle_alert = 0   # Don't repeat vehicle alert for 15 seconds
#         self._last_hazard_alert = 0    # Don't repeat hazard alert for 15 seconds
#         self._last_temp_alert = 0      # Don't repeat temp alert for 60 seconds
#         self._last_humidity_alert = 0  # Don't repeat humidity alert for 60 seconds
        
#         # Cooldown durations (seconds)
#         self.COOLDOWN_TOF_CRITICAL = 30
#         self.COOLDOWN_TOF_WARNING = 15
#         self.COOLDOWN_VEHICLE = 15
#         self.COOLDOWN_HAZARD = 15
#         self.COOLDOWN_TEMP = 60
#         self.COOLDOWN_HUMIDITY = 60

#     def _can_speak(self):
#         return (time.time() - self.last_spoken_time) > 1.5

#     def process(self, vision_hazards, urgent_vehicles, sensors):
#         if not sensors:
#             return
        
#         if not self._can_speak():
#             return

#         now = time.time()
#         temp = sensors.get('temperature', 0)
#         hum = sensors.get('humidity', 0)
#         tof_dist = sensors.get('distance_mm')
#         bme_ok = sensors.get('bme_ok', False)
#         tof_ok = sensors.get('tof_ok', False)

#         # Priority 1: ToF CRITICAL — say once, then cooldown
#         if tof_ok and tof_dist is not None and tof_dist <= TOF_CRITICAL_DISTANCE_MM:
#             if (now - self._last_tof_critical) > self.COOLDOWN_TOF_CRITICAL:
#                 print(f"[ALERT] ToF: Immediate obstacle ({tof_dist:.0f}mm)")
#                 self.audio.speak_async("Stop! Immediate obstacle ahead.")
#                 self.last_spoken_time = now
#                 self._last_tof_critical = now
#             return

#         # Priority 2: ToF WARNING — say once, then cooldown
#         if tof_ok and tof_dist is not None and tof_dist <= TOF_WARNING_DISTANCE_MM:
#             if (now - self._last_tof_warning) > self.COOLDOWN_TOF_WARNING:
#                 print(f"[ALERT] ToF: Obstacle nearby ({tof_dist:.0f}mm)")
#                 self.audio.speak_async("Caution, obstacle nearby.")
#                 self.last_spoken_time = now
#                 self._last_tof_warning = now
#             return

#         # Priority 3: Fast approaching vehicles — say once, then cooldown
#         if urgent_vehicles:
#             if (now - self._last_vehicle_alert) > self.COOLDOWN_VEHICLE:
#                 summary = _summarize_counts(urgent_vehicles)
#                 print(f"[ALERT] Vehicle: {summary} approaching")
#                 self.audio.speak_async(f"Caution, {summary} approaching fast.")
#                 self.last_spoken_time = now
#                 self._last_vehicle_alert = now
#             return

#         # Priority 4: Static hazards — say once, then cooldown
#         if vision_hazards:
#             if (now - self._last_hazard_alert) > self.COOLDOWN_HAZARD:
#                 summary = _summarize_counts(vision_hazards)
#                 print(f"[ALERT] Hazard: {summary} detected")
#                 self.audio.speak_async(f"Watch out, {summary} detected ahead.")
#                 self.last_spoken_time = now
#                 self._last_hazard_alert = now
#             return

#         # Priority 5: Temperature warning — say once, then long cooldown
#         if bme_ok and temp >= TEMP_WARNING_THRESHOLD:
#             if (now - self._last_temp_alert) > self.COOLDOWN_TEMP:
#                 print(f"[ALERT] Temperature: {temp:.1f}C")
#                 self.audio.speak_async("Warning, high temperature. Seek shade.")
#                 self.last_spoken_time = now
#                 self._last_temp_alert = now
#             return

#         # Priority 6: Humidity warning — say once, then long cooldown
#         if bme_ok and hum >= HUMIDITY_FLOOD_THRESHOLD:
#             if (now - self._last_humidity_alert) > self.COOLDOWN_HUMIDITY:
#                 print(f"[ALERT] Humidity: {hum:.1f}%")
#                 self.audio.speak_async("Humidity very high. Risk of flooded paths.")
#                 self.last_spoken_time = now
#                 self._last_humidity_alert = now
#             return







import time
from collections import Counter
from config.settings import *
from src.audio.speech_engine import SpiritAudio


def _summarize_counts(items):
    if not items:
        return ""
    counts = Counter(items)
    parts = []
    for name, n in counts.items():
        label = name.replace("_", " ")
        if n > 1:
            label = label + "s" if not label.endswith("s") else label
        parts.append(f"{n} {label}")
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + f" and {parts[-1]}"


def _say(text: str):
    """Always-visible terminal output, matching the You:/Spirit: transcript
    format used everywhere else — so proactive safety alerts show up as
    part of one continuous, readable conversation log, not a separate
    inconsistent [ALERT] format."""
    print(f"Spirit: {text}")


class FusionEngine:
    """
    IMPORTANT — SAFETY BOUNDARY: everything here is deterministic, canned
    phrasing, NOT routed through the LLM. A collision warning must never be
    delayed or altered by a network call, rate limit, or model
    hallucination. SpiritAgent (spirit_agent.py) is the smart conversational
    layer on top of this; this class is the hard safety layer underneath it
    and must keep working even if Groq/the internet is completely down.
    """

    def __init__(self):
        self.audio = SpiritAudio()
        self.last_spoken_time = 0

        # Repeat suppression timers — each alert type has its own cooldown
        self._last_tof_critical = 0    # Don't repeat "STOP" for 30 seconds
        self._last_tof_warning = 0     # Don't repeat "caution" for 15 seconds
        self._last_vehicle_alert = 0   # Don't repeat vehicle alert for 15 seconds
        self._last_hazard_alert = 0    # Don't repeat hazard alert for 15 seconds
        self._last_temp_alert = 0      # Don't repeat temp alert for 60 seconds
        self._last_humidity_alert = 0  # Don't repeat humidity alert for 60 seconds

        # Cooldown durations (seconds)
        self.COOLDOWN_TOF_CRITICAL = 30
        self.COOLDOWN_TOF_WARNING = 15
        self.COOLDOWN_VEHICLE = 15
        self.COOLDOWN_HAZARD = 15
        self.COOLDOWN_TEMP = 60
        self.COOLDOWN_HUMIDITY = 60

    def _can_speak(self):
        return (time.time() - self.last_spoken_time) > 1.5

    def process(self, vision_hazards, urgent_vehicles, sensors):
        if not sensors:
            return

        if not self._can_speak():
            return

        now = time.time()
        temp = sensors.get('temperature', 0)
        hum = sensors.get('humidity', 0)
        tof_dist = sensors.get('distance_mm')
        bme_ok = sensors.get('bme_ok', False)
        tof_ok = sensors.get('tof_ok', False)

        # Priority 1: ToF CRITICAL — say once, then cooldown
        if tof_ok and tof_dist is not None and tof_dist <= TOF_CRITICAL_DISTANCE_MM:
            if (now - self._last_tof_critical) > self.COOLDOWN_TOF_CRITICAL:
                text = "Stop! Immediate obstacle ahead."
                _say(text)
                self.audio.speak_async(text)
                self.last_spoken_time = now
                self._last_tof_critical = now
            return

        # Priority 2: ToF WARNING — say once, then cooldown
        if tof_ok and tof_dist is not None and tof_dist <= TOF_WARNING_DISTANCE_MM:
            if (now - self._last_tof_warning) > self.COOLDOWN_TOF_WARNING:
                text = "Caution, obstacle nearby."
                _say(text)
                self.audio.speak_async(text)
                self.last_spoken_time = now
                self._last_tof_warning = now
            return

        # Priority 3: Fast approaching vehicles — say once, then cooldown
        if urgent_vehicles:
            if (now - self._last_vehicle_alert) > self.COOLDOWN_VEHICLE:
                summary = _summarize_counts(urgent_vehicles)
                text = f"Caution, {summary} approaching fast."
                _say(text)
                self.audio.speak_async(text)
                self.last_spoken_time = now
                self._last_vehicle_alert = now
            return

        # Priority 4: Static hazards — say once, then cooldown
        if vision_hazards:
            if (now - self._last_hazard_alert) > self.COOLDOWN_HAZARD:
                summary = _summarize_counts(vision_hazards)
                text = f"Watch out, {summary} detected ahead."
                _say(text)
                self.audio.speak_async(text)
                self.last_spoken_time = now
                self._last_hazard_alert = now
            return

        # Priority 5: Temperature warning — say once, then long cooldown
        if bme_ok and temp >= TEMP_WARNING_THRESHOLD:
            if (now - self._last_temp_alert) > self.COOLDOWN_TEMP:
                text = "Warning, high temperature. Seek shade."
                _say(text)
                self.audio.speak_async(text)
                self.last_spoken_time = now
                self._last_temp_alert = now
            return

        # Priority 6: Humidity warning — say once, then long cooldown
        if bme_ok and hum >= HUMIDITY_FLOOD_THRESHOLD:
            if (now - self._last_humidity_alert) > self.COOLDOWN_HUMIDITY:
                text = "Humidity very high. Risk of flooded paths."
                _say(text)
                self.audio.speak_async(text)
                self.last_spoken_time = now
                self._last_humidity_alert = now
            return