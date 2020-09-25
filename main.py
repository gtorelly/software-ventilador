"""
Main function
"""
from ui.Ui_GUI_mainWindow import Ui_Respirador
from ui.Ui_GUI_sobre import Ui_Sobre
import sys
from PyQt5 import QtWidgets,  QtCore
import time
# Imports to create the live graphs
import numpy as np
import pyqtgraph as pg

# Hardware control files
from hw_adc_pressure import pressure_gauge
from hw_flowmeter import flowmeter
from hw_piston import pneumatic_piston

UI_UPDATE_FREQUENCY = 15 # Hz
UI_UPDATE_PERIOD = 1 / UI_UPDATE_FREQUENCY

class ReadSensors(QtCore.QObject):
    """
    This class is used to create a thread that reads information from the sensor continuously.
    The signal "signal_sensors" emits a list that is read by the function "update_sensors". The list
    contains flow, volume and pressure.
    TODO Get the period of the respiration more accurately, in order to better calculate the volume
    Alternatively, create a separate function that contains the information about the last period
    """
    signal_sensors = QtCore.pyqtSignal(list)
    
    def __init__(self, meter, gauge, gui):
        super().__init__()
        self.meter = meter
        self.gauge = gauge
        self.gui = gui
        
    def work(self):  # This function is what the new thread will execute
        while(True):
            # TODO Acertar os timings
            start = time.time()
            period = 4 # 60. / self.gui["VCV_frequency_dSpinBox"].value()
            instant = 0.4
            flow = self.meter.calc_flow(instant)
            # flow_time = time.time()
            # print(f"Runtime - calc_flow: {flow_time - start:.4f} s")
            volume = self.meter.calc_volume(period)
            # volume_time = time.time()
            # print(f"Runtime - calc_volume: {volume_time - flow_time:.4f} s")
            pressure = self.gauge.read_pressure()
            # pressure_time = time.time()
            # print(f"Runtime - read_pressure: {pressure_time - volume_time:.4f} s")
            runtime = time.time() - start
            # print(f"Runtime - total: {runtime:.4f} s")
            if runtime < UI_UPDATE_PERIOD:
                time.sleep(UI_UPDATE_PERIOD - runtime)
            self.signal_sensors.emit([flow, volume, pressure])

            
