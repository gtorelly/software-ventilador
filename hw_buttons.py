"""
Buttons configuration file
"""
from PyQt5 import QtCore
import RPi._GPIO as GPIO

class Buttons(QtCore.QObject):
    signal_increase = QtCore.pyqtSignal()
    signal_decrease = QtCore.pyqtSignal()
    def __init__(self, parent=None):
        super().__init__()
        # Configuring the board's parameters
        GPIO.setmode(GPIO.BOARD)
        # Physical pin number on the header (not GPIOxx)
        self.up_pin = 35
        self.down_pin = 37
        GPIO.setup(self.up_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.setup(self.down_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

        # Configuring the rising edge interrupts
        GPIO.add_event_detect(self.up_pin, GPIO.RISING, callback=self.up_btn_pressed,
                              bouncetime=500)
        GPIO.add_event_detect(self.down_pin, GPIO.RISING, callback=self.down_btn_pressed,
                              bouncetime=500)

    def up_btn_pressed(self, triggered_pin):
        self.signal_increase.emit()
        print("Pressed up button")

    def down_btn_pressed(self, triggered_pin):
        self.signal_decrease.emit()
        print("Pressed down button")