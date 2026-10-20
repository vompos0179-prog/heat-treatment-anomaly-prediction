# ════════════════════════════════════════════════════════════════════
# 3단계 ① 팀 코드 재현본 — 팀원 20번 코드(20_FINAL_1S_ANALYSIS_EXECUTED.py)를 이 프로젝트에서 돌리기
#
# 실행(프로젝트 맨 위 폴더에서):
#   .\.venv\Scripts\python.exe "stages/3단계_이상구간/3단계_이상구간_팀코드재현.py"
#   검증용 기록 저장을 끄려면 끝에 --no-labels 를 붙입니다(결과 비교 시험용).
# 출력: reports/3단계_이상구간_팀코드재현/(실행시각)/ — 팀 코드와 같은 00~07 파일
#       + 검증용_기록라벨/(작업별 .npz) + 실행정보.txt
#
# 팀 코드에서 바꾼 곳은 계획 §14-2의 네 곳뿐이며, 모두 "[변경 n]" 표시를 달았습니다.
#   [변경 1] 입력: zip 안 파일 → data/raw/의 같은 파일 (읽기 옵션은 그대로)
#   [변경 2] 출력: /mnt/data/... → reports/3단계_이상구간_팀코드재현/(실행시각)/ (덮어쓰기 안 함)
#   [변경 3] 맨 앞 .venv 확인과 화면 출력 보호 (계산에 영향 없음)
#   [변경 4] 검증용 기록 저장: 이미 계산된 valid·cand·qual을 읽기만 해서 저장 (계산에 영향 없음)
# 그 밖의 줄(규칙 상수, float32 읽기, 계산 순서, 정규식, 출력 이름·열)은 팀 코드와 글자까지 같습니다.
# ════════════════════════════════════════════════════════════════════
# [변경 3] 시작 — 프로젝트 전용 파이썬 확인, 화면 출력 보호 (1단계 통합본과 같은 방식)
import sys, time, platform
from datetime import datetime
from pathlib import Path as _P
_PROJECT = _P(__file__).resolve().parents[2]  # stages/3단계_이상구간/ 의 두 단계 위 = 프로젝트 맨 위 폴더
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, 'reconfigure'):
        _stream.reconfigure(errors='replace')  # cp949 화면에서 표현 못 하는 글자는 '?'로
# Python·패키지 버전이 권장 환경과 다르면 [주의]만 보여 주고 계속합니다(src/env_check.py).
sys.path.insert(0, str(_PROJECT))
from src.env_check import check_python_env as _check_env
_check_env(_PROJECT)
_SAVE_LABELS = '--no-labels' not in sys.argv[1:]
_T0 = time.time()
# [변경 3] 끝

from pathlib import Path
import zipfile, json, math, warnings
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

# [변경 1] 입력 — 원래: DATA_ZIP = Path('/mnt/data/Dataset_열처리 품질보증 AI 데이터셋(3).zip')
RAW_CSV = _PROJECT / 'data' / 'raw' / 'data.csv'
QUALITY_XLSX = _PROJECT / 'data' / 'raw' / '열처리_품질데이터.xlsx'
# [변경 2] 출력 — 원래: OUT = Path('/mnt/data/FINAL_1S_A3_B1_C3C2'); OUT.mkdir(parents=True, exist_ok=True)
OUT = _PROJECT / 'reports' / '3단계_이상구간_팀코드재현' / datetime.now().strftime('%Y%m%d_%H%M%S_%f')
OUT.mkdir(parents=True, exist_ok=False)  # 이미 있으면 멈춤(덮어쓰기 방지)
# [변경 4] 검증용 기록 저장 폴더
LABEL_DIR = OUT / '검증용_기록라벨'
if _SAVE_LABELS: LABEL_DIR.mkdir()

TIME='TAG_MIN'; BATCH='배정번호'
SENSORS=[
    '소입로 온도 1 Zone','소입로 온도 2 Zone','소입로 온도 3 Zone','소입로 온도 4 Zone',
    '솔트조 온도 1 Zone','솔트조 온도 2 Zone'
]
PHYS={s:(0.3 if '솔트조' in s else 3.0) for s in SENSORS}
ROLL_SEC=600
MIN_HISTORY=300
ZTH=4.0
LONG_GAP=60
EVENT_GAP=2
MIN_DURATION=60

