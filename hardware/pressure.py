import time
import os
import statistics
from threading import Lock

from hardware.sensor_calibration import load_profile, correct_sensitivity, hardware_signature

import board
import busio
import RPi.GPIO as GPIO

from adafruit_ads1x15.ads1115 import ADS1115
from adafruit_ads1x15.analog_in import AnalogIn
from adafruit_ads1x15.ads1x15 import Pin

from config import (
    # Fixed input
    PRESSURE_FIXED_INPUT,
    PRESSURE_FIXED_SCAN_COUNT,

    # FSR / MUX GPIO
    FSR_MUX_S0_GPIO,
    FSR_MUX_S1_GPIO,
    FSR_MUX_S2_GPIO,
    FSR_MUX_S3_GPIO,

    FSR_LEFT_EN_GPIO,
    FSR_RIGHT_EN_GPIO,
    FSR_MUX_ENABLE_ACTIVE_LOW,

    # FSR channels
    FSR_SENSOR_COUNT,
    FSR_FIRST_CHANNEL,
    FSR_LAST_CHANNEL,

    # MUX timing
    FSR_MUX_SETTLE_SECONDS,

    # ADS1115
    ADS1115_I2C_ADDRESS,
    ADS1115_LEFT_CHANNEL,
    ADS1115_RIGHT_CHANNEL,
    ADS1115_GAIN,
    ADS1115_DATA_RATE,

    # Measurement
    FSR_MEASUREMENT_SECONDS,
    FSR_DISCARD_INITIAL_READS,
    FSR_DISCARD_INTERVAL_SECONDS,
    FSR_VALID_READS,
    FSR_SAMPLE_INTERVAL_SECONDS,
    FSR_MEDIAN_WINDOW,

    # FSR circuit
    FSR_FIXED_RESISTOR_OHMS,

    # FSR BASELINE
    FSR_LEFT_BASELINE,
    FSR_RIGHT_BASELINE,

    FSR_NOISE_FLOOR,
)

from errors import HardwareMeasurementError


# =========================================================
# GPIO / MUX
#
# 모든 값은
#
# .env
#   ↓
# config.py
#   ↓
# pressure.py
#
# 순서로 읽음
# =========================================================

S0 = FSR_MUX_S0_GPIO
S1 = FSR_MUX_S1_GPIO
S2 = FSR_MUX_S2_GPIO
S3 = FSR_MUX_S3_GPIO

EN_LEFT = FSR_LEFT_EN_GPIO
EN_RIGHT = FSR_RIGHT_EN_GPIO

SELECT_PINS = [
    S0,
    S1,
    S2,
    S3,
]


# =========================================================
# MUX Enable Logic
#
# CD74HC4067 기본:
#
# LOW  = Enable
# HIGH = Disable
#
# .env
#
# FSR_MUX_ENABLE_ACTIVE_LOW=true
# =========================================================

if FSR_MUX_ENABLE_ACTIVE_LOW:
    MUX_ENABLE_LEVEL = GPIO.LOW
    MUX_DISABLE_LEVEL = GPIO.HIGH
else:
    MUX_ENABLE_LEVEL = GPIO.HIGH
    MUX_DISABLE_LEVEL = GPIO.LOW


# =========================================================
# Channel Configuration
# =========================================================

CHANNEL_COUNT = FSR_SENSOR_COUNT

FIRST_CHANNEL = FSR_FIRST_CHANNEL
LAST_CHANNEL = FSR_LAST_CHANNEL

CHANNELS = list(
    range(
        FIRST_CHANNEL,
        LAST_CHANNEL + 1,
    )
)


if len(CHANNELS) != CHANNEL_COUNT:
    raise ValueError(
        "FSR 채널 설정이 올바르지 않습니다. "
        f"FSR_SENSOR_COUNT={CHANNEL_COUNT}, "
        f"FSR_FIRST_CHANNEL={FIRST_CHANNEL}, "
        f"FSR_LAST_CHANNEL={LAST_CHANNEL}"
    )

LEFT_BASELINE = FSR_LEFT_BASELINE
RIGHT_BASELINE = FSR_RIGHT_BASELINE

if len(LEFT_BASELINE) != CHANNEL_COUNT:
    raise ValueError(
        "LEFT_BASELINE 길이와 "
        "FSR_SENSOR_COUNT가 다릅니다."
    )


if len(RIGHT_BASELINE) != CHANNEL_COUNT:
    raise ValueError(
        "RIGHT_BASELINE 길이와 "
        "FSR_SENSOR_COUNT가 다릅니다."
    )


