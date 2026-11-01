def BME280_Humidity(tests, num_test_bytes, write_tests_to_nvm, reset):
    try:
        import board, busio, gc
        gc.collect()
        from bme280_min import BME280
        i2c = busio.I2C(board.SCL, board.SDA)
        humidity = BME280(i2c).read()[1]
        if 0 <= humidity <= 100:
            tests["BME280_Humidity"]["Passed"] = True
            print("Passed with", humidity)
        else:
            tests["BME280_Humidity"]["Passed"] = False
            print("Failed")
    except Exception as e:
        tests["BME280_Humidity"]["Passed"] = False
        print("Failed with ", e)
    finally:
        tests["BME280_Humidity"]["Test Run"] = True
        write_tests_to_nvm(tests, num_test_bytes)
        reset()