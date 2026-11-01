# Minimal ST7735 driver for the Enviro+ FeatherWing on a Feather HUZZAH (ESP8266, CircuitPython 3.x).
# This build has no displayio, so the panel is driven directly over busio.SPI.
# Copy it to the board with: huzzah.sh put st7735.py st7735.py
import time

MADCTL_ROTATE_270 = 0x60

# Register sequence for the 160x80 ST7735 panel, followed by the wing's rotation and invert.
INIT = (
    (0x11, None, 0.5),                       # SLPOUT
    (0xB1, (0x01, 0x2C, 0x2D), 0),           # FRMCTR1
    (0xB2, (0x01, 0x2C, 0x2D), 0),           # FRMCTR2
    (0xB3, (0x01, 0x2C, 0x2D, 0x01, 0x2C, 0x2D), 0),  # FRMCTR3
    (0xB4, (0x07,), 0),                      # INVCTR
    (0xC0, (0xA2, 0x02, 0x84), 0),           # PWCTR1
    (0xC1, (0xC5,), 0),                      # PWCTR2
    (0xC2, (0x0A, 0x00), 0),                 # PWCTR3
    (0xC3, (0x8A, 0x2A), 0),                 # PWCTR4
    (0xC4, (0x8A, 0xEE), 0),                 # PWCTR5
    (0xC5, (0x0E,), 0),                      # VMCTR1
    (0x36, (MADCTL_ROTATE_270,), 0),         # MADCTL
    (0x3A, (0x05,), 0),                      # COLMOD: 16-bit colour
    (0x21, None, 0),                         # INVON (invert=True in the displayio version)
    (0x13, None, 0),                         # NORON
    (0x29, None, 0.1),                       # DISPON
)

# The whole controller memory in this rotation is 162 columns by 132 rows. The visible 160x80
# panel sits inside it, so filling all of it leaves no unwritten memory showing on the glass.
MEM_W = 162
MEM_H = 132

# The first visible panel row sits this many rows into controller memory. Rows above it are off the glass.
VISIBLE_ROW_OFFSET = 26

# PWM frequency for the backlight. CircuitPython 3.x allows only one PWM frequency, and 200 Hz gives several visible levels.
BACKLIGHT_HZ = 200