# =========================================================
# Fixed Pressure Input
#
# 테스트용
#
# PRESSURE_FIXED_INPUT=false이면
# 실제 센서를 사용하므로 아래 값은 사용하지 않음
# =========================================================

FIXED_LEFT_CORRECTED = [
    51.8,
    20.8,
    58.8,
    56.0,
    50.2,
    11099.0,
    629.3,
    45.2,
    43.8,
    587.7,
    8840.7,
    12134.9,
]

FIXED_RIGHT_CORRECTED = [
    9939.8,
    7652.4,
    814.9,
    27.5,
    0.0,
    1684.3,
    8571.8,
    10.2,
    3379.6,
    4.9,
    4.4,
    0.0,
]


# =========================================================
# Measurement Configuration
#
# 전부 config.py에서 가져옴
# =========================================================

MEASUREMENT_SECONDS = (
    FSR_MEASUREMENT_SECONDS
)

MUX_SETTLE_TIME = (
    FSR_MUX_SETTLE_SECONDS
)

DISCARD_READS = (
    FSR_DISCARD_INITIAL_READS
)

DISCARD_INTERVAL = (
    FSR_DISCARD_INTERVAL_SECONDS
)

VALID_READS = (
    FSR_VALID_READS
)

SAMPLE_INTERVAL = (
    FSR_SAMPLE_INTERVAL_SECONDS
)

MEDIAN_WINDOW = FSR_MEDIAN_WINDOW
if MEDIAN_WINDOW < 1 or MEDIAN_WINDOW % 2 == 0:
    raise ValueError("FSR_MEDIAN_WINDOW must be an odd integer >= 1")



# =========================================================
# Validation
# =========================================================

if MEASUREMENT_SECONDS <= 0:
    raise ValueError(
        "FSR_MEASUREMENT_SECONDS는 "
        "0보다 커야 합니다."
    )


if DISCARD_READS < 0:
    raise ValueError(
        "FSR_DISCARD_INITIAL_READS는 "
        "0 이상이어야 합니다."
    )


if VALID_READS <= 0:
    raise ValueError(
        "FSR_VALID_READS는 "
        "1 이상이어야 합니다."
    )


if MUX_SETTLE_TIME < 0:
    raise ValueError(
        "FSR_MUX_SETTLE_SECONDS는 "
        "0 이상이어야 합니다."
    )


# =========================================================
# Pressure Lock
#
# 동시에 두 번 압력 측정이 실행되지 않도록 함
# =========================================================

pressure_lock = Lock()


# =========================================================
# GPIO Setup
# =========================================================

GPIO.setwarnings(False)
GPIO.setmode(GPIO.BCM)


for pin in SELECT_PINS:

    GPIO.setup(
        pin,
        GPIO.OUT,
        initial=GPIO.LOW,
    )


GPIO.setup(
    EN_LEFT,
    GPIO.OUT,
    initial=MUX_DISABLE_LEVEL,
)


GPIO.setup(
    EN_RIGHT,
    GPIO.OUT,
    initial=MUX_DISABLE_LEVEL,
)


# =========================================================
# ADS1115 Setup
#
# .env 예:
#
# ADS1115_I2C_ADDRESS=0x48
# ADS1115_LEFT_CHANNEL=0
# ADS1115_RIGHT_CHANNEL=1
#
# 실제 테스트 결과:
#
# LEFT  -> A0
# RIGHT -> A1
# =========================================================

ADS_PIN_MAP = {
    0: Pin.A0,
    1: Pin.A1,
    2: Pin.A2,
    3: Pin.A3,
}


if ADS1115_LEFT_CHANNEL not in ADS_PIN_MAP:
    raise ValueError(
        "ADS1115_LEFT_CHANNEL은 "
        "0~3 사이여야 합니다."
    )


if ADS1115_RIGHT_CHANNEL not in ADS_PIN_MAP:
    raise ValueError(
        "ADS1115_RIGHT_CHANNEL은 "
        "0~3 사이여야 합니다."
    )


if (
    ADS1115_LEFT_CHANNEL
    == ADS1115_RIGHT_CHANNEL
):
    raise ValueError(
        "LEFT와 RIGHT ADS1115 채널이 "
        "같게 설정되어 있습니다."
    )


i2c = busio.I2C(
    board.SCL,
    board.SDA,
)


ads = ADS1115(
    i2c,
    address=ADS1115_I2C_ADDRESS,
)


