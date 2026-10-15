import os
import socket
import sys

import requests

try:
    from dotenv import load_dotenv
    load_dotenv(override=True)
except ImportError:
    pass

host = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("ESP32_HOST", "esp32cam.local")
print(f"Testing host: {host}\n")

# 1. Name resolution
try:
    ip = socket.gethostbyname(host)
    print(f"[OK]   DNS: {host} -> {ip}")
except Exception as e:
    print(f"[FAIL] DNS: cannot resolve '{host}' ({e})")
    print("       -> Use the ESP32's IP address in ESP32_HOST instead of a .local name.")
    sys.exit(1)

# 2. Raw TCP on the two ports
for port, label in ((80, "web server"), (81, "stream server")):
    try:
        with socket.create_connection((ip, port), timeout=3):
            print(f"[OK]   TCP port {port} ({label}) reachable")
    except Exception as e:
        print(f"[FAIL] TCP port {port} ({label}): {e}")
        if port == 80:
            print("       -> Wrong IP, ESP32 off the network, or router client isolation.")
        else:
            print("       -> Port 81 busy (another viewer connected?) or firmware lacks the stream server.")

# 3. Single snapshot
try:
    r = requests.get(f"http://{host}/capture", timeout=5)
    ctype = r.headers.get("Content-Type", "")
    print(f"[{'OK' if r.ok and 'jpeg' in ctype else 'WARN'}]   /capture -> HTTP {r.status_code}, "
          f"{ctype}, {len(r.content)} bytes")
except Exception as e:
    print(f"[FAIL] /capture: {e}")

# 4. Sensors endpoint
try:
    r = requests.get(f"http://{host}/sensors", timeout=3)
    print(f"[{'OK' if r.ok else 'WARN'}]   /sensors -> HTTP {r.status_code}: {r.text[:120]}")
except Exception as e:
    print(f"[WARN] /sensors: {e} (video can still work without it)")

# 5. MJPEG stream
try:
    r = requests.get(f"http://{host}:81/stream", stream=True, timeout=5)
    data = b""
    for chunk in r.iter_content(chunk_size=2048):
        data += chunk
        if len(data) > 20000:
            break
    has_jpeg = b"\xff\xd8" in data
    print(f"[{'OK' if has_jpeg else 'FAIL'}]   /stream -> HTTP {r.status_code}, "
          f"{len(data)} bytes, JPEG frame found: {has_jpeg}")
    r.close()
except Exception as e:
    print(f"[FAIL] /stream: {e}")