print('1) 품질/원본 로딩')
if True:  # [변경 1] 원래: with zipfile.ZipFile(DATA_ZIP) as z:  (들여쓰기 유지용)
    q=pd.read_excel(QUALITY_XLSX)  # [변경 1] 원래: pd.read_excel(z.open('data/열처리_품질데이터.xlsx'))
    q[BATCH]=q[BATCH].astype(str).str.replace(r'\\.0$','',regex=True)
    q['작업일']=pd.to_datetime(q['작업일'])
    q['불량률(%)']=np.where(q['총수량']>0,q['불량수량']/q['총수량']*100,np.nan)
    q['period']=np.select([
        q['작업일'].dt.month<=4,
        q['작업일'].dt.month==5,
        q['작업일'].dt.month>=6,
    ],['기준작성(1~4월)','조정(5월)','후속비교(6~7월)'],default='기타')
    period_map=dict(zip(q[BATCH],q['period']))
    date_map=dict(zip(q[BATCH],q['작업일']))
    dtype={BATCH:'string', **{s:'float32' for s in SENSORS}}
    with open(RAW_CSV,'rb') as f:  # [변경 1] 원래: with z.open('data/data.csv') as f:  (둘 다 바이트로 열림)
        df=pd.read_csv(f,encoding='cp949',usecols=[TIME,BATCH]+SENSORS,dtype=dtype,low_memory=False)

df[BATCH]=df[BATCH].astype(str).str.replace(r'\\.0$','',regex=True)
df[TIME]=pd.to_datetime(df[TIME],format='%Y-%m-%d %H:%M:%S',errors='coerce')
df=df.sort_values([BATCH,TIME]).reset_index(drop=True)
print('rows',len(df),'batches',df[BATCH].nunique())

# split each batch into continuity segments on long gaps

def add_segment_ids(g):
    gap=g[TIME].diff().dt.total_seconds()
    return (gap.isna() | (gap>LONG_GAP)).cumsum().astype('int32')

def rolling_baseline(g):
    # returns baseline dataframe aligned with g index; rolling time window, current point excluded
    out=pd.DataFrame(index=g.index, columns=SENSORS, dtype='float64')
    seg=add_segment_ids(g)
    for _, idx in g.groupby(seg, sort=False).groups.items():
        sub=g.loc[idx, [TIME]+SENSORS].set_index(TIME)
        rb=sub[SENSORS].rolling(f'{ROLL_SEC}s',closed='left',min_periods=MIN_HISTORY).median()
        rb.index=g.loc[idx].index  # restore row indices by order
        out.loc[idx,SENSORS]=rb[SENSORS].to_numpy()
    return out

print('2) A1 학습 잔차 척도 계산 (1~4월)')
resid_store={s:[] for s in SENSORS}
train_batches=set(q.loc[q['period']=='기준작성(1~4월)',BATCH])
for n,(b,g) in enumerate(df.groupby(BATCH,sort=False),1):
    if b not in train_batches: continue
    base=rolling_baseline(g)
    for s in SENSORS:
        r=(g[s].astype('float64')-base[s]).to_numpy()
        r=r[np.isfinite(r)]
        if len(r): resid_store[s].append(r.astype('float32'))
    if n%20==0: print(' train batch progress',n)

a1_scale={}
a1_resid_center={}
for s in SENSORS:
    arr=np.concatenate(resid_store[s]).astype('float64') if resid_store[s] else np.array([])
    med=float(np.nanmedian(arr))
    mad=float(np.nanmedian(np.abs(arr-med)))
    scale=1.4826*mad
    if not np.isfinite(scale) or scale<1e-9: scale=np.nanstd(arr)
    a1_resid_center[s]=med
    a1_scale[s]=float(scale)
    print(' A1 scale',s,'center',med,'scale',scale,'n',len(arr))

print('3) A2 고정 강건 Z 기준 계산 (1~4월)')
train_mask=df[BATCH].isin(train_batches)
a2_center={}; a2_scale={}
for s in SENSORS:
    arr=df.loc[train_mask,s].dropna().astype('float64').to_numpy()
    med=float(np.median(arr)); mad=float(np.median(np.abs(arr-med))); scale=1.4826*mad
    if not np.isfinite(scale) or scale<1e-9: scale=float(np.std(arr))
    a2_center[s]=med; a2_scale[s]=scale
    print(' A2',s,'median',med,'scale',scale)

