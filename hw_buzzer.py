"""
Buzzer configuration file
"""
import RPi._GPIO as GPIO
# import time
from PyQt5 import QtCore

class buzzer():
    def __init__(self):
        super().__init__()
        # Configuring the board's parameters
        # Physical pin number on the header (not GPIOxx)
        GPIO.setmode(GPIO.BOARD)
        # Buzzer pin
        self.buz_pin = 40

        # Buttons should be pulled up
        GPIO.setup(self.buz_pin, GPIO.OUT)
        # shut up
        GPIO.output(self.buz_pin, 0)

    def beep_for(self, duration):
        GPIO.output(self.buz_pin, 1)
        # time.sleep(duration)
        # QtCore.QThread.sleep(1)
        QtCore.QTimer.singleShot(1000 * duration, lambda: GPIO.output(self.buz_pin, 0))
        # GPIO.output(self.buz_pin, 0)




    