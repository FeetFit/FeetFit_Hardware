"""Collect within-session sensitivity candidates from separate sensor sessions.

Does not use GPIO, alter .env, or enable the production 'full' calibration.
Stored values are weight-response landmarks, not scalar force coefficients.

Example:
  python -m pressure_calibration.candidate_registry \
    --profile pressure_calibration/sensor_correction_data/20261019_015640/sensor_calibration_reviewed.json
"""

import argparse
import json
from datetime import datetime
from pathlib import Path


def register_candidates(registry, reviewed, source, *, replace=False,
                        manual_include=(), override_reason=None):
    signature = reviewed['hardware_signature']
    if registry is None:
        registry = {"schema_version": 1, "hardware_signature": signature,
                    "usage": "Offline sensor candidates only. NOT a production calibration profile.",
                    "sensors": {}}
    if registry['hardware_signature'] != signature:
        raise ValueError('Hardware signature mismatch: cannot mix calibration settings')
    # A manual inclusion is a bookkeeping decision, NOT sensor verification.
    manual_include = set(manual_include)
    known = set(reviewed.get('quality_review', {}))
    unknown = manual_include - known
    if unknown:
        raise ValueError(f'Sensors not found in reviewed profile: {sorted(unknown)}')
    if manual_include and not (override_reason and override_reason.strip()):
        raise ValueError('--reason is required with --manual-include')
    added = []
    first = signature['first_channel']
    for sensor, quality in reviewed.get('quality_review', {}).items():
        overridden = sensor in manual_include and not quality.get('candidate')
        if not quality.get('candidate') and not overridden:
            continue
        side, c = sensor.split('_C', 1)
        index = int(c) - first
        row = reviewed['feet'][side]
        base = float(row['baseline'][index])
        r1 = float(row['reference_1kg'][index])
        r2 = float(row['reference_2kg'][index])
        if not (base < r1 < r2):
            raise ValueError(f'Invalid anchor ordering for {sensor}')
        if sensor in registry['sensors'] and not replace:
            raise ValueError(f'{sensor} already recorded; use --replace only deliberately')
        registry['sensors'][sensor] = {
            "baseline_adc_at_capture": base,
            "reference_1kg_adc": r1,
            "reference_2kg_adc": r2,
            "delta_1kg_adc": round(r1 - base, 2),
            "delta_2kg_adc": round(r2 - base, 2),
            "quality_review": quality,
            "capture_file": str(source),
            "status": "manual_override_unvalidated" if overridden else "within_session_candidate",
            "warning": "Cross-session force reproducibility and common inter-sensor scale not established",
        }
        if overridden:
            registry['sensors'][sensor]['manual_override'] = {
                'reason': override_reason.strip(),
                'included_at': datetime.now().astimezone().isoformat(),
                'within_session_review_passed': False,
            }
        added.append(sensor)
    registry['updated_at'] = datetime.now().astimezone().isoformat()
    return registry, added


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--profile', required=True, help='Reviewed sensor_calibration_reviewed.json')
    ap.add_argument('--registry', default='pressure_calibration/sensor_correction_data/calibration_candidates.json')
    ap.add_argument('--replace', action='store_true', help='Explicitly replace existing candidate')
    ap.add_argument('--manual-include', action='append', default=[], metavar='FOOT_CNN',
                    help='Manually record a failed channel WITHOUT changing its failed review')
    ap.add_argument('--reason', help='Required justification for manual inclusion')
    args = ap.parse_args()
    src = Path(args.profile).expanduser().resolve()
    dst = Path(args.registry).expanduser().resolve()
    with src.open(encoding='utf-8') as f:
        reviewed = json.load(f)
    if reviewed.get('validation_method') != 'within_session_median_band_candidate':
        ap.error('Expected reviewed JSON from review_existing_calibration.py')
    registry = None
    if dst.exists():
        with dst.open(encoding='utf-8') as f:
            registry = json.load(f)
    try:
        updated, added = register_candidates(registry, reviewed, src, replace=args.replace,
                                             manual_include=args.manual_include,
                                             override_reason=args.reason)
    except ValueError as exc:
        ap.error(str(exc))
    dst.parent.mkdir(parents=True, exist_ok=True)
    temp = dst.with_suffix('.tmp')
    with temp.open('w', encoding='utf-8') as f:
        json.dump(updated, f, indent=2, ensure_ascii=False)
    temp.replace(dst)
    print('Registered:', ', '.join(added) if added else '(none passed)')
    for sensor in added:
        entry = updated['sensors'][sensor]
        print(f"  {sensor}: {entry['status']} | "
              f"0kg={entry['baseline_adc_at_capture']:.2f} "
              f"1kg={entry['reference_1kg_adc']:.2f} "
              f"2kg={entry['reference_2kg_adc']:.2f}")
    print(f'Candidate registry: {dst} ({len(updated["sensors"])}/24 sensor candidates)')
    print('Production calibration / .env: unchanged')


if __name__ == '__main__':
    main()
