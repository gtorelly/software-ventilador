"""
Main function
"""
import configparser
import numpy as np
from PyQt5 import QtWidgets,  QtCore
import pyqtgraph as pg
from queue import Queue
import sys
import time
from ui.Ui_GUI_mainWindow import Ui_Respirador
from ui.Ui_GUI_sobre import Ui_Sobre
from ui.Ui_GUI_startup_error import Ui_StartupError

# Hardware control files
from hw_adc_pressure import pressure_gauge
from hw_flowmeter import flowmeter
from hw_piston import pneumatic_piston
from hw_buttons import Buttons

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
        self.meter = flowmeter()
        # Associates the received queues with local variables
        self.flw_q = flw_q
        self.prs_q = prs_q

    def work(self):  # This function is what the new thread will execute
        ui_update_frequency = 100  # Hz
        ui_update_period = 1 / ui_update_frequency
        while(True):
            start = time.time()
            debug_print = False

            flow = self.gauge.read_flow_from_dp()
            self.flw_q.put([time.time(), flow])
            # self.flw_q.join()
            # flow = self.meter.calc_flow(instant)

            if debug_print == True:
                flow_time = time.time()
                print(f"Runtime - calc_flow: {1000 * (flow_time - start):.0f} ms")

            # volume = self.meter.calc_volume(period)
            # self.vol_q.put([time.time(), volume])
        
            # if debug_print == True:
            #     volume_time = time.time()
            #     print(f"Runtime - calc_volume: {1000 * (volume_time - flow_time):.0f} ms")

            pressure = self.gauge.read_pressure()
            self.prs_q.put([time.time(), pressure])
            # self.prs_q.join()

            if debug_print == True:
                pressure_time = time.time()
                print(f"Runtime - read_pressure: {1000 * (pressure_time - volume_time):.0f} ms")

            # self.signal_sensors.emit([flow, volume, pressure])

            runtime = time.time() - start
            if runtime < ui_update_period:
                time.sleep(ui_update_period - runtime)
                
            if debug_print == True:
                print(f"Runtime - total: {1000 * runtime:.0f} ms")

