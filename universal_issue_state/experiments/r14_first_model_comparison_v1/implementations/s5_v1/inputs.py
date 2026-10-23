"""Read-only frozen forecast, development truth and predictor access."""
from pathlib import Path
from datetime import date
import json,os,hashlib
import numpy as np
import pyarrow.parquet as pq
import s0
from r14_s1.data import DevelopmentLoader,read_dates,unique_rows,as_date
from r14_s1.probability import summarize_pmf,partition_probabilities
from r14_s1.scoring import weighted_quantile

MODELS=['B0_H','B0_Q','ANEN','GAM_LS_NORMAL','GAM_LOCATION_NORMAL','GAM_LS_T5']
PRIMARY=MODELS[:4]
def digest(v):return hashlib.sha256(s0.canonical(v)).hexdigest()
def clean(v):
    if isinstance(v,dict):return {str(k):clean(x) for k,x in v.items()}
    if isinstance(v,(list,tuple)):return [clean(x) for x in v]
    if isinstance(v,np.ndarray):return clean(v.tolist())
    if isinstance(v,(float,np.floating)):return float(v) if np.isfinite(v) else None
    if isinstance(v,np.integer):return int(v)
    if isinstance(v,np.bool_):return bool(v)
    return v

def save(p,v):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_name(p.name+'.tmp')
    tmp.write_text(json.dumps(clean(v),sort_keys=True,indent=2,allow_nan=False)+'\n');os.replace(tmp,p)

def seal(p,v):v=clean(v);v['record_sha256']=digest(v);save(p,v);return v

def verify_record_file(path,expected=None):
    if expected:s0.require(s0.sha256(path)==expected,'Changed manifest: '+str(path))
    v=s0.read_json(path);s0.check_record(v);return v

