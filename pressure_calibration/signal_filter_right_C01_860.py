import atexit
import csv
import os
import time
from datetime import datetime

import board
import busio
import digitalio

from adafruit_ads1x15.ads1115 import ADS1115
from adafruit_ads1x15.analog_in import AnalogIn
from adafruit_ads1x15.ads1x15 import Pin

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


# ============================================================
# 설정
# ============================================================

# RIGHT MUX
MUX_EN = board.D27

MUX_S0 = board.D22
MUX_S1 = board.D23
MUX_S2 = board.D24
MUX_S3 = board.D25

# RIGHT SIG -> ADS1115 A1
ADS_CHANNEL = Pin.A1

# 측정할 MUX 채널
MUX_CHANNEL = 1

# 초기 샘플 제외
DISCARD_SAMPLES = 3

# Median Filter
MEDIAN_WINDOW = 5

# 샘플 간격
SAMPLE_INTERVAL = 0.05

# 각 단계 측정 시간
PHASE_SECONDS = 5


# ============================================================
# MUX 초기화
# ============================================================

en = digitalio.DigitalInOut(MUX_EN)
en.direction = digitalio.Direction.OUTPUT

s0 = digitalio.DigitalInOut(MUX_S0)
s1 = digitalio.DigitalInOut(MUX_S1)
s2 = digitalio.DigitalInOut(MUX_S2)
s3 = digitalio.DigitalInOut(MUX_S3)

for pin in (s0, s1, s2, s3):
    pin.direction = digitalio.Direction.OUTPUT


def select_channel(channel):
    """CD74HC4067 채널 선택"""

    s0.value = bool(channel & 0x01)
    s1.value = bool(channel & 0x02)
    s2.value = bool(channel & 0x04)
    s3.value = bool(channel & 0x08)


# MUX Enable = LOW
en.value = False

# C01 선택
select_channel(MUX_CHANNEL)


# Cleanup MUX GPIO when the process exits.
def cleanup_mux():
    try:
        en.value = True
    except Exception:
        pass
    for pin in (en, s0, s1, s2, s3):
        try:
            pin.deinit()
        except Exception:
            pass


atexit.register(cleanup_mux)


# ============================================================
# ADS1115 초기화
# ============================================================

i2c = busio.I2C(
    board.SCL,
    board.SDA,
)

ads = ADS1115(
    i2c,
    address=0x48,
)

ads.gain = 1
ads.data_rate = 860

adc = AnalogIn(
    ads,
    ADS_CHANNEL,
)


# ============================================================
# Median Filter
# ============================================================

def median_filter(values, window=5):

    result = []

    half = window // 2

    for i in range(len(values)):

        start = max(
            0,
            i - half
        )

        end = min(
            len(values),
            i + half + 1
        )

        window_values = values[start:end]

        sorted_values = sorted(
            window_values
        )

        median = sorted_values[
            len(sorted_values) // 2
        ]

        result.append(median)

    return result


# ============================================================
# 안내
# ============================================================

print()
print("=" * 70)
print("RIGHT C01 - SIGNAL FILTER VALIDATION")
print("=" * 70)

print()
print("RIGHT MUX")
print("  EN : GPIO27")
print("  S0 : GPIO22")
print("  S1 : GPIO23")
print("  S2 : GPIO24")
print("  S3 : GPIO25")

print()
print("MUX CHANNEL : C01")
print("ADS1115     : A1")
print()

print("Measurement sequence")
print("  1. NO LOAD")
print("  2. PRESS C01")
print("  3. HOLD")
print("  4. RELEASE")
print()

input("Ready? Press ENTER to start: ")


# ============================================================
# 안정화
# ============================================================

print()
print("Sensor settling...")
time.sleep(2)


# ============================================================
# 초기 샘플 버리기
# ============================================================

for _ in range(DISCARD_SAMPLES):

    _ = adc.value

    time.sleep(
        SAMPLE_INTERVAL
    )


raw_values = []
phase_labels = []


def measure_phase(name, message):

    print()
    print(message)

    start = time.time()

    while time.time() - start < PHASE_SECONDS:

        value = adc.value

        raw_values.append(value)
        phase_labels.append(name)

        time.sleep(
            SAMPLE_INTERVAL
        )


# ============================================================
# 1. 무하중
# ============================================================

measure_phase(
    "NO_LOAD",
    "[1/4] NO LOAD - remove all pressure."
)


# ============================================================
# 2. 누르기
# ============================================================

measure_phase(
    "PRESS",
    "[2/4] PRESS - press RIGHT C01 now!"
)


# ============================================================
# 3. 유지
# ============================================================

measure_phase(
    "HOLD",
    "[3/4] HOLD - keep pressing RIGHT C01."
)


# ============================================================
# 4. 손 떼기
# ============================================================

