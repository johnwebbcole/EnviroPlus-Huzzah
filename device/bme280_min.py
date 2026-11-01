# Minimal BME280 driver for temperature, humidity and pressure on a Feather HUZZAH (ESP8266, CircuitPython 3.x).
# The full adafruit_bme280 library doesn't fit in this build's heap, so this reads only the registers
# needed for these three values.
# Copy it to the board with: huzzah.sh put device/bme280_min.py bme280_min.py

ADDRESS = 0x76
CHIP_ID = 0x60

def _signed16(lo, hi):
    value = lo | (hi << 8)
    if value & 0x8000:
        value -= 0x10000
    return value

class BME280:
    def __init__(self, i2c, address=ADDRESS):
        self.i2c = i2c
        self.address = address

        chip_id = self._read(0xD0, 1)[0]
        if chip_id != CHIP_ID:
            raise OSError("not a BME280, chip id 0x%02x" % chip_id)

        # Temperature calibration: dig_T1 is unsigned, dig_T2 and dig_T3 are signed
        t = self._read(0x88, 6)
        self.dig_T1 = t[0] | (t[1] << 8)
        self.dig_T2 = _signed16(t[2], t[3])
        self.dig_T3 = _signed16(t[4], t[5])

        # Pressure calibration: dig_P1 is unsigned, dig_P2 to dig_P9 are signed
        p = self._read(0x8E, 18)
        self.dig_P1 = p[0] | (p[1] << 8)
        self.dig_P2 = _signed16(p[2], p[3])
        self.dig_P3 = _signed16(p[4], p[5])
        self.dig_P4 = _signed16(p[6], p[7])
        self.dig_P5 = _signed16(p[8], p[9])
        self.dig_P6 = _signed16(p[10], p[11])
        self.dig_P7 = _signed16(p[12], p[13])
        self.dig_P8 = _signed16(p[14], p[15])
        self.dig_P9 = _signed16(p[16], p[17])

        # Humidity calibration. The 12-bit values share the byte at 0xE5.
        self.dig_H1 = self._read(0xA1, 1)[0]
        h = self._read(0xE1, 7)
        self.dig_H2 = _signed16(h[0], h[1])
        self.dig_H3 = h[2]
        self.dig_H4 = (h[3] << 4) | (h[4] & 0x0F)
        if self.dig_H4 & 0x800:
            self.dig_H4 -= 0x1000
        self.dig_H5 = (h[5] << 4) | (h[4] >> 4)
        if self.dig_H5 & 0x800:
            self.dig_H5 -= 0x1000
        self.dig_H6 = h[6] - 0x100 if h[6] & 0x80 else h[6]

        # Humidity oversampling must be written before ctrl_meas. Temperature and pressure x1, normal mode.
        self._write(0xF2, 0x01)
        self._write(0xF4, 0x27)

    def read(self):
        # Returns (temperature in degrees C, relative humidity in %, pressure in hPa),
        # from one burst read of the data registers
        d = self._read(0xF7, 8)
        adc_P = (d[0] << 12) | (d[1] << 4) | (d[2] >> 4)
        adc_T = (d[3] << 12) | (d[4] << 4) | (d[5] >> 4)
        adc_H = (d[6] << 8) | d[7]

        var1 = (adc_T / 16384.0 - self.dig_T1 / 1024.0) * self.dig_T2
        diff = adc_T / 131072.0 - self.dig_T1 / 8192.0
        var2 = diff * diff * self.dig_T3
        t_fine = var1 + var2
        temperature = t_fine / 5120.0

        h = t_fine - 76800.0
        h = (adc_H - (self.dig_H4 * 64.0 + self.dig_H5 / 16384.0 * h)) * (
            self.dig_H2 / 65536.0 * (1.0 + self.dig_H6 / 67108864.0 * h * (1.0 + self.dig_H3 / 67108864.0 * h)))
        h = h * (1.0 - self.dig_H1 * h / 524288.0)
        if h > 100.0:
            h = 100.0
        elif h < 0.0:
            h = 0.0

        # Pressure, from the datasheet's floating-point compensation. Result is in Pa, converted to hPa
        var1 = t_fine / 2.0 - 64000.0
        var2 = var1 * var1 * self.dig_P6 / 32768.0
        var2 = var2 + var1 * self.dig_P5 * 2.0
        var2 = var2 / 4.0 + self.dig_P4 * 65536.0
        var1 = (self.dig_P3 * var1 * var1 / 524288.0 + self.dig_P2 * var1) / 524288.0
        var1 = (1.0 + var1 / 32768.0) * self.dig_P1
        pressure = 0.0
        if var1 != 0.0:
            p = 1048576.0 - adc_P
            p = (p - var2 / 4096.0) * 6250.0 / var1
            var1 = self.dig_P9 * p * p / 2147483648.0
            var2 = p * self.dig_P8 / 32768.0
            pressure = (p + (var1 + var2 + self.dig_P7) / 16.0) / 100.0
        return temperature, h, pressure

    def _read(self, register, count):
        buf = bytearray(count)
        while not self.i2c.try_lock():
            pass
        try:
            # CircuitPython 3.x has no writeto_then_readfrom, so send the register address, then read.
            # The BME280 accepts a stop between the two.
            self.i2c.writeto(self.address, bytes([register]))
            self.i2c.readfrom_into(self.address, buf)
        finally:
            self.i2c.unlock()
        return buf

    def _write(self, register, value):
        while not self.i2c.try_lock():
            pass
        try:
            self.i2c.writeto(self.address, bytes([register, value]))
        finally:
            self.i2c.unlock()
