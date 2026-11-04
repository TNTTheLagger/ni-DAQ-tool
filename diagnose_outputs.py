"""
Standalone diagnostic script to verify NI USB-6363 output hardware.

This directly writes to AO 0 and a digital output line, then reads back
AO 0 via AI 0 (requires jumper: AO 0 -> AI 0).

USAGE
-----
1. Connect your multimeter or oscilloscope to measure outputs.
2. For analog loopback verification: jumper AO 0 to AI 0.
3. Run: .\venv\Scripts\activate && python diagnose_outputs.py
4. Follow the prompts.

Hardware expected
-----------------
- AO 0  -> measure vs AI GND (should show the written voltage)
- AI 0  -> should read back AO 0 voltage if jumpered
- PFI 0 (Dev1/port1/line0) -> measure vs DGND (should be 3.3V/0V)
"""

import sys
import time
import nidaqmx
from nidaqmx.errors import DaqError


def test_analog_output():
    """Write known voltages to AO 0 and read back via AI 0 if available."""
    print("\n=== Analog Output Test (AO 0) ===")
    try:
        with nidaqmx.Task() as ao_task, nidaqmx.Task() as ai_task:
            ao_task.ao_channels.add_ao_voltage_chan("Dev1/ao0", min_val=-10, max_val=10)
            ai_task.ai_channels.add_ai_voltage_chan("Dev1/ai0", min_val=-10, max_val=10)

            test_voltages = [0.0, 2.5, 5.0, -2.5, 0.0]
            for v in test_voltages:
                ao_task.write(v)
                time.sleep(0.3)
                read_back = ai_task.read()
                print(f"  Wrote AO 0: {v:+.3f} V  |  Read AI 0: {read_back:+.4f} V  |  Match: {abs(read_back - v) < 0.1}")
        print("  AO test: COMPLETE (no DaqError)")
        return True
    except DaqError as e:
        print(f"  AO test: FAILED - {e}")
        return False
    except Exception as e:
        print(f"  AO test: FAILED - {type(e).__name__}: {e}")
        return False


def test_digital_output():
    """Toggle digital output PFI 0 (Dev1/port1/line0) HIGH/LOW."""
    print("\n=== Digital Output Test (PFI 0 / Dev1/port1/line0) ===")
    print("  Measure with multimeter: PFI 0 vs DGND")
    print("  Should toggle between ~3.3V and 0V")
    try:
        with nidaqmx.Task() as do_task:
            do_task.do_channels.add_do_chan("Dev1/port1/line0")
            for i in range(5):
                state = i % 2 == 0
                do_task.write(state)
                print(f"  Wrote PFI 0: {'HIGH' if state else 'LOW'}")
                time.sleep(0.5)
            do_task.write(False)
        print("  DO test: COMPLETE (no DaqError)")
        return True
    except DaqError as e:
        print(f"  DO test: FAILED - {e}")
        return False
    except Exception as e:
        print(f"  DO test: FAILED - {type(e).__name__}: {e}")
        return False


def main():
    print("=" * 60)
    print("NI USB-6363 Output Diagnostic")
    print("=" * 60)

    # Verify device exists
    try:
        system = nidaqmx.system.System.local()
        devices = system.devices
        dev_names = [d.name for d in devices]
        print(f"Devices found: {dev_names}")
        if "Dev1" not in dev_names:
            print("ERROR: Dev1 not found. Update device name in script.")
            return 1
    except Exception as e:
        print(f"ERROR: Cannot communicate with NI-DAQmx: {e}")
        return 1

    ao_ok = test_analog_output()
    do_ok = test_digital_output()

    print("\n" + "=" * 60)
    print("DIAGNOSTIC SUMMARY")
    print("=" * 60)
    print(f"  Analog Output (AO 0): {'PASS' if ao_ok else 'FAIL'}")
    print(f"  Digital Output (PFI 0): {'PASS' if do_ok else 'FAIL'}")
    print()
    if not ao_ok or not do_ok:
        print("TROUBLESHOOTING:")
        print("  1. Open NI-MAX and verify Dev1 is detected and not reserved.")
        print("  2. In NI-MAX, try test panels to write to AO 0 and PFI 0 directly.")
        print("  3. Verify wiring: measure between output pin and appropriate GND.")
        print("  4. For AO: measure AO 0 vs AI GND.")
        print("  5. For DO: measure PFI 0 vs DGND.")
        print("  6. Check that no other application is reserving the device.")
        return 1
    else:
        print("All output tests passed. If you still see no hardware change,")
        print("check your physical wiring and measurement points.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
