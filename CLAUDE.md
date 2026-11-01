# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Enviro+ FeatherWing sensor tests for an Adafruit Feather HUZZAH (ESP8266) running CircuitPython 3.1.2. The main EnviroPlus-FeatherWing repo dropped ESP8266 support, so this repo carries its own patched copies. Code under `device/` is copied to the board's CIRCUITPY drive; nothing here runs on the host except the shell scripts and `tools/security_test.py`.

## Commands

Host-side tooling lives in `esptool-env/` (a Python venv, created by `setup.sh`, pinned in `requirements.txt`).

```bash
./setup.sh                      # create/update esptool-env (safe to re-run)
./setup.sh --recreate           # rebuild the venv from scratch
PYTHON=python3.14 ./setup.sh    # pick the interpreter

./huzzah.sh port                # show the serial port (/dev/cu.usbserial*)
./huzzah.sh ls [-l] [dir]       # list files on the board
./huzzah.sh put LOCAL [REMOTE]  # upload one file (creates it first; does not create parent dirs)
./huzzah.sh load                # copy every .py under device/ (incl. lib/) to the board, creating folders
./huzzah.sh get REMOTE [LOCAL]
./huzzah.sh mkdir|rmdir|rm REMOTE
./huzzah.sh run FILE.py         # run a host file on the board without copying it
./huzzah.sh reset
./huzzah.sh flash [FIRMWARE.bin]  # erases the board, then flashes CircuitPython (confirms first)
./huzzah.sh erase               # erases all flash (confirms first)
./huzzah.sh wifi set SSID PASS [NAME]  # save WiFi credentials and the board's network name (default "enviro") to wifi_config.py on the board
./huzzah.sh wifi clear          # delete wifi_config.py from the board
./huzzah.sh wifi scan           # pick an access point in range, prompt for its password and the name, save both (uses examples/wifi_scan.py)
```

There is no build step. The only automated tests are the HTTP server's security tests:

```bash
python3 tools/security_test.py --emulate   # device/http_server.py on the host with stub hardware (about 10 s)
python3 tools/security_test.py enviro      # the board, by name or IP
./huzzah.sh run examples/security_check.py # board settings: access point, WebREPL, WiFi auth, server version
```

Run `--emulate` after any change to `http_server.py`. The tests read the limits from `device/http_server.py`, and their order matters, because they spend the server's per-client rate limit and trip it last. Everything else is verified on hardware. Syntax can be checked on the host with `python3 -m py_compile <file>`, but that uses the host Python, not CircuitPython 3.x, so it won't catch the restrictions listed below.

Deploying to the board: `./huzzah.sh load` copies every `.py` under `device/` (including `lib/`) to the board root. After copying, reset the board. `AMPY_PORT` selects a port when more than one is attached.

## Architecture

**Boot readout (`device/code.py`).** `code.py` runs on every boot. It sets up the screen, reads the BME280 with `bme280_min.py` and the LTR559 light sensor, and draws the temperature large on the left half (with a `C` under it) and `HUM`, `PRES` and `LUX` small on the right, or `SENSOR ERROR` on the right if either read fails. Under `LUX` on the right, `REQ n` counts the connections the HTTP server has accepted since boot. The count goes back to 0 when the next value would be too wide for its cell (9999999 is the last value shown). The cells are defined by `CELLS` in `code.py`. The screen rotates through four views every 15 seconds (`IDLE_SECONDS` in `http_server.py`): the readout in C, the readout in F, a network view with `IP`, `NAME` (the device name from `wifi_config.py`) and `REQ n`, laid out by `NETWORK_CELLS`, then a graph of the last 24 hours, drawn by `draw_graph` in `device/graph_draw.py` from the history in `device/graph.py`. The graph draws temperature in red, humidity in blue, pressure in green and light in yellow, each scaled to its own range, with each line's highest value in small text along the top and its lowest along the bottom. `code.py` records a sample every `SAMPLE_SECONDS` (600) from the readings it draws, so 144 samples cover the 24 hours. Until 24 hours are recorded, the samples are spread across the whole width, so the graph always spans the panel. Five-minute samples (288) did not fit in the heap beside the server. They are held in RAM, so a reset starts the history again. If `graph.py` or `graph_draw.py` can't be loaded for lack of memory, the graph view is skipped and the rest of the rotation still runs. Drawing the graph blocks the server for about 1.5 s on each entry to the graph view. Drawing in steps from the idle callback doesn't work: any accept timeout under 5 s made connections reset on this firmware. The `display.spi.unlock()` after the readout is required, because the screen setup leaves the SPI bus locked. Then it calls `http_server.serve()`, which joins WiFi from `wifi_config.py` and serves the readings as JSON until reset. Without `wifi_config.py`, it returns at once.

**HTTP server (`device/http_server.py`).** `GET /` returns `{"temperature_c", "humidity_percent", "pressure_hpa", "light_lux"}`. Other paths get 404, other methods 405, and bad or oversized requests 400 or 431. Every accepted connection counts against `RATE_LIMIT_REQUESTS` before anything is read. Clients over the limit get 429 after at most `REFUSED_TIMEOUT`, and the sensor is read at most once per `READING_CACHE_SECONDS`. One client is served at a time, with a backlog of 1. `REQUEST_TIMEOUT` covers the whole request, not each read (a per-read timeout let slowloris clients hold the server), and the reply has its own limit. `connect_wifi()` turns off the board's own access point first. Elapsed times go through `seconds_since()`, which treats a clock going backwards as a long interval. The security review is in README.md. The limits are module constants. Unverified on hardware: the `socket` calls (`bind`, `settimeout`, `accept`) follow the CircuitPython 3.x API as remembered, so check them on a board first.

