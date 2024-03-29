"""
Definition of the hardware attached to the RPi: Buzzer, ADC, LED, Buttons, Rotary switch, pressure
sensor and piston control.
"""
import Adafruit_ADS1x15
import numpy as np
from PyQt5 import QtCore
import RPi._GPIO as GPIO
import bme280 as BME
import smbus2
import time

class pressure_gauge():
    # Configure the ADC parameters
    address = 0x48
    # Possible data rates (from datasheet): 8,  16, 32, 64, 128, 250, 475, 860
    # data_rate = 64
    # Raspberry Pi's bus number. The I2C interface is on bus 1
    busnum = 1

    # Gain: (From Adafruit's example/simpletest.py)
    #  - 2/3 = +/-6.144V
    #  -   1 = +/-4.096V
    #  -   2 = +/-2.048V
    #  -   4 = +/-1.024V
    #  -   8 = +/-0.512V
    #  -  16 = +/-0.256V
    gains = {2/3:6.144, 1:4.096, 2:2.048, 4:1.024, 8:0.512, 16:0.256}

    # Measurement parameters
    # ADC
    adc_read_max = 32767.0  # 16-bit

    def __init__(self, parent=None):
        # Create an instance of the ADC
        self.adc = Adafruit_ADS1x15.ADS1115(address=self.address, busnum=self.busnum)
        # Starts the adc measuring continuously. This doesn't work for two inputs, due to the way 
        # this library ws implemented
        # Starts the pressure measurement channel (MPX5010DP) - Non differential
        # self.adc.start_adc(channel=channel, data_rate=data_rate, gain=gain)
        # Starts the flow measurement channel (MPX10DP) - Differential
        # self.adc.start_adc(channel=channel, data_rate=data_rate, gain=gain)

        # In order to use two inputs of the same ADC, I will use single shot data acquisition
        # One is configured in channel 0 (input 1, single-ended) and the other at channel 3 (inputs 
        # 2-3, differential)

        # Configuration of the sensor used to measure pressure (MPX5010DP - single-ended)
        self.prs_channel = 0
        self.prs_gain = 2/3
        self.prs_volt_max = self.gains[self.prs_gain]

        # The gauge's output ranges from 0.2 to 4.7 V as per the datasheet (MPX5010DP)
        self.gauge_min_volt = 0.2
        self.gauge_max_volt = 4.7
        self.gauge_max_press = 101.978  # cm H2O
        self.prs_volt_offset = 0

        # Configuration of the sensor measuring flow from pressure delta (MPX10DP - differential)
        self.flw_channel = 3
        self.flw_gain = 16
        self.flw_volt_max = self.gains[self.flw_gain]
        self.flw_volt_offset = 0.0274

        # Creating the instance of the temperature, pressure ad humidity sensor, to get air density
        self.bme_sensor = bme()

    def read_volts(self, ch, gain, adc_max, volt_max, mode):
        """
        Generic function to get voltage read by the adc, withou any kind of offset compensation
        """
        if mode == "differential":
            digital = self.adc.read_adc_difference(ch, gain)
        else:
            digital = self.adc.read_adc(ch, gain)
        # calculating the voltage
        return ((digital / adc_max) * volt_max)

    def read_pressure(self):
        """
        Function that converts the input voltage read by the MPX5010DP to cm H2O
        """
        volts = self.read_volts(self.prs_channel, self.prs_gain, self.adc_read_max,
                                self.prs_volt_max, "single-ended")
        # print(f"prs volts: {volts:.4f}")
        # Offset correction (measured at zero pressure)
        # Converting the voltage to pressure, according to the gauge's properties
        cmh2o = self.gauge_max_press * ((volts - self.gauge_min_volt) / 
                                        (self.gauge_max_volt - self.gauge_min_volt))
        return(cmh2o)  # Pressure in cmh2o

    def read_flow_from_dp(self):
        """
        Function that converts the sensors voltage to a pressure difference, then to an 
        airflow based on the conversion equation of the orifice flow meter.
        """
        # reads the raw voltage from the adc
        volts = self.read_volts(self.flw_channel, self.flw_gain, self.adc_read_max,
                                self.flw_volt_max, "differential")

        # print(f"flow volts: {volts:.5f}")
        offset = 0.0274

        # delta_p must be in N / m² (Pa)
        # The full span of the sensor is 35 mV, corresponding to 10 kPa
        delta_p = (volts - self.flw_volt_offset) * 10000 / 0.035  # Pressure in Pa
        flow_dir = 1
        if delta_p < 0:
            flow_dir = -1


        # Pressure sensor and orifice parameters used to obtain the flow
        # Diameters of the orifice tube and ratio (beta)
        D_1 = 0.0185  # m
        D_2 = 0.0040  # m
        A_1 = np.pi * (D_1 / 2) * (D_1 / 2)
        A_2 = np.pi * (D_2 / 2) * (D_2 / 2)
        C_D = A_2 / A_1  # Area ratio
        d = D_2 / D_1  # Diameter ratio
        # The air density must be calculated taking into account the air temperature and humidity,
        # therefore it is necessary to buy another sensor for this application.
        rho = self.bme_sensor.get_air_density()

        # q is the flow in m³/s
        q = C_D * (np.pi / 4.0) * (D_2 ** 2.0) * (2.0 * delta_p * flow_dir /
                                                  (rho * ((1.0 - d) ** 4.0))) ** 0.5 
        # Converting to l / minute
        flow = q * 60000 * flow_dir
        # print(f"mV: {1000 * volts:.2f}")
        return flow  # flow in liters per minute

    def tare_sensors(self, duration):
        """
        Called at the start of the routine to obtain the tare of both pressure sensors. This helps
        to obtain a more accurate measurement. Can also be called at other times when the ventilator
        is not operating.
        These values are offset voltages read by the adc.
        This function needs to be called in a clever way to avoid accumulation of errors.
        """
        prs_volts = []
        flw_volts = []
        start = time.time()
        i = 0
        while time.time() - start < duration:
            prs_volts.append(self.read_volts(self.prs_channel, self.prs_gain, self.adc_read_max,
                                             self.prs_volt_max, "single-ended"))
            flw_volts.append(self.read_volts(self.flw_channel, self.flw_gain, self.adc_read_max,
                                             self.flw_volt_max, "differential"))
            i += 1
        print(f"Took {i} measurements during {duration} seconds to tare the sensor")
        self.prs_volt_offset = np.mean(np.array(prs_volts))
        self.flw_volt_offset = np.mean(np.array(flw_volts))

