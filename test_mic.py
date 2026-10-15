# import speech_recognition as sr
# import sys

# def list_microphones():
#     print("--- Available Microphones ---")
#     mics = sr.Microphone.list_microphone_names()
#     for index, name in enumerate(mics[:5]): 
#         print(f"Index {index}: {name}")
#     return mics

# def test_mic():
#     mics = list_microphones()
    
#     # Use Index 1 (Your USB Mic)
#     device_index = 1 
#     print(f"\nUsing Index {device_index}: {mics[device_index]}")

#     # 2. Setup Recognizer
#     r = sr.Recognizer()
    
#     # 3. CONFIGURATION
#     # Keep this OFF so it doesn't cut off mid-sentence
#     r.dynamic_energy_threshold = False
    
#     # Fixed sensitivity (prevents volume jumps)
#     r.energy_threshold = 300 
    
#     # FAST STOP: Stop recording after 0.8 seconds of silence
#     # This is the standard "human" pause between sentences.
#     r.pause_threshold = 0.8 
    
#     print(f"Energy Threshold LOCKED at: {r.energy_threshold}")
#     print(f"Pause Threshold: {r.pause_threshold} seconds (Fast)")
    
#     try:
#         with sr.Microphone(device_index=device_index) as source:
#             print("\n========================================================")
#             print("LISTENING...")
#             print("Speak continuously. Stops after 0.8s of silence.")
#             print("========================================================")
            
#             # phrase_time_limit=None = Allows long sentences
#             # But pause_threshold=0.8 = Stops quickly when you finish
#             audio = r.listen(source, timeout=None, phrase_time_limit=None)
            
#             print("\nProcessing audio...")
            
#             try:
#                 text = r.recognize_google(audio, language='en-US')
#                 print(f"\nSUCCESS: You said:\n'{text}'")
#             except sr.UnknownValueError:
#                 print("\nERROR: Audio heard, but could not understand words.")
#             except sr.RequestError as e:
#                 print(f"\nERROR: Google API error; {e}")
                
#     except OSError as e:
#         print(f"\nCRITICAL ERROR: Could not open microphone: {e}")

# if __name__ == "__main__":
#     test_mic()





#!/usr/bin/env python3
"""
Speech recognition mic test, tuned for Raspberry Pi 4.
 
Setup on the Pi (Raspberry Pi OS / Debian-based):
    sudo apt update
    sudo apt install -y portaudio19-dev flac
    pip3 install SpeechRecognition pyaudio
"""
 
import os
import sys
import contextlib
 
try:
    import speech_recognition as sr
except ImportError:
    sys.exit(
        "Missing dependency: run 'pip3 install SpeechRecognition pyaudio'\n"
        "and 'sudo apt install portaudio19-dev flac' first."
    )
 
 
# ---------------------------------------------------------------------------
# Raspberry Pi's ALSA config is noisy: it prints a wall of "unable to open
# slave" / JACK-server warnings straight to the C-level stderr file
# descriptor, which Python can't catch as an exception. We redirect fd 2
# (real OS-level stderr) to /dev/null for the duration of the risky calls.
#
# NOTE: an earlier version of this used a ctypes callback registered with
# ALSA's snd_lib_error_set_handler. That approach can segfault (the C
# library can call the callback after Python has GC'd it, or it can clash
# with PortAudio's own ALSA error handling). Redirecting the raw fd is
# safer because no Python object needs to stay alive on the C side.
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
 
 
def list_microphones():
    print("--- Available Microphones ---")
    with suppress_alsa_errors():
        mics = sr.Microphone.list_microphone_names()
    for index, name in enumerate(mics):
        print(f"Index {index}: {name}")
    return mics
 
 
def pick_device_index(mics, preferred_keyword="USB"):
    """
    Auto-select a mic by keyword (default: 'USB') instead of a hardcoded
    index, since USB enumeration order can shift on the Pi across reboots
    or when other USB devices are plugged in.
    """
    for index, name in enumerate(mics):
        if preferred_keyword.lower() in name.lower():
            return index
    return None
 



def test_mic():
    mics = list_microphones()
    if not mics:
        print("\nCRITICAL ERROR: No microphones detected by PortAudio.")
        print("Check 'arecord -l' to confirm the OS sees the device.")
        return
 
    device_index = pick_device_index(mics, preferred_keyword="USB")
    if device_index is None:
        print("\nNo device with 'USB' in its name found � falling back to index 0.")
        print("Edit preferred_keyword in pick_device_index() if needed.")
        device_index = 0
 
    print(f"\nUsing Index {device_index}: {mics[device_index]}")
 
    r = sr.Recognizer()
 
    # Keep this OFF so it doesn't cut off mid-sentence / hunt for a new
    # threshold mid-recording.
    r.dynamic_energy_threshold = False
 
    # Stop recording after this many seconds of silence.
    r.pause_threshold = 0.8
 
    # How long to wait for speech to START before giving up (prevents an
    # infinite hang if the threshold is wrong or the mic is silent).
    LISTEN_TIMEOUT = 10
 
    try:
        with suppress_alsa_errors():
            mic = sr.Microphone(device_index=device_index)
 
        with mic as source:
            # --- Calibrate against real ambient noise instead of guessing ---
            # A fixed guess like 300 is meaningless without knowing what this
            # specific mic/gain actually reports for silence. This measures
            # 1.5s of ambient noise and sets the threshold a bit above it.
            print("\nCalibrating ambient noise (stay quiet for 1.5s)...")
            with suppress_alsa_errors():
                r.adjust_for_ambient_noise(source, duration=1.5)
            print(f"Ambient noise measured at: {r.energy_threshold:.0f}")
 
            # Push the threshold above ambient so background hiss doesn't
            # register as continuous "speech" and block the pause detector.
            r.energy_threshold = max(r.energy_threshold * 1.5, 50)
            print(f"Energy Threshold set to: {r.energy_threshold:.0f}")
            print(f"Pause Threshold: {r.pause_threshold} seconds")
 
            print("\n========================================================")
            print(f"LISTENING... (times out after {LISTEN_TIMEOUT}s of no speech)")
            print("Speak continuously. Stops after 0.8s of silence.")
            print("========================================================")
 
            try:
                audio = r.listen(source, timeout=LISTEN_TIMEOUT, phrase_time_limit=None)
            except sr.WaitTimeoutError:
                print(f"\nERROR: No speech detected within {LISTEN_TIMEOUT}s.")
                print("Try speaking louder/closer to the mic, or check its input gain")
                print("with 'alsamixer' (select the USB card with F6).")
                return
 
        print("\nProcessing audio...")
 
        try:
            text = r.recognize_google(audio, language="en-US")
            print(f"\nSUCCESS: You said:\n'{text}'")
        except sr.UnknownValueError:
            print("\nERROR: Audio heard, but could not understand words.")
        except sr.RequestError as e:
            print(f"\nERROR: Google API error (check internet connectivity on the Pi): {e}")
 
    except OSError as e:
        print(f"\nCRITICAL ERROR: Could not open microphone: {e}")
        print("Try: 'arecord -l' to list ALSA devices and confirm the index/name match.")
    except KeyboardInterrupt:
        print("\nStopped by user.")
 
 
if __name__ == "__main__":
    test_mic()
 