ads.gain = ADS1115_GAIN
ads.data_rate = ADS1115_DATA_RATE


left_adc = AnalogIn(
    ads,
    ADS_PIN_MAP[
        ADS1115_LEFT_CHANNEL
    ],
)


right_adc = AnalogIn(
    ads,
    ADS_PIN_MAP[
        ADS1115_RIGHT_CHANNEL
    ],
)

# =========================================================
# Optional sensor calibration profile
# legacy   : original .env baseline, original AI ADC scale
# baseline : measured 24-channel baseline, original AI ADC scale
# full     : measured baseline + checked piecewise sensitivity correction
#            (changes AI input scale: test with AI service first)
# =========================================================
CALIBRATION_MODE = os.getenv("FSR_CALIBRATION_MODE", "legacy").strip().lower()
CALIBRATION_FILE = os.getenv("FSR_CALIBRATION_FILE", "").strip()
CALIBRATION_SIGNATURE = hardware_signature(
    left_en=EN_LEFT, right_en=EN_RIGHT,
    left_ads=ADS1115_LEFT_CHANNEL, right_ads=ADS1115_RIGHT_CHANNEL,
    gain=ADS1115_GAIN, data_rate=ADS1115_DATA_RATE,
    first_channel=FIRST_CHANNEL, last_channel=LAST_CHANNEL,
    channel_count=CHANNEL_COUNT, median_window=MEDIAN_WINDOW,
    valid_reads=VALID_READS,
    mux_select_pins=SELECT_PINS,
    active_low=FSR_MUX_ENABLE_ACTIVE_LOW,
    fixed_resistor_ohms=FSR_FIXED_RESISTOR_OHMS,
)
CALIBRATION_PROFILE = load_profile(
    CALIBRATION_FILE, CALIBRATION_MODE, CALIBRATION_SIGNATURE
)
if CALIBRATION_PROFILE is not None:
    LEFT_BASELINE = CALIBRATION_PROFILE["feet"]["left"]["baseline"]
    RIGHT_BASELINE = CALIBRATION_PROFILE["feet"]["right"]["baseline"]
    print(f"[PRESSURE CALIBRATION] mode={CALIBRATION_MODE} file={CALIBRATION_FILE}", flush=True)



# =========================================================
# MUX Disable
# =========================================================

def disable_muxes():

    GPIO.output(
        EN_LEFT,
        MUX_DISABLE_LEVEL,
    )

    GPIO.output(
        EN_RIGHT,
        MUX_DISABLE_LEVEL,
    )


# =========================================================
# MUX Channel Select
#
# CD74HC4067:
#
# S0 = LSB
#
# C0  = 0000
# C1  = 0001
# C2  = 0010
# ...
# C11 = 1011
# =========================================================

def select_channel(
    channel: int,
):

    if channel < 0 or channel > 15:

        raise ValueError(
            "MUX channel은 "
            "0~15 사이여야 합니다."
        )


    for bit, pin in enumerate(
        SELECT_PINS
    ):

        GPIO.output(
            pin,
            (channel >> bit) & 1,
        )


# =========================================================
# ADC Read
#
# 채널 선택
# ↓
# 초기 ADC 값 버림
# ↓
# VALID_READS만큼 실제 측정
# ↓
# 평균값 반환
# =========================================================

def read_adc(
    adc: AnalogIn,
) -> float:

    # -----------------------------------------------------
    # 초기값 버리기
    # -----------------------------------------------------

    for _ in range(
        DISCARD_READS
    ):

        _ = adc.value

        if DISCARD_INTERVAL > 0:

            time.sleep(
                DISCARD_INTERVAL
            )


    # -----------------------------------------------------
    # 실제 측정
    # -----------------------------------------------------

    values = []


    for _ in range(
        VALID_READS
    ):

        values.append(
            adc.value
        )

        if SAMPLE_INTERVAL > 0:

            time.sleep(
                SAMPLE_INTERVAL
            )


    if not values:

        raise ValueError(
            "ADC 측정값이 없습니다."
        )


    # Five-point temporal median filtering (offline-compatible centered window).
    # The original average is retained for MEDIAN_WINDOW=1.
    if MEDIAN_WINDOW == 1:
        filtered = values
    else:
        half = MEDIAN_WINDOW // 2
        filtered = [
            statistics.median(values[max(0, i-half):min(len(values), i+half+1)])
            for i in range(len(values))
        ]
    return float(statistics.mean(filtered))


# =========================================================
# Read One Foot
#
# 한쪽 MUX만 활성화한 상태에서
# C0 ~ C11 순차 측정
# =========================================================

