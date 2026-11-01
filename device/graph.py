# Graph of the last 24 hours of temperature, humidity, pressure and light, for the screen on a Feather HUZZAH
# (ESP8266, CircuitPython 3.x). The readings are kept in RAM, so a reset starts the history again.
# Copied to the board as graph.py. code.py calls History.record() with each reading and draw_steps() to draw the graph a step at a time.

import time

# A sample is taken at most this often, so SAMPLES of them cover the last 24 hours. 10 minutes leaves enough heap
# for the server; 5 minutes did not fit beside it on the ESP8266, so the store is half the size of 5 minutes.
SAMPLE_SECONDS = 600
SAMPLES = 24 * 60 * 60 // SAMPLE_SECONDS

# The four series, in the order readings are stored: temperature, humidity, pressure, light.
# Each entry is (colour in RGB565, scale, offset, label format). A value is stored as (value - offset) * scale in two
# bytes, so it covers offset to offset + 65535 / scale. The label format shows the max and min values on the screen.
SERIES = (
    (0xF800, 100, -40, "%.1fC"),  # temperature, red
    (0x001F, 100, 0, "%.1f%%"),   # humidity, blue
    (0x07E0, 10, 300, "%.0f"),    # pressure, green
    (0xFFE0, 1, 0, "%.0f"),       # light, yellow
)
# Left edge of each series' max and min labels in the top and bottom rows. Each label has 40 pixels, enough for 6 characters.
LABEL_X = (0, 40, 80, 120)
LABEL_TOP_ROW = 0
LABEL_BOTTOM_ROW = 73
LABEL_CHARS = 6
# The plot sits between the two label rows. Rows are panel rows, with 0 at the top visible row.
PLOT_TOP = 9
PLOT_BOTTOM = 70
PLOT_RIGHT = 159
PANEL_ROWS = 80

def encode(value, scale, offset):
    n = int((value - offset) * scale + 0.5)
    return min(max(n, 0), 65535)

def decode(n, scale, offset):
    return n / scale + offset

def row_for(n, lo, hi):
    # Places n between lo and hi, the lowest and highest stored values of its series, so each line uses the full plot height
    if hi == lo:
        return (PLOT_TOP + PLOT_BOTTOM) // 2
    return PLOT_BOTTOM - (n - lo) * (PLOT_BOTTOM - PLOT_TOP) // (hi - lo)

def column_for(age, count):
    # Newest sample (age 0) is on the right edge, and the oldest recorded sample, count - 1 samples back, is on the left edge.
    # Until a full 24 hours is recorded the samples spread across the whole width, rather than bunching at the right.
    span = max(count - 1, 1)
    return PLOT_RIGHT - age * PLOT_RIGHT // span

class History:
    def __init__(self):
        # Two bytes per series per sample, held as a ring. next is the slot the next sample goes in.
        self.data = bytearray(SAMPLES * len(SERIES) * 2)
        self.next = 0
        self.count = 0
        self.taken_at = None

    def record(self, reading):
        # Stores reading (temperature, humidity, pressure, light) if SAMPLE_SECONDS have passed since the last sample.
        # Returns True when a sample was stored. monotonic time doesn't go backwards, so no guard is needed here.
        if self.taken_at is not None and time.monotonic() - self.taken_at < SAMPLE_SECONDS:
            return False
        self.taken_at = time.monotonic()
        base = self.next * len(SERIES) * 2
        for j, (colour, scale, offset, label) in enumerate(SERIES):
            n = encode(reading[j], scale, offset)
            self.data[base + 2 * j] = n >> 8
            self.data[base + 2 * j + 1] = n & 0xFF
        self.next = (self.next + 1) % SAMPLES
        if self.count < SAMPLES:
            self.count += 1
        return True

    def value(self, age, j):
        # Stored value of series j, age samples ago (0 is the newest)
        slot = (self.next - 1 - age) % SAMPLES
        i = (slot * len(SERIES) + j) * 2
        return (self.data[i] << 8) | self.data[i + 1]
