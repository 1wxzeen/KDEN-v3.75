"""Focused contract/integrity tests, including negative controls."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from s0 import ContractError,canonical,check_design,check_partitions,check_record,exact_schema,read_json,safe_path

class S0Tests(unittest.TestCase):
    def setUp(self):
        self.c=read_json(ROOT/'config/experiment.json')
        self.f=read_json(ROOT/'config/features.json')
        self.grid=read_json(ROOT/'config/candidates.json')
        self.s=read_json(ROOT/'config/scorecard.json')

    def test_frozen_configuration_accepts(self):
        check_design(self.c,self.f,self.grid,self.s)
        exact_schema(self.c,read_json(ROOT/'schemas/experiment.schema.json'))

    def test_reserved_outcome_access_rejected(self):
        self.c['access']['reserved_outcomes_allowed']=True
        with self.assertRaises(ContractError):check_design(self.c,self.f,self.grid,self.s)

    def test_fitting_authorization_rejected(self):
        self.c['execution']['s0_model_fits_allowed']=True
        with self.assertRaises(ContractError):check_design(self.c,self.f,self.grid,self.s)

    def test_injected_truth_predictor_rejected(self):
        self.f['sets']['GAM'].append('y_audited_f')
        self.f['registry_entries']['y_audited_f']={'name':'y_audited_f'}
        with self.assertRaises(ContractError):check_design(self.c,self.f,self.grid,self.s)

    def test_missing_feature_rejected(self):
        self.f['sets']['ANEN'].append('nonexistent')
        with self.assertRaises(ContractError):check_design(self.c,self.f,self.grid,self.s)

    def test_changed_lag_rejected_by_frozen_schema(self):
        self.c['truth']['publication_lag_target_days']=0
        with self.assertRaises(ContractError):exact_schema(self.c,read_json(ROOT/'schemas/experiment.schema.json'))

    def test_unregistered_configuration_rejected(self):
        self.grid['candidates'].append(copy.deepcopy(self.grid['candidates'][0]))
        self.grid['count']+=1
        with self.assertRaises(ContractError):check_design(self.c,self.f,self.grid,self.s)

    def test_partition_overlap_rejected(self):
        self.s['partitions']['pair_even'][1]['lower']-=1
        with self.assertRaises(ContractError):check_partitions(self.s['partitions'])

    def test_partition_gap_rejected(self):
        self.s['partitions']['pair_odd'][2]['upper']-=1
        with self.assertRaises(ContractError):check_partitions(self.s['partitions'])

    def test_edge_categories_and_inclusive_pair(self):
        self.assertEqual(self.s['partitions']['pair_odd'][0],{'lower':-40,'upper':-40})
        self.assertIn({'lower':91,'upper':92},self.s['partitions']['pair_odd'])
        self.assertEqual(self.s['partitions']['pair_even'][-1],{'lower':120,'upper':120})

    def test_record_tampering_rejected(self):
        record={'status':'PASS'}
        record['record_sha256']=hashlib.sha256(canonical(record)).hexdigest()
        check_record(record)
        record['status']='OTHER'
        with self.assertRaises(ContractError):check_record(record)

    def test_path_escape_and_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'root';root.mkdir()
            with self.assertRaises(ContractError):safe_path(root,'../elsewhere')
            with self.assertRaises(ContractError):safe_path(root,'/etc/passwd')
            (root/'escape').symlink_to(Path(d))
            with self.assertRaises(ContractError):safe_path(root,'escape/file')

    def test_unknown_schema_keywords_fail_closed(self):
        schema=read_json(ROOT/'schemas/experiment.schema.json');schema['not']={}
        with self.assertRaises(ContractError):exact_schema(self.c,schema)

if __name__=='__main__':unittest.main()
