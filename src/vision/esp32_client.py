# import requests
# import numpy as np
# import cv2
# import threading
# import time
# import logging
# from config.settings import STREAM_ENDPOINT, SENSORS_ENDPOINT

# logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
# logger = logging.getLogger(__name__)

# # JPEG start-of-image / end-of-image markers — used to carve individual
# # frames out of the raw MJPEG multipart byte stream.
# JPEG_SOI = b'\xff\xd8'
# JPEG_EOI = b'\xff\xd9'

# # The AI-Thinker ESP32-CAM module is often mounted upside-down or sideways
# # depending on the enclosure, so the sensor's raw output doesn't match "up"
# # in real life. Corrected here on the Python side rather than in firmware —
# # much faster to change without reflashing.
# #   None                          -> no rotation
# #   cv2.ROTATE_180                -> upside-down mount
# #   cv2.ROTATE_90_CLOCKWISE       -> sideways mount (confirmed correct for this rig)
# #   cv2.ROTATE_90_COUNTERCLOCKWISE
# FRAME_ROTATION = cv2.ROTATE_90_CLOCKWISE


# class ESP32Client:
#     """
#     Consumes the ESP32's MJPEG stream (/stream, port 81) over a single
#     persistent connection instead of issuing a fresh HTTP request per frame.

#     Sensors are polled independently on their own thread at ~3Hz — they
#     don't need to update at video framerate, and keeping them separate means
#     a sensor read never has to wait behind a video frame or vice versa.
#     """

#     SENSOR_POLL_INTERVAL_SEC = 0.3

#     def __init__(self):
#         self.latest_frame = None
#         self.latest_sensors = {}
#         self.lock = threading.Lock()
#         self.is_connected = False
#         self.is_running = False
#         self._stream_thread = None
#         self._sensors_thread = None

#     # ------------------------------------------------------------------ #
#     # Video: one persistent MJPEG connection
#     # ------------------------------------------------------------------ #
#     def _stream_loop(self):
#         while self.is_running:
#             try:
#                 resp = requests.get(STREAM_ENDPOINT, stream=True, timeout=5)
#                 if resp.status_code != 200:
#                     raise ConnectionError(f"/stream returned HTTP {resp.status_code}")

#                 if not self.is_connected:
#                     logger.info("ESP32 stream ESTABLISHED.")
#                     self.is_connected = True

#                 buffer = b""
#                 for chunk in resp.iter_content(chunk_size=2048):
#                     if not self.is_running:
#                         break

#                     buffer += chunk
#                     start = buffer.find(JPEG_SOI)
#                     end = buffer.find(JPEG_EOI)

#                     if start != -1 and end != -1 and end > start:
#                         jpg_bytes = buffer[start:end + 2]
#                         buffer = buffer[end + 2:]

#                         img_array = np.frombuffer(jpg_bytes, dtype=np.uint8)
#                         frame = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
#                         if frame is not None:
#                             if FRAME_ROTATION is not None:
#                                 frame = cv2.rotate(frame, FRAME_ROTATION)
#                             with self.lock:
#                                 self.latest_frame = frame

#                     # Guard against an unbounded buffer if we somehow never
#                     # find a valid EOI (corrupted stream) — drop and resync.
#                     elif len(buffer) > 200_000:
#                         buffer = b""

#             except Exception as e:
#                 if self.is_connected:
#                     logger.warning(f"ESP32 stream disconnected: {e}")
#                 self.is_connected = False
#                 # Brief pause before reconnecting so a dead endpoint doesn't
#                 # spin-loop reconnect attempts.
#                 time.sleep(1.0)

#     # ------------------------------------------------------------------ #
#     # Sensors: independent, slower poll — doesn't need video framerate
#     # ------------------------------------------------------------------ #
#     def _sensors_loop(self):
#         while self.is_running:
#             try:
#                 resp = requests.get(SENSORS_ENDPOINT, timeout=3)
#                 if resp.status_code == 200:
#                     with self.lock:
#                         self.latest_sensors = resp.json()
#             except Exception:
#                 pass  # video stream's own logging already reflects connectivity state
#             time.sleep(self.SENSOR_POLL_INTERVAL_SEC)

#     # ------------------------------------------------------------------ #
#     # Lifecycle
#     # ------------------------------------------------------------------ #
#     def start_stream(self):
#         if self.is_running:
#             logger.debug("start_stream() called but already running; ignoring.")
#             return
#         self.is_running = True
#         self._stream_thread = threading.Thread(target=self._stream_loop, daemon=True)
#         self._sensors_thread = threading.Thread(target=self._sensors_loop, daemon=True)
#         self._stream_thread.start()
#         self._sensors_thread.start()
#         logger.info("ESP32 client streaming threads active. (Waiting for connection...)")

