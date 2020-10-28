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
        self.A_pin = 11
        self.B_pin = 13
        GPIO.setup(self.A_pin, GPIO.IN)
        GPIO.setup(self.B_pin, GPIO.IN)
        
        # Array to store timing of the rising edges
        self.A_edge_t = np.zeros(5000) 
        self.B_edge_t = np.zeros(5000) 
        # Configuring the rising edge interrupts
        GPIO.add_event_detect(self.A_pin, GPIO.RISING, callback=self.store_A_edge_t)
        GPIO.add_event_detect(self.B_pin, GPIO.RISING, callback=self.store_B_edge_t)

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
        gpio_init = GPIO.input(self.A_pin)
        # On the start, the last is equal to the initial
        gpio_last = gpio_init
        # While we want the measurement to last, count the pulses.
        while delta_t < meas_duration:
            # See if there was any change
            gpio_cur = GPIO.input(self.A_pin)
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
        
    def store_A_edge_t(self, triggered_pin):
        # rolls the data, eliminating the last column and inserting zero
        self.A_edge_t = np.roll(self.A_edge_t, -1)
        # the zeros in the end of the array receive the data
        self.A_edge_t[-1] = time.time()

    def store_B_edge_t(self, triggered_pin):
        # rolls the data, eliminating the last column and inserting zero
        self.B_edge_t = np.roll(self.B_edge_t, -1)
        # the zeros in the end of the array receive the data
        self.B_edge_t[-1] = time.time()
        
    def calc_flow(self, time_window):
        # Sums how many times in the last "window" seconds the signal changed
        pulses = np.sum(self.A_edge_t > time.time() - time_window)
        return 60 * pulses / (self.pulses_per_liter * time_window)  # In liters per minute
        
    def calc_volume(self, time_window):
        # Sums how many times in the last "window" seconds the signal changed
        pulses = np.sum(self.A_edge_t > time.time() - time_window)
        return pulses / self.pulses_per_liter # In liters
