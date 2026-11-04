# NI USB-6363 Monitor & Output Controller

**File:** `ni_measurment.py`  
**Author:** NI DAQ Monitor project  
**Python version:** 3.x (tested with Python 3.8+)  
**Dependencies:** `nidaqmx`, `matplotlib`, `numpy`, `tkinter` (standard library)

A graphical and command-line application for monitoring and controlling National Instruments USB-6363 (and compatible) DAQ devices. It reads all analog and digital inputs, graphs them live in an auto-resizing window, and provides controls to drive analog and digital outputs. It also includes a **Network Analyzer** mode for detecting pin-to-pin wire bridges and logic gate behavior between digital I/O lines.

---

## Table of Contents

1. [Overview](#overview)
2. [Key Features](#key-features)
3. [Requirements](#requirements)
4. [Installation](#installation)
5. [Quick Start](#quick-start)
6. [GUI Mode](#gui-mode)
7. [CLI / Command-Line Mode](#cli-command-line-mode)
8. [CLI Argument Reference](#cli-argument-reference)
9. [Network Analyzer](#network-analyzer)
10. [Architecture & Code Structure](#architecture--code-structure)
11. [Class & Function Reference](#class--function-reference)
12. [Configuration Constants](#configuration-constants)
13. [Safety Warnings](#safety-warnings)
14. [Troubleshooting](#troubleshooting)
15. [File Layout](#file-layout)

---

## Overview

This script is a full-featured NI-DAQmx client application with two operating modes:

| Mode | Description |
|------|-------------|
| **GUI** | A Tkinter desktop window with live scrolling graphs of all analog and digital inputs, plus control panels for analog outputs (AO) and digital outputs (DO). |
| **CLI** | A headless command-line mode for automation, scripting, and one-shot reads/writes of AI/AO/DI/DO channels, plus continuous monitoring and Network Analyzer runs. |

The application auto-discovers connected NI DAQ devices, queries their channel capabilities (analog input/output channels, digital input/output lines, voltage ranges), and configures the UI dynamically based on what the hardware reports.

---

## Key Features

### Input Monitoring
* **Analog Inputs (AI):** Reads all configured AI voltage channels continuously. Each channel is plotted in its own color on a shared time axis.
* **Digital Inputs (DI):** Reads all digital input lines (port 0) continuously. Each line is plotted as a step waveform (LOW/HIGH) on a shared time axis.
* **Auto-resizing graphs:** The plot window resizes with the window; the time window scrolls automatically to show the most recent `HISTORY_SECONDS` (default 10 seconds).
* **Live data buffering:** Samples are stored in `collections.deque` rings with a fixed maximum length, so memory usage stays constant during long runs.

### Output Control
* **Analog Outputs (AO 0–3):** Per-channel enable checkbox + voltage textbox (in volts). Values are clamped to the device's reported AO voltage range.
* **Digital Outputs (DO PFI 0–15):** Per-line enable checkboxes. Drives lines HIGH/LOW.
* **Apply buttons:** "Apply All Analog Outputs" and "Apply All Digital Outputs" push the current UI values to the hardware at once.

### Network Analyzer (Pin Connection & Logic Detection)
* **Single-pin tests:** Drives each DIO line HIGH one at a time, reads all other lines as inputs, and reports which lines respond (possible wire bridges or logic connections).
* **Bidirectional pair detection:** Finds pin pairs where each pin affects the other.
* **Logic gate detection (Phase 2):** For every pair of output pins, drives all 4 combinations (00, 01, 10, 11) and reads every remaining pin. Matches the observed 2-bit truth table against a table of 16 standard logic gates (AND, OR, XOR, NAND, NOR, XNOR, buffers, inverters, constants, etc.).
* **Combinational network detection:** Detects gate chains where the output of one gate feeds into the input of another.
* **Results:** Printed to console (CLI) or shown in a scrollable results window (GUI), with optional CSV export.

---

## Requirements

| Package | Purpose | Install |
|---------|---------|---------|
| Python 3.8+ | Runtime interpreter | https://python.org |
| `nidaqmx` | NI-DAQmx Python driver | `pip install nidaqmx` |
| `matplotlib` | Plotting engine | `pip install matplotlib` |
| `numpy` | Numerical arrays | `pip install numpy` |
| `tkinter` | GUI toolkit (usually bundled with Python) | Built-in on most installs |

### One-line install
```bash
pip install nidaqmx matplotlib numpy
```

> **Note:** You must also have the **NI-DAQmx runtime or full driver** installed on the machine for `nidaqmx` to communicate with hardware. Without it, the script runs in a degraded mode (no hardware access) but still compiles and the UI will open.

---

## Quick Start

### GUI mode (recommended for first use)
```bash
python ni_measurment.py
```

### CLI mode examples
```bash
# List connected NI DAQ devices
python ni_measurment.py --cli --list-devices

# Read all analog inputs once
python ni_measurment.py --cli --read-ai --device Dev1

# Read all digital inputs once
python ni_measurment.py --cli --read-di --device Dev1

# Write 5.0 V to analog output ao0
python ni_measurment.py --cli --write-ao ao0 5.0 --device Dev1

# Set digital output port1/line0 HIGH
python ni_measurment.py --cli --write-do port1/line0 HIGH --device Dev1

# Continuous monitoring every 0.5 s
python ni_measurment.py --cli --monitor --device Dev1 --interval 0.5

# Run Network Analyzer (default 1 ms pulses)
python ni_measurment.py --cli --analyze --device Dev1

# Run Network Analyzer with 2 ms pulses
python ni_measurment.py --cli --analyze --device Dev1 --pulse-width 2.0
```

---

## GUI Mode

When launched without `--cli`, a Tkinter window opens titled **"NI USB-6363 Monitor & Output Controller"**.

### Layout

```
+---------------------------------------------------------------+
| Device: [Combobox]  [Refresh]                DAQ: stopped    |
+-------------------------------+-------------------------------+
|                               |                               |
|   Controls (scrollable)       |   Live Graphs               |
|                               |                               |
|   - Analog Outputs            |   Analog Inputs (all ch)    |
|   - Digital Outputs           |   Digital Inputs (all lines)|
|   - Network Analyzer          |                               |
|   - Device Info               |                               |
|                               |                               |
+-------------------------------+-------------------------------+
```

### Controls Panel
1. **Device selector** – Choose which NI DAQ device to use. Clicking **Refresh** re-scans for devices.
2. **Analog Outputs** – For each AO channel:
   - **Enable** checkbox
   - **Voltage (V)** text entry
   - **Channel** label (short name + device)
   - **Apply All Analog Outputs** button sends all enabled voltages at once.
3. **Digital Outputs** – For each DO line: a checkbox labeled with the short line name. **Apply All Digital Outputs** sends all states at once.
4. **Network Analyzer** – Pulse width entry (ms), "Run Network Analyzer" button, and an option to include analog output monitoring.
5. **Device Info** – Read-only summary of AI/AO/DI/DO counts and voltage ranges.

### Graphs Panel
* **Top graph:** Analog Inputs (all channels) – Voltage (V) vs Time (s). One colored line per AI channel.
* **Bottom graph:** Digital Inputs (all lines) – Level (0/1) vs Time (s). One step line per DI line.
* Graphs auto-scroll to show the most recent 10 seconds of data.

---

## CLI / Command-Line Mode

Launch with `--cli` (or any action flag such as `--read-ai`, `--list-devices`, etc.) to run headless. A `USB6363App` instance is created internally with `root=None` and `cli_mode=True`.

### Typical CLI workflow
```bash
# 1. See what's connected
python ni_measurment.py --cli --list-devices

# 2. Read inputs
python ni_measurment.py --cli --read-ai --device Dev1
python ni_measurment.py --cli --read-di --device Dev1

# 3. Control outputs
python ni_measurment.py --cli --write-ao ao0 3.3 --device Dev1
python ni_measurment.py --cli --write-do port1/line0 HIGH --device Dev1

# 4. Monitor continuously (Ctrl+C to stop)
python ni_measurment.py --cli --monitor --device Dev1 --interval 0.25

# 5. Run Network Analyzer and save CSV
python ni_measurment.py --cli --analyze --device Dev1 --pulse-width 1.0
```

Exit codes: `0` = success, `1` = error.

---

## CLI Argument Reference

| Argument | Type | Description |
|----------|------|-------------|
| `--cli` | flag | Run in command-line mode instead of GUI |
| `--device` | string | NI DAQ device name (e.g. `Dev1`). Auto-detected if omitted |
| `--list-devices` | flag | List all connected NI DAQ devices and exit |
| `--read-ai` | flag | Read all analog input channels once and print values |
| `--read-di` | flag | Read all digital input lines once and print states |
| `--write-ao` | 2 values | `<CHANNEL> <VOLTAGE>` – Write voltage to an analog output (e.g. `ao0 5.0`) |
| `--write-do` | 2 values | `<LINE> <STATE>` – Set a digital output line (e.g. `port1/line0 HIGH`) |
| `--monitor` | flag | Continuously monitor inputs until Ctrl+C |
| `--interval` | float | Monitoring interval in seconds (default `0.5`) |
| `--analyze` | flag | Run Network Analyzer (pin bridge & logic gate detection) |
| `--pulse-width` | float | Pulse width in ms for Network Analyzer (default `1.0`) |

### CLI output examples

**`--read-ai`**
```
Device: Dev1
  AI channels: 16
  ...

Analog Inputs (16 channels):
  ai0: +2.4135 V
  ai1: +0.0012 V
  ...
```

**`--read-di`**
```
Digital Inputs (8 lines):
  HIGH lines: ['port0/line2', 'port0/line5']
  port0/line0: LOW
  port0/line1: LOW
  port0/line2: HIGH
  ...
```

**`--monitor`**
```
Monitoring Dev1 every 0.5s (Ctrl+C to stop)...

[14:32:10] Sample #1
  ai0: +2.4135 V
  ai1: +0.0012 V
  DI HIGH: ['port0/line2']

[14:32:10] Sample #2
  ...
```

---

## Network Analyzer

The Network Analyzer helps you debug external wiring connected to the DAQ's digital I/O lines. It answers questions like: *"Is pin A shorted to pin B?"* or *"Does driving pin A HIGH cause pin C to go HIGH through some external logic?"*

### How it works

**Phase 1 – Single-pin tests**
For each DIO line:
1. Configure that line as a digital output; all other DIO lines as digital inputs.
2. Read the baseline state of all input lines.
3. Drive the output line HIGH for `pulse_ms` milliseconds.
4. Read the inputs again while HIGH.
5. Drive the output LOW.
6. Any input that went from LOW → HIGH is recorded as "affected by" that output.

**Bidirectional pairs:** If output A affects input B AND output B affects input A, the pair is flagged as a directly connected / bidirectionally coupled pair.

**Phase 2 – Full truth table (logic gate detection)**
For every unordered pair of output pins `(A, B)`:
1. Drive A and B through all 4 combinations: (0,0), (0,1), (1,0), (1,1).
2. After each combination, read all remaining DIO lines as inputs.
3. Build a 4-bit truth table for each remaining output line.
4. Match the truth table against a built-in table of 16 logic patterns:

| Truth (00,01,10,11) | Gate Name | Symbol | Meaning |
|---------------------|-----------|--------|---------|
| 0,0,0,0 | CONST_0 | `0` | Always low |
| 0,0,0,1 | AND | `&` | A AND B |
| 0,0,1,0 | A_AND_NOT_B | `A & ~B` | A and not B |
| 0,0,1,1 | BUFFER_B | `B` | Follows B |
| 0,1,0,0 | NOT_A_AND_B | `~A & B` | Not A and B |
| 0,1,0,1 | BUFFER_A | `A` | Follows A |
| 0,1,1,0 | XOR | `^` | A XOR B |
| 0,1,1,1 | OR | `\|` | A OR B |
| 1,0,0,0 | NOR | `~(A\|B)` | Not (A or B) |
| 1,0,0,1 | XNOR | `~(A^B)` | A XNOR B |
| 1,0,1,0 | NOT_B | `~B` | Not B |
| 1,0,1,1 | B_OR_NOT_A | `B \| ~A` | B or not A |
| 1,1,0,0 | NOT_A | `~A` | Not A |
| 1,1,0,1 | A_OR_NOT_B | `A \| ~B` | A or not B |
| 1,1,1,0 | NAND | `~(A&B)` | Not (A and B) |
| 1,1,1,1 | CONST_1 | `1` | Always high |

**Phase 3 – Combinational networks**
Detects chains where the output of one detected gate is used as an input to another detected gate.

### Safety
Before running the analyzer, the GUI shows a warning dialog:
* Ensure no external voltage sources are connected to the pins being tested.
* Pulse width is kept short (default 1 ms) to protect connected chips.
* Only one or two lines are driven at a time.

### Results output
* **GUI:** A scrollable results window opens with bridges, gates, and networks listed. An **Export to CSV** button saves results.
* **CLI:** Results are printed to the console and automatically saved to `na_results_<device>_<timestamp>.csv` in the current folder.

---

## Architecture & Code Structure

The script is a single file (`ni_measurment.py`) organized as follows:

### Module-level helpers
* `discover_devices()` – Returns a list of NI device names (e.g. `["Dev1"]`). Returns `[]` if `nidaqmx` is unavailable.
* `get_device_capabilities(device_name)` – Queries the device for AI/AO channels, DI/DO lines, and voltage ranges. Falls back to safe defaults if hardware is missing.
* `_extract_names(obj)` / `_line_name(obj)` – Utility to extract human-readable names from NI-DAQmx channel objects.

### Class: `USB6363App`
The main application class. Holds all state (buffers, tasks, UI variables, DAQ thread) and methods.

**Key state attributes:**
* `ai_buffer` / `di_buffer` – `deque` rings of `(timestamp, values)` tuples.
* `ao_task` / `do_task` – `nidaqmx.Task` objects for output control.
* `running` / `stop_event` – DAQ loop control flags.
* `ao_values` / `do_values` – Current output values being driven.

**Major methods:**
* `__init__` / `_build_ui` – Initialize state and build the Tkinter interface.
* `_rebuild_controls` / `_rebuild_plots` – Rebuild UI when a new device is selected.
* `_start_daq` / `_daq_loop` – Start/stop the background acquisition thread that reads AI/DI at `READ_PERIOD` (50 ms).
* `_update_plots` – Called from the Tkinter main loop to refresh the matplotlib canvases.
* `_open_output_tasks` / `_close_output_tasks` – Lazily create and destroy NI output tasks.
* AO/DO methods: `_ao_enable_toggle`, `_ao_voltage_commit`, `_apply_ao`, `_write_ao`, `_do_toggle`, `_apply_do`, `_write_do`.
* Network Analyzer: `_test_pin_connections`, `_run_na_analysis`, `_finalize_na_gui`, `_open_na_results_window`, `_print_cli_na_results`, `_save_cli_na_csv`.
* Shutdown: `_on_close`.

### Function: `run_cli(args, app)`
Handles every CLI sub-command (`--list-devices`, `--read-ai`, `--read-di`, `--write-ao`, `--write-do`, `--monitor`, `--analyze`). Returns an exit code.

### Function: `main()`
Parses `argparse` arguments, decides GUI vs CLI, creates the `USB6363App`, and starts either `root.mainloop()` or `run_cli()`.

---

## Class & Function Reference

### `discover_devices() -> list[str]`
Returns names of discovered NI DAQ devices. Safe to call without hardware; returns `[]`.

### `get_device_capabilities(device_name) -> dict`
Returns a dictionary with keys:
* `ai_channels` – list of AI channel names
* `ao_channels` – list of AO channel names
* `di_lines` – list of DI line names
* `do_lines` – list of DO line names
* `ai_ranges` – list of `(min, max)` voltage tuples
* `ao_ranges` – list of `(min, max)` voltage tuples

### `USB6363App(root=None, cli_mode=False)`
Main application object.

### `run_cli(args, app) -> int`
CLI dispatcher. Returns process exit code.

### `main() -> int`
Program entry point. Returns process exit code.

---

## Configuration Constants

Edit the top of the file to tune behavior:

| Constant | Default | Meaning |
|----------|---------|---------|
| `DEFAULT_DEVICE` | `""` | Pre-selected device name (empty = first discovered) |
| `AI_MIN, AI_MAX` | `-10.0, 10.0` | Default analog input voltage range |
| `AO_MIN, AO_MAX` | `-10.0, 10.0` | Default analog output voltage range |
| `HISTORY_SECONDS` | `10.0` | Seconds of history shown on the graphs |
| `READ_PERIOD` | `0.05` | DAQ read interval in seconds (50 ms = 20 Hz) |
| `UI_UPDATE_PERIOD` | `50` | Tkinter plot refresh interval in milliseconds |

---

## Safety Warnings

1. **Voltage limits:** The USB-6363 analog outputs are typically ±10 V. Do not connect outputs to external voltage sources higher than the device rating.
2. **Network Analyzer:** This mode actively drives digital lines HIGH. Make sure:
   * No external power supplies are wired to the test pins.
   * Connected chips can tolerate brief 3.3 V / 5 V pulses.
   * Only one or two lines are driven at any instant.
3. **Short circuits:** If you suspect a wire bridge, use the lowest practical pulse width (`--pulse-width`) to minimize current.
4. **Grounding:** Ensure your external circuit shares a common ground with the DAQ device (AO GND / DGND).

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `nidaqmx is not installed` | Missing Python package | `pip install nidaqmx` |
| `No NI DAQ devices found` | NI-DAQmx driver not installed or device not connected | Install NI-DAQmx runtime; check USB connection; run `--list-devices` |
| `IndentationError` / `SyntaxError` | Corrupted file | Re-download or re-copy the file; the current version compiles cleanly |
| Graphs are empty | DAQ not running or no AI/DI channels | Select a device; click the status area; ensure AI/DI channels exist |
| Output voltage doesn't change | Output task not open or channel disabled | Check the **Enable** checkbox; click **Apply All Analog Outputs** |
| CLI returns exit code 1 | DAQ error or invalid argument | Check the printed error message; verify `--device` name matches `--list-devices` output |

To verify the file has no syntax errors:
```bash
python -m py_compile ni_measurment.py
```

---

## File Layout

```
USBtester/
├── ni_measurment.py          # Main application (this file)
├── test_ni_usb6363_monitor.py # Test/support script
├── venv/                     # Python virtual environment
└── README.md                 # This file
```

> **Note on filename:** The file is named `ni_measurment.py` (missing the second "e" in "measurement"). The code works correctly under this name. If you prefer the correctly spelled `ni_measurement.py`, you can rename the file and update any launch commands accordingly.

---

## License / Disclaimer

This software is provided as-is for educational and test-automation purposes. The author is not responsible for damage to NI hardware or connected circuits caused by misuse of the output controls or Network Analyzer. Always verify wiring and voltage limits before applying outputs.