#     def stop_stream(self):
#         if not self.is_running:
#             return
#         self.is_running = False
#         for t in (self._stream_thread, self._sensors_thread):
#             if t is not None:
#                 t.join(timeout=3.0)
#         self._stream_thread = None
#         self._sensors_thread = None
#         with self.lock:
#             self.latest_frame = None
#             self.latest_sensors = {}
#         self.is_connected = False
#         logger.info("ESP32 client streaming stopped.")

#     def get_data(self):
#         """Returns the latest frame and sensor data safely."""
#         with self.lock:
#             return (self.latest_frame.copy() if self.latest_frame is not None else None,
#                     self.latest_sensors.copy())






# import requests
# import numpy as np
# import cv2
# import threading
# import time
# import logging
# from config.settings import STREAM_ENDPOINT, SENSORS_ENDPOINT

# logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
# logger = logging.getLogger(__name__)

# # JPEG start-of-image / end-of-image markers — used to carve individual
# # frames out of the raw MJPEG multipart byte stream.
# JPEG_SOI = b'\xff\xd8'
# JPEG_EOI = b'\xff\xd9'

# # The AI-Thinker ESP32-CAM module is often mounted upside-down or sideways
# # depending on the enclosure, so the sensor's raw output doesn't match "up"
# # in real life. Corrected here on the Python side rather than in firmware —
# # much faster to change without reflashing.
# # The AI-Thinker ESP32-CAM module is physically mounted sideways in this
# # enclosure (confirmed: a 90° software rotation fixes orientation but
# # forces a portrait frame, since rotation always swaps width/height).
# #
# # Current choice: keep the native landscape frame shape and accept that
# # content appears sideways, rather than force portrait. IMPORTANT: this
# # means the vision model (trained on upright imagery) will likely see
# # reduced hazard/vehicle detection accuracy, since objects won't match the
# # orientation it expects. If the camera can be physically rotated in its
# # housing later, that's the fix that avoids this tradeoff entirely.
# #   None                          -> no rotation (current choice — native landscape, sideways content)
# #   cv2.ROTATE_180                -> upside-down mount
# #   cv2.ROTATE_90_CLOCKWISE       -> corrects orientation but produces a portrait frame
# #   cv2.ROTATE_90_COUNTERCLOCKWISE
# FRAME_ROTATION = cv2.ROTATE_90_CLOCKWISE


# class ESP32Client:
#     """
#     Consumes the ESP32's MJPEG stream (/stream, port 81) over a single
#     persistent connection instead of issuing a fresh HTTP request per frame.

#     Sensors are polled independently on their own thread at ~3Hz — they
#     don't need to update at video framerate, and keeping them separate means
#     a sensor read never has to wait behind a video frame or vice versa.
#     """

#     SENSOR_POLL_INTERVAL_SEC = 0.3

#     def __init__(self):
#         self.latest_frame = None
#         self.latest_sensors = {}
#         self.lock = threading.Lock()
#         self.is_connected = False
#         self.is_running = False
#         self._stream_thread = None
#         self._sensors_thread = None

#     # ------------------------------------------------------------------ #
#     # Video: one persistent MJPEG connection
#     # ------------------------------------------------------------------ #
#     def _stream_loop(self):
#         while self.is_running:
#             try:
#                 resp = requests.get(STREAM_ENDPOINT, stream=True, timeout=5)
#                 if resp.status_code != 200:
#                     raise ConnectionError(f"/stream returned HTTP {resp.status_code}")

#                 if not self.is_connected:
#                     logger.info("ESP32 stream ESTABLISHED.")
#                     self.is_connected = True

#                 buffer = b""
#                 for chunk in resp.iter_content(chunk_size=2048):
#                     if not self.is_running:
#                         break

#                     buffer += chunk
#                     start = buffer.find(JPEG_SOI)
#                     end = buffer.find(JPEG_EOI)

#                     if start != -1 and end != -1 and end > start:
#                         jpg_bytes = buffer[start:end + 2]
#                         buffer = buffer[end + 2:]

