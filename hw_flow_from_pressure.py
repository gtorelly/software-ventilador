"""
Controlling the ADC and pressure sensor to mesure a pressure difference in the airflow through an 
orifice. This method will be compared to using a flow sensor with a spinning wheel and the most 
accurate will be used to measure the bi-directional.
"""
import RPi._GPIO as GPIO
import time
import numpy as np

class flow_pressure():
    def __init__(self, parent=None):
        # Configuring the board's parameters
        GPIO.setmode(GPIO.BOARD)
        # Physical pin number on the header (not GPIOxx)
        self.input_pin = XX
        GPIO.setup(self.input_pin, GPIO.IN)
        