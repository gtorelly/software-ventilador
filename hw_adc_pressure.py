"""
Setup of the ADC and Pressure gauge
"""
import Adafruit_ADS1x15
import numpy as np
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
        self.flw_volt_offset = 0

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
        volts = self.read_volts(self.flw_channel, self.flw_gain, self.adc_read_max,
                                self.flw_volt_max, "differential")
        # print(f"flow volts: {volts:.5f}")
        # Pressure sensor and orifice parameters used to obtain the flow
        offset = 0.0274
        beta = 1000 # TEMPORARY, the real equation is much more complex
        flow = (volts - self.flw_volt_offset) * beta
        # print(flow)
        return flow  # flow in liters per minute

    def tare_sensors(self, duration):
        """
        Called at the start of the routine to obtain the tare of both pressure sensors. This helps
        to obtain a more accurate measurement. Can also be called at other times when the ventilator
        is not operating.
        These values are offset voltages read by the adc.
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