#                         img_array = np.frombuffer(jpg_bytes, dtype=np.uint8)
#                         frame = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
#                         if frame is not None:
#                             if FRAME_ROTATION is not None:
#                                 frame = cv2.rotate(frame, FRAME_ROTATION)
#                             with self.lock:
#                                 self.latest_frame = frame

#                     # Guard against an unbounded buffer if we somehow never
#                     # find a valid EOI (corrupted stream) — drop and resync.
#                     elif len(buffer) > 200_000:
#                         buffer = b""

#             except Exception as e:
#                 if self.is_connected:
#                     logger.warning(f"ESP32 stream disconnected: {e}")
#                 self.is_connected = False
#                 # Brief pause before reconnecting so a dead endpoint doesn't
#                 # spin-loop reconnect attempts.
#                 time.sleep(1.0)

#     # ------------------------------------------------------------------ #
#     # Sensors: independent, slower poll — doesn't need video framerate
#     # ------------------------------------------------------------------ #
#     def _sensors_loop(self):
#         while self.is_running:
#             try:
#                 resp = requests.get(SENSORS_ENDPOINT, timeout=3)
#                 if resp.status_code == 200:
#                     with self.lock:
#                         self.latest_sensors = resp.json()
#             except Exception:
#                 pass  # video stream's own logging already reflects connectivity state
#             time.sleep(self.SENSOR_POLL_INTERVAL_SEC)

#     # ------------------------------------------------------------------ #
#     # Lifecycle
#     # ------------------------------------------------------------------ #
#     def start_stream(self):
#         if self.is_running:
#             logger.debug("start_stream() called but already running; ignoring.")
#             return
#         self.is_running = True
#         self._stream_thread = threading.Thread(target=self._stream_loop, daemon=True)
#         self._sensors_thread = threading.Thread(target=self._sensors_loop, daemon=True)
#         self._stream_thread.start()
#         self._sensors_thread.start()
#         logger.info("ESP32 client streaming threads active. (Waiting for connection...)")

#     def stop_stream(self):
#         if not self.is_running:
#             return
#         self.is_running = False
#         for t in (self._stream_thread, self._sensors_thread):
#             if t is not None:
#                 t.join(timeout=3.0)
#         self._stream_thread = None
#         self._sensors_thread = None
#         with self.lock:
#             self.latest_frame = None
#             self.latest_sensors = {}
#         self.is_connected = False
#         logger.info("ESP32 client streaming stopped.")

#     def get_data(self):
#         """Returns the latest frame and sensor data safely."""
#         with self.lock:
#             return (self.latest_frame.copy() if self.latest_frame is not None else None,
#                     self.latest_sensors.copy())








import json
import logging
import socket
import struct
import threading
import time

import cv2
import numpy as np

from config.settings import ESP32_HOST, ESP32_STREAM_PORT

logger = logging.getLogger("spirit.esp32")

# Wire protocol (must match the firmware): 'S' 'P' | type | length (uint32 LE) | payload
HEADER = struct.Struct("<2sBI")
MAGIC = b"SP"
PKT_JPEG = 1
PKT_SENSORS = 2
MAX_PAYLOAD = 400_000

FRAME_STALE_SEC = 2.0          # no new frame for this long => treat the camera as down
SERVICE_TYPE = "_spirit-cam._tcp.local."

# The camera may be mounted sideways. Change here, no reflashing needed.
#   None | cv2.ROTATE_180 | cv2.ROTATE_90_CLOCKWISE | cv2.ROTATE_90_COUNTERCLOCKWISE
FRAME_ROTATION = cv2.ROTATE_90_CLOCKWISE


def _recv_exact(sock: socket.socket, n: int) -> bytearray:
    buf = bytearray(n)
    view = memoryview(buf)
    got = 0
    while got < n:
        r = sock.recv_into(view[got:], n - got)
        if r == 0:
            raise ConnectionError("connection closed by ESP32")
        got += r
    return buf


def _discover_via_zeroconf(timeout: float = 3.0):
    """Find the camera by its advertised service. Works even if the device was renamed."""
    try:
        from zeroconf import ServiceBrowser, ServiceListener, Zeroconf
    except ImportError:
        return None

    found = {}

    class Listener(ServiceListener):
        def add_service(self, zc, type_, name):
            info = zc.get_service_info(type_, name, timeout=1500)
            if info and info.parsed_addresses():
                found["addr"] = (info.parsed_addresses()[0], info.port)

        def update_service(self, zc, type_, name):
            pass

        def remove_service(self, zc, type_, name):
            pass

    zc = Zeroconf()
    try:
        browser = ServiceBrowser(zc, SERVICE_TYPE, Listener())
        deadline = time.monotonic() + timeout
        while "addr" not in found and time.monotonic() < deadline:
            time.sleep(0.1)
        browser.cancel()
    finally:
        zc.close()
    return found.get("addr")