pd.DataFrame({
    'sensor':SENSORS,
    'A1_residual_center':[a1_resid_center[s] for s in SENSORS],
    'A1_residual_scale':[a1_scale[s] for s in SENSORS],
    'A2_fixed_median':[a2_center[s] for s in SENSORS],
    'A2_fixed_scale':[a2_scale[s] for s in SENSORS],
    'physical_min_deviation':[PHYS[s] for s in SENSORS],
}).to_csv(OUT/'01_고정된_기준값.csv',index=False,encoding='utf-8-sig')


def qualifying_event_mask(times, cand, min_duration=MIN_DURATION, max_gap=EVENT_GAP):
    times=pd.Series(pd.to_datetime(times)).reset_index(drop=True)
    cand=np.asarray(cand,dtype=bool)
    qual=np.zeros(len(cand),dtype=bool); events=[]
    pos=np.flatnonzero(cand)
    if len(pos)==0: return qual,events
    t=times.iloc[pos].to_numpy(dtype='datetime64[ns]')
    diffs=np.diff(t).astype('timedelta64[s]').astype(int)
    cuts=np.r_[0,np.flatnonzero(diffs>max_gap)+1,len(pos)]
    for a,b in zip(cuts[:-1],cuts[1:]):
        p=pos[a:b]
        if len(p)==0: continue
        dur=(times.iloc[p[-1]]-times.iloc[p[0]]).total_seconds()+1
        if dur>=min_duration:
            qual[p]=True
            events.append((int(p[0]),int(p[-1]),float(dur),int(len(p))))
    return qual,events

print('4) A1/A2 전체 136배치 적용')
batch_rows=[]; event_rows=[]; rep_cache={}
rep_batches={'102410','128795','133924'}
for bi,(b,g0) in enumerate(df.groupby(BATCH,sort=False),1):
    g=g0.reset_index(drop=True).copy()
    times=g[TIME]
    base=rolling_baseline(g0).reset_index(drop=True)
    method_masks={}; valid_masks={}
    sensor_stats={}
    _lab={}  # [변경 4] 이 작업의 검증용 기록 라벨
    for method in ['A1','A2']:
        union=np.zeros(len(g),dtype=bool)
        valid_all=np.ones(len(g),dtype=bool)
        total_events=0
        for s in SENSORS:
            x=g[s].astype('float64').to_numpy()
            if method=='A1':
                bl=base[s].to_numpy(dtype='float64')
                dev=x-bl-a1_resid_center[s]
                score=np.abs(dev)/a1_scale[s]
                valid=np.isfinite(x)&np.isfinite(bl)&np.isfinite(score)
                cand=valid & (score>=ZTH) & (np.abs(x-bl)>=PHYS[s])
            else:
                dev=x-a2_center[s]
                score=np.abs(dev)/a2_scale[s]
                valid=np.isfinite(x)&np.isfinite(score)
                cand=valid & (score>=ZTH) & (np.abs(dev)>=PHYS[s])
            qual,evs=qualifying_event_mask(times,cand)
            if _SAVE_LABELS:  # [변경 4] 읽기만 해서 복사본 보관(계산 변수는 그대로)
                _lab[f'{method}_{SENSORS.index(s)}_valid']=np.array(valid,dtype=bool,copy=True)
                _lab[f'{method}_{SENSORS.index(s)}_cand']=np.array(cand,dtype=bool,copy=True)
                _lab[f'{method}_{SENSORS.index(s)}_qual']=np.array(qual,dtype=bool,copy=True)
            union |= qual
            valid_all &= valid
            total_events += len(evs)
            sensor_stats[(method,s,'event_count')]=len(evs)
            sensor_stats[(method,s,'candidate_count')]=int(cand.sum())
            for st,en,dur,npts in evs:
                event_rows.append({
                    'method':method,'배정번호':b,'period':period_map.get(b,''),'sensor':s,
                    'start_time':times.iloc[st],'end_time':times.iloc[en],
                    'duration_sec':dur,'anomaly_sample_count':npts,
                    'max_score':float(np.nanmax(score[st:en+1])) if en>=st else np.nan,
                    'max_abs_deviation':float(np.nanmax(np.abs(dev[st:en+1]))) if en>=st else np.nan,
                })
        method_masks[method]=union
        valid_masks[method]=valid_all
        denom=int(valid_all.sum()); anom=int((union&valid_all).sum())
        sensor_stats[(method,'ALL','valid_count')]=denom
        sensor_stats[(method,'ALL','anomaly_count')]=anom
        sensor_stats[(method,'ALL','ratio_pct')]=anom/denom*100 if denom else np.nan
        sensor_stats[(method,'ALL','event_count')]=total_events
    common=valid_masks['A1']&valid_masks['A2']
    overlap=int((method_masks['A1']&method_masks['A2']&common).sum())
    unionc=int(((method_masks['A1']|method_masks['A2'])&common).sum())
    row={
        '배정번호':b,'작업일':date_map.get(b,pd.NaT),'period':period_map.get(b,''),
        'raw_rows':len(g),
        'A1_valid_sec':sensor_stats[('A1','ALL','valid_count')],
        'A1_anomaly_sec':sensor_stats[('A1','ALL','anomaly_count')],
        'A1_anomaly_ratio_pct':sensor_stats[('A1','ALL','ratio_pct')],
        'A1_event_count':sensor_stats[('A1','ALL','event_count')],
        'A2_valid_sec':sensor_stats[('A2','ALL','valid_count')],
        'A2_anomaly_sec':sensor_stats[('A2','ALL','anomaly_count')],
        'A2_anomaly_ratio_pct':sensor_stats[('A2','ALL','ratio_pct')],
        'A2_event_count':sensor_stats[('A2','ALL','event_count')],
        'A1_A2_overlap_sec':overlap,
        'A1_A2_union_sec':unionc,
        'A1_A2_jaccard':overlap/unionc if unionc else np.nan,
    }
    for method in ['A1','A2']:
        for s in SENSORS:
            key=s.replace(' ','_')
            row[f'{method}_{key}_event_count']=sensor_stats[(method,s,'event_count')]
    batch_rows.append(row)
    if b in rep_batches:
        rep_cache[b]={'g':g.copy(),'base':base.copy(),'A1':method_masks['A1'].copy(),'A2':method_masks['A2'].copy()}
    if _SAVE_LABELS:  # [변경 4] 기록 시각(나노초 정수)과 라벨을 작업별 압축 파일로 저장
        np.savez_compressed(LABEL_DIR/f'{b}.npz', TAG_MIN_ns=times.to_numpy(dtype='datetime64[ns]').astype('int64'), **_lab)
    if bi%20==0: print(' apply progress',bi)

