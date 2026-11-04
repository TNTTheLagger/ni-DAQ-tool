#!/usr/bin/env python3
"""
NI USB-6363 Monitor & Output Controller

Reads all analog inputs and all digital inputs, graphs them in one
auto-resizing window, and provides output controls:

* Analog outputs AO 0..3: voltage textbox + enable checkbox
* Digital outputs PFI 0..15: enable checkboxes
* Network Analyzer: input/output graphing with voltage/current graphing

Requirements
------------
    pip install nidaqmx matplotlib numpy

Run
----
    python ni_usb6363_monitor.py          # GUI mode
    python ni_usb6363_monitor.py --cli    # CLI mode
    python ni_usb6363_monitor.py --cli --analyze   # Library/CLI mode
"""

import tkinter as tk
from tkinter import ttk, messagebox
import threading
import time
from collections import deque

import numpy as np

try:
    import nidaqmx
    from nidaqmx.errors import DaqError
    from nidaqmx.system import System
    _HAS_NIDAQMX = True
except Exception:
    nidaqmx = None
    DaqError = Exception
    System = None
    _HAS_NIDAQMX = False

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.pyplot as plt

# --------------------------------------------------------------------------- #
# Configuration constants
# --------------------------------------------------------------------------- #
DEFAULT_DEVICE = ""
AI_MIN, AI_MAX = -10.0, 10.0
AO_MIN, AO_MAX = -10.0, 10.0
HISTORY_SECONDS = 10.0
READ_PERIOD = 0.05
UI_UPDATE_PERIOD = 50


def discover_devices():
    if not _HAS_NIDAQMX:
        return []
    try:
        system = System.local()
        return [d.name for d in system.devices]
    except Exception:
        return []


def get_device_capabilities(device_name):
    caps = {
        "ai_channels": [],
        "ao_channels": [],
        "di_lines": [],
        "do_lines": [],
        "ai_ranges": [(AI_MIN, AI_MAX)],
        "ao_ranges": [(AO_MIN, AO_MAX)],
    }
    if not _HAS_NIDAQMX:
        return caps
    try:
        system = System.local()
        device = None
        for d in system.devices:
            if d.name == device_name:
                device = d
                break
        if device is None:
            return caps
        try:
            caps["ai_channels"] = _extract_names(device.ai_physical_chans)
        except Exception:
            pass
        try:
            caps["ao_channels"] = _extract_names(device.ao_physical_chans)
        except Exception:
            pass
        try:
            caps["di_lines"] = _extract_names(device.di_lines)
        except Exception:
            pass
        try:
            caps["do_lines"] = _extract_names(device.do_lines)
        except Exception:
            pass
        try:
            caps["ai_ranges"] = [(r.min, r.max) for r in device.ai_voltage_rngs]
        except Exception:
            pass
        try:
            caps["ao_ranges"] = [(r.min, r.max) for r in device.ao_voltage_rngs]
        except Exception:
            pass
    except Exception:
        pass
    return caps


def _extract_names(obj):
    names = []
    try:
        for item in obj:
            name = getattr(item, "name", None) or str(item)
            names.append(name)
    except TypeError:
        names = list(obj)
    return names


def _line_name(obj):
    return getattr(obj, "name", None) or str(obj)


class ScrollableFrame(ttk.Frame):
    def __init__(self, parent, *args, **kwargs):
        super().__init__(parent, *args, **kwargs)
        self.canvas = tk.Canvas(self, highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical",
                                       command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas)
        self.inner.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
        )
        self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind_all("<Button-4>",
                             lambda e: self.canvas.yview_scroll(-1, "units"))
        self.canvas.bind_all("<Button-5>",
                             lambda e: self.canvas.yview_scroll(1, "units"))

    def _on_mousewheel(self, event):
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")


