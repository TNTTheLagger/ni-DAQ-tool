"""
Dynamic hardware verification test for ni_usb6363_monitor.py

Auto-detects connected NI DAQ devices, queries their capabilities, and
tests read/write on whatever I/O is available — no hardcoded channel counts.

Run with NI hardware connected:
    .\venv\Scripts\activate
    python test_hardware_verify.py
"""

import sys
import time
import tkinter as tk

import ni_usb6363_monitor as mod


def main():
    root = tk.Tk()
    root.withdraw()  # headless

    # ---- Step 1: Discover devices dynamically ----
    print("=" * 60)
    print("STEP 1: Auto-detect NI DAQ devices")
    print("=" * 60)
    devices = mod.discover_devices()
    if not devices:
        print("ERROR: No NI DAQ devices found.")
        print("       Make sure nidaqmx is installed and hardware is connected.")
        root.destroy()
        return 1

    print(f"Found {len(devices)} device(s): {devices}")
    dev_name = devices[0]  # test the first device
    print(f"Testing device: {dev_name}")

    # ---- Step 2: Query capabilities dynamically ----
    print("\n" + "=" * 60)
    print("STEP 2: Query device capabilities")
    print("=" * 60)
    caps = mod.get_device_capabilities(dev_name)
    print(f"  AI channels ({len(caps['ai_channels'])}): {caps['ai_channels'][:5]}{'...' if len(caps['ai_channels']) > 5 else ''}")
    print(f"  AO channels ({len(caps['ao_channels'])}): {caps['ao_channels']}")
    dio = caps['dio_lines']
    # Split by port for display
    di_count = sum(1 for l in dio if '/port0/' in l)
    do_count = len(dio) - di_count
    print(f"  DIO lines   ({len(dio)}): {dio[:5]}{'...' if len(dio) > 5 else ''}")
    print(f"    -> DI (port 0): {di_count}, DO (ports 1+): {do_count}")
    print(f"  AI ranges: {caps['ai_ranges']}")
    print(f"  AO ranges: {caps['ao_ranges']}")

    results = {
        "device_comms": len(devices) > 0,
        "ai_read": False,
        "di_read": False,
        "ao_write": False,
        "do_write": False,
    }

    app = mod.NADAQApp(root)
    app.selected_device.set(dev_name)
    app._on_device_selected()

    try:
        # ---- Step 3: Start acquisition ----
        print("\n" + "=" * 60)
        print("STEP 3: Start analog & digital input acquisition")
        print("=" * 60)
        app._start_daq()
        time.sleep(1.0)  # let buffers fill

        with app.lock:
            ai_snapshot = list(app.ai_buffer)
            di_snapshot = list(app.di_buffer)

        if ai_snapshot and app.ai_channels:
            _, v_ai = ai_snapshot[-1]
            print(f"Read {len(v_ai)} analog inputs from {len(app.ai_channels)} channels.")
            # Print first 4 and last 4
            for i in list(range(min(4, len(v_ai)))) + list(range(max(0, len(v_ai)-4), len(v_ai))):
                print(f"  {app.ai_channels[i]}: {v_ai[i]:+.4f} V")
            results["ai_read"] = True
        else:
            print("WARNING: No analog input data (device may have no AI channels).")

        if di_snapshot and app.di_lines:
            _, v_di = di_snapshot[-1]
            high = [app.di_lines[i] for i, v in enumerate(v_di) if v]
            print(f"Read {len(v_di)} digital inputs from {len(app.di_lines)} lines.")
            print(f"  HIGH lines: {high if high else 'none (all LOW)'}")
            results["di_read"] = True
        else:
            print("WARNING: No digital input data (device may have no DI lines).")

        # ---- Step 4: Write analog outputs ----
        if app.ao_channels:
            print("\n" + "=" * 60)
            print("STEP 4: Write analog outputs")
            print("=" * 60)
            ao_min, ao_max = caps["ao_ranges"][0]
            # Use a safe mid-range voltage for testing
            test_v = (ao_min + ao_max) / 4  # quarter of range
            for ch in range(len(app.ao_channels)):
                app.ao_enable_vars[ch].set(True)
                app.ao_voltage_vars[ch].set(f"{test_v:.3f}")
                app._ao_enable_toggle(ch)
                time.sleep(0.05)

            if app.ao_task is not None:
                print(f"Wrote {test_v:+.3f} V to all {len(app.ao_channels)} AO channels.")
                for ch, chan in enumerate(app.ao_channels):
                    print(f"  {chan}: {test_v:+.3f} V (enabled)")
                results["ao_write"] = True
            else:
                print("ERROR: AO task not created.")
            time.sleep(0.3)

            # Disable AO
            for ch in range(len(app.ao_channels)):
                app.ao_enable_vars[ch].set(False)
                app._ao_enable_toggle(ch)
        else:
            print("\n" + "=" * 60)
            print("STEP 4: Write analog outputs — SKIPPED (no AO channels)")
            print("=" * 60)
            results["ao_write"] = True  # nothing to test, consider pass

        # ---- Step 5: Write digital outputs ----
        if app.do_lines:
            print("\n" + "=" * 60)
            print("STEP 5: Write digital outputs")
            print("=" * 60)
            for i in range(len(app.do_lines)):
                app.do_vars[i].set(True)
                app._do_toggle(i)
                time.sleep(0.03)

            if app.do_task is not None:
                high_count = sum(app.do_values)
                print(f"Drove {high_count}/{len(app.do_lines)} DO lines HIGH.")
                for i, line in enumerate(app.do_lines):
                    print(f"  {line}: {'HIGH' if app.do_values[i] else 'LOW'}")
                results["do_write"] = True
            else:
                print("ERROR: DO task not created.")
            time.sleep(0.3)

            # Disable DO
            for i in range(len(app.do_lines)):
                app.do_vars[i].set(False)
                app._do_toggle(i)
        else:
            print("\n" + "=" * 60)
            print("STEP 5: Write digital outputs — SKIPPED (no DO lines)")
            print("=" * 60)
            results["do_write"] = True

    except Exception as e:
        print("\nEXCEPTION:", type(e).__name__, e)
        import traceback
        traceback.print_exc()

    finally:
        print("\nShutting down DAQ ...")
        app._on_close()
        try:
            root.destroy()
        except tk.TclError:
            pass

    # ---- Summary ----
    print("\n" + "=" * 60)
    print("HARDWARE VERIFICATION SUMMARY")
    print("=" * 60)
    all_pass = True
    for name, ok in results.items():
        status = "PASS" if ok else "FAIL"
        if not ok:
            all_pass = False
        print(f"  {name:14s}: {status}")
    print("=" * 60)
    print(f"Device tested: {dev_name}")
    print(f"AI ch: {len(caps['ai_channels'])}, AO ch: {len(caps['ao_channels'])}")
    di_count = sum(1 for l in caps['dio_lines'] if '/port0/' in l)
    do_count = len(caps['dio_lines']) - di_count
    print(f"DI lines: {di_count}, DO lines: {do_count}")
    print("OVERALL:", "ALL TESTS PASSED" if all_pass else "SOME TESTS FAILED")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
