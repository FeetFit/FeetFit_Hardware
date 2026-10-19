import csv
import os
import time
import statistics
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
# 02. SENSOR VALUE CORRECTION & NORMALIZATION
#
# LEFT C01
#
# MUX EN : GPIO27
# S0     : GPIO22
# S1     : GPIO23
# S2     : GPIO24
# S3     : GPIO25
#
# C01 -> MUX SIG -> ADS1115 A1
# ============================================================


# ============================================================
# 기본 설정
# ============================================================

MUX_CHANNEL = 1

ADS_CHANNEL = Pin.A1
ADS_ADDRESS = 0x48

DISCARD_SAMPLES = 3
MEDIAN_WINDOW = 5

SAMPLE_INTERVAL = 0.05

# Calibration 측정 시간
BASELINE_SECONDS = 5
REFERENCE_SECONDS = 5

# Controlled test 각 구간
PHASE_SECONDS = 5


# ============================================================
# GPIO
# ============================================================

MUX_EN = digitalio.DigitalInOut(board.D27)

MUX_S0 = digitalio.DigitalInOut(board.D22)
MUX_S1 = digitalio.DigitalInOut(board.D23)
MUX_S2 = digitalio.DigitalInOut(board.D24)
MUX_S3 = digitalio.DigitalInOut(board.D25)


MUX_EN.direction = digitalio.Direction.OUTPUT

for pin in (
    MUX_S0,
    MUX_S1,
    MUX_S2,
    MUX_S3,
):
    pin.direction = digitalio.Direction.OUTPUT


# ============================================================
# MUX
# ============================================================

def select_channel(channel):

    MUX_S0.value = bool(channel & 0b0001)
    MUX_S1.value = bool(channel & 0b0010)
    MUX_S2.value = bool(channel & 0b0100)
    MUX_S3.value = bool(channel & 0b1000)


# MUX 활성화
MUX_EN.value = False

# C01 선택
select_channel(MUX_CHANNEL)


# ============================================================
# ADS1115
# ============================================================

i2c = busio.I2C(
    board.SCL,
    board.SDA,
)

ads = ADS1115(
    i2c,
    address=ADS_ADDRESS,
)

ads.gain = 1
ads.data_rate = 128

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

        result.append(
            statistics.median(window_values)
        )

    return result


# ============================================================
# 초기 샘플 제외
# ============================================================

def discard_initial(values):

    if len(values) <= DISCARD_SAMPLES:
        return values

    return values[DISCARD_SAMPLES:]


# ============================================================
# 단순 측정
# ============================================================

def measure_seconds(seconds):

    values = []

    start = time.time()

    while time.time() - start < seconds:

        values.append(
            float(adc.value)
        )

        time.sleep(
            SAMPLE_INTERVAL
        )

    return values


# ============================================================
# Calibration 측정
# ============================================================

def measure_calibration(name, message, seconds):

    print()
    print(message)

    values = measure_seconds(seconds)

    values = discard_initial(values)

    filtered = median_filter(
        values,
        MEDIAN_WINDOW
    )

    average = statistics.mean(
        filtered
    )

    print(
        f"{name} Filtered Average : "
        f"{average:.1f}"
    )

    print(
        f"{name} Filtered Min     : "
        f"{min(filtered):.1f}"
    )

    print(
        f"{name} Filtered Max     : "
        f"{max(filtered):.1f}"
    )

    return values, filtered, average


# ============================================================
# Controlled Test
# ============================================================

def measure_phase(
    phase_name,
    message,
    seconds
):

    print()
    print(message)

    values = []

    start = time.time()

    while time.time() - start < seconds:

        values.append(
            float(adc.value)
        )

        time.sleep(
            SAMPLE_INTERVAL
        )

    filtered = median_filter(
        discard_initial(values),
        MEDIAN_WINDOW
    )

    return filtered


# ============================================================
# 시작 안내
# ============================================================

print()
print("=" * 75)
print("02. SENSOR VALUE CORRECTION & NORMALIZATION")
print("=" * 75)

print()
print("LEFT C01")
print()
print("MUX EN : GPIO27")
print("S0     : GPIO22")
print("S1     : GPIO23")
print("S2     : GPIO24")
print("S3     : GPIO25")
print()
print("MUX CHANNEL : C01")
print("ADS1115     : A1")
print()

print("실험 순서")
print()
print("1. 무하중 5초 측정")
print("2. 2 kg 추를 C01 위치에 올리고 5초 측정")
print("3. 추 제거")
print("4. 무하중 → Press → Hold → Release")
print()
print("보정:")
print("  Zero Correction")
print("  Sensitivity Correction")
print("  0~100% Normalization")
print()

input(
    "준비가 되었으면 ENTER를 누르세요."
)


# ============================================================
# 센서 안정화
# ============================================================

print()
print("센서 안정화 중...")
time.sleep(2)


