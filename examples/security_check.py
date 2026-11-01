# Checks the board's own security settings. Run with: ./huzzah.sh run examples/security_check.py
# Prints one line per check (PASS, WARN, FAIL or INFO), then a summary. It changes nothing on the board, and it
# never prints the WiFi password. The network tests are in tools/security_test.py, which runs on the computer.
import gc
import os
import network

counts = {"PASS": 0, "WARN": 0, "FAIL": 0, "INFO": 0}

def report(level, name, detail):
    counts[level] += 1
    print("%s %s: %s" % (level, name, detail))

files = os.listdir("/")

# The firmware's first boot can turn on an access point with a published password. http_server.serve() turns it off.
ap_if = network.WLAN(network.AP_IF)
if ap_if.active():
    try:
        essid = ap_if.config("essid")
    except Exception:
        essid = "?"
    report("FAIL", "access point", "on as %s. Anyone in range can join it and reach the server. Load the current http_server.py and reset" % essid)
else:
    report("PASS", "access point", "off")

# WebREPL gives a password-protected Python prompt over the network. Nothing here should start it.
started = []
for name in ("boot.py", "code.py", "main.py"):
    if name in files:
        with open(name) as f:
            for line in f:
                if line.strip().startswith("webrepl.start"):
                    started.append(name)
if started:
    report("FAIL", "webrepl", "started by %s" % ", ".join(started))
else:
    report("PASS", "webrepl", "not started at boot")
if "webrepl_cfg.py" in files:
    report("WARN", "webrepl", "webrepl_cfg.py (the WebREPL password) is on the board. Delete it if WebREPL isn't used")

# The network the server runs on. An open or WEP network lets anyone nearby join it and read the traffic.
AUTH_NAMES = {0: "open", 1: "WEP", 2: "WPA-PSK", 3: "WPA2-PSK", 4: "WPA/WPA2-PSK"}
if "wifi_config.py" not in files:
    report("INFO", "wifi", "no wifi_config.py, so the HTTP server doesn't start")
else:
    from wifi_config import SSID
    sta_if = network.WLAN(network.STA_IF)
    sta_if.active(True)
    auth = None
    for ap in sta_if.scan():
        # CircuitPython 3.x bytes have no decode(), so build the text from the byte values
        if "".join([chr(c) for c in ap[0]]) == SSID:
            auth = ap[4]
    if auth is None:
        report("WARN", "wifi", "%s is not in range, so its security can't be checked" % SSID)
    elif auth in (0, 1):
        report("FAIL", "wifi", "%s is %s. Anyone in range can join it and read the server's traffic" % (SSID, AUTH_NAMES[auth]))
    else:
        report("PASS", "wifi", "%s uses %s" % (SSID, AUTH_NAMES.get(auth, "authmode %d" % auth)))
    if sta_if.isconnected():
        report("INFO", "wifi", "connected as %s. Readings are served over plain HTTP on port 80" % sta_if.ifconfig()[0])
    del SSID

# The server's limits. An old http_server.py on the board has none of the fixes from the security review.
# They are read from the file's text, because importing it means compiling it, which runs out of memory here.
# This checks the file only: a board that hasn't been reset since ./huzzah.sh load still runs the old copy.
gc.collect()
SERVER_FILE = "http_server.py"
LIMITS = ("MAX_REQUEST_BYTES", "REQUEST_TIMEOUT", "REFUSED_TIMEOUT", "RATE_LIMIT_REQUESTS", "RATE_LIMIT_WINDOW",
          "MAX_TRACKED_CLIENTS")
hs = {}
if SERVER_FILE in files:
    with open(SERVER_FILE) as f:
        for line in f:
            parts = line.split("=", 1)
            name = parts[0].strip()
            # Only the module constants, which start at the beginning of the line
            if len(parts) == 2 and name in LIMITS and not line.startswith(" "):
                value = float(parts[1].split("#")[0])
                hs[name] = int(value) if value == int(value) else value
if SERVER_FILE not in files:
    report("FAIL", "http_server", "http_server.py is missing. Run ./huzzah.sh load")
elif "REFUSED_TIMEOUT" not in hs:
    report("FAIL", "http_server", "the board has an old http_server.py without the security fixes. Run ./huzzah.sh load")
else:
    problems = []
    if hs["MAX_REQUEST_BYTES"] > 1024:
        problems.append("MAX_REQUEST_BYTES %s > 1024" % hs["MAX_REQUEST_BYTES"])
    if hs["REQUEST_TIMEOUT"] > 5:
        problems.append("REQUEST_TIMEOUT %s > 5" % hs["REQUEST_TIMEOUT"])
    if hs["REFUSED_TIMEOUT"] > hs["REQUEST_TIMEOUT"]:
        problems.append("REFUSED_TIMEOUT is longer than REQUEST_TIMEOUT")
    if hs["MAX_TRACKED_CLIENTS"] > 32:
        problems.append("MAX_TRACKED_CLIENTS %s > 32" % hs["MAX_TRACKED_CLIENTS"])
    if problems:
        report("WARN", "http_server", "; ".join(problems))
    else:
        report("PASS", "http_server", "limits: %s byte requests, %ss to send one, %s requests a client every %ss" % (
            hs["MAX_REQUEST_BYTES"], hs["REQUEST_TIMEOUT"], hs["RATE_LIMIT_REQUESTS"], hs["RATE_LIMIT_WINDOW"]))

# Files that a deploy doesn't put there, such as a main.py that would run instead of code.py
EXPECTED = ("boot.py", "code.py", "http_server.py", "bme280_min.py", "st7735.py", "Screen.py", "I2C.py",
            "BME280_Humidity.py", "BME280_Pressure.py", "BME280_Temperature.py", "Light.py", "Prox.py", "Mic.py",
            "WiFi.py", "wifi_config.py", "lib", "test-results.bin", "webrepl_cfg.py")
extra = [name for name in files if name not in EXPECTED]
if extra:
    report("INFO", "files", "not part of a deploy: %s" % ", ".join(extra))

print("SUMMARY %d passed, %d warnings, %d failed" % (counts["PASS"], counts["WARN"], counts["FAIL"]))
