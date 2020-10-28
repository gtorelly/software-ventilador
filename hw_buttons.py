"""
Buttons configuration file
"""
import RPi._GPIO as GPIO
import time
# from queue import Queue

class Buttons():
    def __init__(self, input_q):
        super().__init__()
        # Creating the local reference to input_q
        self.input_q = input_q
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
        GPIO.setup(self.rot_clk_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.setup(self.rot_dt_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.setup(self.rot_btn_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

        # Configuring the falling edge interrupts - every button has a pullup
        # Clicky switches
        bounce_clicky = 300
        GPIO.add_event_detect(self.ok_pin, GPIO.FALLING,
                              callback=lambda x:self.queue_input("OK"), bouncetime=bounce_clicky)
        GPIO.add_event_detect(self.up_pin, GPIO.FALLING,
                              callback=lambda x:self.queue_input("UP"), bouncetime=bounce_clicky)
        GPIO.add_event_detect(self.down_pin, GPIO.FALLING, 
                              callback=lambda x:self.queue_input("DOWN"), bouncetime=bounce_clicky)
        GPIO.add_event_detect(self.rot_btn_pin, GPIO.FALLING,
                              callback=lambda x:self.queue_input("ROT"), bouncetime=bounce_clicky)
        
        # Rotary switch/encoder
        bounce_enc = 20
        GPIO.add_event_detect(self.rot_clk_pin, GPIO.FALLING, 
                              callback=lambda x:self.queue_input("clk"), bouncetime=bounce_enc)
        GPIO.add_event_detect(self.rot_dt_pin, GPIO.FALLING, 
                              callback=lambda x:self.queue_input("dt"), bouncetime=bounce_enc)
    
    def queue_input(self, key):
        self.input_q.put([key, time.time()])

    