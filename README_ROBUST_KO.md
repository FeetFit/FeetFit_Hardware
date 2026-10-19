# FeetFit: 10회 반복 중앙값 기반 보정 후보 등록

이 패치는 **사용자가 업로드한 기존 FeetFit 보정 패치 버전**의 스크립트를 기준으로 작성했습니다. `.env`, 하드웨어 `pressure.py`, FastAPI API, AI payload는 **수정하지 않습니다**.

## 설치 (Raspberry Pi 프로젝트 폴더)

```bash
cd ~/feetfit-api
cp pressure_calibration/calibrate_24_sensors.py pressure_calibration/calibrate_24_sensors.py.before_robust
unzip -o feetfit_robust_calibration_update.zip
source .venv/bin/activate
python -m unittest discover -s tests -v
```

## 이미 측정한 RIGHT C01 10회를 재측정하지 않고 등록

현재 `feetfit-api.service`를 중지할 필요가 없습니다. 아래는 JSON만 읽고 쓰며 GPIO/I2C를 건드리지 않습니다.

```bash
cd ~/feetfit-api
python -m pressure_calibration.review_existing_calibration \
  --profile pressure_calibration/sensor_correction_data/20261019_015640/sensor_calibration.json

python -m pressure_calibration.candidate_registry \
  --profile pressure_calibration/sensor_correction_data/20261019_015640/sensor_calibration_reviewed.json
```

기대 출력:
```
right_C01: 0kg=15.1 1kg=3670.0 (10/10) 2kg=6503.0 (9/10) => CANDIDATE
Registered: right_C01
Candidate registry: .../calibration_candidates.json (1/24 sensor candidates)
Production calibration / .env: unchanged
```

- 측정된 RIGHT C01 기준점: baseline 15.1, 1kg 3670.0, 2kg 6503.0 ADC.
- 무하중 제외 신호: 1kg 3654.9, 2kg 6487.9 ADC.
- 10개 배치값 중 중앙값(영점 제거 후) ±20% 안에 최소 9개가 들어오고 증가 관계가 단조롭다면 **실험 내 보정 후보**로 저장합니다.
- `calibration_candidates.json`에 기존 후보를 누적하므로 C01을 다시 측정할 필요는 없습니다. 이미 있는 센서 후보를 다른 데이터로 덮어쓰려면 `--replace`를 명시해야 합니다.
- `sensor_calibration.json` **원본은 수정하지 않습니다**. `sensor_calibration_reviewed.json`을 별도로 만듭니다.

## 다음 센서에서 10회 측정하고 후보 누적

**새로운 실제 측정 전에는** FastAPI 중지 필요:

```bash
sudo systemctl stop feetfit-api.service
python -m pressure_calibration.calibrate_24_sensors --foot right --channels 2 --repeats 10 --skip-mapping-check
sudo systemctl start feetfit-api.service
```

새로운 타임스탬프 폴더가 나오면 해당 `sensor_calibration.json`을 위 `review_existing_calibration`에 넣고, 결과를 `candidate_registry`에 넘기면 누적됩니다. 신호는 실리콘 접촉 조건에 의존하므로 한 실험 안에서 ±20% 통과는 **절대 하중 정확도, 측정 간 재현성의 입증이 아닙니다**.

## 주의

이 패치의 후보 등록은 **실제 측정값 변경 기능이 아닙니다**. `FSR_CALIBRATION_MODE=legacy`를 유지하세요. 24개 센서의 기준점과 센서 간 공통 스케일 및 측정 간 재현성을 확인하기 전 RIGHT C01만 센서 감도 보정해 AI로 보내면 다른 23개와 단위가 달라져 좌우 균형을 왜곡할 수 있습니다. 기존 `full`의 검증 차단을 유지합니다.

원래 `--tolerance .25` 기반 최댓값·최솟값 편차는 계속 **진단 정보**로 출력하되, 10회 데이터를 활용한 `CANDIDATE` 판정은 중앙값 기반으로 별도 저장됩니다.
