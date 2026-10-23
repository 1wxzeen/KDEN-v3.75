"""Outcome-free prediction schema, lineage and immutable partition publication."""
from datetime import date,datetime,timedelta
from pathlib import Path
import hashlib,json,os,tempfile,shutil
from zoneinfo import ZoneInfo
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import s0
from .probability import validate_pmf

FIELDS={'issue_state_id','target_date','statistical_group_id','issue_time_utc','local_minutes_since_0200','issue_count_for_target_day','model_id','outer_fold_id','inner_fold_id','status','abstention_reason','probabilities','point_f','baseline_center_f','training_start','training_end','label_cutoff','configuration_sha256','code_sha256','input_hashes_json','diagnostics_json'}

def validate_record(r):
    s0.require(set(r)==FIELDS,'Forecast fields differ; outcomes and extra fields forbidden')
    s0.require(r['model_id'] in ['B0_H','B0_Q','ANEN','GAM_LS_NORMAL','GAM_LOCATION_NORMAL','GAM_LS_T5'],'Unknown model')
    s0.require(type(r['target_date']) is date and isinstance(r['issue_time_utc'],datetime) and r['issue_time_utc'].utcoffset()==timedelta(0),'Forecast time types')
    s0.require(all(type(r[k]) is date for k in ['training_start','training_end','label_cutoff']),'Training dates')
    s0.require(r['training_start']<=r['training_end']<=r['label_cutoff']<=r['target_date']-timedelta(days=2),'Noncausal training lineage')
    local=r['issue_time_utc'].astimezone(ZoneInfo('America/Denver'))
    s0.require(local.date()==r['target_date'] and local.minute%15==0 and local.second==0 and local.microsecond==0 and local.hour*60+local.minute-120==r['local_minutes_since_0200'],'Issue clock mismatch')
    s0.require(r['statistical_group_id']=='KDEN_DAY_'+r['target_date'].isoformat(),'Statistical group mismatch')
    s0.require(r['issue_count_for_target_day'] in [53,57] and r['local_minutes_since_0200'] in range(0,841,15),'Invalid issue metadata')
    for k in ['configuration_sha256','code_sha256']:
        s0.require(isinstance(r[k],str) and len(r[k])==64 and all(c in '0123456789abcdef' for c in r[k]),'Invalid lineage hash')
    hashes=json.loads(r['input_hashes_json']);s0.require(isinstance(hashes,dict) and hashes,'Missing input lineage')
    s0.require(all(isinstance(v,str) and len(v)==64 and all(c in '0123456789abcdef' for c in v) for v in hashes.values()),'Bad input hash')
    diagnostics=json.loads(r['diagnostics_json']);s0.require(isinstance(diagnostics,dict),'Diagnostics must be object')
    s0.require(not any(any(x in k.lower() for x in ['truth','y_audited','settlement','actual_tmax']) for k in diagnostics),'Outcome-bearing diagnostic key')
    if r['status']=='AVAILABLE':
        validate_pmf(r['probabilities'])
        s0.require(np.ndim(r['probabilities'])==1 and r['abstention_reason'] is None,'Available forecast status')
        s0.require(r['point_f'] is not None and np.isfinite(r['point_f']),'Missing named point')
    else:
        s0.require(r['status']=='ABSTAIN' and isinstance(r['abstention_reason'],str) and r['abstention_reason'],'Invalid abstention')
        s0.require(r['probabilities'] is None and r['point_f'] is None,'Abstention contains forecast')
    s0.require(r['baseline_center_f'] is None or np.isfinite(r['baseline_center_f']),'Nonfinite baseline center')


