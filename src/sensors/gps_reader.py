# import logging
# import os
# import threading
# import time

# logger = logging.getLogger("spirit.gps")

# try:
#     import serial
# except ImportError:
#     serial = None

# try:
#     import pynmea2
# except ImportError:
#     pynmea2 = None


# class GPSReader:
#     """
#     Reads NMEA sentences from a NEO-6M GPS module over serial (UART) and
#     caches the latest fix — same background-thread-plus-cache pattern as
#     ESP32Client, for the same reason: a blocking serial read must never
#     stall the main loop.

#     On the Raspberry Pi, the NEO-6M is typically wired to the UART pins and
#     shows up at /dev/serial0 (or /dev/ttyAMA0 / /dev/ttyS0 depending on Pi
#     model and raspi-config UART settings). On Windows (dev/testing), there's
#     no GPS hardware unless you have a USB GPS dongle on a COM port — in that
#     case this just reports gps_ok=False and the rest of the app degrades
#     gracefully (spirit_agent already knows how to honestly say "no location
#     right now" instead of making something up).

#     Configure the port via the GPS_PORT env var (see config/settings.py).
#     """

#     def __init__(self, port: str = None, baudrate: int = 9600, timeout: float = 1.0):
#         self.port = port or os.environ.get("GPS_PORT", "/dev/serial0")
#         self.baudrate = baudrate
#         self.timeout = timeout

#         self._lock = threading.Lock()
#         self._latest = {"lat": None, "lon": None, "gps_ok": False, "satellites": None}
#         self.is_running = False
#         self._thread = None
#         self._warned_missing_deps = False
#         self._last_error_log_time = 0.0
#         self._error_streak = 0

#     def start(self):
#         if self._thread is not None and self._thread.is_alive():
#             return
#         if serial is None or pynmea2 is None:
#             if not self._warned_missing_deps:
#                 logger.warning(
#                     "pyserial/pynmea2 not installed — GPS disabled. "
#                     "Install with: pip install pyserial pynmea2"
#                 )
#                 self._warned_missing_deps = True
#             return
#         self.is_running = True
#         self._thread = threading.Thread(target=self._read_loop, daemon=True, name="gps-reader")
#         self._thread.start()
#         logger.info(f"GPS reader started on {self.port} @ {self.baudrate} baud.")

#     def stop(self):
#         self.is_running = False
#         if self._thread is not None:
#             self._thread.join(timeout=2.0)
#             self._thread = None
#         with self._lock:
#             self._latest = {"lat": None, "lon": None, "gps_ok": False, "satellites": None}
#         logger.info("GPS reader stopped.")

#     def _read_loop(self):
#         ser = None
#         while self.is_running:
#             try:
#                 if ser is None:
#                     ser = serial.Serial(self.port, self.baudrate, timeout=self.timeout)

#                 raw = ser.readline().decode('ascii', errors='replace').strip()
#                 if not raw.startswith('$'):
#                     continue

#                 try:
#                     msg = pynmea2.parse(raw)
#                 except pynmea2.ParseError:
#                     continue

#                 # GGA carries fix quality + satellite count + lat/lon in one sentence.
#                 if msg.sentence_type == 'GGA':
#                     has_fix = getattr(msg, 'gps_qual', 0) and int(msg.gps_qual) > 0
#                     if has_fix and msg.latitude and msg.longitude:
#                         self._error_streak = 0  # port is working — reset the warning throttle
#                         with self._lock:
#                             self._latest = {
#                                 "lat": msg.latitude,
#                                 "lon": msg.longitude,
#                                 "gps_ok": True,
#                                 "satellites": msg.num_sats,
#                             }
#                     else:
#                         with self._lock:
#                             self._latest["gps_ok"] = False

#             except Exception as e:
#                 # Throttled: warn immediately on the FIRST failure so it's
#                 # visible once, then only every 60s after that — this is a
#                 # known/expected state on a dev machine with no GPS
#                 # hardware, and repeating it every ~2s forever conflicts
#                 # with QUIET_TERMINAL's whole point (conversation flow +
#                 # things that actually need attention, not a fact you
#                 # already know).
#                 self._error_streak += 1
#                 now = time.time()
#                 if self._error_streak == 1 or now - self._last_error_log_time > 60:
#                     logger.warning(
#                         f"GPS read error on {self.port} ({self._error_streak} attempts so far): {e}"
#                     )
#                     self._last_error_log_time = now
#                 with self._lock:
#                     self._latest["gps_ok"] = False
#                 if ser is not None:
#                     try:
#                         ser.close()
#                     except Exception:
#                         pass
#                     ser = None
#                 time.sleep(2.0)  # back off before retrying the port

#         if ser is not None:
#             try:
#                 ser.close()
#             except Exception:
#                 pass

#     def get_location(self) -> dict:
#         """Returns {"lat", "lon", "gps_ok", "satellites"} — instant, never blocks."""
#         with self._lock:
#             return dict(self._latest)






