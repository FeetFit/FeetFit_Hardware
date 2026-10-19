import os
import csv
import time
import statistics
from datetime import datetime

import board
import busio
import digitalio

from adafruit_ads1x15.ads1115 import ADS1115
from adafruit_ads1x15.analog_in import AnalogIn
from adafruit_ads1x15.ads1x15 import Pin


# =========================================================
# C01 / LEFT FSR CALIBRATION
# 0 kg / 1 kg / 2 kg
# =========================================================

# ---------------------------------------------------------
# MUX
# ---------------------------------------------------------
MUX_EN = board.D27

MUX_S0 = board.D22
MUX_S1 = board.D23
MUX_S2 = board.D24
MUX_S3 = board.D25

MUX_CHANNEL = 1          # C01


# ---------------------------------------------------------
# ADS1115
# ---------------------------------------------------------
ADS_ADDRESS = 0x48
ADS_CHANNEL = Pin.A1     # LEFT -> ADS A1


# ---------------------------------------------------------
# Measurement
# ---------------------------------------------------------
STABILIZE_SECONDS = 2.0
SAMPLES = 30

DISCARD_INITIAL = 3


# ---------------------------------------------------------
# Output
# ---------------------------------------------------------
TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")

OUTPUT_DIR = (
    f"pressure_calibration/"
    f"sensor_correction_data/"
    f"{TIMESTAMP}"
)

os.makedirs(OUTPUT_DIR, exist_ok=True)

CSV_PATH = os.path.join(
    OUTPUT_DIR,
    "left_C01_0_1_2kg_calibration.csv"
)

SUMMARY_PATH = os.path.join(
    OUTPUT_DIR,
    "left_C01_calibration_summary.csv"
)


# =========================================================
# MUX SETUP
# =========================================================

mux_en = digitalio.DigitalInOut(MUX_EN)
mux_en.direction = digitalio.Direction.OUTPUT

s0 = digitalio.DigitalInOut(MUX_S0)
s1 = digitalio.DigitalInOut(MUX_S1)
s2 = digitalio.DigitalInOut(MUX_S2)
s3 = digitalio.DigitalInOut(MUX_S3)

for pin in (s0, s1, s2, s3):
    pin.direction = digitalio.Direction.OUTPUT


def mux_disable():
    mux_en.value = True


def mux_enable():
    mux_en.value = False


def select_mux_channel(channel):
    if not 0 <= channel <= 15:
        raise ValueError("MUX channel must be 0~15")

    s0.value = bool(channel & 0x01)
    s1.value = bool(channel & 0x02)
    s2.value = bool(channel & 0x04)
    s3.value = bool(channel & 0x08)


# =========================================================
# ADS SETUP
# =========================================================

i2c = busio.I2C(
    board.SCL,
    board.SDA,
)

ads = ADS1115(
    i2c,
    address=ADS_ADDRESS,
)

# 기존 pressure.py 설정과 맞춰도 됨.
ads.gain = 1
ads.data_rate = 128

adc = AnalogIn(
    ads,
    ADS_CHANNEL,
)


# =========================================================
# READ
# =========================================================

def read_value():
    mux_disable()
    time.sleep(0.01)

    select_mux_channel(MUX_CHANNEL)

    mux_enable()
    time.sleep(0.02)

    return float(adc.value)


def collect_samples():
    values = []

    # 초기값 버림
    for _ in range(DISCARD_INITIAL):
        read_value()
        time.sleep(0.02)

    for _ in range(SAMPLES):
        values.append(read_value())
        time.sleep(0.03)

    return values


# =========================================================
# MEASUREMENT
# =========================================================

def measure_weight(weight):
    print()
    print("=" * 70)
    print(f"{weight} kg MEASUREMENT")
    print("=" * 70)

    if weight == 0:
        print("→ C01 위에 아무것도 올리지 마세요.")
    else:
        print(f"→ {weight} kg 추를 C01 위치에 정확히 올려주세요.")

    input("준비되었으면 ENTER를 누르세요.")

    print()
    print(f"{STABILIZE_SECONDS:.1f}초 안정화 중...")
    time.sleep(STABILIZE_SECONDS)

    values = collect_samples()

    average = statistics.mean(values)
    median = statistics.median(values)
    minimum = min(values)
    maximum = max(values)

    print()
    print(f"Samples : {len(values)}")
    print(f"Average : {average:.1f}")
    print(f"Median  : {median:.1f}")
    print(f"Min     : {minimum:.1f}")
    print(f"Max     : {maximum:.1f}")

    return {
        "weight": weight,
        "values": values,
        "average": average,
        "median": median,
        "min": minimum,
        "max": maximum,
    }


