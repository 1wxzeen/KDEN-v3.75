from pathlib import Path
import os,time,json,joblib,shutil
import numpy as np
import pyarrow as pa,pyarrow.parquet as pq
import s0
from common import save,seal,read_seal,digest,validate
from data import Data,label_cutoff
from models import fit_model,predict_pmf
from r14_s1.scoring import score_rows


def predict_chunks(fit,data,idx,cfg):
 ps=[];points=[];diags={}
 for start in range(0,len(idx),2048):
  ii=idx[start:start+2048];p,point,d=predict_pmf(fit,data.X[ii],data.offset[ii],cfg);ps.append(p);points.append(point)
  for k,v in d.items():diags.setdefault(k,[]).append(v)
 return np.concatenate(ps),np.concatenate(points),{k:np.concatenate(v) for k,v in diags.items()}


def select_candidate(records,candidates,cutoff,cfg):
 results={};invalid={}
 for c in candidates:
  parts=[r for r in records if r['candidate']['id']==c['id']];loss={}
  for r in parts:
   if r['status']!='COMPLETE':invalid[c['id']]=r.get('error','FAILED');continue
   vals={d:v for d,v in r['daily_nll'].items() if d<=cutoff}
   if len(vals)<cfg['selection']['minimum_inner_days']:invalid[c['id']]='INSUFFICIENT_INNER_DAYS'
   if set(loss)&set(vals):raise ValueError('Duplicate tuning target day')
   loss.update(vals)
  if len(parts)<cfg['selection']['minimum_inner_blocks']:invalid[c['id']]='INSUFFICIENT_INNER_BLOCKS'
  if c['id'] not in invalid:results[c['id']]={'mean_nll':float(np.mean(list(loss.values()))),'days':len(loss),'max_label_date':max(loss)}
 if not results:raise ValueError('No valid candidates on registered support')
 minimum=min(r['mean_nll'] for r in results.values());tied=[c for c in candidates if c['id'] in results and results[c['id']]['mean_nll']<=minimum+cfg['selection']['tie_tolerance']]
 winner=min(tied,key=lambda c:(c['depth'],c['rounds'],c['id']))
 return {'selected':winner,'candidate_scores':results,'invalid':invalid,'label_cutoff':cutoff,'tie_policy':cfg['selection']['tie_order']}


def inner_unit(root,out,data,candidate,spec,identity,cfg):
 file=out/'inner'/spec['inner_fold_id']/(candidate['id']+'.json')
 if file.exists():
  r=read_seal(file);s0.require(r['binding']==digest(identity),'Changed inner binding');return r
 cut=label_cutoff(spec['assessment_start']);fm=data.mask(spec['train_start'],cut)&data.available;qm=data.mask(spec['assessment_start'],spec['assessment_end'])&data.available
 s0.require(len(set(data.dates[fm]))>=cfg['selection']['minimum_training_days'],'Insufficient training-day support')
 s0.require(len(set(data.dates[qm]))>=cfg['selection']['minimum_inner_days'],'Insufficient inner support')
 y=data.truth(fm,cut);start=time.monotonic();record={'candidate':candidate,'inner':spec['inner_fold_id'],'binding':digest(identity),'training_cutoff':cut,'fit_days':len(set(data.dates[fm])),'fit_rows':int(fm.sum()),'expected_query_rows':int(data.mask(spec['assessment_start'],spec['assessment_end']).sum()),'available_query_rows':int(qm.sum())}
 try:
  fit=fit_model(data.X[fm],y[fm]-data.offset[fm],data.dates[fm],candidate,cfg);idx=np.where(qm)[0];p,point,diag=predict_chunks(fit,data,idx,cfg)
  truth=data.truth(qm,spec['assessment_end'])[idx].astype(int);q=np.maximum(p,1e-6);q/=q.sum(axis=1,keepdims=True);loss=-np.log(q[np.arange(len(idx)),truth+40]);days=data.dates[idx]
  record.update(status='COMPLETE',daily_nll={d:float(loss[days==d].mean()) for d in sorted(set(days))},diagnostics={k:float(np.mean(v)) for k,v in diag.items()},seconds=time.monotonic()-start,confidence_histogram=np.histogram(p.max(axis=1),bins=np.linspace(0,1,11))[0].tolist(),candidate_artifacts_retained=False)
 except (ValueError,FloatingPointError,np.linalg.LinAlgError) as exc:
  record.update(status='INVALID_MODEL',error=str(exc),seconds=time.monotonic()-start)
 return seal(file,record)


def verify_outer(path,identity):
 u=read_seal(path/'UNIT.json');s0.require(u['binding']==digest(identity),'Outer binding changed')
 for p,h in u['files'].items():s0.require(s0.sha256(path/p)==h,'Changed completed outer artifact')
 return u