# ============================================================
# STEP 1
# Baseline
# ============================================================

print()
print("=" * 75)
print("STEP 1 / 4")
print("=" * 75)

print()
print("⚠️ C01에 아무것도 올리지 마세요.")
print()

input(
    "무하중 상태가 되면 ENTER를 누르세요."
)

baseline_raw, baseline_filtered, baseline = (
    measure_calibration(
        "BASELINE",
        ">>> 무하중 측정 중...",
        BASELINE_SECONDS
    )
)


# ============================================================
# STEP 2
# 2 kg Reference
# ============================================================

print()
print("=" * 75)
print("STEP 2 / 4")
print("=" * 75)

print()
print("⚠️ C01 위치에 2 kg 추를 올려주세요.")
print()

input(
    "2 kg 추가 안정적으로 올라갔으면 ENTER를 누르세요."
)

reference_raw, reference_filtered, reference_2kg = (
    measure_calibration(
        "2KG",
        ">>> 2 kg 기준값 측정 중...",
        REFERENCE_SECONDS
    )
)


# ============================================================
# Calibration 계수
# ============================================================

sensitivity_range = (
    reference_2kg - baseline
)

if sensitivity_range <= 0:

    raise RuntimeError(
        "\n2 kg 기준값이 baseline보다 크지 않습니다.\n"
        f"Baseline : {baseline:.1f}\n"
        f"2 kg     : {reference_2kg:.1f}\n"
        "센서 또는 하중 전달 구조를 확인하세요."
    )


# ============================================================
# STEP 3
# 추 제거
# ============================================================

print()
print("=" * 75)
print("STEP 3 / 4")
print("=" * 75)

print()
print("2 kg 추를 제거해주세요.")
print()

input(
    "추를 제거했으면 ENTER를 누르세요."
)

time.sleep(2)


# ============================================================
# STEP 4
# Controlled Test
# ============================================================

print()
print("=" * 75)
print("STEP 4 / 4")
print("=" * 75)

print()
print("이제 실제 하중 변화 측정을 시작합니다.")
print()
print("순서:")
print("  No Load → Press → Hold → Release")
print()

input(
    "ENTER를 누르면 바로 시작합니다."
)


# ------------------------------------------------------------
# No Load
# ------------------------------------------------------------

no_load = measure_phase(
    "NO_LOAD",
    "[1/4] NO LOAD",
    PHASE_SECONDS
)


# ------------------------------------------------------------
# Press
# ------------------------------------------------------------

press = measure_phase(
    "PRESS",
    "[2/4] PRESS - C01을 눌러주세요!",
    PHASE_SECONDS
)


# ------------------------------------------------------------
# Hold
# ------------------------------------------------------------

hold = measure_phase(
    "HOLD",
    "[3/4] HOLD - 계속 누르고 유지하세요.",
    PHASE_SECONDS
)


# ------------------------------------------------------------
# Release
# ------------------------------------------------------------

release = measure_phase(
    "RELEASE",
    "[4/4] RELEASE - 손을 떼세요!",
    PHASE_SECONDS
)


# ============================================================
# 데이터 합치기
# ============================================================

filtered_values = (
    no_load
    + press
    + hold
    + release
)

phase_labels = (
    ["NO_LOAD"] * len(no_load)
    + ["PRESS"] * len(press)
    + ["HOLD"] * len(hold)
    + ["RELEASE"] * len(release)
)


# ============================================================
# 보정
# ============================================================

zero_corrected = []

normalized = []


for value in filtered_values:

    # --------------------------------------------------------
    # ① 영점 보정
    # --------------------------------------------------------

    zero_value = (
        value - baseline
    )

    # 음수 방지
    zero_value = max(
        0.0,
        zero_value
    )

    zero_corrected.append(
        zero_value
    )


    # --------------------------------------------------------
    # ② 감도 보정 + 정규화
    #
    # baseline = 0%
    # 2kg reference = 100%
    # --------------------------------------------------------

    normalized_value = (
        zero_value
        / sensitivity_range
        * 100.0
    )

    # 0~100% 제한
    normalized_value = max(
        0.0,
        min(
            100.0,
            normalized_value
        )
    )

    normalized.append(
        normalized_value
    )


# ============================================================
# 저장 폴더
# ============================================================

timestamp = datetime.now().strftime(
    "%Y%m%d_%H%M%S"
)

save_dir = os.path.join(
    "pressure_calibration",
    "sensor_correction_data",
    timestamp
)

os.makedirs(
    save_dir,
    exist_ok=True
)


# ============================================================
# Calibration 정보 저장
# ============================================================

calibration_path = os.path.join(
    save_dir,
    "calibration_summary.csv"
)

