def Mic(tests, num_test_bytes, write_tests_to_nvm, reset):
    try:
        import analogio, board, time
        # The HUZZAH's only ADC is board.ADC, which the wing's mic is wired to (pin 8 on other boards)
        mic = analogio.AnalogIn(board.ADC)
        samples = list(range(20))
        clap_time = 0
        half_second = 0.5 # measured in seconds, as this build has no time.monotonic_ns
        clap_threshold = 1000 # the higher the value the less sensitive
        print("Please Double Clap. If nothing happens, there may be a problem with the Mic")
        while True: # detection start
            for i in range(20): # take 20 samples of how loud it is
                samples[i] = abs(mic.value - 32768)

            if (sum(samples)/20) > clap_threshold: # if clap found

                if not clap_time + half_second >= time.monotonic(): # if another clap hasn't happened in the last half second
                    #print("Clap at {}".format(time.monotonic()))
                    clap_time = time.monotonic() # update the last time a clap happened
                    time.sleep(0.1)
                else: # if another clap has happened in the last half second
                    print("Double Clap Detected!")
                    break
        tests["Mic"]["Passed"] = True
    except Exception as e:
        tests["Mic"]["Passed"] = False
        print("Failed with ", e)
    finally:
        tests["Mic"]["Test Run"] = True
        write_tests_to_nvm(tests, num_test_bytes)
        reset()
