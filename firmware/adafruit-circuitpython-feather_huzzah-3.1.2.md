# Feather HUZZAH (ESP8266): esptool in a Python virtual environment

## Set up the environment (Linux/macOS)

```bash
# Create the virtual environment
python3 -m venv ~/esptool-env

# Activate it
source ~/esptool-env/bin/activate

# Upgrade pip (optional but recommended)
pip3 install --upgrade pip

# Install esptool
pip3 install esptool

# Verify it works
esptool.py version
```

On newer esptool releases (v5+), the command is `esptool` instead of `esptool.py`. Both usually work, but if one isn't found, try the other.

On Windows, the activation step is `esptool-env\Scripts\activate` instead.

## Using it with the Feather HUZZAH

```bash
# Find the serial port first
ls /dev/ttyUSB*        # Linux
ls /dev/cu.usbserial*  # macOS

# Check that the chip responds
esptool.py --port /dev/ttyUSB0 chip_id

# Erase flash (recommended before flashing new firmware)
esptool.py --port /dev/ttyUSB0 erase_flash

# Flash firmware (example: CircuitPython 3.1.2 build for the Feather HUZZAH)
esptool.py --port /dev/ttyUSB0 --baud 460800 write_flash --flash_size=detect 0 firmware.bin
```

## Notes

- When you're done, leave the environment with `deactivate`. Next session, run `source ~/esptool-env/bin/activate` again.
- On Linux, if you get "permission denied" on the serial port, add yourself to the dialout group: `sudo usermod -a -G dialout $USER`, then log out and back in.
- The HUZZAH's USB-serial chip is a CP2104, so you may need its driver on macOS or Windows. Linux includes it in the kernel.
- If the board doesn't enter bootloader mode automatically, hold the **GPIO0** button, tap **Reset**, then release GPIO0. The red LED should glow dimly, meaning it's ready to flash.
- If `python3 -m venv` fails on Debian/Ubuntu, install it with `sudo apt install python3-venv`.
