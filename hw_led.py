"""
LED configuration file
"""
import RPi._GPIO as GPIO
# import time
from PyQt5 import QtCore

class led():
    def __init__(self):
        super().__init__()
        # Configuring the board's parameters
        # Physical pin number on the header (not GPIOxx)
        GPIO.setmode(GPIO.BOARD)
        # LED pin
        self.led_pin = 7

        GPIO.setup(self.led_pin, GPIO.OUT)
        # start turned off, it's logic is reversed
        GPIO.output(self.led_pin, 1)

    def light_for(self, duration):
        GPIO.output(self.led_pin, 0)
        QtCore.QTimer.singleShot(1000 * duration, lambda: GPIO.output(self.led_pin, 1))
