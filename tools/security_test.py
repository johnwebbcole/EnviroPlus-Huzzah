#!/usr/bin/env python3
"""Security tests for the board's HTTP server (device/http_server.py), run from the computer.

    python3 tools/security_test.py enviro          # the board, by its network name or IP address
    python3 tools/security_test.py --emulate       # device/http_server.py on this computer, with a fake sensor
    python3 tools/security_test.py enviro --full   # also wait out the rate limit window and check it recovers

Each check prints PASS, WARN, FAIL, SKIP or INFO. The exit status is 1 if any check failed, 2 if the server can't
be reached. The limits the checks expect (timeouts, rate limit) are read from device/http_server.py, so keep the
board in step with this checkout (./huzzah.sh load).

The server allows RATE_LIMIT_REQUESTS connections a minute from one address, and these checks use most of them,
then trip the limit on purpose. Running the tests again within a minute waits for the limit to reset first.
Needs only the Python standard library.
"""

import argparse
import importlib.util
import json
import os
import select
import socket
import sys
import threading
import time
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER_FILE = os.path.join(ROOT, "device", "http_server.py")
# Allowance for WiFi latency when timing how long the server holds a connection
MARGIN = 1.5
# Ports that should be closed on the board. WebREPL (8266) and telnet would give a Python prompt over the network.
PORTS = {21: "FTP", 22: "SSH", 23: "telnet", 443: "HTTPS", 8080: "HTTP alternate", 8266: "WebREPL"}
SHELL_PORTS = (23, 8266)
READING_KEYS = {"temperature_c", "humidity_percent", "pressure_hpa", "light_lux"}


class RateLimited(Exception):
    """The server answered 429 to a check that wasn't testing the rate limit."""


class Response:
    def __init__(self, raw, reset=False):
        self.raw = raw
        self.reset = reset
        self.status = None
        self.headers = {}
        self.body = b""
        head, _, self.body = raw.partition(b"\r\n\r\n")
        lines = head.split(b"\r\n")
        parts = lines[0].split(b" ", 2)
        if len(parts) >= 2 and parts[0].startswith(b"HTTP/") and parts[1].isdigit():
            self.status = int(parts[1])
        for line in lines[1:]:
            name, sep, value = line.partition(b":")
            if sep:
                self.headers[name.strip().lower().decode("latin-1")] = value.strip().decode("latin-1")

    def describe(self):
        if self.status is not None:
            return "HTTP %d" % self.status
        return "connection reset" if self.reset else "no response"


class Tester:
    def __init__(self, host, port, limits, timeout=10.0):
        self.host = host
        self.port = port
        self.limits = limits
        self.timeout = timeout
        # Connections made so far. Each one counts against the server's rate limit.
        self.connections = 0
        self.results = []

    def report(self, level, name, detail):
        self.results.append(level)
        print("%-4s %s: %s" % (level, name, detail), flush=True)

    def connect(self, timeout=None):
        self.connections += 1
        return socket.create_connection((self.host, self.port), timeout=timeout or self.timeout)

    def exchange(self, payload, expect_limit=False):
        """Sends payload, reads until the server closes the connection, and returns the Response."""
        with self.connect() as conn:
            reset = False
            chunks = []
            try:
                if payload:
                    conn.sendall(payload)
                while True:
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    chunks.append(chunk)
            except (ConnectionResetError, BrokenPipeError):
                reset = True
        response = Response(b"".join(chunks), reset)
        if response.status == 429 and not expect_limit:
            raise RateLimited()
        return response

    def get(self, path=b"/", extra=b""):
        return self.exchange(b"GET " + path + b" HTTP/1.1\r\nHost: " + self.host.encode() + b"\r\n" + extra + b"\r\n")

    def time_until_closed(self, give_up, drip=None):
        """Opens a connection and returns the seconds until the server closes it, or None if it is still open after
        give_up seconds. With drip, sends one byte of it every second, the way a slowloris client does."""
        with self.connect() as conn:
            start = time.monotonic()
            sent = 0
            while time.monotonic() - start < give_up:
                if drip and sent < len(drip):
                    try:
                        conn.sendall(drip[sent:sent + 1])
                    except (ConnectionResetError, BrokenPipeError):
                        return time.monotonic() - start
                    sent += 1
                readable, _, _ = select.select([conn], [], [], 1.0 if drip else 0.2)
                if readable:
                    try:
                        conn.recv(4096)
                    except (ConnectionResetError, OSError):
                        pass
                    return time.monotonic() - start
            return None


