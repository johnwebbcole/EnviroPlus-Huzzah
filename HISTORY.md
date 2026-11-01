# History

How this project was built, reconstructed from the Claude Code sessions that were run in this repository on 31 October and 1 November 2026. Times are UTC, taken from the session transcripts. Short confirmations ("1", "y", "yes") are left out.

The project started as a CLAUDE.md for the repo, then grew from a single sensor readout on the Enviro+ FeatherWing screen into a board that shows its readings on the screen, serves them over HTTP, and rotates through several views. Each step came from a prompt, a flash to the board, and a report back of what the screen or the web server showed. Many steps were fixes for problems seen on the hardware.

## Timeline

### 1. Repository documentation (31 Oct, 17:40)

- Asked Claude to analyze the codebase and write a CLAUDE.md for future Claude Code sessions: build and test commands, and the architecture that takes more than one file to understand.

### 2. First readout on the screen (31 Oct, 17:42 to 19:20)

- Asked for the main file to start by showing the current temperature and humidity.
- Redirected the output from the serial console to the Enviro+ screen.
- Reported that the screen said `SENSOR ERROR`, and that the text was cut off. Sent a photo of the screen and a paste of the board's boot log (`Adafruit CircuitPython 3.1.2 ... ESP8266`).
- Fixed the layout until temperature and humidity both showed. The temperature line first drew only one pixel row, so the first full row was the one that showed.
- Added pressure, then confirmed the layout looked right.

### 3. Wi-Fi setup (31 Oct, 19:21 to 19:34)

- Asked how to turn on Wi-Fi on the HUZZAH ESP8266.
- Asked for `huzzah.sh wifi scan`: pick an access point from a list and be prompted for its password. The first run failed with `error: scan failed`.
- Asked for the board's network name to be prompted too, with `enviro` as the default.

### 4. HTTP server (31 Oct, 19:43 to 20:44)

- Scanned the open ports on `enviro.localdomain` to see what the board exposed.
- Asked for a small HTTP server that returns only temperature, humidity and pressure as JSON, and that resists abusive requests.
- Asked for a security check of that server, test tools to check it, and a README with how to run them and the status of the review. Once the board was updated, asked for the tests to be run on it.

### 5. Light sensor and backlight (31 Oct, 20:50 to 21:57)

- Asked whether the light sensor worked, then added lux to the screen and to the JSON. The font had to shrink to fit. One run was interrupted and resumed.
- Asked whether screen brightness could be controlled. The backlight pin was not documented in the code, so it was found on the board. Brightness was then set in steps, and the change was tested on the board.
- Asked how often the screen updated: the light value was not changing. Added a refresh loop, then confirmed the value changed.

### 6. Readout layout (31 Oct, 22:09 to 22:43)

- Asked for a large temperature on the left half of the screen, with the smaller readings on the right.
- Set the refresh to every 2 seconds, alternated temperature between C and F, and centred the large temperature vertically.
- Made the brightness follow ambient light: the dimmest setting in the dark, brighter as the light level rises.
- Added a request counter that counts connections to the web server. It is shown on the left, then moved under the lux line on the right. When the number would not fit, it resets to zero.
- Slowed the refresh to every 5 seconds and added a third view with the IP address, the device name and the request count. The views did not rotate at first, and the screen kept showing the last output.
- Tried `curl http://enviro.localdomain`, which failed to resolve.

### 7. Reset problem (31 Oct, 22:51 to 22:56)

- Reported that running `./huzzah.sh reset` while the board was running stopped the screen drawing and the web server, and that `curl` got "connection reset by peer". Asked whether the reset command crashed the board.

### 8. Graph view (31 Oct, 23:00 to 1 Nov, 00:57)

- Asked for a fourth view that graphs the last 24 hours of temperature (red), humidity (blue), pressure (green) and lux (yellow), with each line's max and min in small text in its colour.
- Reported that the graph only drew a line at the far right, not across the screen.

### 9. Rotation timing and repository cleanup (1 Nov, 21:47 to 22:36)

- Set the time between view changes to 15 seconds.
- Asked what a file named `-` in the repository was for.
- Asked for the relevant skills to be copied from the WarpCad repository into this one.
- Checked the repository for publishing to GitHub. Asked which licenses are compatible with the Adafruit sources it was derived from, and chose MIT.

### 10. This document (1 Nov, 22:44)

- Asked for this history to be written from the prompt history.

## How the work was done

- **Hardware loop.** Most changes were tested on a board. The user flashed the code, and reported what the screen or `curl` showed. Several prompts are bug reports with a photo or pasted output, not feature requests.
- **Derived code.** The repo is based on the Adafruit and Pimoroni Enviro+ and FeatherWing code, adapted for the ESP8266 running CircuitPython 3.1.2. The adapted libraries are noted in CLAUDE.md.
- **Sessions.** The work was spread over about 20 Claude Code sessions in VS Code, most of them short. Each session covered one change or one bug.
- **Gaps.** No prompts for this project were recorded between 1 Nov 00:57 and 21:47 UTC.