class USB6363App:
    def __init__(self, root=None, cli_mode=False):
        self.cli_mode = cli_mode
        self.root = root
        self.device_var = tk.StringVar(value=DEFAULT_DEVICE) if not cli_mode else None
        self.available_devices = discover_devices()
        self.selected_device = tk.StringVar(
            value=self.available_devices[0] if self.available_devices else ""
        ) if not cli_mode else None
        self.device_capabilities = {}
        self.ai_channels = []
        self.ao_channels = []
        self.di_lines = []
        self.do_lines = []
        self.running = False
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.daq_thread = None
        self.t0 = time.perf_counter()
        maxlen = int(HISTORY_SECONDS / READ_PERIOD) + 1
        self.ai_buffer = deque(maxlen=maxlen)
        self.di_buffer = deque(maxlen=maxlen)
        self.ao_task = None
        self.do_task = None
        self.ao_values = []
        self.do_values = []
        self.ao_enable_vars = []
        self.ao_voltage_vars = []
        self.do_vars = []
        self.ai_plot_lines = []
        self.di_plot_lines = []
        self._redraw_pending = False
        self._log_lines = []
        self._na_csv_saved = False

        if not cli_mode:
            self.root.title("NI USB-6363 Monitor & Output Controller")
            self.root.geometry("1300x850")
            self.root.minsize(950, 650)
            self._build_ui()
            self._schedule_plot_update()
            if self.selected_device.get():
                self.root.after(100, self._on_device_selected)
            self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._log("NI DAQ Monitor initialized", "INFO")
        self._log(f"CLI mode: {cli_mode}", "INFO")
        self._log(f"nidaqmx available: {_HAS_NIDAQMX}", "INFO")
        self._log(f"Devices discovered: {self.available_devices}", "INFO")

    def _log(self, message, level="INFO"):
        timestamp = time.strftime("%H:%M:%S")
        log_entry = f"[{timestamp}] [{level}] {message}"
        self._log_lines.append(log_entry)
        if self.cli_mode:
            print(log_entry, flush=True)
        else:
            print(log_entry, flush=True)
            if level in ("ERROR", "WARN", "WARNING"):
                self._set_status(message, "red")
            elif level == "INFO":
                pass

    def _show_error(self, title, message):
        """Show an error dialog with console output and copy-to-clipboard button."""
        print(f"[ERROR] {title}: {message}", flush=True)
        if self.cli_mode:
            return
        win = tk.Toplevel(self.root)
        win.title(title)
        win.geometry("500x250")
        win.resizable(False, False)
        win.transient(self.root)
        win.grab_set()

        ttk.Label(win, text=title, font=("TkDefaultFont", 10, "bold")).pack(
            padx=12, pady=(12, 4), anchor="w")

        text = tk.Text(win, height=6, width=58, wrap="word")
        text.pack(padx=12, pady=(0, 8), fill="both", expand=True)
        text.insert("1.0", message)
        text.configure(state="disabled")

        def copy_to_clipboard():
            win.clipboard_clear()
            win.clipboard_append(message)
            win.update()

        btn_frame = ttk.Frame(win)
        btn_frame.pack(pady=(0, 12))
        ttk.Button(btn_frame, text="Copy to Clipboard",
                   command=copy_to_clipboard).pack(side="left", padx=6)
        ttk.Button(btn_frame, text="OK", command=win.destroy).pack(
            side="left", padx=6)

        # Center on parent
        win.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() // 2) - 250
        y = self.root.winfo_rooty() + (self.root.winfo_height() // 2) - 125
        win.geometry(f"500x250+{x}+{y}")

        self.root.wait_window(win)

    @staticmethod
    def _format_eta(seconds):
        seconds = int(seconds)
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        parts = []
        if hours > 0:
            parts.append(f"{hours}h")
        if minutes > 0 or hours > 0:
            parts.append(f"{minutes}m")
        parts.append(f"{secs}s")
        return " ".join(parts)

    def _build_ui(self):
        top = ttk.Frame(self.root)
        top.grid(row=0, column=0, columnspan=2, sticky="ew", padx=8, pady=6)
        top.grid_columnconfigure(2, weight=1)
        ttk.Label(top, text="Device:").grid(row=0, column=0, sticky="w")
        self.device_combo = ttk.Combobox(
            top, textvariable=self.selected_device,
            values=self.available_devices, state="readonly", width=15
        )
        self.device_combo.grid(row=0, column=1, sticky="w", padx=4)
        self.device_combo.bind("<<ComboboxSelected>>",
                               lambda e: self._on_device_selected())
        ttk.Button(top, text="Refresh", command=self._refresh_devices).grid(
            row=0, column=3, padx=4)
        self.status_var = tk.StringVar(value="DAQ: stopped")
        self.status_label = ttk.Label(top, textvariable=self.status_var,
                                      foreground="gray")
        self.status_label.grid(row=0, column=4, sticky="e", padx=8)
        self.root.grid_rowconfigure(1, weight=1)
        self.root.grid_columnconfigure(0, weight=0, minsize=340)
        self.root.grid_columnconfigure(1, weight=1)
        self.controls_container = ttk.Frame(self.root)
        self.controls_container.grid(row=1, column=0, sticky="nsew",
                                     padx=8, pady=8)
        self.controls_container.grid_rowconfigure(0, weight=1)
        self.controls_container.grid_columnconfigure(0, weight=1)
        self.controls = ScrollableFrame(self.controls_container)
        self.controls.grid(row=0, column=0, sticky="nsew")
        self.plot_frame = ttk.Frame(self.root)
        self.plot_frame.grid(row=1, column=1, sticky="nsew", padx=8, pady=8)
        self.plot_frame.grid_rowconfigure(0, weight=1)
        self.plot_frame.grid_columnconfigure(0, weight=1)
        self._build_plots(self.plot_frame)
        self.plot_frame.bind("<Configure>", lambda e: self._request_redraw())

    def _rebuild_controls(self):
        for widget in self.controls.inner.winfo_children():
            widget.destroy()
        parent = self.controls.inner
        parent.grid_columnconfigure(0, weight=1)
        if not self.ai_channels and not self.di_lines and not self.do_lines:
            ttk.Label(parent, text="No I/O channels found on this device.",
                      foreground="gray").grid(row=0, column=0, pady=20)
            return
        row = 0
        if self.ao_channels:
            ao_frame = ttk.LabelFrame(
                parent, text=f"Analog Outputs ({len(self.ao_channels)} ch)")
            ao_frame.grid(row=row, column=0, sticky="ew", pady=(0, 8))
            ao_frame.grid_columnconfigure(1, weight=1)
            ttk.Label(ao_frame, text="Enable").grid(
                row=0, column=0, padx=4, pady=2)
            ttk.Label(ao_frame, text="Voltage (V)").grid(
                row=0, column=1, padx=4, pady=2)
            ttk.Label(ao_frame, text="Channel").grid(
                row=0, column=2, padx=4, pady=2)
            for i, chan in enumerate(self.ao_channels, start=1):
                en = tk.BooleanVar(value=False)
                ao_min, ao_max = self.device_capabilities.get(
                    "ao_ranges", [(AO_MIN, AO_MAX)])[0]
                val = tk.StringVar(value="0.000")
                cb = ttk.Checkbutton(
                    ao_frame, variable=en,
                    command=lambda ch=i-1: self._ao_enable_toggle(ch))
                cb.grid(row=i, column=0, padx=4, pady=2, sticky="w")
                ent = ttk.Entry(ao_frame, textvariable=val, width=10)
                ent.grid(row=i, column=1, padx=4, pady=2, sticky="ew")
                ent.bind("<FocusOut>",
                         lambda e, ch=i-1: self._ao_voltage_commit(ch))
                ent.bind("<Return>",
                         lambda e, ch=i-1: self._ao_voltage_commit(ch))
                short = chan.split("/")[-1] if "/" in chan else chan
                ttk.Label(ao_frame, text=f"{short}  ({self.selected_device.get()})").grid(
                    row=i, column=2, padx=4, pady=2, sticky="w")
                self.ao_enable_vars.append(en)
                self.ao_voltage_vars.append(val)
            ttk.Button(ao_frame, text="Apply All Analog Outputs",
                       command=self._apply_ao).grid(
                row=len(self.ao_channels) + 1, column=0, columnspan=3, pady=6)
            row += 1
        if self.do_lines:
            do_frame = ttk.LabelFrame(
                parent, text=f"Digital Outputs ({len(self.do_lines)} lines)")
            do_frame.grid(row=row, column=0, sticky="ew", pady=(0, 8))
            ncols = 4
            for idx, line in enumerate(self.do_lines):
                var = tk.BooleanVar(value=False)
                short = line.split("/")[-1] if "/" in line else line
                cb = ttk.Checkbutton(
                    do_frame, text=short, variable=var,
                    command=lambda i=idx: self._do_toggle(i))
                r, c = divmod(idx, ncols)
                cb.grid(row=r, column=c, padx=6, pady=3, sticky="w")
                self.do_vars.append(var)
            ttk.Button(do_frame, text="Apply All Digital Outputs",
                       command=self._apply_do).grid(
                row=(len(self.do_lines) + ncols - 1) // ncols + 1,
                column=0, columnspan=ncols, pady=6)
            row += 1
        pt_frame = ttk.LabelFrame(parent, text="Network Analyzer")
        pt_frame.grid(row=row, column=0, sticky="ew", pady=(0, 8))
        pt_frame.grid_columnconfigure(1, weight=1)
        ttk.Label(pt_frame, text="Pulse width (ms):").grid(
            row=0, column=0, padx=4, pady=2, sticky="w")
        self.pulse_width_var = tk.StringVar(value="1.0")
        self.pulse_entry = ttk.Entry(pt_frame, textvariable=self.pulse_width_var, width=8)
        self.pulse_entry.grid(row=0, column=1, padx=4, pady=2, sticky="w")
        ttk.Button(pt_frame, text="Run Network Analyzer",
                   command=self._test_pin_connections).grid(
            row=1, column=0, columnspan=2, pady=4)
        self.na_and_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(pt_frame, text="Include Analog Output Monitoring "
                   "(tests analog outputs)",
                   variable=self.na_and_var).grid(
            row=2, column=0, columnspan=2, padx=4, pady=2, sticky="w")
        ttk.Label(pt_frame, text="Pulse each DIO line HIGH, read all others as inputs.",
                  font=("TkDefaultFont", 8), foreground="gray").grid(
            row=3, column=0, columnspan=2, padx=4, pady=(4, 0), sticky="w")
        row += 1
        info = ttk.LabelFrame(parent, text="Device Info")
        info.grid(row=row, column=0, sticky="ew")
        caps = self.device_capabilities
        info_text = (
            f"AI channels: {len(self.ai_channels)}\n"
            f"AO channels: {len(self.ao_channels)}\n"
            f"DI lines:    {len(self.di_lines)} (port 0)\n"
            f"DO lines:    {len(self.do_lines)} (ports 1+)\n"
            f"AI range:    {caps.get('ai_ranges', [(AI_MIN, AI_MAX)])[0]}\n"
            f"AO range:    {caps.get('ao_ranges', [(AO_MIN, AO_MAX)])[0]}\n"
            f"\nGraphs auto-resize with the window.\n"
            f"Install: pip install nidaqmx matplotlib numpy\n"
            f"Note: DI (port 0) and DO (ports 1+) use separate physical lines."
        )
        ttk.Label(info, text=info_text, justify="left").grid(
            row=0, column=0, sticky="w", padx=6, pady=6)

    def _build_plots(self, parent):
        self.fig = Figure(figsize=(8, 5), constrained_layout=True)
        self.ax_ai = self.fig.add_subplot(2, 1, 1)
        self.ax_di = self.fig.add_subplot(2, 1, 2, sharex=self.ax_ai)
        colors = plt.cm.tab20.colors
        n_colors = len(colors)
        self.ax_ai.set_title("Analog Inputs (all channels)")
        self.ax_ai.set_ylabel("Voltage (V)")
        ai_min, ai_max = self.device_capabilities.get(
            "ai_ranges", [(AI_MIN, AI_MAX)])[0]
        self.ax_ai.set_ylim(ai_min, ai_max)
        self.ax_ai.grid(True, alpha=0.3)
        self.ai_plot_lines = []
        for i, chan in enumerate(self.ai_channels):
            short = chan.split("/")[-1] if "/" in chan else chan
            line, = self.ax_ai.plot(
                [], [], color=colors[i % n_colors],
                lw=0.8, alpha=0.9, label=short)
            self.ai_plot_lines.append(line)
        if self.ai_plot_lines:
            self.ax_ai.legend(ncol=8, fontsize=6,
                              loc="upper right", framealpha=0.9)
        self.ax_di.set_title("Digital Inputs (all lines)")
        self.ax_di.set_ylabel("Level")
        self.ax_di.set_xlabel("Time (s)")
        self.ax_di.set_ylim(-0.2, 1.2)
        self.ax_di.set_yticks([0, 1])
        self.ax_di.grid(True, alpha=0.3)
        self.di_plot_lines = []
        for i, line in enumerate(self.di_lines):
            short = line.split("/")[-1] if "/" in line else line
            line_obj, = self.ax_di.plot(
                [], [], drawstyle="steps-post",
                color=colors[i % n_colors],
                lw=0.8, alpha=0.9, label=short)
            self.di_plot_lines.append(line_obj)
        if self.di_plot_lines:
            self.ax_di.legend(ncol=8, fontsize=6,
                              loc="upper right", framealpha=0.9)
        self.ax_ai.set_xlim(0, HISTORY_SECONDS)
        self.ax_di.set_xlim(0, HISTORY_SECONDS)
        old = getattr(self, "canvas", None)
        if old is not None:
            old.get_tk_widget().grid_forget()
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.plot_frame)
        self.canvas.draw()
        self.canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")

    def _refresh_devices(self):
        self._log("Refreshing device list", "INFO")
        devs = discover_devices()
        self.available_devices = devs
        self.device_combo["values"] = devs
        if devs and not self.selected_device.get():
            self.selected_device.set(devs[0])
            self._log(f"Auto-selected device: {devs[0]}", "INFO")
        self._on_device_selected()

    def _on_device_selected(self):
        dev = self.selected_device.get().strip()
        self._log(f"Device selected: {dev}", "INFO")
        was_running = self.running
        if was_running:
            self.stop_event.set()
            if self.daq_thread and self.daq_thread.is_alive():
                self.daq_thread.join(timeout=1.0)
            self.running = False
        self.device_capabilities = get_device_capabilities(dev)
        self.ai_channels = list(self.device_capabilities["ai_channels"])
        self.ao_channels = list(self.device_capabilities["ao_channels"])
        dio_all = list(self.device_capabilities.get("di_lines", [])) + \
                  list(self.device_capabilities.get("do_lines", []))
        self.di_lines = []
        self.do_lines = []
        for line in dio_all:
            parts = line.split("/")
            port_num = None
            for p in parts:
                if p.startswith("port"):
                    try:
                        port_num = int(p[4:])
                    except ValueError:
                        pass
                    break
            if port_num == 0:
                self.di_lines.append(line)
            else:
                self.do_lines.append(line)
        # Remove duplicates while preserving order
        self.di_lines = list(dict.fromkeys(self.di_lines))
        self.do_lines = list(dict.fromkeys(self.do_lines))
        self._log(f"Capabilities: AI={len(self.ai_channels)}, AO={len(self.ao_channels)}, DI={len(self.di_lines)}, DO={len(self.do_lines)}", "INFO")
        self.ao_values = [0.0] * len(self.ao_channels)
        self.do_values = [False] * len(self.do_lines)
        self.ao_enable_vars = []
        self.ao_voltage_vars = []
        self.do_vars = []
        self.ai_plot_lines = []
        self.di_plot_lines = []
        self._close_output_tasks()
        self._rebuild_controls()
        self._rebuild_plots()
        if was_running:
            self._start_daq()
        else:
            self._set_status(f"DAQ: ready ({dev})", "gray")
            self.root.after(100, self._start_daq)

    def _rebuild_plots(self):
        self.fig = Figure(figsize=(8, 5), constrained_layout=True)
        self.ax_ai = self.fig.add_subplot(2, 1, 1)
        self.ax_di = self.fig.add_subplot(2, 1, 2, sharex=self.ax_ai)
        colors = plt.cm.tab20.colors
        n_colors = len(colors)
        self.ax_ai.set_title("Analog Inputs (all channels)")
        self.ax_ai.set_ylabel("Voltage (V)")
        ai_min, ai_max = self.device_capabilities.get(
            "ai_ranges", [(AI_MIN, AI_MAX)])[0]
        self.ax_ai.set_ylim(ai_min, ai_max)
        self.ax_ai.grid(True, alpha=0.3)
        self.ai_plot_lines = []
        for i, chan in enumerate(self.ai_channels):
            short = chan.split("/")[-1] if "/" in chan else chan
            line, = self.ax_ai.plot(
                [], [], color=colors[i % n_colors],
                lw=0.8, alpha=0.9, label=short)
            self.ai_plot_lines.append(line)
        if self.ai_plot_lines:
            self.ax_ai.legend(ncol=8, fontsize=6,
                              loc="upper right", framealpha=0.9)
        self.ax_di.set_title("Digital Inputs (all lines)")
        self.ax_di.set_ylabel("Level")
        self.ax_di.set_xlabel("Time (s)")
        self.ax_di.set_ylim(-0.2, 1.2)
        self.ax_di.set_yticks([0, 1])
        self.ax_di.grid(True, alpha=0.3)
        self.di_plot_lines = []
        for i, line in enumerate(self.di_lines):
            short = line.split("/")[-1] if "/" in line else line
            line_obj, = self.ax_di.plot(
                [], [], drawstyle="steps-post",
                color=colors[i % n_colors],
                lw=0.8, alpha=0.9, label=short)
            self.di_plot_lines.append(line_obj)
        if self.di_plot_lines:
            self.ax_di.legend(ncol=8, fontsize=6,
                              loc="upper right", framealpha=0.9)
        self.ax_ai.set_xlim(0, HISTORY_SECONDS)
        self.ax_di.set_xlim(0, HISTORY_SECONDS)
        old = getattr(self, "canvas", None)
        if old is not None:
            old.get_tk_widget().grid_forget()
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.plot_frame)
        self.canvas.draw()
        self.canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")

    def _schedule_plot_update(self):
        self._update_plots()
        self.root.after(UI_UPDATE_PERIOD, self._schedule_plot_update)

    def _request_redraw(self):
        if not self._redraw_pending:
            self._redraw_pending = True
            self.root.after(50, self._do_throttled_redraw)

    def _do_throttled_redraw(self):
        self._redraw_pending = False
        self.canvas.draw_idle()

    def _update_plots(self):
        if not self.ai_channels and not self.di_lines:
            return
        with self.lock:
            ai_snapshot = list(self.ai_buffer)
            di_snapshot = list(self.di_buffer)
        if not ai_snapshot and not di_snapshot:
            return
        if ai_snapshot and self.ai_plot_lines:
            t_ai = np.array([row[0] for row in ai_snapshot])
            v_ai = np.array([row[1] for row in ai_snapshot])
            t_now = t_ai[-1]
            t_start = max(0.0, t_now - HISTORY_SECONDS)
            for i, line in enumerate(self.ai_plot_lines):
                if i < v_ai.shape[1]:
                    line.set_data(t_ai, v_ai[:, i])
            self.ax_ai.set_xlim(t_start, t_now)
        if di_snapshot and self.di_plot_lines:
            t_di = np.array([row[0] for row in di_snapshot])
            v_di = np.array([row[1] for row in di_snapshot], dtype=float)
            t_now = t_di[-1]
            t_start = max(0.0, t_now - HISTORY_SECONDS)
            for i, line in enumerate(self.di_plot_lines):
                if i < v_di.shape[1]:
                    line.set_data(t_di, v_di[:, i])
            self.ax_di.set_xlim(t_start, t_now)
        self.canvas.draw_idle()

    def _start_daq(self):
        if self.running:
            return
        if not _HAS_NIDAQMX:
            self._show_error(
                "Missing dependency",
                "nidaqmx is not installed. Install with:\n"
                "pip install nidaqmx matplotlib numpy")
            return
        if not self.selected_device.get():
            self._show_error("No Device", "Please select an NI DAQ device.")
            return
        self.running = True
        self.stop_event.clear()
        self.t0 = time.perf_counter()
        self.ai_buffer.clear()
        self.di_buffer.clear()
        dev = self.selected_device.get()
        self.daq_thread = threading.Thread(
            target=self._daq_loop, args=(dev,), daemon=True)
        self.daq_thread.start()
        self._set_status("DAQ: running", "green")

    def _daq_loop(self, dev):
        self._log(f"DAQ loop starting on {dev}", "INFO")
        try:
            ai_task = nidaqmx.Task() if self.ai_channels else None
            di_task = nidaqmx.Task() if self.di_lines else None
            if ai_task is not None:
                for chan in self.ai_channels:
                    ai_min, ai_max = self.device_capabilities.get(
                        "ai_ranges", [(AI_MIN, AI_MAX)])[0]
                    ai_task.ai_channels.add_ai_voltage_chan(
                        chan, min_val=ai_min, max_val=ai_max)
            if di_task is not None:
                self._log(f"Adding {len(self.di_lines)} DI channels", "DEBUG")
                for line in self.di_lines:
                    di_task.di_channels.add_di_chan(line)
            self._log("DAQ tasks created, entering read loop", "INFO")
            read_count = 0
            while not self.stop_event.is_set():
                t = time.perf_counter() - self.t0
                ai = None
                di = None
                try:
                    if ai_task is not None:
                        ai = np.atleast_1d(np.array(ai_task.read())).ravel()
                    if di_task is not None:
                        di = np.atleast_1d(np.array(di_task.read())).ravel().astype(bool)
                except Exception:
                    self.stop_event.wait(READ_PERIOD)
                    continue
                ai_ok = (len(self.ai_channels) == 0) or \
                        (ai is not None and ai.size == len(self.ai_channels))
                di_ok = (len(self.di_lines) == 0) or \
                        (di is not None and di.size == len(self.di_lines))
                if ai_ok and di_ok:
                    read_count += 1
                    with self.lock:
                        if ai is not None and len(self.ai_channels) > 0:
                            self.ai_buffer.append((t, ai.copy()))
                        if di is not None and len(self.di_lines) > 0:
                            self.di_buffer.append((t, di.copy()))
                    if read_count % 100 == 0:
                        self._log(f"DAQ read count: {read_count}", "DEBUG")
                self.stop_event.wait(READ_PERIOD)
            if ai_task is not None:
                ai_task.close()
            if di_task is not None:
                di_task.close()
        except DaqError as e:
            self._log(f"DAQ error: {e}", "ERROR")
            self._set_status(f"DAQ error: {e}", "red")
            if not self.cli_mode:
                self.root.after(0, lambda err=e: self._show_error(
                    "NI-DAQmx Error", str(err)))
        except Exception as e:
            self._log(f"DAQ error: {e}", "ERROR")
            self._set_status(f"DAQ error: {e}", "red")
            if not self.cli_mode:
                self.root.after(0, lambda err=e: self._show_error("Error", str(err)))
        finally:
            self.running = False
            self._log("DAQ loop stopped", "INFO")
            self._set_status("DAQ: stopped", "gray")

    def _set_status(self, text, color):
        if self.cli_mode:
            print(f"[STATUS] {text}")
        else:
            self.status_var.set(text)
            self.status_label.configure(foreground=color)

    def _open_output_tasks(self):
        dev = self.selected_device.get().strip()
        if not dev:
            return
        ao_ranges = self.device_capabilities.get(
            "ao_ranges", [(AO_MIN, AO_MAX)])[0]
        ao_min, ao_max = ao_ranges
        if self.ao_task is None and self.ao_channels:
            self._log(f"Opening AO task with {len(self.ao_channels)} channels", "INFO")
            self.ao_task = nidaqmx.Task()
            for chan in self.ao_channels:
                self.ao_task.ao_channels.add_ao_voltage_chan(
                    chan, min_val=ao_min, max_val=ao_max)
            self.ao_task.write([0.0] * len(self.ao_channels))
        if self.do_task is None and self.do_lines:
            self._log(f"Opening DO task with {len(self.do_lines)} lines", "INFO")
            self.do_task = nidaqmx.Task()
            for line in self.do_lines:
                self.do_task.do_channels.add_do_chan(line)
            self.do_task.write([False] * len(self.do_lines))

    def _close_output_tasks(self):
        self._log("Closing output tasks", "INFO")
        for task in (self.ao_task, self.do_task):
            if task is not None:
                try:
                    task.close()
                except Exception:
                    pass
        self.ao_task = None
        self.do_task = None

    def _ao_enable_toggle(self, ch):
        if not _HAS_NIDAQMX or ch >= len(self.ao_channels):
            return
        self._open_output_tasks()
        if self.ao_enable_vars[ch].get():
            try:
                v = float(self.ao_voltage_vars[ch].get())
            except ValueError:
                if self.cli_mode:
                    print("ERROR: Invalid voltage. Enter a numeric voltage.", flush=True)
                else:
                    self._show_error("Invalid voltage", "Enter a numeric voltage.")
                self.ao_enable_vars[ch].set(False)
                return
            ao_min, ao_max = self.device_capabilities.get(
                "ao_ranges", [(AO_MIN, AO_MAX)])[0]
            v = min(max(v, ao_min), ao_max)
            self.ao_voltage_vars[ch].set(f"{v:.3f}")
            self.ao_values[ch] = v
            self._log(f"AO {ch} enabled: {v:.3f} V", "INFO")
        else:
            self.ao_values[ch] = 0.0
            self._log(f"AO {ch} disabled: 0.0 V", "INFO")
        self._write_ao()

    def _ao_voltage_commit(self, ch):
        if not _HAS_NIDAQMX or ch >= len(self.ao_channels):
            return
        try:
            v = float(self.ao_voltage_vars[ch].get())
        except ValueError:
            if self.cli_mode:
                print("ERROR: Invalid voltage. Enter a numeric voltage.", flush=True)
            else:
                self._show_error("Invalid voltage", "Enter a numeric voltage.")
            return
        ao_min, ao_max = self.device_capabilities.get(
            "ao_ranges", [(AO_MIN, AO_MAX)])[0]
        v = min(max(v, ao_min), ao_max)
        self.ao_voltage_vars[ch].set(f"{v:.3f}")
        if self.ao_enable_vars[ch].get():
            self.ao_values[ch] = v
            self._log(f"AO {ch} voltage set: {v:.3f} V", "INFO")
            self._write_ao()

    def _apply_ao(self):
        if not _HAS_NIDAQMX:
            return
        self._open_output_tasks()
        ao_min, ao_max = self.device_capabilities.get(
            "ao_ranges", [(AO_MIN, AO_MAX)])[0]
        for ch in range(len(self.ao_channels)):
            if self.ao_enable_vars[ch].get():
                try:
                    v = float(self.ao_voltage_vars[ch].get())
                except ValueError:
                    continue
                self.ao_values[ch] = min(max(v, ao_min), ao_max)
            else:
                self.ao_values[ch] = 0.0
        self._write_ao()

    def _write_ao(self):
        if self.ao_task is not None:
            self.ao_task.write(self.ao_values)
            for ch, v in enumerate(self.ao_values):
                chan = self.ao_channels[ch].split("/")[-1]
                self._log(f"AO WRITE: {chan} = {v:+.4f} V (enabled={self.ao_enable_vars[ch].get()})", "DEBUG")

    def _do_toggle(self, i):
        if not _HAS_NIDAQMX or i >= len(self.do_lines):
            return
        self._open_output_tasks()
        state = self.do_vars[i].get()
        self.do_values[i] = state
        self._log(f"DO toggle: {self.do_lines[i]} = {'HIGH' if state else 'LOW'}", "INFO")
        self._write_do()

    def _apply_do(self):
        if not _HAS_NIDAQMX:
            return
        self._open_output_tasks()
        for i in range(len(self.do_lines)):
            self.do_values[i] = self.do_vars[i].get()
        self._write_do()

    def _write_do(self):
        if self.do_task is not None:
            self.do_task.write(self.do_values)
            for i, v in enumerate(self.do_values):
                line = self.do_lines[i].split("/")[-1]
                self._log(f"DO WRITE: {line} = {'HIGH' if v else 'LOW'}", "DEBUG")

    def _test_pin_connections(self):
        """Analyze digital I/O pin connections and detect logic networks."""
        if not _HAS_NIDAQMX:
            if self.cli_mode:
                print("ERROR: nidaqmx is not installed")
            else:
                self._show_error("Missing dependency", "nidaqmx is not installed")
            return

        try:
            pulse_ms = float(self.pulse_width_var.get())
            if pulse_ms <= 0:
                raise ValueError
        except (ValueError, AttributeError):
            if self.cli_mode:
                print("ERROR: Invalid pulse width. Using default 1.0ms")
                pulse_ms = 1.0
            else:
                self._show_error("Invalid pulse width",
                                 "Enter a positive numeric pulse width in ms")
                return

        pulse_s = pulse_ms / 1000.0

        dev = self.selected_device.get().strip() if self.selected_device else "Dev1"
        if not dev:
            if self.cli_mode:
                print("ERROR: No device selected")
            else:
                self._show_error("No device", "Select a device first")
            return

        caps = get_device_capabilities(dev)
        dio_all = list(dict.fromkeys(caps.get("di_lines", []) + caps.get("do_lines", [])))

        if len(dio_all) < 2:
            if self.cli_mode:
                print("ERROR: Need at least 2 DIO lines to test")
            else:
                self._show_error("Not enough lines",
                                 "Need at least 2 DIO lines to test")
            return

        if not self.cli_mode:
            result = messagebox.askyesno(
                "Safety Warning - Network Analyzer",
                f"This test will drive digital I/O lines HIGH for {pulse_ms}ms each\n"
                f"while reading all other lines as inputs.\n\n"
                f"Tests:\n"
                f"• {len(dio_all)} single-pin tests\n"
                f"• {len(dio_all) * (len(dio_all) - 1) // 2} pin pairs × 4 combinations each\n"
                f"• Total: ~{len(dio_all) + len(dio_all) * (len(dio_all) - 1) // 2 * 4} write operations\n\n"
                f"SAFETY:\n"
                f"• Ensure no external voltage sources are connected to the pins\n"
                f"• Pulse width is kept short ({pulse_ms}ms) to protect connected chips\n"
                f"• Only one or two lines driven at a time\n\n"
                f"Continue?",
                icon="warning")
            if not result:
                return
        else:
            print(f"Network Analyzer starting on {dev}")
            print(f"Pulse width: {pulse_ms}ms")
            print(f"DIO lines: {len(dio_all)}")
            print()

        self._set_status("Network Analyzer running...", "orange")
        self._log(f"Network Analyzer starting on {dev}", "INFO")
        self._log(f"Pulse width: {pulse_ms}ms", "INFO")
        self._log(f"DIO lines: {len(dio_all)}", "INFO")

        was_running = self.running
        if was_running:
            self.stop_event.set()
            if self.daq_thread and self.daq_thread.is_alive():
                self.daq_thread.join(timeout=2.0)
            self.running = False
            self._log("DAQ acquisition paused for analysis", "INFO")

        self._na_cancel = False
        self._na_start_time = time.perf_counter()
        eta_times = []

        if self.cli_mode:
            self._run_na_analysis(dev, dio_all, pulse_s, pulse_ms, was_running)
        else:
            analysis_thread = threading.Thread(
                target=self._run_na_analysis,
                args=(dev, dio_all, pulse_s, pulse_ms, was_running),
                daemon=True)
            analysis_thread.start()

    def _run_na_analysis(self, dev, dio_all, pulse_s, pulse_ms, was_running):
        """Run the Network Analyzer in a background thread."""
        total_tests = len(dio_all) + len(dio_all) * (len(dio_all) - 1) // 2 * 4
        test_count = 0
        eta_times = []

        # Create progress dialog (GUI mode only)
        progress_win = None
        progress_var = None
        status_label = None
        cancel_btn = None

        if not self.cli_mode:
            progress_win = tk.Toplevel(self.root)
            progress_win.title("Network Analyzer - Progress")
            progress_win.geometry("520x180")
            progress_win.minsize(400, 100)
            ttk.Label(progress_win, text="Network Analyzer Running",
                      font=("TkDefaultFont", 11, "bold")).pack(pady=(10, 5))
            status_label = ttk.Label(progress_win, text="Initializing...",
                                     font=("TkDefaultFont", 9))
            status_label.pack(pady=(0, 5))
            progress_var = tk.DoubleVar(value=0)
            progress_bar = ttk.Progressbar(progress_win, variable=progress_var,
                                           maximum=100, length=450)
            progress_bar.pack(pady=(0, 8), padx=20, fill="x")
            btn_frame = ttk.Frame(progress_win)
            btn_frame.pack(pady=(0, 10))
            cancel_state = [False]

            def do_cancel():
                cancel_state[0] = True
                self._na_cancel = True
                if cancel_btn and cancel_btn.winfo_exists():
                    cancel_btn.configure(text="Cancelling...", state="disabled")
                self._log("User requested cancellation", "WARN")

            cancel_btn = ttk.Button(btn_frame, text="Cancel Analysis",
                                    command=do_cancel)
            cancel_btn.pack(side="left", padx=5)
            ttk.Button(btn_frame, text="Close", command=progress_win.destroy).pack(
                side="right", padx=5)

            progress_win.update_idletasks()
            x = (progress_win.winfo_screenwidth() // 2) - (520 // 2)
            y = (progress_win.winfo_screenheight() // 2) - (180 // 2)
            progress_win.geometry(f"520x180+{x}+{y}")

        def update_progress(percent, status_text):
            if not self.cli_mode and progress_win and progress_win.winfo_exists():
                self.root.after(0, lambda p=percent, s=status_text: _update_gui(p, s))
            elif self.cli_mode:
                print(f"[{percent:3.0f}%] {status_text}", flush=True)

        def _update_gui(percent, status_text):
            try:
                if progress_win and progress_win.winfo_exists():
                    progress_var.set(percent)
                    status_label.configure(text=status_text)
                    progress_win.update_idletasks()
            except tk.TclError:
                pass

        try:
            # Phase 1: Single-pin tests
            affects_single = {}
            test_count = 0

            for i, output_line in enumerate(dio_all):
                if self._na_cancel:
                    self._log("Analysis cancelled by user during Phase 1", "WARN")
                    return

                input_lines = [l for l in dio_all if l != output_line]
                test_start = time.perf_counter()
                test_count += 1
                pct = int(test_count / total_tests * 100)

                in_short = [l.split("/")[-1] if "/" in l else l for l in input_lines[:5]]
                in_more = f" (+{len(input_lines)-5} more)" if len(input_lines) > 5 else ""

                if test_count > 1:
                    avg_time = sum(eta_times) / len(eta_times)
                    remaining = total_tests - test_count
                    eta_seconds = avg_time * remaining
                    eta_str = f" ETA: {self._format_eta(eta_seconds)}"
                else:
                    eta_str = ""
                status_text = f"Outputting on {output_line.split('/')[-1]} and reading DI {', '.join(in_short)}{in_more}{eta_str}"
                update_progress(pct, status_text)

                with nidaqmx.Task() as do_task, nidaqmx.Task() as di_task:
                    do_task.do_channels.add_do_chan(output_line)
                    for line in input_lines:
                        di_task.di_channels.add_di_chan(line)

                    do_task.timeout = 2.0
                    di_task.timeout = 2.0

                    do_task.start()

                    baseline = np.atleast_1d(
                        np.array(di_task.read())).ravel().astype(bool)

                    do_task.write([True])
                    time.sleep(pulse_s)
                    high_read = np.atleast_1d(
                        np.array(di_task.read())).ravel().astype(bool)

                    do_task.write([False])
                    time.sleep(pulse_s)

                affects_single[output_line] = set()
                for j, input_line in enumerate(input_lines):
                    if j < len(high_read) and j < len(baseline):
                        if high_read[j] and not baseline[j]:
                            affects_single[output_line].add(input_line)

                test_time = time.perf_counter() - test_start
                eta_times.append(test_time)

            if self._na_cancel:
                self._log("Analysis cancelled by user during Phase 1", "WARN")
                return

            if self.cli_mode:
                print("Phase 1 (single-pin) complete.")
                for out_line, responders in sorted(affects_single.items()):
                    if responders:
                        short_out = out_line.split("/")[-1] if "/" in out_line else out_line
                        short_resp = [l.split("/")[-1] if "/" in l else l
                                      for l in sorted(responders)]
                        print(f"  {short_out} -> {short_resp}")
                print()

            # Find bidirectionally connected pairs
            connected_pairs = []
            checked = set()
            for pin_a in dio_all:
                for pin_b in dio_all:
                    if pin_a == pin_b:
                        continue
                    pair_key = tuple(sorted([pin_a, pin_b]))
                    if pair_key in checked:
                        continue
                    checked.add(pair_key)

                    b_responds_to_a = pin_b in affects_single.get(pin_a, set())
                    a_responds_to_b = pin_a in affects_single.get(pin_b, set())

                    if b_responds_to_a and a_responds_to_b:
                        connected_pairs.append((pin_a, pin_b))

            # Phase 2: Full truth table on all pin pairs
            GATE_PATTERNS = {
                (0, 0, 0, 0): ("CONST_0", "0"),
                (0, 0, 0, 1): ("AND", "&"),
                (0, 0, 1, 0): ("A_AND_NOT_B", "A & ~B"),
                (0, 0, 1, 1): ("BUFFER_B", "B"),
                (0, 1, 0, 0): ("NOT_A_AND_B", "~A & B"),
                (0, 1, 0, 1): ("BUFFER_A", "A"),
                (0, 1, 1, 0): ("XOR", "^"),
                (0, 1, 1, 1): ("OR", "|"),
                (1, 0, 0, 0): ("NOR", "~(A|B)"),
                (1, 0, 0, 1): ("XNOR", "~(A^B)"),
                (1, 0, 1, 0): ("NOT_B", "~B"),
                (1, 0, 1, 1): ("B_OR_NOT_A", "B | ~A"),
                (1, 1, 0, 0): ("NOT_A", "~A"),
                (1, 1, 0, 1): ("A_OR_NOT_B", "A | ~B"),
                (1, 1, 1, 0): ("NAND", "~(A&B)"),
                (1, 1, 1, 1): ("CONST_1", "1"),
            }

            logic_gates = []
            checked_pairs = set()

            for i, in_a in enumerate(dio_all):
                if self._na_cancel:
                    self._log("Analysis cancelled by user during Phase 2", "WARN")
                    return

                for in_b in dio_all[i + 1:]:
                    if self._na_cancel:
                        self._log("Analysis cancelled by user during Phase 2", "WARN")
                        return

                    pair_key = tuple(sorted([in_a, in_b]))
                    if pair_key in checked_pairs:
                        continue
                    checked_pairs.add(pair_key)

                    test_count += 1
                    pct = int(test_count / total_tests * 100)

                    a_short = in_a.split("/")[-1] if "/" in in_a else in_a
                    b_short = in_b.split("/")[-1] if "/" in in_b else in_b
                    out_short = []
                    for l in dio_all:
                        if l != in_a and l != in_b:
                            out_short.append(l.split("/")[-1] if "/" in l else l)
                        if len(out_short) >= 5:
                            break
                    out_more = f" (+{len(dio_all)-2-5} more)" if len(dio_all) > 7 else ""
                    status_text = f"Outputting on DO {a_short}+{b_short} and reading DI {', '.join(out_short)}{out_more}{eta_str}"
                    update_progress(pct, status_text)

                    test_start = time.perf_counter()

                    output_lines = [l for l in dio_all if l != in_a and l != in_b]

                    with nidaqmx.Task() as do_task_2, nidaqmx.Task() as di_task_2:
                        do_task_2.do_channels.add_do_chan(in_a)
                        do_task_2.do_channels.add_do_chan(in_b)
                        for line in output_lines:
                            di_task_2.di_channels.add_di_chan(line)

                        do_task_2.timeout = 2.0
                        di_task_2.timeout = 2.0

                        do_task_2.start()

                        combos = [(False, False), (False, True),
                                  (True, False), (True, True)]
                        results = {l: [False, False, False, False]
                                   for l in output_lines}

                        for combo_idx, (a_val, b_val) in enumerate(combos):
                            if self._na_cancel:
                                return
                            do_task_2.write([a_val, b_val])
                            time.sleep(pulse_s)
                            read_vals = np.atleast_1d(
                                np.array(di_task_2.read())).ravel().astype(bool)
                            do_task_2.write([False, False])
                            time.sleep(pulse_s * 0.5)

                            for j, out_line in enumerate(output_lines):
                                if j < len(read_vals):
                                    results[out_line][combo_idx] = bool(read_vals[j])

                    for out_line, truth_list in results.items():
                        truth = tuple(int(v) for v in truth_list)
                        gate_name, gate_symbol = GATE_PATTERNS.get(
                            truth, (f"CUSTOM{truth}", "?"))

                        if truth == (0, 0, 0, 0):
                            continue
                        if truth == (1, 1, 1, 1):
                            continue

                        logic_gates.append({
                            "input_a": in_a,
                            "input_b": in_b,
                            "output": out_line,
                            "truth": truth,
                            "gate_name": gate_name,
                            "gate_symbol": gate_symbol,
                        })

                    test_time = time.perf_counter() - test_start
                    eta_times.append(test_time)

                if self._na_cancel:
                    self._log("Analysis cancelled by user after Phase 2", "WARN")
                    return

                if self.cli_mode:
                    print("Phase 2 (logic gate detection) complete.")
                    print(f"Found {len(logic_gates)} logic gate(s)")
                    for gate in logic_gates:
                        a = gate["input_a"].split("/")[-1] if "/" in gate["input_a"] else gate["input_a"]
                        b = gate["input_b"].split("/")[-1] if "/" in gate["input_b"] else gate["input_b"]
                        c = gate["output"].split("/")[-1] if "/" in gate["output"] else gate["output"]
                        t = gate["truth"]
                        print(f"  {a} {gate['gate_symbol']} {b} -> {c} [{gate['gate_name']}] "
                              f"truth={t}")
                    print()

                # Phase 3: Combinational network detection
                combinational_networks = []
                gate_outputs = {g["output"] for g in logic_gates}

                for gate_out in gate_outputs:
                    for other_gate in logic_gates:
                        if other_gate["output"] == gate_out:
                            continue
                        if gate_out in (other_gate["input_a"], other_gate["input_b"]):
                            combinational_networks.append({
                                "upstream_gate": gate_out,
                                "downstream_gate": other_gate["output"],
                                "upstream_name": next(
                                    g["gate_name"] for g in logic_gates
                                    if g["output"] == gate_out),
                                "downstream_name": other_gate["gate_name"],
                            })

                if self.cli_mode:
                    if combinational_networks:
                        print("Combinational networks (gate chains):")
                        for net in combinational_networks:
                            print(f"  {net['upstream_name']} ({net['upstream_gate']}) "
                                  f"-> {net['downstream_name']} ({net['downstream_gate']})")
                    print()

                self.na_results = {
                    "device": dev,
                    "pulse_ms": pulse_ms,
                    "pairs": connected_pairs,
                    "gates": logic_gates,
                    "networks": combinational_networks,
                    "dio_all": dio_all,
                }

                if not self.cli_mode:
                    self.root.after(0, lambda: self._finalize_na_gui(
                        progress_win, dev, pulse_ms))
                else:
                    self._print_cli_na_results()
                    self._save_cli_na_csv()
                    self._set_status("DAQ: running", "green")

        except Exception as e:
            self._log(f"Analyzer error: {e}", "ERROR")
            if self.cli_mode:
                print(f"ERROR: {e}")
                import traceback
                traceback.print_exc()
            else:
                self.root.after(0, lambda: self._show_error("Analyzer Error", str(e)))
                self.root.after(0, lambda: self._set_status("DAQ: error", "red"))
        finally:
            if not self.cli_mode:
                self.root.after(0, lambda: progress_win.destroy() if progress_win and progress_win.winfo_exists() else None)
            if was_running:
                self.root.after(100, self._start_daq)
                self._log("DAQ acquisition resumed", "INFO")

    def _finalize_na_gui(self, progress_win, dev, pulse_ms):
        try:
            if progress_win and progress_win.winfo_exists():
                progress_win.destroy()
        except tk.TclError:
            pass

        self._open_na_results_window()
        self._set_status("DAQ: running", "green")

    def _print_cli_na_results(self):
        r = self.na_results
        print("=" * 60)
        print("NETWORK ANALYZER RESULTS")
        print("=" * 60)
        print(f"Device:      {r['device']}")
        print(f"Pulse width: {r['pulse_ms']} ms")
        print(f"Direct bridges: {len(r['pairs'])}")
        print(f"Logic gates:    {len(r.get('gates', []))}")
        print(f"Networks:       {len(r.get('networks', []))}")
        print()

        if r["pairs"]:
            print("--- Direct Wire Bridges ---")
            for pin_a, pin_b in r["pairs"]:
                a = pin_a.split("/")[-1] if "/" in pin_a else pin_a
                b = pin_b.split("/")[-1] if "/" in pin_b else pin_b
                print(f"  {a} | {b}")
                print(f"    True    |   True")
                print(f"    True    |   True")
            print()
        else:
            print("--- Direct Wire Bridges: None ---")
            print()

        gates = r.get("gates", [])
        if gates:
            print("--- Logic Gates Detected ---")
            for gate in gates:
                a = gate["input_a"].split("/")[-1] if "/" in gate["input_a"] else gate["input_a"]
                b = gate["input_b"].split("/")[-1] if "/" in gate["input_b"] else gate["input_b"]
                c = gate["output"].split("/")[-1] if "/" in gate["output"] else gate["output"]
                gate_name = gate["gate_name"]
                truth = gate["truth"]
                print(f"  {a} {gate['gate_symbol']} {b} -> {c}  [{gate_name}]")
                print(f"    A   B   |   Out")
                print(f"    {truth[0]}  {truth[1]}   |   {truth[0]}")
                print(f"    {truth[2]}  {truth[3]}   |   {truth[1]}")
                print(f"    {truth[0]}  {truth[1]}   |   {truth[2]}")
                print(f"    {truth[2]}  {truth[3]}   |   {truth[3]}")
                print()
        else:
            print("--- Logic Gates: None ---")
            print()

        networks = r.get("networks", [])
        if networks:
            print("--- Combinational Networks (Gate Chains) ---")
            for net in networks:
                print(f"  {net['upstream_name']} ({net['upstream_gate']}) "
                      f"-> {net['downstream_name']} ({net['downstream_gate']})")
            print()
        else:
            print("--- Combinational Networks: None ---")
            print()

        if not r["pairs"] and not gates and not networks:
            print("No connections found.")
        print("=" * 60)

    def _save_cli_na_csv(self):
        import csv
        from datetime import datetime

        if self._na_csv_saved:
            return
        self._na_csv_saved = True

        r = self.na_results
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"na_results_{r['device']}_{timestamp}.csv"

        try:
            with open(filename, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["Device", r["device"]])
                writer.writerow(["Pulse width (ms)", r["pulse_ms"]])
                writer.writerow([])

                if r["pairs"]:
                    writer.writerow(["Type", "Pin A", "Pin B", "State A", "State B"])
                    for pin_a, pin_b in r["pairs"]:
                        short_a = pin_a.split("/")[-1] if "/" in pin_a else pin_a
                        short_b = pin_b.split("/")[-1] if "/" in pin_b else pin_b
                        writer.writerow(["Direct", short_a, short_b, "True", "True"])
                        writer.writerow(["Direct", short_a, short_b, "True", "True"])
                    writer.writerow([])

                gates = r.get("gates", [])
                if gates:
                    writer.writerow(["Type", "Input A", "Input B", "Output",
                                     "Gate", "Symbol", "00", "01", "10", "11"])
                    for gate in gates:
                        a_short = gate["input_a"].split("/")[-1] if "/" in gate["input_a"] else gate["input_a"]
                        b_short = gate["input_b"].split("/")[-1] if "/" in gate["input_b"] else gate["input_b"]
                        c_short = gate["output"].split("/")[-1] if "/" in gate["output"] else gate["output"]
                        gate_name = gate["gate_name"]
                        gate_symbol = gate["gate_symbol"]
                        truth = gate["truth"]
                        writer.writerow(["Logic", a_short, b_short, c_short,
                                         gate_name, gate_symbol,
                                         truth[0], truth[1], truth[2], truth[3]])

                networks = r.get("networks", [])
                if networks:
                    writer.writerow([])
                    writer.writerow(["Type", "Upstream Gate", "Upstream Name",
                                     "Downstream Gate", "Downstream Name"])
                    for net in networks:
                        writer.writerow(["Network",
                                         net["upstream_gate"],
                                         net["upstream_name"],
                                         net["downstream_gate"],
                                         net["downstream_name"]])

                    if not r["pairs"] and not gates and not networks:
                        writer.writerow(["Result", "No connections found"])

            print(f"\nResults saved to: {filename}")
        except Exception as e:
            print(f"ERROR saving CSV: {e}")

    def _open_na_results_window(self):
        r = self.na_results

        win = tk.Toplevel(self.root)
        win.title("Network Analyzer Results")
        win.geometry("1000x700")
        win.minsize(600, 400)

        info_frame = ttk.Frame(win)
        info_frame.pack(fill="x", padx=10, pady=5)

        ttk.Label(info_frame, text=f"Device: {r['device']}",
                  font=("TkDefaultFont", 11, "bold")).pack(anchor="w")
        ttk.Label(info_frame, text=f"Pulse width: {r['pulse_ms']} ms").pack(anchor="w")
        ttk.Label(info_frame,
                  text=f"Direct bridges: {len(r['pairs'])}  |  "
                       f"Logic gates: {len(r.get('gates', []))}  |  "
                       f"Combinational networks: {len(r.get('networks', []))}").pack(
            anchor="w")

        text_frame = ttk.Frame(win)
        text_frame.pack(fill="both", expand=True, padx=10, pady=10)

        text_widget = tk.Text(text_frame, wrap="none", font=("Consolas", 10))
        text_widget.pack(side="left", fill="both", expand=True)

        v_scroll = ttk.Scrollbar(text_frame, orient="vertical",
                                 command=text_widget.yview)
        v_scroll.pack(side="right", fill="y")
        h_scroll = ttk.Scrollbar(win, orient="horizontal",
                                 command=text_widget.xview)
        h_scroll.pack(side="bottom", fill="x")
        text_widget.configure(yscrollcommand=v_scroll.set,
                              xscrollcommand=h_scroll.set)

        lines = []
        lines.append("=== Network Analyzer Results ===")
        lines.append(f"Device: {r['device']}")
        lines.append(f"Pulse width: {r['pulse_ms']} ms")
        lines.append("")

        if r["pairs"]:
            lines.append("--- Direct Wire Bridges ---")
            lines.append("")
            for pin_a, pin_b in r["pairs"]:
                short_a = pin_a.split("/")[-1] if "/" in pin_a else pin_a
                short_b = pin_b.split("/")[-1] if "/" in pin_b else pin_b
                lines.append(f"{short_a} | {short_b}")
                lines.append("  True    |   True")
                lines.append("  True    |   True")
                lines.append("")
        else:
            lines.append("--- Direct Wire Bridges: None ---")
            lines.append("")

        gates = r.get("gates", [])
        if gates:
            lines.append("--- Logic Gates Detected ---")
            lines.append("")
            for gate in gates:
                a_short = gate["input_a"].split("/")[-1] if "/" in gate["input_a"] else gate["input_a"]
                b_short = gate["input_b"].split("/")[-1] if "/" in gate["input_b"] else gate["input_b"]
                c_short = gate["output"].split("/")[-1] if "/" in gate["output"] else gate["output"]
                gate_name = gate["gate_name"]
                truth = gate["truth"]
                lines.append(f"{a_short} {gate['gate_symbol']} {b_short} -> {c_short}  [{gate_name}]")
                lines.append("  A   B   |   Out")
                lines.append(f"  {truth[0]}  {truth[1]}   |   {truth[0]}")
                lines.append(f"  {truth[2]}  {truth[3]}   |   {truth[1]}")
                lines.append(f"  {truth[0]}  {truth[1]}   |   {truth[2]}")
                lines.append(f"  {truth[2]}  {truth[3]}   |   {truth[3]}")
                lines.append("")
        else:
            lines.append("--- Logic Gates: None ---")
            lines.append("")

        networks = r.get("networks", [])
        if networks:
            lines.append("--- Combinational Networks (Gate Chains) ---")
            lines.append("")
            for net in networks:
                lines.append(f"{net['upstream_name']} ({net['upstream_gate']}) "
                             f"-> feeds into -> {net['downstream_name']} "
                             f"({net['downstream_gate']})")
                lines.append("")
        else:
            lines.append("--- Combinational Networks: None ---")
            lines.append("")

        if not r["pairs"] and not gates and not networks:
            lines.append("No connections found.")
            lines.append("")
            lines.append(
                "(No pins were found where driving one HIGH caused the "
                "other to read HIGH.)")

        text_widget.insert("1.0", "\n".join(lines))
        text_widget.configure(state="disabled")

        btn_frame = ttk.Frame(win)
        btn_frame.pack(fill="x", padx=10, pady=10)

        def export_csv():
            import csv
            from tkinter import filedialog

            filepath = filedialog.asksaveasfilename(
                parent=win,
                defaultextension=".csv",
                filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
                title="Save Network Analyzer Results",
            )
            if not filepath:
                return

            try:
                with open(filepath, "w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow(["Device", r["device"]])
                    writer.writerow(["Pulse width (ms)", r["pulse_ms"]])
                    writer.writerow([])

                    if r["pairs"]:
                        writer.writerow(["Type", "Pin A", "Pin B", "State A", "State B"])
                        for pin_a, pin_b in r["pairs"]:
                            short_a = pin_a.split("/")[-1] if "/" in pin_a else pin_a
                            short_b = pin_b.split("/")[-1] if "/" in pin_b else pin_b
                            writer.writerow(["Direct", short_a, short_b, "True", "True"])
                            writer.writerow(["Direct", short_a, short_b, "True", "True"])
                        writer.writerow([])

                    gates = r.get("gates", [])
                    if gates:
                        writer.writerow(["Type", "Input A", "Input B", "Output",
                                         "Gate", "Symbol", "00", "01", "10", "11"])
                        for gate in gates:
                            a_short = gate["input_a"].split("/")[-1] if "/" in gate["input_a"] else gate["input_a"]
                            b_short = gate["input_b"].split("/")[-1] if "/" in gate["input_b"] else gate["input_b"]
                            c_short = gate["output"].split("/")[-1] if "/" in gate["output"] else gate["output"]
                            gate_name = gate["gate_name"]
                            gate_symbol = gate["gate_symbol"]
                            truth = gate["truth"]
                            writer.writerow(["Logic", a_short, b_short, c_short,
                                             gate_name, gate_symbol,
                                             truth[0], truth[1], truth[2], truth[3]])

                    networks = r.get("networks", [])
                    if networks:
                        writer.writerow([])
                        writer.writerow(["Type", "Upstream Gate", "Upstream Name",
                                         "Downstream Gate", "Downstream Name"])
                        for net in networks:
                            writer.writerow(["Network",
                                             net["upstream_gate"],
                                             net["upstream_name"],
                                             net["downstream_gate"],
                                             net["downstream_name"]])

                    if not r["pairs"] and not gates and not networks:
                        writer.writerow(["Result", "No connections found"])

                messagebox.showinfo("Export Complete",
                                    f"Results saved to:\n{filepath}",
                                    parent=win)
            except Exception as e:
                print(f"[ERROR] Export Error: {e}", flush=True)
                self._show_error("Export Error", str(e))

        ttk.Button(btn_frame, text="Export to CSV", command=export_csv).pack(
            side="left", padx=5)
        ttk.Button(btn_frame, text="Close", command=win.destroy).pack(
            side="right", padx=5)

    # ------------------------------------------------------------------ #
    # Shutdown
    # ------------------------------------------------------------------ #
    def _on_close(self):
        self.stop_event.set()
        self._close_output_tasks()
        if self.daq_thread and self.daq_thread.is_alive():
            self.daq_thread.join(timeout=1.0)
        self.root.destroy()


def run_cli(args, app):
    """Command-line interface mode for testing and automation."""
    import nidaqmx
    from nidaqmx.errors import DaqError

    dev = args.device if args.device else None

    # Auto-detect if no device specified
    if not dev:
        devices = discover_devices()
        if not devices:
            print("ERROR: No NI DAQ devices found.")
            return 1
        dev = devices[0]
        print(f"Auto-detected device: {dev}")

    # Query capabilities
    caps = get_device_capabilities(dev)
    ai_chans = caps["ai_channels"]
    ao_chans = caps["ao_channels"]
    dio_lines = list(dict.fromkeys(caps.get("di_lines", []) + caps.get("do_lines", [])))
    di_lines = [l for l in dio_lines if "/port0/" in l]
    do_lines = [l for l in dio_lines if "/port0/" not in l]

    print(f"Device: {dev}")
    print(f"  AI channels: {len(ai_chans)}")
    print(f"  AO channels: {len(ao_chans)}")
    print(f"  DI lines (port 0): {len(di_lines)}")
    print(f"  DO lines (ports 1+): {len(do_lines)}")
    print()

    # --- List devices ---
    if args.list_devices:
        print("Connected NI DAQ devices:")
        for d in discover_devices():
            print(f"  {d}")
        return 0

    # --- Read all analog inputs ---
    if args.read_ai:
        try:
            with nidaqmx.Task() as task:
                for chan in ai_chans:
                    ai_min, ai_max = caps["ai_ranges"][0]
                    task.ai_channels.add_ai_voltage_chan(chan, min_val=ai_min, max_val=ai_max)
                data = task.read()
            data = np.atleast_1d(np.array(data)).ravel()
            print(f"Analog Inputs ({len(data)} channels):")
            for i, v in enumerate(data):
                name = ai_chans[i].split("/")[-1] if i < len(ai_chans) else f"ch{i}"
                print(f"  {name}: {v:+.4f} V")
        except DaqError as e:
            print(f"DAQ Error reading AI: {e}")
            return 1
        return 0

    # --- Read all digital inputs ---
    if args.read_di:
        if not di_lines:
            print("No digital input lines found on this device.")
            return 0
        try:
            with nidaqmx.Task() as task:
                for line in di_lines:
                    task.di_channels.add_di_chan(line)
                data = task.read()
            data = np.atleast_1d(np.array(data)).ravel().astype(bool)
            print(f"Digital Inputs ({len(data)} lines):")
            high = [di_lines[i].split("/")[-1] for i, v in enumerate(data) if v]
            if high:
                print(f"  HIGH lines: {high}")
            else:
                print("  All lines LOW")
            for i, v in enumerate(data):
                name = di_lines[i].split("/")[-1]
                print(f"  {name}: {'HIGH' if v else 'LOW'}")
        except DaqError as e:
            print(f"DAQ Error reading DI: {e}")
            return 1
        return 0

    # --- Write analog output ---
    if args.write_ao:
        if not ao_chans:
            print("No analog output channels found on this device.")
            return 1
        try:
            chan_name, voltage_str = args.write_ao
            voltage = float(voltage_str)
        except (ValueError, TypeError):
            print("ERROR: --write-ao requires <channel> <voltage>")
            print("  Example: --write-ao ao0 5.0")
            return 1

        matched = None
        matches = [c for c in ao_chans if c == chan_name or c.split("/")[-1] == chan_name]
        if len(matches) == 1:
            matched = matches[0]
        elif len(matches) > 1:
            print(f"ERROR: '{chan_name}' is ambiguous. Matches: {matches}")
            print(f"  Use full path like: {matches[0]}")
            return 1
        if not matched:
            print(f"ERROR: Channel '{chan_name}' not found. Available: {[c.split('/')[-1] for c in ao_chans]}")
            return 1

        try:
            with nidaqmx.Task() as task:
                ao_min, ao_max = caps["ao_ranges"][0]
                for chan in ao_chans:
                    task.ao_channels.add_ao_voltage_chan(chan, min_val=ao_min, max_val=ao_max)
                values = [0.0] * len(ao_chans)
                idx = ao_chans.index(matched)
                values[idx] = min(max(voltage, ao_min), ao_max)
                task.write(values)
            print(f"Wrote {values[idx]:+.4f} V to {matched.split('/')[-1]}")
        except DaqError as e:
            print(f"DAQ Error writing AO: {e}")
            return 1
        return 0

    # --- Write digital output ---
    if args.write_do:
        if not do_lines:
            print("No digital output lines found on this device.")
            return 1
        try:
            line_name, state_str = args.write_do
        except (ValueError, TypeError):
            print("ERROR: --write-do requires <line> <state>")
            print("  Example: --write-do port1/line0 HIGH")
            return 1

        state = state_str.upper() in ("1", "TRUE", "HIGH", "ON", "YES")

        matched = None
        matches = [l for l in do_lines if l == line_name or l.split("/")[-1] == line_name]
        if len(matches) == 1:
            matched = matches[0]
        elif len(matches) > 1:
            print(f"ERROR: '{line_name}' is ambiguous. Matches: {matches}")
            print(f"  Use full path like: {matches[0]}")
            return 1
        if not matched:
            print(f"ERROR: Line '{line_name}' not found. Available: {[l.split('/')[-1] for l in do_lines]}")
            return 1

        try:
            with nidaqmx.Task() as task:
                for line in do_lines:
                    task.do_channels.add_do_chan(line)
                values = [False] * len(do_lines)
                idx = do_lines.index(matched)
                values[idx] = state
                task.write(values)
            print(f"Set {matched.split('/')[-1]} to {'HIGH' if state else 'LOW'}")
        except DaqError as e:
            print(f"DAQ Error writing DO: {e}")
            return 1
        return 0

    # --- Continuous monitoring ---
    if args.monitor:
        if not ai_chans and not di_lines:
            print("No input channels found on this device.")
            return 1
        interval = args.interval if args.interval else 0.5
        print(f"Monitoring {dev} every {interval}s (Ctrl+C to stop)...")
        print()

        try:
            with nidaqmx.Task() as ai_task, nidaqmx.Task() as di_task:
                ai_min, ai_max = caps["ai_ranges"][0]
                for chan in ai_chans:
                    task.ai_channels.add_ai_voltage_chan(chan, min_val=ai_min, max_val=ai_max)
                for line in di_lines:
                    task.di_channels.add_di_chan(line)

                count = 0
                while True:
                    count += 1
                    ts = time.strftime("%H:%M:%S")
                    ai_data = np.atleast_1d(np.array(ai_task.read())).ravel() if ai_chans else []
                    di_data = np.atleast_1d(np.array(di_task.read())).ravel().astype(bool) if di_lines else []

                    print(f"[{ts}] Sample #{count}", flush=True)
                    for i, v in enumerate(ai_data):
                        name = ai_chans[i].split("/")[-1] if i < len(ai_chans) else f"ch{i}"
                        print(f"  {name}: {v:+.4f} V", flush=True)
                    high = [di_lines[i].split("/")[-1] for i, v in enumerate(di_data) if v] if di_lines else []
                    if high:
                        print(f"  DI HIGH: {high}", flush=True)
                    print(flush=True)
                    time.sleep(interval)
        except KeyboardInterrupt:
            print("\nMonitoring stopped.")
            return 0
        except DaqError as e:
            print(f"DAQ Error: {e}")
            return 1
        return 0

    # --- Network Analyzer ---
    if args.analyze:
        app.pulse_width_var = type('SV', (), {'get': lambda self: str(args.pulse_width)})()
        app.selected_device = type('SV', (), {'get': lambda self: dev})()
        app._test_pin_connections()
        return 0

    # No action specified -- show help
    print("No action specified. Use --help for available commands.")
    return 1


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="NI DAQ Monitor & Output Controller -- GUI or CLI mode"
    )
    parser.add_argument(
        "--cli", action="store_true",
        help="Run in command-line mode instead of GUI"
    )
    parser.add_argument(
        "--device", type=str, default=None,
        help="NI DAQ device name (e.g. Dev1). Auto-detected if omitted."
    )
    parser.add_argument(
        "--list-devices", action="store_true",
        help="List all connected NI DAQ devices"
    )
    parser.add_argument(
        "--read-ai", action="store_true",
        help="Read all analog input channels"
    )
    parser.add_argument(
        "--read-di", action="store_true",
        help="Read all digital input lines"
    )
    parser.add_argument(
        "--write-ao", nargs=2, metavar=("CHANNEL", "VOLTAGE"),
        help="Write voltage to an analog output channel (e.g. ao0 5.0)"
    )
    parser.add_argument(
        "--write-do", nargs=2, metavar=("LINE", "STATE"),
        help="Set a digital output line (e.g. port1/line0 HIGH)"
    )
    parser.add_argument(
        "--monitor", action="store_true",
        help="Continuously monitor inputs (Ctrl+C to stop)"
    )
    parser.add_argument(
        "--interval", type=float, default=0.5,
        help="Monitoring interval in seconds (default: 0.5)"
    )
    parser.add_argument(
        "--analyze", action="store_true",
        help="Run Network Analyzer (pin connection & logic gate detection)"
    )
    parser.add_argument(
        "--pulse-width", type=float, default=1.0,
        help="Pulse width in ms for Network Analyzer (default: 1.0)"
    )

    args = parser.parse_args()

    if args.cli or args.list_devices or args.read_ai or args.read_di or \
       args.write_ao or args.write_do or args.monitor or args.analyze:
        app = USB6363App(root=None, cli_mode=True)
        return run_cli(args, app)

    root = tk.Tk()
    app = USB6363App(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())