class buttons():
    def __init__(self, input_q):
        super().__init__()
        # Creating the local reference to input_q
        self.input_q = input_q
        # Configuring the board's parameters
        # Pin numbers as defined by BCM, not the physical location on the board
        GPIO.setmode(GPIO.BCM)
        # Pins of the buttons
        self.ok_pin = 11
        self.up_pin = 9
        self.down_pin = 10
        # Pins of the rotary switch
        self.rot_btn_pin = 17
        self.rot_dt_pin = 27
        self.rot_clk_pin = 0

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
        bounce_clicky = 200
        GPIO.add_event_detect(self.ok_pin, GPIO.FALLING,
                              callback=lambda x:self.queue_input("OK"), bouncetime=bounce_clicky)
        GPIO.add_event_detect(self.up_pin, GPIO.FALLING,
                              callback=lambda x:self.queue_input("UP"), bouncetime=bounce_clicky)
        GPIO.add_event_detect(self.down_pin, GPIO.FALLING, 
                              callback=lambda x:self.queue_input("DOWN"), bouncetime=bounce_clicky)
        GPIO.add_event_detect(self.rot_btn_pin, GPIO.FALLING,
                              callback=lambda x:self.queue_input("ROT"), bouncetime=bounce_clicky)
        
        # Rotary switch/encoder
        bounce_enc = 10
        GPIO.add_event_detect(self.rot_clk_pin, GPIO.FALLING, 
                              callback=lambda x:self.queue_input("clk"), bouncetime=bounce_enc)
        GPIO.add_event_detect(self.rot_dt_pin, GPIO.FALLING, 
                              callback=lambda x:self.queue_input("dt"), bouncetime=bounce_enc)
    
    def queue_input(self, key):
        self.input_q.put([key, time.time()])

