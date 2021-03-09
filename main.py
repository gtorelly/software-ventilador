"""
Main function
"""
import configparser
import numpy as np
import os
from PyQt5 import QtWidgets, QtCore, uic
import pyqtgraph as pg
from queue import Queue, LifoQueue
from scipy import integrate
import sys
import time
from hardware import pressure_gauge, pneumatic_piston, buttons, buzzer, led, bme

class ReadSensors(QtCore.QObject):
    """
    This class is used to create a thread that reads information from the sensor continuously.
    The signal "signal_sensors" emits a list that is read by the function "update_sensors". The list
    contains flow, volume and pressure.
    """
    def __init__(self, flw_q, prs_q):
        super().__init__()
        # Classes that creates the instances of IO classes
        self.gauge = pressure_gauge()
        # self.meter = flowmeter()
        # Associates the received queues with local variables
        self.flw_q = flw_q
        self.prs_q = prs_q

    def work(self):
        """
        Continuously reads the data from the sensors and feeds it to the main function through 
        queues.
        """
        while(True):
            debug_print = False
            if debug_print == True:
                start = time.time()

            flow = self.gauge.read_flow_from_dp()
            self.flw_q.put([time.time(), flow])

            if debug_print == True:
                flow_time = time.time()
                print(f"Runtime - calc_flow: {1000 * (flow_time - start):.0f} ms")

            pressure = self.gauge.read_pressure()
            self.prs_q.put([time.time(), pressure])

            if debug_print == True:
                pressure_time = time.time()
                print(f"Runtime - read_pressure: {1000 * (pressure_time - flow_time):.0f} ms")
                
            if debug_print == True:
                runtime = time.time() - start
                print(f"Runtime - total: {1000 * runtime:.1f} ms")
                print(f"Frequency: {1 / runtime:.1f} Hz")