measure_phase(
    "RELEASE",
    "[4/4] RELEASE - release pressure now!"
)


# ============================================================
# Median Filter
# ============================================================

filtered_values = median_filter(
    raw_values,
    MEDIAN_WINDOW
)


# ============================================================
# 저장 폴더
# ============================================================

timestamp = datetime.now().strftime(
    "%Y%m%d_%H%M%S"
)

save_dir = (
    "pressure_calibration/"
    "signal_filter_860_data/"
    f"{timestamp}"
)

os.makedirs(
    save_dir,
    exist_ok=True
)


# ============================================================
# CSV 저장
# ============================================================

csv_path = os.path.join(
    save_dir,
    "right_C01_controlled.csv"
)

with open(
    csv_path,
    "w",
    newline="",
    encoding="utf-8"
) as f:

    writer = csv.writer(f)

    writer.writerow([
        "sample",
        "raw",
        "phase",
        "filtered",
    ])

    for i in range(len(raw_values)):

        writer.writerow([
            i,
            raw_values[i],
            phase_labels[i],
            filtered_values[i],
        ])


# ============================================================
# 그래프
# ============================================================

x = list(
    range(len(raw_values))
)

# ------------------------------------------------------------
# 정사각형 그래프
# ------------------------------------------------------------

plt.figure(
    figsize=(9, 9)
)


# RAW
plt.plot(
    x,
    raw_values,
    label="RAW",
    linewidth=1.4
)


# Filtered
plt.plot(
    x,
    filtered_values,
    label=f"Median Filtered (window={MEDIAN_WINDOW})",
    linewidth=2.8
)


# ------------------------------------------------------------
# Phase 경계
# ------------------------------------------------------------

previous_phase = phase_labels[0]

for i, phase in enumerate(phase_labels):

    if phase != previous_phase:

        plt.axvline(
            i,
            linestyle="--",
            alpha=0.5,
            linewidth=1
        )

        previous_phase = phase


# ------------------------------------------------------------
# Phase 이름
# ------------------------------------------------------------

phase_names = {
    "NO_LOAD": "No Load",
    "PRESS": "Press",
    "HOLD": "Hold",
    "RELEASE": "Release",
}


ymax = max(
    raw_values
)

label_y = ymax * 0.95


for phase in (
    "NO_LOAD",
    "PRESS",
    "HOLD",
    "RELEASE",
):

    indices = [
        i
        for i, p in enumerate(phase_labels)
        if p == phase
    ]

    if indices:

        center = (
            indices[0]
            + indices[-1]
        ) / 2

        plt.text(
            center,
            label_y,
            phase_names[phase],
            ha="center",
            va="top",
            fontsize=13,
            fontweight="bold",
        )


# ------------------------------------------------------------
# 제목
# ------------------------------------------------------------

plt.title(
    "RIGHT C01 - FSR Signal Filtering",
    fontsize=20,
    fontweight="bold",
    pad=16,
)


# ------------------------------------------------------------
# 축
# ------------------------------------------------------------

plt.xlabel(
    "Sample",
    fontsize=15,
)

plt.ylabel(
    "ADC Value",
    fontsize=15,
)

plt.xticks(
    fontsize=12
)

plt.yticks(
    fontsize=12
)


# ------------------------------------------------------------
# 범례
# ------------------------------------------------------------

plt.legend(
    fontsize=12,
    loc="upper right",
    frameon=True,
)


# ------------------------------------------------------------
# Grid
# ------------------------------------------------------------

plt.grid(
    alpha=0.25,
    linewidth=0.8,
)


# ------------------------------------------------------------
# 여백
# ------------------------------------------------------------

plt.tight_layout()


# ------------------------------------------------------------
# PNG 저장
# ------------------------------------------------------------

png_path = os.path.join(
    save_dir,
    "right_C01_filtering.png"
)

plt.savefig(
    png_path,
    dpi=300,
    bbox_inches="tight",
)

plt.close()


# ============================================================
# 결과
# ============================================================

print()
print("=" * 70)
print("RESULT")
print("=" * 70)

print(
    f"Samples          : "
    f"{len(raw_values)}"
)

print(
    f"Raw Average      : "
    f"{sum(raw_values) / len(raw_values):.1f}"
)

print(
    f"Filtered Average : "
    f"{sum(filtered_values) / len(filtered_values):.1f}"
)

print(
    f"Raw Min          : "
    f"{min(raw_values):.1f}"
)

print(
    f"Raw Max          : "
    f"{max(raw_values):.1f}"
)

print(
    f"Filtered Min     : "
    f"{min(filtered_values):.1f}"
)

print(
    f"Filtered Max     : "
    f"{max(filtered_values):.1f}"
)

print()
print("CSV saved:")
print(csv_path)

print()
print("GRAPH saved:")
print(png_path)

print()
print("=" * 70)
print("Measurement complete")
print("=" * 70)
