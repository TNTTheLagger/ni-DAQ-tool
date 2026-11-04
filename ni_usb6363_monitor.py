"""
Compatibility shim: ni_usb6363_monitor -> ni_measurment

This module re-exports everything from ni_measurment.py so that existing
test files (test_ni_usb6363_monitor.py, test_hardware_library.py,
test_hardware_verify.py, fix_file.py) that import `ni_usb6363_monitor`
continue to work without modification.

Channels are discovered dynamically from the connected NI-DAQmx hardware
rather than hardcoded, so the following constants are provided as empty
lists with the expected names for backwards compatibility.
"""

from ni_measurment import *  # noqa: F401,F403
from ni_measurment import (  # noqa: F401
    USB6363App,
    discover_devices,
    get_device_capabilities,
    run_cli,
    main,
    AI_MIN, AI_MAX, AO_MIN, AO_MAX,
    HISTORY_SECONDS, READ_PERIOD, UI_UPDATE_PERIOD,
    DEFAULT_DEVICE,
    _HAS_NIDAQMX,
)

# Backwards-compatible constants expected by older test files.
# These are empty because channel names are discovered dynamically
# from the connected NI-DAQmx device at runtime.
AI_CHANNEL_NAMES = []   # populated at runtime from device.ai_physical_chans
AO_CHANNEL_NAMES = []   # populated at runtime from device.ao_physical_chans
DI_LINE_NAMES = []      # populated at runtime from device.di_lines (port 0)
DO_LINE_NAMES = []      # populated at runtime from device.do_lines (ports 1+)

__all__ = [
    "USB6363App",
    "discover_devices",
    "get_device_capabilities",
    "run_cli",
    "main",
    "AI_MIN", "AI_MAX", "AO_MIN", "AO_MAX",
    "HISTORY_SECONDS", "READ_PERIOD", "UI_UPDATE_PERIOD",
    "DEFAULT_DEVICE",
    "_HAS_NIDAQMX",
    "AI_CHANNEL_NAMES",
    "AO_CHANNEL_NAMES",
    "DI_LINE_NAMES",
    "DO_LINE_NAMES",
]