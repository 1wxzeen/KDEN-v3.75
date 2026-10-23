import sys,os,json,tempfile,unittest
from pathlib import Path
from datetime import date,timedelta
from unittest.mock import patch
from types import SimpleNamespace
import numpy as np
P=Path(__file__).resolve().parents[1];E=Path(os.environ['R14_EXPERIMENT_ROOT'])
sys.path[:0]=[str(P),str(E/'src'),str(E/'implementations/s6_v1'),str(E/'implementations/s5_v1'),str(E/'implementations/s3_v1')]
import runner,report
from model import design
from inputs import save

class Workflow(unittest.TestCase):
 def fixture(self):
  reg=json.loads((E/'implementations/s6_v1/registration.json').read_text());ds=[str(date(2023,1,1)+timedelta(days=i)) for i in range((date(2025,9,6)-date(2023,1,1)).days+1)];dates=np.repeat(ds,2);n=len(dates);minutes=np.tile([0,480],len(ds));truth={date.fromisoformat(d):60+i%3 for i,d in enumerate(ds)};weather={f['column']:np.ones(n) for f in reg['weather_features']};base={};designs={}
  for m in ['ANEN','GAM_LS_NORMAL','B0_H','B0_Q']:
   integers=np.array([60+(i//2)%3+(i%2==0) for i in range(n)]);base[m]={'native':np.full(n,.7),'integer':integers,'median':integers}
   if m in reg['base_models']:designs[m],_=design(base[m]['native'],minutes,np.sin(np.arange(n)/100),np.cos(np.arange(n)/100),weather,reg)
  d={'dates':dates,'ids':[str(i) for i in range(n)],'common':np.ones(n,bool),'expected':np.full(n,2),'minutes':minutes,'base':base,'designs':designs,'input_hashes':{}}
  return reg,d,truth
 def test_full_freeze_score_resume_and_tamper(self):
  reg,d,truth=self.fixture();access=[];ctx=SimpleNamespace(authorities={},truth=lambda ds:{x:truth[x] for x in ds})
  def labels(ctx,data,mask,first,reg):
   from boundaries import assert_eligible
   ds=sorted(set(data['dates'][mask]));assert_eligible(ds,first,*reg['evidence']['historical_allowed']);access.append((ds,first));y=np.full(len(mask),np.nan)
   for i in np.where(mask)[0]:y[i]=truth[date.fromisoformat(data['dates'][i])]
   return y
  identity={'synthetic':True}
  with tempfile.TemporaryDirectory() as tmp:
   out=Path(tmp);save(out/'run.json',identity)
   with patch.object(runner,'validate',return_value=identity),patch.object(runner,'Context',return_value=ctx),patch.object(runner,'certificate',return_value={'fit_lineage_units':[],'synthetic':True}),patch.object(runner,'load',return_value=d),patch.object(runner,'labels',side_effect=labels):
    runner.run(E,P,out,lambda *x:None);self.assertEqual(len(access),12);self.assertTrue((out/'PREDICTION_RELEASE.json').exists());self.assertFalse((out/'SCORE_RELEASE.json').exists())
    runner.run(E,P,out,lambda *x:None);self.assertEqual(len(access),12)
   with patch.object(report,'validate',return_value=identity),patch.object(report,'Context',return_value=ctx),patch.object(report,'block_weights',side_effect=lambda days,*a:np.ones((10,len(days)))):
    report.score(E,P,out,lambda *x:None)
   self.assertTrue((out/'REPORT.md').exists());self.assertEqual(len(json.loads((out/'RELIABILITY_SCORES.json').read_text())),8)
   pred=next((out/'units').glob('*/predictions.parquet'));pred.write_bytes(b'changed')
   with patch.object(runner,'validate',return_value=identity):
    with self.assertRaises(Exception):runner.run(E,P,out,lambda *x:None)
 def test_score_rejects_unfrozen_run(self):
  with tempfile.TemporaryDirectory() as tmp,patch.object(report,'validate',return_value={}):
   with self.assertRaises(FileNotFoundError):report.score(E,P,Path(tmp),lambda *x:None)

if __name__=='__main__':unittest.main()
