#!/usr/bin/env python3
import contextlib
import logging
import os
import queue
import random
import threading
import time

import speech_recognition as sr

from config.settings import QUIET_TERMINAL

logger = logging.getLogger("spirit.wake_word")

SLEEP_PHRASES = (
    "stop listening", "go to sleep", "sleep now", "goodnight",
    "that's all for now", "thats all for now", "you can sleep now",
)

FOLLOWUP_TIMEOUT_SEC = 8
MAX_CONSECUTIVE_SILENT_TIMEOUTS = 6
SILENT_TIMEOUT_HEARTBEAT = 6

WAKE_RESPONSES = [
    "Yes, Master? I'm listening.",
    "I'm here, Master.",
    "Go ahead, Master.",
    "Yes, Master?",
]

ACTIVITY_START_TIMEOUT_SEC = 3.0

# Microphone calibration limits. One bad calibration must never make Spirit deaf.
CALIBRATION_SECONDS = 2.0
MIN_ENERGY_THRESHOLD = 300
MAX_ENERGY_THRESHOLD = 1200


# ---------------------------------------------------------------------------
# HELPER: Suppress ALSA errors
# ---------------------------------------------------------------------------
@contextlib.contextmanager
def suppress_alsa_errors():
    devnull_fd = os.open(os.devnull, os.O_WRONLY)
    saved_stderr_fd = os.dup(2)
    try:
        os.dup2(devnull_fd, 2)
        yield
    finally:
        os.dup2(saved_stderr_fd, 2)
        os.close(saved_stderr_fd)
        os.close(devnull_fd)


# ---------------------------------------------------------------------------
# HELPER: Auto-select device
# ---------------------------------------------------------------------------
def pick_device_index(mics, preferred_keyword="USB"):
    for index, name in enumerate(mics):
        if preferred_keyword.lower() in name.lower():
            return index
    return None


def _say(text: str):
    print(text)


def _debug(text: str):
    if not QUIET_TERMINAL:
        print(text)


def _is_just_wake_word(text: str, wake_words) -> bool:
    normalized = text.strip().lower().strip(".,!?")
    return normalized in wake_words


