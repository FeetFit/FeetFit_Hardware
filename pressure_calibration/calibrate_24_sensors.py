#!/usr/bin/env python3
"""Manual 0/1/2 kg calibration for the real FeetFit pressure scan path.

Run only while feetfit-api.service is stopped. Physical placement is repeated
independently for each trial; the script records that variability, rather than
pretending repeated ADC reads at one placement are independent calibrations.
"""

import argparse
import csv
import json
import os
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

# Calibration must use raw measurements, never a prior calibration profile.
os.environ["FSR_CALIBRATION_MODE"] = "legacy"

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hardware import pressure as p  # noqa: E402
from hardware.sensor_calibration import hardware_signature  # noqa: E402
from pressure_calibration.calibration_quality import review_sensor  # noqa: E402


def read_one(foot, channel, samples=3):
    if channel not in p.CHANNELS:
        raise ValueError("Unconfigured MUX channel")
    pin = p.EN_LEFT if foot == "left" else p.EN_RIGHT
    adc = p.left_adc if foot == "left" else p.right_adc
    readings = []
    try:
        for _ in range(samples):
            p.disable_muxes()
            p.select_channel(channel)
            p.GPIO.output(pin, p.MUX_ENABLE_LEVEL)
            if p.MUX_SETTLE_TIME:
                time.sleep(p.MUX_SETTLE_TIME)
            readings.append(p.read_adc(adc))
    finally:
        p.disable_muxes()
    return statistics.median(readings)


def get_baseline(scans):
    left = []
    right = []
    print(f"Reading 24-channel baseline ({scans} full scans)...")
    for n in range(scans):
        l, r = p.read_both_feet()
        left.append(l)
        right.append(r)
        print(f"  baseline scan {n+1}/{scans}", flush=True)
    return {
        foot: [
            round(statistics.median(row[i] for row in data), 2)
            for i in range(p.CHANNEL_COUNT)
        ]
        for foot, data in (("left", left), ("right", right))
    }


def check_mapping(baseline):
    print("\nPhysical wiring verification (not assumed from source comments)")
    print("  Place 1kg on PHYSICAL LEFT C01; keep right foot empty.")
    input("  Press ENTER after placing the weight: ")
    time.sleep(2)
    l, r = p.read_both_feet()
    p.disable_muxes()
    i = 1 - p.FIRST_CHANNEL
    if not (0 <= i < p.CHANNEL_COUNT):
        raise ValueError("C01 does not exist in configured channels")
    dl = l[i] - baseline["left"][i]
    dr = r[i] - baseline["right"][i]
    print(f"  software LEFT C01 delta : {dl:.1f} ADC")
    print(f"  software RIGHT C01 delta: {dr:.1f} ADC")
    input("  Remove the weight, then press ENTER: ")
    if not (dl > dr and dl > max(100, p.FSR_NOISE_FLOOR)):
        raise RuntimeError(
            "Physical LEFT C01 did not respond primarily as software LEFT C01. "
            "Review .env wiring, then repeat. Calibration file NOT saved."
        )
    print("  Mapping check passed for LEFT C01.")
    return {"physical_left_c01_delta": {"software_left": dl, "software_right": dr}}


def parse_channels(spec):
    if spec.lower() == "all":
        return list(p.CHANNELS)
    chosen = []
    for token in spec.split(","):
        token = token.strip()
        if "-" in token:
            a, b = map(int, token.split("-", 1))
            chosen.extend(range(a, b + 1))
        else:
            chosen.append(int(token))
    chosen = sorted(set(chosen))
    if not chosen or any(c not in p.CHANNELS for c in chosen):
        raise ValueError(f"Channels must be from {p.CHANNELS}")
    return chosen


