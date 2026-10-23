from pathlib import Path
import sys,os,unittest
from datetime import date,timedelta
import numpy as np
ROOT=Path(__file__).resolve().parents[1];E=Path(os.environ['R14_EXPERIMENT_ROOT']);sys.path[:0]=[str(ROOT),str(E/'src')]
from core import block_weights,interval,ratio_draws,summarize,selective,regime_labels,reliability
from r14_s1.scoring import confidence_threshold,score_rows
from r14_s1.probability import normal_pmf
import s0

class BootstrapTests(unittest.TestCase):
 def test_calendar_hole_preserved_and_fold_mass(self):
  days=[str(date(2023,1,1)+timedelta(days=i)) for i in range(20) if i!=8]
  folds=[{'assessment_start':'2023-01-01','assessment_end':'2023-01-10'},{'assessment_start':'2023-01-11','assessment_end':'2023-01-20'}]
  W=block_weights(days,folds,7,200,12)
  np.testing.assert_allclose(W[:,:9].sum(axis=1),9);np.testing.assert_allclose(W[:,9:].sum(axis=1),10)
  np.testing.assert_array_equal(W,block_weights(days,folds,7,200,12))
  self.assertEqual(W.shape,(200,19))
 def test_block_length_entire_fold(self):
  days=[str(date(2023,1,1)+timedelta(days=i)) for i in range(7)];W=block_weights(days,[{'assessment_start':days[0],'assessment_end':days[-1]}],7,20)
  np.testing.assert_array_equal(W,np.ones((20,7)))
 def test_paired_constant_difference_exact(self):
  W=np.array([[2,0],[0,2],[1,1]],float);draw=W@np.array([.25,.25])/W.sum(axis=1)
  self.assertEqual(interval(draw)['lower'],.25);self.assertEqual(interval(draw)['upper'],.25)
 def test_undefined_not_zero(self):
  out=interval(np.array([np.nan]*6+[1.]*94));self.assertIsNone(out['lower']);self.assertAlmostEqual(out['undefined_fraction'],.06)
  a=ratio_draws(np.eye(2),np.array([0,1]),np.array([0,1]));self.assertTrue(np.isnan(a[0]));self.assertEqual(a[1],1)

class EstimandTests(unittest.TestCase):
 def fixture(self):
  di=np.array([0,0,1,1]);scores={'mae':np.array([1,3,5,7.]),'mean_squared_error':np.array([1,9,25,49.]),'negative_log_score':np.array([1,2,3,4.]),'modal_integer_hit':np.array([1,1,0,0.]),'discrete_crps_f':np.ones(4),'ae_ge_5':np.array([0,0,1,1.]),'ae_ge_10':np.zeros(4),'event_hit':np.array([1,1,0,0.])};return di,scores
 def test_equal_day_means(self):
  di,s=self.fixture();out=summarize(s,di,np.array([True,False,True,True]));self.assertAlmostEqual(out['metrics']['mae'],3.5)
 def test_population_vs_admitted_day_weight(self):
  di,s=self.fixture();q=np.array([.9,.9,.9,.1]);out=selective(s,q,q,di,np.full(4,2),np.ones(4,bool),.5,np.eye(2),{'baseline':s})
  self.assertAlmostEqual(out['metrics']['event_hit'],2/3);self.assertAlmostEqual(out['equal_admitted_day_hit_rate'],.5);self.assertAlmostEqual(out['dayweighted_coverage'],.75)
  self.assertEqual(out['baselines']['baseline']['event_hit'],out['metrics']['event_hit'])
 def test_no_admission_null(self):
  di,s=self.fixture();out=selective(s,np.zeros(4),np.zeros(4),di,np.full(4,2),np.ones(4,bool),1,np.eye(2),{})
  self.assertIsNone(out['metrics']['event_hit']);self.assertEqual(out['dayweighted_coverage'],0);self.assertEqual(out['intervals']['mae']['undefined_fraction'],1)
 def test_all_ties_admitted(self):
  days=['a','a','b','b'];t=confidence_threshold(np.full(4,.3),days,{'a':2,'b':2},.1);self.assertEqual(t,.3);self.assertTrue(np.all(np.full(4,.3)>=t))
 def test_regime_thresholds_training_only_and_ties(self):
  train=np.array([1.,1,1,1]);minutes=np.zeros(4);labels,rules=regime_labels(np.array([1.,2.,np.nan]),np.zeros(3),train,minutes,np.array([0,0,1,1]),'training_exact_issue_weighted_tertiles')
  self.assertEqual(labels.tolist(),['LOW','HIGH','MISSING']);self.assertEqual(rules['0.0'],[1,1])
 def test_positive_proxy_missing(self):
  labels,_=regime_labels(np.array([0.,.01,np.nan]),np.zeros(3),np.zeros(3),np.zeros(3),np.arange(3),'positive_vs_nonpositive');self.assertEqual(labels.tolist(),['NONPOSITIVE','POSITIVE','MISSING'])
 def test_reliability_weighting(self):
  r=reliability(np.array([.2,.2,.2]),np.array([1.,1.,0.]),np.array([0,0,1]),np.ones(3,bool))
  self.assertAlmostEqual(r['bins'][2]['observed'],.5)
 def test_integer_and_band_are_distinct(self):
  sc={'thresholds_f':[90],'partitions':{'pair':[{'lower':-40,'upper':89},{'lower':90,'upper':91},{'lower':92,'upper':120}]}}
  p=np.zeros((1,161));p[0,130]=.4;p[0,131]=.6;s=score_rows(p,np.array([90]),['id'],sc,point=np.array([91]))
  self.assertEqual(s['modal_integer_hit'][0],0);self.assertEqual(s['synthetic_pair_modal_hit'][0],1)

if __name__=='__main__':unittest.main()
