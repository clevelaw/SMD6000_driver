import serial
import time
import threading
import queue
import tkinter as tk
from tkinter import ttk, messagebox
import io
import re


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

    def DONT_send_command(self, cmd):
        """
        Send a single command and return the response string.
        Must only be called from the worker thread — not thread-safe.
        """
        # self._ser.reset_input_buffer()
        # self._ser.reset_output_buffer()
        print(f"Sending: {cmd}")
        self._io.write(cmd + '\r')
        self._io.flush()

        echo = self._io.readline()
        print(f"Controller response: {echo.strip()}")
        print("-----")
        return echo.strip()

    def send_command(self, cmd):
        """
        Send a single command and return the response string.
        Must only be called from the worker thread — not thread-safe.
        """
        # self._ser.reset_input_buffer()
        # self._ser.reset_output_buffer()
        print(f"Sending: {cmd}")
        self._io.write(cmd + '\r')
        self._io.flush()
        b = self._io.read()

        print("Return\n", b, "-------")
        return b

    # Not implemented: "STEN=YES/NO", "STPOW=###", write_apc, recalibrate, query_power, query_version
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

        # control
        ctrl_frame = ttk.LabelFrame(self.root, text="Power")
        ctrl_frame.grid(row=1, column=0, padx=10, pady=10, sticky="ew")
        self.on_btn = ttk.Button(
            ctrl_frame, text="Laser ON", command=self.laser_on, state="disabled"
        )
        self.on_btn.grid(row=0, column=0, padx=5, pady=5)
        self.off_btn = ttk.Button(
            ctrl_frame, text="Laser OFF", command=self.laser_off, state="disabled"
        )

        # power
        power_frame = ttk.LabelFrame(self.root, text="Control")
        power_frame.grid(row=2, column=0, padx=10, pady=10, sticky="ew")
        self.off_btn.grid(row=0, column=1, padx=5, pady=5)
        ttk.Button(power_frame, text="Power Mode",
                   command=self.set_power_mode).grid(row=0, column=0, pady=5)
        ttk.Button(power_frame, text="Current Mode",
                   command=self.set_current_mode).grid(row=0, column=1, pady=5)
        ttk.Label(power_frame, text="Current (%):").grid(
            row=2, column=0, pady=5)
        self.current_scale = ttk.Scale(
            power_frame, from_=0, to=100, command=self._on_current_change
        )
        self.current_scale.grid(row=2, column=1, pady=5)
        self._current_after_id = None

        self.power_entry = ttk.Entry(power_frame, width=10)
        self.power_entry.grid(row=1, column=1)
        ttk.Button(power_frame, text="Set Power",
                   command=self.set_power).grid(row=1, column=0, padx=5)

        # status
        status_frame = ttk.LabelFrame(self.root, text="Status")
        status_frame.grid(row=3, column=0, padx=10, pady=10, sticky="ew")
        self.status_label = ttk.Label(status_frame, text="Disconnected")
        self.status_label.grid(row=0, column=0, padx=5)
        ttk.Button(status_frame, text="Refresh Status",
                   command=self.refresh_status).grid(row=0, column=1, padx=5)

        # temperature
        temp_frame = ttk.LabelFrame(self.root, text="Live info")
        temp_frame.grid(row=4, column=0, padx=10, pady=10, sticky="ew")
        self.temp_label = ttk.Label(temp_frame, text="None so far")
        self.temp_label.grid(row=0, column=0, padx=5)

        ttk.Label(temp_frame, text="Laser Temp").grid(row=0, column=0, padx=5)
        self.laser_temp_bar = ttk.Progressbar(
            temp_frame, orient="horizontal", length=200, mode="determinate"
        )
        self.laser_temp_bar.grid(row=0, column=1, padx=5)
        self.laser_temp_label = ttk.Label(temp_frame, text="-- °C")
        self.laser_temp_label.grid(row=0, column=2, padx=5)

        ttk.Label(temp_frame, text="PSU Temp").grid(row=1, column=0, padx=5)
        self.psu_temp_bar = ttk.Progressbar(
            temp_frame, orient="horizontal", length=200, mode="determinate"
        )
        self.psu_temp_bar.grid(row=1, column=1, padx=5)
        self.psu_temp_label = ttk.Label(temp_frame, text="-- °C")
        self.psu_temp_label.grid(row=1, column=2, padx=5)

        # power bar
        ttk.Label(temp_frame, text="Power").grid(row=3, column=0, padx=5)
        self.laser_power_bar = ttk.Progressbar(
            temp_frame, orient="horizontal", length=200, mode="determinate"
        )
        self.laser_power_bar.grid(row=3, column=1, padx=5)
        self.laser_power_label = ttk.Label(temp_frame, text="-- W")
        self.laser_power_label.grid(row=3, column=2, padx=5)
        # current bar
        ttk.Label(temp_frame, text="Current").grid(row=4, column=0, padx=5)
        self.laser_current_bar = ttk.Progressbar(
            temp_frame, orient="horizontal", length=200, mode="determinate"
        )
        self.laser_current_bar.grid(row=4, column=1, padx=5)
        self.laser_current_label = ttk.Label(temp_frame, text="-- %")
        self.laser_current_label.grid(row=4, column=2, padx=5)

        ttk.Button(temp_frame, text="Get Temps", command=self.get_temps)\
            .grid(row=2, column=1, pady=5)

        # PSU info
        timers_frame = ttk.LabelFrame(self.root, text="PSU info")
        timers_frame.grid(row=5, column=0, padx=10, pady=10, sticky="ew")

        ttk.Label(timers_frame, text="PSU Time:").grid(
            row=0, column=0, padx=5, sticky="w")
        self.psu_time_label = ttk.Label(timers_frame, text="--")
        self.psu_time_label.grid(row=0, column=1, padx=5, sticky="w")

        ttk.Label(timers_frame, text="Laser Time:").grid(
            row=1, column=0, padx=5, sticky="w")
        self.laser_time_label = ttk.Label(timers_frame, text="--")
        self.laser_time_label.grid(row=1, column=1, padx=5, sticky="w")

        ttk.Label(timers_frame, text="Laser >1A Time:").grid(
            row=2, column=0, padx=5, sticky="w")
        self.laser_1a_time_label = ttk.Label(timers_frame, text="--")
        self.laser_1a_time_label.grid(row=2, column=1, padx=5, sticky="w")

        ttk.Button(timers_frame, text="Get Timers", command=self.get_timers)\
            .grid(row=4, column=0, columnspan=2, pady=5)

        ttk.Label(timers_frame, text="Firmware:").grid(
            row=3, column=0, padx=5, sticky="w")
        self.firmware_label = ttk.Label(timers_frame, text="--")
        self.firmware_label.grid(row=3, column=1, padx=5, sticky="w")

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
            t1 = self._parse_temp(r)
            if t1 is not None:
                self.laser_temp_bar["value"] = t1
                self.laser_temp_label.config(text=f"{t1:.1f} °C")
                self.laser_temp_bar["maximum"] = 50
                self.psu_temp_bar["maximum"] = 50

            self._enqueue(
                self.laser.query_psu_temp(),
                callback=on_psu_temp
            )

        def on_psu_temp(r):
            t2 = self._parse_temp(r)
            if t2 is not None:
                self.psu_temp_bar["value"] = t2
                self.psu_temp_label.config(text=f"{t2:.1f} °C")
                self.psu_temp_bar["maximum"] = 100

        self._enqueue(self.laser.query_laser_temp(), callback=on_laser_temp)

    def get_timers(self):
        def callback(response):
            parsed = self._parse_timers(response)

            if parsed["psu"] is not None:
                self.psu_time_label.config(text=parsed["psu"])

            if parsed["laser"] is not None:
                self.laser_time_label.config(text=parsed["laser"])

            if parsed["laser_1a"] is not None:
                self.laser_1a_time_label.config(text=parsed["laser_1a"])

            if parsed["firmware"] is not None:
                self.firmware_label.config(text=parsed["firmware"])

        self._enqueue(self.laser.query_timers(), callback=callback)
        self._enqueue(self.laser.query_version(), callback=callback)

    # helpers
    def _set_status(self, text):
        self.status_label.config(text=text)

    def _set_temps(self, text):
        self.temp_label.config(text=text)

    def _parse_temp(self, response: str):
        try:
            # Extract first number found in response
            match = re.search(r"[-+]?\d*\.?\d+", response)
            return float(match.group()) if match else None
        except:
            return None

    def _parse_timers(self, response: str):
        result = {
            "psu": None,
            "laser": None,
            "laser_1a": None,
            "firmware": None
        }

        for line in response.splitlines():
            if "PSU Time" in line:
                result["psu"] = line.split("=")[-1].strip()
            elif "Laser Time" in line and "> 1A" not in line:
                result["laser"] = line.split("=")[-1].strip()
            elif "Laser > 1A Time" in line:
                result["laser_1a"] = line.split("=")[-1].strip()

        return result


if __name__ == "__main__":
    root = tk.Tk()
    app = LaserGUI(root)
    root.protocol("WM_DELETE_WINDOW", lambda: (
        app.disconnect(), root.destroy()))
    root.mainloop()
