# Screen test for the Enviro+ FeatherWing on a Feather HUZZAH (ESP8266, CircuitPython 3.x).
# Ports the Screen check from test-all-low-mem to this board: the panel passes if it can be set up
# and filled. A pass fills the screen green; a failure is printed, since the panel can't be drawn to.
# Needs st7735.py on the board first: huzzah.sh put examples/huzzah/st7735.py st7735.py
import board, busio, digitalio, time
import st7735

GREEN = 0x07E0

# Wing header pins, read off the HUZZAH silkscreen:
#   19 = GPIO2 (DC), 20 = GPIO16 (CS), 21 = GPIO0 (RST)
DC = digitalio.DigitalInOut(board.GPIO2)
CS = digitalio.DigitalInOut(board.GPIO16)
RST = digitalio.DigitalInOut(board.GPIO0)
for pin in (DC, CS, RST):
    pin.direction = digitalio.Direction.OUTPUT
    pin.value = True

spi = busio.SPI(board.SCK, MOSI=board.MOSI)
# CircuitPython 3 only allows writes while the bus is locked, so keep it locked for the whole run
while not spi.try_lock():
    pass
spi.configure(baudrate=1000000)

try:
    panel = st7735.ST7735(spi, DC, CS, RST)
    panel.fill(GREEN)
    print("Screen passed")
except Exception as e:
    print("Screen failed with", e)

# Keep the script running so DC/CS/RST stay driven; when it exits the pins are released and float,
# which lets the panel's controller pick up random commands.
while True:
    time.sleep(1)