def read_foot(
    enable_pin: int,
    other_enable_pin: int,
    adc: AnalogIn,
) -> list:

    values = []


    for channel in CHANNELS:

        # -------------------------------------------------
        # 1. 두 MUX 모두 OFF
        # -------------------------------------------------

        disable_muxes()


        # -------------------------------------------------
        # 2. 읽을 MUX 채널 선택
        # -------------------------------------------------

        select_channel(
            channel
        )


        # -------------------------------------------------
        # 3. 반대쪽 MUX OFF
        # -------------------------------------------------

        GPIO.output(
            other_enable_pin,
            MUX_DISABLE_LEVEL,
        )


        # -------------------------------------------------
        # 4. 측정할 MUX ON
        # -------------------------------------------------

        GPIO.output(
            enable_pin,
            MUX_ENABLE_LEVEL,
        )


        # -------------------------------------------------
        # 5. MUX 안정화
        # -------------------------------------------------

        if MUX_SETTLE_TIME > 0:

            time.sleep(
                MUX_SETTLE_TIME
            )


        try:

            value = read_adc(
                adc
            )


        finally:

            # 측정 후 해당 MUX OFF

            GPIO.output(
                enable_pin,
                MUX_DISABLE_LEVEL,
            )


        values.append(
            value
        )


    return values


# =========================================================
# Read Both Feet
#
# 실제 현재 배선은 .env 기준
#
# LEFT
#   EN  -> GPIO17
#   SIG -> ADS1115 A0
#
# RIGHT
#   EN  -> GPIO27
#   SIG -> ADS1115 A1
#
# 단, 실제 값은 하드코딩하지 않고
# config.py에서 가져옴
# =========================================================

def read_both_feet():

    left_values = read_foot(
        enable_pin=EN_LEFT,
        other_enable_pin=EN_RIGHT,
        adc=left_adc,
    )


    right_values = read_foot(
        enable_pin=EN_RIGHT,
        other_enable_pin=EN_LEFT,
        adc=right_adc,
    )


    return (
        left_values,
        right_values,
    )


# =========================================================
# Baseline Correction
#
# corrected = raw - baseline
#
# 음수는 0으로 처리
# =========================================================

def apply_baseline(
    raw_values: list,
    baseline: list,
) -> list:

    if len(raw_values) != CHANNEL_COUNT:
        raise ValueError(
            "RAW ??? ??? "
            "FSR_SENSOR_COUNT? ????."
        )

    if len(baseline) != CHANNEL_COUNT:
        raise ValueError(
            "Baseline ??? "
            "FSR_SENSOR_COUNT? ????."
        )

    corrected = []

    for index in range(
        CHANNEL_COUNT
    ):

        value = (
            raw_values[index]
            - baseline[index]
        )

        # ?? ??
        if value < 0:
            value = 0.0

        # ??? ADC ??? ??
        if value < FSR_NOISE_FLOOR:
            value = 0.0

        corrected.append(
            value
        )

    return corrected



# =========================================================
# Relative Pressure
#
# 각 발에서 가장 높은 값을 100으로 환산
#
# 디버깅 / 앱 확인용
#
# AI에는 Relative가 아니라
# baseline 보정된 corrected 값을 전달
# =========================================================

def calculate_relative(
    corrected_values: list,
) -> list:

    if not corrected_values:

        return []


    max_value = max(
        corrected_values
    )


    if max_value <= 0:

        return [
            0.0
        ] * CHANNEL_COUNT


    return [

        value
        / max_value
        * 100.0

        for value
        in corrected_values
    ]


# =========================================================
# Fixed Input
#
# 기존 테스트 모드 지원
# =========================================================