class ESP32Client:
    """
    Receives frames and sensor readings over one persistent TCP connection.
    The ESP32 pushes everything; the Pi never polls.
    """

    def __init__(self):
        self.latest_frame = None
        self.latest_sensors = {}
        self.lock = threading.Lock()
        self.is_connected = False
        self.is_running = False
        self._thread = None
        self._sock = None
        self._frame_time = 0.0
        self._last_addr = None
        self._last_err = None

    # ------------------------------------------------------------------ #
    def _resolve(self):
        """Name first, then service discovery, then the last known address."""
        try:
            infos = socket.getaddrinfo(ESP32_HOST, ESP32_STREAM_PORT,
                                       socket.AF_INET, socket.SOCK_STREAM)
            self._last_addr = infos[0][4]
            return self._last_addr
        except socket.gaierror:
            pass
        addr = _discover_via_zeroconf()
        if addr:
            if addr != self._last_addr:
                logger.info("Found ESP32-CAM via service discovery at %s:%s", *addr)
            self._last_addr = addr
            return addr
        return self._last_addr   # may be None

    def _handle_packet(self, ptype: int, payload: bytearray):
        if ptype == PKT_JPEG:
            frame = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR)
            if frame is None:
                return
            if FRAME_ROTATION is not None:
                frame = cv2.rotate(frame, FRAME_ROTATION)
            with self.lock:
                self.latest_frame = frame
                self._frame_time = time.monotonic()
        elif ptype == PKT_SENSORS:
            try:
                data = json.loads(bytes(payload))
            except ValueError:
                return
            with self.lock:
                self.latest_sensors = data

    def _stream_loop(self):
        while self.is_running:
            sock = None
            try:
                addr = self._resolve()
                if addr is None:
                    raise ConnectionError(
                        f"cannot find '{ESP32_HOST}' (is the ESP32 on the same network?)")
                sock = socket.create_connection(addr, timeout=5)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                sock.settimeout(5.0)    # no data for 5 s => treat as dead and reconnect
                self._sock = sock
                self.is_connected = True
                self._last_err = None
                logger.info("ESP32 stream ESTABLISHED (%s:%s).", *addr)

                while self.is_running:
                    magic, ptype, length = HEADER.unpack(_recv_exact(sock, HEADER.size))
                    if magic != MAGIC or length > MAX_PAYLOAD:
                        raise ConnectionError("protocol error (bad header)")
                    self._handle_packet(ptype, _recv_exact(sock, length))

            except Exception as e:
                if self.is_running:
                    msg = f"{type(e).__name__}: {e}"
                    if msg != self._last_err:     # log each distinct problem once
                        self._last_err = msg
                        verb = "disconnected" if self.is_connected else "connect failed"
                        logger.warning("ESP32 stream %s: %s", verb, msg)
            finally:
                self.is_connected = False
                self._sock = None
                if sock is not None:
                    try:
                        sock.close()
                    except OSError:
                        pass
                with self.lock:
                    self.latest_frame = None
                    self.latest_sensors = {}
                if self.is_running:
                    time.sleep(1.0)

     # ------------------------------------------------------------------ #
    def start_stream(self):
        if self.is_running:
            return
        self.is_running = True
        self._thread = threading.Thread(target=self._stream_loop, daemon=True, name="esp32-rx")
        self._thread.start()
        logger.info("ESP32 client started. Target: %s:%s", ESP32_HOST, ESP32_STREAM_PORT)

    def stop_stream(self):
        if not self.is_running:
            return
        self.is_running = False
        sock = self._sock
        if sock is not None:
            try:
                sock.close()    # unblocks recv immediately
            except OSError:
                pass
        if self._thread is not None:
            self._thread.join(timeout=3.0)
        self._thread = None
        with self.lock:
            self.latest_frame = None
            self.latest_sensors = {}
        self.is_connected = False
        logger.info("ESP32 client stopped.")

    def get_data(self):
        """Latest frame (or None if stale) and the latest sensor readings."""
        with self.lock:
            fresh = (self.latest_frame is not None
                     and time.monotonic() - self._frame_time < FRAME_STALE_SEC)
            frame = self.latest_frame.copy() if fresh else None
            return frame, dict(self.latest_sensors)