# import threading
# import time
# import logging
# import platform
# from config.settings import GPS_PORT, GPS_BAUDRATE

# logger = logging.getLogger("spirit.gps")

# # Dummy coordinates for Windows testing
# # Change these to your actual location
# DUMMY_LAT = 6.5244    # Example: Lagos, Nigeria
# DUMMY_LON = 3.3792
# DUMMY_LOCATION_NAME = "Lagos, Nigeria"


# class GPSReader:
#     def __init__(self):
#         self._lat = None
#         self._lon = None
#         self._gps_ok = False
#         self._lock = threading.Lock()
#         self._running = False
#         self._thread = None
#         self._attempts = 0
        
#         # Detect if we're on Windows (no real GPS)
#         self._is_windows = platform.system() == "Windows"
        
#         if self._is_windows:
#             logger.info("Windows detected — using dummy GPS coordinates")
#             self._lat = DUMMY_LAT
#             self._lon = DUMMY_LON
#             self._gps_ok = True

#     def _read_loop(self):
#         """Real GPS reading loop for Raspberry Pi with NEO-6M."""
#         try:
#             import serial
#         except ImportError:
#             logger.error("pyserial not installed. Run: pip install pyserial")
#             return

#         while self._running:
#             try:
#                 with serial.Serial(GPS_PORT, GPS_BAUDRATE, timeout=1) as ser:
#                     logger.info("GPS serial connection established.")
#                     buffer = ""
#                     while self._running:
#                         line = ser.readline().decode('ascii', errors='replace').strip()
#                         if line.startswith('$GPGGA') or line.startswith('$GPRMC'):
#                             self._parse_nmea(line)
#                         time.sleep(0.1)
#             except serial.SerialException as e:
#                 self._attempts += 1
#                 if self._attempts <= 5 or self._attempts % 30 == 0:
#                     logger.warning("GPS read error on %s (%d attempts so far): %s", 
#                                    GPS_PORT, self._attempts, e)
#                 time.sleep(5)
#             except Exception as e:
#                 logger.error("Unexpected GPS error: %s", e)
#                 time.sleep(5)

#     def _parse_nmea(self, line):
#         """Parse NMEA sentence for latitude/longitude."""
#         try:
#             parts = line.split(',')
            
#             if line.startswith('$GPGGA'):
#                 if len(parts) < 6 or parts[2] == '' or parts[4] == '':
#                     return
#                 lat_raw = float(parts[2])
#                 lat_dir = parts[3]
#                 lon_raw = float(parts[4])
#                 lon_dir = parts[5]
                
#                 lat = self._nmea_to_decimal(lat_raw, lat_dir)
#                 lon = self._nmea_to_decimal(lon_raw, lon_dir)
#                 fix = int(parts[6])
                
#                 if fix > 0:
#                     with self._lock:
#                         self._lat = lat
#                         self._lon = lon
#                         self._gps_ok = True
#                         self._attempts = 0
            
#             elif line.startswith('$GPRMC'):
#                 if len(parts) < 7 or parts[3] == '' or parts[5] == '':
#                     return
#                 if parts[2] == 'V':  # Invalid
#                     return
#                 lat_raw = float(parts[3])
#                 lat_dir = parts[4]
#                 lon_raw = float(parts[5])
#                 lon_dir = parts[6]
                
#                 lat = self._nmea_to_decimal(lat_raw, lat_dir)
#                 lon = self._nmea_to_decimal(lon_raw, lon_dir)
                
#                 with self._lock:
#                     self._lat = lat
#                     self._lon = lon
#                     self._gps_ok = True
#                     self._attempts = 0
#         except (ValueError, IndexError) as e:
#             pass  # Malformed sentence, ignore

#     @staticmethod
#     def _nmea_to_decimal(raw, direction):
#         """Convert NMEA coordinates (DDMM.MMMM) to decimal degrees."""
#         if direction in ('N', 'S'):
#             degrees = int(raw / 100)
#             minutes = raw - (degrees * 100)
#         else:
#             degrees = int(raw / 100)
#             minutes = raw - (degrees * 100)
#         decimal = degrees + (minutes / 60.0)
#         if direction in ('S', 'W'):
#             decimal = -decimal
#         return decimal

#     def get_location(self):
#         """Returns dict with lat, lon, gps_ok, and location_name."""
#         with self._lock:
#             result = {
#                 "lat": self._lat,
#                 "lon": self._lon,
#                 "gps_ok": self._gps_ok,
#             }
#             if self._is_windows and self._gps_ok:
#                 result["location_name"] = DUMMY_LOCATION_NAME
#             return result

#     def start(self):
#         if self._is_windows:
#             logger.info("Using dummy GPS: %s (%.4f, %.4f)", DUMMY_LOCATION_NAME, DUMMY_LAT, DUMMY_LON)
#             return
            
#         self._running = True
#         self._thread = threading.Thread(target=self._read_loop, daemon=True, name="gps-reader")
#         self._thread.start()

