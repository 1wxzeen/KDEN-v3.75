"""Development-only loading with physically separate predictors and labels."""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from collections import Counter
from pathlib import Path
from zoneinfo import ZoneInfo
import numpy as np
import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq
import s0

MODEL_SETS={'B0_H':'B0_H','B0_Q':'B0_Q','ANEN':'ANEN','GAM_LS_NORMAL':'GAM','GAM_LOCATION_NORMAL':'GAM','GAM_LS_T5':'GAM'}
FEATURE_KEYS=['issue_state_id','target_date','statistical_group_id','issue_time_utc','wrfsfcf_cycle_init_utc','wrfsubhf_cycle_init_utc']


def as_date(x):
    s0.require(isinstance(x,date) and not isinstance(x,datetime) or isinstance(x,str),'Expected target date')
    return date.fromisoformat(x) if isinstance(x,str) else x


def kelvin_to_fahrenheit(x):
    """Only absolute temperature centers use this conversion; differences do not."""
    return (np.asarray(x,dtype=float)-273.15)*1.8+32.0


def legal_issue_times(day):
    day=as_date(day)
    start=datetime.combine(day,time(7),timezone.utc)
    return [t for i in range(96) if (t:=start+timedelta(minutes=15*i)).astimezone(ZoneInfo('America/Denver')).date()==day
            and 120 <= (t.astimezone(ZoneInfo('America/Denver')).hour*60+t.astimezone(ZoneInfo('America/Denver')).minute) <=960]


def read_dates(path, columns, dates):
    """Explicit projection and date predicate; never infer columns from data."""
    s0.require(len(columns)==len(set(columns)),'Duplicate projected columns')
    dates=sorted({as_date(d) for d in dates})
    return ds.dataset(str(path),format='parquet').to_table(columns=columns,filter=ds.field('target_date').isin(pa.array(dates,type=pa.date32())))


def unique_rows(rows,key):
    result={}
    for row in rows:
        value=tuple(row[k] for k in key)
        s0.require(value not in result,f'Duplicate key {key}: {value}')
        result[value]=row
    return result


def day_weights(days,available):
    days=list(days);available=np.asarray(available,dtype=bool)
    s0.require(available.shape==(len(days),),'Weight mask shape')
    counts=Counter(d for d,a in zip(days,available) if a)
    return np.array([1/(len(counts)*counts[d]) if a else 0.0 for d,a in zip(days,available)],dtype=float)


@dataclass(frozen=True)
class FeatureBatch:
    model_id: str
    columns: tuple
    X: np.ndarray
    metadata: tuple
    available: np.ndarray
    missing_features: tuple
    source_hashes: dict
    outer_fold_id: str
    inner_fold_id: str | None
    split: str

    @property
    def dates(self):return tuple(r['target_date'] for r in self.metadata)
    @property
    def weights(self):return day_weights(self.dates,self.available)
    @property
    def baseline_center_f(self):
        name='h16_local_retained_max' if self.model_id=='B0_H' else 'q05_local_retained_max'
        return kelvin_to_fahrenheit(self.X[:,self.columns.index(name)])