class buzzer():
    
    def __init__(self):
        super().__init__()
        # Configuring the board's parameters
        # Pin numbers as defined by BCM, not the physical location on the board
        GPIO.setmode(GPIO.BCM)
        # Buzzer pin
        self.buz_pin = 4

        # Buttons should be pulled up
        GPIO.setup(self.buz_pin, GPIO.OUT)
        # shut up
        GPIO.output(self.buz_pin, 0)

    def beep_for(self, duration):
        GPIO.output(self.buz_pin, 1)
        QtCore.QTimer.singleShot(1000 * duration, lambda: GPIO.output(self.buz_pin, 0))

class led():
    def __init__(self):
        super().__init__()
        # Configuring the board's parameters
        # Pin numbers as defined by BCM, not the physical location on the board
        GPIO.setmode(GPIO.BCM)
        # LED pin
        self.led_pin = 12

        GPIO.setup(self.led_pin, GPIO.OUT)
        # start turned off, it's logic is reversed
        GPIO.output(self.led_pin, 1)

    def light_for(self, duration):
        GPIO.output(self.led_pin, 0)
        QtCore.QTimer.singleShot(1000 * duration, lambda: GPIO.output(self.led_pin, 1))
        
class pneumatic_piston():
    def __init__(self, parent=None):
        # Pin numbers as defined by BCM, not the physical location on the board
        GPIO.setmode(GPIO.BCM)
        self.pin_down = 6
        self.pin_up = 5
        self.pin_sensor_down = 19
        self.pin_sensor_up = 26
        
        # Assigning pin numbers and setting them to zero
        GPIO.setwarnings(False)
        GPIO.setup(self.pin_down, GPIO.OUT) 
        GPIO.setup(self.pin_up, GPIO.OUT)
        GPIO.setup(self.pin_sensor_down, GPIO.IN, pull_up_down=GPIO.PUD_UP) 
        GPIO.setup(self.pin_sensor_up, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.output(self.pin_down, 0)  # garantir zero p/pistao descida
        GPIO.output(self.pin_up, 0)  # garantir zero p/pistao subida

        # In case the movement doesn't complete in this amount of time, stop
        self.timeout = 10000  # ms

        # Variables that register the piston position
        self.piston_at_bottom = False
        self.piston_at_top = False
        # Configuring the interrupts that will define 
        GPIO.add_event_detect(self.pin_sensor_down, GPIO.RISING, 
                              callback=lambda x:self.position_sensor("down"))
        GPIO.add_event_detect(self.pin_sensor_up, GPIO.RISING, 
                              callback=lambda x:self.position_sensor("up"))
        
    # def piston_down(self, duration):
    #     """
    #     Lowers the piston if it is not already on the bottom. Once the piston reached the bottom, as 
    #     identified by the endstop sensor, returns True indicating that the movement happened as 
    #     desired. If there was a timeout, stops the movement and returns False. The timeout might be
    #     because something stopped the piston from moving or it may be the desired duration of the 
    #     movement, which stops before reaching the endstop.
    #     """
    #     if GPIO.input(self.pin_sensor_down) == True:
    #         # The piston is already at the lowest position.
    #         return 'bottom'
    #     GPIO.output(self.pin_up, 0)  # Guarantees the piston is not going up
    #     GPIO.output(self.pin_down, 1)
    #     # The timeout must be an int in ms
    #     ms_duration = int(round(1000 * duration, 0))
    #     if ms_duration < 1:  # This value must be always greater than zero
    #         print(f"Timeout Error, less than 1 ms: {ms_duration}")
    #         ms_duration = 1
    #     down = GPIO.wait_for_edge(self.pin_sensor_down, GPIO.RISING, timeout=ms_duration)
    #     # In any case, turn the output off
    #     GPIO.output(self.pin_down, 0)
    #     # return depending on the case
    #     if down is None:  # Timeout occurred
    #         return None
    #     # Didn't timeout, piston went down normally
    #     return 'bottom'
        
    # def piston_up(self, duration):
    #     """
    #     Raises the piston if it is not already on the top. Once the piston reached the top, as 
    #     identified by the endstop sensor, returns True indicating that the movement happened as 
    #     desired. If there was a timeout, stops the movement and returns False. The timeout might be
    #     because something stopped the piston from moving or it may be the desired duration of the 
    #     movement, which stops before reaching the endstop.
    #     """
    #     if GPIO.input(self.pin_sensor_up) == True:
    #         # The piston is already at the highest position.
    #         return 'top'
    #     GPIO.output(self.pin_down, 0)  # Guarantees the piston is not going down
    #     GPIO.output(self.pin_up, 1)  # Makes the piston go up
    #     # The timeout must be an int in ms
    #     ms_duration = int(round(1000 * duration, 0))
    #     if ms_duration < 1:  # This value must be always greater than zero
    #         print(f"Timeout Error, less than 1 ms: {ms_duration}")
    #         ms_duration = 1
    #     up = GPIO.wait_for_edge(self.pin_sensor_up, GPIO.RISING, timeout=ms_duration)
    #     GPIO.output(self.pin_up, 0) 
    #     if up is None: # Timeout occurred
    #         return None
    #     return 'top'

    def emergency(self):
        """
        Moves the piston up in an emergency
        """
        # Send the piston up
        GPIO.output(self.pin_up, 1)
        GPIO.output(self.pin_down, 0)
        # After 10 seconds, turn off the up output
        time.sleep(10)
        GPIO.output(self.pin_up, 0)

    def stop(self):
        """
        Stops the piston by disabling both solenoids
        """
        GPIO.output(self.pin_up, 0)
        GPIO.output(self.pin_down, 0)

    def pst_down(self):
        """
        Simple function that turns on the solenoid making the piston go down.
        """
        # if GPIO.input(self.pin_sensor_down) == True:
        #     # The piston is already at the bottom.
        #     return 'bottom'
        GPIO.output(self.pin_up, 0)  # Guarantees the piston is not going up 
        GPIO.output(self.pin_down, 1)  # Makes the piston go down
        self.piston_at_top = False  # If the piston is going down, its not at the top

    def pst_up(self):
        """
        Simple function that turns on the solenoid making the piston go up.
        """
        GPIO.output(self.pin_down, 0)  # Guarantees the piston is not going down
        GPIO.output(self.pin_up, 1)  # Makes the piston go up
        self.piston_at_bottom = False  # If the piston is going up, it's not at the bottom
        
    def position_sensor(self, sens):
        """
        Function called by interrupts to define the position of the piston.
        """
        if sens == "down":
            self.piston_at_bottom = True
            self.piston_at_top = False
        else:
            self.piston_at_bottom = False
            self.piston_at_top = True

class bme():
    def __init__(self):
        super().__init__()
        self.port = 1
        self.address = 0x76
        self.bus = smbus2.SMBus(self.port)

        self.calibration_params = BME.load_calibration_params(self.bus, self.address)

    def get_air_density(self):
        # the sample method will take a single reading and return a
        # compensated_reading object
        data = BME.sample(self.bus, self.address, self.calibration_params)

        # the compensated_reading class has the following attributes
        # print(data.id)
        # print(data.timestamp)
        # print(f"T: {data.temperature:.2f} °C")
        # print(f"P: {data.pressure:.2f} mbar")
        # print(f"H: {data.humidity:.2f} %")

        # The equation used to calculate the density of air was taken from wikipedia's article,
        # and it is from https://wahiduddin.net/calc/density_altitude.htm - An Introduction fo Air 
        # Density and Density Altitude Calculations by Richard Shelquist, 2019
        # Calculation of the air density based on T, P and H
        T = data.temperature + 273.15  # Temperature in Kelvin
        P = data.pressure * 100  # Pressure in Pa
        R = 8.31446  # Universal gas constant in J/(K.Mol)
        M_d = 0.0289652  # Molar mass of dry air in Kg/Mol
        M_v = 0.018016  # Molar mass of water vapor in Kg/Mol

        # Saturation vapor pressure of water (Tetens' equation) (uses temperatures in C!)
        P_sat = 610.78 * 10 ** (7.5 * data.temperature / (data.temperature + 237.3))  # in Pa
        phi = data.humidity / 100  # Relative umidity varying from 0-1
        P_v = phi * P_sat  # Vapor pressure of water in Pa
        P_d = P - P_v  # partial pressure of dry air in Pa

        # print(f"P_sat: {P_sat} Pa")
        # print(f"phi: {phi}")
        # print(f"P_v: {P_v} Pa")
        # print(f"P_d: {P_d} Pa")

        air_density = (P_d * M_d + P_v * M_v) / (R * T)
        # print(f"Density of humid air: {air_density:.4f} Kg/m³\n")
        # there is a handy string representation too
        # print(data)
        return(air_density)