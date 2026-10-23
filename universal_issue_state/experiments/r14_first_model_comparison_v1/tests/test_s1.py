import copy,json,math,sys,tempfile,unittest
from datetime import date,datetime,timezone
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from s0 import ContractError
from r14_s1.data import day_weights,kelvin_to_fahrenheit,legal_issue_times,unique_rows
from r14_s1.probability import *
from r14_s1.scoring import *
from r14_s1.forecast import *
CARD=json.loads((ROOT/'config/scorecard.json').read_text())

def mass(values):
    p=np.zeros(161)
    for k,v in values.items():p[k+40]=v
    return p

def record():
    return {'issue_state_id':'i','target_date':date(2023,1,1),'statistical_group_id':'KDEN_DAY_2023-01-01','issue_time_utc':datetime(2023,1,1,17,tzinfo=timezone.utc),'local_minutes_since_0200':480,'issue_count_for_target_day':57,'model_id':'ANEN','outer_fold_id':'OUTER_01','inner_fold_id':None,'status':'AVAILABLE','abstention_reason':None,'probabilities':mass({92:1}).tolist(),'point_f':92.,'baseline_center_f':91.,'training_start':date(2021,1,1),'training_end':date(2022,12,30),'label_cutoff':date(2022,12,30),'configuration_sha256':'a'*64,'code_sha256':'b'*64,'input_hashes_json':json.dumps({'input':'c'*64}),'diagnostics_json':'{}'}

class ProbabilityTests(unittest.TestCase):
    def test_kelvin_conversion(self):self.assertAlmostEqual(float(kelvin_to_fahrenheit(273.15)),32)
    def test_negative_rounding_ties(self):np.testing.assert_array_equal(round_half_away([-2.5,-.5,.5,2.5]),[-3,-1,1,3])
    def test_normal_mass_and_center(self):
        p=normal_pmf(50,2);self.assertAlmostEqual(p.sum(),1);self.assertAlmostEqual(p[90],math.erf(.5/(2*math.sqrt(2))))
    def test_endpoint_accumulation(self):
        self.assertAlmostEqual(normal_pmf(-1000,1)[0],1);self.assertAlmostEqual(normal_pmf(1000,1)[-1],1)
    def test_tiny_upper_tail_preserved(self):self.assertGreater(normal_pmf(0,1)[48],0)
    def test_kernel_translation(self):
        p=residual_kernel_pmf(90,[1,3],[1,3],1)
        np.testing.assert_allclose(p,.25*normal_pmf(91,1)+.75*normal_pmf(93,1))
    def test_invalid_distributions_fail(self):
        for p in [np.zeros(161),np.ones(161),mass({92:float('nan')}),np.r_[[-.1],np.ones(160)/160*1.1]]:
            with self.assertRaises(ContractError):validate_pmf(p)
    def test_mean_median_mode_are_distinct(self):
        s=summarize_pmf(mass({0:.4,1:.35,10:.25}));self.assertEqual(s['mode'],0);self.assertEqual(s['median'],1);self.assertAlmostEqual(s['mean'],2.85)
    def test_modal_tie_chooses_lower(self):self.assertEqual(summarize_pmf(mass({91:.5,92:.5}))['mode'],91)
    def test_explicit_bands_do_not_follow_outcome(self):
        p=mass({91:.2,92:.5,93:.3})
        self.assertAlmostEqual(inclusive_band_probability(p,91,92),.7)
        self.assertAlmostEqual(inclusive_band_probability(p,92,93),.8)
        self.assertEqual(inclusive_band_probability(p,92,92),.5)
    def test_band_arguments_required(self):
        with self.assertRaises(TypeError):inclusive_band_probability(mass({92:1}))
        with self.assertRaises(ContractError):inclusive_band_probability(mass({92:1}),92.0,93)
    def test_both_synthetic_alignments_complete(self):
        p=normal_pmf(92,2)
        for b in CARD['partitions'].values():self.assertAlmostEqual(partition_probabilities(p,b).sum(),1)
    def test_partition_overlap_rejected(self):
        b=copy.deepcopy(CARD['partitions']['pair_even']);b[1]['lower']-=1
        with self.assertRaises(ContractError):partition_probabilities(mass({92:1}),b)
    def test_dst_issue_grid(self):
        self.assertEqual(len(legal_issue_times(date(2023,3,12))),53)
        self.assertEqual(len(legal_issue_times(date(2024,11,3))),57)
        self.assertEqual(len(legal_issue_times(date(2023,3,13))),57)

