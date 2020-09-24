"""
Definition of the pneumatic piston control
"""
import RPi.GPIO as GPIO
import time

class pneumatic_piston():
    def __init__(self, parent=None):
        # Definition of the pins (physical numbering on board, not GPIOXX)
        self.pin_down = 16
        self.pin_up = 18
        self.pin_sensor_down = 38
        self.pin_sensor_up = 36
        
        # Assigning pin numbers and setting them to zero
        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BOARD)  # defines pin numbers as physical numbering on board, not GPIOXX
        GPIO.setup(self.pin_down,GPIO.OUT) 
        GPIO.setup(self.pin_up,GPIO.OUT)
        GPIO.setup(self.pin_sensor_down,GPIO.IN) 
        GPIO.setup(self.pin_sensor_up,GPIO.IN)
        GPIO.output(self.pin_down, 0) #garantir zero p/pistao descida
        GPIO.output(self.pin_up, 0) #garantir zero p/pistao subida

        # In case the movement doesn't complete in this amount of time, stop
        self.timeout = 10000  # ms
        
    def piston_down(self, duration):
        """
        Lowers the piston if it is not already on the bottom. Once the piston reached the bottom, as 
        identified by the endstop sensor, returns True indicating that the movement happened as 
        desired. If there was a timeout, stops the movement and returns False. The timeout might be
        because something stopped the piston from moving or it may be the desired duration of the 
        movement, which stops before reaching the endstop.
        """
        if GPIO.input(self.pin_sensor_down) == True:
            # The piston is already at the lowest position.
            return True
        GPIO.output(self.pin_down, 1)
        # The timeout must be an int in ms
        ms_duration = int(round(1000 * duration, 0))
        if ms_duration < 1:  # This value must be always greater than zero
            print(f"Timeout Error, less than 1 ms: {ms_duration}")
            ms_duration = 1
        down = GPIO.wait_for_edge(self.pin_sensor_down, GPIO.RISING, timeout=ms_duration)
        # In any case, turn the output off
        GPIO.output(self.pin_down, 0)
        # return depending on the case
        if down is None:  # Timeout occurred
            return False
        else:  # Didn't timeout, piston went down normally
            return True
        
    def piston_up(self, duration):
        """
        Raises the piston if it is not already on the top. Once the piston reached the top, as 
        identified by the endstop sensor, returns True indicating that the movement happened as 
        desired. If there was a timeout, stops the movement and returns False. The timeout might be
        because something stopped the piston from moving or it may be the desired duration of the 
        movement, which stops before reaching the endstop.
        """
        if GPIO.input(self.pin_sensor_up) == True:
            # The piston is already at the highest position.
            return True
        GPIO.output(self.pin_up, 1)  # Makes the piston go up
        # The timeout must be an int in ms
        ms_duration = int(round(1000 * duration, 0))
        if ms_duration < 1:  # This value must be always greater than zero
            print(f"Timeout Error, less than 1 ms: {ms_duration}")
            ms_duration = 1
        up = GPIO.wait_for_edge(self.pin_sensor_up, GPIO.RISING, timeout=ms_duration)
        GPIO.output(self.pin_up, 0) 
        if up is None: # Timeout occurred
            return False
        else:
            return True
         
    def piston_up_no_stop(self, timeout):
        # Turn on the up output
        GPIO.output(self.pin_up, 1)
        # wait
        time.sleep(timeout)
        # turn off the up output
        GPIO.output(self.pin_up, 0)
        
    def piston_down_no_stop(self, timeout):
        # Turn on the down output
        GPIO.output(self.pin_down, 1)
        # wait
        time.sleep(timeout)
        # turn off the down output
        GPIO.output(self.pin_down, 0)
            
            
            
        
