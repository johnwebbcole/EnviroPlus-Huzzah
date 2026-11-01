# HTTP server that returns the current temperature, humidity, pressure and light level as JSON, on a Feather HUZZAH
# (ESP8266, CircuitPython 3.x). It answers one client at a time.
#
#   GET /  ->  {"temperature_c": 21.53, "humidity_percent": 45.10, "pressure_hpa": 1012.87, "light_lux": 7.16}
#
# Other paths get 404, other methods 405, oversized requests 431, malformed requests 400 and clients that ask too
# often 429. A reading is reused for READING_CACHE_SECONDS, so a flood of requests doesn't keep hitting the sensor.
# The security review and the tests that check these limits are in README.md and tools/security_test.py.
# Copied to the board as http_server.py. code.py calls serve() after the boot readout.

import time
import gc

PORT = 80
# Largest request line and headers the server will read. Anything bigger is refused with 431.
MAX_REQUEST_BYTES = 512
# Seconds a client has to send its whole request before the connection is dropped. Sending the reply has the same limit.
REQUEST_TIMEOUT = 3
# Seconds a client that is over its rate limit has to send its request before it gets 429 or is dropped.
REFUSED_TIMEOUT = 0.5
# A new reading is taken at most this often, however many requests arrive.
READING_CACHE_SECONDS = 2
# Each client IP may make RATE_LIMIT_REQUESTS requests in each RATE_LIMIT_WINDOW seconds.
RATE_LIMIT_REQUESTS = 20
RATE_LIMIT_WINDOW = 60
# Clients tracked at once. While the table is full, requests from new clients get 429, so memory stays bounded.
MAX_TRACKED_CLIENTS = 16
WIFI_TIMEOUT = 20 # seconds to wait for the access point to hand out an address
# While no client is connecting, serve() calls its on_idle callback this often (code.py uses it to move to the next screen view)
IDLE_SECONDS = 15

REASONS = {
    200: "OK",
    400: "Bad Request",
    404: "Not Found",
    405: "Method Not Allowed",
    429: "Too Many Requests",
    431: "Request Header Fields Too Large",
    503: "Service Unavailable",
}

def to_bytes(text):
    # CircuitPython 3.x bytes have no encode(), so build the bytes from the character codes.
    # Filled in place: a list of the codes would take four times the memory, which fails on a fragmented heap.
    out = bytearray(len(text))
    for i in range(len(text)):
        out[i] = ord(text[i])
    return bytes(out)

def seconds_since(start):
    # time.monotonic() shouldn't go backwards. If it ever does, treat start as long ago, so nothing waits forever.
    passed = time.monotonic() - start
    return passed if passed >= 0 else 1e9

def send_all(conn, data):
    start = time.monotonic()
    while data:
        # The limit covers the whole reply, so a client that reads one byte at a time can't hold the server
        left = REQUEST_TIMEOUT - seconds_since(start)
        if left <= 0:
            raise OSError("reply timed out")
        conn.settimeout(left)
        sent = conn.send(data)
        # Some builds return None from send(), which means everything went out
        if sent is None:
            sent = len(data)
        data = data[sent:]

def send_reply(conn, status, text):
    body = to_bytes(text)
    head = "HTTP/1.1 %d %s\r\n" % (status, REASONS[status])
    head += "Content-Type: application/json\r\nContent-Length: %d\r\nCache-Control: no-store\r\nX-Content-Type-Options: nosniff\r\nConnection: close\r\n" % len(body)
    if status == 405:
        head += "Allow: GET\r\n"
    send_all(conn, to_bytes(head + "\r\n") + body)

def read_request_line(conn, timeout):
    # Returns (request line, None), or (None, status) to refuse the request, or (None, None) if the client sent nothing.
    # timeout covers the whole request, not each read, so a client sending a byte at a time can't hold the server.
    start = time.monotonic()
    data = b""
    while b"\r\n\r\n" not in data:
        if len(data) >= MAX_REQUEST_BYTES:
            return None, 431
        left = timeout - seconds_since(start)
        if left <= 0:
            raise OSError("request timed out")
        conn.settimeout(left)
        chunk = conn.recv(64)
        if not chunk:
            return None, None
        data += chunk
    return data.split(b"\r\n", 1)[0], None

class RateLimiter:
    def __init__(self):
        # ip -> [start of the current window, requests made in it]
        self.clients = {}

    def allow(self, ip):
        now = time.monotonic()
        # Forget clients whose window has passed, so the table only holds recent ones
        for other in list(self.clients):
            if seconds_since(self.clients[other][0]) >= RATE_LIMIT_WINDOW:
                del self.clients[other]
        if ip not in self.clients:
            if len(self.clients) >= MAX_TRACKED_CLIENTS:
                return False
            self.clients[ip] = [now, 0]
        entry = self.clients[ip]
        if entry[1] >= RATE_LIMIT_REQUESTS:
            return False
        entry[1] += 1
        return True