class ControlPiston(QtCore.QObject):
    signal_piston = QtCore.pyqtSignal(bool)
    signal_cycle_data = QtCore.pyqtSignal(dict)
    signal_startup_error = QtCore.pyqtSignal(bool)
    
    def __init__(self, gui, mode):
        super().__init__()
        # receives the piston instance from the call of this worker in the main window
        # assigns the instance to another with the same name.
        self.piston = pneumatic_piston()
        self.stop = False
        self.gui = gui
        self.mode = 0
        self.pause = False
        self.pause_duration = 1

        # Variables to store the current position and next direction of the piston movement
        self.pst_pos = None
        self.pst_dir = 0  # Starts going down

        # Dictionary that stores the cycle data, in order to create the pipeline, sending this info
        # to the interface.
        self.cd = {"started_up": False}

    def startup(self):
        """
        Starts the cycle until the piston moves to a known position
        """
        # Initializing the cycle data (cd) dictionary
        self.cd["started_up"] = False
        self.cd["peak_pressure"] = "0 cmH2O"
        self.cd["tidal_volume"] = "0 ml"
        self.cd["inhale_time"] = "0 s"
        self.cd["exhale_time"] = "0 s"
        self.cd["exhale_time"] = "0 s"
        self.cd["IE_ratio"] = "1 : 1"
        to = 2  # Timeout
        startup_cycles = 0
        limit = 20
        while self.pst_pos == None:
            if self.pst_dir == 1:
                self.pst_pos = self.piston.piston_up(to)
                self.pst_dir = 0
            else:
                self.pst_pos = self.piston.piston_down(to)
                self.pst_dir = 1
            startup_cycles += 1
            if startup_cycles >= limit:
                print("There is a problem at startup, check compressed air")
                print(f"Tried to startup for {startup_cycles} cycles")
                # Breaks the loop so that the controller doesn't start
                self.signal_startup_error.emit(True)
                return
        print(f"startup_cycles: {startup_cycles}")
        self.cd["started_up"] = True
        self.signal_cycle_data.emit(self.cd)
        self.controller()

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
        up_cycle_end = time.time()
        down_cycle_end = time.time()
        last_cycle_dur = 0.1
        inhale_time = 1
        exhale_time = 1

        # 5% margin of error for the target values
        margin = 0.05

        # Variable created for the PSV mode
        triggered_last_cycle = False

        # Starts the automatic loop
        while True:
            # Uses flow for the calculation of the indexes, but flow, volume and pressure are
            # stored simultaneously, so it shouldn't make a difference
            idxs_last_cycle = np.where(time.time() - self.flw_data[0, :] < last_cycle_dur)[0]
            
            # Sends the maximum pressure and volume in the last cycle to the interface
            # This try-except logic is just to avoid a problem when the max of an empty array is 
            # calculated, leading to an error.
            try:
                peak_prs = np.max(self.prs_data[1, idxs_last_cycle])
            except:
                peak_prs = 0
            try:
                peak_vol = np.max(self.vol_data[1, idxs_last_cycle])
            except:
                peak_vol = 0
            self.cd["peak_pressure"] = f"{peak_prs:.1f} cmH2O"
            self.cd["tidal_volume"] = f"{peak_vol:.1f} ml"

            if self.mode == 1:  # 'VCV'
                """
                This mode should press the ambu until the desired volume is reached. The maximum
                flow limits how fast the volume is pumped. The frequency defines the period between
                two breaths.
                """
                # Reading the relevant values from the interface
                tgt_per = 60. / self.gui["VCV_frequency_spb"].value()
                max_flw = self.gui["VCV_flow_spb"].value()
                tgt_vol = self.gui["VCV_volume_spb"].value()
                self.pause_duration = self.gui["VCV_inhale_pause_spb"].value()

                # On the first cycle, use standard values
                if first_cycle:
                    t_move_down = tgt_per / 4.
                    first_cycle = False
                    # Defines how long each cycle takes, enabling the volume control
                    t_move_up = tgt_per - t_move_down
                    continue  # skips the rest of the loop on the first cycle
                # Calculate the peak volume and flow for the last cycle
                try:
                    peak_flw = np.max(self.flw_data[1, idxs_last_cycle])
                except:
                    peak_flw = 0
                print(f"Peak flow: {peak_flw:.1f}")
                try:
                    peak_vol = np.max(self.vol_data[1, idxs_last_cycle])
                except:
                    peak_vol = 0
                print(f"Peak volume: {peak_vol:.1f}")

                if peak_flw > max_flw:
                    print("Flow is too high, close valve")
                    
                if peak_vol > tgt_vol * (1.0 + margin):
                    if peak_vol == 0:  # Avoiding a division by zero
                        t_move_down  = t_move_down * (1.0 - margin)
                    else:  # Proportional reduction
                        t_move_down = t_move_down * tgt_vol / peak_vol
                    print(f"Volume is too high, reducing t_move_down to {t_move_down:.2f}")
                if peak_vol < tgt_vol * (1.0 - margin):
                    if peak_vol == 0:  # Avoiding a division by zero
                        new_t_move_down  = t_move_down * (1.0 + margin)
                    else:  # Proportional increase
                        new_t_move_down = t_move_down * tgt_vol / peak_vol
                    if new_t_move_down > tgt_per * 0.5:
                        t_move_down = tgt_per * 0.5
                        print(f"t_move_down is too long, limited at 50% cycle: {t_move_down:.2f}")
                        
                    else:
                        t_move_down = new_t_move_down
                        print(f"Volume is too low, increasing t_move_down to {t_move_down:.2f}")

                # Defines how long each cycle takes, enabling the volume control
                t_move_up = tgt_per - t_move_down
                t_wait_up = 0
                t_wait_down = 0

            elif self.mode == 2:  # 'PCV'
                """
                This mode should press the ambu until the desired pressure is reached. The maximum 
                flow limits how fast the volume is pumped. The frequency defines the period between 
                two breaths.
                """
                # The target period (in secs) has to be calculated as a function of the frequency 
                # (in rpm)
                tgt_per = 60. / self.gui["PCV_frequency_spb"].value()
                # Reading the relevant values from the interface
                tgt_prs = self.gui["PCV_pressure_spb"].value()
                t_move_down = self.gui["PCV_rise_time_spb"].value()
                t_wait_down = self.gui["PCV_inhale_time_spb"].value()
                self.pause_duration = self.gui["PCV_inhale_pause_spb"].value()
            
                # Defines how long each cycle takes. This is the main method of controlling the cycle in 
                # this mode.
                t_move_up = tgt_per - t_move_down - t_wait_down
                    
                # Calculate the peak pressure during the last cycle
                try:
                    peak_prs = np.max(self.prs_data[1, idxs_last_cycle])
                except:
                    peak_prs = 0
                if peak_prs > tgt_prs * (1 + margin):
                    print(f"Peak pressure {peak_prs:.1f} cmH2O is too high, close valve")
                elif peak_prs < tgt_prs * (1 - margin):
                    print(f"Peak pressure {peak_prs:.1f} cmH2O is too low, open valve")
                else:
                    print(f"Peak pressure is within 10% of {tgt_prs:.1f}: {peak_prs:.1f} cmH2O")

            elif self.mode == 3:  # 'PSV'
                """
                This mode must detect a negative pressure (patient is inhale by itself) and start a 
                cycle with the pressure limited 
                """
                tgt_prs = self.gui["PSV_pressure_spb"].value()
                t_move_down = self.gui["PSV_rise_time_spb"].value()
                self.pause_duration = self.gui["PSV_inhale_pause_spb"].value()
                 
                t_move_up = t_move_down

                sens_range = 0.2
                ids_prs = np.where(time.time() - self.prs_data[0, :] < sens_range)[0]
                try:
                    prs_trigger = np.mean(self.prs_data[1, ids_prs])
                except:
                    prs_trigger = np.inf
                # Negative pressure means patient is trying to breathe
                threshold = -0.5  # cmH2O
                if triggered_last_cycle:
                    triggered_last_cycle = False
                    self.pst_dir = 1
                elif prs_trigger < threshold:
                    triggered_last_cycle = True
                    self.pst_dir = 0
                else:
                    time.sleep(sens_range / 2)
                    self.pst_dir = 2

            else:  # STOP
                # Does not move, just waits and continues to the next cycle
                time.sleep(0.5)
                continue

            # After the configuration of the cycle times, perform the movement
            if self.mode in [1, 2, 3]:
                move_start = time.time()
                if self.pst_dir == 0:  # Should move down
                    # the movement will last a maximum of "t_move_down"
                    self.pst_pos = self.piston.piston_down(t_move_down)
                    # Waits until t_move_down is completed, in case the piston descended faster
                    move_down_dur = time.time() - move_start
                    if move_down_dur < t_move_down:
                        time.sleep(t_move_down - move_down_dur)
                    # If the pause button was pressed, pauses 
                    if self.pause == True:
                        time.sleep(self.pause_duration)
                        t_wait_down = t_wait_down - self.pause_duration
                        self.pause = False
                    # if the piston needs to wait in the down position
                    if t_wait_down > 0:
                        time.sleep(t_wait_down)
                    self.pst_dir = 1
                    down_cycle_end = time.time()
                
                elif self.pst_dir == 1:  # Should move up
                    self.pst_pos = self.piston.piston_up(t_move_up)
                    move_up_dur = time.time() - move_start
                    # If this movement was faster than the expected duration, wait
                    if move_up_dur < t_move_up:
                        time.sleep(t_move_up - move_up_dur)
                    # if the piston needs to wait in the up position
                    if t_wait_up > 0:
                        time.sleep(t_wait_up)
                    self.pst_dir = 0
                    up_cycle_end = time.time()

                else:  # Should do nothing
                    #print("do nothing")
                    continue

            # Calculating how long the inhale and exhale took
            if self.pst_dir == 0:  # The up cycle has just ended
                exhale_time = up_cycle_end - down_cycle_end
            elif self.pst_dir == 1:  # The down cycle has just ended
                inhale_time = down_cycle_end - up_cycle_end

            last_cycle_dur = exhale_time + inhale_time

            # Calculating the I:E ratio
            ratio = exhale_time / inhale_time
            self.cd["IE_ratio"] = f"1 : {ratio:.1f}"
            # Saving the data for the GUI update
            self.cd["inhale_time"] = f"{inhale_time:.1f} s"
            self.cd["exhale_time"] = f"{exhale_time:.1f} s"
            self.signal_cycle_data.emit(self.cd)

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
        self.btns = Buttons(self.input_q)

    def read_queue(self):
        key = None
        prev_key = [0, 0]
        # usually the difference between correct signals is in the range of 40 ms
        dt_max = 100E-3
        dt_min = 3E-6
        while(True):
            # If the queue is empty, skips to the next block
            if self.input_q.empty():
                time.sleep(0.2)
                continue
            # key gets from the queue a list with the name of the key and the time it was pressed
            key = self.input_q.get()
            self.input_q.task_done()
            if key[0] == "clk":
                dt = key[1] - prev_key[1]
                # Doesn'
                if prev_key[0] == "dt" and dt < dt_max and dt > dt_min:
                    # print(f"Interval = {1000 * (key[1] - prev_key[1]):.3f} ms - CCW")
                    self.signal_button.emit("CCW")
                    prev_key = [0, 0]
                else:
                    prev_key = key

            elif key[0] == "dt":
                dt = key[1] - prev_key[1]
                if prev_key[0] == "clk" and dt < dt_max and dt > dt_min:
                    # print(f"Interval = {1000 * (key[1] - prev_key[1]):.3f} ms - CW")
                    self.signal_button.emit("CW")
                    prev_key = [0, 0]
                else:
                    prev_key = key

            elif key[0] in ["UP", "DOWN", "OK", "ROT"]:
                self.signal_button.emit(key[0])