class Context:
    def __init__(self,E,root):
        self.E=E;self.R=E.parents[2];self.root=root;self.cfg=s0.read_json(root/'config.json')
        for rel,h in self.cfg['parents'].items():s0.require(s0.sha256(s0.safe_path(E,rel))==h,'S5 parent changed: '+rel)
        self.run=E/self.cfg['s4_run'];self.base=E/self.cfg['s2_run'];self.release=verify_record_file(self.run/'COMPARISON_RELEASE.json')
        s0.require(self.release['status']=='FROZEN' and not self.release['unsupported_models'],'This scorecard is bound to the complete all-model S4 release; incomplete releases need explicit support handling')
        s0.require(digest(s0.read_json(self.run/'run.json'))==self.release['run_binding_sha256'],'S4 run binding changed')
        for rel,h in self.release['artifacts'].items():s0.require(s0.sha256(s0.safe_path(self.run,rel))==h,'S4 artifact changed: '+rel)
        self.brelease=verify_record_file(self.base/'BASELINE_RELEASE.json');self.loader=DevelopmentLoader(self.R,E)
        self.contract=self.loader.contract;self.sc=s0.read_json(E/'config/scorecard.json');self.features=s0.read_json(E/'config/features.json')
        self.checked={};self.conf_cache={};self.authorities={};self.expected={}
    def prediction(self,path,expected_hash=None,columns=None):
        path=Path(path);m=verify_record_file(path/'manifest.json',expected_hash)
        p=path/'predictions.parquet';stat=p.stat();key=str(p);signature=(stat.st_size,stat.st_mtime_ns,m['predictions_sha256'])
        if self.checked.get(key)!=signature:s0.require(s0.sha256(p)==m['predictions_sha256'],'Changed predictions');self.checked[key]=signature
        self.authorities[str(p.relative_to(self.E))]=m['predictions_sha256']
        return m,pq.ParquetFile(p).read(columns=columns).to_pylist()
    def outer(self,oid,model):
        ref=self.release['outer_partitions'][oid+'/'+model];unit=(self.run/ref['path']).resolve()
        s0.require(unit.is_relative_to(self.E/'runs'),'External forecast path')
        cols=['issue_state_id','target_date','issue_time_utc','local_minutes_since_0200','issue_count_for_target_day','status','probabilities','point_f','baseline_center_f','diagnostics_json','training_end','label_cutoff']
        m,rows=self.prediction(unit/'forecast',ref['forecast_manifest_sha256'],cols)
        s0.require(m['predictions_sha256']==ref['predictions_sha256'] and m['model_id']==model and m['outer_fold_id']==oid and m['inner_fold_id'] is None,'Wrong outer partition')
        if oid not in self.expected:
            ds=self.loader.fold_dates(oid,'ASSESS');spine=read_dates(self.loader._input(self.contract['time']['issue_spine_path']),['issue_state_id','target_date','local_minutes_since_0200','issue_count_for_target_day'],ds).to_pylist()
            self.expected[oid]={r['issue_state_id']:(r['target_date'],r['local_minutes_since_0200'],r['issue_count_for_target_day']) for r in spine}
        lookup={r['issue_state_id']:r for r in rows};ex=self.expected[oid]
        s0.require(len(lookup)==len(rows)==len(ex) and set(lookup)==set(ex),'Outer keys incomplete')
        for r in rows:
            s0.require((r['target_date'],r['local_minutes_since_0200'],r['issue_count_for_target_day'])==ex[r['issue_state_id']],'Outer metadata changed')
            s0.require(r['status']=='AVAILABLE','Unexpected missing forecast; stop rather than change support')
            s0.require(r['training_end']<=r['label_cutoff']<r['target_date'],'Fit boundary violation')
        return rows,unit
    def truth(self,dates):
        allowed=set(d for f in self.contract['folds']['outer'] for d in self.loader.fold_dates(f['outer_fold_id'],'ASSESS'))
        s0.require(set(dates)<=allowed,'Only frozen development outer dates can be scored')
        t=self.loader.supplement['truth_accessor'];auth=read_dates(self.loader._input(t['catalog']),t['catalog_authorization_columns'],dates).to_pylist()
        lookup=unique_rows(auth,['target_date']);s0.require(set(lookup)=={(d,) for d in dates},'Missing truth authority')
        for a in auth:s0.require(a['truth_group']=='development' and a['label_available_for_supervised_use'] is True and a['source_artifact_path']==t['source_path'] and a['source_artifact_sha256']==t['source_sha256'],'Unauthorized truth source')
        p=self.loader._input(t['source_path']);sd=pq.ParquetFile(p).read(columns=['target_date'])['target_date'].to_pylist();s0.require(max(sd)<=as_date(t['source_max_date']),'Reserved/tail source prohibited')
        vals=unique_rows(read_dates(p,['target_date','y_audited_f'],dates).to_pylist(),['target_date'])
        s0.require(set(vals)==set(lookup),'Truth key mismatch')
        values={d:vals[(d,)]['y_audited_f'] for d in dates};s0.require(all(type(y) is int and -40<=y<=120 for y in values.values()),'Invalid truth')
        return values
    def selected_inner(self,oid,model):
        """Confidence only; no inner labels. Common support matches sealed family masks."""
        baseline=model.startswith('B0_');select=s0.read_json((self.base/f'{oid}_{model}_selection.json') if baseline else (self.run/f'selections/{oid}_{model}.json'))
        candidate=select['selected'];parts=[]
        specs=[i for i in self.contract['folds']['inner'] if i['assessment_end']<=next(o['train_end'] for o in self.contract['folds']['outer'] if o['outer_fold_id']==oid)]
        for spec in specs:
            iid=spec['inner_fold_id']
            if baseline:
                support=s0.read_json(self.base/f'{oid}_{model}_{iid}_support.json')
                if not support['summary']['included']:continue
                unit=self.base/'units'/f'{oid}_{iid}_{candidate["candidate_id"]}'
                u=verify_record_file(unit/'unit.json',self.brelease['units'][str(unit.relative_to(self.base))])
                manifest_hash=u['forecast_manifest_sha256']
            else:
                block=self.run/'inner'/f'{iid}_{model}';support=s0.read_json(block/'SUPPORT.json')
                if not support['summary']['included']:continue
                unit=block/candidate['candidate_id'];u=verify_record_file(unit/'UNIT.json');s0.require(u['candidate']==candidate,'Selected candidate mismatch');manifest_hash=u['files']['forecast/manifest.json']
            key=str(unit)
            if key not in self.conf_cache:
                m,rows=self.prediction(unit/'forecast',manifest_hash,['issue_state_id','target_date','local_minutes_since_0200','issue_count_for_target_day','status','probabilities','diagnostics_json'])
                ids=[r['issue_state_id'] for r in rows]
                s0.require(digest(ids)==support.get('issue_ids_sha256',support.get('expected_issue_ids_sha256')),'Common-mask key order mismatch')
                common=np.array([r['status']=='AVAILABLE' for r in rows]) if baseline else np.array(support['mask'],bool)
                if baseline:s0.require(digest(common.tolist())==support['mask_sha256'],'Baseline chosen mask differs from common tuning mask')
                chosen=[r for r,k in zip(rows,common) if k];s0.require(all(r['status']=='AVAILABLE' for r in chosen),'Incomplete common inner support')
                p=np.array([r['probabilities'] for r in chosen]);summary=summarize_pmf(p)
                stats={'integer':summary['max_integer_probability'],'negative_entropy':-summary['entropy'],'negative_width80':-summary['width_80'].astype(float)}
                for name,bands in self.sc['partitions'].items():stats[name]=partition_probabilities(p,bands).max(axis=1)
                self.conf_cache[key]={'days':[r['target_date'].isoformat() for r in chosen],'minutes':np.array([r['local_minutes_since_0200'] for r in chosen]),'weights':np.array([1/r['issue_count_for_target_day'] for r in chosen]),'ranks':stats,'diagnostics':[json.loads(r['diagnostics_json']) for r in chosen]}
            parts.append(self.conf_cache[key])
        s0.require(len(parts)>=2,'Insufficient registered inner threshold support')
        out={'days':sum([p['days'] for p in parts],[]),'minutes':np.concatenate([p['minutes'] for p in parts]),'weights':np.concatenate([p['weights'] for p in parts]),'ranks':{k:np.concatenate([p['ranks'][k] for p in parts]) for k in parts[0]['ranks']},'diagnostics':sum([p['diagnostics'] for p in parts],[])}
        s0.require(len(out['days'])==len(set(zip(out['days'],out['minutes']))),'Duplicate inner day/issue')
        return out
    def features_batch(self,oid,split):
        import copy
        loader=DevelopmentLoader(self.R,self.E);loader.features=copy.deepcopy(loader.features)
        names=self.features['sets']['regime_diagnostics']+['q05_local_retained_max','clock_wrfsfcf_cycle_age_minutes','clock_wrfsubhf_cycle_age_minutes']
        loader.features['sets']['B0_Q']=names
        b=loader.load_features('B0_Q',oid,split);self.authorities.update(loader.input_hashes());return b
