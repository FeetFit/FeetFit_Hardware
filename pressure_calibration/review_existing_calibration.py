"""Re-evaluate an existing calibration JSON without any GPIO or service changes.

Example:
  python -m pressure_calibration.review_existing_calibration \
      --profile /home/chaeni/feetfit-api/pressure_calibration/sensor_correction_data/20261019_015640/sensor_calibration.json

Creates sensor_calibration_reviewed.json beside the source profile. It never
changes original data or .env. The service's legacy mode ignores this file.
"""
import argparse
import copy
import json
import statistics
from datetime import datetime
from pathlib import Path
from .calibration_quality import review_sensor


def review_profile(profile, *, band=0.2, fraction=0.9, min_repeats=10):
    reviewed = copy.deepcopy(profile)
    sig = reviewed["hardware_signature"]
    first = sig["first_channel"]
    count = sig["channel_count_per_foot"]
    reviewed["reviewed_at"] = datetime.now().astimezone().isoformat()
    reviewed["validation_method"] = "within_session_median_band_candidate"
    reviewed["review_settings"] = {
        "band_fraction": band, "minimum_fraction": fraction,
        "minimum_repeats": min_repeats,
    }
    reviewed["quality_review"] = {}
    for foot in ("left", "right"):
        row = reviewed["feet"][foot]
        for i in range(count):
            channel = first + i
            vals = {
                weight: [float(t["adc"]) for t in reviewed["trials"]
                         if t["foot"] == foot and int(t["channel"]) == channel
                         and int(t["weight_kg"]) == weight]
                for weight in (1, 2)
            }
            if not (vals[1] and vals[2]):
                row["validated"][i] = False
                continue
            b = float(row["baseline"][i])
            quality = review_sensor(vals[1], vals[2], b, band=band,
                                    min_fraction=fraction, min_repeats=min_repeats)
            reviewed["quality_review"][f"{foot}_C{channel:02d}"] = quality
            row["reference_1kg"][i] = quality["one_kg"]["median_adc"]
            row["reference_2kg"][i] = quality["two_kg"]["median_adc"]
            row["spread_1kg"][i] = quality["one_kg"]["range_spread"]
            row["spread_2kg"][i] = quality["two_kg"]["range_spread"]
            # Preserve production safety: acceptance of a candidate is NOT
            # equivalent to an independently validated sensitivity profile.
            row["validated"][i] = False
    return reviewed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--band", type=float, default=0.20)
    parser.add_argument("--min-fraction", type=float, default=0.90)
    parser.add_argument("--min-repeats", type=int, default=10)
    args = parser.parse_args()
    if not (0 < args.band < 1) or not (0 < args.min_fraction <= 1) or args.min_repeats < 3:
        parser.error("Require 0<band<1, 0<min-fraction<=1, min-repeats>=3")
    src = Path(args.profile).expanduser().resolve()
    with src.open(encoding="utf-8") as f:
        profile = json.load(f)
    if profile.get("schema_version") != 1:
        parser.error("Only existing schema_version=1 calibration files supported")
    reviewed = review_profile(profile, band=args.band,
                              fraction=args.min_fraction, min_repeats=args.min_repeats)
    dst = src.with_name("sensor_calibration_reviewed.json")
    if dst.exists():
        parser.error(f"Output already exists: {dst}; refusing to overwrite")
    with dst.open("w", encoding="utf-8") as f:
        json.dump(reviewed, f, ensure_ascii=False, indent=2)
    for sensor, result in reviewed["quality_review"].items():
        a = result["one_kg"]
        b = result["two_kg"]
        print(f"{sensor}: 0kg={reviewed['feet'][sensor.split('_')[0]]['baseline'][int(sensor[-2:])-reviewed['hardware_signature']['first_channel']]:.1f} "
              f"1kg={a['median_adc']:.1f} ({a['inliers']}/{a['count']}) "
              f"2kg={b['median_adc']:.1f} ({b['inliers']}/{b['count']}) "
              f"=> {'CANDIDATE' if result['candidate'] else 'NOT READY'}")
    print("Saved review to:", dst)
    print("No production sensitivity applied; .env and original JSON unchanged.")
    print("A candidate needs cross-session checks and a common scale across sensors.")


if __name__ == "__main__":
    main()
