import os


# ESP32 Configuration
# Use the device's mDNS name (default) or an IP address.
ESP32_HOST = os.environ.get("ESP32_HOST", "spiritcam.local")
ESP32_STREAM_PORT = int(os.environ.get("ESP32_STREAM_PORT", "8765"))

# HTTP endpoints (diagnostics only)
CAPTURE_ENDPOINT = f"http://{ESP32_HOST}/capture"
SENSORS_ENDPOINT = f"http://{ESP32_HOST}/sensors"

# Model Paths
DETECTION_MODEL_PATH = "models/spirit_v1_seg.onnx"

# Safety Thresholds
TOF_CRITICAL_DISTANCE_MM = 800
TOF_WARNING_DISTANCE_MM = 1500
TEMP_WARNING_THRESHOLD = 38.0
HUMIDITY_FLOOD_THRESHOLD = 90.0

# Classes for COCO models
HAZARD_CLASSES = [
    "fire hydrant",
    "stop sign",
    "parking meter",
    "bench",
    "potted plant",
    "chair",
    "bottle",
]

VEHICLE_CLASSES = ["car", "bus", "truck", "motorcycle", "bicycle","person"]

# GPS (NEO-6M) — used on Raspberry Pi only
GPS_PORT = os.environ.get("GPS_PORT", "/dev/serial0")
GPS_BAUDRATE = int(os.environ.get("GPS_BAUDRATE", "9600"))

# Dummy GPS for Windows testing (change to your location)
DUMMY_GPS_LAT = 6.5244    # Lagos, Nigeria — change this!
DUMMY_GPS_LON = 3.3792
DUMMY_GPS_LOCATION_NAME = "Lagos, Nigeria"

# Google Maps
GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "")

# Terminal noise control
QUIET_TERMINAL = os.environ.get("QUIET_TERMINAL", "true").lower() != "false"