def outer_unit(root,out,data,selection,spec,identity,cfg):
 c=selection['selected'];path=out/'outer'/(spec['outer_fold_id']+'_'+c['family'])
 if (path/'UNIT.json').exists():return verify_outer(path,identity)
 path.mkdir(parents=True,exist_ok=True);cut=label_cutoff(spec['assessment_start']);fm=data.mask(spec['train_start'],cut)&data.available;mask=data.mask(spec['assessment_start'],spec['assessment_end']);qm=mask&data.available
 s0.require(len(set(data.dates[fm]))>=cfg['selection']['minimum_training_days'],'Insufficient outer training support');y=data.truth(fm,cut);start=time.monotonic();fit=fit_model(data.X[fm],y[fm]-data.offset[fm],data.dates[fm],c,cfg)
 idx=np.where(qm)[0];p,point,diag=predict_chunks(fit,data,idx,cfg);lookup={j:i for i,j in enumerate(idx)};rows=[]
 for j in np.where(mask)[0]:
  i=lookup.get(j);r=data.meta[j];rows.append({'issue_state_id':r['issue_state_id'],'target_date':r['target_date'],'minutes':r['minutes'],'expected_issues':r['expected_issues'],'model':c['family'],'outer':spec['outer_fold_id'],'training_cutoff':cut,'status':'AVAILABLE' if i is not None else 'ABSTAIN_MISSING_RAW_Q','point_f':float(point[i]) if i is not None else None,'probabilities':p[i].tolist() if i is not None else None,'diagnostics':json.dumps({k:float(v[i]) for k,v in diag.items()}) if i is not None else '{}'})
 joblib.dump(fit,path/'model.joblib',compress=3);save(path/'FIT.json',{'candidate':c,'feature_columns':[n for ns in cfg['features'].values() for n in ns]+['heating_potential'],'input_width_after_missing_indicators':2*data.X.shape[1],'imputer':fit['imputer'],'training_days':sorted(set(data.dates[fm])),'selection':selection,'training_input_hashes':data.loader.input_hashes(),'label_cutoff':cut})
 pq.write_table(pa.Table.from_pylist(rows),path/'predictions.parquet')
 return seal(path/'UNIT.json',{'status':'FROZEN','binding':digest(identity),'candidate':c,'rows':len(rows),'available':len(idx),'seconds':time.monotonic()-start,'assessment_labels_scored':False,'files':{f:s0.sha256(path/f) for f in ['FIT.json','model.joblib','predictions.parquet']}})


def run(root,project,out,status):
 identity=validate(root);cfg=s0.read_json(root/'config.json')
 if (out/'run.json').exists():s0.require(s0.read_json(out/'run.json')==identity,'Changed run binding; create a new run')
 else:save(out/'run.json',identity)
 if (out/'PREDICTION_RELEASE.json').exists():
  r=read_seal(out/'PREDICTION_RELEASE.json')
  for f,h in r['files'].items():s0.require(s0.sha256(out/f)==h,'Changed frozen output')
  status('PREDICTIONS_FROZEN','Existing completed release verified');return
 s0.require(shutil.disk_usage(out).free>=cfg['storage']['minimum_free_gib']*1024**3,'Less than registered 2 GiB free')
 status('LOADING_SHARED_FEATURES');data=Data(root,project,cfg).load(out/'shared');specs=[s for s in data.contract['folds']['inner'] if s['inner_fold_id'] in cfg['selection']['inner_blocks']];allrecords={};times=[];done=0;total=len(specs)*len(cfg['candidates'])+6
 for spec in specs:
  records=[]
  for c in cfg['candidates']:
   status('INNER_TUNING',{'block':spec['inner_fold_id'],'candidate':c['id'],'completed':done,'total':total,'rough_remaining_seconds':float(np.mean(times)*(total-done)) if times else None,'eta_note':'Mixed-family estimate; excludes scoring'})
   r=inner_unit(root,out,data,c,spec,identity,cfg);records.append(r);times.append(r['seconds']);done+=1
   if (out/'PAUSE_REQUESTED').exists():status('PAUSED','Completed units preserved');return
  allrecords[spec['inner_fold_id']]=records
 for spec in data.contract['folds']['outer']:
  cut=label_cutoff(spec['assessment_start']);inner=[s for s in specs if s['assessment_end']<spec['assessment_start']]
  for family in ['XGB_QUANTILE','NGB_NORMAL']:
   cs=[c for c in cfg['candidates'] if c['family']==family];rs=[r for s in inner for r in allrecords[s['inner_fold_id']] if r['candidate']['family']==family];selection=select_candidate(rs,cs,cut,cfg);selection['source_units']={str((Path('inner')/s['inner_fold_id']/(c['id']+'.json'))):s0.sha256(out/'inner'/s['inner_fold_id']/(c['id']+'.json')) for s in inner for c in cs};save(out/'selections'/(spec['outer_fold_id']+'_'+family+'.json'),selection)
   status('OUTER_FIT',{'outer':spec['outer_fold_id'],'selected':selection['selected'],'completed':done,'total':total});outer_unit(root,out,data,selection,spec,identity,cfg);done+=1
   if (out/'PAUSE_REQUESTED').exists():status('PAUSED','Completed units preserved');return
 s0.require(validate(root)==identity,'Changed implementation during run');files={p.relative_to(out).as_posix():s0.sha256(p) for sub in ['inner','outer','selections','shared'] for p in (out/sub).rglob('*') if p.is_file()}
 seal(out/'PREDICTION_RELEASE.json',{'status':'FROZEN','binding':digest(identity),'files':files,'outer_assessment_scores_computed':False,'reserved_labels_read':False,'trading':False});status('PREDICTIONS_FROZEN','Use Score after reviewing completion; no outer tuning')
