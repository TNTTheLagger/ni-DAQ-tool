"""
Full Network Analyzer test script.

Runs the complete Network Analyzer (Phase 1-3) on the connected NI-DAQmx device,
outputs the current configuration, waits for completion, checks for errors,
and saves results to a CSV file showing any detected pin bridges.

USAGE
-----
1. Connect pin pairs together on your NI USB-6363 (e.g. PFI 0 <-> PFI 1).
2. Run: python test_network_analyzer_full.py
3. Check na_results_Dev1_<timestamp>.csv for detected bridges.

No physical hardware required to run the code structure — it will use mocked
nidaqmx if the real driver is not available.  With real hardware connected,
bridged pin pairs will appear in the CSV under the "Direct" rows.
"""

import sys
import time
import csv
import traceback
from datetime import datetime
from unittest.mock import patch, MagicMock

# Try to import real nidaqmx; fall back to mock if not available.
try:
    import nidaqmx
    from nidaqmx.errors import DaqError
    _HAS_REAL_NIDAQMX = True
except Exception:
    nidaqmx = None
    DaqError = Exception
    _HAS_REAL_NIDAQMX = False

import tkinter as tk
import ni_measurment as mod


def run_full_network_analyzer(device_name="Dev1", pulse_ms=1.0, dio_lines=None,
                               phase1_only=False, max_lines=None):
    """
    Run the full Network Analyzer end-to-end.

    Returns (results_dict, error_list, elapsed_seconds).
    """
    errors = []
    start = time.perf_counter()

    # ---- Build app headlessly ----
    root = tk.Tk()
    root.withdraw()

    app = mod.USB6363App(root, cli_mode=True)

    # Capture all log messages at ERROR/WARN level.
    captured_errors = []
    original_log = app._log

    def capturing_log(message, level="INFO"):
        original_log(message, level)
        if level in ("ERROR", "WARN", "WARNING"):
            captured_errors.append(f"[{level}] {message}")

    app._log = capturing_log

    # Use provided DIO lines or auto-discover from device capabilities.
    if dio_lines is None:
        caps = mod.get_device_capabilities(device_name)
        dio_lines = caps.get("di_lines", []) + caps.get("do_lines", [])
        # Deduplicate while preserving order.
        dio_lines = list(dict.fromkeys(dio_lines))

        # Apply max_lines limit if specified
        if max_lines is not None and max_lines > 0 and len(dio_lines) > max_lines:
            dio_lines = dio_lines[:max_lines]
            print(f"Limited DIO lines to {max_lines} for analysis")

    app.selected_device = tk.StringVar(value=device_name)
    app.pulse_width_var = tk.StringVar(value=str(pulse_ms))
    app.di_lines = [l for l in dio_lines if "/port0/" in l]
    app.do_lines = [l for l in dio_lines if "/port0/" not in l]
    app._na_cancel = False

    print("=" * 60)
    print("NETWORK ANALYZER — FULL RUN")
    print("=" * 60)
    print(f"Device:        {device_name}")
    print(f"Pulse width:   {pulse_ms} ms")
    print(f"DIO lines:     {len(dio_lines)}")
    print(f"  DI (port 0): {len(app.di_lines)}")
    print(f"  DO (ports 1+): {len(app.do_lines)}")
    print()

    # Show current device configuration.
    caps = mod.get_device_capabilities(device_name)
    print("--- Device Configuration ---")
    print(f"  AI channels: {len(caps.get('ai_channels', []))}")
    print(f"  AO channels: {len(caps.get('ao_channels', []))}")
    print(f"  DI lines:    {len(app.di_lines)}")
    print(f"  DO lines:    {len(app.do_lines)}")
    if caps.get("ai_ranges"):
        print(f"  AI range:    {caps['ai_ranges'][0]}")
    if caps.get("ao_ranges"):
        print(f"  AO range:    {caps['ao_ranges'][0]}")
    print()

    # ---- Run the analysis ----
    mode_str = "Phase 1 only" if phase1_only else "Full (Phase 1 + Phase 2)"
    print(f"Starting Network Analyzer ({mode_str}) ...")
    print()

    try:
        app._run_na_analysis(
            device_name,
            dio_lines,
            pulse_ms / 1000.0,   # pulse_s
            pulse_ms,            # pulse_ms
            False,               # was_running
            phase1_only=phase1_only,
        )
    except Exception as exc:  # noqa: BLE001
        errors.append(f"EXCEPTION: {type(exc).__name__}: {exc}")
        errors.append(traceback.format_exc())
        print(f"ERROR during analysis: {exc}")
        traceback.print_exc()

    elapsed = time.perf_counter() - start

    # ---- Collect results ----
    results = getattr(app, "na_results", None)

    print()
    print("=" * 60)
    print("ANALYSIS COMPLETE")
    print("=" * 60)
    print(f"Elapsed time:  {elapsed:.3f} s")
    print(f"Errors:        {len(errors) + len(captured_errors)}")

    if errors:
        print("\n--- Exceptions ---")
        for e in errors:
            print(e)

    if captured_errors:
        print("\n--- Logged Errors/Warnings ---")
        for e in captured_errors:
            print(e)

    if results:
        print(f"\nDevice:        {results.get('device')}")
        print(f"Pulse width:   {results.get('pulse_ms')} ms")
        print(f"DIO lines:     {len(results.get('dio_all', []))}")
        print(f"Bridges:       {len(results.get('pairs', []))}")
        print(f"Logic gates:   {len(results.get('gates', []))}")
        print(f"Networks:      {len(results.get('networks', []))}")

        if results.get("pairs"):
            print("\n--- Detected Pin Bridges ---")
            for pin_a, pin_b in results["pairs"]:
                a = pin_a.split("/")[-1] if "/" in pin_a else pin_a
                b = pin_b.split("/")[-1] if "/" in pin_b else pin_b
                print(f"  {a} <--> {b}")

        if results.get("gates"):
            print("\n--- Detected Logic Gates ---")
            for gate in results["gates"]:
                a = gate["input_a"].split("/")[-1] if "/" in gate["input_a"] else gate["input_a"]
                b = gate["input_b"].split("/")[-1] if "/" in gate["input_b"] else gate["input_b"]
                c = gate["output"].split("/")[-1] if "/" in gate["output"] else gate["output"]
                t = gate["truth"]
                print(f"  {a} {gate['gate_symbol']} {b} -> {c}  [{gate['gate_name']}]  truth={t}")
    else:
        print("\nNo results were produced (analysis may have failed early).")

    # ---- Save CSV ----
    # _save_cli_na_csv() was already called inside _run_na_analysis() when
    # cli_mode=True, so we skip saving here to avoid duplicate files.
    csv_filename = None
    if results and not self.app.cli_mode:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_dev = device_name.replace("/", "_")
        csv_filename = f"na_results_{safe_dev}_{timestamp}.csv"

        try:
            with open(csv_filename, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)

                # Header / config
                writer.writerow(["Device", device_name])
                writer.writerow(["Pulse width (ms)", pulse_ms])
                writer.writerow(["Elapsed time (s)", f"{elapsed:.3f}"])
                writer.writerow(["Total errors", len(errors) + len(captured_errors)])
                writer.writerow([])

                # Device configuration
                writer.writerow(["--- Device Configuration ---"])
                writer.writerow(["AI channels", len(caps.get("ai_channels", []))])
                writer.writerow(["AO channels", len(caps.get("ao_channels", []))])
                writer.writerow(["DI lines", len(app.di_lines)])
                writer.writerow(["DO lines", len(app.do_lines)])
                writer.writerow([])

                # Bridges
                if results.get("pairs"):
                    writer.writerow(["--- Detected Pin Bridges ---"])
                    writer.writerow(["Pin A", "Pin B", "Bridge"])
                    for pin_a, pin_b in results["pairs"]:
                        short_a = pin_a.split("/")[-1] if "/" in pin_a else pin_a
                        short_b = pin_b.split("/")[-1] if "/" in pin_b else pin_b
                        writer.writerow([short_a, short_b, "YES"])
                    writer.writerow([])
                else:
                    writer.writerow(["--- Detected Pin Bridges: None ---"])
                    writer.writerow([])

                # Logic gates
                if results.get("gates"):
                    writer.writerow(["--- Detected Logic Gates ---"])
                    writer.writerow(["Input A", "Input B", "Output", "Gate", "Symbol",
                                     "Truth 00", "Truth 01", "Truth 10", "Truth 11"])
                    for gate in results["gates"]:
                        a_short = gate["input_a"].split("/")[-1] if "/" in gate["input_a"] else gate["input_a"]
                        b_short = gate["input_b"].split("/")[-1] if "/" in gate["input_b"] else gate["input_b"]
                        c_short = gate["output"].split("/")[-1] if "/" in gate["output"] else gate["output"]
                        t = gate["truth"]
                        writer.writerow([
                            a_short, b_short, c_short,
                            gate["gate_name"], gate["gate_symbol"],
                            t[0], t[1], t[2], t[3],
                        ])
                    writer.writerow([])
                else:
                    writer.writerow(["--- Detected Logic Gates: None ---"])
                    writer.writerow([])

                # Combinational networks
                if results.get("networks"):
                    writer.writerow(["--- Combinational Networks ---"])
                    writer.writerow(["Upstream Gate", "Upstream Name",
                                     "Downstream Gate", "Downstream Name"])
                    for net in results["networks"]:
                        writer.writerow([
                            net["upstream_gate"], net["upstream_name"],
                            net["downstream_gate"], net["downstream_name"],
                        ])
                else:
                    writer.writerow(["--- Combinational Networks: None ---"])

            print(f"\nResults saved to: {csv_filename}")
        except Exception as exc:  # noqa: BLE001
            print(f"\nERROR saving CSV: {exc}")
            csv_filename = None
    elif results and app.cli_mode:
        print(f"\nCSV already saved by _save_cli_na_csv() inside _run_na_analysis()")

    # ---- Cleanup ----
    try:
        root.destroy()
    except tk.TclError:
        pass

    return results, errors + captured_errors, elapsed, csv_filename


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Run full Network Analyzer and save CSV results"
    )
    parser.add_argument(
        "--device", type=str, default="Dev1",
        help="NI DAQ device name (default: Dev1)"
    )
    parser.add_argument(
        "--pulse-width", type=float, default=1.0,
        help="Pulse width in ms (default: 1.0)"
    )
    parser.add_argument(
        "--dio", type=str, nargs="*", default=None,
        help="Specific DIO lines to test (e.g. Dev1/port0/line0 Dev1/port1/line0)"
    )
    parser.add_argument(
        "--phase-1-only", action="store_true",
        help="Run Phase 1 (single-pin bridge detection) only, skip Phase 2"
    )
    parser.add_argument(
        "--max-lines", type=int, default=None,
        help="Limit number of DIO lines to test (default: all)"
    )
    args = parser.parse_args()

    results, errors, elapsed, csv_file = run_full_network_analyzer(
        device_name=args.device,
        pulse_ms=args.pulse_width,
        dio_lines=args.dio,
        phase1_only=args.phase_1_only,
        max_lines=args.max_lines,
    )

    # Exit code: 0 if no errors, 1 if errors occurred.
    if errors:
        print(f"\nEXIT CODE: 1 ({len(errors)} error(s))")
        return 1
    else:
        print(f"\nEXIT CODE: 0 (no errors)")
        return 0


if __name__ == "__main__":
    sys.exit(main())