"""Validate S1 or run its fixed four-day development-only data-access probe."""
import argparse,hashlib,json,sys
from collections import Counter
from pathlib import Path
from unittest.mock import patch
import s0
from r14_s1 import data


def validate(experiment,project,require_release=True):
    e=Path(experiment);p=Path(project)
    previous=s0.validate(e,p)
    c=s0.read_json(e/'config/s1_foundation.json')
    s0.exact_schema(c,s0.read_json(e/'schemas/s1_foundation.schema.json'))
    s0.require(s0.sha256(e/'manifests/S0_RELEASE.json')==c['parent_s0_release_sha256'],'S0 release parent changed')
    for rel,expected in [(c['truth_accessor']['source_path'],c['truth_accessor']['source_sha256']),(c['source_catalog_builder'],c['source_catalog_builder_sha256'])]:
        s0.require(s0.sha256(s0.safe_path(p,rel))==expected,'S1 input/source provenance changed')
    if require_release:
        record=s0.read_json(e/'manifests/S1_RELEASE.json');s0.check_record(record)
        for name,h in record['artifact_hashes'].items():s0.require(s0.sha256(s0.safe_path(e,name))==h,'S1 artifact changed: '+name)
        s0.require(record['status']=='S1_COMPLETE_S2_READY','Unexpected S1 status')
    return {'status':'VALID','stage':'S1','s0_status':previous['status'],'parent_s0_unchanged':True,'synthetic_bands_are_market_listings':False,'source_ledger_identity_verified':True,'model_fits_performed':0,'validation_outcome_values_read':0}


def probe(experiment,project):
    e=Path(experiment);c=s0.read_json(e/'config/s1_foundation.json')
    dates=c['probe_dates'];s0.require(len(dates)<=c['probe_limit_days'],'Probe too broad')
    loader=data.DevelopmentLoader(project,e);calls=[];original=data.read_dates
    def guarded(path,columns,requested):
        rel=Path(path).resolve().relative_to(Path(project).resolve()).as_posix()
        s0.require(all(data.as_date(d) in {data.as_date(x) for x in dates} for d in requested),'Probe requested unregistered date')
        if rel==c['truth_accessor']['catalog']:s0.require('y_audited_f' not in columns,'Catalog outcome decode forbidden')
        if 'y_audited_f' in columns:s0.require(rel==c['truth_accessor']['source_path'],'Unauthorized outcome source')
        calls.append({'path':rel,'columns':columns,'requested_dates':[str(d) for d in requested]})
        return original(path,columns,requested)
    batches=[]
    with patch.object(data,'read_dates',guarded):
        for model in ['B0_H','B0_Q','ANEN','GAM_LS_NORMAL']:
            b=loader.load_features(model,'OUTER_03',dates=dates)
            batches.append({'model_id':model,'rows':len(b.metadata),'columns':len(b.columns),'available_rows':int(b.available.sum()),'missing_rows':int((~b.available).sum()),'rows_by_day':dict(Counter(str(d) for d in b.dates))})
        y=loader.training_labels(b)
        s0.require(len(y)==224,'Unexpected probe label row count')
    return {'status':'PASS','stage':'S1','probe_type':'bounded_loader_check_not_model_evaluation','days':len(dates),'batches':batches,'unique_audited_training_labels_returned':len(set(b.dates)),'returned_training_label_rows':len(y),'returned_label_values_printed_or_persisted':False,'catalog_outcome_column_read':False,'reserved_or_tail_outcome_source_reads':0,'source_physical_decode_note':c['truth_accessor']['source_physical_scope'],'model_fits_performed':0,'model_scores_computed':0,'access_log':calls}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['validate','probe'])
    parser.add_argument('--project-root',type=Path,required=True)
    args=parser.parse_args();e=Path(__file__).resolve().parent.parent
    try:
        result=validate(e,args.project_root)
        if args.command=='probe':result=probe(e,args.project_root)
        print(json.dumps(result,indent=2,sort_keys=True));return 0
    except (s0.ContractError,OSError,KeyError,ValueError) as exc:
        print(json.dumps({'status':'INVALID','reason':str(exc)}));return 1

if __name__=='__main__':sys.exit(main())
