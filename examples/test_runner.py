# Test runner for the Enviro+ FeatherWing on a Feather HUZZAH (ESP8266, CircuitPython 3.1.2).
# Not copied to the board by 'huzzah.sh load'. It stores results in /test-results.bin and resets the board
# between tests, which wears out the ESP8266 flash filesystem. Run it deliberately with:
#   ./huzzah.sh run examples/test_runner.py
import microcontroller
from microcontroller import reset

def setup_display():
    import board, busio, digitalio, gc
    # Compiling st7735.py needs a lot of free heap, so collect garbage before importing it
    gc.collect()
    import st7735
    #region Screen setup
    """
    This region of code is used to setup the envirowing screen on a Feather HUZZAH (ESP8266, CircuitPython 3.x).
    That build has no displayio, so the panel is driven directly over busio.SPI by st7735.py.
    """

    # Wing header pins, as in Screen.py: 19 = GPIO2 (DC), 20 = GPIO16 (CS), 21 = GPIO0 (RST)
    tft_dc = digitalio.DigitalInOut(board.GPIO2) # define which pin the command line is on
    tft_cs = digitalio.DigitalInOut(board.GPIO16) # define which pin the chip select line is on
    tft_rst = digitalio.DigitalInOut(board.GPIO0)
    for pin in (tft_dc, tft_cs, tft_rst):
        pin.direction = digitalio.Direction.OUTPUT
        pin.value = True

    spi = busio.SPI(board.SCK, MOSI=board.MOSI) # define which spi bus the screen is on
    # CircuitPython 3 only allows writes while the bus is locked, so keep it locked for the whole run
    while not spi.try_lock():
        pass
    spi.configure(baudrate=1000000)

    # The panel object holds the DC/CS/RST pins, so keeping it alive keeps them driven
    display = st7735.ST7735(spi, tft_dc, tft_cs, tft_rst) # define the display (these values are specific to the envirowing's screen)

    #endregion Screen setup
    return display


class FileNVM:
    """Stands in for microcontroller.nvm on boards without NVM (e.g. ESP8266 CircuitPython)."""
    def __init__(self, path, size):
        self.path = path
        try:
            with open(path, "rb") as f:
                self.data = bytearray(f.read())
        except OSError:
            self.data = bytearray(size)

    def __getitem__(self, key):
        return self.data[key]

    def __setitem__(self, key, value):
        self.data[key] = value
        with open(self.path, "wb") as f:
            f.write(self.data)

tests = {
    "Screen":
        {"Test Run":False, "Passed":False},
    "I2C":
        {"Test Run":False, "Passed":False},
    "BME280_Temperature":
        {"Test Run":False, "Passed":False},
    "BME280_Humidity":
        {"Test Run":False, "Passed":False},
    "BME280_Pressure":
        {"Test Run":False, "Passed":False},
    "Light":
        {"Test Run":False, "Passed":False},
    "Prox":
        {"Test Run":False, "Passed":False},
    "Mic":
        {"Test Run":False, "Passed":False},
    "WiFi":
        {"Test Run":False, "Passed":False},
    "Finished": False,
    "Read": False
    }

nvm = microcontroller.nvm
if nvm is None:
    nvm = FileNVM("/test-results.bin", len(tests) * 2 - 1)

def restart_tests(num_test_bytes):
    nvm[0:num_test_bytes] = bytearray(num_test_bytes)
    reset()

def read_tests_from_nvm(bool_bytes, tests):
    keys = list(tests.keys())
    keys.sort()
    i = 0
    for test in keys:
        if test not in ("Finished", "Read"):
            tests[test]["Test Run"] = int(bool_bytes[i])
            i += 1
            tests[test]["Passed"] = int(bool_bytes[i])
            i += 1
        else:
            tests[test] = int(bool_bytes[i])
            i +=1
    return tests

def write_tests_to_nvm(tests, num_test_bytes):
    bits = [0]*num_test_bytes
    keys = list(tests.keys())
    keys.sort()
    i = 1
    for test in keys:
        if test not in ("Finished", "Read"):
            bits[i] = nvm[i] = int(tests[test]["Test Run"])
            i += 1
            bits[i] = nvm[i] = int(tests[test]["Passed"])
            i += 1
        else:
            bits[i] = nvm[i] = int(tests[test])
            i += 1
    nvm[0] = sum(bits) # checksum

def check_if_finished(tests):
    finished = True
    for test in tests.keys():
        if test not in ("Finished", "Read"):
            if not tests[test]["Test Run"]:
                    finished = False
    tests["Finished"] = finished
    return tests

def display_results(tests):
    display = setup_display()

    failed = []
    for test in tests.keys():
        if test not in ("Finished", "Read"):
            if not tests[test]["Passed"]:
                failed.append(test)

    # The driver can only fill the panel, so show the result as a colour: green for all passed, red otherwise
    if not failed:
        display.fill(0x07E0)
        print("All Tests Passed!")
    else:
        display.fill(0xF800)
        print("These tests failed:")
        print(", ".join(failed))
    tests["Read"] = True
    write_tests_to_nvm(tests, num_test_bytes)
    while True:
        pass
    #reset()

num_test_bytes = (len(tuple(tests.keys())) * 2 - 1) # -2, +1, because 2 tests don't have Run and Passed properties, but 1 byte is used for the checksum

nvm_checksum = nvm[0]

bool_bytes = nvm[1:num_test_bytes]

calc_checksum = sum(bool_bytes)

if nvm_checksum != calc_checksum:
    print(nvm_checksum, " != ", calc_checksum)
    print("Checksum Mismatch")
    restart_tests(num_test_bytes)
else:
    tests = read_tests_from_nvm(bool_bytes, tests)
    print("Read tests from NVM")
    tests = check_if_finished(tests)
    print("Checked if tests are finished")
    if tests["Read"]:
        print("Tests finished and read. Resetting...")
        restart_tests(num_test_bytes)
    elif tests["Finished"]:
        print("Tests finished. Displaying...")
        display_results(tests)
    else:
        for test in tests.keys():
            if test not in ("Finished", "Read"):
                if not tests[test]["Test Run"]:
                    print("Running", test)
                    importedtest = __import__(test)
                    getattr(importedtest, test)(tests, num_test_bytes, write_tests_to_nvm, reset)