def _read_fixed_pressure():

    if PRESSURE_FIXED_SCAN_COUNT <= 0:

        raise ValueError(
            "PRESSURE_FIXED_SCAN_COUNT는 "
            "1 이상이어야 합니다."
        )


    # 기존 9회 테스트 모드에서
    # 전체 평균이 1.0이 되도록 구성
    default_factors = [
        0.96,
        0.97,
        0.98,
        0.99,
        1.00,
        1.01,
        1.02,
        1.03,
        1.04,
    ]


    left_sums = [
        0.0
    ] * CHANNEL_COUNT


    right_sums = [
        0.0
    ] * CHANNEL_COUNT


    scan_count = 0

    start_time = time.monotonic()

    scan_interval = (
        MEASUREMENT_SECONDS
        / PRESSURE_FIXED_SCAN_COUNT
    )


    for scan_index in range(
        PRESSURE_FIXED_SCAN_COUNT
    ):

        if (
            PRESSURE_FIXED_SCAN_COUNT
            == len(default_factors)
        ):

            factor = (
                default_factors[
                    scan_index
                ]
            )

        else:

            factor = 1.0


        left_corrected_scan = [

            value * factor

            for value
            in FIXED_LEFT_CORRECTED
        ]


        right_corrected_scan = [

            value * factor

            for value
            in FIXED_RIGHT_CORRECTED
        ]


        # 기존 실제 센서 처리와 동일하게
        # RAW -> baseline correction 경로를 거치기 위해
        # baseline을 다시 더함

        left_raw_scan = [

            LEFT_BASELINE[index]
            + left_corrected_scan[index]

            for index in range(
                CHANNEL_COUNT
            )
        ]


        right_raw_scan = [

            RIGHT_BASELINE[index]
            + right_corrected_scan[index]

            for index in range(
                CHANNEL_COUNT
            )
        ]


        for index in range(
            CHANNEL_COUNT
        ):

            left_sums[index] += (
                left_raw_scan[index]
            )

            right_sums[index] += (
                right_raw_scan[index]
            )


        scan_count += 1


        print(
            f"[PRESSURE] "
            f"Scan {scan_count:02d} | "
            f"L Max {max(left_raw_scan):8.1f} | "
            f"R Max {max(right_raw_scan):8.1f}"
        )


        target_time = (
            start_time
            + scan_count
            * scan_interval
        )


        remaining = (
            target_time
            - time.monotonic()
        )


        if remaining > 0:

            time.sleep(
                remaining
            )


    return (
        left_sums,
        right_sums,
        scan_count,
    )


# =========================================================
# Pressure Measurement
#
# 실제 센서 모드:
#
# 10초 반복 측정
# ↓
# 좌우 C0~C11 Scan
# ↓
# RAW 평균
# ↓
# Baseline 제거
# ↓
# Relative 계산
# ↓
# corrected 값 반환
#
#
# 반환 형식:
#
# {
#     "left":  [...],
#     "right": [...]
# }
#
# AI에는 corrected 값을 전달
# =========================================================

