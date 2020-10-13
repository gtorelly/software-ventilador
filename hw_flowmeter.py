"""
Flowmeter configuration file
"""

import RPi._GPIO as GPIO
import time
import numpy as np

class flowmeter():
    def __init__(self, parent=None):
        # Flowmeter parameters
        self.pulses_per_liter = 450
        # Configuring the board's parameters
        GPIO.setmode(GPIO.BOARD)
        # Physical pin number on the header (not GPIOxx)
        self.input_pin = 13
        GPIO.setup(self.input_pin, GPIO.IN)
        
        # Array to store timing of the rising edges
        self.edge_timing = np.zeros(1000) 
        # Configuring the rising edge interrupts
        GPIO.add_event_detect(self.input_pin, GPIO.RISING, callback=self.store_edge_timing)

    def read_flow(self): # Old function that counts n pulses in a given amount of time. veeeery slow
        # Pulse counter
        pulses = 0
        # Duration of the measurement in seconds.
        meas_duration = 1  # 100 ms
        # Time elapsed since the beginning of the measurement
        delta_t = 0.0
        # Instant when the measurement is started
        time_start = time.time()
        # Gets the initial input state
        gpio_init = GPIO.input(self.input_pin)
        # On the start, the last is equal to the initial
        gpio_last = gpio_init
        # While we want the measurement to last, count the pulses.
        while delta_t < meas_duration:
            # See if there was any change
            gpio_cur = GPIO.input(self.input_pin)
            # gets the delta_t right after the measurement
            delta_t = time.time() - time_start
            # If there was a state change and it is in the same state as when started, there was a 
            # pulse
            if gpio_cur == gpio_init and gpio_cur != gpio_last:
                # Count the pulse
                pulses += 1
                # Store the change
            gpio_last = gpio_cur
           
        flow = 60 * pulses / (self.pulses_per_liter * delta_t)  # In liters per minute   
        return flow
        
    def store_edge_timing(self, triggered_pin):
        # rolls the data, eliminating the last column and inserting zero
        self.edge_timing = np.roll(self.edge_timing, -1)
        # the zeros in the end of the array receive the data
        self.edge_timing[-1] = time.time()
        
    def calc_flow(self, time_window):
        # Sums how many times in the last "window" seconds the signal changed
        pulses = np.sum(self.edge_timing > time.time() - time_window)
        return 60 * pulses / (self.pulses_per_liter * time_window)  # In liters per minute
        
    def calc_volume(self, time_window):
        # Sums how many times in the last "window" seconds the signal changed
        pulses = np.sum(self.edge_timing > time.time() - time_window)
        return pulses / self.pulses_per_liter # In liters