**Test runner (`examples/test_runner.py`).** This is no longer copied to the board or run at boot. It is a state machine that runs each sensor check in its own boot, which is why it isn't on the board: it writes `/test-results.bin` on every boot, and those writes broke the board's flash filesystem repeatedly. Run it on purpose with `./huzzah.sh run examples/test_runner.py`, and expect the board to reset between tests. Its design:

1. Test results live in a `tests` dict: each sensor name maps to `{"Test Run": bool, "Passed": bool}`, plus `"Finished"` and `"Read"` flags. Keys are sorted before serialization, so the NVM layout depends on the key set.
2. The state is persisted in `microcontroller.nvm`. The ESP8266 build has no NVM, so `FileNVM` emulates it with `/test-results.bin`. Byte 0 is a checksum of the remaining bytes.
3. On each boot, the runner loads the state. If the checksum fails, it clears NVM and reboots. If `Read` is set, it clears NVM and reboots, which starts a new cycle. If `Finished` is set, it draws the result. Otherwise it imports the module named after the first test with `Test Run` false and calls `getattr(module, name)(tests, num_test_bytes, write_tests_to_nvm, reset)`.
4. Each test module (`Screen.py`, `I2C.py`, `BME280_*.py`, `Light.py`, `Prox.py`, `Mic.py`, `WiFi.py`) follows the same contract: it sets its own `Passed`, sets `Test Run` in a `finally`, writes NVM, and calls `reset()`. Each test therefore runs in its own boot. Keep this pattern when adding a test, or the state machine will loop or skip it.
5. When every test has run, `display_results` fills the 160x80 ST7735 panel green (all passed) or red (any failed), then spins forever. It sets `Read` so the next boot wipes state and starts over.

To add a sensor test: create `device/NAME.py` defining `NAME(tests, num_test_bytes, write_tests_to_nvm, reset)`, follow the same try/finally contract, and add `"NAME": {"Test Run": False, "Passed": False}` to the `tests` dict in `examples/test_runner.py`. The module and function name must match the key, because the runner uses `__import__(test)`.

**Each test module is also runnable on its own.** `Screen.py` has an `if __name__ == "__main__":` block that stubs out the runner arguments. Use `./huzzah.sh run device/Screen.py` to exercise one test without touching the NVM state. Other sensor modules don't have this block.

**Hardware pin map.** The Enviro+ wing sits on the HUZZAH header. DC is GPIO2, CS is GPIO16, and RST is GPIO0 for the ST7735. The backlight is also GPIO0 (wing pin 21, as in upstream EnviroPlus-FeatherWing), so after reset `st7735.py` releases the pin and drives it as 200 Hz PWM. Pass `backlight=board.GPIO0` to `ST7735` and call `set_brightness` with a value from 0.0 (off) to 1.0 (full). Only one PWM frequency is allowed, and a soft reset can keep the last one. The sensors use I2C at `board.SCL`/`board.SDA`, with the BME280 at address 0x76. The microphone uses `board.ADC`, the HUZZAH's only ADC. The gas sensor (MiCS6814, which needs three ADC channels) and PMS5003 are unsupported on this board. Their modules are deliberately absent.

**Bundled libraries (`device/lib/`).** These are patched forks, not the upstream packages:
- `adafruit_bme280` and `adafruit_bus_device` have function annotations and f-strings converted to `%` formatting, because CircuitPython 3.x can't parse either. `spi_device.py` is omitted.
- `pimoroni_ltr559` is a minimal driver. The full package doesn't fit in RAM.
- `pimoroni_circuitpython_adapter` is installed under that name because `Light.py` and `Prox.py` import it that way.
- `st7735.py` is a hand-written SPI driver. It can fill the panel and draw text with a built-in 5x7 font (upper case only, `draw_text`), because CircuitPython 3.x has no `displayio`.

**Heap.** The ESP8266 has about 26 KB free at boot, and the boot code only just fits. A list the size of a screen row (`bytes([...] * width)`) and a list of the reply bytes (`bytes([ord(c) for c in ...])`) each take four times the memory of the bytes they hold, so both are built in a `bytearray` instead. The font is packed to 5 bytes per glyph (`FONT_BITS` in `st7735.py`). Check any new allocation against the boot heap on the board, not just on the host.

**CircuitPython 3.x restrictions** apply to all code under `device/`. Avoid f-strings, type annotations, `displayio`, `board.I2C`, `time.monotonic_ns`, and `microcontroller.nvm` (it's absent, so use the `FileNVM` fallback pattern). SPI writes must happen while the bus is locked (`spi.try_lock()`).

**Status.** The patched libraries and the test code have been checked for syntax only. They have not been run on hardware. The HTTP server and its security tests have been run on a board (see README.md, Security status). Treat any change as unverified until it has been flashed and observed on a board.

## Conventions

- Keep `device/` files flat in the board root, except `lib/`. `huzzah.sh put` does not create directories, so add `mkdir` steps when a new library package is added.
- `examples/` is for standalone scripts run with `huzzah.sh run`. `examples/screen_test.py` and `examples/bme280_simple.py` are not part of the runner.
