def BME280_Pressure(tests, num_test_bytes, write_tests_to_nvm, reset):
    try:
        import board, busio, gc
        gc.collect()
        from bme280_min import BME280
        i2c = busio.I2C(board.SCL, board.SDA)
        pressure = BME280(i2c).read()[2]
        if 850 <= pressure <= 1100:
            tests["BME280_Pressure"]["Passed"] = True
            print("Passed with", pressure)
        else:
            tests["BME280_Pressure"]["Passed"] = False
            print("Failed")
    except Exception as e:
        tests["BME280_Pressure"]["Passed"] = False
        print("Failed with ", e)
    finally:
        tests["BME280_Pressure"]["Test Run"] = True
        write_tests_to_nvm(tests, num_test_bytes)
        reset()