# =========================================================
# MAIN
# =========================================================

try:

    print()
    print("=" * 70)
    print("LEFT C01 - 0 / 1 / 2 kg CALIBRATION")
    print("=" * 70)

    print()
    print("LEFT MUX")
    print("  EN : GPIO27")
    print("  S0 : GPIO22")
    print("  S1 : GPIO23")
    print("  S2 : GPIO24")
    print("  S3 : GPIO25")

    print()
    print("MUX CHANNEL : C01")
    print("ADS1115     : A1")

    print()
    print("측정 순서")
    print("  1. 0 kg - 무하중")
    print("  2. 1 kg - 1 kg 추")
    print("  3. 2 kg - 2 kg 추")

    print()
    print("주의:")
    print("  • 모든 측정에서 C01의 동일한 위치를 사용하세요.")
    print("  • 실리콘 → 돌기 → FSR 구조를 그대로 유지하세요.")
    print("  • 추는 센서 중앙에 최대한 동일하게 올리세요.")

    input("\n준비되었으면 ENTER를 누르세요.")

    mux_enable()

    results = []

    # -----------------------------------------------------
    # 0 kg
    # -----------------------------------------------------
    results.append(
        measure_weight(0)
    )

    # -----------------------------------------------------
    # 1 kg
    # -----------------------------------------------------
    results.append(
        measure_weight(1)
    )

    # -----------------------------------------------------
    # 2 kg
    # -----------------------------------------------------
    results.append(
        measure_weight(2)
    )

    # -----------------------------------------------------
    # Calculate
    # -----------------------------------------------------

    baseline = results[0]["median"]
    reference_1kg = results[1]["median"]
    reference_2kg = results[2]["median"]

    sensitivity_range = reference_2kg - baseline

    print()
    print("=" * 70)
    print("CALIBRATION RESULT")
    print("=" * 70)

    print()
    print(f"Baseline (0 kg)   : {baseline:.1f}")
    print(f"Reference (1 kg)  : {reference_1kg:.1f}")
    print(f"Reference (2 kg)  : {reference_2kg:.1f}")
    print(f"Sensitivity Range : {sensitivity_range:.1f}")

    # -----------------------------------------------------
    # Normalized response
    # -----------------------------------------------------

    print()
    print("Normalized response")

    for result in results:

        corrected = result["median"] - baseline

        if sensitivity_range > 0:
            normalized = (
                corrected /
                sensitivity_range *
                100.0
            )
        else:
            normalized = 0.0

        normalized = max(
            0.0,
            min(100.0, normalized)
        )

        print(
            f"{result['weight']} kg"
            f" -> {result['median']:.1f} ADC"
            f" -> {normalized:.1f}%"
        )

    # -----------------------------------------------------
    # Save detailed CSV
    # -----------------------------------------------------

    with open(
        CSV_PATH,
        "w",
        newline="",
        encoding="utf-8",
    ) as f:

        writer = csv.writer(f)

        writer.writerow([
            "weight_kg",
            "sample",
            "adc_value",
        ])

        for result in results:

            for i, value in enumerate(
                result["values"],
                start=1,
            ):

                writer.writerow([
                    result["weight"],
                    i,
                    value,
                ])

    # -----------------------------------------------------
    # Save summary
    # -----------------------------------------------------

    with open(
        SUMMARY_PATH,
        "w",
        newline="",
        encoding="utf-8",
    ) as f:

        writer = csv.writer(f)

        writer.writerow([
            "weight_kg",
            "average",
            "median",
            "min",
            "max",
            "zero_corrected",
            "normalized_percent",
        ])

        for result in results:

            corrected = (
                result["median"] -
                baseline
            )

            if sensitivity_range > 0:
                normalized = (
                    corrected /
                    sensitivity_range *
                    100.0
                )
            else:
                normalized = 0.0

            normalized = max(
                0.0,
                min(100.0, normalized)
            )

            writer.writerow([
                result["weight"],
                f"{result['average']:.2f}",
                f"{result['median']:.2f}",
                f"{result['min']:.2f}",
                f"{result['max']:.2f}",
                f"{corrected:.2f}",
                f"{normalized:.2f}",
            ])

    print()
    print("Saved:")
    print(CSV_PATH)
    print(SUMMARY_PATH)

    print()
    print("=" * 70)
    print("측정 및 보정 기준 산출 완료")
    print("=" * 70)

finally:

    mux_disable()

    mux_en.deinit()
    s0.deinit()
    s1.deinit()
    s2.deinit()
    s3.deinit()
