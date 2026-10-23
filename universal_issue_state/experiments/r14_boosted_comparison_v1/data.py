from pathlib import Path
from datetime import date,timedelta
import copy
import numpy as np
import pyarrow as pa,pyarrow.parquet as pq
import s0
from r14_s1.data import DevelopmentLoader,read_dates,unique_rows
from common import save,seal,read_seal

class Data:
 def __init__(self,root,project,cfg):
  self.root=root;self.project=project;self.cfg=cfg;self.loader=DevelopmentLoader(project,root/'foundation');self.contract=self.loader.contract
  self.columns=[n for ns in cfg['features'].values() for n in ns];self.loader.features=copy.deepcopy(self.loader.features);self.loader.features['registry_entries'].update(cfg['feature_entries']);self.loader.features['sets']['B0_Q']=self.columns
 def load(self,cache=None,probe=False):
  if cache and (cache/'MANIFEST.json').exists():
   m=read_seal(cache/'MANIFEST.json');s0.require(m['configuration']==s0.sha256(self.root/'config.json'),'Changed feature-cache configuration');s0.require(s0.sha256(cache/'features.parquet')==m['file_sha256'],'Changed feature cache')
   for rel,h in m['inputs'].items():s0.require(s0.sha256(self.loader._input(rel))==h,'Changed weather input')
   rows=pq.read_table(cache/'features.parquet').to_pylist()
  else:
   batches=[]
   if probe:
    train=self.loader.fold_dates('OUTER_01','TRAIN','INNER_02');ds=list(train)[::3];batches.append(self.loader.load_features('B0_Q','OUTER_01','TRAIN','INNER_02',dates=ds))
    batches.append(self.loader.load_features('B0_Q','OUTER_01','ASSESS','INNER_02',dates=[date(2022,1,20),date(2022,2,20),date(2022,3,13)]))
   else:
    ds=[d for d in self.loader.fold_dates('OUTER_03','TRAIN') if d.year<=2022];batches.append(self.loader.load_features('B0_Q','OUTER_03','TRAIN',dates=ds))
    for oid in ['OUTER_01','OUTER_02','OUTER_03']:batches.append(self.loader.load_features('B0_Q',oid,'ASSESS'))
   rows=[]
   for b in batches:
    for m,x in zip(b.metadata,b.X):rows.append({'issue_state_id':m['issue_state_id'],'target_date':str(m['target_date']),'minutes':m['local_minutes_since_0200'],'expected_issues':m['issue_count_for_target_day'],'features':x.tolist()})
   rows.sort(key=lambda r:(r['target_date'],r['minutes']))
   if cache:
    cache.mkdir(parents=True,exist_ok=True);pq.write_table(pa.Table.from_pylist(rows),cache/'features.parquet');seal(cache/'MANIFEST.json',{'configuration':s0.sha256(self.root/'config.json'),'file_sha256':s0.sha256(cache/'features.parquet'),'inputs':self.loader.input_hashes(),'outcome_columns':False})
  self.meta=rows;self.dates=np.array([r['target_date'] for r in rows]);self.ids=[r['issue_state_id'] for r in rows];s0.require(len(set(self.ids))==len(self.ids),'Duplicate input keys');self.expected=np.array([r['expected_issues'] for r in rows]);X=np.array([r['features'] for r in rows]);self.offset=(X[:,self.columns.index(self.cfg['offset'])]-273.15)*1.8+32
  heating=X[:,self.columns.index('q05_local_remaining_max')]-X[:,self.columns.index('q05_local_asof_value')];self.X=np.column_stack([X,heating]);self.available=np.isfinite(self.offset)
  return self
 def mask(self,start,end):return (self.dates>=start)&(self.dates<=end)
 def truth(self,mask,cutoff=None):
  ds=sorted(set(self.dates[mask]));s0.require(ds and min(ds)>='2021-01-01' and max(ds)<='2025-09-06','Unauthorized truth date')
  if cutoff is not None:s0.require(max(ds)<=cutoff,'Unavailable label used')
  dates=[date.fromisoformat(d) for d in ds];t=self.loader.supplement['truth_accessor'];auth=read_dates(self.loader._input(t['catalog']),t['catalog_authorization_columns'],dates).to_pylist();a=unique_rows(auth,['target_date']);s0.require(set(a)=={(d,) for d in dates},'Missing truth authorization')
  for r in auth:s0.require(r['truth_group']=='development' and r['label_available_for_supervised_use'] and r['source_artifact_path']==t['source_path'] and r['source_artifact_sha256']==t['source_sha256'],'Unauthorized truth')
  path=self.loader._input(t['source_path']);source_dates=pq.ParquetFile(path).read(columns=['target_date'])['target_date'].to_pylist();s0.require(max(source_dates)<=date(2025,9,6),'Reserved labels in source')
  values=unique_rows(read_dates(path,['target_date','y_audited_f'],dates).to_pylist(),['target_date']);out=np.full(len(self.dates),np.nan)
  for i in np.where(mask)[0]:
   y=values[(date.fromisoformat(self.dates[i]),)]['y_audited_f'];s0.require(type(y) is int and -40<=y<=120,'Invalid truth');out[i]=y
  return out

def label_cutoff(start):return str(date.fromisoformat(start)-timedelta(days=2))