with open(
    calibration_path,
    "w",
    newline="",
    encoding="utf-8"
) as f:

    writer = csv.writer(f)

    writer.writerow([
        "parameter",
        "value"
    ])

    writer.writerow([
        "foot",
        "LEFT"
    ])

    writer.writerow([
        "mux_channel",
        "C01"
    ])

    writer.writerow([
        "ads_channel",
        "A1"
    ])

    writer.writerow([
        "baseline",
        baseline
    ])

    writer.writerow([
        "reference_2kg",
        reference_2kg
    ])

    writer.writerow([
        "sensitivity_range",
        sensitivity_range
    ])

    writer.writerow([
        "median_window",
        MEDIAN_WINDOW
    ])


# ============================================================
# 측정 데이터 CSV
# ============================================================

data_path = os.path.join(
    save_dir,
    "left_C01_correction.csv"
)

with open(
    data_path,
    "w",
    newline="",
    encoding="utf-8"
) as f:

    writer = csv.writer(f)

    writer.writerow([
        "sample",
        "filtered",
        "zero_corrected",
        "normalized_percent",
        "phase",
    ])

    for i in range(
        len(filtered_values)
    ):

        writer.writerow([
            i,
            filtered_values[i],
            zero_corrected[i],
            normalized[i],
            phase_labels[i],
        ])


# ============================================================
# 그래프
# ============================================================

x = list(
    range(len(filtered_values))
)


plt.figure(
    figsize=(9, 9)
)


# ------------------------------------------------------------
# Filtered
# ------------------------------------------------------------

plt.plot(
    x,
    filtered_values,
    label="Filtered",
    linewidth=2.2,
)


# ------------------------------------------------------------
# Zero Corrected
# ------------------------------------------------------------

plt.plot(
    x,
    zero_corrected,
    label="Zero Corrected",
    linewidth=2.2,
)


# ------------------------------------------------------------
# Normalized
# ------------------------------------------------------------

# 오른쪽 Y축
ax1 = plt.gca()

ax2 = ax1.twinx()

ax2.plot(
    x,
    normalized,
    label="Normalized",
    linewidth=3.0,
    linestyle="--",
)


# ------------------------------------------------------------
# Phase 경계
# ------------------------------------------------------------

previous = phase_labels[0]

for i, phase in enumerate(phase_labels):

    if phase != previous:

        ax1.axvline(
            i,
            linestyle="--",
            alpha=0.35,
            linewidth=1,
        )

        previous = phase


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
    filtered_values
)

label_y = ymax * 0.94


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

        ax1.text(
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
    "LEFT C01 - Sensor Value Correction",
    fontsize=20,
    fontweight="bold",
    pad=18,
)


# ------------------------------------------------------------
# 축
# ------------------------------------------------------------

ax1.set_xlabel(
    "Sample",
    fontsize=15,
)

ax1.set_ylabel(
    "ADC Value",
    fontsize=15,
)

ax2.set_ylabel(
    "Normalized Load (%)",
    fontsize=15,
)

ax1.tick_params(
    axis="both",
    labelsize=12,
)

ax2.tick_params(
    axis="y",
    labelsize=12,
)


# ------------------------------------------------------------
# 정규화 범위
# ------------------------------------------------------------

ax2.set_ylim(
    0,
    110
)


# ------------------------------------------------------------
# 범례 합치기
# ------------------------------------------------------------

lines1, labels1 = ax1.get_legend_handles_labels()
lines2, labels2 = ax2.get_legend_handles_labels()

ax1.legend(
    lines1 + lines2,
    labels1 + labels2,
    fontsize=11,
    loc="upper right",
)


# ------------------------------------------------------------
# Grid
# ------------------------------------------------------------

ax1.grid(
    alpha=0.25,
    linewidth=0.8,
)


plt.tight_layout()


# ============================================================
# PNG
# ============================================================

graph_path = os.path.join(
    save_dir,
    "left_C01_correction.png"
)

plt.savefig(
    graph_path,
    dpi=300,
    bbox_inches="tight",
)

plt.close()


# ============================================================
# 결과 출력
# ============================================================

print()
print("=" * 75)
print("CALIBRATION RESULT")
print("=" * 75)

print()
print(
    f"Baseline        : "
    f"{baseline:.1f}"
)

print(
    f"2 kg Reference  : "
    f"{reference_2kg:.1f}"
)

print(
    f"Sensitivity Range : "
    f"{sensitivity_range:.1f}"
)

print()
print("Normalization:")
print("  Baseline → 0%")
print("  2 kg     → 100%")

print()
print("Saved:")
print(
    calibration_path
)

print(
    data_path
)

print(
    graph_path
)

print()
print("=" * 75)
print("측정 및 보정 완료")
print("=" * 75)


# ============================================================
# GPIO 정리
# ============================================================

MUX_EN.value = True

for pin in (
    MUX_EN,
    MUX_S0,
    MUX_S1,
    MUX_S2,
    MUX_S3,
):
    pin.deinit()