batch=pd.DataFrame(batch_rows)
events=pd.DataFrame(event_rows)
res=batch.merge(q[[BATCH,'양품수량','불량수량','총수량','불량률(%)']],on=BATCH,how='left')
res.to_csv(OUT/'02_배정번호별_A1_A2_결과.csv',index=False,encoding='utf-8-sig')
events.to_csv(OUT/'03_A1_A2_이상이벤트.csv',index=False,encoding='utf-8-sig')

# period summary
summ=[]
for period,sub in res.groupby('period',sort=False):
    for method in ['A1','A2']:
        valid=sub[f'{method}_valid_sec'].sum(); anom=sub[f'{method}_anomaly_sec'].sum()
        summ.append({
            'period':period,'method':method,'batch_count':sub[BATCH].nunique(),
            'valid_sec':int(valid),'anomaly_sec':int(anom),
            'anomaly_ratio_pct':anom/valid*100 if valid else np.nan,
            'event_count':int(sub[f'{method}_event_count'].sum()),
            'median_batch_ratio_pct':sub[f'{method}_anomaly_ratio_pct'].median(),
        })
period_summary=pd.DataFrame(summ)
period_summary.to_csv(OUT/'04_기간별_A1_A2_요약.csv',index=False,encoding='utf-8-sig')

# sensor event summary
if len(events):
    sensor_summary=(events.groupby(['period','method','sensor'],as_index=False)
                    .agg(event_count=('duration_sec','size'),total_duration_sec=('duration_sec','sum'),median_duration_sec=('duration_sec','median'),max_duration_sec=('duration_sec','max')))
else:
    sensor_summary=pd.DataFrame()
sensor_summary.to_csv(OUT/'05_센서별_이벤트요약.csv',index=False,encoding='utf-8-sig')

# quality association - descriptive only
assoc=[]
for scope_name,sub in [('전체136',res),('기준작성1~4월',res[res.period=='기준작성(1~4월)']),('조정5월',res[res.period=='조정(5월)']),('후속비교6~7월',res[res.period=='후속비교(6~7월)'])]:
    for method in ['A1','A2']:
        x=sub[f'{method}_anomaly_ratio_pct']; y=sub['불량률(%)']; m=x.notna()&y.notna()
        if m.sum()>=3:
            rho,p=spearmanr(x[m],y[m])
        else: rho,p=np.nan,np.nan
        assoc.append({'scope':scope_name,'method':method,'n_batch':int(m.sum()),'spearman_rho':rho,'p_value':p})