class ControlPiston(QtCore.QObject):
    signal_piston = QtCore.pyqtSignal(bool)
    
    def __init__(self, piston, gui):
        super().__init__()
        # receives the piston instance from the call of this worker in the main window
        # assigns the instance to another with the same name.
        self.piston = piston
        self.stop = False
        self.gui = gui
        self.mode = 0

        # Variables to store the current position and next direction of the piston movement
        self.pst_pos = None
        # Starts going down
        self.pst_dir = 0

        self.start_up()
        self.controller()

    def start_up(self):
        """
        Starts the cycle until the piston moves to a known position
        """
        to = 3  # Timeout
        start_up_cycles = 0
        limit = 20
        while self.pst_pos == None:
            if self.pst_dir == 1:
                self.pst_pos = self.piston.piston_up(to)
                self.pst_dir = 0
            else:
                self.pst_pos = self.piston.piston_down(to)
                self.pst_dir = 1
            start_up_cycles += 1
            if start_up_cycles > limit:
                print("There is a problem at startup, check compressed air")
        print(f"start_up_cycles: {start_up_cycles}")

    def controller(self):
        """
        This function intends to replace all the separate functions that were developed to control
        the pneumatic piston. By controlling the behavior of the piston at each step, a better
        integration between the modes and the information that is shown on the screen may be
        achieved.
        When I started to write this function, there was no unified way to determine the stats on
        the last cycle or to synchronize the data shown on the interface between modes.
        A lot of the code was repeated between modes. By aggregating everything in one function I
        hope to reduce the length of the code and keep this thread running with piston actions
        based on the interface in a simpler way.
        """
        t_wait_up = 0
        t_wait_down = 0
        first_cycle = True
        # Initializing the timers
        up_cycle_start = time.time()
        down_cycle_start = time.time()
        up_cycle_end = time.time()
        down_cycle_end = time.time()

        # 5% margin of error for the target values
        margin = 0.05

        # Starts the automatic loop
        while True:
            # Stores the time at the beginning of a cycle or semi-cycle
            if self.pst_dir == 1:
                up_cycle_start = time.time()
            else:
                down_cycle_start = time.time()
            last_cycle_dur = up_cycle_end - down_cycle_start

            # Uses flow for the calculation of the indexes, but flow, volume and pressure are
            # stored simultaneously, so it shouldn't make a difference
            idxs_last_cycle = np.where(time.time() - self.flw_data[0, :] < last_cycle_dur)[0]

            if self.mode == 1: # 'VCV'
                # Reading the relevant values from the interface
                tgt_per = 60. / self.gui["VCV_frequency_dSpinBox"].value()
                max_flw = self.gui["VCV_flow_dSpinBox"].value()
                tgt_vol = self.gui["VCV_volume_dSpinBox"].value()

                # On the first cycle, use standard values
                if first_cycle:
                    t_move_down = tgt_per / 4.
                    first_cycle = False
                    # Defines how long each cycle takes, enabling the volume control
                    t_move_up = target_per - t_move_down
                    break

                # Calculate the peak volume and flow for the last cycle
                peak_flw = np.max(self.flw_data[1, idxs_last_cycle])
                print(f"Peak flow: {peak_flw:.1f}")
                peak_vol = np.max(self.vol_data[1, idxs_last_cycle])
                print(f"Peak volume: {peak_vol:.1f}")

                if peak_flw > max_flw:
                    print("Flow is too high, close valve")
                    
                if peak_vol > target_vol * (1.0 + margin):
                    t_move_down = t_move_down * target_vol / peak_vol
                    print(f"Volume is too high, reducing t_move_down to {t_move_down:.2f}")
                if peak_vol < target_vol * (1.0 - margin):
                    new_t_move_down = t_move_down * target_vol / peak_vol
                    if new_t_move_down > target_per * 0.5:
                        t_move_down = target_per * 0.5
                        print(f"t_move_down is too long, limited at 50% cycle: {t_move_down:.2f}")
                        
                    else:
                        t_move_down = new_down_duration
                        print(f"Volume is too low, increasing t_move_down to {t_move_down:.2f}")

                # Defines how long each cycle takes, enabling the volume control
                t_move_up = target_per - t_move_down
                t_wait_up = 0
                t_wait_down = 0
                print('VCV')

            elif self.mode == 2:  # 'PCV'
                print('PCV')

            elif self.mode == 3:  # 'PSV'
                print('PSV')

            elif self.mode == 4:  # 'Manual Auto'
                print('Manual')

            else:  # STOP
                print('STOP')
                # Does not perform the movements below, just waits and continues to the next cycle
                time.sleep(0.5)
                continue

            # After the configuration of the cycle times, perform the movement
            if self.mode in [1, 2, 3, 4]:
                move_start = time.time()
                if piston_direction == 0:
                    # the movement will last a maximum of "t_move_down"
                    self.piston.piston_down(t_move_down)
                    # Waits until t_move_down is completed, in case the piston descended faster
                    move_down_dur = time.time() - move_start
                    if move_down_dur < t_move_down:
                        time.sleep(t_move_down - move_down_dur)
                    # if the piston needs to wait in the down position
                    if t_wait_down > 0:
                        time.sleep(t_wait_down)
                    # t_end_move_down = time.time()
                    piston_direction = 1
                    down_cycle_end = time.time()
                
                else:
                    self.piston.piston_up(t_move_up)
                    move_up_dur = time.time() - move_start
                    # If this movement was faster than the expected duration, wait
                    if move_up_dur < t_move_up:
                        time.sleep(t_move_up - move_up_dur)
                    # if the piston needs to wait in the up position
                    if t_wait_up > 0:
                        time.sleep(t_wait_up)
                    piston_direction = 0
                    up_cycle_end = time.time()

        
    def piston_lower(self):
        """
        Manual command to lower the piston
        """
        if not self.piston.piston_down(5):
            print("Failed to lower piston: Timeout")
        
    def piston_raise(self):
        """
        Manual command to raise the piston
        """
        if not self.piston.piston_up(5):
            print("Failed to lower piston: Timeout")
        
    def piston_auto(self):
        """
        Function that automatically moves the piston with delays based on the manual tab settings.
        """
        position_known = False
        piston_direction = 1
        
        # Starts the cycle until the piston moves to a known position
        to = 2  # Timeout
        while not position_known and not self.gui["piston_auto_btn"].isEnabled():
            if piston_direction == 1:
                position_known = self.piston.piston_up(to)
                piston_direction = 0
            else:
                position_known = self.piston.piston_down(to)
                piston_direction = 1

        # Starts the automatic loop
        while not self.gui["piston_auto_btn"].isEnabled():  # while it is not stopped
            move_start = time.time()
            down_duration = self.gui["piston_bottom_delay_dSpinBox"].value()
            up_duration = self.gui["piston_top_delay_dSpinBox"].value()
            if piston_direction == 0:
                # the movement will last a maximum of "down_duration"
                self.piston.piston_down(down_duration)
                # Waits until down_duration is completed, in case the piston descended faster
                elapsed_time = time.time() - move_start
                if elapsed_time < down_duration:
                    time.sleep(down_duration - elapsed_time)
                piston_direction = 1
                               
            else:
                self.piston.piston_up(up_duration)
                # If this movement was faster than the expected duration, wait
                elapsed_time = time.time() - move_start
                if elapsed_time < up_duration:
                    time.sleep(up_duration - elapsed_time)
                piston_direction = 0
                
    def mode_VCV(self):
        """
        This mode should press the ambu until the desired volume is reached. The maximum flow limits
        how fast the volume is pumped. The frequency defines the period between two breaths.
        """
        # The target period (in secs) has to be calculated as a function of the frequency (in rpm)
        target_per = 60. / self.gui["VCV_frequency_dSpinBox"].value()
                
        position_known = False
        piston_direction = 1
        start_up_cycles = 0
        down_duration = 2
        margin = 0.1
        
        # Starts the cycle until the piston moves to a known position
        to = 5  # Timeout
        while not position_known and not self.gui["mode_VCV_btn"].isEnabled():
            if piston_direction == 1:
                position_known = self.piston.piston_up(to)
                piston_direction = 0
            else:
                position_known = self.piston.piston_down(to)
                piston_direction = 1
            start_up_cycles += 1
        print(f"start_up_cycles: {start_up_cycles}")
            
        # If the button is enabled, meaning another button was pressed, stops the cycle
        while(self.gui["mode_VCV_btn"].isEnabled() == False):
            # Reading the relevant values from the interface
            target_per = 60. / self.gui["VCV_frequency_dSpinBox"].value()
            max_flw = self.gui["VCV_flow_dSpinBox"].value()
            target_vol = self.gui["VCV_volume_dSpinBox"].value()
            
            move_start = time.time()
            # Defines how long each cycle takes. This is the main method of controlling volume in 
            # this mode.
            up_duration = target_per - down_duration
            if piston_direction == 0:
                # the movement will last a maximum of "down_duration"
                self.piston.piston_down(down_duration)
                # Waits until down_duration is completed, in case the piston descended faster
                elapsed_time = time.time() - move_start
                if elapsed_time < down_duration:
                    time.sleep(down_duration - elapsed_time)
                piston_direction = 1
                
            else:
                self.piston.piston_up(up_duration)
                # If this movement was faster than the expected duration, wait
                elapsed_time = time.time() - move_start
                if elapsed_time < up_duration:
                    time.sleep(up_duration - elapsed_time)
                piston_direction = 0
                
                # Calculate the peak volume and flow for the last cycle
                ids_flw_last_cycle = np.where(time.time() - self.flw_data[0, :] < target_per)[0]
                peak_flw = np.max(self.flw_data[1, ids_flw_last_cycle])
                if peak_flw > max_flw:
                    print("Flow is too high, close valve")
                    
                ids_vol_last_cycle = np.where(time.time() - self.vol_data[0, :] < target_per)[0]
                peak_vol = np.max(self.vol_data[1, ids_vol_last_cycle])
                print(f"Peak volume: {peak_vol:.1f}")
                print(f"down_duration: {down_duration:.2f}")
                if peak_vol > target_vol * (1.0 + margin):
                    down_duration = down_duration * target_vol / peak_vol
                    print(f"Volume is too high, reducing down duration to {down_duration:.2f}")
                if peak_vol < target_vol * (1.0 - margin):
                    new_down_duration = down_duration * target_vol / peak_vol
                    if new_down_duration > target_per * 0.5:
                        down_duration = target_per * 0.5
                        print(f"Down duration is too long, limited at 50% duty cycle: {down_duration:.2f}")
                        
                    else:
                        down_duration = new_down_duration
                        print(f"Volume is too low, increasing down duration to {down_duration:.2f}")
            
                
    def mode_PCV(self):
        """
        This mode should press the ambu until the desired pressure is reached. The maximum flow limits
        how fast the volume is pumped. The frequency defines the period between two breaths.
        """
        # The target period (in secs) has to be calculated as a function of the frequency (in rpm)
        target_per = 60. / self.gui["PCV_frequency_dSpinBox"].value()
                
        position_known = False  # At startup the piston has to "find" where it is
        piston_direction = 0  # Starts going down
        start_up_cycles = 0
        down_duration = 2 
        margin = 0.1
        
        # Starts the cycle until the piston moves to a known position
        to = 5  # Timeout
        while not position_known and not self.gui["mode_PCV_btn"].isEnabled():
            if piston_direction == 1:
                position_known = self.piston.piston_up(to)
                piston_direction = 0
            else:
                position_known = self.piston.piston_down(to)
                piston_direction = 1
            start_up_cycles += 1
        print(f"start_up_cycles: {start_up_cycles}")
            
        # If the button is enabled, meaning another button was pressed, stops the cycle
        while(self.gui["mode_PCV_btn"].isEnabled() == False):
            # Reading the relevant values from the interface
            target_per = 60. / self.gui["PCV_frequency_dSpinBox"].value()
            target_prs = self.gui["PCV_pressure_dSpinBox"].value()
            rise_duration = self.gui["PCV_rise_time_dSpinBox"].value()
            inhale_duration = self.gui["PCV_inhale_time_dSpinBox"].value()
            
            move_start = time.time()
            # Defines how long each cycle takes. This is the main method of controlling the cycle in 
            # this mode.
            down_duration = rise_duration + inhale_duration
            up_duration = target_per - down_duration
            if piston_direction == 0:
                # the movement will last a maximum of "rise_duration"
                self.piston.piston_down(rise_duration)
                # Waits until down_duration is completed, in case the piston descended faster
                elapsed_time = time.time() - move_start
                if elapsed_time < rise_duration:
                    time.sleep(rise_duration - elapsed_time)
                # Waits for the inhale_time
                time.sleep(inhale_duration)
                piston_direction = 1
                
            else:
                self.piston.piston_up(up_duration)
                # If this movement was faster than the expected duration, wait
                elapsed_time = time.time() - move_start
                if elapsed_time < up_duration:
                    time.sleep(up_duration - elapsed_time)
                piston_direction = 0
                
                # Calculate the peak pressure during the last cycle
                ids_prs_last_cycle = np.where(time.time() - self.prs_data[0, :] < target_per)[0]
                peak_prs = np.max(self.prs_data[1, ids_prs_last_cycle])
                if peak_prs > target_prs * (1 + margin):
                    print(f"Peak pressure {peak_prs:.1f} cmH2O is too high, close valve")
                elif peak_prs < target_prs * (1 - margin):
                    print(f"Peak pressure {peak_prs:.1f} cmH2O is too low, open valve")
                else:
                    print(f"Peak pressure is within 10% of {target_prs:.1f}: {peak_prs:.1f} cmH2O")
        
    def mode_PSV(self):
        """
        This mode must detect a negative pressure (patient is inhale by itself) and start a cycle 
        with the pressure limited 
        """
        # The target period (in secs) has to be calculated as a function of the frequency (in rpm)
        target_prs = self.gui["PSV_support_pressure_dSpinBox"].value()
        down_duration = self.gui["PSV_rise_time_dSpinBox"].value() 
                
        position_known = False  # At startup the piston has to "find" where it is
        piston_direction = 0  # Starts going down
        start_up_cycles = 0
        margin = 0.1
        
        # Starts the cycle until the piston moves to a known position
        to = 5  # Timeout
        while not position_known and not self.gui["mode_PCV_btn"].isEnabled():
            if piston_direction == 1:
                position_known = self.piston.piston_up(to)
                piston_direction = 0
            else:
                position_known = self.piston.piston_down(to)
                piston_direction = 1
            start_up_cycles += 1
        # Guarantees that the piston is in the up position
        if piston_direction == 1:
            position_known = self.piston.piston_up(to)
            piston_direction = 0
            start_up_cycles += 1
        print(f"start_up_cycles: {start_up_cycles}")
            
        # If the button is enabled, meaning another button was pressed, stops the cycle
        while(self.gui["mode_PCV_btn"].isEnabled() == False):
            # Reading the relevant values from the interface
            target_prs = self.gui["PSV_support_pressure_dSpinBox"].value()
            down_duration = self.gui["PSV_rise_time_dSpinBox"].value() 
            
            move_start = time.time()
            # The pumping starts as soon as a inhale is detected. This is obtained from a negative 
            # pressure peak
            # Calculate the peak pressure during the last 0.2 seconds
            sens_range = 0.2
            ids_prs = np.where(time.time() - self.prs_data[0, :] < sens_range)[0]
            prs_trigger = np.mean(self.prs_data[1, ids_prs])
            if prs_trigger < np.median(self.prs_data[1, :]):
                if piston_direction == 0:
                    # the movement will last a maximum of "rise_duration"
                    self.piston.piston_down(down_duration)
                    # Waits until down_duration is completed, in case the piston descended faster
                    elapsed_time = time.time() - move_start
                    if elapsed_time < down_duration:
                        time.sleep(down_duration - elapsed_time)
                    piston_direction = 1
                    
                else:
                    self.piston.piston_up(down_duration)
                    piston_direction = 0
                    
                    # Calculate the peak pressure during the last cycle
                    ids_prs_last_cycle = np.where(self.prs_data[0, :] > move_start)[0]
                    peak_prs = np.max(self.prs_data[1, ids_prs_last_cycle])
                    if peak_prs > target_prs * (1 + margin):
                        print(f"Peak pressure {peak_prs:.1f} cmH2O is too high, close valve")
                    elif peak_prs < target_prs * (1 - margin):
                        print(f"Peak pressure {peak_prs:.1f} cmH2O is too low, open valve")
                    else:
                        print(f"Peak pressure is within 10% of {target_prs:.1f}: {peak_prs:.1f} cmH2O")
                
    def piston_stop(self):  # Redundant with the if inside the while of the piston_auto function
        self.stop = True
        self.signal_piston.emit(False)

