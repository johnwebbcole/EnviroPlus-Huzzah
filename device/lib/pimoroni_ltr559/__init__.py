# Minimal LTR559 light and proximity driver for a Feather HUZZAH (ESP8266, CircuitPython 3.x).
# The full pimoroni_ltr559 driver is too big to compile in this build's RAM, so this one reads the
# registers directly, with the same settings and lux formula as the full driver.
# Copy it to the board with: huzzah.sh put examples/huzzah/pimoroni_ltr559/__init__.py lib/pimoroni_ltr559/__init__.py
# It needs pimoroni_circuitpython_adapter on the board too, for the I2C object passed in as i2c_dev.

I2C_ADDR = 0x23
PART_ID = 0x09

ALS_CONTROL = 0x80
PS_CONTROL = 0x81
PS_LED = 0x82
PS_N_PULSES = 0x83
PS_MEAS_RATE = 0x84
ALS_MEAS_RATE = 0x85
PART_ID_REG = 0x86
ALS_DATA = 0x88
ALS_PS_STATUS = 0x8C
PS_DATA = 0x8D

GAIN = 4
INTEGRATION_TIME = 50

# Lux coefficients for each colour-ratio band
CH0_C = (17743, 42785, 5926, 0)
CH1_C = (-11059, 19548, -1185, 0)


class LTR559:
    def __init__(self, i2c_dev=None, **_):
        self.i2c = i2c_dev
        if self.i2c.read_byte_data(I2C_ADDR, PART_ID_REG) >> 4 != PART_ID:
            raise RuntimeError("LTR559 not found")
        self.i2c.write_byte_data(I2C_ADDR, PS_LED, 0x1B) # 30kHz pulse, 100% duty, 50mA
        self.i2c.write_byte_data(I2C_ADDR, PS_N_PULSES, 1)
        self.i2c.write_byte_data(I2C_ADDR, ALS_CONTROL, 0x09) # gain 4, active
        self.i2c.write_byte_data(I2C_ADDR, PS_CONTROL, 0x23) # proximity active, saturation indicator on
        self.i2c.write_byte_data(I2C_ADDR, PS_MEAS_RATE, 0x02) # 100ms
        self.i2c.write_byte_data(I2C_ADDR, ALS_MEAS_RATE, 0x08) # 50ms integration, 50ms repeat
        self._lux = 0
        self._ps0 = 0

    def update_sensor(self):
        status = self.i2c.read_byte_data(I2C_ADDR, ALS_PS_STATUS)
        if status & 0x01: # new proximity data
            ps = self.i2c.readfrom_mem(I2C_ADDR, PS_DATA, 2)
            self._ps0 = ps[0] | ((ps[1] & 0x0F) << 8)
        if status & 0x04: # new light data
            als = self.i2c.readfrom_mem(I2C_ADDR, ALS_DATA, 4)
            als1 = als[0] | (als[1] << 8)
            als0 = als[2] | (als[3] << 8)
            total = als0 + als1
            ratio = als1 * 100 / total if total > 0 else 101
            if ratio < 45:
                band = 0
            elif ratio < 64:
                band = 1
            elif ratio < 85:
                band = 2
            else:
                band = 3
            self._lux = (als0 * CH0_C[band] - als1 * CH1_C[band]) / (INTEGRATION_TIME / 100.0) / GAIN / 10000.0

    def get_lux(self, passive=False):
        if not passive:
            self.update_sensor()
        return self._lux

    def get_proximity(self, passive=False):
        if not passive:
            self.update_sensor()
        return self._ps0
