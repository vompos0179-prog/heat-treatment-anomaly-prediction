"""이미 계산된 IF 결과를 저장한다. 모델 학습·점수·판정·구간 계산은 하지 않는다.

보완본2 원문의 계산 결과를 저장하는 도우미다. 사용안내.txt 참조.
production은 보완본2 원문 SHA256 전체 값과 300개 조건을 확인한다.
--self-test는 합성 배열의 저장/복원만 시험하며 실제 분석 결과를 만들지 않는다.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
import re
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd


SENSORS = {4: "솔트조 온도 1 Zone", 5: "솔트조 온도 2 Zone"}
BASE_HASH_PREFIX = "a83490a6"
BASE_SHA256 = "a83490a626cab47a8e9755daa09f956f07baae49d1694713e130099a673b529e"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "not-installed"


class IFRecordExporter:
    """원본 df와 같은 행 순서인 계산 결과를 받아 6~7월 기록만 저장한다.

    training_rows는 실제 fit에 사용한 행을 실제 사용 순서대로 전달한다.
    필수 열: source_row_position(정수, df.iloc의 위치), 배정번호, TAG_MIN.
    fit_idx가 라벨인 경우 위치로 변환해야 한다. 위치와 라벨을 혼동하지 않는다.
    """

    def __init__(self, output_dir, df, *, base_code_path, patched_code_path,
                 min_history_valid_count, test_mode=False,
                 batch_col="배정번호", time_col="TAG_MIN"):
        self.out = Path(output_dir).resolve()
        self.base = Path(base_code_path).resolve()
        self.patched = Path(patched_code_path).resolve()
        self.test_mode = bool(test_mode)
        self.base_hash = sha256(self.base)
        self.patched_hash = sha256(self.patched)
        if not self.test_mode and self.base_hash != BASE_SHA256:
            raise ValueError("보완본2 원문 해시가 a83490a6...와 다릅니다. 구버전으로 대신 실행하지 마세요.")
        if min_history_valid_count != 300:
            raise ValueError("저장 대상 코드의 최소 과거 기록 조건은 300개여야 합니다.")
        if self.base == self.patched and not self.test_mode:
            raise ValueError("수정 전 원문과 저장 기능을 연결한 실행 코드를 별도로 보존하세요.")
        if not isinstance(df.index, pd.RangeIndex) or not df.index.equals(pd.RangeIndex(len(df))):
            raise ValueError("df는 0부터 이어지는 행 인덱스를 유지해야 합니다. 저장 중 순서를 바꾸지 마세요.")
        if not len(df) or batch_col not in df or time_col not in df:
            raise ValueError("배정번호·TAG_MIN을 가진 실제 계산용 df가 필요합니다.")
        if not pd.api.types.is_datetime64_any_dtype(df[time_col].dtype):
            raise TypeError("TAG_MIN은 실제 계산에 사용한 datetime 열이어야 합니다.")
        if getattr(df[time_col].dt, "tz", None) is not None:
            raise ValueError("시간대 변환 없이 사용한 원본 시각을 전달하세요.")
        self.n = len(df)
        self.batch_col, self.time_col = batch_col, time_col
        self.batches = df[batch_col].astype(str).to_numpy(copy=True)
        if not all(re.fullmatch(r"[0-9]+", value) for value in self.batches):
            raise ValueError("배정번호는 숫자로만 된 식별자여야 합니다. 소수점 또는 경로 문자는 허용하지 않습니다.")
        self.times = df[time_col].to_numpy(dtype="datetime64[ns]", copy=True).astype("int64")
        if np.any(self.times == np.iinfo(np.int64).min):
            raise ValueError("기록 시각에 NaT가 있습니다.")
        self.jobs = {}
        self.first_times = {}
        for batch, positions in pd.Series(np.arange(self.n)).groupby(self.batches, sort=False):
            idx = positions.to_numpy(dtype="int64")
            if np.any(np.diff(self.times[idx]) <= 0):
                raise ValueError(f"{batch}: 시각이 중복되거나 시간순이 아닙니다.")
            first = pd.Timestamp(self.times[idx[0]])
            self.first_times[str(batch)] = first
            if first.year == 2022 and first.month in (6, 7):
                self.jobs[str(batch)] = idx
        if not self.jobs or (not self.test_mode and len(self.jobs) != 36):
            raise ValueError(f"첫 기록 월 기준 2022년 6~7월 36개 작업을 확인하세요: {len(self.jobs)}개")
        self.selected = np.concatenate(list(self.jobs.values()))
        self.cache = {}
        self.info = {}
        self.files = {}
        self.finished = False
        self.out.mkdir(parents=True, exist_ok=True)
        if (self.out / "IF_저장정보.json").exists() or (self.out / "IF_기록별판정").exists():
            raise FileExistsError("기존 저장 결과가 있습니다. 새 실행 결과 폴더를 사용하세요.")

    def _array(self, value, name, *, boolean=False):
        array = np.asarray(value)
        if array.shape != (self.n,):
            raise ValueError(f"{name}: df와 같은 길이의 1차원 배열이 필요합니다: {array.shape}")
        if boolean and array.dtype != np.dtype(bool):
            raise TypeError(f"{name}: 계산된 bool 배열을 그대로 전달하세요.")
        return array.copy()

    def _remember(self, path):
        self.files[Path(path).relative_to(self.out).as_posix()] = sha256(path)

    def capture(self, sensor_index, *, model, valid, score, cand, qual,
                threshold, training_rows, input_feature_names, qual_available):
        """센서 반복문 안에서 최종 판정 직후 호출한다. 계산값을 바꾸지 않는다."""
        import joblib

        if self.finished or sensor_index not in SENSORS or sensor_index in self.cache:
            raise ValueError("센서 4·5를 각각 한 번만, finish 이전에 저장하세요.")
        if not self.test_mode and (type(model).__name__ != "IsolationForest" or
                                   not type(model).__module__.startswith("sklearn.")):
            raise TypeError("학습이 끝난 sklearn IsolationForest 모델이 필요합니다.")
        if getattr(model, "n_estimators", None) != 300 or getattr(model, "random_state", None) != 42:
            raise ValueError("모델 설정이 300개 나무·random_state=42와 다릅니다.")
        if len(getattr(model, "estimators_", [])) != 300 or getattr(model, "n_features_in_", None) != 4:
            raise ValueError("학습된 나무 300개·입력 특성 4개가 필요합니다.")
        names = list(input_feature_names)
        if len(names) != 4 or len(set(names)) != 4:
            raise ValueError("실제로 사용한 입력 특성 이름 네 개를 순서대로 전달하세요.")
        threshold = float(threshold)
        if not np.isfinite(threshold):
            raise ValueError("점수 기준값은 유한한 숫자여야 합니다.")
        arrays = {"valid": self._array(valid, "valid", boolean=True),
                  "score": self._array(score, "score"),
                  "cand": self._array(cand, "cand", boolean=True),
                  "qual": self._array(qual, "qual", boolean=True)}
        available = self._array(qual_available, "qual_available", boolean=True)
        if not available[self.selected].all():
            raise ValueError("저장할 6~7월 기록에 최종 구간 판정을 계산하지 않은 행이 있습니다.")
        if not np.issubdtype(arrays["score"].dtype, np.floating):
            raise TypeError("score는 실제 계산된 실수 배열이어야 합니다.")
        if not np.isfinite(arrays["score"][arrays["valid"]]).all():
            raise ValueError("판정 가능한 기록의 IF 점수에 빈칸·무한대가 있습니다.")
        if np.any(arrays["qual"] & ~arrays["cand"]) or np.any(arrays["cand"] & ~arrays["valid"]):
            raise ValueError("qual ⊆ cand ⊆ valid 조건을 위반했습니다.")
        expected = arrays["valid"] & (arrays["score"] >= threshold)
        # 후보를 다시 만드는 것이 아니라, 전달된 후보가 같은 점수 기준인지 확인한다.
        # 월별 mask로 잘라 만든 후보 대신 전체 valid/score 기준 후보를 전달해야 한다.
        if not np.array_equal(arrays["cand"], expected):
            raise ValueError("cand가 valid & (score >= threshold)와 다릅니다.")
        rows = training_rows.copy(deep=True)
        required = ["source_row_position", self.batch_col, self.time_col]
        if any(name not in rows for name in required):
            raise ValueError(f"학습행 목록에 다음 열이 필요합니다: {required}")
        if not len(rows) or (not self.test_mode and len(rows) != 200000):
            raise ValueError(f"실제 모델 학습에 사용한 센서별 200,000행을 전달하세요: {len(rows)}행")
        if not pd.api.types.is_integer_dtype(rows["source_row_position"].dtype):
            raise TypeError("source_row_position은 df.iloc 기준 정수 위치여야 합니다.")
        fit_pos = rows["source_row_position"].to_numpy(dtype="int64")
        if np.any(fit_pos < 0) or np.any(fit_pos >= self.n) or len(np.unique(fit_pos)) != len(fit_pos):
            raise ValueError("학습행의 원본 위치가 중복되거나 범위를 벗어났습니다.")
        fit_time = pd.to_datetime(rows[self.time_col]).to_numpy(dtype="datetime64[ns]").astype("int64")
        if not np.array_equal(fit_time, self.times[fit_pos]) or not np.array_equal(
                rows[self.batch_col].astype(str).to_numpy(), self.batches[fit_pos]):
            raise ValueError("학습행 목록의 배정번호·시각이 df의 실제 행 위치와 다릅니다.")
        first_month = {batch: self.first_times[batch] for batch in pd.unique(self.batches[fit_pos])}
        if any(value.year != 2022 or value.month not in (1, 2, 3, 4) for value in first_month.values()):
            raise ValueError("학습행에 첫 기록 월 기준 1~4월 이외의 작업이 포함되어 있습니다.")
        if not arrays["valid"][fit_pos].all():
            raise ValueError("학습행에 IF 판정 불가 기록이 포함되어 있습니다.")
        safe = SENSORS[sensor_index].replace(" ", "_")
        model_path = self.out / f"IF_모델_{safe}.joblib"
        train_path = self.out / f"IF_학습행_{safe}.csv.gz"
        if model_path.exists() or train_path.exists():
            raise FileExistsError("기존 모델 또는 학습행 파일을 덮어쓰지 않습니다.")
        joblib.dump(model, model_path, compress=3)
        rows.insert(0, "fit_order", np.arange(len(rows)))
        rows.insert(0, "sensor_index", sensor_index)
        rows.to_csv(train_path, index=False, encoding="utf-8-sig", compression="gzip")
        self._remember(model_path)
        self._remember(train_path)
        self.cache[sensor_index] = {name: value[self.selected].copy() for name, value in arrays.items()}
        self.info[str(sensor_index)] = {"sensor_name": SENSORS[sensor_index], "threshold": threshold,
            "input_feature_names": names, "fit_rows": len(rows), "n_estimators": 300, "random_state": 42,
            "exported_valid_count": int(arrays["valid"][self.selected].sum()),
            "exported_candidate_count": int(arrays["cand"][self.selected].sum()),
            "exported_qualified_count": int(arrays["qual"][self.selected].sum()),
            "score_dtype": str(arrays["score"].dtype)}

    def finish(self):
        """두 센서가 모두 저장된 뒤 작업별 NPZ와 실행 증거를 작성한다."""
        if self.finished or set(self.cache) != {4, 5}:
            raise ValueError("센서 4·5의 capture를 각각 완료한 다음 finish를 한 번 호출하세요.")
        if sha256(self.base) != self.base_hash or sha256(self.patched) != self.patched_hash:
            raise RuntimeError("저장 중 원본 코드 또는 실행 코드가 변경되었습니다.")
        target = self.out / "IF_기록별판정"
        target.mkdir(exist_ok=False)
        offset = 0
        for batch, idx in self.jobs.items():
            part = slice(offset, offset + len(idx))
            payload = {"TAG_MIN_ns": self.times[idx].copy()}
            for sensor_index in (4, 5):
                for name, value in self.cache[sensor_index].items():
                    payload[f"IF_{sensor_index}_{name}"] = value[part].copy()
            path = target / f"{batch}.npz"
            np.savez_compressed(path, **payload)
            with np.load(path, allow_pickle=False) as loaded:
                for key, expected in payload.items():
                    if not np.array_equal(loaded[key], expected, equal_nan=True):
                        raise RuntimeError(f"저장/복원 불일치: {batch}/{key}")
            self._remember(path)
            offset += len(idx)
        info = {"schema_version": 1, "test_mode": self.test_mode,
            "for_submission": not self.test_mode,
            "base_code_path": str(self.base), "base_code_sha256": self.base_hash,
            "patched_code_path": str(self.patched), "patched_code_sha256": self.patched_hash,
            "export_helper_path": str(Path(__file__).resolve()), "export_helper_sha256": sha256(Path(__file__)),
            "verified_base_hash_prefix": BASE_HASH_PREFIX if not self.test_mode else None,
            "min_history_valid_count": 300,
            "scope": "first observation month 2022-06 or 2022-07; full original records of each selected job",
            "exported_jobs": len(self.jobs), "exported_records": len(self.selected),
            "source_df_rows": self.n, "job_ids": list(self.jobs), "sensors": self.info,
            "array_note": "valid/score/cand/qual are provided by the executing stage4 code, not recalculated here",
            "host": platform.node(), "python": platform.python_version(),
            "versions": {key: _version(key) for key in ("numpy", "pandas", "scikit-learn", "joblib")},
            "files_sha256": self.files}
        metadata = self.out / "IF_저장정보.json"
        metadata.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
        # 기존 4단계 실행정보를 지우지 않고 저장 파일 검증정보만 덧붙인다.
        with (self.out / "실행정보.txt").open("a", encoding="utf-8") as stream:
            stream.write("\nIF 저장 정보 SHA256: " + sha256(metadata) + "\n")
            stream.write("IF 저장 파일별 SHA256: IF_저장정보.json의 files_sha256 참조\n")
            if self.test_mode:
                stream.write("합성 저장 시험 전용: 프로젝트 분석 결과·제출 결과가 아님\n")
        self.finished = True
        return metadata


class _SyntheticModel:
    """저장 시험용 객체. 실제 학습 모델이 아니다."""
    n_estimators = 300
    random_state = 42
    n_features_in_ = 4
    estimators_ = [None] * 300


def self_test():
    """모델을 학습하지 않고 합성 배열 저장/복원·오류 차단을 확인한다."""
    with tempfile.TemporaryDirectory(prefix="if_storage_test_") as directory:
        root = Path(directory)
        source = root / "synthetic.py"
        source.write_text("# synthetic storage test only\n", encoding="utf-8")
        timestamps = list(pd.date_range("2022-01-01", periods=4, freq="s"))
        timestamps += list(pd.date_range("2022-06-01", periods=4, freq="s"))
        frame = pd.DataFrame({"배정번호": [1] * 4 + [2] * 4, "TAG_MIN": timestamps})
        exporter = IFRecordExporter(root / "out", frame, base_code_path=source,
            patched_code_path=source, min_history_valid_count=300, test_mode=True)
        valid = np.array([True, True, True, True, False, True, True, True])
        score = np.array([0.1, 0.2, 0.3, 0.4, np.nan, 0.8, 0.9, 0.2])
        cand = valid & (score >= 0.7)
        qual = cand.copy()
        rows = frame.iloc[:4].copy()
        rows.insert(0, "source_row_position", np.arange(4))
        invalid_qual = qual.copy()
        invalid_qual[4] = True
        try:
            exporter.capture(4, model=_SyntheticModel(), valid=valid, score=score,
                cand=cand, qual=invalid_qual, threshold=0.7, training_rows=rows,
                input_feature_names=["temperature", "delta10", "std5", "rate"],
                qual_available=np.array([False] * 4 + [True] * 4))
        except ValueError as error:
            assert "qual" in str(error)
        else:
            raise AssertionError("Invalid record accepted as a qualified candidate")
        for sensor in (4, 5):
            exporter.capture(sensor, model=_SyntheticModel(), valid=valid, score=score,
                cand=cand, qual=qual, threshold=0.7, training_rows=rows,
                input_feature_names=["temperature", "delta10", "std5", "rate"],
                qual_available=np.array([False] * 4 + [True] * 4))
        metadata = exporter.finish()
        info = json.loads(metadata.read_text(encoding="utf-8"))
        assert info["test_mode"] is True and info["for_submission"] is False
        assert info["sensors"]["4"]["exported_qualified_count"] == 2
        assert all(sha256(root / "out" / name) == digest for name, digest in info["files_sha256"].items())
        try:
            IFRecordExporter(root / "forbidden", frame, base_code_path=source,
                patched_code_path=source, min_history_valid_count=300)
        except ValueError as error:
            assert "해시" in str(error)
        else:
            raise AssertionError("Production accepted an unverified source")
        print("PASS: 합성 저장·복원·해시 검증·출처 차단. 실제 분석 실행은 하지 않았습니다.")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    arguments = parser.parse_args()
    if arguments.self_test:
        self_test()
    else:
        parser.error("이 파일은 최신 4단계 코드에서 가져와 쓰는 도우미입니다. 사용안내.txt를 읽으세요.")
