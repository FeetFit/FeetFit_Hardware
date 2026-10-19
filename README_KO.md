# FeetFit RIGHT C02 수동 후보 등록 (실제 감도 보정 적용 아님)

이 패치는 `pressure_calibration/candidate_registry.py`만 교체합니다. `--manual-include` 옵션으로 반복성 기준을 미통과한 센서도 **보정 데이터 후보 목록**에 저장하며, 그 미통과 결과(`quality_review`)와 사유를 그대로 기록합니다.

- 기존 등록된 C00/C01은 보존됩니다.
- 측정 스크립트의 0kg → 1kg → 2kg 10회 수집 방식은 그대로입니다.
- **실제 FastAPI의 하중값/AI API/`.env`는 바꾸지 않습니다.** 기존 `FSR_CALIBRATION_MODE=legacy`를 유지하세요.
- 수동 등록은 `validated=True`로 바꾸지 않습니다. 따라서 기존 `full` 모드는 여전히 24개 미검증 상태에서 실행 차단됩니다.

## 설치 (Raspberry Pi)

```bash
cd ~/feetfit-api
cp pressure_calibration/candidate_registry.py pressure_calibration/candidate_registry.py.before_manual_override
unzip -o feetfit_manual_candidate_override.zip
```

## RIGHT C02: 최신 10회 측정값으로 수동 등록

FastAPI를 끌 필요 없습니다. 다음 두 명령은 저장된 JSON만 다룹니다.

```bash
python -m pressure_calibration.review_existing_calibration \
  --profile pressure_calibration/sensor_correction_data/20261019_032014/sensor_calibration.json

python -m pressure_calibration.candidate_registry \
  --profile pressure_calibration/sensor_correction_data/20261019_032014/sensor_calibration_reviewed.json \
  --manual-include right_C02 \
  --reason "user_selected_provisional_0_1_2kg"
```

출력에 `manual_override_unvalidated`가 뜨는 것이 정상입니다. C02는 `0kg=16.85`, `1kg=2500.3`, `2kg=6029.6` ADC의 기준점과 재현성 미통과(1kg 5/10, 2kg 9/10)를 함께 기록합니다.

## 다음 센서들

기존 명령 사용:

```bash
sudo systemctl stop feetfit-api.service
python -m pressure_calibration.calibrate_24_sensors --foot right --channels 3 --repeats 10 --skip-mapping-check
sudo systemctl start feetfit-api.service
```

측정 후 review→registry 순서로 등록합니다. 후보 기준을 통과하면 `--manual-include`가 필요 없습니다. 미통과한 센서를 꼭 임시 후보로 등록하고 싶을 때만 `--manual-include FOOT_CNN --reason ...`을 추가하세요.

이 파일은 후보 저장만 담당합니다. 모든 센서의 0/1/2kg 기준점이 수집되면, 생산 서비스와 격리된 미리보기에서 **센서별 구간별(0→1kg, 1→2kg) 변환**을 먼저 검증하는 것이 다음 단계입니다.
