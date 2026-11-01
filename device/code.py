# HUZZAH build of the Enviro+ FeatherWing (ESP8266, CircuitPython 3.1.2).
# On boot this shows the current temperature, humidity, pressure and light level on the screen. The sensor test runner is in
# examples/test_runner.py and is not copied to the board, because it writes to flash on every boot.

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

    # The panel object holds the DC/CS/RST pins, so keeping it alive keeps them driven. GPIO0 becomes the backlight PWM after reset.
    display = st7735.ST7735(spi, tft_dc, tft_cs, tft_rst, backlight=board.GPIO0) # define the display (these values are specific to the envirowing's screen)

    #endregion Screen setup
    return display

# The 160x80 panel is split in two. The temperature is drawn large on the left, and the other readings are small on the right.
# Each cell is (x, y, scale, width, height) in panel coordinates. The cell is cleared before its text is drawn.
# The big number is 7 * scale pixels tall, so a scale of 3 gives 21 rows. The scale drops if the text is too wide for its cell.
# The number and its unit are 41 rows together (19 to 59), so they are centred on the 80-row panel.
# The request count sits under the LUX line, on the right.
CELLS = (
    (4, 19, 3, 76, 22),  # big temperature, left half
    (4, 46, 2, 40, 14),  # "C" or "F" under the big number
    (90, 9, 1, 66, 7),   # HUM, right half
    (90, 27, 1, 66, 7),  # PRES
    (90, 45, 1, 66, 7),  # LUX
    (90, 63, 1, 66, 7),  # request count, right half, below LUX
)
REQUEST_CELL = CELLS[5]
# The network view has its own layout: the address, the device name and the request count, one per row, in small text
NETWORK_CELLS = (
    (4, 9, 1, 152, 7),   # IP address
    (4, 27, 1, 152, 7),  # device name on the network
    (4, 45, 1, 152, 7),  # request count
)
# Characters that fit in a NETWORK_CELLS row at scale 1, since each glyph is 6 pixels wide and the last column is blank
NETWORK_CHARS = (152 + 1) // 6

def request_text(requests):
    return "REQ %d" % requests

def next_request_count(requests):
    # The count goes back to zero when the next value would be too wide for its cell
    requests += 1
    scale = REQUEST_CELL[2]
    if len(request_text(requests)) * 6 * scale - scale > REQUEST_CELL[3]:
        requests = 0
    return requests

def readout_cells(reading, requests, fahrenheit=False):
    # A failed read leaves the big number blank and shows the error on the right
    if reading is None:
        return ("", "", "SENSOR", "ERROR", "", request_text(requests))
    if fahrenheit:
        return ("%.1f" % (reading[0] * 9 / 5 + 32), "F", "HUM %.1f %%" % reading[1], "PRES %.1f" % reading[2], "LUX %.1f" % reading[3], request_text(requests))
    return ("%.1f" % reading[0], "C", "HUM %.1f %%" % reading[1], "PRES %.1f" % reading[2], "LUX %.1f" % reading[3], request_text(requests))

def network_texts(ip, name, requests):
    # The device name is shown in capitals, since the built-in font has no lower case
    return (
        ("IP %s" % ip)[:NETWORK_CHARS],
        ("NAME %s" % name.upper())[:NETWORK_CHARS],
        request_text(requests),
    )

def draw_cells(display, cells, texts, shown, clear):
    # Redraws only the cells whose text changed, so the panel isn't refilled on every update.
    # shown holds the text currently in each cell, and is updated as cells are drawn.
    # clear refills the whole panel first, for when the layout has changed.
    import st7735
    while not display.spi.try_lock():
        pass
    try:
        if clear:
            display.fill(0x0000)
        for i, (x, y, scale, w, h) in enumerate(cells):
            text = texts[i]
            if text != shown[i]:
                # draw_text only lights pixels, so clear the cell's old text first
                top = y + st7735.VISIBLE_ROW_OFFSET
                display.fill_rect(x, top, x + w - 1, top + h - 1, 0x0000)
                # Each glyph is 6 * scale wide, less the blank column after the last one
                while scale > 1 and len(text) * 6 * scale - scale > w:
                    scale -= 1
                display.draw_text(x, y, text, 0xFFFF, scale=scale)
                shown[i] = text
    finally:
        display.spi.unlock()

# The screen rotates through these views, each shown for IDLE_SECONDS: the readout in C, the readout in F, the network view,
# then the graph of the last 24 hours
VIEW_CELSIUS, VIEW_FAHRENHEIT, VIEW_NETWORK, VIEW_GRAPH = 0, 1, 2, 3
VIEW_COUNT = 4

