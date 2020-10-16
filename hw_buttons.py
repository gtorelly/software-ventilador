"""
Buttons configuration file
"""
from PyQt5 import QtCore
import RPi._GPIO as GPIO
import time
from threading import Lock

class Buttons(QtCore.QObject):
    signal_button = QtCore.pyqtSignal(str)
    clk = 1
    dt = 1
    lock = Lock()
    def __init__(self, parent=None):
        super().__init__()
        # Configuring the board's parameters
        # Physical pin number on the header (not GPIOxx)
        GPIO.setmode(GPIO.BOARD)
        # Pins of the buttons
        self.ok_pin = 33
        self.up_pin = 35
        self.down_pin = 37
        # Pins of the rotary switch
        self.rot_btn_pin = 19
        self.rot_dt_pin = 21
        self.rot_clk_pin = 23

        # Buttons should be pulled up
        GPIO.setup(self.ok_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.setup(self.up_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.setup(self.down_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        # The rotary switch has 10k pull up resistors
        GPIO.setup(self.rot_clk_pin, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
        GPIO.setup(self.rot_dt_pin, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
        GPIO.setup(self.rot_btn_pin, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)

        # Configuring the rising edge interrupts
        GPIO.add_event_detect(self.ok_pin, GPIO.RISING, callback=self.ok_btn_pressed,
                              bouncetime=100)
        GPIO.add_event_detect(self.up_pin, GPIO.RISING, callback=self.up_btn_pressed,
                              bouncetime=100)
        GPIO.add_event_detect(self.down_pin, GPIO.RISING, callback=self.down_btn_pressed,
                              bouncetime=100)
        GPIO.add_event_detect(self.rot_btn_pin, GPIO.RISING, callback=self.rot_btn_pressed,
                              bouncetime=100)
        
        # When the switch is rotated, one of the signals will fall first, one if CW, else CCW
        GPIO.add_event_detect(self.rot_clk_pin, GPIO.FALLING, callback=self.cw_rot,
                              bouncetime=100)
        GPIO.add_event_detect(self.rot_dt_pin, GPIO.FALLING, callback=self.ccw_rot,
                              bouncetime=100)

    def ok_btn_pressed(self, triggered_pin):
        self.signal_button.emit("OK")
        # print("Pressed ok button")

    def up_btn_pressed(self, triggered_pin):
        self.signal_button.emit("UP")
        # print("Pressed up button")

    def down_btn_pressed(self, triggered_pin):
        self.signal_button.emit("DOWN")
        # print("Pressed down button")
        
    def rot_btn_pressed(self, triggered_pin):
        self.signal_button.emit("ROT")
        # print("Pressed rot button")

    def cw_rot(self, triggered_pin):
        # self.lock.acquire()
        print(f"1 dt: {self.dt} - clk: {self.clk}")
        if self.dt == 0:
            direction = "CW"
        else:
            direction = "CCW"
        print("Emit " + direction)
        self.signal_button.emit(direction)
        self.dt = 1
        print(f"4 dt: {self.dt} - clk: {self.clk}\n")
        # self.lock.release()

    def ccw_rot(self, triggered_pin):
        # self.lock.acquire()
        print(f"5 dt: {self.dt} - clk: {self.clk}")
        self.dt = 0
        print(f"6 dt: {self.dt} - clk: {self.clk}\n")
        # self.lock.release()


    