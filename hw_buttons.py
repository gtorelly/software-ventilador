"""
Buttons configuration file
"""

import RPi._GPIO as GPIO

class btns():
    def __init__(self, parent=None):
        # Configuring the board's parameters
        GPIO.setmode(GPIO.BOARD)
        # Physical pin number on the header (not GPIOxx)
        self.up_pin = 35
        self.down_pin = 37
        GPIO.setup(self.up_pin, GPIO.IN)
        GPIO.setup(self.down_pin, GPIO.IN)

        # Configuring the rising edge interrupts
        GPIO.add_event_detect(self.up_pin, GPIO.RISING, callback=self.up_btn_pressed)
        GPIO.add_event_detect(self.down_pin, GPIO.RISING, callback=self.down_btn_pressed)

    def up_btn_pressed(self):
        print("Pressed up button")

    def down_btn_pressed(self):
        print("Pressed down button")