class DesignerMainWindow(QtWidgets.QMainWindow, Ui_Respirador):
    """
    Class that corresponds to the programs main window. The init starts the interface and essential
    functions
    """
    def __init__(self, parent=None):
        super(DesignerMainWindow, self).__init__(parent)
        
        # setup the GUI --> function generated by pyuic5
        self.setupUi(self)

        # Menus
        self.actionAbout.triggered.connect(self.showAbout)
        self.actionExit.triggered.connect(self.exit)
        
        # Buttons
        self.piston_top_delay_minus_btn.clicked.connect(lambda: self.piston_delay('top', '-'))
        self.piston_top_delay_plus_btn.clicked.connect(lambda: self.piston_delay('top', '+'))
        self.piston_bottom_delay_minus_btn.clicked.connect(lambda: self.piston_delay('bottom', '-'))
        self.piston_bottom_delay_plus_btn.clicked.connect(lambda: self.piston_delay('bottom', '+'))
        self.mode_VCV_btn.clicked.connect(lambda: self.modes(1))
        self.mode_PCV_btn.clicked.connect(lambda: self.modes(2))
        self.mode_PSV_btn.clicked.connect(lambda: self.modes(3))
        self.piston_auto_btn.clicked.connect(lambda: self.modes(4))
        self.mode_STOP_btn.clicked.connect(lambda: self.modes(0))

        # Configuration of the default values on the interface
        self.start_interface()

        # Classes that creates the instances of IO classes
        self.gauge = pressure_gauge()
        self.meter = flowmeter()
        self.piston = pneumatic_piston()

        # Starting the graphs and threads
        self.create_graphs()
        self.create_threads()

    def create_threads(self):
        """
        Creating the threads that will update the GUI
        Must use .self so that the garbage collection doesn't kill the threads
        """
        # Dictionary with the interface items that will be passed to the functions
        gui_items = {"piston_auto_btn":self.piston_auto_btn,
                     "piston_top_delay_dSpinBox":self.piston_top_delay_dSpinBox,
                     "piston_bottom_delay_dSpinBox":self.piston_bottom_delay_dSpinBox,
                     "VCV_flow_dSpinBox":self.VCV_flow_dSpinBox,
                     "VCV_frequency_dSpinBox":self.VCV_frequency_dSpinBox,
                     "inhale_pause_dSpinBox":self.inhale_pause_dSpinBox,
                     "VCV_volume_dSpinBox":self.VCV_volume_dSpinBox,
                     "PCV_frequency_dSpinBox":self.PCV_frequency_dSpinBox,
                     "PCV_rise_time_dSpinBox":self.PCV_rise_time_dSpinBox,
                     "PCV_pressure_dSpinBox":self.PCV_pressure_dSpinBox,
                     "PCV_inhale_time_dSpinBox":self.PCV_inhale_time_dSpinBox,
                     "PSV_support_pressure_dSpinBox":self.PSV_support_pressure_dSpinBox,
                     "PSV_rise_time_dSpinBox":self.PSV_rise_time_dSpinBox,
                     "mode_VCV_btn": self.mode_VCV_btn,
                     "mode_PCV_btn": self.mode_PCV_btn,
                     "mode_PSV_btn": self.mode_PSV_btn,
                     "mode_STOP_btn": self.mode_STOP_btn}

        # Sensors thread
        self.worker_sensors = ReadSensors(self.meter, self.gauge, gui_items)
        self.thread_sensors = QtCore.QThread()
        self.worker_sensors.moveToThread(self.thread_sensors)
        self.worker_sensors.signal_sensors.connect(self.update_sensors)
        self.thread_sensors.started.connect(self.worker_sensors.work)
        self.thread_sensors.start()
        
        # Piston control thread
        self.worker_piston = ControlPiston(self.piston, gui_items)
        self.thread_piston = QtCore.QThread()
        self.worker_piston.moveToThread(self.thread_piston)

        # Another way of passing variables to threads
        # This is done again at every loop where flow, pressure and volume are updated
        self.worker_piston.flw_data = self.flw_data
        self.worker_piston.vol_data = self.vol_data
        self.worker_piston.prs_data = self.prs_data
        self.worker_piston.mode = self.mode

        # Connecting the interface buttons to the functions inside the separate threads
        self.piston_raise_btn.clicked.connect(self.worker_piston.piston_raise)
        self.piston_lower_btn.clicked.connect(self.worker_piston.piston_lower)
        self.piston_auto_btn.clicked.connect(self.worker_piston.piston_auto)
        self.mode_VCV_btn.clicked.connect(self.worker_piston.mode_VCV)
        self.mode_PCV_btn.clicked.connect(self.worker_piston.mode_PCV)
        self.mode_PSV_btn.clicked.connect(self.worker_piston.mode_PSV)
        self.piston_auto_btn.clicked.connect(self.worker_piston.piston_auto)
        self.thread_piston.start()
        
    def piston_delay(self, which, operation):
        """
        Control the piston delay shown on the interface.
        Requires usage of lambdas on the button connect:
        btn.clicked.connect(lambda: piston_delay(which, operation)
        """
        if which == 'top':
            current_value = self.piston_top_delay_dSpinBox.value()
            if operation == '+':
                self.piston_top_delay_dSpinBox.setValue(current_value + 0.1)
            else:
                self.piston_top_delay_dSpinBox.setValue(current_value - 0.1)
        else:
            current_value = self.piston_bottom_delay_dSpinBox.value()
            if operation == '+':
                self.piston_bottom_delay_dSpinBox.setValue(current_value + 0.1)
            else:
                self.piston_bottom_delay_dSpinBox.setValue(current_value - 0.1)
        
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
        
        # Data storage arrays for time and measurement
        # Create the array of zeros and preallocating
        start_time = time.time()
        # The number of data points has to be optimized, but running at 10 fps, 200 data_points
        # correspond to about 18 seconds of data.
        self.data_points = 500
        self.prs_data = np.zeros([2, self.data_points])
        self.prs_data[0, :] = start_time
        
        self.flw_data = np.zeros([2, self.data_points])
        self.flw_data[0, :] = start_time
        
        self.vol_data = np.zeros([2, self.data_points])
        self.vol_data[0, :] = start_time
        
        # Plot settings
        bg_color = (0,  0,  50)  # Definition of the background color in RGB
        pen_color = (255, 255, 255)  # Definition of the pen color in RGB
        plot_pen = pg.mkPen(color=pen_color, width=2)
        # For some reason the color definition is different inside "styles"
        self.styles = {'color': '#FFF', 'font-size':'12pt'}
        self.time_range = [-20, 0]
        self.padding = 0.02
        # TODO Configure a simple autoscale method, because the automatic autoscale slows down the 
        # program
        
        # Configuration of the pressure plot
        self.prs_pw.setBackground(bg_color) # Set the background color
        self.prs_pw.setMenuEnabled(False) # Disables the menu
        # The title size doesn't change with the style
        self.prs_pw.setTitle("Pressão (cm H2O)", **self.styles)
        self.prs_pw.showGrid(x=True, y=True)
        self.prs_pw.setLabel(axis='bottom', text='Tempo (s)', **self.styles)
        self.prs_pw.setXRange(self.time_range[0], self.time_range[1], padding=self.padding)
        self.prs_min = 0
        self.prs_max = 40
        self.prs_pw.setYRange(self.prs_min, self.prs_max, padding=self.padding)
