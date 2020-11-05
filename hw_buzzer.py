"""
Buzzer configuration file
"""
import RPi._GPIO as GPIO
import time

class buzzer():
    def __init__(self):
        super().__init__()
        # Configuring the board's parameters
        # Physical pin number on the header (not GPIOxx)
        GPIO.setmode(GPIO.BOARD)
        # Buzzer pin
        self.buz_pin = 8

        # Buttons should be pulled up
        GPIO.setup(self.buz_pin, GPIO.OUT)
        # shut up
        GPIO.output(self.buz_pin, 0)

    def beep_for(self, duration):
        GPIO.output(self.buz_pin, 1)
        time.sleep(duration)
        GPIO.output(self.buz_pin, 0)




    