def check(tester, name, func):
    try:
        func(tester, name)
    except RateLimited:
        tester.report("SKIP", name, "rate limited before the check could run. Wait a minute and run the tests again")
    except OSError as e:
        tester.report("FAIL", name, "connection failed: %s" % e)


def check_ports(t, name):
    for port, service in sorted(PORTS.items()):
        try:
            socket.create_connection((t.host, port), timeout=1.5).close()
        except OSError:
            t.report("PASS", "port %d" % port, "%s closed" % service)
            continue
        level = "FAIL" if port in SHELL_PORTS else "WARN"
        t.report(level, "port %d" % port, "%s is open. Only port %d should be" % (service, t.port))


def wait_for_limit_reset(t):
    """If an earlier run left this address rate limited, waits for the window to pass. Refused connections don't
    count against the limit, so polling is free."""
    window = t.limits["RATE_LIMIT_WINDOW"]
    deadline = time.monotonic() + window + 5
    while True:
        response = t.exchange(b"GET / HTTP/1.1\r\n\r\n", expect_limit=True)
        if response.status != 429:
            return True
        if time.monotonic() > deadline:
            return False
        print("     rate limited from an earlier run; waiting for it to reset...", flush=True)
        time.sleep(10)


def check_baseline(t, name):
    r = t.get()
    if r.status != 200:
        return t.report("FAIL", name, "GET / gave %s, expected 200" % r.describe())
    problems = []
    try:
        data = json.loads(r.body)
        if set(data) != READING_KEYS:
            problems.append("JSON keys are %s" % sorted(data))
        elif not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in data.values()):
            problems.append("JSON values are not all numbers")
    except ValueError:
        problems.append("body is not valid JSON")
    if r.headers.get("content-type") != "application/json":
        problems.append("Content-Type is %r" % r.headers.get("content-type"))
    if r.headers.get("content-length") != str(len(r.body)):
        problems.append("Content-Length %r doesn't match the %d byte body" % (r.headers.get("content-length"), len(r.body)))
    if r.headers.get("cache-control") != "no-store":
        problems.append("no Cache-Control: no-store")
    if r.headers.get("x-content-type-options") != "nosniff":
        problems.append("no X-Content-Type-Options: nosniff")
    if r.headers.get("connection") != "close":
        problems.append("no Connection: close")
    if "server" in r.headers:
        problems.append("Server header gives away %r" % r.headers["server"])
    if "access-control-allow-origin" in r.headers:
        problems.append("Access-Control-Allow-Origin lets other web sites read the readings")
    if problems:
        t.report("FAIL", name, "; ".join(problems))
    else:
        t.report("PASS", name, "200 with only the four readings as JSON, and safe headers")


def check_methods(t, name):
    bad = []
    for request in (b"POST / HTTP/1.1\r\nContent-Length: 3\r\n\r\na=1",
                    b"TRACE / HTTP/1.1\r\nX-Probe: trace-marker\r\n\r\n"):
        r = t.exchange(request)
        method = request.split(b" ")[0].decode()
        if r.status != 405 or r.headers.get("allow") != "GET":
            bad.append("%s gave %s" % (method, r.describe()))
        if b"trace-marker" in r.raw:
            bad.append("%s echoed the request back" % method)
    if bad:
        t.report("FAIL", name, "; ".join(bad))
    else:
        t.report("PASS", name, "POST and TRACE refused with 405 and Allow: GET, nothing echoed")


def check_paths(t, name):
    bad = []
    for path in (b"/wifi_config.py", b"/../wifi_config.py", b"/%2e%2e/code.py?x=<script>path-marker</script>"):
        r = t.get(path)
        if r.status != 404:
            bad.append("%s gave %s" % (path.decode(), r.describe()))
        for secret in (b"PASSWORD", b"SSID", b"path-marker", b"import"):
            if secret in r.raw:
                bad.append("%s returned %r" % (path.decode(), secret.decode()))
    if bad:
        t.report("FAIL", name, "; ".join(bad))
    else:
        t.report("PASS", name, "file names and traversal paths get 404, and nothing from the request is echoed")


