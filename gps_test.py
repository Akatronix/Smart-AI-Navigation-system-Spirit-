# import serial
# import pynmea2
# import requests
# import time

# def reverse_geocode(lat, lon):
#     try:
#         response = requests.get(
#             "https://nominatim.openstreetmap.org/reverse",
#             params={"lat": lat, "lon": lon, "format": "json"},
#             headers={"User-Agent": "Project-Spirit-Pi"},
#             timeout=5
#         )
#         data = response.json()
#         return data.get("display_name", "Unknown location")
#     except Exception as e:
#         return f"Geocoding failed: {e}"

# def parse_gps():
#     port = "/dev/serial0"
#     last_geocode_time = 0

#     try:
#         ser = serial.Serial(port, baudrate=9600, timeout=1)
#         print(f"Connected to GPS on {port}")

#         while True:
#             line = ser.readline().decode('ascii', errors='replace').strip()

#             if line.startswith('$GNGGA') or line.startswith('$GPGGA'):
#                 try:
#                     msg = pynmea2.parse(line)

#                     if msg.gps_qual in [1, 2]:
#                         lat = msg.latitude
#                         lon = msg.longitude
#                         alt = msg.altitude
#                         satellites = msg.num_sats

#                         print(f"Fix acquired! Lat: {lat:.6f}, Lon: {lon:.6f}, Alt: {alt}m, Sats: {satellites}")

#                         # Only reverse geocode once every 15s to respect Nominatim's rate limit
#                         now = time.time()
#                         if now - last_geocode_time > 15:
#                             address = reverse_geocode(lat, lon)
#                             print(f"  ? Address: {address}")
#                             last_geocode_time = now
#                     else:
#                         print("Searching for satellites...")

#                 except pynmea2.ParseError:
#                     continue

#     except KeyboardInterrupt:
#         print("\nExiting...")
#     except Exception as e:
#         print(f"Error: {e}")

# if __name__ == '__main__':
#     parse_gps()







# from groq import Groq
# import os
# from dotenv import load_dotenv
# load_dotenv()
# c = Groq(api_key=os.environ["GROQ_API_KEY"])
# for m in c.models.list().data:
#     print(m.id)




#!/usr/bin/env python3
"""Standalone audio test. Run: python3 audio_test.py"""
import time, subprocess, shutil, sys

print("=== SPIRIT AUDIO TEST ===")

# --- [1] Generate a test audio file ---
print("\n[1] Generating test audio...")
TEST_FILE = "/tmp/spirit_test.mp3"
try:
    import asyncio, edge_tts
    asyncio.run(edge_tts.Communicate(
        "Spirit audio test. Can you hear me?", "en-US-AvaMultilingualNeural"
    ).save(TEST_FILE))
    print(f"    OK -> {TEST_FILE}")
except Exception as e:
    print(f"    edge-tts FAILED: {e}")
    # Fallback: generate a 2-second 440Hz sine wave with pure Python
    import wave, struct, math
    TEST_FILE = "/tmp/spirit_test.wav"
    with wave.open(TEST_FILE, "w") as f:
        f.setnchannels(1); f.setsampwidth(2); f.setframerate(44100)
        for i in range(44100 * 2):
            f.writeframes(struct.pack("<h", int(9000 * math.sin(2 * math.pi * 440 * i / 44100))))
    print(f"    Generated sine wave instead -> {TEST_FILE}")

# --- [2] pygame playback ---
print("\n[2] pygame playback...")
try:
    import pygame
    pygame.mixer.init()
    print(f"    mixer init OK: {pygame.mixer.get_init()}")
    pygame.mixer.music.load(TEST_FILE)
    pygame.mixer.music.play()
    print("    >>> SOUND SHOULD BE PLAYING NOW <<<")
    while pygame.mixer.music.get_busy():
        time.sleep(0.05)
    pygame.mixer.quit()
    print("    OK")
except Exception as e:
    print(f"    FAILED: {type(e).__name__}: {e}")

# --- [3] CLI players ---
print("\n[3] CLI players...")
players = [["mpg123", "-q"], ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"]]
if TEST_FILE.endswith(".wav"):
    players.append(["aplay"])
for cmd in players:
    if not shutil.which(cmd[0]):
        print(f"    {cmd[0]}: not installed")
        continue
    try:
        print(f"    running {cmd[0]}... >>> SOUND SHOULD BE PLAYING NOW <<<")
        subprocess.run(cmd + [TEST_FILE], check=True, timeout=30)
        print(f"    {cmd[0]} OK")
    except Exception as e:
        print(f"    {cmd[0]} FAILED: {e}")

print("\n=== DONE ===")
print("Heard nothing but saw OK? -> routing/mute issue: run 'alsamixer' and 'sudo raspi-config'")