class ControlPiston(QtCore.QObject):
    signal_piston = QtCore.pyqtSignal(bool)
    signal_cycle_data = QtCore.pyqtSignal(dict)
    signal_startup_error = QtCore.pyqtSignal(bool)
    signal_get_tare = QtCore.pyqtSignal(float)
    
    def __init__(self, gui, flw_lifo_q, prs_lifo_q, vol_lifo_q, mode):
        super().__init__()
        # receives the piston instance from the call of this worker in the main window
        # assigns the instance to another with the same name.
        self.piston = pneumatic_piston()
        self.stop = False
        self.gui = gui
        self.flw = flw_lifo_q
        self.prs = prs_lifo_q
        self.vol = vol_lifo_q
        self.mode = 0
        self.pause = False
        self.pause_duration = 1

        # Variables to store the current position and next direction of the piston movement
        self.pst_pos = None
        self.pst_dir = 1  # Starts going down

        # Dictionary that stores the cycle data, in order to create the pipeline, sending this info
        # to the interface.
        self.cd = {"started_up": False}

    def startup(self):
        """
        Starts the cycle until the piston moves to a known position
        """
        # Initializing the cycle data (cd) dictionary
        self.cd["started_up"] = False
        self.cd["peak_pressure"] = 0
        self.cd["tidal_volume"] = 0
        self.cd["inhale_duration"] = 0
        self.cd["exhale_duration"] = 0
        self.cd["IE_ratio"] = 1
        self.cd["PEEP"] = 0

        to = 2  # Timeout
        startup_cycles = 0
        limit = 20
        # If the piston position is unknown
        last_cycle = time.time()
        while not self.piston.piston_at_bottom and not self.piston.piston_at_top:
            if self.pst_dir == 1:
                self.piston.pst_up()
                if time.time() - last_cycle > to:
                    self.pst_dir = 0
                    startup_cycles += 1
                    last_cycle = time.time()
            else:
                self.piston.pst_down()
                if time.time() - last_cycle > to:
                    self.pst_dir = 1
                    startup_cycles += 1
                    last_cycle = time.time()
            if startup_cycles >= limit:
                print("There is a problem at startup, check compressed air")
                print(f"Tried to startup for {startup_cycles} cycles")
                # Breaks the loop so that the controller doesn't start
                self.signal_startup_error.emit(True)
                return
        while not self.piston.piston_at_top:
            self.piston.pst_up()
        self.piston.stop()

        print(f"startup_cycles: {startup_cycles}")
        self.cd["started_up"] = True
        self.signal_cycle_data.emit(self.cd)
        # Duration of the first tare of the system
        tare_duration = 5.0
        time.sleep(tare_duration)
        self.signal_get_tare.emit(tare_duration)
        # Waits a little bit just to make sure that the respirator isn't working when the controller 
        # is called
        time.sleep(0.5)
        self.piston_control()

    def piston_control(self):
        """
        Function that follows simple cycles to control the piston, based on live feedback from the
        sensors and inputs from the interface.
        """
        # At the beginning it is necessary to set some variables
        t_last = 0  # time of the last cycle
        inhale_end = time.time() - 1  # End of the last inhale
        self.cd["exhale_duration"] = 1
        self.cd["inhale_duration"] = 1
        #now = time.time()
        VCV_stage = 0
        PCV_stage = 0
        PSV_stage = 0
        emergency_contained = False

        # Gets the current volume and pressure before starting the cycles. If this doesn't work and 
        # takes too long, there is probably some problem with the sensors
        t_P, P = (None, None)
        t_V, V = (None, None)
        P_V_t_limit = 5
        first_P_V = time.time()
        while P == None and V == None:
            if not self.prs.empty():
                t_P, P = self.prs.get()
            if not self.vol.empty():
                t_V, V = self.vol.get()
            if time.time() - first_P_V > P_V_t_limit:
                print("Took too long to receive new values of P or V from the queues")
                # TODO Raise exception, error or return in this condition

        while True:
            # Gets the newest data and empties que queues. If there was no data, uses the values of 
            # pressure or volume that it already has
            if not self.prs.empty():
                t_P, P = self.prs.get()
                while not self.prs.empty():  # Emptying the queue, only the most recent info is used
                    dump = self.prs.get()

            if not self.vol.empty():
                t_V, V = self.vol.get()
                while not self.vol.empty():  # Emptying the queue, only the most recent info is used
                    dump = self.vol.get()

            # TODO Needs to be obtained from the interface or defined in a configuration by the user
            T_inh_max = 60. / self.gui["VCV_frequency_spb"].value() / 2

            if self.mode == 1:  # 'VCV'
                """
                This mode has 3 stages:
                0 - Wait
                1 - Inhale
                2 - Exhale
                """
                period = 60. / self.gui["VCV_frequency_spb"].value()
                T_inh_max = period / 2
                if VCV_stage == 0:  
                    self.piston.stop()
                    # If it's time for a new cycle, volume and pressure are within limits
                    if (time.time() - t_last > period
                        and V < self.gui["VCV_volume_spb"].value()
                        and P < self.gui["VCV_pressure_max_spb"].value()):
                        VCV_stage = 1
                        inhale_start = time.time()
                        # It is possible to calculate how long the last exhale took
                        self.cd["exhale_duration"] = inhale_start - inhale_end

                if VCV_stage == 1:
                    # Checks if the current pressure is above P_max
                    if P >= self.gui["VCV_pressure_max_spb"].value():
                        print("Pressure is too high during VCV cycle!")
                        self.piston.stop()
                    # Checks if it reached the maximum inhale t
                    elif time.time() - inhale_start >= T_inh_max:
                        print(f"VCV cycle is too long: {time.time() - inhale_start:.2f} s")
                        self.piston.stop()
                        VCV_stage = 2
                        inhale_end = time.time()
                    # Checks whether the piston reached the bottom
                    # TODO Define what happens in this case
                    elif self.piston.piston_at_bottom:
                        print("Reached max piston travel")
                        self.piston.stop()
                        VCV_stage = 2
                        inhale_end = time.time()
                    # Checks if the current volume is above target
                    # TODO Implement margin in options
                    elif V >= self.gui["VCV_volume_spb"].value() * 0.9:
                        print("Reached target volume")
                        self.piston.stop()
                        VCV_stage = 2 
                        inhale_end = time.time()
                    # if none of the previous limitations occured, may move the piston
                    else:
                        self.piston.pst_down()

                if VCV_stage == 2:
                    # While the piston still hasn't reached the top
                    # TODO Put timeout in piston raise time
                    if not self.piston.piston_at_top and time.time() - t_last > period:
                        self.piston.pst_up()
                    else:
                        self.piston.stop()
                        VCV_stage = 0
                        # Saves the last inhale start time to calculate when a new one should start
                        t_last = inhale_start
                        # It is possible to calculate how long the last inhale took
                        self.cd["inhale_duration"] = inhale_end - inhale_start

            elif self.mode == 2: # 'PCV'
                """
                This mode has 3 stages:
                0 - Wait
                1 - Inhale
                2 - Exhale
                """    
                period = 60. / self.gui["PCV_frequency_spb"].value()
                T_inh_max = period / 2
                if PCV_stage == 0:  
                    self.piston.stop()
                    # If it's time for a new cycle, volume and pressure are within limits
                    if (time.time() - t_last > period
                        and V < self.gui["PCV_volume_max_spb"].value()
                        and P < self.gui["PCV_pressure_spb"].value()):
                        PCV_stage = 1
                        inhale_start = time.time()
                        # It is possible to calculate how long the last exhale took
                        self.cd["exhale_duration"] = inhale_start - inhale_end

                if PCV_stage == 1:
                    # Checks if the current volume is above max
                    if V >= self.gui["PCV_volume_max_spb"].value():
                        print("Volume is too high during PCV cycle!")
                        self.piston.stop()
                    # Checks if it reached the maximum inhale t
                    elif time.time() - inhale_start >= T_inh_max:
                        print(f"PCV cycle is too long: {time.time() - inhale_start:.2f} s")
                        self.piston.stop()
                        PCV_stage = 2
                        inhale_end = time.time()
                    # Checks whether the piston reached the bottom
                    elif self.piston.piston_at_bottom:
                        print("Reached max piston travel")
                        self.piston.stop()
                        PCV_stage = 2
                        inhale_end = time.time()
                    # Checks if the current pressure is above target
                    elif P >= self.gui["PCV_pressure_spb"].value():
                        print("Reached target pressure")
                        self.piston.stop()
                        PCV_stage = 2 
                        inhale_end = time.time()
                    # if none of the previous limitations occured, may move the piston
                    else:
                        self.piston.pst_down()

                if PCV_stage == 2:
                    # While the piston still hasn't reached the top
                    if not self.piston.piston_at_top and time.time() - t_last > period:
                        self.piston.pst_up()
                    else:
                        self.piston.stop()
                        PCV_stage = 0
                        # Saves the last inhale start time to calculate when a new one should start
                        t_last = inhale_start
                        # It is possible to calculate how long the last inhale took
                        self.cd["inhale_duration"] = inhale_end - inhale_start

            elif self.mode == 3:  # 'PSV'
                """
                This mode has 3 stages:
                0 - Wait for inhale, P < threshold
                1 - Inhale
                2 - Exhale
                """
                if PSV_stage == 0:
                    self.piston.stop()
                    # If the pressure is below the threshold, time to inhale
                    if P < self.gui["PSV_sensitivity_spb"].value():
                        PSV_stage = 1
                        inhale_start = time.time()
                        # It is possible to calculate how long the last exhale took
                        self.cd["exhale_duration"] = inhale_start - inhale_end

                if PSV_stage == 1:
                    # Checks if the current pressure is close to P_target
                    if P >= self.gui["PSV_pressure_spb"].value():
                        print("Pressure reached target.")
                        self.piston.stop()
                        PSV_stage = 2
                        inhale_end = time.time()
                    elif self.piston.piston_at_bottom:
                        print("Reached max piston travel.")
                        self.piston.stop()
                        PSV_stage = 2
                        inhale_end = time.time()
                    # if none of the previous limitations occured, may move the piston
                    else:
                        self.piston.pst_down()
                        
                if PSV_stage == 2:
                    # While the piston still hasn't reached the top
                    if not self.piston.piston_at_top:
                        self.piston.pst_up()
                    else:
                        self.piston.stop()
                        PSV_stage = 0
                        # Saves the last inhale start time to calculate when a new one should start
                        t_last = inhale_start
                        # It is possible to calculate how long the last inhale took
                        self.cd["inhale_duration"] = inhale_end - inhale_start

            # Emergency mode
            elif self.mode == 4:  # 'Emergency'
                if not emergency_contained:
                    self.piston.emergency()
                    emergency_contained = True
                else:
                    self.piston.stop()


            else:  # Stop
                self.piston.stop()

            # Finds the indexes of data from the last cycle for flow and pressure
            # i_flw = np.where(time.time() - self.flw_data[0, :] < last_cycle_dur)[0]
            # i_prs = np.where(time.time() - self.prs_data[0, :] < last_cycle_dur)[0]
            
            # Sends the maximum pressure and volume in the last cycle to the interface
            self.cd["IE_ratio"] = self.cd["exhale_duration"] / self.cd["inhale_duration"]
            # Saving the data for the GUI update
            # self.cd["peak_pressure"] = peak_prs
            # self.cd["tidal_volume"] = peak_vol
            self.signal_cycle_data.emit(self.cd)

            time.sleep(0.05)

