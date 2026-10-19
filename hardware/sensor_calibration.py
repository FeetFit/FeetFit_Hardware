"""Pure-Python pressure sensor profile validation and relative sensitivity scaling.

No GPIO imports.  A profile is only applied after the operator explicitly chooses
FSR_CALIBRATION_MODE=baseline or full. No single C01 reference is reused for other
sensors, and full mode is rejected until all 24 channels pass validation.
"""

import json
import math
import statistics
from pathlib import Path


def hardware_signature(*, left_en, right_en, left_ads, right_ads,
                       gain, data_rate, first_channel, last_channel,
                       channel_count, median_window, valid_reads,
                       mux_select_pins=None, active_low=None, fixed_resistor_ohms=None):
    return {
        "left_en_gpio": int(left_en),
        "right_en_gpio": int(right_en),
        "left_ads_channel": int(left_ads),
        "right_ads_channel": int(right_ads),
        "ads_gain": int(gain),
        "ads_data_rate": int(data_rate),
        "first_channel": int(first_channel),
        "last_channel": int(last_channel),
        "channel_count_per_foot": int(channel_count),
        "median_window": int(median_window),
        "valid_reads": int(valid_reads),
        "mux_select_pins": list(mux_select_pins) if mux_select_pins is not None else None,
        "active_low": bool(active_low) if active_low is not None else None,
        "fixed_resistor_ohms": int(fixed_resistor_ohms) if fixed_resistor_ohms is not None else None,
    }


def _numbers(values, label, count, nullable=False):
    if not isinstance(values, list) or len(values) != count:
        raise ValueError(f"{label}: expected list of {count} values")
    for value in values:
        if nullable and value is None:
            continue
        if not isinstance(value, (float, int)) or not math.isfinite(value):
            raise ValueError(f"{label}: non-finite/non-numeric entry")
    return values


def load_profile(filename, mode, signature):
    if mode not in ("legacy", "baseline", "full"):
        raise ValueError("FSR_CALIBRATION_MODE: use legacy / baseline / full")
    if mode == "legacy":
        return None
    if not filename:
        raise ValueError("FSR_CALIBRATION_FILE is required for baseline/full mode")
    path = Path(filename).expanduser()
    with path.open(encoding="utf-8") as stream:
        profile = json.load(stream)
    if profile.get("schema_version") != 1:
        raise ValueError("Unsupported pressure calibration profile version")
    if profile.get("hardware_signature") != signature:
        raise ValueError(
            "Calibration hardware settings do not match current .env/config. "
            "Check physical LEFT/RIGHT wiring, ADS gain/rate, and filtering."
        )
    feet = profile.get("feet")
    if not isinstance(feet, dict):
        raise ValueError("Missing feet section")
    count = signature["channel_count_per_foot"]
    for foot in ("left", "right"):
        if foot not in feet or not isinstance(feet[foot], dict):
            raise ValueError(f"Missing {foot} calibration data")
        data = feet[foot]
        _numbers(data.get("baseline"), f"{foot}.baseline", count)
        _numbers(data.get("reference_1kg"), f"{foot}.reference_1kg", count, True)
        _numbers(data.get("reference_2kg"), f"{foot}.reference_2kg", count, True)
        statuses = data.get("validated")
        if not isinstance(statuses, list) or len(statuses) != count or any(type(v) is not bool for v in statuses):
            raise ValueError(f"{foot}.validated: expected {count} bools")
        if mode == "full":
            for i in range(count):
                a = data["reference_1kg"][i]
                b = data["reference_2kg"][i]
                base = data["baseline"][i]
                if not statuses[i] or a is None or b is None or not (base < a < b):
                    raise ValueError(
                        f"Full sensitivity correction blocked: {foot} "
                        f"C{i + signature['first_channel']:02d} is not validated."
                    )
    return profile


def correct_sensitivity(values, foot, profile):
    """Map each sensor's 0/1/2kg empirical ADC landmarks to shared landmarks.

    Outputs a positive ADC-*like* relative signal, NOT an accurate kg or kPa
    measurement. Above the tested 2kg range the upper segment is extrapolated,
    so out-of-range values should not be interpreted as accurate force.
    """
    if profile is None:
        raise ValueError("Missing profile")
    count = profile["hardware_signature"]["channel_count_per_foot"]
    _numbers(values, f"{foot}.input", count)
    feet = profile["feet"]
    a_spans = []
    b_spans = []
    for side in ("left", "right"):
        row = feet[side]
        for i in range(count):
            if not row["validated"][i]:
                raise ValueError("Unvalidated sensor: full correction is not allowed")
            base = row["baseline"][i]
            a_spans.append(row["reference_1kg"][i] - base)
            b_spans.append(row["reference_2kg"][i] - base)
    a_target = statistics.median(a_spans)
    b_target = statistics.median(b_spans)
    if not (0 < a_target < b_target):
        raise ValueError("Invalid shared calibration landmarks")
    row = feet[foot]
    result = []
    for i, val in enumerate(values):
        x = max(0.0, float(val))
        base = row["baseline"][i]
        a = row["reference_1kg"][i] - base
        b = row["reference_2kg"][i] - base
        if not (0 < a < b):
            raise ValueError("Non-monotone calibration anchors")
        if x <= a:
            corrected = x * a_target / a
        elif x <= b:
            corrected = a_target + (x - a) * (b_target - a_target) / (b - a)
        else:
            corrected = b_target + (x - b) * (b_target - a_target) / (b - a)
        result.append(max(0.0, corrected))
    return result