def measure_pressure() -> dict:

    try:

        with pressure_lock:

            print()
            print(
                "=" * 72
            )

            print(
                "[PRESSURE] 측정 시작"
            )

            print(
                f"[PRESSURE] 측정 시간: "
                f"{MEASUREMENT_SECONDS:.0f}초"
            )

            print(
                "[PRESSURE] Input Mode = "
                + (
                    "FIXED"
                    if PRESSURE_FIXED_INPUT
                    else "SENSOR"
                )
            )


            if not PRESSURE_FIXED_INPUT:

                print(
                    f"[PRESSURE] USER LEFT  = "
                    f"GPIO{EN_LEFT} / "
                    f"ADS1115 A{ADS1115_LEFT_CHANNEL}"
                )

                print(
                    f"[PRESSURE] USER RIGHT = "
                    f"GPIO{EN_RIGHT} / "
                    f"ADS1115 A{ADS1115_RIGHT_CHANNEL}"
                )

                print(
                    f"[PRESSURE] ADS1115 = "
                    f"{hex(ADS1115_I2C_ADDRESS)}"
                )

                print(
                    f"[PRESSURE] ADS Gain = "
                    f"{ADS1115_GAIN}"
                )

                print(
                    f"[PRESSURE] ADS Data Rate = "
                    f"{ADS1115_DATA_RATE}"
                )


            print(
                "=" * 72
            )


            # =================================================
            # FIXED MODE
            # =================================================

            if PRESSURE_FIXED_INPUT:

                (
                    left_sums,
                    right_sums,
                    scan_count,
                ) = _read_fixed_pressure()


            # =================================================
            # REAL SENSOR MODE
            # =================================================

            else:

                left_sums = [
                    0.0
                ] * CHANNEL_COUNT


                right_sums = [
                    0.0
                ] * CHANNEL_COUNT


                scan_count = 0


                start_time = (
                    time.monotonic()
                )


                while (
                    time.monotonic()
                    - start_time
                    < MEASUREMENT_SECONDS
                ):

                    (
                        left_values,
                        right_values,
                    ) = read_both_feet()


                    if (
                        len(left_values)
                        != CHANNEL_COUNT
                    ):

                        raise ValueError(
                            "LEFT 측정 채널 수가 "
                            "올바르지 않습니다."
                        )


                    if (
                        len(right_values)
                        != CHANNEL_COUNT
                    ):

                        raise ValueError(
                            "RIGHT 측정 채널 수가 "
                            "올바르지 않습니다."
                        )


                    # -----------------------------------------
                    # RAW 누적
                    # -----------------------------------------

                    for index in range(
                        CHANNEL_COUNT
                    ):

                        left_sums[index] += (
                            left_values[index]
                        )

                        right_sums[index] += (
                            right_values[index]
                        )


                    scan_count += 1


                    print(
                        f"[PRESSURE] "
                        f"Scan {scan_count:02d} | "
                        f"L Max "
                        f"{max(left_values):8.1f} | "
                        f"R Max "
                        f"{max(right_values):8.1f}"
                    )


            # =================================================
            # Validation
            # =================================================

            if scan_count <= 0:

                raise ValueError(
                    "압력 센서 측정값이 없습니다."
                )


            # =================================================
            # RAW Average
            # =================================================

            left_raw_average = [

                value / scan_count

                for value
                in left_sums
            ]


            right_raw_average = [

                value / scan_count

                for value
                in right_sums
            ]


            # =================================================
            # Baseline Correction
            # =================================================

            left_corrected = (
                apply_baseline(
                    left_raw_average,
                    LEFT_BASELINE,
                )
            )


            right_corrected = (
                apply_baseline(
                    right_raw_average,
                    RIGHT_BASELINE,
                )
            )


            # =================================================
            # Sensitivity correction, AFTER baseline, BEFORE relative conversion.
            # Full mode intentionally changes the payload numbers sent to AI.
            # =================================================
            if CALIBRATION_MODE == "full" and not PRESSURE_FIXED_INPUT:
                left_corrected = correct_sensitivity(
                    left_corrected, "left", CALIBRATION_PROFILE
                )
                right_corrected = correct_sensitivity(
                    right_corrected, "right", CALIBRATION_PROFILE
                )

            # =================================================
            # Relative Pressure
            # =================================================

            left_relative = (
                calculate_relative(
                    left_corrected
                )
            )


            right_relative = (
                calculate_relative(
                    right_corrected
                )
            )


            # =================================================
            # Round
            # =================================================

            left_raw_average = [

                round(
                    value,
                    1,
                )

                for value
                in left_raw_average
            ]


            right_raw_average = [

                round(
                    value,
                    1,
                )

                for value
                in right_raw_average
            ]


            left_corrected = [

                round(
                    value,
                    1,
                )

                for value
                in left_corrected
            ]


            right_corrected = [

                round(
                    value,
                    1,
                )

                for value
                in right_corrected
            ]


            left_relative = [

                round(
                    value,
                    1,
                )

                for value
                in left_relative
            ]


            right_relative = [

                round(
                    value,
                    1,
                )

                for value
                in right_relative
            ]


            # =================================================
            # Result Log
            # =================================================

            print()
            print(
                "=" * 72
            )

            print(
                "[PRESSURE RESULT]"
            )

            print(
                "=" * 72
            )


            print(
                "LEFT RAW =",
                left_raw_average,
            )

            print(
                "LEFT CORRECTED =",
                left_corrected,
            )

            print(
                "LEFT RELATIVE =",
                left_relative,
            )


            print()


            print(
                "RIGHT RAW =",
                right_raw_average,
            )

            print(
                "RIGHT CORRECTED =",
                right_corrected,
            )

            print(
                "RIGHT RELATIVE =",
                right_relative,
            )


            print()


            print(
                f"[PRESSURE] "
                f"Total Scan Count = "
                f"{scan_count}"
            )


            print(
                "=" * 72
            )


            # =================================================
            # AI 전달값
            #
            # Relative가 아니라
            # Baseline 보정된 실제 ADC 값을 반환
            # =================================================

            return {
                "left": left_corrected,
                "right": right_corrected,
            }


    except HardwareMeasurementError:

        raise


    except Exception as e:

        raise HardwareMeasurementError(
            reason="PRESSURE_SENSOR_ERROR",
            message=(
                "압력 측정에 실패했습니다. "
                "다시 시도해주세요."
            ),
            detail=str(e),
        )


    finally:

        # FastAPI 서버가 다음 측정에서도 GPIO를
        # 계속 사용해야 하므로 GPIO.cleanup()은 하지 않음.
        #
        # 측정 종료 후 MUX만 안전하게 비활성화.

        try:

            disable_muxes()

        except Exception:

            pass
