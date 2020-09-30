import Adafruit_ADS1x15

class pressure_gauge():
    """
    Setup of the ADC and Pressure gauge
    """
    def __init__(self, parent=None):
        # Configure the ADC parameters
        address = 0x48
        # Possible data rates (from datasheet): 8,  16, 32, 64, 128, 250, 475, 860
        data_rate = 860
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
        gain = 2/3  # +/-6.144V
        # ADC channel
        channel = 0
        # Starts the adc measuring continuously.
        # Create an instance of the ADC
        self.adc = Adafruit_ADS1x15.ADS1115(address=address, busnum=busnum)
        self.adc.start_adc(channel=channel, data_rate=data_rate, gain=gain)

        # Measurement parameters
        # ADC
        self.adc_read_max = 32767.0  # 16-bit
        self.adc_volt_max = gains[gain]
        
        # Pressure gauge
        # The gauge's output ranges from 0.2 to 4.7 V as per the datasheet
        self.gauge_min_volt = 0.2
        self.gauge_max_volt = 4.7
        self.tara = 0.27  # 0.17 # ver valor em volt sem pressão
        self.gauge_max_press = 101.978  # cm H2O
    
    def read_pressure(self):
        """
        Function that reads the ADC and converts its value to cm H2O
        """
        # Since the adc is reading continuously, it's just a matter of getting the last measurement
        value = self.adc.get_last_result()
        # Calculating the voltage read by the adc
        volt = ((value / self.adc_read_max) * self.adc_volt_max)
        # Converting the voltage to pressure, according to the gauge's properties
        cmh2o = self.gauge_max_press * ((volt - self.gauge_min_volt) / 
                                        (self.gauge_max_volt - self.gauge_min_volt))
        
        return(cmh2o)  # Pressure in cmh2o
