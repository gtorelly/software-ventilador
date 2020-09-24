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

UI_UPDATE_FREQUENCY = 20 # Hz
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
            period = 60. / self.gui["VCV_frequency_dSpinBox"].value()
            instant = 0.4
            flow = self.meter.calc_flow(instant)
            volume = self.meter.calc_volume(period)
            pressure = self.gauge.read_pressure()
            self.signal_sensors.emit([flow, volume, pressure])
            time.sleep(UI_UPDATE_PERIOD)
            
class ControlPiston(QtCore.QObject):
    signal_piston = QtCore.pyqtSignal(bool)
    
    def __init__(self, piston, gui):
        super().__init__()
        # receives the piston instance from the call of this worker in the main window
        # assigns the instance to another with the same name.
        self.piston = piston
        self.stop = False
        self.gui = gui
        
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
        
    def mode_PSV(self):
        print("PSV")
                
    def piston_stop(self):  # Redundant with the if inside the while of the piston_auto function
        self.stop = True
        self.signal_piston.emit(False)

class DesignerMainWindow(QtWidgets.QMainWindow, Ui_Respirador):
    """
    Class that corresponds to the programs main windows. The init starts the interface and essential
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
        self.mode_STOP_btn.clicked.connect(lambda: self.modes(0))
        self.piston_auto_btn.clicked.connect(lambda: self.modes(4))

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
                     "VCV_inhale_pause_dSpinBox":self.VCV_inhale_pause_dSpinBox,
                     "VCV_volume_dSpinBox":self.VCV_volume_dSpinBox,
                     "PCV_frequency_dSpinBox":self.PCV_frequency_dSpinBox,
                     "PCV_inhale_pause_dSpinBox":self.PCV_inhale_pause_dSpinBox,
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
        self.data_points = 200
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
        time_range = [-20, 0]
        padding = 0.02
        # TODO Configure a simple autoscale method, because the automatic autoscale slows down the 
        # program
        
        # Configuration of the pressure plot
        self.prs_pw.setBackground(bg_color) # Set the background color
        self.prs_pw.setMenuEnabled(False) # Disables the menu
        # The title size doesn't change with the style
        self.prs_pw.setTitle("Pressão (cm H2O)", **self.styles)
        self.prs_pw.showGrid(x=True, y=True)
        self.prs_pw.setLabel(axis='bottom', text='Tempo (s)', **self.styles)
        self.prs_pw.setXRange(time_range[0], time_range[1], padding=padding)
        self.prs_pw.setYRange(0, 30, padding=padding)
#        prs_pw.setDownsampling(ds=True, auto=True) # Conferir se faz diferença no desempenho
        self.prs_graph = self.prs_pw.plot(self.prs_data[0, :], self.prs_data[1, :], pen=plot_pen)
        
        # Configuration of the flow plot
        self.flw_pw.setBackground(bg_color) # Set the background color
        self.flw_pw.setMenuEnabled(False) # Disables the menu
        # The title size doesn't change with the style
        self.flw_pw.setTitle("Fluxo (l/min)", **self.styles)
        self.flw_pw.showGrid(x=True, y=True)
        self.flw_pw.setXRange(time_range[0], time_range[1], padding=padding)
        self.flw_pw.setYRange(0, 12, padding=padding)
#        flw_pw.setDownsampling(ds=True, auto=True) # Conferir se faz diferença no desempenho
        self.flw_graph = self.flw_pw.plot(self.flw_data[0, :], self.flw_data[1, :], pen=plot_pen)
        
        # Configuration of the volume plot
        self.vol_pw.setBackground(bg_color) # Set the background color
        self.vol_pw.setMenuEnabled(False) # Disables the menu
        # The title size doesn't change with the style
        self.vol_pw.setTitle("Volume (ml)", **self.styles)
        self.vol_pw.showGrid(x=True, y=True)
        self.vol_pw.setXRange(time_range[0], time_range[1], padding=padding)
        self.vol_pw.setYRange(0, 200, padding=padding)
#        vol_pw.setDownsampling(ds=True, auto=True) # Conferir se faz diferença no desempenho
        self.vol_graph = self.vol_pw.plot(self.vol_data[0, :], self.vol_data[1, :], pen=plot_pen)
        # Adding text inside the graph
        self.vol_lbl.setText("TEST")
        # Anchor is the position to which the text will refer in setPos
        self.vol_lbl.setAnchor((1, 1))
        # This is the position of the anchor, in the coordinates of the graph
        self.vol_lbl.setPos(0.0, 0.0)
        
    # Functions that update the interface based on feedback from the threads
    @QtCore.pyqtSlot(list)
    def update_sensors(self, sensor_data):
        current_time = time.time()
        # The incoming data is a list with flow and volume in liters and l/min and pressure in cmH2O
        flow = sensor_data[0]
        volume = sensor_data[1]
        pressure = sensor_data[2]
        
        self.flw_pw.setTitle(f"Fluxo: {round(flow, 1):.1f} l/min", **self.styles)
        self.flw_data = np.roll(self.flw_data, 1)
        self.flw_data[:, 0] = (current_time, flow)
        self.flw_graph.setData(self.flw_data[0, :] - current_time, self.flw_data[1, :])
        # Updates the data that is given to the piston function
        self.worker_piston.flw_data = self.flw_data
        
        # Converting the volume from L to mL
        volume = 1000 * volume
        self.vol_pw.setTitle(f"Volume: {round(volume, 0):.0f} ml", **self.styles)
        self.vol_data = np.roll(self.vol_data, 1)
        self.vol_data[:, 0] = (current_time, volume)
        self.vol_graph.setData(self.vol_data[0, :] - current_time, self.vol_data[1, :])
        # Updates the data that is given to the piston function
        self.worker_piston.vol_data = self.vol_data
        mean_pts = 50
        FPS = np.nan_to_num(1.0 / np.mean(self.vol_data[0, 0:mean_pts] - self.vol_data[0, 1:1+mean_pts]))
        self.vol_lbl.setText(f"FPS: {FPS:.0f}")

        # Calculates the tare to adjust the minimum pressure by getting the 1 percentile
        self.tare = np.percentile(self.prs_data[1, :], 1)
        # Rolls the array
        self.prs_data = np.roll(self.prs_data, 1)
        # inserts the new data in the current i position
        self.prs_data[:, 0] = (current_time, pressure)
        # Update the graph data
        self.prs_graph.setData(self.prs_data[0, :] - current_time, self.prs_data[1, :] - self.tare)
        # Updates the graph title
        self.prs_pw.setTitle(f"Pressão: {round(self.prs_data[1, 0] - self.tare, 1):.1f} cm H2O", **self.styles)
        # Updates the data that is given to the piston function
        self.worker_piston.prs_data = self.prs_data
    
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
        # VCV Tab
        self.VCV_volume_dSpinBox.setValue(300)
        self.VCV_frequency_dSpinBox.setValue(12)
        self.VCV_inhale_pause_dSpinBox.setValue(1)
        self.VCV_flow_dSpinBox.setValue(30)
        # PCV Tab
        self.PCV_pressure_dSpinBox.setValue(20)
        self.PCV_frequency_dSpinBox.setValue(12)
        self.PCV_inhale_time_dSpinBox.setValue(2)
        self.PCV_rise_time_dSpinBox.setValue(1)
        self.PCV_inhale_pause_dSpinBox.setValue(1)
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
        self.current_mode = mode
        if self.current_mode == 1:  # 'VCV'
            self.mode_VCV_btn.setEnabled(False)
            self.mode_PCV_btn.setEnabled(True)
            self.mode_PSV_btn.setEnabled(True)
            self.mode_STOP_btn.setEnabled(True)
            self.piston_auto_btn.setEnabled(True)
            self.tabWidget.setCurrentIndex(0)
        elif self.current_mode == 2:  # 'PCV'
            self.mode_VCV_btn.setEnabled(True)
            self.mode_PCV_btn.setEnabled(False)
            self.mode_PSV_btn.setEnabled(True)
            self.mode_STOP_btn.setEnabled(True)
            self.piston_auto_btn.setEnabled(True)
            self.tabWidget.setCurrentIndex(1)
        elif self.current_mode == 3:  # 'PSV'
            self.mode_VCV_btn.setEnabled(True)
            self.mode_PCV_btn.setEnabled(True)
            self.mode_PSV_btn.setEnabled(False)
            self.mode_STOP_btn.setEnabled(True)
            self.piston_auto_btn.setEnabled(True)
            self.tabWidget.setCurrentIndex(2)
        elif self.current_mode == 4:  # 'Manual Auto'
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