class DevelopmentLoader:
    """Assessment feature reads are target-free. No outer assessment-label API."""
    def __init__(self,project_root,experiment_root=None):
        self.project=Path(project_root).resolve()
        self.experiment=Path(experiment_root or Path(__file__).resolve().parents[2]).resolve()
        self.contract=s0.read_json(self.experiment/'config/experiment.json')
        self.supplement=s0.read_json(self.experiment/'config/s1_foundation.json')
        self.features=s0.read_json(self.experiment/'config/features.json')
        for n in ['experiment','features']:
            s0.exact_schema(s0.read_json(self.experiment/f'config/{n}.json'),s0.read_json(self.experiment/f'schemas/{n}.schema.json'))
        s0.exact_schema(self.supplement,s0.read_json(self.experiment/'schemas/s1_foundation.schema.json'))
        s0.require(s0.sha256(self.experiment/'manifests/S0_RELEASE.json')==self.supplement['parent_s0_release_sha256'],'S0 parent changed')
        self.expected={r['path']:r['sha256'] for r in s0.read_json(self.experiment/'manifests/input_inventory.json')['files']}
        self.expected[self.supplement['truth_accessor']['source_path']]=self.supplement['truth_accessor']['source_sha256']
        self.verified={}
        self.roles={r['target_date']:r for r in pq.ParquetFile(self._input('folds/kden_v375/v1/date_roles.parquet')).read(columns=s0.ROLE_COLS).to_pylist()}

    def _input(self,relative):
        s0.require(relative in self.expected,f'Unregistered input: {relative}')
        p=s0.safe_path(self.project,relative)
        # Verify once per loader; reject changed size/mtime within its lifetime.
        stat=(p.stat().st_size,p.stat().st_mtime_ns)
        if relative in self.verified:
            s0.require(self.verified[relative]==stat,'Input changed during loader lifetime')
        else:
            s0.require(s0.sha256(p)==self.expected[relative],f'Input hash mismatch: {relative}')
            self.verified[relative]=stat
        return p

    def input_hashes(self):
        """Fit lineage after feature and label access includes the audited source ledger."""
        return {k:self.expected[k] for k in sorted(self.verified)}

    def fold_dates(self,outer_id,split,inner_id=None):
        s0.require(split in ['TRAIN','ASSESS'],'Invalid split')
        outer=next((f for f in self.contract['folds']['outer'] if f['outer_fold_id']==outer_id),None)
        s0.require(outer is not None,'Unknown outer fold')
        if inner_id:
            spec=next((f for f in self.contract['folds']['inner'] if f['inner_fold_id']==inner_id),None)
            s0.require(spec is not None and spec['assessment_end']<=outer['train_end'],'Inner not in outer training window')
            name='inner_folds.parquet';cols=['inner_fold_id']+s0.FOLD_COLS
        else:spec=outer;name='outer_folds.parquet';cols=s0.FOLD_COLS
        rows=pq.ParquetFile(self._input('folds/kden_v375/v1/'+name)).read(columns=cols).to_pylist()
        selected=[r for r in rows if r['outer_fold_id']==outer_id and (not inner_id or r['inner_fold_id']==inner_id) and r['assignment']==split]
        unique_rows(selected,['target_date'])
        cutoff=as_date(spec['assessment_start'])-timedelta(days=self.contract['truth']['publication_lag_target_days'])
        dates=sorted(r['target_date'] for r in selected if split!='TRAIN' or r['target_date']<=cutoff)
        for d in dates:
            s0.require(self.roles[d]['evidence_role']=='DEVELOPMENT_SUPERVISED' and self.roles[d]['supervised_eligible'],'Unauthorized date role')
            s0.require(as_date('2021-01-01')<=d<=as_date('2025-09-06'),'Nondevelopment date')
        return tuple(dates)

    def _requested(self,outer,split,inner,dates):
        allowed=set(self.fold_dates(outer,split,inner))
        if dates is None:return sorted(allowed)
        requested=[as_date(d) for d in dates]
        s0.require(requested and len(set(requested))==len(requested),'Empty/duplicate requested dates')
        s0.require(set(requested)<=allowed,'Requested date outside authorized fold/lag/role')
        return sorted(requested)

    def load_features(self,model_id,outer_id,split='TRAIN',inner_id=None,dates=None):
        s0.require(model_id in MODEL_SETS,'Unregistered model')
        requested=self._requested(outer_id,split,inner_id,dates)
        columns=tuple(self.features['sets'][MODEL_SETS[model_id]])
        spine_path=self._input(self.contract['time']['issue_spine_path'])
        spine=read_dates(spine_path,['issue_state_id','target_date','statistical_group_id','issue_time_utc','local_minutes_since_0200','issue_count_for_target_day','target_window_start_utc','target_window_end_utc'],requested).to_pylist()
        smap=unique_rows(spine,['issue_state_id'])
        spine.sort(key=lambda r:(r['target_date'],r['issue_time_utc']))
        for day in requested:
            rows=[r for r in spine if r['target_date']==day]
            s0.require([r['issue_time_utc'] for r in rows]==legal_issue_times(day),'Incomplete or invalid issue grid')
            for r in rows:
                s0.require(r['issue_count_for_target_day']==len(rows),'Day issue count mismatch')
                s0.require(r['statistical_group_id']==self.roles[day]['statistical_group_id'],'Statistical group mismatch')
                s0.require(r['target_window_start_utc']==datetime.combine(day,time(7),timezone.utc),'Climate-window start')
                s0.require(r['target_window_end_utc']==r['target_window_start_utc']+timedelta(days=1),'Climate-window end')
                local=r['issue_time_utc'].astimezone(ZoneInfo('America/Denver'))
                s0.require(r['local_minutes_since_0200']==local.hour*60+local.minute-120,'Issue minute mismatch')
        cycles=read_dates(self._input(self.contract['time']['selected_cycles_path']),['issue_state_id','target_date','issue_time_utc','product','selection_status','cycle_init_utc','emulated_complete_time_utc','previous_cycle_init_utc','previous_emulated_complete_time_utc'],requested).to_pylist()
        cmap=unique_rows(cycles,['issue_state_id','product'])
        s0.require(set(cmap)=={(r['issue_state_id'],p) for r in spine for p in ['wrfsfcf','wrfsubhf']},'Cycle join keys incomplete/extra')
        feature_rows=[]
        for year in sorted({d.year for d in requested}):
            relative=f'universal_issue_state/v1/deterministic_features/target_year={year}/part-{year}.parquet'
            names=list(dict.fromkeys(FEATURE_KEYS+list(columns)))
            feature_rows.extend(read_dates(self._input(relative),names,[d for d in requested if d.year==year]).to_pylist())
        fmap=unique_rows(feature_rows,['issue_state_id'])
        s0.require(set(fmap)==set(smap),'Feature/spine join mismatch')
        X=[];meta=[]
        errata={e['feature_name']:e['accepted_range'] for e in self.features['errata_overlay']['entries']}
        for r in spine:
            f=fmap[(r['issue_state_id'],)]
            for k in ['target_date','statistical_group_id','issue_time_utc']:s0.require(f[k]==r[k],f'Feature key mismatch {k}')
            m=dict(r)
            for product in ['wrfsfcf','wrfsubhf']:
                cy=cmap[(r['issue_state_id'],product)]
                s0.require(cy['target_date']==r['target_date'] and cy['issue_time_utc']==r['issue_time_utc'],'Cycle time/key mismatch')
                s0.require(cy['selection_status']=='SELECTED' and cy['cycle_init_utc'] is not None,'Unavailable selected cycle')
                s0.require(cy['emulated_complete_time_utc']==cy['cycle_init_utc']+timedelta(minutes=105) and cy['emulated_complete_time_utc']<=r['issue_time_utc'],'Future/invalid cycle availability')
                if cy['previous_cycle_init_utc'] is not None:
                    s0.require(cy['previous_cycle_init_utc']<cy['cycle_init_utc'] and cy['previous_emulated_complete_time_utc']==cy['previous_cycle_init_utc']+timedelta(minutes=105) and cy['previous_emulated_complete_time_utc']<=r['issue_time_utc'],'Invalid previous cycle')
                s0.require(f[product+'_cycle_init_utc']==cy['cycle_init_utc'],'Feature/cycle mismatch')
                m[product+'_cycle_init_utc']=cy['cycle_init_utc']
            values=[]
            for name in columns:
                value=f[name]
                if value is not None:
                    s0.require(np.isfinite(value),f'Nonfinite feature {name}')
                    bounds=errata.get(name,self.features['registry_entries'][name]['physical_range'])
                    s0.require(bounds[0]<=value<=bounds[1],f'Feature outside accepted bounds {name}')
                values.append(np.nan if value is None else float(value))
            X.append(values);meta.append(m)
        X=np.array(X,dtype=float);available=np.all(np.isfinite(X),axis=1)
        missing=tuple(tuple(c for c,x in zip(columns,row) if not np.isfinite(x)) for row in X)
        X.setflags(write=False);available.setflags(write=False)
        return FeatureBatch(model_id,columns,X,tuple(meta),available,missing,{k:self.expected[k] for k in self.verified},outer_id,inner_id,split)

    def training_labels(self,batch):
        s0.require(batch.split=='TRAIN','Assessment labels are not exposed through training loader')
        allowed=set(self.fold_dates(batch.outer_fold_id,'TRAIN',batch.inner_fold_id))
        dates=sorted(set(batch.dates));s0.require(set(dates)<=allowed,'Labels outside training fold')
        t=self.supplement['truth_accessor']
        catalog=read_dates(self._input(t['catalog']),t['catalog_authorization_columns'],dates).to_pylist()
        authorized=unique_rows(catalog,['target_date'])
        s0.require(set(authorized)=={(d,) for d in dates},'Truth authorization missing')
        for r in catalog:
            s0.require(r['truth_group']=='development' and r['label_available_for_supervised_use'] is True,'Truth role unauthorized')
            s0.require(r['source_artifact_path']==t['source_path'] and r['source_artifact_sha256']==t['source_sha256'],'Catalog/source binding mismatch')
        source=self._input(t['source_path'])
        source_dates=pq.ParquetFile(source).read(columns=['target_date'])['target_date'].to_pylist()
        s0.require(source_dates and max(source_dates)<=as_date(t['source_max_date']),'Truth source contains reserved/tail dates')
        values=read_dates(source,['target_date','y_audited_f'],dates).to_pylist()
        vmap=unique_rows(values,['target_date'])
        s0.require(set(vmap)==set(authorized),'Source truth join mismatch')
        for row in values:
            y=row['y_audited_f'];s0.require(type(y) is int and -40<=y<=120,'Missing/noninteger/out-of-support audited truth')
        y=np.array([vmap[(d,)]['y_audited_f'] for d in batch.dates],dtype=np.int16);y.setflags(write=False)
        return y