assoc=pd.DataFrame(assoc)
assoc.to_csv(OUT/'06_불량률_연관성_참고.csv',index=False,encoding='utf-8-sig')

# monthly descriptive comparison
month=res.copy(); month['month']=pd.to_datetime(month['작업일']).dt.month
monthly=(month.groupby('month',as_index=False).agg(
    batch_count=(BATCH,'nunique'),total_qty=('총수량','sum'),defects=('불량수량','sum'),
    A1_anomaly_sec=('A1_anomaly_sec','sum'),A1_valid_sec=('A1_valid_sec','sum'),
    A2_anomaly_sec=('A2_anomaly_sec','sum'),A2_valid_sec=('A2_valid_sec','sum')))
monthly['불량률_ppm']=monthly['defects']/monthly['total_qty']*1_000_000
monthly['A1_anomaly_ratio_pct']=monthly['A1_anomaly_sec']/monthly['A1_valid_sec']*100
monthly['A2_anomaly_ratio_pct']=monthly['A2_anomaly_sec']/monthly['A2_valid_sec']*100
monthly.to_csv(OUT/'07_월별_참고요약.csv',index=False,encoding='utf-8-sig')

# Save rules metadata
rules={
 'resolution':'1 second raw timestamps',
 'A':'A3: A1 main + A2 comparison',
 'B':'B1: Jan-Apr baseline / May adjustment / Jun-Jul retrospective follow-up comparison',
 'C':'C3 + C2 label: freeze rules before follow-up application; Jun-Jul has prior exploratory exposure and is not independent validation',
 'A1':{'window_sec':ROLL_SEC,'min_history_sec':MIN_HISTORY,'center':'past-window median (current point excluded)','scale':'training-period residual MAD*1.4826','z_threshold':ZTH,'physical_min_deviation_C':PHYS,'min_event_duration_sec':MIN_DURATION,'long_gap_reset_sec':LONG_GAP,'event_continuity_gap_sec':EVENT_GAP},
 'A2':{'center':'Jan-Apr sensor median','scale':'Jan-Apr sensor MAD*1.4826','z_threshold':ZTH,'physical_min_deviation_C':PHYS,'min_event_duration_sec':MIN_DURATION},
 'quality_use':'descriptive association only; not anomaly ground truth',
}
(OUT/'00_동결규칙.json').write_text(json.dumps(rules,ensure_ascii=False,indent=2),encoding='utf-8')

print('\nPERIOD SUMMARY')
print(period_summary.to_string(index=False))
print('\nASSOCIATION')
print(assoc.to_string(index=False))
print('\nMONTHLY')
print(monthly.to_string(index=False))
print('events',len(events))

# [변경 3] 실행 기록 — 계산이 모두 끝난 뒤 남기기만 함(계획 §14-2: 실행 시간·환경, 136개 작업 기간 배정 확인)
_batches=list(df[BATCH].unique())
_unassigned=[b for b in _batches if period_map.get(b,'') not in ('기준작성(1~4월)','조정(5월)','후속비교(6~7월)')]
_info=[
    f'실행 시각: {OUT.name}',
    f'걸린 시간: {time.time()-_T0:.1f}초',
    f'파이썬 {platform.python_version()} / pandas {pd.__version__} / numpy {np.__version__} / scipy {__import__("scipy").__version__}',
    f'입력: {RAW_CSV} ({RAW_CSV.stat().st_size:,} bytes), {QUALITY_XLSX}',
    f'원본 행 수: {len(df):,} / 작업 수: {len(_batches)}',
    f'기간에 배정되지 않은 작업 수: {len(_unassigned)} {_unassigned[:10]}',
    f'검증용 기록 저장: {"켬" if _SAVE_LABELS else "끔(--no-labels)"}',
    '팀 코드에서 바꾼 곳: 이 파일 맨 위 설명의 [변경 1]~[변경 4]',
]
(OUT/'실행정보.txt').write_text('\n'.join(_info)+'\n',encoding='utf-8')
print('\n'.join(_info))
print('결과 폴더:',OUT)