class ScoringTests(unittest.TestCase):
    def test_hand_calculated_two_point_scores(self):
        p=mass({0:.25,1:.75});r=score_rows(p,[0],['id'],CARD,point=[.75])
        self.assertAlmostEqual(r['discrete_crps_f'][0],.5625)
        self.assertAlmostEqual(r['multiclass_brier'][0],1.125)
        self.assertAlmostEqual(r['negative_log_score'][0],-math.log(.25/(1+159e-6)))
        self.assertEqual(r['modal_integer_hit'][0],0);self.assertEqual(r['within_one'][0],1)
    def test_floor_does_not_change_native_confidence(self):
        r=score_rows(mass({92:1}),[92],['id'],CARD)
        self.assertEqual(r['max_integer_probability'][0],1);self.assertEqual(r['multiclass_brier'][0],0)
        self.assertEqual(r['score_floor_count'][0],160);self.assertGreater(r['negative_log_score'][0],0)
    def test_truth_not_clipped(self):
        for y in [121,-41,92.5]:
            with self.assertRaises(ContractError):score_rows(mass({92:1}),[y],['id'],CARD)
    def test_band_names_are_synthetic(self):
        r=score_rows(mass({92:1}),[92],['id'],CARD)
        self.assertIn('synthetic_pair_odd_modal_hit',r);self.assertFalse(any('kalshi' in k for k in r))
    def test_day_weighting_not_row_weighting(self):
        r=aggregate_scores({'mae':np.array([0,0,9.]),'mean_squared_error':np.array([0,0,9.])},['a','a','b'])
        self.assertEqual(r['mae'],4.5);self.assertAlmostEqual(r['rmse'],math.sqrt(4.5))
    def test_missing_forecasts_not_zero_errors(self):
        r=aggregate_scores({'mae':[2,np.nan]},['a','b'],[True,False]);self.assertEqual(r['mae'],2);self.assertEqual(r['scored_days'],1)
    def test_common_support_same_for_all(self):
        r=paired_common_summary({'a':{'mae':[1,100]},'b':{'mae':[2,np.nan]}},['x','y'],{'a':[True,True],'b':[True,False]}, {'a':['1','2'],'b':['1','2']})
        self.assertEqual(r['a']['mae'],1);self.assertEqual(r['b']['mae'],2)
    def test_paired_key_misalignment_rejected(self):
        with self.assertRaises(ContractError):paired_common_summary({'a':{'mae':[1,2]},'b':{'mae':[2,1]}},['x','y'],{'a':[True,True],'b':[True,True]},{'a':['1','2'],'b':['2','1']})
    def test_secondary_confidence_ranking(self):
        s=selection_summary([.6,.9],[1,0],['a','b'],['1','2'],{'a':1,'b':1},-.5,ranking_scores=[-.2,-1.])
        self.assertEqual(s['admitted_rows'],1);self.assertEqual(s['mean_predicted_hit'],.6)
    def test_weighted_quantile_and_ties(self):
        self.assertEqual(weighted_quantile([1,2,3],[.2,.6,.2],.5),2)
        self.assertEqual(confidence_threshold([.8,.8],['a','b'],{'a':1,'b':1},.1),.8)
    def test_selection_counts_days_and_missing(self):
        s=selection_summary([.9,.8,np.nan,.7],[1,0,np.nan,1],['a','a','b','b'],['1','2','3','4'],{'a':2,'b':2},.8)
        self.assertEqual(s['admitted_rows'],2);self.assertEqual(s['dayweighted_coverage'],.5);self.assertEqual(s['unique_day_coverage'],.5);self.assertEqual(s['hit_rate'],.5)
    def test_no_admission_is_null(self):
        s=selection_summary([.4],[0],['a'],['1'],{'a':1},.9)
        self.assertIsNone(s['hit_rate']);self.assertEqual(s['dayweighted_coverage'],0)
    def test_selection_requires_expected_population(self):
        with self.assertRaises(ContractError):selection_summary([.4],[0],['a'],['1'],{'a':2},.9)
    def test_reliability_bins_include_one(self):
        r=reliability([0.,1.],[0.,1.],['a','b']);self.assertEqual(r['ECE'],0);self.assertEqual(r['bins'][9]['rows'],1)
    def test_reliability_hand_calculation(self):
        r=reliability([.8,.8],[1.,0.],['a','b']);self.assertAlmostEqual(r['calibration_in_the_large'],-.3)
    def test_pit_reproducible_across_calls(self):
        a=score_rows(mass({91:.5,92:.5}),[92],['id'],CARD)['randomized_pit'];b=score_rows(mass({91:.5,92:.5}),[92],['id'],CARD)['randomized_pit']
        np.testing.assert_array_equal(a,b);self.assertGreaterEqual(a[0],.5);self.assertLessEqual(a[0],1)
    def test_duplicate_keys_rejected(self):
        with self.assertRaises(ContractError):unique_rows([{'id':1},{'id':1}],['id'])

class ForecastTests(unittest.TestCase):
    def test_rejects_outcome_field(self):
        r=record();r['y_audited_f']=92
        with self.assertRaises(ContractError):validate_record(r)
    def test_rejects_future_training(self):
        r=record();r['training_end']=date(2023,1,1)
        with self.assertRaises(ContractError):validate_record(r)
    def test_explicit_abstention(self):
        r=record();r.update(status='ABSTAIN',abstention_reason='MISSING_INPUT',probabilities=None,point_f=None);validate_record(r)
    def test_atomic_roundtrip_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'partition';m=publish_partition(p,[record()],['i'],synthetic=True);again,rows=read_partition(p)
            self.assertEqual(m,again);self.assertEqual(rows[0]['probabilities'][132],1)
            with self.assertRaises(ContractError):publish_partition(p,[record()],['i'],synthetic=True)
    def test_incomplete_partition_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ContractError):publish_partition(Path(d)/'p',[record()],['i','missing'],True)
    def test_tampered_prediction_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'p';publish_partition(p,[record()],['i'],True)
            with (p/'predictions.parquet').open('ab') as f:f.write(b'x')
            with self.assertRaises(ContractError):read_partition(p)

if __name__=='__main__':unittest.main()
