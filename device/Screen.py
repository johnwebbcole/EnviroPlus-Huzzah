def Screen(tests, num_test_bytes, write_tests_to_nvm, reset):
    try:
        import board, busio, digitalio
        import st7735
        #region Screen setup
        """
        This region of code is used to setup the envirowing screen on a Feather HUZZAH (ESP8266, CircuitPython 3.x).
        That build has no displayio, so the panel is driven directly over busio.SPI by st7735.py.
        """

        # Wing header pins, read off the HUZZAH silkscreen (same as examples/huzzah/screen_test.py):
        #   19 = GPIO2 (DC), 20 = GPIO16 (CS), 21 = GPIO0 (RST)
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
        display = st7735.ST7735(spi, tft_dc, tft_cs, tft_rst, backlight=board.GPIO0) # define the display (these values are specific to the envirowing's screen)

        #endregion Screen setup

        # The driver can't draw text, so the check fills the panel with bright green, as screen_test.py does
        display.fill(0x07E0)
        display.set_brightness(1.0)

        if display:
            tests["Screen"]["Passed"] = True
            print("Passed with", display)
        else:
            tests["Screen"]["Passed"] = False
            print("Failed")
        return display
    except Exception as e:
        tests["Screen"]["Passed"] = False
        print("Failed with ", e)
    finally:
        tests["Screen"]["Test Run"] = True
        write_tests_to_nvm(tests, num_test_bytes)
        reset()

# Run directly with huzzah.sh run: test-all-low-mem normally calls Screen() with its own tests/NVM/reset arguments,
# so stub those out here and keep the script alive so the display keeps showing its last frame.
if __name__ == "__main__":
    tests = {"Screen": {"Test Run": False, "Passed": False}}
    display = Screen(tests, 0, lambda t, n: None, lambda: None)
    while True:
        pass