#        prs_pw.setDownsampling(ds=True, auto=True) # Conferir se faz diferença no desempenho
        self.prs_graph = self.prs_pw.plot(self.prs_data[0, :], self.prs_data[1, :], pen=plot_pen)
        
        # Configuration of the flow plot
        self.flw_pw.setBackground(bg_color) # Set the background color
        self.flw_pw.setMenuEnabled(False) # Disables the menu
        # The title size doesn't change with the style
        self.flw_pw.setTitle("Fluxo (l/min)", **self.styles)
        self.flw_pw.showGrid(x=True, y=True)
        self.flw_pw.setXRange(self.time_range[0], self.time_range[1], padding=self.padding)
        self.flw_min = 0
        self.flw_max = 10
        self.flw_pw.setYRange(self.flw_min, self.flw_max, padding=self.padding)
#        flw_pw.setDownsampling(ds=True, auto=True) # Conferir se faz diferença no desempenho
        self.flw_graph = self.flw_pw.plot(self.flw_data[0, :], self.flw_data[1, :], pen=plot_pen)
        
        # Configuration of the volume plot
        self.vol_pw.setBackground(bg_color) # Set the background color
        self.vol_pw.setMenuEnabled(False) # Disables the menu
        # The title size doesn't change with the style
        self.vol_pw.setTitle("Volume (ml)", **self.styles)
        self.vol_pw.showGrid(x=True, y=True)
        self.vol_pw.setXRange(self.time_range[0], self.time_range[1], padding=self.padding)
        self.vol_min = 0
        self.vol_max = 200
        self.vol_pw.setYRange(self.vol_min, self.vol_max, padding=self.padding)
