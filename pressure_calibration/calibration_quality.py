"""Offline quality review for independent weight placements.

This checks consistency of ADC readings in a single test session. Passing
is NOT evidence of calibrated absolute force or cross-session stability.
"""

import math
import statistics


def review_weight(values, baseline, *, band=0.20, min_fraction=0.90, min_repeats=10):
    values = [float(v) for v in values]
    if any(not math.isfinite(v) for v in values):
        raise ValueError("Readings must be finite numbers")
    if not values:
        raise ValueError("At least one reading is required")
    med = statistics.median(values)
    corrected = med - float(baseline)
    lower = float(baseline) + corrected * (1.0 - band)
    upper = float(baseline) + corrected * (1.0 + band)
    included = [v for v in values if corrected > 0 and lower <= v <= upper]
    old_spread = (max(values) - min(values)) / max(1.0, corrected)
    passed = (len(values) >= min_repeats and corrected > 100
              and len(included) / len(values) >= min_fraction)
    return {
        "count": len(values),
        "median_adc": round(med, 2),
        "median_minus_baseline_adc": round(corrected, 2),
        "inliers": len(included),
        "inlier_fraction": round(len(included) / len(values), 4),
        "range_spread": round(old_spread, 4),
        "band_fraction": band,
        "minimum_fraction": min_fraction,
        "minimum_repeats": min_repeats,
        "passed_session_repeatability": bool(passed),
    }


def review_sensor(values_1kg, values_2kg, baseline, *, band=0.20,
                  min_fraction=0.90, min_repeats=10):
    one = review_weight(values_1kg, baseline, band=band,
                        min_fraction=min_fraction, min_repeats=min_repeats)
    two = review_weight(values_2kg, baseline, band=band,
                        min_fraction=min_fraction, min_repeats=min_repeats)
    monotone = two["median_adc"] > one["median_adc"] + 100
    passed = (one["passed_session_repeatability"]
              and two["passed_session_repeatability"] and monotone)
    return {"one_kg": one, "two_kg": two,
            "monotonic_0_1_2kg": bool(monotone),
            "candidate": bool(passed),
            "caution": "Within-session candidate only; no cross-session accuracy validation"}
