"""
Spirit Navigation System - main entry point (ESP32-CAM only).
"""

import argparse
import logging
import math
import queue
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import cv2
import numpy as np

try:
    from dotenv import load_dotenv
    if load_dotenv(override=True):
        print("INFO: Loaded environment variables from .env file.")
    else:
        print("INFO: No .env file found.")
except ImportError:
    print("WARNING: python-dotenv not installed.")

from config.settings import QUIET_TERMINAL
from src.vision.esp32_client import ESP32Client
from src.vision.detector import SpiritVision
from src.core.fusion_engine import FusionEngine, _summarize_counts
from src.nlp.spirit_agent import SpiritAgent
from src.nlp.maps_client import MapsClient
from src.audio.wake_word import WakeWordListener
from src.sensors.gps_reader import GPSReader

# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
FRAME_WIDTH = 640
FRAME_HEIGHT = 480
TARGET_FPS = 15.0
WINDOW_NAME = "Spirit Vision Stream"
SOURCE_LABEL = "ESP32-CAM"

GEOCODE_REFRESH_INTERVAL_SEC = 25

NAV_TRIGGERS = ("take me to", "navigate to", "directions to", "how do i get to",
                "how do you get to", "walk me to", "guide me to")

ACK_PHRASES = [
    "I'm on it.",
    "One moment.",
    "Let me check.",
    "Hmm, let me think.",
    "Alright.",
    "Sure thing.",
    "Got you.",
    "On it.",
]

GOODBYE_PHRASES = [
    "Goodbye Master, stay safe out there.",
    "See you later, Master. Take care.",
    "Until next time, Master. Be safe.",
]

