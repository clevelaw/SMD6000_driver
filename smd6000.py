import serial
import time
import threading
import queue
import tkinter as tk
from tkinter import ttk, messagebox
import io


class MPCLaser:
    """
    Resources:
        Adapter used: USB to RS232, USB Serial Adapter with FTDI Chipset
        Pinout for laser: https://www.directed-energy.net/laser/ignis.html

    Laser Controller:
    Version: SMD12/6H-3.1.0
    Model: EXCEL FS SMD6000

    Lasers:
    Green
        Brand: excel HP
        Power range: 50mW to 2W
        532nm > 0.5W
        1064nm < 1.0mW
    Red
        Brand: ignis HP
        Power range: 50mW to 1W
        660nm > 0.5W
        1320nm < 1.0mW


    RS232 configuration:
        Baud Rate: 9600
        Parity: None
        Stop Bits: 1
        Hand Shaking: None

    RS232 wiring:
        Adapter pin 2 → PSU pin 2  (RX <- TX)
        Adapter pin 3 → PSU pin 3  (TX -> RX)
        Adapter pin 5 → PSU pin 5  (GND -> GND)

    Control port  connections (DB9):
        Pin 1 — Pin 4  (max power enable)
        Pin 3 — Pin 8  (enable switch)
        Pin 5 — Pin 6  (interlock) or
            Pin 2 — Pin 6

    Errors:
    Wrong signals sent to the controller will result in 
    "ERROR:COMMAND- XX
    Where XX represents the hexadecimal value for the first letter of the incrorrect command
    """

    def __init__(self, port):
        self._ser = serial.Serial(
            port=port,
            baudrate=9600,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=3,
            rtscts=False,
            dsrdtr=False,
            xonxoff=False
        )

        self._io = io.TextIOWrapper(
            io.BufferedRWPair(self._ser, self._ser),
            encoding='ascii',
            errors='ignore'
        )

    def send_command(self, cmd):
        """
        Send a single command and return the response string.
        Must only be called from the worker thread — not thread-safe.
        """
        self._ser.reset_input_buffer()
        self._ser.reset_output_buffer()
        print(f"Sending: {cmd}")
        self._io.write(cmd + '\r')
        self._io.flush()

        echo = self._io.readline()
        print(f"Controller response: {echo.strip()}")
        print("-----")
        return echo.strip()

    # Not implemented: "STEN=YES/NO", "STPOW=###", write_apc, recalibrate, query_timers, query_power, query_version
    # "STAT?" and not "STATUS?"
    # https://novantaphotonics.com/wp-content/uploads/2022/05/gem_with_mpc_6000_Novanta_Product_Manual.pdf
    def laser_off(self): return "OFF"
    def laser_on(self): return "ON"
    def current_mode(self): return "CONTROL=CURRENT"
    def power_mode(self): return "CONTROL=POWER"
    def set_current(self, pct): return f"CURRENT={int(pct)}"
    def set_power(self, mw): return f"POWER={int(mw)}"
    def query_power(self): return "POWER?"
    def query_status(self): return "STAT?"
    def query_laser_temp(self): return "LASTEMP?"
    def query_psu_temp(self): return "PSUTEMP?"
    def query_timers(self): return "TIMERS?"
    def query_version(self): return "VERSION?"
    def write_apc(self): return "WRITE"
    def recalibrate(self, mw): return f"ACTP={int(mw)}"

    def close(self):
        try:
            self._io.flush()
        except Exception:
            print("Failed to flush during close")
            pass
        self._ser.close()


class LaserGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("SMD6000 Laser Controller")
        self.laser = None

        # Command queue: each item is (command_string, optional_callback)
        # The callback receives the response string and runs on the main thread.
        self._cmd_queue = queue.Queue()
        self._worker_thread = None
        self._build_ui()

    def _build_ui(self):
        # TODO: Select Laser type
        """
        532nm - 50mW to 2W
        660nm - 50mW to 1W
        """
        # connection
        conn_frame = ttk.LabelFrame(self.root, text="Connection")
        conn_frame.grid(row=0, column=0, padx=10, pady=10, sticky="ew")
        ttk.Label(conn_frame, text="COM Port:").grid(row=0, column=0, padx=4)
        self.port_entry = ttk.Entry(conn_frame, width=10)
        self.port_entry.insert(0, "COM6")
        self.port_entry.grid(row=0, column=1)
        self.connect_btn = ttk.Button(
            conn_frame, text="Connect", command=self.connect)
        self.connect_btn.grid(row=0, column=2, padx=5)

        self.disconnect_btn = ttk.Button(
            conn_frame, text="Disconnect", command=self.disconnect, state="disabled"
        )
        self.disconnect_btn.grid(row=0, column=3, padx=5)

        #  control
        ctrl_frame = ttk.LabelFrame(self.root, text="Control")
        ctrl_frame.grid(row=1, column=0, padx=10, pady=10, sticky="ew")
        self.on_btn = ttk.Button(
            ctrl_frame, text="Laser ON", command=self.laser_on, state="disabled"
        )
        self.on_btn.grid(row=0, column=0, padx=5, pady=5)
        self.off_btn = ttk.Button(
            ctrl_frame, text="Laser OFF", command=self.laser_off, state="disabled"
        )
        self.off_btn.grid(row=0, column=1, padx=5, pady=5)
        ttk.Button(ctrl_frame, text="Power Mode",
                   command=self.set_power_mode).grid(row=1, column=0, pady=5)
        ttk.Button(ctrl_frame, text="Current Mode",
                   command=self.set_current_mode).grid(row=1, column=1, pady=5)
        ttk.Label(ctrl_frame, text="Current (%):").grid(
            row=2, column=0, pady=5)
        self.current_scale = ttk.Scale(
            ctrl_frame, from_=0, to=100, command=self._on_current_change
        )
        self.current_scale.grid(row=2, column=1, pady=5)
        self._current_after_id = None

        # power
        power_frame = ttk.LabelFrame(self.root, text="Set Power (mW)")
        power_frame.grid(row=2, column=0, padx=10, pady=10, sticky="ew")
        self.power_entry = ttk.Entry(power_frame, width=10)
        self.power_entry.grid(row=0, column=0)
        ttk.Button(power_frame, text="Set Power",
                   command=self.set_power).grid(row=0, column=1, padx=5)

        # status
        status_frame = ttk.LabelFrame(self.root, text="Status")
        status_frame.grid(row=3, column=0, padx=10, pady=10, sticky="ew")
        self.status_label = ttk.Label(status_frame, text="Disconnected")
        self.status_label.grid(row=0, column=0, padx=5)
        ttk.Button(status_frame, text="Refresh Status",
                   command=self.refresh_status).grid(row=0, column=1, padx=5)

        # temperature
        temp_frame = ttk.LabelFrame(self.root, text="Temperature")
        temp_frame.grid(row=4, column=0, padx=10, pady=10, sticky="ew")
        self.temp_label = ttk.Label(temp_frame, text="None so far")
        self.temp_label.grid(row=0, column=0, padx=5)
        ttk.Button(temp_frame, text="Get Temps",
                   command=self.get_temps).grid(row=0, column=2, padx=5)

    # Worker thread — the only place serial I/O happens
    def _start_worker(self):
        self._worker_thread = threading.Thread(
            target=self._worker_loop, daemon=True)
        self._worker_thread.start()

    def _worker_loop(self):
        """
        Drains the command queue in a background thread.
        Send None as a sentinel to shut down cleanly on disconnect.
        """
        while True:
            item = self._cmd_queue.get()

            if item is None:
                break
            cmd, callback = item
            try:
                response = self.laser.send_command(cmd)
            except Exception as e:
                response = f"ERROR: {e}"
            if callback:
                self.root.after(0, callback, response)
            self._cmd_queue.task_done()

    def _enqueue(self, cmd, callback=None):
        if self.laser is None:
            self._set_status("Not connected")
            return
        self._cmd_queue.put((cmd, callback))

    # connection management
    def connect(self):
        port = self.port_entry.get()
        try:
            self.laser = MPCLaser(port)
            self._start_worker()
            self._set_status("Connected")
            self.on_btn.config(state="normal")
            self.off_btn.config(state="normal")
            self.connect_btn.config(state="disabled")
            self.disconnect_btn.config(state="normal")
        except Exception as e:
            messagebox.showerror("Connection Error:", str(e))

    def disconnect(self):
        if self.laser:
            self._cmd_queue.put(None)
            if self._worker_thread:
                self._worker_thread.join(timeout=5)
            self.laser.close()
            self.laser = None
        self._set_status("Disconnected")
        self.on_btn.config(state="disabled")
        self.off_btn.config(state="disabled")
        self.connect_btn.config(state="normal")
        self.disconnect_btn.config(state="disabled")

    # GUI callbacks
    def laser_on(self):
        self._enqueue(
            self.laser.laser_on(),
            callback=lambda r: self._set_status(f"ON: {r}")
        )

    def laser_off(self):
        self._enqueue(
            self.laser.laser_off(),
            callback=lambda r: self._set_status(f"OFF: {r}")
        )

    def set_power_mode(self):
        self._enqueue(
            self.laser.power_mode(),
            callback=lambda r: self._set_status(f"Power mode: {r}")
        )

    def set_current_mode(self):
        self._enqueue(
            self.laser.current_mode(),
            callback=lambda r: self._set_status(f"Current mode: {r}")
        )

    def _on_current_change(self, value):
        if self._current_after_id:
            self.root.after_cancel(self._current_after_id)
        self._current_after_id = self.root.after(
            400, lambda: self._send_current(float(value))
        )

    def _send_current(self, percent):
        self._enqueue(
            self.laser.set_current(percent),
            callback=lambda r: self._set_status(f"Current set: {r}")
        )

    def set_power(self):
        try:
            value = int(self.power_entry.get())
        except ValueError:
            messagebox.showerror(
                "Error", "Invalid power value")
            return
        self._enqueue(
            self.laser.set_power(value),
            callback=lambda r: self._set_status(f"Power set at: {r}")
        )

    def refresh_status(self):
        self._enqueue(
            self.laser.query_status(),
            callback=lambda r: self._set_status(f"Status: {r}")
        )

    def get_temps(self):
        def on_laser_temp(r):
            self._set_temps(f"Laser temp: {r}")
            self._enqueue(
                self.laser.query_psu_temp(),
                callback=lambda r2: self._set_temps(
                    f"Laser temp: {r} | PSU temp: {r2}")
            )
        self._enqueue(self.laser.query_laser_temp(), callback=on_laser_temp)

    # helpers
    def _set_status(self, text):
        self.status_label.config(text=text)

    def _set_temps(self, text):
        self.temp_label.config(text=text)


if __name__ == "__main__":
    root = tk.Tk()
    app = LaserGUI(root)
    root.protocol("WM_DELETE_WINDOW", lambda: (
        app.disconnect(), root.destroy()))
    root.mainloop()
