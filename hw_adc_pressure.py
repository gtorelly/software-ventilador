"""
Setup of the ADC and Pressure gauge
"""
import Adafruit_ADS1x15

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
        
        # ADC channel
        channel = 0
        # Starts the adc measuring continuously.
        # Create an instance of the ADC
        self.adc = Adafruit_ADS1x15.ADS1115(address=self.address, busnum=self.busnum)
        # Starts the pressure measurement channel (MPX5010DP) - Non differential
        # self.adc.start_adc(channel=channel, data_rate=data_rate, gain=gain)
        # Starts the flow measurement channel (MPX10DP) - Differential
        # self.adc.start_adc(channel=channel, data_rate=data_rate, gain=gain)

        # Pressure gauge
        # The gauge's output ranges from 0.2 to 4.7 V as per the datasheet
        self.gauge_min_volt = 0.2
        self.gauge_max_volt = 4.7
        # self.tara = 0.27  # 0.17 # ver valor em volt sem pressão
        self.gauge_max_press = 101.978  # cm H2O
    
    def read_pressure(self):
        """
        Function that reads the ADC and converts its value to cm H2O
        """
        # ADC parameters
        channel = 0
        gain = 2/3
        volt_max = self.gains[gain]
        # In order to use two inputs of the same chip, I will use single shot data acquisition
        value = self.adc.read_adc(channel, gain)
        # Calculating the voltage read by the adc
        volt = ((value / self.adc_read_max) * volt_max)
        # Converting the voltage to pressure, according to the gauge's properties
        cmh2o = self.gauge_max_press * ((volt - self.gauge_min_volt) / 
                                        (self.gauge_max_volt - self.gauge_min_volt))
        
        return(cmh2o)  # Pressure in cmh2o

    def read_flow_from_dp(self):
        """
        Function that reads the ADC and converts its value to a pressure difference, then to an 
        airflow based on the conversion equation of the orifice flow meter.
        """
        # ADC parameters
        gain = 16
        channel = 3
        volt_max = self.gains[gain]
        # Pressure sensor parameters
        offset = -0.0276 # V
        beta = 1000 # TEMPORARY, the real equation is much more complex
        # read the voltage difference
        value = self.adc.read_adc_difference(channel, gain)
        volts = ((value / self.adc_read_max) * volt_max)
        # print(volts)
        flow = (volts - offset) * beta
        # print(flow)
        return flow