class InterfaceControl(QtCore.QObject):
    """
    This class processes the user inputs put in a queue by the Buttons class. It sends a signal to 
    the function that updates the interface, in the main thread, with a string corresponding to the
    input from the physical buttons
    """
    # These variables belong to the class
    signal_button = QtCore.pyqtSignal(str)

    def __init__(self):  # Inside init the variables belong to each instance
        super().__init__()
        # Classes that creates the instances of IO classes
        self.input_q = Queue()
        self.btns = buttons(self.input_q)

    def read_queue(self):
        key = None
        prev_key = [0, 0]
        # usually the difference between correct signals is in the range of 40-80 ms
        dt_min = 10E-3
        dt_max = 100E-3

        while(True):
            # If the queue is empty, skips to the next run
            if self.input_q.empty():
                time.sleep(0.05)
                continue

            # key gets from the queue a list with the name of the key and the time it was pressed
            key = self.input_q.get()
            self.input_q.task_done()

            # The non-rotary signals don't need special treatment, just emit them
            if key[0] in ["UP", "DOWN", "OK", "ROT"]:
                self.signal_button.emit(key[0])
                prev_key = key

            elif key[0] == "clk":
                # print("clk")
                dt = key[1] - prev_key[1]
                if prev_key[0] == "dt" and dt > dt_min and dt < dt_max:
                    print(f"Interval = {1000 * (key[1] - prev_key[1]):.3f} ms - CCW")
                    self.signal_button.emit("CCW")
                    prev_key = [0, 0]
                else:
                    prev_key = key

            elif key[0] == "dt":
                # print("dt")
                dt = key[1] - prev_key[1]
                if prev_key[0] == "clk" and dt > dt_min and dt < dt_max:
                    print(f"Interval = {1000 * (key[1] - prev_key[1]):.3f} ms - CW")
                    self.signal_button.emit("CW")
                    prev_key = [0, 0]
                else:
                    prev_key = key
            
            else:
                print("Key not configured")

    def read_queue_state(self):
        key = None
        prev_key = [0, 0]
        # usually the difference between correct signals is in the range of 40-80 ms
        dt_min = 5E-6
        dt_max = 150E-3
        state = "idle"
        last_clk = 0
        last_dt = 0

        while(True):
            # If the queue is empty, skips to the next run
            if self.input_q.empty():
                time.sleep(0.05)
                continue

            # key gets from the queue a list with the name of the key and the time it was pressed
            key = self.input_q.get()
            self.input_q.task_done()

            # First there is the decision tree to determine the current state after the input
            # The non-rotary signals don't need special treatment, just emit them
            if key[0] in ["UP", "DOWN", "OK", "ROT"]:
                self.signal_button.emit(key[0])
                state = "idle"

            elif state == "idle":
                if key[0] == "clk":
                    last_clk = key[1]
                    state = "got_clk_1"
                elif key[0] == "dt":
                    last_dt = key[1]
                    state = "got_dt_1"
                else:
                    pass

            elif state == "got_clk_1":
                if key[0] == "clk":
                    last_clk = key[1]
                    state = "got_clk_1"
                elif key[0] == "dt":
                    last_dt = key[1]
                    delta_t = last_dt - last_clk
                    if dt_min < delta_t < dt_max:
                        state = "idle"
                        print(f"Interval = {1000 * (delta_t):.3f} ms - CW")
                        self.signal_button.emit("CW")
                    else:
                        state = "got_dt_1"
                else:
                    pass

            elif state == "got_dt_1":
                if key[0] == "dt":
                    last_dt = key[1]
                    state = "got_dt_1"
                elif key[0] == "clk":
                    last_clk = key[1]
                    delta_t = last_clk - last_dt 
                    if dt_min < delta_t < dt_max:
                        state = "idle"
                        print(f"Interval = {1000 * (delta_t):.3f} ms - CCW")
                        self.signal_button.emit("CCW")
                    else:
                        state = "got_clk_1"
                else:
                    pass

class BuzBuzzer(QtCore.QObject):
    """
    Runs the buzzer in a separate thread, so that the main doesn't have to wait for the buzzer to 
    stop buzzing
    """
    def __init__(self):
        super().__init__()
        self.buzzer = buzzer()
        
    def short_buzz(self):
        self.buzzer.beep_for(0.05)

    def long_buzz(self):
        self.buzzer.beep_for(0.3)

class LEDControl(QtCore.QObject):
    """
    Runs in a separate thread, controls the LED
    """
    def __init__(self):
        super().__init__()
        self.led = led()
        
    def blink(self):
        self.led.light_for(0.3)

    def long_blink(self):
        self.led.light_for(1.0)