class DesignerMainWindow(QtWidgets.QMainWindow, Ui_Respirador):
    """
    Class that corresponds to the programs main window. The init starts the interface and essential
    functions
    """
    def __init__(self, parent=None):
        super(DesignerMainWindow, self).__init__(parent)
        
        # setup the GUI --> function generated by pyuic5
        self.setupUi(self)

        # Creates the error_window instance
        self.error_window = StartupErrorWindow()

        # Reads the configuration file and create the corresponding variables
        self.conf = configparser.ConfigParser()
        self.conf.read('config_file.conf')
        print(self.conf['VCV'].getfloat('volume_inc'))

        # Buttons
        # VCV tab
        self.VCV_start_btn.clicked.connect(lambda: self.modes(1))
        self.VCV_stop_btn.clicked.connect(lambda: self.modes(0))
        self.VCV_volume_plus.clicked.connect(
            lambda: self.change_value(self.VCV_volume_spb, self.conf['VCV'].getfloat('volume_inc')))
        self.VCV_volume_minus.clicked.connect(
            lambda: self.change_value(self.VCV_volume_spb, 
                                      -1 * self.conf['VCV'].getfloat('volume_inc')))
        self.VCV_frequency_plus.clicked.connect(
            lambda: self.change_value(self.VCV_frequency_spb, 1))
        self.VCV_frequency_minus.clicked.connect(
            lambda: self.change_value(self.VCV_frequency_spb, -1))
        self.VCV_flow_plus.clicked.connect(
            lambda: self.change_value(self.VCV_flow_spb, 1))
        self.VCV_flow_minus.clicked.connect(
            lambda: self.change_value(self.VCV_flow_spb, -1))
        self.VCV_inhale_pause_plus.clicked.connect(
            lambda: self.change_value(self.VCV_inhale_pause_spb, 0.1))
        self.VCV_inhale_pause_minus.clicked.connect(
            lambda: self.change_value(self.VCV_inhale_pause_spb, -0.1))
        self.VCV_inhale_pause_btn.clicked.connect(self.inhale_pause_control)
        
        # PCV tab
        self.PCV_start_btn.clicked.connect(
            lambda: self.modes(2))
        self.PCV_stop_btn.clicked.connect(
            lambda: self.modes(0))
        self.PCV_pressure_plus.clicked.connect(
            lambda: self.change_value(self.PCV_pressure_spb, 1))
        self.PCV_pressure_minus.clicked.connect(
            lambda: self.change_value(self.PCV_pressure_spb, -1))
        self.PCV_frequency_plus.clicked.connect(
            lambda: self.change_value(self.PCV_frequency_spb, 1))
        self.PCV_frequency_minus.clicked.connect(
            lambda: self.change_value(self.PCV_frequency_spb, -1))
        self.PCV_inhale_time_plus.clicked.connect(
            lambda: self.change_value(self.PCV_inhale_time_spb, 0.1))
        self.PCV_inhale_time_minus.clicked.connect(
            lambda: self.change_value(self.PCV_inhale_time_spb, -0.1))
        self.PCV_rise_time_plus.clicked.connect(
            lambda: self.change_value(self.PCV_rise_time_spb, 0.1))
        self.PCV_rise_time_minus.clicked.connect(
            lambda: self.change_value(self.PCV_rise_time_spb, -0.1))
        self.PCV_inhale_pause_plus.clicked.connect(
            lambda: self.change_value(self.PCV_inhale_pause_spb, 0.1))
        self.PCV_inhale_pause_minus.clicked.connect(
            lambda: self.change_value(self.PCV_inhale_pause_spb, -0.1))
        self.PCV_inhale_pause_btn.clicked.connect(self.inhale_pause_control)
        
        # PSV tab
        self.PSV_start_btn.clicked.connect(
            lambda: self.modes(3))
        self.PSV_stop_btn.clicked.connect(
            lambda: self.modes(0))
        self.PSV_pressure_plus.clicked.connect(
            lambda: self.change_value(self.PSV_pressure_spb, 1))
        self.PSV_pressure_minus.clicked.connect(
            lambda: self.change_value(self.PSV_pressure_spb, -1))
        self.PSV_rise_time_plus.clicked.connect(
            lambda: self.change_value(self.PSV_rise_time_spb, 0.1))
        self.PSV_rise_time_minus.clicked.connect(
            lambda: self.change_value(self.PSV_rise_time_spb, -0.1))
        self.PSV_inhale_pause_plus.clicked.connect(
            lambda: self.change_value(self.PSV_inhale_pause_spb, 0.1))
        self.PSV_inhale_pause_minus.clicked.connect(
            lambda: self.change_value(self.PSV_inhale_pause_spb, -0.1))
        self.PSV_inhale_pause_btn.clicked.connect(self.inhale_pause_control)

        # Configuration of the default values on the interface
        self.start_interface()

        # Starting the graphs and threads
        self.create_graphs()
        self.create_threads()

        # Create a timer to update the graphs at some period
        self.timer = QtCore.QTimer()
        gui_update_frequency = 20  # FPS
        gui_update_period = 1000 / gui_update_frequency  # period in ms
        self.timer.start(gui_update_period)
        self.timer.timeout.connect(self.update_graphs)

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
        self.data_points = 5000
        # prs_data has three rows, 0 = time, 1 = pressure - tare, 2 = raw_pressure
        self.prs_data = np.zeros([3, self.data_points])
        self.prs_data[0, :] = start_time
        self.prs_q = Queue()
        self.tare = 0
        
        self.flw_data = np.zeros([2, self.data_points])
        self.flw_data[0, :] = start_time
        self.flw_q = Queue()
        
        self.vol_data = np.zeros([2, self.data_points])
        self.vol_data[0, :] = start_time
        
        # Plot settings
        bg_color = "#000032"  # Background color
        pen_color = "#FFFFFF"  # Pen color
        font_size = "24px"
        plot_pen = pg.mkPen(color=pen_color, width=3)
        # For some reason the color definition is different inside "styles"
        # Titles use 'size', while labels use 'font_size'
        self.lbl_style = {'color': pen_color, 'font-size': font_size}
        self.ttl_style = {'color': pen_color, 'size': font_size} 
        self.time_range = [-20, 0]
        self.padding = 0.01

        # Configuration of the pressure plot
        self.prs_pw.setBackground(bg_color) # Set the background color
        self.prs_pw.setMenuEnabled(False) # Disables the menu
        # The title size doesn't change with the style
        self.prs_pw.setTitle("Pressão (cm H2O)", **self.ttl_style)
        self.prs_pw.showGrid(x=True, y=True)
        self.prs_pw.setLabel(axis='bottom', text='Tempo (s)', **self.lbl_style)
        self.prs_pw.setXRange(self.time_range[0], self.time_range[1], self.padding)
        self.prs_graph = self.prs_pw.plot(self.prs_data[0, :], self.prs_data[1, :], pen=plot_pen)
        
        # Configuration of the flow plot
        self.flw_pw.setBackground(bg_color) # Set the background color
        self.flw_pw.setMenuEnabled(False) # Disables the menu
        # The title size doesn't change with the style
        self.flw_pw.setTitle("Fluxo (l/min)", **self.ttl_style)
        self.flw_pw.showGrid(x=True, y=True)
        self.flw_pw.setXRange(self.time_range[0], self.time_range[1], self.padding)
        self.flw_graph = self.flw_pw.plot(self.flw_data[0, :], self.flw_data[1, :], pen=plot_pen)
        
        # Configuration of the volume plot
        self.vol_pw.setBackground(bg_color) # Set the background color
        self.vol_pw.setMenuEnabled(False) # Disables the menu
        # The title size doesn't change with the style
        self.vol_pw.setTitle("Volume (ml)", **self.ttl_style)
        self.vol_pw.showGrid(x=True, y=True)
        self.vol_pw.setXRange(self.time_range[0], self.time_range[1], self.padding)
        self.vol_graph = self.vol_pw.plot(self.vol_data[0, :], self.vol_data[1, :], pen=plot_pen)
        # Adding text inside the graph
        self.vol_lbl.setText("TEST")
        # Anchor is the position to which the text will refer in setPos
        self.vol_lbl.setAnchor((1, 1))
        # This is the position of the anchor, in the coordinates of the graph
        self.vol_lbl.setPos(0.0, 0.0)
        self.run_counter = 0

    def create_threads(self):
        """
        Creating the threads that will update the GUI
        Must use .self so that the garbage collection doesn't kill the threads
        """
        # Dictionary with the interface items that will be passed to the functions
        gui_items = {"VCV_flow_spb":self.VCV_flow_spb,
                     "VCV_frequency_spb":self.VCV_frequency_spb,
                     "VCV_inhale_pause_spb":self.VCV_inhale_pause_spb,
                     "VCV_volume_spb":self.VCV_volume_spb,
                     "PCV_frequency_spb":self.PCV_frequency_spb,
                     "PCV_rise_time_spb":self.PCV_rise_time_spb,
                     "PCV_pressure_spb":self.PCV_pressure_spb,
                     "PCV_inhale_time_spb":self.PCV_inhale_time_spb,
                     "PCV_inhale_pause_spb":self.PCV_inhale_pause_spb,
                     "PSV_pressure_spb":self.PSV_pressure_spb,
                     "PSV_rise_time_spb":self.PSV_rise_time_spb,
                     "PSV_inhale_pause_spb":self.PSV_inhale_pause_spb,
                     "VCV_start_btn": self.VCV_start_btn,
                     "PCV_start_btn": self.PCV_start_btn,
                     "PSV_start_btn": self.PSV_start_btn,
                     "VCV_stop_btn": self.VCV_stop_btn,
                     "PCV_stop_btn": self.PCV_stop_btn,
                     "PSV_stop_btn": self.PSV_stop_btn}

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
        self.worker_piston = ControlPiston(gui_items, mode=0)
        self.thread_piston = QtCore.QThread()
        self.worker_piston.moveToThread(self.thread_piston)
        # Another way of passing variables to threads
        # This is done again at every loop where flow, pressure and volume are updated
        self.worker_piston.flw_data = self.flw_data
        self.worker_piston.vol_data = self.vol_data
        self.worker_piston.prs_data = self.prs_data
        self.worker_piston.signal_cycle_data.connect(self.update_interface)
        self.worker_piston.signal_startup_error.connect(self.error_window.show)
        self.error_window.signal_retry_startup.connect(self.worker_piston.startup)
        self.thread_piston.started.connect(self.worker_piston.startup)
        self.thread_piston.start()

        # Buttons control thread
        self.worker_buttons = InterfaceControl()
        self.thread_buttons = QtCore.QThread()
        self.worker_buttons.moveToThread(self.thread_buttons)
        self.worker_buttons.signal_button.connect(self.spinbox_control)
        self.thread_buttons.started.connect(self.worker_buttons.read_queue)
        self.thread_buttons.start()
        
    def update_graphs(self):
        """
        This function continuously checks if the queues have available data and update the graphs
        """
        profile_time = False
        # The incoming data is a list with flow and volume in liters and l/min and pressure in cmH2O
        # flow = sensor_data[0]
        # volume = sensor_data[1]
        # pressure = sensor_data[2]

        # while True:
        if profile_time:
            start_time = time.time()
        # If both queues are empty, just wait
        if self.prs_q.empty() and self.flw_q.empty():
            time.sleep(0.1)
            return

        # while the pressure queue is not empty, get the data and append
        new_prs_data = False
        while not self.prs_q.empty():
            t, pressure = self.prs_q.get()
            # Rolls the array
            self.prs_data = np.roll(self.prs_data, 1)
            # inserts the new data in the current i position
            self.prs_data[:, 0] = (t, pressure - self.tare, pressure)
            new_prs_data = True
        if new_prs_data:
            # Signals that it got all the data from the queue and the sensors can continue to put
            # new data in the queue
            self.prs_q.task_done()
            # Calculates the tare (baseline) of the pressure sensor
            # If the pressure deviation over the entire measurement is below the standard dev,
            # assume that it is stable enough, so it is the baseline.
            std_limit = 0.02
            std = np.std(self.prs_data[2, :])
            if std < std_limit:
                self.tare = np.mean(self.prs_data[2, :])
                self.prs_data[1, :] = self.prs_data[2, :] - self.tare
            # Update the graph data with data only within the chosen time_range
            now = time.time()
            idxs_tr = np.where(now - self.prs_data[0, :] < 
                               self.time_range[1] - self.time_range[0])[0]
            self.prs_graph.setData(self.prs_data[0, idxs_tr] - now, self.prs_data[1, idxs_tr])
            std_dev = np.std(self.prs_data[1, idxs_tr])
            # Updates the graph title
            self.prs_pw.setTitle(f"Pressão: {self.prs_data[1, 0]:.1f} cmH2O +- {std_dev:.2f}",
                                 **self.ttl_style)
            # Updates the data that is given to the piston function
            self.worker_piston.prs_data = self.prs_data
            if profile_time == True:
                time_at_pressure = time.time()
                print(f"Until pressure graph: {time_at_pressure - start_time:.4f} s")
        
        # while the flow queue is not empty, get the data and append
        new_flw_data = False
        while not self.flw_q.empty():
            t, flow = self.flw_q.get()
            # Rolls the array
            self.flw_data = np.roll(self.flw_data, 1)
            # inserts the new data in the current i position
            self.flw_data[:, 0] = (t, flow)
            new_flw_data = True
        if new_flw_data:
            # Signals that it got all the data from the queue and the sensors can continue to put
            # new data in the queue
            self.flw_q.task_done()
            # Update the graph data with data only within the chosen time_range
            now = time.time()
            idxs_tr = np.where(now - self.flw_data[0, :] < 
                               self.time_range[1] - self.time_range[0])[0]
            std_dev = np.std(self.flw_data[1, idxs_tr])
            self.flw_pw.setTitle(f"Fluxo: {flow:.1f} l/min +- {std_dev:.2f}",
                                 **self.ttl_style)
            self.flw_graph.setData(self.flw_data[0, idxs_tr] - now, self.flw_data[1, idxs_tr])
            # Updates the data that is given to the piston function
            self.worker_piston.flw_data = self.flw_data
            if profile_time == True:
                time_at_flow = time.time()
                print(f"Until flow graph: {time_at_flow - start_time:.4f} s")
        
            # Calculating volume from the flow
            now = time.time()
            last_inhale = 5
            # Gets the indexes of the data since the last breath
            idxs_li = np.where(now - self.flw_data[0, :] < last_inhale)[0]
            volume = np.sum(self.flw_data[1, idxs_li]) / (60 * last_inhale)
            # Converting the volume from L to mL
            volume = 1000 * volume
            self.vol_data = np.roll(self.vol_data, 1)
            self.vol_data[:, 0] = (self.flw_data[0, 0], volume)
            idxs_tr = np.where(now - self.vol_data[0, :] < 
                               self.time_range[1] - self.time_range[0])[0]
            std_dev = np.std(self.vol_data[1, idxs_tr])
            self.vol_pw.setTitle(f"Volume: {volume:.0f} ml +- {std_dev:.1f}",
                                 **self.ttl_style)
            self.vol_graph.setData(self.vol_data[0, idxs_tr] - now, self.vol_data[1, idxs_tr])
            # Updates the data that is given to the piston function
            self.worker_piston.vol_data = self.vol_data
            mean_pts = 50
            FPS = np.nan_to_num(1.0 / np.mean(self.vol_data[0, 0:mean_pts] - 
                                self.vol_data[0, 1:1+mean_pts]))
            self.vol_lbl.setText(f"FPS: {FPS:.1f}")
            if profile_time == True:
                time_at_volume = time.time()
                print(f"After the volume graph: {time_at_volume - time_at_flow:.4f} s")

        # Adjust the Y range every N measurements
        # Manually adjusting by calculating the max and min with numpy is faster than 
        # autoscale on the graph
        
        N = 20
        if self.run_counter % N == 0:
            self.vol_pw.setYRange(np.min(self.vol_data[1, idxs_tr]),
                                  np.max(self.vol_data[1, idxs_tr]),
                                  self.padding)
            self.prs_pw.setYRange(np.min(self.prs_data[1, idxs_tr]),
                                  np.max(self.prs_data[1, idxs_tr]),
                                  self.padding)
            self.flw_pw.setYRange(np.min(self.flw_data[1, idxs_tr]),
                                  np.max(self.flw_data[1, idxs_tr]),
                                  self.padding)
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
        self.VCV_volume_spb.setValue(300)
        self.VCV_frequency_spb.setValue(12)
        self.VCV_flow_spb.setValue(30)
        self.VCV_inhale_pause_spb.setValue(1)
        self.VCV_stop_btn.setEnabled(False)
        # PCV Tab
        self.PCV_pressure_spb.setValue(20)
        self.PCV_frequency_spb.setValue(12)
        self.PCV_inhale_time_spb.setValue(2)
        self.PCV_rise_time_spb.setValue(1)
        self.PCV_inhale_pause_spb.setValue(1)
        self.PCV_stop_btn.setEnabled(False)
        # PSV Tab
        self.PSV_pressure_spb.setValue(20)
        self.PSV_rise_time_spb.setValue(2)
        self.PSV_inhale_pause_spb.setValue(1)
        self.PSV_stop_btn.setEnabled(False)
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
        # Always shown elements
        self.inhale_time_val.setText("0,0 s")
        self.exhale_time_val.setText("0,0 s")
        self.IE_ratio_val.setText("1:1")
        self.peak_pressure_val.setText("0,0 cm H2O")
        self.tidal_volume_val.setText("0 ml")

    @QtCore.pyqtSlot(str)
    def spinbox_control(self, action):
        """
        Finds the active (in focus, last clicked) spinbox and increases or decreases its value,
        based on the button that was pressed
        """
        # Gets the current tab, so that it can check which of the spinboxes currently shown is
        # in focus, or choose one to be in focus 
        c_tab = self.tabWidget.currentIndex()
        tab_content = {0:[self.VCV_frequency_spb,
                          self.VCV_flow_spb,
                          self.VCV_volume_spb,
                          self.VCV_inhale_pause_spb],
                       1:[self.PCV_frequency_spb,
                          self.PCV_rise_time_spb,
                          self.PCV_inhale_time_spb,
                          self.PCV_pressure_spb,
                          self.PCV_inhale_pause_spb],
                       2:[self.PSV_pressure_spb,
                          self.PSV_rise_time_spb,
                          self.PSV_inhale_pause_spb],
                       3:[self.al_tidal_volume_min_dSpinBox,
                          self.al_tidal_volume_max_dSpinBox,
                          self.al_volume_minute_min_dSpinBox,
                          self.al_volume_minute_max_dSpinBox,
                          self.al_flow_min_dSpinBox,
                          self.al_flow_max_dSpinBox,
                          self.al_paw_min_dSpinBox,
                          self.al_paw_max_dSpinBox,
                          self.al_plateau_pressure_min_dSpinBox,
                          self.al_plateau_pressure_max_dSpinBox,
                          self.al_PEEP_min_dSpinBox,
                          self.al_PEEP_max_dSpinBox,
                          self.al_frequency_min_dSpinBox,
                          self.al_frequency_max_dSpinBox,
                          self.al_apnea_min_dSpinBox,
                          self.al_apnea_max_dSpinBox]}
        # By default will choose the first spinbox on the current tab.
        current_spb = tab_content[c_tab][1]
        # Going through the spinboxes of the current tab and checking whether they have the focus
        for item in tab_content[c_tab]:
            if item.hasFocus():
                current_spb = item
                continue

        if action == "UP":
            self.change_value(current_spb, 1)
        elif action == "DOWN":
            self.change_value(current_spb, -1)
        elif action == "OK":
            # Put the next spinbox in focus
            nxt = tab_content[c_tab][(tab_content[c_tab].index(current_spb) + 1) % 
                                     len(tab_content[c_tab])]
            nxt.setFocus()
        elif action == "ROT":
            # Put the next spinbox in focus
            nxt = tab_content[c_tab][(tab_content[c_tab].index(current_spb) + 1) %
                                     len(tab_content[c_tab])]
            nxt.setFocus()
        elif action == "CW":
            self.change_value(current_spb, 1)
        elif action == "CCW":
            self.change_value(current_spb, -1)
        else:
            print("I just don't get it man")

    def change_value(self, spinbox, increment):
        """
        Function to update the value of the spinboxes when they're clicked or modified.
        The button is connected to a lambda: change_value(button, + or - value)
        """
        spinbox.setValue(spinbox.value() + increment)

    def modes(self, mode):
        """
        Defines the current mode and based on the user's selection
        Mode 1 = VCV
        Mode 2 = PCV
        Mode 3 = PSV
        Mode 0 or else = Stop everything
        """
        # Sends the update to the piston worker
        self.worker_piston.mode = mode
        if mode == 1:  # 'VCV'
            self.VCV_start_btn.setEnabled(False)
            self.PCV_start_btn.setEnabled(True)
            self.PSV_start_btn.setEnabled(True)
            self.VCV_stop_btn.setEnabled(True)
            self.PCV_stop_btn.setEnabled(True)
            self.PSV_stop_btn.setEnabled(True)
        elif mode == 2:  # 'PCV'
            self.VCV_start_btn.setEnabled(True)
            self.PCV_start_btn.setEnabled(False)
            self.PSV_start_btn.setEnabled(True)
            self.VCV_stop_btn.setEnabled(True)
            self.PCV_stop_btn.setEnabled(True)
            self.PSV_stop_btn.setEnabled(True)
        elif mode == 3:  # 'PSV'
            self.VCV_start_btn.setEnabled(True)
            self.PCV_start_btn.setEnabled(True)
            self.PSV_start_btn.setEnabled(False)
            self.VCV_stop_btn.setEnabled(True)
            self.PCV_stop_btn.setEnabled(True)
            self.PSV_stop_btn.setEnabled(True)
        else:  # STOP
            self.VCV_start_btn.setEnabled(True)
            self.PCV_start_btn.setEnabled(True)
            self.PSV_start_btn.setEnabled(True)
            self.VCV_stop_btn.setEnabled(False)
            self.PCV_stop_btn.setEnabled(False)
            self.PSV_stop_btn.setEnabled(False)
    
    def inhale_pause_control(self):
        """
        If the user pressed the inhale pause button, it changes the respective value at the
        controller function
        """
        self.worker_piston.pause = True

    @QtCore.pyqtSlot(dict)
    def update_interface(self, cd):
        """
        Receives information about the last cycle in the form of a dict and updates the GUI based on
        that.
        """
        self.inhale_time_val.setText(cd["inhale_time"])
        self.exhale_time_val.setText(cd["exhale_time"])
        self.IE_ratio_val.setText(cd["IE_ratio"])
        self.peak_pressure_val.setText(cd["peak_pressure"])
        self.tidal_volume_val.setText(cd["tidal_volume"])

class AboutWindow(QtWidgets.QMainWindow, Ui_Sobre):
    """Customization for Qt Designer created window"""
    def __init__(self, parent=None):
        # initialization of the superclass
        super(AboutWindow, self).__init__(parent)
        # setup the GUI --> function generated by pyuic5
        self.setupUi(self)

class StartupErrorWindow(QtWidgets.QMainWindow, Ui_StartupError):
    signal_retry_startup = QtCore.pyqtSignal(bool)
    """Customization for Qt Designer created window"""
    def __init__(self, parent=None):
        # initialization of the superclass
        super(StartupErrorWindow, self).__init__(parent)
        # setup the GUI --> function generated by pyuic5
        self.setupUi(self)
        self.startup_error_btn.clicked.connect(self.try_restart)

    def try_restart(self):
        self.signal_retry_startup.emit(True)
        self.close()

if __name__ == "__main__":
    # %% Calling the main window
    app = QtWidgets.QApplication(sys.argv)
    dmw = DesignerMainWindow()
    # dmw.show()
    dmw.showFullScreen()
    

    sys.exit(app.exec_())
    #app.exec_()