def draw_view(view, requests):
    # Reads the sensor, which only touches the hardware once per READING_CACHE_SECONDS, and redraws what changed.
    # The readout views share CELLS, so switching between C and F only redraws the cells that changed.
    # Switching to or from the network view changes the layout, so the panel is cleared and every cell is drawn again.
    # Every reading is offered to the history, which stores one sample every SAMPLE_SECONDS whichever view is showing.
    global shown, shown_cells, shown_view, graph_samples
    reading = sensor.read()
    if reading is not None and history is not None:
        history.record(reading)
    if view == VIEW_GRAPH:
        # The graph is drawn in full, so it is only redrawn when the view is entered or a new sample has been stored
        if shown_view != VIEW_GRAPH or graph_samples != history.count:
            graph_draw.draw_graph(display, history)
            graph_samples = history.count
            # The next readout or network view finds the panel changed, so it clears and draws every cell
            shown_cells = None
        shown_view = view
        return
    if view == VIEW_NETWORK:
        cells = NETWORK_CELLS
        texts = network_texts(http_server.ip_address, http_server.device_name, requests)
    else:
        cells = CELLS
        texts = readout_cells(reading, requests, view == VIEW_FAHRENHEIT)
    shown_view = view
    clear = cells is not shown_cells
    if clear:
        shown = [None] * len(cells)
        shown_cells = cells
    draw_cells(display, cells, texts, shown, clear)

# The backlight follows the light level. Darkness gives MIN_BRIGHTNESS, and brightness rises on a log scale until
# LUX_FULL, above which it stays at full. Eyes judge light by ratio, so a log scale gives an even-looking ramp.
MIN_BRIGHTNESS = 0.05
LUX_FULL = 1000

def brightness_for_lux(lux):
    import math
    # Negative readings count as dark
    fraction = math.log(max(lux, 0) + 1) / math.log(LUX_FULL + 1)
    return MIN_BRIGHTNESS + (1 - MIN_BRIGHTNESS) * min(fraction, 1.0)

def update_brightness(display, sensor):
    # Uses the reading that draw_view just took. With no reading the sensor has failed, so the backlight goes to full and the error stays visible
    reading = sensor.reading
    if reading is None:
        display.set_brightness(1.0)
    else:
        display.set_brightness(brightness_for_lux(reading[3]))

# Runs on every boot, so the current reading is what the screen shows after a reset.
# The display is set up first, while the heap is still free.
display = setup_display()
# Compiling http_server.py needs a large block of free heap, so collect garbage first
import gc
gc.collect()
import http_server
# Keeps its I2C bus, so the HTTP server can use it without setting the bus up again
sensor = http_server.Sensor()
# The first read imports the sensor drivers, which needs a free heap too. A failed import leaves the driver broken until reset.
sensor.read()
# The graph needs its own heap, which the ESP8266 may not have left. If it can't be loaded, the graph view is skipped.
gc.collect()
try:
    import graph
    # Holds the last 24 hours of readings, from boot
    history = graph.History()
    import graph_draw
except MemoryError as e:
    print("Graph view off, not enough memory:", e)
    history = None
# setup_display left the bus locked. Clear the panel while it is still locked, then release it for draw_cells
display.fill(0x0000)
display.spi.unlock()
# What the panel shows now, so draw_view only redraws what changed. The first view drawn is the readout.
shown = [None] * len(CELLS)
shown_cells = CELLS
shown_view = VIEW_CELSIUS
graph_samples = 0
# Counts every connection the HTTP server accepts, from boot
request_count = 0
view = VIEW_CELSIUS
draw_view(view, request_count)
# Light the backlight only once the readout is drawn, so the panel never shows stale memory
update_brightness(display, sensor)

# Serve the readings as JSON over WiFi, and move to the next screen view every IDLE_SECONDS while no client is connecting.
# This runs until the board is reset, and does nothing without wifi_config.py.

def refresh_screen():
    # Moves to the next view, and keeps the backlight in step with the light level
    global view
    view = (view + 1) % VIEW_COUNT
    # Skips the graph when it couldn't be loaded at boot
    if view == VIEW_GRAPH and history is None:
        view = (view + 1) % VIEW_COUNT
    draw_view(view, request_count)
    update_brightness(display, sensor)
    # Each view builds new strings, so collect garbage here as well, not only after requests
    gc.collect()

def count_request():
    # Redraws the count as soon as a connection arrives, in whichever view is showing
    global request_count
    request_count = next_request_count(request_count)
    draw_view(view, request_count)

http_server.serve(sensor, refresh_screen, count_request)
