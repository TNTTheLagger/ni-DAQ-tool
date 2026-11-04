"""
Library-level hardware test for ni_usb6363_monitor.py

Loads ni_usb6363_monitor as a library and directly calls its internal
functions to verify:

  * DAQ initialization & background read loop
  * Reading ALL 32 analog inputs (AI 0..31)
  * Reading ALL 32 digital inputs (Port 0 lines 0..31)
  * Writing ALL 4 analog outputs (AO 0..3) via enable checkboxes
  * Writing ALL 16 digital outputs (PFI 0..15) via checkboxes

Run with the USB-6363 connected:
    .\venv\Scripts\activate
    python test_hardware_library.py
"""

import sys
import time
import tkinter as tk

# Import the application module as a library
import ni_usb6363_monitor as mod


def main():
    # ---- Build app without showing the window ----
    root = tk.Tk()
    root.withdraw()  # headless - no window appears

    app = mod.USB6363App(root)

    results = {
        "daq_init": False,
        "ai_read": False,
        "di_read": False,
        "ao_write": False,
        "do_write": False,
    }

    try:
        # 1) Initialize DAQ (starts background acquisition thread)
        print("Initializing DAQ on", app.device.get(), "...")
        app._start_daq()
        results["daq_init"] = True  # thread started without exception

        # Wait for the background loop to fill the buffers
        timeout = 10.0
        t_start = time.time()
        while time.time() - t_start < timeout:
            with app.lock:
                if len(app.ai_buffer) > 0 and len(app.di_buffer) > 0:
                    break
            time.sleep(0.1)

        # 2) Read ALL analog inputs
        with app.lock:
            ai_snapshot = list(app.ai_buffer)
            di_snapshot = list(app.di_buffer)

        if ai_snapshot:
            t_ai, v_ai = ai_snapshot[-1]
            print(f"\nAnalog Inputs (latest sample @ {t_ai:.3f}s):")
            for i in range(len(mod.AI_CHANNEL_NAMES)):
                print(f"  AI {i:2d}: {v_ai[i]:+7.4f} V")
            results["ai_read"] = True
        else:
            print("ERROR: No analog input data received.")

        # 3) Read ALL digital inputs
        if di_snapshot:
            t_di, v_di = di_snapshot[-1]
            print(f"\nDigital Inputs (latest sample @ {t_di:.3f}s):")
            high_lines = [i for i, v in enumerate(v_di) if v]
            if high_lines:
                print("  HIGH lines:", high_lines)
            else:
                print("  All lines LOW")
            for i in range(len(mod.DI_LINE_NAMES)):
                mark = "HIGH" if v_di[i] else "low "
                print(f"  P0.{i:2d}: {mark}")
            results["di_read"] = True
        else:
            print("ERROR: No digital input data received.")

        # 4) Write ALL analog outputs (enable each, set voltage)
        print("\nWriting Analog Outputs ...")
        voltages = [1.0, -2.5, 5.0, -7.5]
        for ch in range(len(mod.AO_CHANNEL_NAMES)):
            app.ao_enable_vars[ch].set(True)
            app.ao_voltage_vars[ch].set(f"{voltages[ch]:.3f}")
            app._ao_enable_toggle(ch)
            time.sleep(0.05)

        # Verify AO task has the values written
        if app.ao_task is not None:
            # Read back what the task is configured to output
            print("  AO values queued:", [f"{v:+.3f}V" for v in app.ao_values])
            results["ao_write"] = True
        else:
            print("ERROR: AO task was not created.")

        time.sleep(0.3)

        # 5) Write ALL digital outputs (toggle each high)
        print("\nWriting Digital Outputs ...")
        for i in range(len(mod.DO_LINE_NAMES)):
            app.do_vars[i].set(True)
            app._do_toggle(i)
            time.sleep(0.03)

        if app.do_task is not None:
            print("  DO values queued:", app.do_values)
            results["do_write"] = True
        else:
            print("ERROR: DO task was not created.")

        time.sleep(0.3)

        # 6) Disable all analog outputs (set to 0 V)
        print("\nDisabling all analog outputs ...")
        for ch in range(len(mod.AO_CHANNEL_NAMES)):
            app.ao_enable_vars[ch].set(False)
            app._ao_enable_toggle(ch)
        time.sleep(0.2)

        # 7) Disable all digital outputs
        print("Disabling all digital outputs ...")
        for i in range(len(mod.DO_LINE_NAMES)):
            app.do_vars[i].set(False)
            app._do_toggle(i)
        time.sleep(0.2)

    except Exception as e:
        print("\nEXCEPTION during hardware test:", type(e).__name__, e)
        import traceback
        traceback.print_exc()

    finally:
        # Clean shutdown
        print("\nShutting down DAQ ...")
        app._on_close()
        try:
            root.destroy()
        except tk.TclError:
            pass

    # ---- Summary ----
    print("\n" + "=" * 50)
    print("HARDWARE TEST SUMMARY")
    print("=" * 50)
    all_pass = True
    for name, ok in results.items():
        status = "PASS" if ok else "FAIL"
        if not ok:
            all_pass = False
        print(f"  {name:12s}: {status}")
    print("=" * 50)
    print("OVERALL:", "ALL TESTS PASSED" if all_pass else "SOME TESTS FAILED")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
