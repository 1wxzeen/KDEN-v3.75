"""Independent tiny Parquet fixtures test data-boundary failures without real outcomes."""
from datetime import date,datetime,time,timedelta,timezone
from pathlib import Path
import hashlib,json,shutil,sys,tempfile,unittest
from unittest.mock import patch
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from s0 import ContractError,sha256
from r14_s1 import data

class LoaderTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.project=Path(self.tmp.name)/'project';self.e=Path(self.tmp.name)/'experiment'
        for folder in ['config','schemas','manifests']:
            shutil.copytree(ROOT/folder,self.e/folder)
        self.paths=[]
        self.train=date(2022,12,30);self.lag=date(2022,12,31);self.assess=date(2023,1,1);self.unresolved=date(2021,3,19);self.reserved=date(2025,9,7)
        roles=[]
        for d in [self.train,self.lag,self.assess,self.unresolved,self.reserved]:
            roles.append({'target_date':d,'statistical_group_id':'day_'+str(d),'evidence_role':'DEVELOPMENT_UNRESOLVED' if d==self.unresolved else 'SEALED_HOLDOUT' if d==self.reserved else 'DEVELOPMENT_SUPERVISED','supervised_eligible':d not in [self.unresolved,self.reserved]})
        self.write('folds/kden_v375/v1/date_roles.parquet',roles)
        folds=[{'outer_fold_id':'OUTER_01','target_date':r['target_date'],'statistical_group_id':r['statistical_group_id'],'assignment':'ASSESS' if r['target_date']==self.assess else 'TRAIN' if r['supervised_eligible'] else 'EXCLUDED','supervised_assignment':r['supervised_eligible']} for r in roles]
        self.write('folds/kden_v375/v1/outer_folds.parquet',folds)
        spine=[];cycles=[];features={2022:[],2023:[]}
        for d in [self.train,self.assess]:
            for i,t in enumerate(data.legal_issue_times(d)):
                rid=f'{d}_{i}';cycle=(t-timedelta(hours=2)).replace(minute=0);minute=i*15
                r={'issue_state_id':rid,'target_date':d,'statistical_group_id':'day_'+str(d),'issue_time_utc':t,'local_minutes_since_0200':minute,'issue_count_for_target_day':57,'target_window_start_utc':datetime.combine(d,time(7),timezone.utc),'target_window_end_utc':datetime.combine(d+timedelta(days=1),time(7),timezone.utc)};spine.append(r)
                for product in ['wrfsfcf','wrfsubhf']:
                    cycles.append({'issue_state_id':rid,'target_date':d,'issue_time_utc':t,'product':product,'selection_status':'SELECTED','cycle_init_utc':cycle,'emulated_complete_time_utc':cycle+timedelta(minutes=105),'previous_cycle_init_utc':cycle-timedelta(hours=1),'previous_emulated_complete_time_utc':cycle-timedelta(hours=1)+timedelta(minutes=105)})
                features[d.year].append({'issue_state_id':rid,'target_date':d,'statistical_group_id':r['statistical_group_id'],'issue_time_utc':t,'wrfsfcf_cycle_init_utc':cycle,'wrfsubhf_cycle_init_utc':cycle,'q05_local_retained_max':300.0})
        self.write('universal_issue_state/v1/issue_spine/issue_spine.parquet',spine)
        self.write('universal_issue_state/v1/selected_cycles/selected_cycles.parquet',cycles)
        for y,rows in features.items():self.write(f'universal_issue_state/v1/deterministic_features/target_year={y}/part-{y}.parquet',rows)
        supplement=json.loads((self.e/'config/s1_foundation.json').read_text());ledger=supplement['truth_accessor']['source_path']
        self.write(ledger,[{'target_date':self.train,'y_audited_f':92},{'target_date':self.assess,'y_audited_f':93}])
        digest=sha256(self.project/ledger);supplement['truth_accessor']['source_sha256']=digest
        self.write(supplement['truth_accessor']['catalog'],[{'target_date':d,'truth_group':'development' if d!=self.reserved else 'sealed_final_holdout','label_available_for_supervised_use':d!=self.reserved,'source_artifact_path':ledger,'source_artifact_sha256':digest,'y_audited_f':-999 if d==self.reserved else 111} for d in [self.train,self.assess,self.reserved]])
        (self.e/'config/s1_foundation.json').write_text(json.dumps(supplement));schema=json.loads((self.e/'schemas/s1_foundation.schema.json').read_text());schema['const']=supplement;(self.e/'schemas/s1_foundation.schema.json').write_text(json.dumps(schema))
        self.refresh()

    def write(self,rel,rows):
        p=self.project/rel;p.parent.mkdir(parents=True,exist_ok=True);pq.write_table(pa.Table.from_pylist(rows),p)
        if rel not in self.paths:self.paths.append(rel)

    def refresh(self):
        (self.e/'manifests/input_inventory.json').write_text(json.dumps({'files':[{'path':p,'sha256':sha256(self.project/p)} for p in self.paths]}))

    def loader(self):return data.DevelopmentLoader(self.project,self.e)

    def test_training_load_and_catalog_value_not_read(self):
        loader=self.loader();seen=[];original=data.read_dates
        def guard(path,columns,dates):
            if 'catalog' in str(path):self.assertNotIn('y_audited_f',columns)
            seen.append((str(path),list(columns)));return original(path,columns,dates)
        with patch.object(data,'read_dates',guard):
            b=loader.load_features('B0_Q','OUTER_01');y=loader.training_labels(b)
        self.assertEqual(len(y),57);self.assertTrue(np.all(y==92));self.assertNotIn('y_audited_f',b.columns)
        self.assertAlmostEqual(b.weights.sum(),1)
        self.assertTrue(seen)

    def test_lag_day_rejected(self):
        with self.assertRaises(ContractError):self.loader().load_features('B0_Q','OUTER_01',dates=[self.lag])
    def test_reserved_date_rejected_before_features(self):
        with self.assertRaises(ContractError):self.loader().load_features('B0_Q','OUTER_01',dates=[self.reserved])
    def test_unresolved_date_rejected(self):
        with self.assertRaises(ContractError):self.loader().load_features('B0_Q','OUTER_01',dates=[self.unresolved])
    def test_assessment_features_no_training_label_access(self):
        loader=self.loader();b=loader.load_features('B0_Q','OUTER_01','ASSESS')
        with self.assertRaises(ContractError):loader.training_labels(b)
    def test_missing_input_explicit(self):
        rel='universal_issue_state/v1/deterministic_features/target_year=2022/part-2022.parquet'
        rows=pq.ParquetFile(self.project/rel).read().to_pylist();rows[0]['q05_local_retained_max']=None;self.write(rel,rows);self.refresh()
        b=self.loader().load_features('B0_Q','OUTER_01');self.assertFalse(b.available[0]);self.assertEqual(b.missing_features[0],('q05_local_retained_max',));self.assertEqual(b.weights[0],0)
    def test_feature_join_mismatch(self):
        rel='universal_issue_state/v1/deterministic_features/target_year=2022/part-2022.parquet';rows=pq.ParquetFile(self.project/rel).read().to_pylist();rows[0]['statistical_group_id']='wrong';self.write(rel,rows);self.refresh()
        with self.assertRaises(ContractError):self.loader().load_features('B0_Q','OUTER_01')
    def test_duplicate_feature_key(self):
        rel='universal_issue_state/v1/deterministic_features/target_year=2022/part-2022.parquet';rows=pq.ParquetFile(self.project/rel).read().to_pylist();rows.append(rows[0]);self.write(rel,rows);self.refresh()
        with self.assertRaises(ContractError):self.loader().load_features('B0_Q','OUTER_01')
    def test_future_cycle_rejected(self):
        rel='universal_issue_state/v1/selected_cycles/selected_cycles.parquet';rows=pq.ParquetFile(self.project/rel).read().to_pylist();rows[0]['emulated_complete_time_utc']=rows[0]['issue_time_utc']+timedelta(minutes=1);self.write(rel,rows);self.refresh()
        with self.assertRaises(ContractError):self.loader().load_features('B0_Q','OUTER_01')
    def test_modified_input_hash_rejected(self):
        rel='universal_issue_state/v1/deterministic_features/target_year=2022/part-2022.parquet'
        with (self.project/rel).open('ab') as f:f.write(b'x')
        with self.assertRaises(ContractError):self.loader().load_features('B0_Q','OUTER_01')
    def test_catalog_source_hash_mismatch_rejected(self):
        rel='truth/kden_tmax/v1/catalog/kden_truth_catalog.parquet';rows=pq.ParquetFile(self.project/rel).read().to_pylist();rows[0]['source_artifact_sha256']='0'*64;self.write(rel,rows);self.refresh()
        loader=self.loader();b=loader.load_features('B0_Q','OUTER_01')
        with self.assertRaises(ContractError):loader.training_labels(b)

if __name__=='__main__':unittest.main()