#        vol_pw.setDownsampling(ds=True, auto=True) # Conferir se faz diferença no desempenho
        self.vol_graph = self.vol_pw.plot(self.vol_data[0, :], self.vol_data[1, :], pen=plot_pen)
        # Adding text inside the graph
        self.vol_lbl.setText("TEST")
        # Anchor is the position to which the text will refer in setPos
        self.vol_lbl.setAnchor((1, 1))
        # This is the position of the anchor, in the coordinates of the graph
        self.vol_lbl.setPos(0.0, 0.0)
        self.run_counter = 0
        
    # Functions that update the interface based on feedback from the threads
    @QtCore.pyqtSlot(list)
    def update_sensors(self, sensor_data):
        profile_time = False
        current_time = time.time()
        # The incoming data is a list with flow and volume in liters and l/min and pressure in cmH2O
        flow = sensor_data[0]
        volume = sensor_data[1]
        pressure = sensor_data[2]
        
        self.flw_pw.setTitle(f"Fluxo: {np.round(flow, 1):.1f} l/min", **self.styles)
        self.flw_data = np.roll(self.flw_data, 1)
        self.flw_data[:, 0] = (current_time, flow)
        self.flw_graph.setData(self.flw_data[0, :] - current_time, self.flw_data[1, :])
        # Updates the data that is given to the piston function
        self.worker_piston.flw_data = self.flw_data
        if profile_time == True:
            time_at_flow = time.time()
            print(f"After the flow graph: {time_at_flow - current_time:.4f} s")
        
        # Converting the volume from L to mL
        volume = 1000 * volume
        self.vol_pw.setTitle(f"Volume: {np.round(volume, 0):.0f} ml", **self.styles)
        self.vol_data = np.roll(self.vol_data, 1)
        self.vol_data[:, 0] = (current_time, volume)
        self.vol_graph.setData(self.vol_data[0, :] - current_time, self.vol_data[1, :])
        # Updates the data that is given to the piston function
        self.worker_piston.vol_data = self.vol_data
        mean_pts = 50
        FPS = np.nan_to_num(1.0 / np.mean(self.vol_data[0, 0:mean_pts] - self.vol_data[0, 1:1+mean_pts]))
        self.vol_lbl.setText(f"FPS: {FPS:.1f}")
        if profile_time == True:
            time_at_volume = time.time()
            print(f"After the volume graph: {time_at_volume - time_at_flow:.4f} s")

        # Calculates the tare to adjust the minimum pressure by getting the 1 percentile
        self.tare = np.percentile(self.prs_data[1, :], 1)
        # Rolls the array
        self.prs_data = np.roll(self.prs_data, 1)
        # inserts the new data in the current i position
        self.prs_data[:, 0] = (current_time, pressure)
        # Update the graph data
        self.prs_graph.setData(self.prs_data[0, :] - current_time, self.prs_data[1, :] - self.tare)
        # Updates the graph title
        self.prs_pw.setTitle(f"Pressão: {np.round(self.prs_data[1, 0] - self.tare, 1):.1f} cm H2O", **self.styles)
        # Updates the data that is given to the piston function
        self.worker_piston.prs_data = self.prs_data
        if profile_time == True:
            time_at_pressure = time.time()
            print(f"After the volume graph: {time_at_pressure - time_at_volume:.4f} s")
            print(f"Total: {time_at_pressure - current_time:.4f} s")

        # Adjust the Y range every N measurements
        # Manually adjusting by calculating the max and min with numpy is faster than enabling and
        # disabling the autoscale on the graph
        N = 20
        if self.run_counter % N == 0:
            self.vol_pw.setYRange(np.min(self.vol_data[1, :]), np.max(self.vol_data[1, :]),
                                  padding=self.padding)
            self.prs_pw.setYRange(np.min(self.prs_data[1, :] - self.tare),
                                  np.max(self.prs_data[1, :] - self.tare),
                                  padding=self.padding)
            self.flw_pw.setYRange(np.min(self.flw_data[1, :]), np.max(self.flw_data[1, :]),
                                  padding=self.padding)
            self.run_counter = 0
        self.run_counter += 1

    def exit(self):
        sys.exit()

    def showAbout(self):
        self.About = AboutWindow()
        self.About.show()
        
    def start_interface(self):
        """
        This function fills the interface with the proper values for each of the properties at start
        up
        """
        # Always shown elements
        self.inhale_pause_dSpinBox.setValue(1)
        # VCV Tab
        self.VCV_volume_dSpinBox.setValue(300)
        self.VCV_frequency_dSpinBox.setValue(12)
        self.VCV_flow_dSpinBox.setValue(30)
        # PCV Tab
        self.PCV_pressure_dSpinBox.setValue(20)
        self.PCV_frequency_dSpinBox.setValue(12)
        self.PCV_inhale_time_dSpinBox.setValue(2)
        self.PCV_rise_time_dSpinBox.setValue(1)
        # PSV Tab
        self.PSV_support_pressure_dSpinBox.setValue(20)
        self.PSV_rise_time_dSpinBox.setValue(2)
        # Manual Tab
        self.piston_top_delay_dSpinBox.setValue(6)
        self.piston_bottom_delay_dSpinBox.setValue(1)
        # Alarms Tab
        self.al_tidal_volume_min_dSpinBox.setValue(0)
        self.al_tidal_volume_max_dSpinBox.setValue(600)
        self.al_volume_minute_min_dSpinBox.setValue(0)
        self.al_volume_minute_max_dSpinBox.setValue(60)
        self.al_flow_min_dSpinBox.setValue(0)
        self.al_flow_max_dSpinBox.setValue(60)
        self.al_paw_min_dSpinBox.setValue(0)
        self.al_paw_max_dSpinBox.setValue(100)
        self.al_plateau_pressure_min_dSpinBox.setValue(0)
        self.al_plateau_pressure_max_dSpinBox.setValue(50)
        self.al_PEEP_min_dSpinBox.setValue(0)
        self.al_PEEP_max_dSpinBox.setValue(100)
        self.al_frequency_min_dSpinBox.setValue(5)
        self.al_frequency_max_dSpinBox.setValue(20)
        self.al_apnea_min_dSpinBox.setValue(0)
        self.al_apnea_max_dSpinBox.setValue(100)
        
    def modes(self, mode):
        """
        Defines the current mode based on the user's selection
        Mode 1 = VCV
        Mode 2 = PCV
        Mode 3 = PSV
        Mode 4 = Auto started from manual tab
        Mode 0 or else = Stop everything
        """
        # Sends the update to the piston worker
        self.worker_piston.mode = mode
        if mode == 1:  # 'VCV'
            self.mode_VCV_btn.setEnabled(False)
            self.mode_PCV_btn.setEnabled(True)
            self.mode_PSV_btn.setEnabled(True)
            self.mode_STOP_btn.setEnabled(True)
            self.piston_auto_btn.setEnabled(True)
            self.tabWidget.setCurrentIndex(0)
        elif mode == 2:  # 'PCV'
            self.mode_VCV_btn.setEnabled(True)
            self.mode_PCV_btn.setEnabled(False)
            self.mode_PSV_btn.setEnabled(True)
            self.mode_STOP_btn.setEnabled(True)
            self.piston_auto_btn.setEnabled(True)
            self.tabWidget.setCurrentIndex(1)
        elif mode == 3:  # 'PSV'
            self.mode_VCV_btn.setEnabled(True)
            self.mode_PCV_btn.setEnabled(True)
            self.mode_PSV_btn.setEnabled(False)
            self.mode_STOP_btn.setEnabled(True)
            self.piston_auto_btn.setEnabled(True)
            self.tabWidget.setCurrentIndex(2)
        elif mode == 4:  # 'Manual Auto'
            self.mode_VCV_btn.setEnabled(True)
            self.mode_PCV_btn.setEnabled(True)
            self.mode_PSV_btn.setEnabled(True)
            self.mode_STOP_btn.setEnabled(True)
            self.piston_auto_btn.setEnabled(False)
        else:  # STOP
            self.mode_VCV_btn.setEnabled(True)
            self.mode_PCV_btn.setEnabled(True)
            self.mode_PSV_btn.setEnabled(True)
            self.mode_STOP_btn.setEnabled(False)
            self.piston_auto_btn.setEnabled(True)
        
# %% About window
class AboutWindow(QtWidgets.QMainWindow, Ui_Sobre):
    """Customization for Qt Designer created window"""
    def __init__(self, parent=None):
        # initialization of the superclass
        super(AboutWindow, self).__init__(parent)
        # setup the GUI --> function generated by pyuic5
        self.setupUi(self)

if __name__ == "__main__":
    # %% Calling the main window
    app = QtWidgets.QApplication(sys.argv)
    dmw = DesignerMainWindow()
    dmw.show()

    sys.exit(app.exec_())
    #app.exec_()