def make_plot(result, output):
    # This chart is evidence of repeat placement variability, not fabricated ideal response.
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib unavailable; JSON and CSV are still saved")
        return
    for foot in ("left", "right"):
        rows = [r for r in result["trials"] if r["foot"] == foot]
        if not rows:
            continue
        fig, ax = plt.subplots(figsize=(9, 9))
        channels = sorted(set(r["channel"] for r in rows))
        for channel in channels:
            medians = []
            lower = []
            upper = []
            for weight in (1, 2):
                values = [r["adc"] for r in rows
                          if r["channel"] == channel and r["weight_kg"] == weight]
                med = statistics.median(values)
                medians.append(med)
                lower.append(med-min(values))
                upper.append(max(values)-med)
            b = result["feet"][foot]["baseline"][channel-p.FIRST_CHANNEL]
            ax.plot([0, 1, 2], [b]+medians, marker="o", label=f"C{channel:02d}")
            ax.errorbar([1, 2], medians, yerr=[lower, upper], fmt="none", alpha=.55, capsize=2)
        ax.set_title(f"{foot.upper()} - 0/1/2 kg FSR calibration", fontsize=17)
        ax.set_xlabel("Placed mass (kg)", fontsize=14)
        ax.set_ylabel("ADC response (arbitrary units)", fontsize=14)
        ax.set_xticks([0, 1, 2])
        ax.grid(alpha=.25)
        ax.legend(fontsize=9, ncol=3)
        fig.tight_layout()
        fig.savefig(output/f"{foot}_calibration_repeatability.png", dpi=250)
        plt.close(fig)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--foot", choices=("left", "right", "both"), default="both")
    parser.add_argument("--channels", default="all", help="all, 1, or 0-11")
    parser.add_argument("--repeats", type=int, default=3,
                        help="Independent placements per weight, >= 3")
    parser.add_argument("--tolerance", type=float, default=.25,
                        help="Original full-range tolerance, default 0.25")
    parser.add_argument("--median-band", type=float, default=.20,
                        help="Candidate band +/-fraction of baseline-corrected median (default .20)")
    parser.add_argument("--min-inlier-fraction", type=float, default=.90,
                        help="Fraction within median band for candidate (default .90)")
    parser.add_argument("--candidate-min-repeats", type=int, default=10,
                        help="Minimum independent placements to identify candidate (default 10)")
    parser.add_argument("--baseline-scans", type=int, default=5)
    parser.add_argument("--baseline-only", action="store_true")
    parser.add_argument("--skip-mapping-check", action="store_true")
    args = parser.parse_args()
    if (args.repeats < 3 or args.baseline_scans < 3 or not (0 < args.tolerance < 1)
        or not (0 < args.median_band < 1)
        or not (0 < args.min_inlier_fraction <= 1)
        or args.candidate_min_repeats < 3):
        parser.error("Invalid repeats/baseline/tolerance/robust review settings")
    channels = parse_channels(args.channels)
    feet_to_test = ["left", "right"] if args.foot == "both" else [args.foot]

    signature = hardware_signature(
        left_en=p.EN_LEFT, right_en=p.EN_RIGHT,
        left_ads=p.ADS1115_LEFT_CHANNEL, right_ads=p.ADS1115_RIGHT_CHANNEL,
        gain=p.ADS1115_GAIN, data_rate=p.ADS1115_DATA_RATE,
        first_channel=p.FIRST_CHANNEL, last_channel=p.LAST_CHANNEL,
        channel_count=p.CHANNEL_COUNT,
        median_window=p.MEDIAN_WINDOW, valid_reads=p.VALID_READS,
        mux_select_pins=p.SELECT_PINS,
        active_low=p.FSR_MUX_ENABLE_ACTIVE_LOW,
        fixed_resistor_ohms=p.FSR_FIXED_RESISTOR_OHMS,
    )
    print("\nFEETFIT FSR CALIBRATION — ACTUAL PRODUCTION SCAN SETTINGS")
    print(json.dumps(signature, indent=2))
    print("\nWARNING: Stop feetfit-api.service first. Keep the device empty for baseline.")
    print("All trials use real weight placement; DO NOT press with your hand.")
    print("Full sensitivity mode is blocked until all 24 sensors are validated.")
    input("\nEmpty BOTH footbeds and press ENTER: ")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output = ROOT/"pressure_calibration"/"sensor_correction_data"/stamp
    output.mkdir(parents=True, exist_ok=True)
    partial_csv = output/"placement_trials.partial.csv"
    trials = []
    mapping = {}
    try:
        with p.pressure_lock:
            baseline = get_baseline(args.baseline_scans)
            print("\nBASELINE LEFT :", baseline["left"])
            print("BASELINE RIGHT:", baseline["right"])
            if not args.baseline_only and not args.skip_mapping_check:
                mapping = check_mapping(baseline)

            for foot in feet_to_test if not args.baseline_only else []:
                for channel in channels:
                    for repeat in range(1, args.repeats + 1):
                        for weight in (1, 2):
                            print(f"\n[{foot.upper()} C{channel:02d}] "
                                  f"placement {repeat}/{args.repeats} | {weight} kg")
                            print("Place mass on the SAME sensor center as best you can.")
                            print("1->2kg: if possible, keep bottom 1kg weight stationary.")
                            input("Press ENTER only after weight is positioned: ")
                            time.sleep(2.0)
                            value = read_one(foot, channel)
                            trials.append({"foot": foot, "channel": channel,
                                           "placement": repeat, "weight_kg": weight,
                                           "adc": round(value, 2)})
                            # Save each independent placement immediately in case of interruption.
                            with partial_csv.open("w", newline="", encoding="utf-8") as tf:
                                writer = csv.DictWriter(tf, fieldnames=["foot", "channel", "placement", "weight_kg", "adc"])
                                writer.writeheader()
                                writer.writerows(trials)
                            print(f"  measured ADC = {value:.1f}")
                        input("Remove ALL weight, then press ENTER: ")
    finally:
        p.disable_muxes()

    count = p.CHANNEL_COUNT
    profile = {
        "schema_version": 1,
        "created_at": datetime.now().astimezone().isoformat(),
        "hardware_signature": signature,
        "repeat_count": args.repeats,
        "relative_spread_tolerance": args.tolerance,
        "mapping_check": mapping,
        "feet": {
            foot: {"baseline": baseline[foot],
                   "reference_1kg": [None]*count,
                   "reference_2kg": [None]*count,
                   "validated": [False]*count,
                   "spread_1kg": [None]*count,
                   "spread_2kg": [None]*count}
            for foot in ("left", "right")
        },
        "trials": trials,
        "quality_review": {},
        "validation_method": "within_session_candidate_not_production_validated",
        "review_settings": {"median_band": args.median_band,
                            "min_inlier_fraction": args.min_inlier_fraction,
                            "candidate_min_repeats": args.candidate_min_repeats},
    }
    for foot in feet_to_test:
        for channel in channels:
            index = channel - p.FIRST_CHANNEL
            row = profile["feet"][foot]
            base = row["baseline"][index]
            vals = {weight: [r["adc"] for r in trials
                             if r["foot"] == foot and r["channel"] == channel
                             and r["weight_kg"] == weight]
                    for weight in (1, 2)}
            a = statistics.median(vals[1]); b = statistics.median(vals[2])
            # Spread is assessed AFTER baseline subtraction, over independent placements.
            spread1 = (max(vals[1])-min(vals[1]))/max(1.0, a-base)
            spread2 = (max(vals[2])-min(vals[2]))/max(1.0, b-base)
            old_range_pass = (a-base > 100 and b-a > 100
                              and spread1 <= args.tolerance and spread2 <= args.tolerance)
            quality = review_sensor(vals[1], vals[2], base,
                                    band=args.median_band,
                                    min_fraction=args.min_inlier_fraction,
                                    min_repeats=args.candidate_min_repeats)
            profile["quality_review"][f"{foot}_C{channel:02d}"] = quality
            candidate = bool(quality["candidate"])
            row["reference_1kg"][index] = round(a, 2)
            row["reference_2kg"][index] = round(b, 2)
            # Candidate selection is NOT production validation. In particular,
            # multiple runs of C01 have shown substantial between-run drift.
            row["validated"][index] = False
            row["spread_1kg"][index] = round(spread1, 4)
            row["spread_2kg"][index] = round(spread2, 4)
            print(f"{foot.upper()} C{channel:02d}: 0={base:.1f} 1={a:.1f} "
                  f"2={b:.1f}, spreads={spread1:.1%}/{spread2:.1%}, "
                  f"old_range={'PASS' if old_range_pass else 'FAIL'}, "
                  f"median_band={quality['one_kg']['inliers']}/{len(vals[1])},"
                  f"{quality['two_kg']['inliers']}/{len(vals[2])}, "
                  f"{'CANDIDATE' if candidate else 'NOT READY'} (not production validated)")

    with (output/"sensor_calibration.json").open("w", encoding="utf-8") as f:
        json.dump(profile, f, indent=2, ensure_ascii=False)
    with (output/"placement_trials.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["foot", "channel", "placement", "weight_kg", "adc"])
        w.writeheader(); w.writerows(trials)
    make_plot(profile, output)
    n_valid = sum(sum(row["validated"]) for row in profile["feet"].values())
    print(f"\nValidated: {n_valid}/{2*count} sensors")
    print("Data saved to:", output)
    print("Reminder: check between-run repeatability before production correction.")
    print("\nTo use measured BASELINES only, set:")
    print("  FSR_CALIBRATION_MODE=baseline")
    print(f"  FSR_CALIBRATION_FILE={output/'sensor_calibration.json'}")
    if n_valid == 2*count:
        print("All channels passed. 'full' is now possible after AI-scale tests.")
    else:
        print("Full sensitivity mode NOT READY (unvalidated/missing channels).")


if __name__ == "__main__":
    main()
