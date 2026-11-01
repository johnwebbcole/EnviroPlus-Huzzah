#region WiFi test
# Connects to the access point named in wifi_config.py. Write that file with './huzzah.sh wifi set SSID PASSWORD'.
# The test passes if the board gets an IP address before WIFI_TIMEOUT seconds run out.
WIFI_TIMEOUT = 20 # seconds to wait for the access point to hand out an address

def WiFi(tests, num_test_bytes, write_tests_to_nvm, reset):
    try:
        import network, time
        from wifi_config import SSID, PASSWORD
        # Older wifi_config.py files have no HOSTNAME, so fall back to the default name
        try:
            from wifi_config import HOSTNAME
        except ImportError:
            HOSTNAME = "enviro"
        sta_if = network.WLAN(network.STA_IF)
        sta_if.active(True)
        # The name the board shows as on the network (its DHCP hostname), set before it asks for an address
        sta_if.config(dhcp_hostname=HOSTNAME)
        sta_if.connect(SSID, PASSWORD)
        start = time.monotonic()
        while not sta_if.isconnected():
            if time.monotonic() - start > WIFI_TIMEOUT:
                raise OSError("no connection to %s after %d seconds" % (SSID, WIFI_TIMEOUT))
            time.sleep(0.5)
        tests["WiFi"]["Passed"] = True
        print("Passed with", sta_if.ifconfig()[0])
    except Exception as e:
        tests["WiFi"]["Passed"] = False
        print("Failed with ", e)
    finally:
        tests["WiFi"]["Test Run"] = True
        write_tests_to_nvm(tests, num_test_bytes)
        reset()
#endregion WiFi test
