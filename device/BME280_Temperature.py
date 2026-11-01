def BME280_Temperature(tests, num_test_bytes, write_tests_to_nvm, reset):
    try:
        import board, busio, gc
        gc.collect()
        from bme280_min import BME280
        i2c = busio.I2C(board.SCL, board.SDA)
        temperature = BME280(i2c).read()[0]
        if -50 <= temperature <= 50:
            tests["BME280_Temperature"]["Passed"] = True
            print("Passed with", temperature)
        else:
            tests["BME280_Temperature"]["Passed"] = False
            print("Failed")
    except Exception as e:
        tests["BME280_Temperature"]["Passed"] = False
        print("Failed with ", e)
    finally:
        tests["BME280_Temperature"]["Test Run"] = True
        write_tests_to_nvm(tests, num_test_bytes)
        reset()