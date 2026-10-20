# data/raw — 원시 데이터 넣는 곳

원본 데이터 파일은 **제출 폴더에 넣지 않습니다**(과제 가이드: 원본 데이터는 넣지 않고 내려받는 방법만 적음). 실행 전에 아래 파일을 이 폴더에 그대로 넣으세요. 이름을 바꾸거나 내용을 고치지 않습니다.

## 출처
- 데이터셋: **열처리 품질보증 AI 데이터셋** (원본 ZIP 이름 `Dataset_열처리 품질보증 AI 데이터셋.zip`, SHA256 `c86896260f68ed16a5f8b393042e23410663b76821cf2a81ea10e6235c49c1a8`)
- 내려받는 곳: **https://www.kamp-ai.kr/aidataDetail?DATASET_SEQ=60** (KAMP 인공지능 제조 플랫폼, 이용 목적 선택 후 내려받기)
- 출처 표기(KAMP 지정 형식): 중소벤처기업부, Korea AI Manufacturing Platform(KAMP), 열처리 품질보증 AI 데이터셋, 스마트제조혁신추진단(수행기관: ㈜임픽스), 2022.12.23., https://www.kamp-ai.kr/aidataDetail?DATASET_SEQ=60
- 프로젝트 저장소: https://github.com/vompos0179-prog/heat-treatment-anomaly-prediction (원본 데이터 파일은 저장소에 넣지 않음)
- ZIP을 풀면 아래 파일이 나옵니다.

## 넣을 파일

| 파일 | 내용 | 쓰는 단계 | SHA256(앞 16자리) |
|---|---|---|---|
| `data.csv` | 공정 원본 기록(cp949 인코딩), 2,939,722행 × 21열, 2022-01-03 ~ 2022-07-19 | 1~6단계 | `007ec19b7244f4a0` |
| `열처리_품질데이터.xlsx` | 작업(배정번호)별 품질 결과 136행 | 1~3·5·6단계 | `5adfa7d3c3fe32c1` |
| `train.csv` | 데이터셋에 들어 있는 학습용 표(작업별 요약) | 5단계 품질 예측 대조 | `7883d5f1e78dc798` |
| `품질전처리후데이터.csv` | 데이터셋에 들어 있는 품질 전처리 결과 | 5단계 품질 예측 대조 | `e6139f965d00dd26` |
| `데이터설명.txt` | 데이터셋 파일 설명 | 참고 | — |

넣은 뒤 PowerShell에서 `Get-FileHash data\raw\data.csv` 로 SHA256을 확인할 수 있습니다.
