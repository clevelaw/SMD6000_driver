## Overview

This program provides a basic GUI for controlling an Excel FS SMD6000 laser power supply unit (PSU) over an RS232 serial connection. It has been tested and verified working on Firmware version SMD12/6H-3.1.0 with the following lasers:

| Color | Brand | Wavelength | Power Range |
|-------|-------|------------|-------------|
| Green | Excel HP | 532 nm (1064 nm leakage < 1 mW) | 50 mW – 2 W |
| Red | Ignis HP | 660 nm (1320 nm leakage < 1 mW) | 50 mW – 1 W |

The GUI is built with Python's tkinter library and communicates with the controller using the pyserial library. Serial I/O runs in a dedicated background thread to keep the interface responsive.

---

## Hardware 

In lieu of a dedicated serial port, this was devloped using a USB to RS232 adapter with FTDI chipset bought on Amazon


### RS232 Configuration
     Baud Rate: 9600
     Parity: None
     Stop Bits: 1
     Hand Shaking: None

### RS232 Wiring

| Adapter Pin | PSU Pin | Signal |
|-------------|---------|--------|
| Pin 2 | Pin 2 | RX ← TX |
| Pin 3 | Pin 3 | TX → RX |
| Pin 5 | Pin 5 | GND |

The controller will detect a "valid" input if pin 3 has a negative voltage applied to it.

### Control Port Connections

| Connection | Purpose |
|------------|---------|
| Pin 1 - Pin 4 | Max power enable |
| Pin 3 - Pin 8 | Enable switch |
| Pin 5 - Pin 6 | Interlock (or Pin 2 - Pin 6) |

The control port must be wired with the above pins shorted together to enable remote operation via RS232.
---

## Software Architecture

The program is split into two classes:

### SMDLaser

Handles low-level serial communication. Wraps a `serial.Serial` instance in a `TextIOWrapper` for line-oriented ASCII I/O.

**Key methods:**

| Method | Command Sent | Description |
|--------|-------------|-------------|
| `laser_on()` | `ON` | Enable laser output |
| `laser_off()` | `OFF` | Disable laser output |
| `power_mode()` | `CONTROL=POWER` | Switch to APC (power) control mode |
| `current_mode()` | `CONTROL=CURRENT` | Switch to ACC (current) control mode |
| `set_power(mw)` | `POWER=###` | Set output power in mW |
| `set_current(pct)` | `CURRENT=###` | Set diode current as a percentage |
| `query_power()` | `POWER?` | Query current output power |
| `query_current()` | `CURRENT?` | Query current drive level |
| `query_status()` | `STAT?` | Query controller status |
| `query_laser_temp()` | `LASTEMP?` | Query laser head temperature |
| `query_psu_temp()` | `PSUTEMP?` | Query PSU temperature |
| `query_timers()` | `TIMERS?` | Query PSU/laser run-time counters |
| `query_version()` | `VERSION?` | Query firmware version string |
| `send_command(cmd)` | *(any)* | Send a raw command and return the response |

> **Note:** `write_apc()` (`WRITE`) and `recalibrate(mw)` (`ACTP=###`) are defined but not yet exposed in the GUI. There is a `Custom Response` box for using these if desired.

**Error format:** Sending an unrecognised command returns `ERROR:COMMAND-XX`, where `XX` is the hex value of the first character of the bad command. Recognized commands with extra units will still return an error.

---

### `LaserGUI`

Builds the `tkinter` window and manages all user interaction. All serial commands are dispatched through a thread-safe queue (`_cmd_queue`) and executed by a single background worker thread, ensuring the GUI never blocks on I/O.

**Threading model:**

```
Main thread (tkinter)
     ↓
_enqueue(cmd, callback)
     ↓
_cmd_queue → Main thread updates UI
     ↓
_worker_loop (daemon thread)
     ↓
sends command via MPCLaser
     ↓
root.after(0, callback, response)
```

---

## GUI Sections

### Connection

- **COM Port** entry defaults to `COM6`
- **Connect** — opens the serial port and starts the worker thread.
- **Disconnect** — sends a sentinel to shut down the worker thread cleanly, then closes the port.

### Power

- **Laser ON / Laser OFF** — enable or disable laser emission.

### Control

| Control | Description |
|---------|-------------|
| Power Mode | Switch to APC (constant power) mode |
| Current Mode | Switch to ACC (constant current) mode |
| Set Power (mW) | Type a value in the entry box and click |
| Current (%) slider | Drag to set drive current |
| Custom Command | Send any arbitrary RS232 command and display the raw response |

### Status

- Displays the last command result or connection state.
- Refresh Status queries `STAT?` and shows the response.

### Live Info

| Display | Source Command | Range |
|---------|---------------|-------|
| Laser Temp progress bar | `LASTEMP?` | 0 – 50 °C |
| PSU Temp progress bar | `PSUTEMP?` | 0 – 500 °C |
| Power progress bar | `POWER?` | 0 – 2000 mW |
| Current progress bar | `CURRENT?` | 0 – 100 % |

Click **Get Temps** or **Get Power/Current** to refresh the respective bars.

### PSU Info

Displays run-time counters retrieved by `TIMERS?` and the firmware string from `VERSION?`:

- **PSU Time** — total PSU on-time
- **Laser Time** — total laser emission time
- **Laser >1A Time** — time the diode current exceeded 1 A

---
## Running the Program

```bash
python laser_controller.py
```

On Windows the default COM port is `COM6`. On Linux/macOS, change this to the appropriate device path (e.g. `/dev/ttyUSB0`).

---

## TODO

- Add laser type selection. 
     The power bar maximum is hard-coded to 2000 mW
- `WRITE` (save APC calibration) and `ACTP=###` (recalibrate) commands are defined in `MPCLaser` but not exposed as GUI buttons.

---

## References

- Controller manual: [Novanta GEM with MPC 6000 Product Manual](https://novantaphotonics.com/wp-content/uploads/2022/05/gem_with_mpc_6000_Novanta_Product_Manual.pdf)
- Laser pinout: [Directed Energy Ignis](https://www.directed-energy.net/laser/ignis.html)

Note: The closest publically available manual is for the MPC6000. Key differences are the baud rate being lower on the SMD6000 and additional pins being available on the control port for setting the interlock. Additionally, some SMD6000 lasers do not have the ability to be set in current control mode.

Obligatory safety warning, please don't control a Class 4 laser without taking all safety precautions.