# ---------------------------------------------------------------------------
# WakeWordListener
# ---------------------------------------------------------------------------
class WakeWordListener:
    def __init__(self, audio_engine, wake_words=None, device_index: int = None):
        self.recognizer = sr.Recognizer()
        self.wake_words = list(wake_words) if wake_words else ["spirit", "hey spirit", "a spirit"]
        self.command_queue = queue.Queue()
        self.is_running = False
        self.audio_engine = audio_engine
        self._thread = None

        # Device selection: explicit argument, then MIC_DEVICE_INDEX, then auto-detect USB mic
        if device_index is not None:
            self.device_index = device_index
        else:
            env_index = os.environ.get("MIC_DEVICE_INDEX")
            if env_index is not None:
                self.device_index = int(env_index)
            else:
                with suppress_alsa_errors():
                    mics = sr.Microphone.list_microphone_names()

                auto_index = pick_device_index(mics, preferred_keyword="USB")
                if auto_index is not None:
                    self.device_index = auto_index
                    _debug(f"Auto-selected USB Mic at index {auto_index}: {mics[auto_index]}")
                else:
                    _debug("No USB mic found, falling back to default device (Index 0).")
                    self.device_index = 0

        # Fixed threshold so it doesn't drift in the middle of a sentence.
        # _calibrate() sets the real value once the mic is open.
        self.recognizer.dynamic_energy_threshold = False
        self.recognizer.energy_threshold = 400

    @staticmethod
    def list_microphones():
        names = sr.Microphone.list_microphone_names()
        _debug("Available microphones:")
        for i, name in enumerate(names):
            _debug(f"  [{i}] {name}")
        return names

    def _wait_until_silent(self, extra_buffer=1.0):
        self.audio_engine.wait_until_done(timeout=30.0)
        time.sleep(extra_buffer)

    def _wait_for_activity_then_silent(self, start_wait_sec=ACTIVITY_START_TIMEOUT_SEC,
                                       extra_buffer=1.0):
        waited = 0.0
        while not self.audio_engine.speaking_event.is_set() and waited < start_wait_sec:
            time.sleep(0.1)
            waited += 0.1
        self._wait_until_silent(extra_buffer=extra_buffer)

    def _calibrate(self, source):
        """Measure background noise in silence, then clamp the result."""
        # Never calibrate while Spirit is talking: it would learn its own voice as noise.
        self.audio_engine.wait_until_done(timeout=30.0)
        time.sleep(1.0)

        _debug("Calibrating background noise...")
        self.recognizer.adjust_for_ambient_noise(source, duration=CALIBRATION_SECONDS)

        # adjust_for_ambient_noise already adds a safety margin, so no extra multiplier here.
        measured = self.recognizer.energy_threshold
        self.recognizer.energy_threshold = min(max(measured, MIN_ENERGY_THRESHOLD),
                                               MAX_ENERGY_THRESHOLD)
        _say(f"Spirit: Mic calibrated (measured {measured:.0f}, using "
             f"{self.recognizer.energy_threshold:.0f}).")

    def _listen_for_command(self, source, timeout=8, phrase_time_limit=10,
                            announce_failures=True):
        max_attempts = 2 if announce_failures else 1
        for attempt in range(1, max_attempts + 1):
            try:
                _debug(f"[DEBUG] Listening (attempt {attempt})...")
                with suppress_alsa_errors():
                    audio = self.recognizer.listen(source, timeout=timeout,
                                                   phrase_time_limit=phrase_time_limit)

                text = self.recognizer.recognize_google(audio)
                _debug(f"[DEBUG] Recognized: '{text}'")
                return text

            except sr.WaitTimeoutError:
                _debug("[DEBUG] Timeout")
                return None

            except sr.UnknownValueError:
                _debug(f"[DEBUG] Couldn't understand (attempt {attempt})")
                if announce_failures and attempt < max_attempts:
                    self.audio_engine.speak_async("Say that again?")
                    self._wait_for_activity_then_silent()
                    continue
                if announce_failures:
                    self.audio_engine.speak_async("Didn't catch that.")
                    self._wait_for_activity_then_silent()
                return None

            except sr.RequestError as e:
                logger.error(f"Google API error: {e}")
                return None

            except Exception as e:
                logger.error(f"Error: {e}")
                return None

        return None

    def _run_conversation(self, source):
        consecutive_silence = 0

        while self.is_running:
            self._wait_until_silent(extra_buffer=1.5)

            followup = self._listen_for_command(
                source, timeout=FOLLOWUP_TIMEOUT_SEC, phrase_time_limit=10,
                announce_failures=False,
            )

            if not followup:
                consecutive_silence += 1
                _debug(f"[DEBUG] Silence {consecutive_silence}/{MAX_CONSECUTIVE_SILENT_TIMEOUTS}")
                if consecutive_silence >= MAX_CONSECUTIVE_SILENT_TIMEOUTS:
                    self.audio_engine.speak_async("Going to sleep. Say my name to wake me.")
                    self._wait_until_silent()
                    _say("Spirit: Listening for 'Spirit'...")
                    return
                continue

            consecutive_silence = 0

            if any(phrase in followup.lower() for phrase in SLEEP_PHRASES):
                _say(f"You: {followup}")
                self.audio_engine.speak_async("Okay, going to sleep.")
                self._wait_until_silent()
                _say("Spirit: Listening for 'Spirit'...")
                return

            if _is_just_wake_word(followup, self.wake_words):
                _debug(f"[DEBUG] Ignored bare wake-word echo: '{followup}'")
                continue

            _say(f"You: {followup}")
            self.command_queue.put(followup)

            self._wait_for_activity_then_silent(extra_buffer=1.0)

    def _listen_loop(self):
        self.list_microphones()
        if self.device_index is not None:
            _debug(f"Using microphone device index {self.device_index}")

        with suppress_alsa_errors():
            with sr.Microphone(device_index=self.device_index) as source:
                self._calibrate(source)
                _say("Spirit: Listening for 'Spirit'...")

                consecutive_silent_timeouts = 0

                while self.is_running:
                    try:
                        # Don't listen while Spirit is speaking (it would hear itself)
                        if self.audio_engine.speaking_event.is_set():
                            time.sleep(0.2)
                            continue

                        with suppress_alsa_errors():
                            audio = self.recognizer.listen(source, timeout=5, phrase_time_limit=5)

                        consecutive_silent_timeouts = 0

                        text = self.recognizer.recognize_google(audio).lower()
                        _debug(f"[DEBUG] Heard: '{text}'")

                        if any(word in text for word in self.wake_words):
                            wake_response = random.choice(WAKE_RESPONSES)
                            _say(f"Spirit: {wake_response}")
                            self.command_queue.put("WAKE")
                            self.audio_engine.speak_async(wake_response)

                            self._wait_until_silent(extra_buffer=1.0)

                            command_text = self._listen_for_command(
                                source, timeout=10, phrase_time_limit=10,
                                announce_failures=True
                            )

                            if command_text:
                                if any(p in command_text.lower() for p in SLEEP_PHRASES):
                                    _say(f"You: {command_text}")
                                    self.audio_engine.speak_async("Okay.")
                                    self._wait_until_silent()
                                    _say("Spirit: Listening for 'Spirit'...")
                                    continue

                                if _is_just_wake_word(command_text, self.wake_words):
                                    _debug(f"[DEBUG] Ignored bare wake-word echo: '{command_text}'")
                                    self._run_conversation(source)
                                else:
                                    _say(f"You: {command_text}")
                                    self.command_queue.put(command_text)
                                    self._run_conversation(source)
                            else:
                                _debug("[DEBUG] No command after wake word")
                                _say("Spirit: Listening for 'Spirit'...")

                    except sr.WaitTimeoutError:
                        consecutive_silent_timeouts += 1
                        if consecutive_silent_timeouts == SILENT_TIMEOUT_HEARTBEAT:
                            logger.warning("No audio for ~%ds.", SILENT_TIMEOUT_HEARTBEAT * 5)
                            consecutive_silent_timeouts = 0
                        continue
                    except sr.UnknownValueError:
                        continue
                    except Exception as e:
                        logger.error(f"Audio error: {e}")
                        time.sleep(1)

    def start(self):
        self.is_running = True
        # If the previous loop is still winding down (quick mute/unmute), reuse it.
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._listen_loop, daemon=True,
                                        name="spirit-listener")
        self._thread.start()

    def stop(self):
        self.is_running = False