class Sensor:
    def __init__(self):
        self.i2c = None
        self.bme = None
        self.light = None
        self.reading = None
        self.read_at = None

    def read(self):
        # Returns (temperature in C, humidity in %, pressure in hPa, light in lux), or None if a sensor can't be read
        now = time.monotonic()
        if self.read_at is None or seconds_since(self.read_at) >= READING_CACHE_SECONDS:
            # Remember the attempt even when it fails, so a broken sensor isn't retried on every request
            self.read_at = now
            try:
                if self.bme is None:
                    import board, busio
                    from bme280_min import BME280
                    from pimoroni_circuitpython_adapter import not_SMBus
                    from pimoroni_ltr559 import LTR559
                    if self.i2c is None:
                        self.i2c = busio.I2C(board.SCL, board.SDA)
                    self.bme = BME280(self.i2c)
                    self.light = LTR559(i2c_dev=not_SMBus(I2C=self.i2c))
                    # The first light measurement takes about 100 ms after the sensor starts
                    time.sleep(0.2)
                temperature, humidity, pressure = self.bme.read()
                self.reading = (temperature, humidity, pressure, self.light.get_lux())
            except Exception as e:
                print("Could not read the sensors:", e)
                self.bme = None
                self.light = None
                self.reading = None
        return self.reading

def respond(conn, line, sensor):
    parts = line.split(b" ")
    if len(parts) != 3 or parts[2][:5] != b"HTTP/":
        return send_reply(conn, 400, '{"error": "%s"}' % REASONS[400])
    if parts[0] != b"GET":
        return send_reply(conn, 405, '{"error": "%s"}' % REASONS[405])
    if parts[1] != b"/":
        return send_reply(conn, 404, '{"error": "%s"}' % REASONS[404])
    reading = sensor.read()
    if reading is None:
        return send_reply(conn, 503, '{"error": "%s"}' % REASONS[503])
    send_reply(conn, 200, '{"temperature_c": %.2f, "humidity_percent": %.2f, "pressure_hpa": %.2f, "light_lux": %.2f}\n' % reading)

def handle(conn, ip, sensor, limiter):
    # The connection counts against the client's limit before anything is read, so connections that send nothing
    # are limited too. A client over its limit gets less time to send its request, so it can't hold the server.
    allowed = limiter.allow(ip)
    line, status = read_request_line(conn, REQUEST_TIMEOUT if allowed else REFUSED_TIMEOUT)
    if line is None and status is None:
        return
    if not allowed:
        status = 429
    if status is not None:
        return send_reply(conn, status, '{"error": "%s"}' % REASONS[status])
    respond(conn, line, sensor)

# Set by connect_wifi(), so code.py can show the address and device name on the screen
ip_address = None
device_name = None

def connect_wifi():
    global ip_address, device_name
    import network
    # The firmware's first boot may leave the board's own access point on (MicroPython-xxxxxx, with a published
    # password). Turn it off before anything else, so the server is only reachable from the network the board joins.
    # Checking first avoids a flash write on every boot.
    ap_if = network.WLAN(network.AP_IF)
    if ap_if.active():
        ap_if.active(False)
    from wifi_config import SSID, PASSWORD
    # Older wifi_config.py files have no HOSTNAME, so fall back to the default name
    try:
        from wifi_config import HOSTNAME
    except ImportError:
        HOSTNAME = "enviro"
    sta_if = network.WLAN(network.STA_IF)
    sta_if.active(True)
    sta_if.config(dhcp_hostname=HOSTNAME)
    sta_if.connect(SSID, PASSWORD)
    start = time.monotonic()
    while not sta_if.isconnected():
        if time.monotonic() - start > WIFI_TIMEOUT:
            raise OSError("no connection to %s after %d seconds" % (SSID, WIFI_TIMEOUT))
        time.sleep(0.5)
    ip_address = sta_if.ifconfig()[0]
    device_name = HOSTNAME
    return ip_address

def serve(sensor=None, on_idle=None, on_request=None):
    # Connects to WiFi, then answers requests until the board is reset. Does nothing if WiFi isn't set up.
    # code.py passes in the Sensor it read at boot. Its I2C bus is set up before the heap fragments, which otherwise fails.
    # on_idle, if given, runs about every IDLE_SECONDS while no client is connecting.
    # on_request, if given, runs once for each connection accepted, before the request is read.
    import socket
    try:
        ip = connect_wifi()
    except Exception as e:
        print("HTTP server not started:", e)
        return
    gc.collect()
    if sensor is None:
        sensor = Sensor()
    limiter = RateLimiter()
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("0.0.0.0", PORT))
    # A backlog of 1 means at most one client waits while another is being served
    listener.listen(1)
    if on_idle is not None:
        # accept() gives up after IDLE_SECONDS, so the loop gets a chance to run on_idle
        listener.settimeout(IDLE_SECONDS)
    print("Serving readings at http://%s:%d/" % (ip, PORT))
    while True:
        try:
            conn, addr = listener.accept()
        except Exception as e:
            if on_idle is None:
                print("Accept failed:", e)
            else:
                # Without a separate timeout error, any accept failure ends up here, so a fault is retried each second
                try:
                    on_idle()
                except Exception as idle_error:
                    print("Idle task failed:", idle_error)
            continue
        if on_request is not None:
            try:
                on_request()
            except Exception as request_error:
                print("Request count failed:", request_error)
        try:
            handle(conn, addr[0], sensor, limiter)
        except Exception as e:
            print("Request failed:", e)
        finally:
            conn.close()
        gc.collect()