#     def stop(self):
#         self._running = False
#         if self._thread and self._thread.is_alive():
#             self._thread.join(timeout=2)



import threading
import time
import logging
from config.settings import GPS_PORT, GPS_BAUDRATE
 
logger = logging.getLogger("spirit.gps")
 
# Reverse geocoding is optional � only used if you want location_name populated.
# Set to False if you don't want outbound network calls from the GPS reader.
ENABLE_REVERSE_GEOCODE = True
REVERSE_GEOCODE_INTERVAL = 15  # seconds between lookups, to respect Nominatim's rate limit
 
 
class GPSReader:
    def __init__(self):
        self._lat = None
        self._lon = None
        self._gps_ok = False
        self._location_name = None
        self._lock = threading.Lock()
        self._running = False
        self._thread = None
        self._attempts = 0
        self._last_geocode_time = 0
 
    def _read_loop(self):
        """Real GPS reading loop for Raspberry Pi with NEO-6M."""
        try:
            import serial
        except ImportError:
            logger.error("pyserial not installed. Run: pip install pyserial")
            return
 
        while self._running:
            try:
                with serial.Serial(GPS_PORT, GPS_BAUDRATE, timeout=1) as ser:
                    logger.info("GPS serial connection established.")
                    while self._running:
                        line = ser.readline().decode('ascii', errors='replace').strip()
                        if line.startswith('$GPGGA') or line.startswith('$GPRMC'):
                            self._parse_nmea(line)
                        time.sleep(0.1)
            except serial.SerialException as e:
                self._attempts += 1
                if self._attempts <= 5 or self._attempts % 30 == 0:
                    logger.warning("GPS read error on %s (%d attempts so far): %s",
                                   GPS_PORT, self._attempts, e)
                time.sleep(5)
            except Exception as e:
                logger.error("Unexpected GPS error: %s", e)
                time.sleep(5)

    def _parse_nmea(self, line):
        """Parse NMEA sentence for latitude/longitude."""
        try:
            parts = line.split(',')
            if line.startswith('$GPGGA'):
                if len(parts) < 6 or parts[2] == '' or parts[4] == '':
                        return
                    
                lat_raw = float(parts[2])
                lat_dir = parts[3]
                lon_raw = float(parts[4])
                lon_dir = parts[5]
    
                lat = self._nmea_to_decimal(lat_raw, lat_dir)
                lon = self._nmea_to_decimal(lon_raw, lon_dir)
                fix = int(parts[6])
    
                if fix > 0:
                    self._update_position(lat, lon)
    
            elif line.startswith('$GPRMC'):
                if len(parts) < 7 or parts[3] == '' or parts[5] == '':
                    return
                if parts[2] == 'V':  # Invalid
                    return
                
                lat_raw = float(parts[3])
                lat_dir = parts[4]
                lon_raw = float(parts[5])
                lon_dir = parts[6]
    
                lat = self._nmea_to_decimal(lat_raw, lat_dir)
                lon = self._nmea_to_decimal(lon_raw, lon_dir)
    
                self._update_position(lat, lon)
    
                
               
        
        except (ValueError, IndexError):
            pass  # Malformed sentence, ignore


 


    def _update_position(self, lat, lon):
        with self._lock:
            self._lat = lat
            self._lon = lon
            self._gps_ok = True
            self._attempts = 0
 
        if ENABLE_REVERSE_GEOCODE:
            now = time.time()
            if now - self._last_geocode_time > REVERSE_GEOCODE_INTERVAL:
                self._last_geocode_time = now
                # Do the network call off the serial-read thread's hot path timing,
                # but still in a background thread so it never blocks GPS reads.
                threading.Thread(
                    target=self._reverse_geocode, args=(lat, lon), daemon=True
                ).start()
 
    def _reverse_geocode(self, lat, lon):
        try:
            import requests
            response = requests.get(
                "https://nominatim.openstreetmap.org/reverse",
                params={"lat": lat, "lon": lon, "format": "json"},
                headers={"User-Agent": "Project-Spirit-Pi"},
                timeout=5,
            )
            data = response.json()
            name = data.get("display_name")
            if name:
                with self._lock:
                    self._location_name = name
        except Exception as e:
            logger.warning("Reverse geocode failed: %s", e)
 
    @staticmethod
    def _nmea_to_decimal(raw, direction):
        """Convert NMEA coordinates (DDMM.MMMM) to decimal degrees."""
        degrees = int(raw / 100)
        minutes = raw - (degrees * 100)
        decimal = degrees + (minutes / 60.0)
        if direction in ('S', 'W'):
            decimal = -decimal
        return decimal
 
    def get_location(self):
        """Returns dict with lat, lon, gps_ok, and location_name (if resolved)."""
        with self._lock:
            return {
                "lat": self._lat,
                "lon": self._lon,
                "gps_ok": self._gps_ok,
                "location_name": self._location_name,
            }
 
    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._read_loop, daemon=True, name="gps-reader")
        self._thread.start()
 
    def stop(self):
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
 