def check_malformed(t, name):
    bad = []
    for request in (b"\x16\x03\x01\x00\xff\x00garbage\r\n\r\n",
                    b"GET /\r\n\r\n",
                    b"GET  /  HTTP/1.1\r\n\r\n"):
        r = t.exchange(request)
        if r.status != 400:
            bad.append("%r gave %s" % (request[:20], r.describe()))
    if bad:
        t.report("FAIL", name, "; ".join(bad))
    else:
        t.report("PASS", name, "binary junk, HTTP/0.9 and badly spaced request lines get 400")


def check_oversized(t, name):
    r = t.get(extra=b"X-Pad: " + b"A" * 4000 + b"\r\n")
    # The server stops reading at MAX_REQUEST_BYTES, so the client may see a reset instead of the 431
    if r.status == 431 or (r.status is None and r.reset):
        t.report("PASS", name, "a 4 KB request was refused (%s)" % r.describe())
    else:
        t.report("FAIL", name, "a 4 KB request gave %s, expected 431" % r.describe())


def check_pipelining(t, name):
    r = t.exchange(b"GET / HTTP/1.1\r\nContent-Length: 5\r\n\r\nhelloGET /wifi_config.py HTTP/1.1\r\n\r\n")
    replies = r.raw.count(b"HTTP/1.1 ")
    if r.status == 200 and replies == 1:
        t.report("PASS", name, "a second request smuggled after the first was ignored, and the connection closed")
    elif replies <= 1 and r.reset:
        # The board's network stack resets a connection closed with unread data, and the computer may then drop
        # the reply it had buffered. Either way the smuggled request got no answer.
        t.report("PASS", name, "the smuggled second request got no answer (the connection was reset after %s)" % (
            "the first reply" if replies else "the first request"))
    else:
        t.report("FAIL", name, "got %d replies, the first %s" % (replies, r.describe()))


def check_host_header(t, name):
    r = t.get(extra=b"Host: attacker.example\r\n")
    if r.status == 200:
        t.report("WARN", name, "any Host header is accepted, so a web page using DNS rebinding could read the "
                               "readings through a visitor's browser. Accepted risk: the readings aren't secret")
    else:
        t.report("PASS", name, "a foreign Host header gave %s" % r.describe())


def check_idle(t, name):
    limit = t.limits["REQUEST_TIMEOUT"] + MARGIN
    held = t.time_until_closed(give_up=20)
    if held is None:
        t.report("FAIL", name, "a connection that sends nothing was still open after 20s")
    elif held > limit:
        t.report("FAIL", name, "a connection that sends nothing was held %.1fs (limit %.1fs)" % (held, limit))
    else:
        t.report("PASS", name, "a connection that sends nothing was dropped after %.1fs" % held)


def check_slowloris(t, name):
    timeout = t.limits["REQUEST_TIMEOUT"]
    # One byte a second stays inside a per-read timeout, so only a limit on the whole request stops it
    drip = b"GET / HTTP/1.1\r\nX-Slow: " + b"a" * 200
    other = {}

    def legit_client():
        time.sleep(1)
        start = time.monotonic()
        try:
            other["response"] = t.get()
        except RateLimited:
            other["response"] = None
        except OSError as e:
            other["error"] = e
        other["took"] = time.monotonic() - start

    thread = threading.Thread(target=legit_client)
    thread.start()
    held = t.time_until_closed(give_up=20, drip=drip)
    thread.join()
    if held is None:
        t.report("FAIL", name, "a client sending one byte a second still held the server after 20s")
    elif held > timeout + MARGIN:
        t.report("FAIL", name, "a client sending one byte a second held the server %.1fs (limit %.1fs)" % (held, timeout + MARGIN))
    else:
        t.report("PASS", name, "a client sending one byte a second was dropped after %.1fs" % held)
    if "error" in other:
        t.report("FAIL", name + " (other client)", "a normal request made meanwhile failed after %.1fs: %s" % (other["took"], other["error"]))
    elif other.get("response") is None or other["response"].status is None:
        t.report("FAIL", name + " (other client)", "a normal request made meanwhile got no answer")
    else:
        t.report("PASS", name + " (other client)", "a normal request made meanwhile was answered in %.1fs" % other["took"])


