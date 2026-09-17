# START HERE

처음 저장소를 만든 뒤 다음 순서로 진행하세요.

## 1. GitHub에 새 저장소 생성

추천 이름:

`heat-treatment-anomaly-prediction`

## 2. 이 폴더 전체를 저장소에 업로드

## 3. 팀원 초대

`Settings → Collaborators`에서 팀원을 추가합니다.

## 4. 원본 데이터 배치

GitHub에는 원본 데이터가 기본적으로 올라가지 않도록 설정되어 있습니다.

로컬 PC의:

`data/raw/`

폴더에 원본 데이터를 넣습니다.

## 5. 분석 시작

`notebooks/01_data_understanding.ipynb`

부터 시작합니다.

## 6. 첫 Issue 예시

제목:

`[Data] 원본 데이터 구조 및 컬럼 확인`

완료 조건:

- shape
- 컬럼명
- dtype
- 결측
- 중복
- 시간 컬럼
- 이상/고장 관련 컬럼
- 샘플링 주기

## 7. 첫 브랜치 예시

```bash
git checkout -b feature/data-check
```

## 8. 첫 Commit 예시

```bash
git add .
git commit -m "data: 원본 데이터 구조 확인"
git push -u origin feature/data-check
```

## 9. PR 생성

작업 결과를 PR 템플릿에 맞춰 작성하고 팀원이 확인한 뒤 `main`에 병합합니다.

---

처음에는 GitHub 기능을 많이 쓰는 것보다 **분석 기록이 사라지지 않고, 팀원이 같은 흐름을 공유하는 것**을 우선합니다.