class DesignerMainWindow(QtWidgets.QMainWindow):
    """
    Class that corresponds to the programs main window. The init starts the interface and essential
    functions
    """
    def __init__(self, parent=None):
        super(DesignerMainWindow, self).__init__(parent)
        uic.loadUi(os.path.join(os.getcwd(), "ui", "GUI_mainWindow.ui"), self)
        
        # Creates the error_window instance
        self.error_window = StartupErrorWindow()

        # Reads the configuration file and create the corresponding variables
        self.conf = configparser.ConfigParser()
        self.conf.read('config_file.conf')

        # Creates the connections between each interface button and the correspondent functions
        self.connect_buttons()

        # Configuration of the default values on the interface
        self.start_interface()

        # Creates queues and lists to process the data read from the sensors
        self.create_data_structures()

        # Starting the graphs and threads
        self.create_graphs()
        self.create_threads()

        # Creates a timer to update the graphs at a specific frequency
        self.gui_timer = QtCore.QTimer()
        gui_update_frequency = 50  # FPS
        gui_update_period = 1000 / gui_update_frequency  # period in ms
        self.gui_timer.start(gui_update_period)
        self.gui_timer.timeout.connect(self.update_graphs)

        # Creates a timer to update the data at a specific frequency
        self.data_timer = QtCore.QTimer()
        data_update_frequency = 100  # Hz
        data_update_period = 1000 / data_update_frequency  # period in ms
        self.data_timer.start(data_update_period)
        self.data_timer.timeout.connect(self.process_data)

        # Creates a timer to read the ambient temperature, pressure and humidity periodically
        # self.gme_timer = QtCore.QTimer()
        # gme_update_period = 500  # period in ms
        # self.gme_timer.start(gme_update_period)
        # self.gme_timer.timeout.connect(self.get_bme)

    def connect_buttons(self):
        # Buttons
        # VCV tab
        self.VCV_start_btn.clicked.connect(lambda: self.modes(1))
        self.VCV_frequency_plus_btn.clicked.connect(
            lambda: self.change_value(self.VCV_frequency_spb, "+"))
        self.VCV_frequency_minus_btn.clicked.connect(
            lambda: self.change_value(self.VCV_frequency_spb, "-"))
        self.VCV_pressure_max_plus_btn.clicked.connect(
            lambda: self.change_value(self.VCV_pressure_max_spb, "+"))
        self.VCV_pressure_max_minus_btn.clicked.connect(
            lambda: self.change_value(self.VCV_pressure_max_spb, "-"))
        self.VCV_volume_plus_btn.clicked.connect(
            lambda: self.change_value(self.VCV_volume_spb, "+"))
        self.VCV_volume_minus_btn.clicked.connect(
            lambda: self.change_value(self.VCV_volume_spb, "-"))
        
        # PCV tab
        self.PCV_start_btn.clicked.connect(lambda: self.modes(2))
        self.PCV_frequency_plus_btn.clicked.connect(
            lambda: self.change_value(self.PCV_frequency_spb, "+"))
        self.PCV_frequency_minus_btn.clicked.connect(
            lambda: self.change_value(self.PCV_frequency_spb, "-"))
        self.PCV_pressure_plus_btn.clicked.connect(
            lambda: self.change_value(self.PCV_pressure_spb, "+"))
        self.PCV_pressure_minus_btn.clicked.connect(
            lambda: self.change_value(self.PCV_pressure_spb, "-"))
        self.PCV_volume_max_plus_btn.clicked.connect(
            lambda: self.change_value(self.PCV_volume_max_spb, "+"))
        self.PCV_volume_max_minus_btn.clicked.connect(
            lambda: self.change_value(self.PCV_volume_max_spb, "-"))

        # PSV tab
        self.PSV_start_btn.clicked.connect(lambda: self.modes(3))
        self.PSV_pressure_plus_btn.clicked.connect(
            lambda: self.change_value(self.PSV_pressure_spb, "+"))
        self.PSV_pressure_minus_btn.clicked.connect(
            lambda: self.change_value(self.PSV_pressure_spb, "-"))
        self.PSV_sensitivity_plus_btn.clicked.connect(
            lambda: self.change_value(self.PSV_sensitivity_spb, "+"))
        self.PSV_sensitivity_minus_btn.clicked.connect(
            lambda: self.change_value(self.PSV_sensitivity_spb, "-"))

        # Alarms tab
        self.al_PEEP_min_plus_btn.clicked.connect(
            lambda: self.change_value(self.al_PEEP_min_spb, "+"))
        self.al_PEEP_min_minus_btn.clicked.connect(
            lambda: self.change_value(self.al_PEEP_min_spb, "-"))
        self.al_apnea_min_plus_btn.clicked.connect(
            lambda: self.change_value(self.al_apnea_min_spb, "+"))
        self.al_apnea_min_minus_btn.clicked.connect(
            lambda: self.change_value(self.al_apnea_min_spb, "-"))
        self.al_flow_min_plus_btn.clicked.connect(
            lambda: self.change_value(self.al_flow_min_spb, "+"))
        self.al_flow_min_minus_btn.clicked.connect(
            lambda: self.change_value(self.al_flow_min_spb, "-"))
        self.al_frequency_min_plus_btn.clicked.connect(
            lambda: self.change_value(self.al_frequency_min_spb, "+"))
        self.al_frequency_min_minus_btn.clicked.connect(
            lambda: self.change_value(self.al_frequency_min_spb, "-"))
        self.al_paw_min_plus_btn.clicked.connect(
            lambda: self.change_value(self.al_paw_min_spb, "+"))
        self.al_paw_min_minus_btn.clicked.connect(
            lambda: self.change_value(self.al_paw_min_spb, "-"))
        self.al_plateau_pressure_min_plus_btn.clicked.connect(
            lambda: self.change_value(self.al_plateau_pressure_min_spb, "+"))
        self.al_plateau_pressure_min_minus_btn.clicked.connect(
            lambda: self.change_value(self.al_plateau_pressure_min_spb, "-"))
        self.al_tidal_volume_min_plus_btn.clicked.connect(
            lambda: self.change_value(self.al_tidal_volume_min_spb, "+"))
        self.al_tidal_volume_min_minus_btn.clicked.connect(
            lambda: self.change_value(self.al_tidal_volume_min_spb, "-"))
        self.al_volume_minute_min_plus_btn.clicked.connect(
            lambda: self.change_value(self.al_volume_minute_min_spb, "+"))
        self.al_volume_minute_min_minus_btn.clicked.connect(
            lambda: self.change_value(self.al_volume_minute_min_spb, "-"))
        self.al_PEEP_max_plus_btn.clicked.connect(
            lambda: self.change_value(self.al_PEEP_max_spb, "+"))
        self.al_PEEP_max_minus_btn.clicked.connect(
            lambda: self.change_value(self.al_PEEP_max_spb, "-"))
        self.al_apnea_max_plus_btn.clicked.connect(
            lambda: self.change_value(self.al_apnea_max_spb, "+"))
        self.al_apnea_max_minus_btn.clicked.connect(
            lambda: self.change_value(self.al_apnea_max_spb, "-"))
        self.al_flow_max_plus_btn.clicked.connect(
            lambda: self.change_value(self.al_flow_max_spb, "+"))
        self.al_flow_max_minus_btn.clicked.connect(
            lambda: self.change_value(self.al_flow_max_spb, "-"))
        self.al_frequency_max_plus_btn.clicked.connect(
            lambda: self.change_value(self.al_frequency_max_spb, "+"))
        self.al_frequency_max_minus_btn.clicked.connect(
            lambda: self.change_value(self.al_frequency_max_spb, "-"))
        self.al_paw_max_plus_btn.clicked.connect(
            lambda: self.change_value(self.al_paw_max_spb, "+"))
        self.al_paw_max_minus_btn.clicked.connect(
            lambda: self.change_value(self.al_paw_max_spb, "-"))
        self.al_plateau_pressure_max_plus_btn.clicked.connect(
            lambda: self.change_value(self.al_plateau_pressure_max_spb, "+"))
        self.al_plateau_pressure_max_minus_btn.clicked.connect(
            lambda: self.change_value(self.al_plateau_pressure_max_spb, "-"))
        self.al_tidal_volume_max_plus_btn.clicked.connect(
            lambda: self.change_value(self.al_tidal_volume_max_spb, "+"))
        self.al_tidal_volume_max_minus_btn.clicked.connect(
            lambda: self.change_value(self.al_tidal_volume_max_spb, "-"))
        self.al_volume_minute_max_plus_btn.clicked.connect(
            lambda: self.change_value(self.al_volume_minute_max_spb, "+"))
        self.al_volume_minute_max_minus_btn.clicked.connect(
            lambda: self.change_value(self.al_volume_minute_max_spb, "-"))

        # Configuration tab
        self.cfg_tare_btn.clicked.connect(lambda: self.set_tare_var(self.cfg_tare_spb.value()))
        self.cfg_tare_plus_btn.clicked.connect(lambda: self.change_value(self.cfg_tare_spb, "+"))
        self.cfg_tare_minus_btn.clicked.connect(lambda: self.change_value(self.cfg_tare_spb, "-"))

        # Bottom panel
        self.stop_btn.clicked.connect(lambda: self.modes(0))
        self.emerg_btn.clicked.connect(lambda: self.modes(4))
        self.inhale_pause_plus_btn.clicked.connect(
            lambda: self.change_value(self.inhale_pause_spb, "+"))
        self.inhale_pause_minus_btn.clicked.connect(
            lambda: self.change_value(self.inhale_pause_spb, "-"))
        self.inhale_pause_btn.clicked.connect(self.inhale_pause_control)
        
    def create_data_structures(self):
        """
        Creates the arrays and queues that will be used to control the piston and update the graphs
        """
        # Data storage arrays for time and measurement
        # Create the array of zeros and preallocating
        start_time = time.time()
        # The number of data points has to be optimized
        self.data_points = 5000
        # prs_data has three rows, 0 = time, 1 = pressure - tare, 2 = raw_pressure
        self.prs_data = np.zeros([3, self.data_points])
        self.prs_data[0, :] = start_time
        # This queue receives data from the sensors and puts it in the graphs and sends to the 
        # LifoQueue
        self.prs_q = Queue()
        # The lifo queue is created to send the data to the piston control thread. The piston
        # control will only read and use the last value, since only the most recent information
        # matters
        self.prs_lifo_q = LifoQueue()
        self.prs_tare = 0
        
        self.flw_data = np.zeros([3, self.data_points])
        self.flw_data[0, :] = start_time
        self.flw_q = Queue()
        self.flw_lifo_q = LifoQueue()  # Read comment on the lifoqueue above
        self.flw_tare = 0

        self.vol_lifo_q = LifoQueue()  # Read comment on the lifoqueue above
        self.vol_data = np.zeros([2, self.data_points])
        self.vol_data[0, :] = start_time
        
    def process_data(self):
        """
        This function receives data from the sensors via a queue, puts it into arrays for the graphs 
        and also puts it into a LifoQueue for the piston control function.
        """
        # If both queues are empty, just wait
        if self.prs_q.empty() and self.flw_q.empty():
            time.sleep(0.01)
            return

        # while the pressure queue is not empty, get the data and append
        new_prs_data = False
        while not self.prs_q.empty():
            t, pressure = self.prs_q.get()
            # Puts the same data on the queue that is read by the piston control thread
            self.prs_lifo_q.put([t, pressure])
            # Rolls the array
            self.prs_data = np.roll(self.prs_data, 1)
            # inserts the new data in the current i position
            self.prs_data[:, 0] = (t, pressure - self.prs_tare, pressure)
            new_prs_data = True
        if new_prs_data:
            # Signals that it got all the data from the queue and the sensors can continue to put
            # new data in the queue
            self.prs_q.task_done()

        # while the flow queue is not empty, get the data and append
        new_flw_data = False
        while not self.flw_q.empty():
            t, flow = self.flw_q.get()
            self.flw_lifo_q.put([t, flow])
            # Rolls the array
            self.flw_data = np.roll(self.flw_data, 1)
            # inserts the new data in the current i position
            self.flw_data[:, 0] = (t, flow - self.flw_tare, flow)
            new_flw_data = True
        if new_flw_data:
            # Signals that it got all the data from the queue and the sensors can continue to put
            # new data in the queue
            self.flw_q.task_done()

        # Calculating volume from the flow
        now = time.time()
        try:
            last_inhale = now - self.cd["inhale_instant"]
        except:
            last_inhale = 3
        # Gets the indexes of the data since the last breath
        i_li = np.where(now - self.flw_data[0, :] < last_inhale)[0]
        # volume = np.sum(self.flw_data[1, i_li]) / (60 * last_inhale)
        # Integrating the flow with trapz to get accurate results, considering the dt is not 
        # constant between samples. The time is negative, so needs to invert the signal
        volume = -integrate.trapz(self.flw_data[1, i_li], self.flw_data[0, i_li])
        # Converting the volume from L to mL and time from minute to second
        volume = 1000 * volume / 60
        # Calibration factor
        calib = 5
        volume = volume * calib
        self.vol_lifo_q.put([t, volume])
        self.vol_data = np.roll(self.vol_data, 1)
        self.vol_data[:, 0] = (t, volume)


        # Gets the tare of the pressure and flow sensors and updates the data 
        if self.get_tare and self.worker_piston.mode == 0:
            idxs_flw_tare = np.where(time.time() - self.flw_data[0, :] < self.tare_duration)[0]
            self.flw_tare = np.mean(self.flw_data[2, idxs_flw_tare])
            self.flw_data[1, :] = self.flw_data[2, :] - self.flw_tare
            idxs_prs_tare = np.where(time.time() - self.prs_data[0, :] < self.tare_duration)[0]
            self.prs_tare = np.mean(self.prs_data[2, idxs_prs_tare])
            self.prs_data[1, :] = self.prs_data[2, :] - self.prs_tare
            self.get_tare = False
        if self.get_tare and self.worker_piston.mode != 0:
            print("The respirator must be stopped before adjusting the tare.")
            self.get_tare = False

    def create_graphs(self):
        # Definitions to create the graphs
        # creates the pressure plot widget 
        self.prs_pw = pg.PlotWidget()
        # Adds the widget to the layout created in qtdesigner
        self.pressure_graph_VBox.addWidget(self.prs_pw)
        
        # Creates the flow plot widget 
        self.flw_pw = pg.PlotWidget()
        self.flow_graph_VBox.addWidget(self.flw_pw)
        
        # Creates the volume plot widget and adds a label to it
        self.vol_pw = pg.PlotWidget()
        self.volume_graph_VBox.addWidget(self.vol_pw)
        self.vol_lbl = pg.TextItem()
        self.vol_pw.addItem(self.vol_lbl, ignoreBounds=True) 
        
        # Plot settings
        bg_color = self.conf["Graph"].get("background_color")
        pen_color = self.conf["Graph"].get("line_color")
        font_size = self.conf["Graph"].get("font_size")
        plot_pen = pg.mkPen(color=pen_color, width=3)
        # For some reason the color definition is different inside "styles"
        # Titles use 'size', while labels use 'font_size'
        self.lbl_style = {'color': pen_color, 'font-size': font_size}
        self.ttl_style = {'color': pen_color, 'size': font_size} 
        self.time_range = [self.conf["Graph"].getfloat("time_range_min"),
                           self.conf["Graph"].getfloat("time_range_max")]
        self.padding = 0.01

        # Configuration of the pressure plot
        self.prs_pw.setBackground(bg_color) # Set the background color
        self.prs_pw.setMenuEnabled(False) # Disables the menu
        # The title size doesn't change with the style
        self.prs_pw.setTitle(self.conf["Graph"].get("title_pressure"), **self.ttl_style)
        self.prs_pw.showGrid(x=True, y=True)
        self.prs_pw.setLabel(axis='bottom', text='Tempo (s)', **self.lbl_style)
        self.prs_pw.setXRange(self.time_range[0], self.time_range[1], self.padding)
        self.prs_graph = self.prs_pw.plot(self.prs_data[0, :], self.prs_data[1, :], pen=plot_pen)
        
        # Configuration of the flow plot
        self.flw_pw.setBackground(bg_color) # Set the background color
        self.flw_pw.setMenuEnabled(False) # Disables the menu
        # The title size doesn't change with the style
        self.flw_pw.setTitle(self.conf["Graph"].get("title_flow"), **self.ttl_style)
        self.flw_pw.showGrid(x=True, y=True)
        self.flw_pw.setXRange(self.time_range[0], self.time_range[1], self.padding)
        self.flw_graph = self.flw_pw.plot(self.flw_data[0, :], self.flw_data[1, :], pen=plot_pen)
        
        # Configuration of the volume plot
        self.vol_pw.setBackground(bg_color) # Set the background color
        self.vol_pw.setMenuEnabled(False) # Disables the menu
        # The title size doesn't change with the style
        self.vol_pw.setTitle(self.conf["Graph"].get("title_volume"), **self.ttl_style)
        self.vol_pw.showGrid(x=True, y=True)
        self.vol_pw.setXRange(self.time_range[0], self.time_range[1], self.padding)
        self.vol_graph = self.vol_pw.plot(self.vol_data[0, :], self.vol_data[1, :], pen=plot_pen)
        # Adding text inside the graph
        # self.vol_lbl.setText("TEST")
        # Anchor is the position to which the text will refer in setPos
        # self.vol_lbl.setAnchor((1, 1))
        # This is the position of the anchor, in the coordinates of the graph
        # self.vol_lbl.setPos(0.0, 0.0)
        self.run_counter = 0
        self.get_tare = False

    def create_threads(self):
        """
        Creating the threads that will update the GUI
        Must use .self so that the garbage collection doesn't kill the threads
        """
        # Dictionary with the interface items that will be passed to the functions
        gui_items = {"VCV_frequency_spb":self.VCV_frequency_spb,
                     "VCV_volume_spb":self.VCV_volume_spb,
                     "VCV_pressure_max_spb":self.VCV_pressure_max_spb,
                     "PCV_frequency_spb":self.PCV_frequency_spb,
                     "PCV_pressure_spb":self.PCV_pressure_spb,
                     "PCV_volume_max_spb":self.PCV_volume_max_spb,
                     "PSV_pressure_spb":self.PSV_pressure_spb,
                     "PSV_sensitivity_spb":self.PSV_sensitivity_spb,
                     "al_PEEP_min_spb":self.al_PEEP_min_spb,
                     "al_apnea_min_spb":self.al_apnea_min_spb,
                     "al_flow_min_spb":self.al_flow_min_spb,
                     "al_frequency_min_spb":self.al_frequency_min_spb,
                     "al_paw_min_spb":self.al_paw_min_spb,
                     "al_plateau_pressure_min_spb":self.al_plateau_pressure_min_spb,
                     "al_tidal_volume_min_spb":self.al_tidal_volume_min_spb,
                     "al_volume_minute_min_spb":self.al_volume_minute_min_spb,
                     "al_PEEP_max_spb":self.al_PEEP_max_spb,
                     "al_apnea_max_spb":self.al_apnea_max_spb,
                     "al_flow_max_spb":self.al_flow_max_spb,
                     "al_frequency_max_spb":self.al_frequency_max_spb,
                     "al_paw_max_spb":self.al_paw_max_spb,
                     "al_plateau_pressure_max_spb":self.al_plateau_pressure_max_spb,
                     "al_tidal_volume_max_spb":self.al_tidal_volume_max_spb,
                     "al_volume_minute_max_spb":self.al_volume_minute_max_spb,
                     "inhale_pause_spb":self.inhale_pause_spb}

        # Sensors thread
        self.worker_sensors = ReadSensors(self.flw_q, self.prs_q)
        self.thread_sensors = QtCore.QThread()
        self.worker_sensors.moveToThread(self.thread_sensors)
        # Passing the arrays to the thread
        # self.worker_sensors.signal_sensors.connect(self.update_sensors)
        self.thread_sensors.started.connect(self.worker_sensors.work)
        self.thread_sensors.start()
        
        # Piston control thread
        # self.worker_piston = ControlPiston(self.piston, gui_items, mode=0)
        self.worker_piston = ControlPiston(gui_items, self.flw_lifo_q, self.prs_lifo_q,
                                           self.vol_lifo_q, mode=0)
        self.thread_piston = QtCore.QThread()
        self.worker_piston.moveToThread(self.thread_piston)
        # Another way of passing variables to threads
        # This is done again at every loop where flow, pressure and volume are updated
        # This is not thread safe, the correct way to pass data to threads is using queues
        # self.worker_piston.flw_data = self.flw_data
        # self.worker_piston.vol_data = self.vol_data
        # self.worker_piston.prs_data = self.prs_data
        self.worker_piston.signal_cycle_data.connect(self.update_interface)
        self.worker_piston.signal_startup_error.connect(self.error_window.show)
        self.error_window.signal_retry_startup.connect(self.worker_piston.startup)
        self.worker_piston.signal_get_tare.connect(self.set_tare_var)
        self.thread_piston.started.connect(self.worker_piston.startup)
        self.thread_piston.start()

        # Buttons control thread
        self.worker_buttons = InterfaceControl()
        self.thread_buttons = QtCore.QThread()
        self.worker_buttons.moveToThread(self.thread_buttons)
        self.worker_buttons.signal_button.connect(self.spinbox_control)
        self.thread_buttons.started.connect(self.worker_buttons.read_queue_state)
        self.thread_buttons.start()

        # Buzzer thread
        self.worker_buzzer = BuzBuzzer()
        self.thread_buzzer = QtCore.QThread()
        self.worker_buzzer.moveToThread(self.thread_buzzer)
        # led thread
        self.worker_led = LEDControl()
        self.thread_led = QtCore.QThread()
        self.worker_led.moveToThread(self.thread_led)

    def set_tare_var(self, tare_duration):
        """
        This function is used to set the variable "get_tare" that is accessed in "update graphs" to
        calculate the tare of the pressure and flow. The tare duration corresponds to the time 
        interval used to obtain the mean value and consider it the tare.
        """
        self.tare_duration = tare_duration
        self.get_tare = True
        # beep and blink after 100 ms
        if self.cfg_beep_chkBox.isChecked():
            QtCore.QTimer.singleShot(100, lambda: self.worker_buzzer.long_buzz())
        if self.cfg_led_chkBox.isChecked():
            QtCore.QTimer.singleShot(100, lambda: self.worker_led.blink())

    # try to use this funtion without having to create a new instance every cycle
    def update_graphs(self):
        """
        This function updates the graphs with data from the arrays
        """
        profile_time = False
        if profile_time:
            start_time = time.time()

        # Update the graph data with data only within the chosen time_range
        now = time.time()
        i_tr_prs = np.where(now - self.prs_data[0, :] < 
                            self.time_range[1] - self.time_range[0])[0]
        self.prs_graph.setData(self.prs_data[0, i_tr_prs] - now, self.prs_data[1, i_tr_prs])
        # Updates the graph title
        self.prs_pw.setTitle(f"Pressão: {self.prs_data[1, 0]:.1f} cmH2O", **self.ttl_style)

        if profile_time == True:
            time_at_pressure = time.time()
            print(f"Until pressure graph: {time_at_pressure - start_time:.4f} s")
        
        # Update the graph data with data only within the chosen time_range
        now = time.time()
        i_tr_flw = np.where(now - self.flw_data[0, :] < 
                            self.time_range[1] - self.time_range[0])[0]
        self.flw_pw.setTitle(f"Fluxo: {self.flw_data[1, 0]:.1f} l/min", **self.ttl_style)
        self.flw_graph.setData(self.flw_data[0, i_tr_flw] - now, self.flw_data[1, i_tr_flw])

        if profile_time == True:
            time_at_flow = time.time()
            print(f"Until flow graph: {time_at_flow - start_time:.4f} s")

        i_tr_vol = np.where(now - self.vol_data[0, :] < 
                    self.time_range[1] - self.time_range[0])[0]
        self.vol_pw.setTitle(f"Volume: {self.vol_data[1, 0]:.0f} ml", **self.ttl_style)
        self.vol_graph.setData(self.vol_data[0, i_tr_vol] - now, self.vol_data[1, i_tr_vol])

        if profile_time == True:
            time_at_volume = time.time()
            print(f"After the volume graph: {time_at_volume - time_at_flow:.4f} s")

        # Adjust the Y range every N measurements
        # Manually adjusting by calculating the max and min with numpy is faster than autoscale on 
        # the graph. Also calculates FPS
        N = 20
        if self.run_counter % N == 0:
            # definition of the minimum acceptable range for the volume
            min_range_vol = [-5, 50]
            # Tries to get the max and min from each data set 
            try:
                range_vol = [np.min(self.vol_data[1, i_tr_vol]), np.max(self.vol_data[1, i_tr_vol])]
             # Adjusts the minimum and maximum, if the measured values are outside the minimum range
                self.vol_pw.setYRange(np.min([range_vol[0], min_range_vol[0]]), 
                                      np.max([range_vol[1], min_range_vol[1]]))
            except:
                pass
            min_range_prs = [-0.2, 5]
            try:
                range_prs = [np.min(self.prs_data[1, i_tr_prs]), np.max(self.prs_data[1, i_tr_prs])]
                self.prs_pw.setYRange(np.min([range_prs[0], min_range_prs[0]]), 
                                    np.max([range_prs[1], min_range_prs[1]]))
            except:
                pass

            min_range_flw = [-0.1, 1]
            try:
                range_flw = [np.min(self.flw_data[1, i_tr_flw]), np.max(self.flw_data[1, i_tr_flw])]
                self.flw_pw.setYRange(np.min([range_flw[0], min_range_flw[0]]), 
                                    np.max([range_flw[1], min_range_flw[1]]))
            except:
                pass
            mean_pts = 50
            try:
                FPS = np.nan_to_num(1.0 / np.mean(self.vol_data[0, 0:mean_pts] - 
                                    self.vol_data[0, 1:1+mean_pts]))
            except:
                FPS = 0
            self.fps_lbl.setText(f"FPS: {FPS:.2f}")
            self.run_counter = 0
        self.run_counter += 1

    def exit(self):
        sys.exit()
    
    def start_interface(self):
        """
        This function fills the interface with the proper values for each of the properties at start
        up
        """
        # VCV Tab
        self.VCV_frequency_spb.setValue(self.conf["VCV"].getfloat("frequency"))
        self.VCV_volume_spb.setValue(self.conf["VCV"].getfloat("volume"))
        self.VCV_pressure_max_spb.setValue(self.conf["VCV"].getfloat("pressure_max"))
        # PCV Tab
        self.PCV_frequency_spb.setValue(self.conf["PCV"].getfloat("frequency"))
        self.PCV_pressure_spb.setValue(self.conf["PCV"].getfloat("pressure"))
        self.PCV_volume_max_spb.setValue(self.conf["PCV"].getfloat("volume_max"))
        # PSV Tab
        self.PSV_pressure_spb.setValue(self.conf["PSV"].getfloat("pressure"))
        self.PSV_sensitivity_spb.setValue(self.conf["PSV"].getfloat("sensitivity"))
        # Alarms Tab
        self.al_tidal_volume_min_spb.setValue(self.conf["Alarms"].getfloat("tidal_volume_min"))
        self.al_tidal_volume_max_spb.setValue(self.conf["Alarms"].getfloat("tidal_volume_max"))
        self.al_tidal_volume_chkBox.setChecked(self.conf["Alarms"].getboolean("tidal_volume_on"))
        self.al_volume_minute_min_spb.setValue(self.conf["Alarms"].getfloat("volume_minute_min"))
        self.al_volume_minute_max_spb.setValue(self.conf["Alarms"].getfloat("volume_minute_max"))
        self.al_volume_minute_chkBox.setChecked(self.conf["Alarms"].getboolean("volume_minute_on"))
        self.al_flow_min_spb.setValue(self.conf["Alarms"].getfloat("flow_min"))
        self.al_flow_max_spb.setValue(self.conf["Alarms"].getfloat("flow_max"))
        self.al_flow_chkBox.setChecked(self.conf["Alarms"].getboolean("flow_on"))
        self.al_paw_min_spb.setValue(self.conf["Alarms"].getfloat("paw_min"))
        self.al_paw_max_spb.setValue(self.conf["Alarms"].getfloat("paw_max"))
        self.al_paw_chkBox.setChecked(self.conf["Alarms"].getboolean("paw_on"))
        self.al_plateau_pressure_min_spb.setValue(
            self.conf["Alarms"].getfloat("plateau_pressure_min"))
        self.al_plateau_pressure_max_spb.setValue(
            self.conf["Alarms"].getfloat("plateau_pressure_max"))
        self.al_plateau_pressure_chkBox.setChecked(
            self.conf["Alarms"].getboolean("plateau_pressure_on"))
        self.al_PEEP_min_spb.setValue(self.conf["Alarms"].getfloat("PEEP_min"))
        self.al_PEEP_max_spb.setValue(self.conf["Alarms"].getfloat("PEEP_max"))
        self.al_PEEP_chkBox.setChecked(self.conf["Alarms"].getboolean("PEEP_on"))
        self.al_frequency_min_spb.setValue(self.conf["Alarms"].getfloat("frequency_min"))
        self.al_frequency_max_spb.setValue(self.conf["Alarms"].getfloat("frequency_max"))
        self.al_frequency_chkBox.setChecked(self.conf["Alarms"].getboolean("frequency_on"))
        self.al_apnea_min_spb.setValue(self.conf["Alarms"].getfloat("apnea_min"))
        self.al_apnea_max_spb.setValue(self.conf["Alarms"].getfloat("apnea_max"))
        self.al_apnea_chkBox.setChecked(self.conf["Alarms"].getboolean("apnea_on"))
        # Config Tab
        self.cfg_tare_spb.setValue(self.conf['Config'].getfloat("tare"))

        # Always shown elements
        self.inhale_time_val.setText("0,0 s")
        self.exhale_time_val.setText("0,0 s")
        self.IE_ratio_val.setText("1:1")
        self.peak_pressure_val.setText("0,0 cm H2O")
        self.tidal_volume_val.setText("0 ml")
        self.inhale_pause_spb.setValue(self.conf["Panel"].getfloat("inhale_pause"))
        self.stop_btn.setEnabled(False)
        self.emerg_btn.setEnabled(True)

    def spinbox_control(self, action):
        """
        Finds the active (in focus, last clicked) spinbox and increases or decreases its value,
        based on the button that was pressed
        """
        # Gets the current tab, so that it can check which of the spinboxes currently shown is
        # in focus, or choose one to be in focus 
        c_tab = self.tabWidget.currentIndex()
        tab_content = {0:[self.VCV_frequency_spb,
                          self.VCV_volume_spb,
                          self.VCV_pressure_max_spb],
                       1:[self.PCV_frequency_spb,
                          self.PCV_pressure_spb,
                          self.PCV_volume_max_spb],
                       2:[self.PSV_pressure_spb,
                          self.PSV_sensitivity_spb],
                       3:[self.al_tidal_volume_min_spb,
                          self.al_tidal_volume_max_spb,
                          self.al_volume_minute_min_spb,
                          self.al_volume_minute_max_spb,
                          self.al_flow_min_spb,
                          self.al_flow_max_spb,
                          self.al_paw_min_spb,
                          self.al_paw_max_spb,
                          self.al_plateau_pressure_min_spb,
                          self.al_plateau_pressure_max_spb,
                          self.al_PEEP_min_spb,
                          self.al_PEEP_max_spb,
                          self.al_frequency_min_spb,
                          self.al_frequency_max_spb,
                          self.al_apnea_min_spb,
                          self.al_apnea_max_spb],
                       4:[self.cfg_tare_spb]}
        # By default will choose the first spinbox on the current tab.
        current_spb = tab_content[c_tab][0]
        # Going through the spinboxes of the current tab and checking whether they have the focus
        # The inhale_pause_spb is a special case, because it's not in any tab, but in the bottom bar
        for item in tab_content[c_tab], self.inhale_pause_spb:
            if item.hasFocus():
                current_spb = item
                continue

        if action == "UP":
            if self.cfg_beep_chkBox.isChecked():
                QtCore.QTimer.singleShot(1, lambda: self.worker_buzzer.short_buzz())
            if self.cfg_led_chkBox.isChecked():
                QtCore.QTimer.singleShot(1, lambda: self.worker_led.blink())
            self.change_value(current_spb, "+")
        elif action == "DOWN":
            if self.cfg_beep_chkBox.isChecked():
                QtCore.QTimer.singleShot(1, lambda: self.worker_buzzer.short_buzz())
            if self.cfg_led_chkBox.isChecked():
                QtCore.QTimer.singleShot(1, lambda: self.worker_led.blink())
            self.change_value(current_spb, "-")
        elif action == "OK":
            if self.cfg_beep_chkBox.isChecked():
                QtCore.QTimer.singleShot(1, lambda: self.worker_buzzer.short_buzz())
            if self.cfg_led_chkBox.isChecked():
                QtCore.QTimer.singleShot(1, lambda: self.worker_led.blink())
            # Put the next spinbox in focus
            nxt = tab_content[c_tab][(tab_content[c_tab].index(current_spb) + 1) % 
                                     len(tab_content[c_tab])]
            nxt.setFocus()
        elif action == "ROT":
            if self.cfg_beep_chkBox.isChecked():
                QtCore.QTimer.singleShot(1, lambda: self.worker_buzzer.short_buzz())
            if self.cfg_led_chkBox.isChecked():
                QtCore.QTimer.singleShot(1, lambda: self.worker_led.blink())
            # Put the next spinbox in focus
            nxt = tab_content[c_tab][(tab_content[c_tab].index(current_spb) + 1) %
                                     len(tab_content[c_tab])]
            nxt.setFocus()
        elif action == "CW":
            self.change_value(current_spb, "+")
        elif action == "CCW":
            self.change_value(current_spb, "-")
        else:
            print("I just don't get it man")

    def change_value(self, spinbox, action):
        """
        Updates the value of the spinboxes when they're clicked or modified.
        The button is connected to a lambda: change_value(spinbox, "+" or "-")
        To get the increment from the conf file based on the spinbox name, it is necessary to parse:
        "VCV_inhale_pause_spb" -> "VCV" is the tab name can be equal or not to the conf file section
        "inhale_pause_spb" -> spinbox name, stripped of the "spb" is the value in the conf file
        "inhale_pause_inc" -> the increment key in the conf file, after "inc" was appended.
        Each spinbox may have a different increment value, easily changed in the conf file.
        """
        # Gets the name of the spinbox and finds from which tab it belongs
        spb_name = spinbox.objectName()
        # Parsing to get the index of the "_" separators from the beginning (tab)
        tab_sep = spb_name.find("_") 
        tab_code = spb_name[0:tab_sep]
        # If the three first letters of the spinbox name correspond to the modes' name, the 
        # section has the same name, therefore it is only necessary to copy. The alarms tab
        # is different
        # Depending on the section, it is necessary to remove a few characters from the end of the 
        # string. Either remove "spb" or "min_spb" or "max_spb"
        if tab_code in ["VCV", "PSV", "PCV"]:
            conf_section = tab_code
            remove_chars = 3
        elif tab_code == "al":
            conf_section = "Alarms"
            remove_chars = 7
        elif tab_code == "cfg":
            conf_section = "Config"
            remove_chars = 3
        # It should never reach the "else", but still here it is, if something fails
        else:
            print("Tab code " + tab_code + " is not valid")
            return
        # Gets the "pure" name of the spb, to which "inc" will be appended in order to access it in
        # the conf file
        spb_no_suffix = spb_name[tab_sep+1:-remove_chars]
        # gets the increment as a float number from the appropriate section and spinbox
        increment = self.conf[conf_section].getfloat(spb_no_suffix + "inc")
        # Sets the single step property of the spinbox to correspond to the increment
        spinbox.setSingleStep(increment)
        # Adjusts the precision based on the increment's order of magnitude
        for i, limit in enumerate([1, 0.1, 0.01, 0.001, 0.0001, 0.00001]):
            if increment < limit:
                continue
            spinbox.setDecimals(i)
            break
        # Depending on the desired action, increases or deccreases the current spinbox value
        if action == "-":
            spinbox.setValue(spinbox.value() - increment)
        else:
            spinbox.setValue(spinbox.value() + increment)

    def modes(self, mode):
        """
        Defines the current mode and based on the user's selection
        Mode 1 = VCV
        Mode 2 = PCV
        Mode 3 = PSV
        Mode 4 = Emergency
        Mode 0 or else = Stop everything
        """
        # Sends the update to the piston worker
        self.worker_piston.mode = mode
        if mode == 1:  # 'VCV'
            self.VCV_start_btn.setEnabled(False)
            self.PCV_start_btn.setEnabled(True)
            self.PSV_start_btn.setEnabled(True)
            self.stop_btn.setEnabled(True)
        elif mode == 2:  # 'PCV'
            self.VCV_start_btn.setEnabled(True)
            self.PCV_start_btn.setEnabled(False)
            self.PSV_start_btn.setEnabled(True)
            self.stop_btn.setEnabled(True)
        elif mode == 3:  # 'PSV'
            self.VCV_start_btn.setEnabled(True)
            self.PCV_start_btn.setEnabled(True)
            self.PSV_start_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
        elif mode == 4:  # 'Emergency'
            print('Emergency')
            self.VCV_start_btn.setEnabled(True)
            self.PCV_start_btn.setEnabled(True)
            self.PSV_start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
        else:  # STOP
            self.VCV_start_btn.setEnabled(True)
            self.PCV_start_btn.setEnabled(True)
            self.PSV_start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
    
    def inhale_pause_control(self):
        """
        If the user pressed the inhale pause button, it changes the respective value at the
        controller function
        """
        self.worker_piston.pause = True

    def update_interface(self, cd):
        """
        Receives information about the last cycle in the form of a dict and updates the GUI based on
        that.
        """
        # Creating a self.cd so that other methods can access it
        self.cd = cd
        self.inhale_time_val.setText(f"{self.cd['inhale_duration']:.1f} s")
        self.exhale_time_val.setText(f"{self.cd['exhale_duration']:.1f} s")
        self.IE_ratio_val.setText(f"1:{self.cd['IE_ratio']:.1f}")
        self.peak_pressure_val.setText(f"{self.cd['peak_pressure']:.2f} cmH2O")
        self.tidal_volume_val.setText(f"{self.cd['tidal_volume']:.0f} ml")
        self.tidal_volume_val.setText(f"{self.cd['tidal_volume']:.0f} ml")

    # def get_bme(self):
    #     sensor = bme()
    #     sensor.get_current()

class AboutWindow(QtWidgets.QMainWindow):
    """Customization for Qt Designer created window"""
    def __init__(self, parent=None):
        super(AboutWindow, self).__init__(parent)
        uic.loadUi(os.path.join(os.getcwd(), "ui", "GUI_sobre.ui"), self)

class StartupErrorWindow(QtWidgets.QMainWindow):
    signal_retry_startup = QtCore.pyqtSignal(bool)
    """Customization for Qt Designer created window"""
    def __init__(self, parent=None):
        super(StartupErrorWindow, self).__init__(parent)
        uic.loadUi(os.path.join(os.getcwd(), "ui", "GUI_startup_error.ui"), self)
        self.startup_error_btn.clicked.connect(self.try_restart)

    def try_restart(self):
        self.signal_retry_startup.emit(True)
        self.close()

if __name__ == "__main__":
    # %% Calling the main window
    app = QtWidgets.QApplication(sys.argv)
    dmw = DesignerMainWindow()
    dmw.showFullScreen()
    sys.exit(app.exec_())