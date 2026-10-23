"""Instrument S0 validation and reject non-allowlisted Parquet data-page reads."""
import argparse
import json
from pathlib import Path
from unittest.mock import patch
import pyarrow.parquet as pq
import s0

def audit(experiment, project):
    original=pq.ParquetFile
    calls=[]
    allowed={'date_roles.parquet':s0.ROLE_COLS,'outer_folds.parquet':s0.FOLD_COLS,'inner_folds.parquet':['inner_fold_id']+s0.FOLD_COLS}
    class Guard:
        def __init__(self,source,*args,**kwargs):
            self.path=Path(source); self.file=original(source,*args,**kwargs)
        def __getattr__(self,name):
            s0.require(name not in ['read_row_group','read_row_groups','iter_batches','scan_contents'],'Unregistered data-page API')
            return getattr(self.file,name)
        def read(self,*args,**kwargs):
            s0.require(self.path.name in allowed,'Forbidden Parquet data decode')
            s0.require(not args and kwargs.get('columns')==allowed[self.path.name],'Non-allowlisted columns')
            calls.append({'file':self.path.name,'columns':kwargs['columns']})
            return self.file.read(**kwargs)
    with patch.object(pq,'ParquetFile',Guard):
        s0.validate(experiment,project)
    s0.require(len(calls)==3,'Unexpected metadata read count')
    return {'status':'PASS','page_reads':calls,'truth_data_page_reads':0,'weather_data_page_reads':0}

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root',type=Path,required=True)
    parser.add_argument('--experiment-root',type=Path,default=Path(__file__).resolve().parents[1])
    args=parser.parse_args()
    print(json.dumps(audit(args.experiment_root,args.project_root),indent=2))