class ST7735:
    def __init__(self, spi, dc, cs, rst, backlight=None):
        # spi must already be locked by the caller, as CircuitPython 3 requires for writes
        self.spi = spi
        self.dc = dc
        self.cs = cs
        self.rst = rst
        self.backlight = None

        self.rst.value = False
        time.sleep(0.02)
        self.rst.value = True
        time.sleep(0.15)
        self.command(0x01)  # SWRESET
        time.sleep(0.15)

        for cmd, data, delay in INIT:
            self.command(cmd, data)
            if delay:
                time.sleep(delay)

        # On the HUZZAH the backlight is on the same pin as RST (GPIO0). Reset and init are done, so release the pin
        # and drive it as PWM. It starts off, so the panel stays dark until set_brightness is called.
        if backlight is not None:
            import pulseio
            self.rst.deinit()
            self.backlight = pulseio.PWMOut(backlight, frequency=BACKLIGHT_HZ, duty_cycle=0)

    def set_brightness(self, fraction):
        # fraction runs from 0.0 (off) to 1.0 (full)
        if self.backlight is not None:
            self.backlight.duty_cycle = int(65535 * fraction)

    def command(self, cmd, data=None):
        self.cs.value = False
        self.dc.value = False
        self.spi.write(bytes([cmd]))
        if data:
            self.dc.value = True
            self.spi.write(bytes(data))
        self.cs.value = True

    def fill_rect(self, x0, y0, x1, y1, color):
        # x1 and y1 are inclusive; color is RGB565
        width = x1 - x0 + 1
        height = y1 - y0 + 1
        self.command(0x2A, (0x00, x0, 0x00, x1))  # CASET
        self.command(0x2B, (0x00, y0, 0x00, y1))  # RASET
        # Built in place, since bytes([...] * width) first makes a list four times this size, which fails on a fragmented heap
        row = bytearray(2 * width)
        for i in range(0, 2 * width, 2):
            row[i] = color >> 8
            row[i + 1] = color & 0xFF
        self.cs.value = False
        self.dc.value = False
        self.spi.write(bytes([0x2C]))             # RAMWR
        self.dc.value = True
        for _ in range(height):
            self.spi.write(row)
        self.cs.value = True

    def fill(self, color):
        self.fill_rect(0, 0, MEM_W - 1, MEM_H - 1, color)

    def draw_text(self, x, y, text, color, scale=1):
        # x and y are panel coordinates, with y = 0 at the top visible row.
        # Each character is a 5x7 pixel glyph with one blank column after it. Lit pixels are drawn as
        # small rectangles, which is slow but needs no framebuffer; the ESP8266 has too little RAM for one.
        top = y + VISIBLE_ROW_OFFSET
        for ch in text:
            index = FONT_CHARS.find(ch)
            glyph = (index if index >= 0 else 0) * 5
            for row in range(7):
                for col in range(5):
                    pixel = row * 5 + col
                    if (FONT_BITS[glyph + pixel // 8] >> (pixel % 8)) & 1:
                        px = x + col * scale
                        py = top + row * scale
                        self.fill_rect(px, py, px + scale - 1, py + scale - 1, color)
            x += 6 * scale

# 5x7 font. FONT_CHARS lists the characters in the order of the glyphs in FONT_BITS. Each glyph is 35 pixels,
# row by row, packed into five bytes: pixel n is bit n %% 8 of byte n // 8 of the glyph. Text is drawn in upper case.
# The glyphs as pixel art, '#' lit, one row of 35 characters per glyph:
#   ' ': ...................................
#   '.': ..........................##...##..
#   '-': ...............#####...............
#   '%': ##..###.#....#...#...#....#.###..##
#   ':': ......##...##........##...##.......
#   '0': .###.#...##..###.#.###..##...#.###.
#   '1': ..#...##....#....#....#....#...###.
#   '2': .###.#...#....#...#...#...#...#####
#   '3': #####...#...#.....#.....##...#.###.
#   '4': ...#...##..#.#.#..#.#####...#....#.
#   '5': ######....####.....#....##...#.###.
#   '6': ..##..#...#....####.#...##...#.###.
#   '7': #####....#...#...#...#....#....#...
#   '8': .###.#...##...#.###.#...##...#.###.
#   '9': .###.#...##...#.####....#...#..##..
#   'A': .###.#...##...#######...##...##...#
#   'B': ####.#...##...#####.#...##...#####.
#   'C': .###.#...##....#....#....#...#.###.
#   'D': ####.#...##...##...##...##...#####.
#   'E': ######....#....####.#....#....#####
#   'F': ######....#....####.#....#....#....
#   'G': .###.#...##....#.####...##...#.####
#   'H': #...##...##...#######...##...##...#
#   'I': .###...#....#....#....#....#...###.
#   'J': ..###...#....#....#....#.#..#..##..
#   'K': #...##..#.#.#..##...#.#..#..#.#...#
#   'L': #....#....#....#....#....#....#####
#   'M': #...###.###.#.##.#.##...##...##...#
#   'N': #...###..##.#.##..###...##...##...#
#   'O': .###.#...##...##...##...##...#.###.
#   'P': ####.#...##...#####.#....#....#....
#   'Q': .###.#...##...##...##.#.##..#..##.#
#   'R': ####.#...##...#####.#.#..#..#.#...#
#   'S': .#####....#.....###.....#....#####.
#   'T': #####..#....#....#....#....#....#..
#   'U': #...##...##...##...##...##...#.###.
#   'V': #...##...##...##...##...#.#.#...#..
#   'W': #...##...##...##.#.##.#.##.#.#.#.#.
#   'X': #...##...#.#.#...#...#.#.#...##...#
#   'Y': #...##...#.#.#...#....#....#....#..
#   'Z': #####....#...#...#...#...#....#####
FONT_CHARS = " .-%:0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
FONT_BITS = (
    b"\x00\x00\x00\x00\x00\x00\x00\x00\x8c\x01\x00\x80\x0f\x00\x00\x73"
    b"\x21\x22\x74\x06\xc0\x18\x60\x0c\x00\x2e\xe6\x3a\xa3\x03\xc4\x10"
    b"\x42\x88\x03\x2e\x42\x44\xc4\x07\x1f\x11\x04\xa3\x03\x88\xa9\xf4"
    b"\x11\x02\x3f\x3c\x08\xa3\x03\x4c\x84\x17\xa3\x03\x1f\x22\x22\x84"
    b"\x00\x2e\x46\x17\xa3\x03\x2e\x46\x0f\x91\x01\x2e\xc6\x1f\x63\x04"
    b"\x2f\xc6\x17\xe3\x03\x2e\x86\x10\xa2\x03\x2f\xc6\x18\xe3\x03\x3f"
    b"\x84\x17\xc2\x07\x3f\x84\x17\x42\x00\x2e\x86\x1e\xa3\x07\x31\xc6"
    b"\x1f\x63\x04\x8e\x10\x42\x88\x03\x1c\x21\x84\x92\x01\x31\x95\x51"
    b"\x52\x04\x21\x84\x10\xc2\x07\x71\xd7\x1a\x63\x04\x71\xd6\x1c\x63"
    b"\x04\x2e\xc6\x18\xa3\x03\x2f\xc6\x17\x42\x00\x2e\xc6\x58\x93\x05"
    b"\x2f\xc6\x57\x52\x04\x3e\x04\x07\xe1\x03\x9f\x10\x42\x08\x01\x31"
    b"\xc6\x18\xa3\x03\x31\xc6\x18\x15\x01\x31\xc6\x5a\xab\x02\x31\x2a"
    b"\xa2\x62\x04\x31\x2a\x42\x08\x01\x1f\x22\x22\xc2\x07"
)