def check_rate_limit(t, name):
    allowed = t.limits["RATE_LIMIT_REQUESTS"]
    while t.connections <= allowed + 3:
        r = t.exchange(b"GET / HTTP/1.1\r\n\r\n", expect_limit=True)
        if r.status == 429:
            if t.connections <= allowed + 1:
                return t.report("PASS", name, "429 after %d connections (limit %d a client every %ds)" % (
                    t.connections - 1, allowed, t.limits["RATE_LIMIT_WINDOW"]))
            return t.report("FAIL", name, "429 only after %d connections, though the limit is %d. Connections that "
                                          "send nothing or time out may not be counted" % (t.connections - 1, allowed))
    t.report("FAIL", name, "no 429 after %d connections" % t.connections)


def check_refused_idle(t, name):
    limit = t.limits["REFUSED_TIMEOUT"] + MARGIN
    held = t.time_until_closed(give_up=20)
    if held is None or held > limit:
        t.report("FAIL", name, "a rate limited client that sends nothing was held %s (limit %.1fs)" % (
            "over 20s" if held is None else "%.1fs" % held, limit))
    else:
        t.report("PASS", name, "a rate limited client that sends nothing was dropped after %.1fs" % held)


def check_flood(t, name):
    socks = []

    def open_one():
        try:
            socks.append(socket.create_connection((t.host, t.port), timeout=3))
        except OSError:
            pass

    threads = [threading.Thread(target=open_one) for _ in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    time.sleep(2)
    for sock in socks:
        sock.close()
    start = time.monotonic()
    while time.monotonic() - start < 15:
        try:
            r = t.exchange(b"GET / HTTP/1.1\r\n\r\n", expect_limit=True)
            if r.status is not None:
                return t.report("PASS", name, "after 10 connections at once (%d accepted), the server answered "
                                              "again in %.1fs" % (len(socks), time.monotonic() - start))
        except OSError:
            pass
        time.sleep(1)
    t.report("FAIL", name, "the server didn't answer within 15s of 10 connections at once")


def check_recovery(t, name):
    window = t.limits["RATE_LIMIT_WINDOW"]
    print("     waiting %ds for the rate limit window to pass..." % (window + 2), flush=True)
    time.sleep(window + 2)
    r = t.exchange(b"GET / HTTP/1.1\r\n\r\n", expect_limit=True)
    if r.status == 200:
        t.report("PASS", name, "200 again after the rate limit window passed")
    else:
        t.report("FAIL", name, "%s after the rate limit window passed, expected 200" % r.describe())


def die(message):
    print("error: " + message, file=sys.stderr)
    sys.exit(2)


def load_server(path):
    spec = importlib.util.spec_from_file_location("http_server", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_limits(module):
    names = ("REQUEST_TIMEOUT", "RATE_LIMIT_REQUESTS", "RATE_LIMIT_WINDOW")
    limits = dict((n, getattr(module, n)) for n in names)
    # Versions before the security review have no separate timeout for refused clients
    limits["REFUSED_TIMEOUT"] = getattr(module, "REFUSED_TIMEOUT", 0.5)
    return limits


def start_emulator(path, verbose):
    """Runs http_server.serve() from path in a background thread on 127.0.0.1, with stub board, busio and sensor
    modules. Returns (port, module). This checks the server's logic, not the ESP8266's network stack."""
    sys.modules["board"] = types.SimpleNamespace(SCL="SCL", SDA="SDA")
    sys.modules["busio"] = types.SimpleNamespace(I2C=lambda scl, sda: object())

    class FakeBME280:
        def __init__(self, i2c):
            pass

        def read(self):
            return (21.53, 45.1, 1012.87)

    sys.modules["bme280_min"] = types.SimpleNamespace(BME280=FakeBME280)

    class FakeLTR559:
        def __init__(self, i2c_dev=None, **_):
            pass

        def get_lux(self, passive=False):
            return 7.16

    sys.modules["pimoroni_ltr559"] = types.SimpleNamespace(LTR559=FakeLTR559)
    sys.modules["pimoroni_circuitpython_adapter"] = types.SimpleNamespace(not_SMBus=lambda I2C=None: object())
    module = load_server(path)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    module.PORT = port
    module.connect_wifi = lambda: "127.0.0.1"
    ready = threading.Event()

    def log(*args):
        if args and str(args[0]).startswith("Serving"):
            ready.set()
        if verbose:
            print("     [server]", *args, file=sys.stderr)

    module.print = log

    # serve() binds 0.0.0.0. Hand it a socket module that binds loopback only, so the emulator isn't on the network.
    class LoopbackSocket(socket.socket):
        def bind(self, address):
            super().bind(("127.0.0.1", address[1]))

    shim = types.SimpleNamespace(socket=LoopbackSocket, AF_INET=socket.AF_INET, SOCK_STREAM=socket.SOCK_STREAM)
    real_socket = sys.modules["socket"]
    sys.modules["socket"] = shim
    try:
        threading.Thread(target=module.serve, daemon=True).start()
        if not ready.wait(5):
            die("the emulated server didn't start")
    finally:
        sys.modules["socket"] = real_socket
    return port, module


def main():
    parser = argparse.ArgumentParser(description="Security tests for the board's HTTP server.")
    parser.add_argument("host", nargs="?", help="the board's network name or IP address")
    parser.add_argument("--port", type=int, default=80)
    parser.add_argument("--emulate", nargs="?", const=SERVER_FILE, metavar="FILE",
                        help="test http_server.py (or FILE) running on this computer instead of a board")
    parser.add_argument("--full", action="store_true",
                        help="also wait for the rate limit window to pass and check the server answers 200 again")
    parser.add_argument("--verbose", action="store_true", help="show the emulated server's log")
    args = parser.parse_args()

    if args.emulate:
        port, module = start_emulator(args.emulate, args.verbose)
        tester = Tester("127.0.0.1", port, read_limits(module))
        print("Testing %s, emulated on 127.0.0.1:%d\n" % (args.emulate, port))
    elif args.host:
        tester = Tester(args.host, args.port, read_limits(load_server(SERVER_FILE)))
        print("Testing http://%s:%d/\n" % (args.host, args.port))
    else:
        parser.error("give the board's network name or IP address, or --emulate")

    try:
        socket.create_connection((tester.host, tester.port), timeout=5).close()
        tester.connections += 1
    except OSError as e:
        die("can't reach %s:%d (%s). Is the board on the network and wifi_config.py set? A board that was "
            "reset with ./huzzah.sh reset may need its reset button pressed" % (tester.host, tester.port, e))

    if not args.emulate:
        check(tester, "open ports", check_ports)
        tester.report("INFO", "transport", "plain HTTP: anyone on the network can read the readings. "
                                           "Accepted, as they aren't secret and the ESP8266 can't serve TLS")
    if not wait_for_limit_reset(tester):
        die("still rate limited after waiting a full window")
    checks = [
        ("baseline GET /", check_baseline),
        ("other methods", check_methods),
        ("other paths", check_paths),
        ("malformed requests", check_malformed),
        ("oversized request", check_oversized),
        ("request smuggling", check_pipelining),
        ("Host header", check_host_header),
        ("idle connection", check_idle),
        ("slowloris", check_slowloris),
        # These trip the rate limit, so they come last
        ("rate limit", check_rate_limit),
        ("rate limited idle connection", check_refused_idle),
        ("connection flood", check_flood),
    ]
    if args.full:
        checks.append(("rate limit recovery", check_recovery))
    for name, func in checks:
        check(tester, name, func)

    counts = dict((level, tester.results.count(level)) for level in ("PASS", "WARN", "FAIL", "SKIP"))
    print("\n%(PASS)d passed, %(WARN)d warnings, %(FAIL)d failed, %(SKIP)d skipped" % counts)
    sys.exit(1 if counts["FAIL"] else 0)


if __name__ == "__main__":
    main()