logging.basicConfig(
    level=logging.WARNING if QUIET_TERMINAL else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("spirit.main")
# Always show ESP32 connection events, even in quiet mode.
logging.getLogger("spirit.esp32").setLevel(logging.INFO)


def _say(text: str):
    print(text)


# --------------------------------------------------------------------------- #
# Camera source (ESP32-CAM only)
# --------------------------------------------------------------------------- #
class CameraSource:
    def __init__(self, esp32: ESP32Client):
        self.esp32 = esp32
        self.esp32.start_stream()

    @property
    def link_up(self) -> bool:
        """True if the TCP link to the ESP32 is connected (video may still be missing)."""
        return self.esp32.is_connected

    def read(self):
        """Returns (frame, sensors, ok). ok is False when there is no fresh frame."""
        frame, sensors = self.esp32.get_data()
        if frame is None:
            return None, sensors, False
        return frame, sensors, True

    def release(self):
        try:
            self.esp32.stop_stream()
        except Exception:
            log.exception("Error stopping ESP32 stream during shutdown.")


# --------------------------------------------------------------------------- #
# Camera health monitoring
# --------------------------------------------------------------------------- #
class CameraWatchdog:
    GRACE_SEC = 3.0        # no frames for this long => declare lost
    REMINDER_SEC = 60.0    # gentle reminder cadence while still down

    def __init__(self, camera: CameraSource, audio):
        self.camera = camera
        self.audio = audio
        self.lost = False
        self._ever_ok = False
        self._last_frame = time.monotonic()
        self._lost_since = None
        self._last_reminder = 0.0

    def set_initial(self, ok: bool):
        """Call once after the startup wait so the intro and watchdog agree."""
        self._ever_ok = ok
        now = time.monotonic()
        self._last_frame = now
        if not ok:
            self.lost = True
            self._lost_since = self._last_reminder = now

    @property
    def down_secs(self) -> float:
        return time.monotonic() - self._lost_since if self._lost_since else 0.0

    def _announce(self, msg: str):
        _say(f"Spirit: {msg}")
        self.audio.speak_async(msg)

    def _lost_message(self) -> str:
        if self.camera.link_up:
            hint = ("I'm connected to the camera board but it isn't sending video. "
                    "Please check the camera cable on the board.")
        else:
            hint = "Please check that the camera has power and is on the same Wi-Fi."
        lead = ("Master, I've lost my camera feed." if self._ever_ok
                else "Master, I can't connect to my camera.")
        return (f"{lead} I can't see hazards or vehicles right now, so please be extra "
                f"careful. {hint} I'll keep trying. Voice help and GPS still work.")

    def tick(self, got_frame: bool):
        now = time.monotonic()

        if got_frame:
            self._last_frame = now
            self._ever_ok = True
            if self.lost:
                secs = int(now - self._lost_since)
                self.lost = False
                self._lost_since = None
                self._announce("My camera is back online. I can see again." if secs < 5 else
                               f"My camera is back online after {secs} seconds. I can see again.")
            return

        if not self.lost:
            if now - self._last_frame >= self.GRACE_SEC:
                self.lost = True
                self._lost_since = self._last_frame
                self._last_reminder = now
                self._announce(self._lost_message())
            return

        # Still down. ESP32Client reconnects on its own; just remind occasionally.
        if now - self._last_reminder >= self.REMINDER_SEC:
            self._last_reminder = now
            self._announce("Still no camera feed, Master. I'm still trying to reconnect.")


def draw_offline_screen(link_up: bool, down_secs: float, w=FRAME_WIDTH, h=FRAME_HEIGHT):
    frame = np.zeros((h, w, 3), np.uint8)
    pulse = int(140 + 115 * math.sin(time.time() * 3))
    cv2.circle(frame, (w // 2, h // 2 - 70), 28, (0, 0, pulse), -1)
    cv2.putText(frame, "CAMERA OFFLINE", (w // 2 - 160, h // 2 - 5),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)
    status = "connected, no video" if link_up else "searching for ESP32-CAM"
    cv2.putText(frame, f"{status}... {int(down_secs)}s",
                (w // 2 - 170, h // 2 + 35), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1)
    cv2.putText(frame, "Hazard detection inactive. Voice + GPS still available.",
                (w // 2 - 235, h // 2 + 65), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 165, 255), 1)
    return frame


def wait_for_first_frame(camera: CameraSource, timeout: float = 8.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        _, _, ok = camera.read()
        if ok:
            return True
        time.sleep(0.2)
    return False


# --------------------------------------------------------------------------- #
# Chat manager
# --------------------------------------------------------------------------- #
class SpiritChatManager:
    def __init__(self, spirit_agent: SpiritAgent, audio, maps: MapsClient, gps: GPSReader):
        self.spirit = spirit_agent
        self.audio = audio
        self.maps = maps
        self.gps = gps
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="spirit-chat")
        self._lock = threading.Lock()
        self._thinking = False

    @property
    def is_thinking(self) -> bool:
        with self._lock:
            return self._thinking

    @staticmethod
    def _extract_nav_destination(command_text: str):
        lowered = command_text.lower()
        for trigger in NAV_TRIGGERS:
            idx = lowered.find(trigger)
            if idx != -1:
                destination = command_text[idx + len(trigger):].strip(" .?!")
                if destination:
                    return destination
        return None

    def submit(self, command_text: str, sensor_summary: str, urgent: bool = False):
        ack = random.choice(ACK_PHRASES)
        _say(f"Spirit: {ack}")
        self.audio.speak_async(ack)

        with self._lock:
            self._thinking = True

        submitted_at = time.monotonic()
        future = self._executor.submit(self._run_chat, command_text, sensor_summary, urgent)
        future.add_done_callback(lambda f: self._on_done(f, submitted_at))

    def _run_chat(self, command_text: str, sensor_summary: str, urgent: bool) -> str:
        nav_destination = self._extract_nav_destination(command_text)
        if nav_destination:
            loc = self.gps.get_location()
            if loc.get("gps_ok"):
                directions = self.maps.get_walking_directions(loc["lat"], loc["lon"], nav_destination)
                if directions:
                    sensor_summary += f"; walking directions to '{nav_destination}': {directions}"
                else:
                    sensor_summary += f"; navigation lookup for '{nav_destination}' failed"
            else:
                sensor_summary += "; no GPS fix available for navigation"

        return self.spirit.chat(command_text, sensor_summary, urgent=urgent)

    def _on_done(self, future, submitted_at: float):
        with self._lock:
            self._thinking = False
        try:
            response = future.result()
        except Exception:
            log.exception("Spirit agent failed to respond.")
            response = "Sorry Master, something went wrong."

        elapsed_ms = (time.monotonic() - submitted_at) * 1000
        log.debug("Turn completed in %.0fms (ack -> spoken response).", elapsed_ms)

        _say(f"Spirit: {response}")
        self.audio.speak_async(response)

    def shutdown(self):
        self._executor.shutdown(wait=False, cancel_futures=True)


# --------------------------------------------------------------------------- #
# Environment summary
# --------------------------------------------------------------------------- #
def build_environment_summary(last_known: dict, camera_ok: bool = True) -> str:
    sensors = last_known.get("sensors", {}) or {}
    hazards = last_known.get("hazards", []) or []
    vehicles = last_known.get("vehicles", []) or []
    address = last_known.get("address")
    location = last_known.get("location") or {}

    temp = sensors.get("temperature")
    dist = sensors.get("distance_mm")
    bme_ok = sensors.get("bme_ok", False)
    tof_ok = sensors.get("tof_ok", False)

    parts = []
    if not camera_ok:
        parts.append("CAMERA OFFLINE: you cannot see right now; hazard and vehicle detection "
                     "are inactive, so never say the path is clear or safe; tell the user "
                     "to be careful and that you are trying to reconnect")
    else:
        if bme_ok and temp is not None:
            parts.append(f"temperature {temp}C")
        if tof_ok and dist is not None:
            parts.append(f"nearest obstacle {dist}mm ahead")
        parts.append(f"hazards: {_summarize_counts(hazards) if hazards else 'none detected'}")
        parts.append(f"vehicles nearby: {_summarize_counts(vehicles) if vehicles else 'none detected'}")

    if address:
        parts.append(f"current location: {address}")
    elif location.get("gps_ok"):
        loc_name = location.get("location_name", "")
        if loc_name:
            parts.append(f"current location: {loc_name}")
        else:
            parts.append(f"current GPS: {location['lat']:.5f}, {location['lon']:.5f}")
    else:
        parts.append("no GPS fix available")

    return "; ".join(parts)


# --------------------------------------------------------------------------- #
# HUD overlay
# --------------------------------------------------------------------------- #
def draw_hud(frame, *, fps: float, listening: bool, thinking: bool,
             hazards, vehicles, gps_ok: bool):
    h, w = frame.shape[:2]
    cv2.putText(frame, f"Source: {SOURCE_LABEL}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX,
                0.7, (0, 255, 255), 2)
    cv2.putText(frame, f"FPS: {fps:.1f}", (10, 60), cv2.FONT_HERSHEY_SIMPLEX,
                0.7, (0, 255, 0), 2)
    n_hazards = len(hazards) if hazards else 0
    n_vehicles = len(vehicles) if vehicles else 0
    cv2.putText(frame, f"Hazards: {n_hazards}  Vehicles: {n_vehicles}", (10, 90),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 165, 255), 2)

    gps_color = (0, 255, 0) if gps_ok else (128, 128, 128)
    cv2.putText(frame, f"GPS: {'FIX' if gps_ok else 'no fix'}", (10, 115),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, gps_color, 2)

    dot_color = (0, 255, 0) if listening else (0, 0, 255)
    cv2.circle(frame, (w - 20, 20), 8, dot_color, -1)
    cv2.putText(frame, "LISTENING" if listening else "MUTED", (w - 150, 26),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, dot_color, 1)

    if thinking:
        cv2.putText(frame, "THINKING...", (w - 150, 50), cv2.FONT_HERSHEY_SIMPLEX,
                    0.6, (0, 200, 255), 2)

    cv2.putText(frame, "[q] quit  [m] mute", (10, h - 15),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
    return frame


# --------------------------------------------------------------------------- #
# Startup
# --------------------------------------------------------------------------- #
def _initialize_system():
    esp32 = ESP32Client()
    vision = SpiritVision()
    fusion = FusionEngine()
    spirit = SpiritAgent()
    maps = MapsClient()
    gps = GPSReader()
    listener = WakeWordListener(fusion.audio)
    camera = CameraSource(esp32)
    chat_manager = SpiritChatManager(spirit, fusion.audio, maps, gps)
    return vision, fusion, maps, gps, listener, camera, chat_manager


# --------------------------------------------------------------------------- #
# Main loop
# --------------------------------------------------------------------------- #
def main():
    parser = argparse.ArgumentParser(description="Spirit Navigation System")
    parser.add_argument("--esp32", action="store_true", help=argparse.SUPPRESS)  # legacy, ignored
    parser.add_argument("--no-gui", action="store_true",
                        help="Run headless (no cv2 window).")
    args = parser.parse_args()

    log.info("Initializing Spirit Navigation System...")

    try:
        vision, fusion, maps, gps, listener, camera, chat_manager = _initialize_system()
    except Exception as e:
        print(f"FATAL: Spirit failed to start up: {e}")
        log.exception("Fatal startup error.")
        sys.exit(1)

    muted = False
    last_known = {"sensors": {}, "hazards": [], "vehicles": [], "address": None, "location": {}}
    last_geocode_time = 0.0

    gps.start()

    watchdog = CameraWatchdog(camera, fusion.audio)
    cam_ok = wait_for_first_frame(camera, timeout=8.0)
    watchdog.set_initial(cam_ok)

    if cam_ok:
        intro = ("Hello Master, I'm Spirit, your navigation assistant. My camera, sensors, "
                 "and location are all online. Say my name whenever you need me.")
    else:
        intro = ("Hello Master, I'm Spirit. Heads up, I can't reach my camera right now, so "
                 "I can't see hazards. I'll keep trying to reconnect. My voice and location "
                 "features still work. Say my name whenever you need me.")
    _say(f"Spirit: {intro}")
    fusion.audio.speak_async(intro)
    # Start listening only after the intro is queued: the mic calibration waits for
    # Spirit to finish speaking, so it never learns Spirit's own voice as background noise.
    listener.start()

    if not args.no_gui:
        log.info("Press 'q' to quit, 'm' to mute/unmute mic.")

    fps = 0.0

    try:
        while True:
            start_time = time.time()

            loc = gps.get_location()
            now = time.time()
            if (loc.get("gps_ok") and maps.enabled
                    and now - last_geocode_time > GEOCODE_REFRESH_INTERVAL_SEC):
                address = maps.reverse_geocode(loc["lat"], loc["lon"])
                if address:
                    last_known["address"] = address
                last_geocode_time = now
            last_known["location"] = loc

            frame, sensors, ok = camera.read()
            watchdog.tick(ok)

            if not ok:
                if watchdog.lost:
                    # Never leave stale detections around: they'd be reported as live.
                    last_known["hazards"] = []
                    last_known["vehicles"] = []
                    last_known["sensors"] = {}
                if not args.no_gui:
                    cv2.imshow(WINDOW_NAME,
                               draw_offline_screen(camera.link_up, watchdog.down_secs))
                else:
                    time.sleep(0.1)
            else:
                try:
                    annotated_frame, hazards, vehicles = vision.process_frame(frame)
                    fusion.process(hazards, vehicles, sensors)
                    last_known["sensors"] = sensors
                    last_known["hazards"] = hazards
                    last_known["vehicles"] = vehicles
                except Exception:
                    log.exception("Vision/fusion pipeline error; showing raw frame instead.")
                    annotated_frame, hazards, vehicles = frame, [], []

                if not args.no_gui:
                    draw_hud(annotated_frame, fps=fps,
                             listening=not muted, thinking=chat_manager.is_thinking,
                             hazards=hazards, vehicles=vehicles,
                             gps_ok=loc.get("gps_ok", False))
                    cv2.imshow(WINDOW_NAME, annotated_frame)

            # Drain voice command queue
            try:
                while True:
                    voice_data = listener.command_queue.get_nowait()

                    if voice_data == "WAKE":
                        continue

                    if not voice_data or not voice_data.strip():
                        continue

                    sensor_summary = build_environment_summary(last_known, camera_ok=not watchdog.lost)
                    is_urgent = (not watchdog.lost) and bool(
                        last_known.get("hazards") or last_known.get("vehicles"))
                    chat_manager.submit(voice_data, sensor_summary, urgent=is_urgent)
            except queue.Empty:
                pass

            # Keyboard input
            if not args.no_gui:
                key = cv2.waitKey(1) & 0xFF
                if key == ord('q'):
                    break
                elif key == ord('m'):
                    muted = not muted
                    if muted:
                        listener.stop()
                    else:
                        listener.start()
                    log.info("Microphone %s.", "muted" if muted else "unmuted")

            # Frame pacing
            elapsed = time.time() - start_time
            fps = 1.0 / elapsed if elapsed > 0 else 0.0
            delay = max(0.0, (1.0 / TARGET_FPS) - elapsed)
            time.sleep(delay)

    except KeyboardInterrupt:
        pass
    except Exception:
        log.exception("Unhandled error in main loop.")
    finally:
        goodbye = random.choice(GOODBYE_PHRASES)
        _say(f"Spirit: {goodbye}")
        fusion.audio.speak_async(goodbye)
        fusion.audio.wait_until_done(timeout=5.0)
        time.sleep(0.5)

        log.info("Shutting down...")
        try:
            listener.stop()
        except Exception:
            pass
        chat_manager.shutdown()
        gps.stop()
        camera.release()
        cv2.destroyAllWindows()
        log.info("Shutdown complete.")


if __name__ == "__main__":
    main()
