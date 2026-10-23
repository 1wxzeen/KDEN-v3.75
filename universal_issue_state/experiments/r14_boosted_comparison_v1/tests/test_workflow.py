import sys,json,tempfile,unittest,shutil
from pathlib import Path
from datetime import date,timedelta
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np,pyarrow as pa,pyarrow.parquet as pq
P=Path(__file__).resolve().parents[1];sys.path[:0]=[str(P),str(P/'foundation/src')]
import engine,report,s0
from common import save
from r14_s1.probability import normal_pmf
from r14_s1.scoring import score_rows

class Workflow(unittest.TestCase):
 def fixture(self):
  ds=[str(date(2021,1,1)+timedelta(days=i)) for i in range((date(2025,9,6)-date(2021,1,1)).days+1)];dates=np.repeat(ds,2);n=len(dates);ids=[str(i) for i in range(n)]
  d=SimpleNamespace(dates=dates,ids=ids,available=np.ones(n,bool),offset=np.full(n,80.),X=np.zeros((n,4)),expected=np.full(n,2),meta=[{'target_date':d,'minutes':int(i%2)*480,'expected_issues':2,'issue_state_id':str(i)} for i,d in enumerate(dates)],contract=json.loads((P/'foundation/config/experiment.json').read_text()),loader=SimpleNamespace(input_hashes=lambda:{}))
  d.mask=lambda a,b:(dates>=a)&(dates<=b)
  def truth(mask,cutoff=None):
   if cutoff is not None:self.assertLessEqual(max(dates[mask]),cutoff)
   y=np.full(n,np.nan);y[mask]=80;return y
  d.truth=truth;d.load=lambda *a,**k:d
  return d
 def test_run_freeze_score_resume_tamper(self):
  d=self.fixture();identity={'synthetic':True};calls=[]
  def fit(X,y,days,c,cfg):calls.append(c['id']);return {'candidate':c,'imputer':{},'model':'synthetic'}
  def pred(fit,data,idx,cfg):return np.tile(normal_pmf(80.,2.),(len(idx),1)),np.full(len(idx),80.),{}
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp)/'root';out=Path(tmp)/'out';root.mkdir();out.mkdir();(root/'foundation/config').mkdir(parents=True);(root/'benchmarks').mkdir();shutil.copy(P/'config.json',root/'config.json');shutil.copy(P/'foundation/config/scorecard.json',root/'foundation/config/scorecard.json')
   with patch.object(engine,'validate',return_value=identity),patch.object(engine,'Data',return_value=d),patch.object(engine,'fit_model',side_effect=fit),patch.object(engine,'predict_chunks',side_effect=pred):
    engine.run(root,root,out,lambda *x:None);self.assertEqual(len(calls),66);self.assertTrue((out/'PREDICTION_RELEASE.json').exists());self.assertFalse((out/'SCORE_RELEASE.json').exists());engine.run(root,root,out,lambda *x:None);self.assertEqual(len(calls),66)
   mask=d.dates>='2023-01-01';idx=np.where(mask)[0];p,point,_=pred({},d,idx,{});sc=json.loads((P/'foundation/config/scorecard.json').read_text());v=score_rows(p,np.full(len(idx),80),[d.ids[i] for i in idx],sc,point);arts={}
   for b in ['B0_H','B0_Q']:
    f=root/'benchmarks'/(b+'_row_scores.parquet');pq.write_table(pa.table({'issue_state_id':[d.ids[i] for i in idx],**v}),f);arts[f.name]=s0.sha256(f)
   save(root/'benchmarks/SOURCE_S5_RELEASE.json',{'artifacts':arts})
   with patch.object(report,'validate',return_value=identity),patch.object(report,'Data',return_value=d),patch.object(report,'block_weights',side_effect=lambda days,*x:np.ones((10,len(days)))):report.score(root,root,out,lambda *x:None)
   self.assertTrue((out/'REPORT.md').exists());self.assertEqual(len(json.loads((out/'PRIMARY_COMPARISONS.json').read_text())),5)
   f=next((out/'outer').glob('*/predictions.parquet'));f.write_bytes(b'changed')
   with patch.object(engine,'validate',return_value=identity):
    with self.assertRaises(Exception):engine.run(root,root,out,lambda *x:None)
 def test_score_requires_freeze(self):
  with tempfile.TemporaryDirectory() as tmp,patch.object(report,'validate',return_value={}):
   with self.assertRaises(FileNotFoundError):report.score(P,P,Path(tmp),lambda *x:None)
if __name__=='__main__':unittest.main()
