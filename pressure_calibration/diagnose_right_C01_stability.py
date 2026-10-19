#!/usr/bin/env python3
"""FeetFit RIGHT C01: distinguish steady-load drift from weight-placement variation.

Uses the installed calibration script's production ADC read path (860 SPS,
3 discards, 5-point median if configured); does not alter calibration profiles.
Stop feetfit-api.service before running.
"""

import csv
import os
import statistics
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["FSR_MEDIAN_WINDOW"] = "5"
os.environ["FSR_CALIBRATION_MODE"] = "legacy"

from pressure_calibration.calibrate_24_sensors import p, read_one  # noqa: E402

TRIALS = 3
READINGS_PER_STAGE = 5
FOOT = "right"
CHANNEL = 1


def measure_stage(trial, weight_kg, label, rows):
    values = []
    print(f"\n[{trial}/{TRIALS}] {label} -- reading {READINGS_PER_STAGE} times WITHOUT moving weight", flush=True)
    for n in range(1, READINGS_PER_STAGE + 1):
        value = float(read_one(FOOT, CHANNEL))
        values.append(value)
        rows.append({
            "placement": trial,
            "weight_kg": weight_kg,
            "reading": n,
            "adc": round(value, 2),
        })
        print(f"  sample {n}: {value:.1f} ADC", flush=True)

    med = statistics.median(values)
    variation = max(values) - min(values)
    spread = 100 * variation / max(1, abs(med))
    print(f"  median={med:.1f}, min={min(values):.1f}, max={max(values):.1f}, within-placement range={spread:.1f}%", flush=True)
    return med, spread


def main():
    print("=" * 68)
    print("RIGHT C01 / 860 SPS / 5-POINT MEDIAN / REPEATABILITY DIAGNOSTIC")
    print("=" * 68)
    print(f"Physical RIGHT -> GPIO{p.EN_RIGHT}, ADS A{p.ADS1115_RIGHT_CHANNEL}")
    print(f"Data rate: {p.ADS1115_DATA_RATE} SPS; median window: {p.MEDIAN_WINDOW}")
    print("WARNING: feetfit-api.service must be STOPPED before this experiment.")
    print("This test does NOT modify .env or the production calibration profile.")
    print("Use a 1kg weight, then add another 1kg on top WITHOUT moving the bottom weight.")
    rows = []
    placement_values = {0: [], 1: [], 2: []}
    try:
        with p.pressure_lock:
            for trial in range(1, TRIALS + 1):
                input(f"\nTrial {trial}: EMPTY both footbeds, then press ENTER: ")
                baseline, _ = measure_stage(trial, 0, "NO LOAD", rows)
                placement_values[0].append(baseline)

                input("Place 1kg on PHYSICAL RIGHT C01, release your hand, press ENTER: ")
                one_kg, _ = measure_stage(trial, 1, "1 KG - DO NOT TOUCH", rows)
                placement_values[1].append(one_kg)

                input("Add second 1kg ON TOP, do not shift bottom weight, press ENTER: ")
                two_kg, _ = measure_stage(trial, 2, "2 KG - DO NOT TOUCH", rows)
                placement_values[2].append(two_kg)

                input("Remove BOTH weights completely, then press ENTER to continue: ")
    finally:
        p.disable_muxes()

    output = ROOT / "pressure_calibration" / "sensor_correction_data" / (
        "stability_right_C01_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".csv"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["placement", "weight_kg", "reading", "adc"])
        writer.writeheader()
        writer.writerows(rows)

    print("\n" + "=" * 68)
    print("BETWEEN-PLACEMENT MEDIANS")
    for weight in (0, 1, 2):
        values = placement_values[weight]
        print(f"{weight}kg: " + ", ".join(f"{v:.1f}" for v in values))
    print("CSV SAVED:", output)
    print("Interpretation: stable readings within each placement but large variation")
    print("between placements suggests load-transfer/placement effects.")
    print("Variation within a fixed placement suggests drift or sensor/electrical instability.")


if __name__ == "__main__":
    main()
