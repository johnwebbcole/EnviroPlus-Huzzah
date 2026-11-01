def Light(tests, num_test_bytes, write_tests_to_nvm, reset):
    try:
        from pimoroni_circuitpython_adapter import not_SMBus
        from pimoroni_ltr559 import LTR559
        i2c_dev = not_SMBus() # uses board.SCL and board.SDA, as this build has no board.I2C
        ltr559 = LTR559(i2c_dev=i2c_dev)
        if 0 <= ltr559.get_lux() <= 30000:
            tests["Light"]["Passed"] = True
            print("Passed with", ltr559.get_lux())
        else:
            tests["Light"]["Passed"] = False
            print("Failed")
    except Exception as e:
        tests["Light"]["Passed"] = False
        print("Failed with ", e)
    finally:
        tests["Light"]["Test Run"] = True
        write_tests_to_nvm(tests, num_test_bytes)
        reset()