def prediction_schema():
    return pa.schema([
      pa.field('issue_state_id',pa.string(),False),pa.field('target_date',pa.date32(),False),pa.field('statistical_group_id',pa.string(),False),pa.field('issue_time_utc',pa.timestamp('us',tz='UTC'),False),pa.field('local_minutes_since_0200',pa.int16(),False),pa.field('issue_count_for_target_day',pa.int16(),False),pa.field('model_id',pa.string(),False),pa.field('outer_fold_id',pa.string(),False),pa.field('inner_fold_id',pa.string()),pa.field('status',pa.string(),False),pa.field('abstention_reason',pa.string()),pa.field('probabilities',pa.list_(pa.float64())),pa.field('point_f',pa.float64()),pa.field('baseline_center_f',pa.float64()),pa.field('training_start',pa.date32(),False),pa.field('training_end',pa.date32(),False),pa.field('label_cutoff',pa.date32(),False),pa.field('configuration_sha256',pa.string(),False),pa.field('code_sha256',pa.string(),False),pa.field('input_hashes_json',pa.string(),False),pa.field('diagnostics_json',pa.string(),False)
    ],metadata={b'schema_version':b'R14_S1_FORECAST_V1',b'band_semantics':b'PMF only; no inferred market bands'})


def publish_partition(destination,records,expected_issue_ids,synthetic=False):
    """Publish one model/fold partition atomically; no overwriting or partial key sets."""
    destination=Path(destination)
    s0.require(not destination.exists(),'Prediction partition already exists')
    rows=list(records);s0.require(rows,'Empty prediction partition')
    for r in rows:validate_record(r)
    keys=[r['issue_state_id'] for r in rows]
    expected=list(expected_issue_ids)
    s0.require(len(set(keys))==len(keys) and len(set(expected))==len(expected) and set(keys)==set(expected),'Missing/duplicate/unexpected prediction keys')
    identity={(r['model_id'],r['outer_fold_id'],r['inner_fold_id'],r['configuration_sha256'],r['code_sha256'],r['training_start'],r['training_end'],r['label_cutoff'],r['input_hashes_json']) for r in rows}
    s0.require(len(identity)==1,'Mixed model/fit identities in partition')
    rows.sort(key=lambda r:(r['target_date'],r['issue_time_utc']))
    destination.parent.mkdir(parents=True,exist_ok=True)
    scratch=Path(tempfile.mkdtemp(prefix='.prediction-',dir=destination.parent))
    try:
        pq.write_table(pa.Table.from_pylist(rows,schema=prediction_schema()),scratch/'predictions.parquet')
        manifest={'schema_version':'R14_S1_PREDICTION_PARTITION_V1','rows':len(rows),'model_id':rows[0]['model_id'],'outer_fold_id':rows[0]['outer_fold_id'],'inner_fold_id':rows[0]['inner_fold_id'],'synthetic':bool(synthetic),'expected_issue_ids_sha256':hashlib.sha256(s0.canonical(sorted(expected))).hexdigest(),'predictions_sha256':s0.sha256(scratch/'predictions.parquet'),'configuration_sha256':rows[0]['configuration_sha256'],'code_sha256':rows[0]['code_sha256'],'input_hashes':json.loads(rows[0]['input_hashes_json']),'truth_included':False}
        manifest['record_sha256']=hashlib.sha256(s0.canonical(manifest)).hexdigest()
        (scratch/'manifest.json').write_text(json.dumps(manifest,sort_keys=True,indent=2)+'\n')
        # Atomic mkdir claims the destination, then files move into it; manifest moved last.
        destination.mkdir()
        os.replace(scratch/'predictions.parquet',destination/'predictions.parquet')
        os.replace(scratch/'manifest.json',destination/'manifest.json')
        return manifest
    finally:
        shutil.rmtree(scratch)


def read_partition(directory):
    directory=Path(directory);m=s0.read_json(directory/'manifest.json');s0.check_record(m)
    s0.require(s0.sha256(directory/'predictions.parquet')==m['predictions_sha256'],'Prediction bytes changed')
    rows=pq.ParquetFile(directory/'predictions.parquet').read().to_pylist()
    s0.require(len(rows)==m['rows'],'Prediction count changed')
    for r in rows:validate_record(r)
    ids=[r['issue_state_id'] for r in rows]
    s0.require(len(ids)==len(set(ids)),'Duplicate prediction keys')
    s0.require(hashlib.sha256(s0.canonical(sorted(ids))).hexdigest()==m['expected_issue_ids_sha256'],'Prediction identities changed')
    return m,rows
