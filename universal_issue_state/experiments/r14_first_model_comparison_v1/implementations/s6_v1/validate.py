from pathlib import Path
import json,hashlib,argparse
from boundaries import assert_eligible
P=Path(__file__).resolve().parent

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def validate(E):
 c=json.loads((P/'registration.json').read_text());r=json.loads((P/'RELEASE.json').read_text())
 for rel,h in r['files'].items():
  if sha(P/rel)!=h:raise ValueError('Changed S6 file: '+rel)
 for rel,h in c['parents'].items():
  if sha(E/rel)!=h:raise ValueError('Changed parent: '+rel)
 assert c['status']=='REGISTERED_NOT_FITTED' and not c['scope']['model_fits_performed']
 assert len(c['models'])*len(c['base_models'])==6
 for b in c['historical_blocks']:
  assert b['fit'][0]<=b['fit'][1]<b['threshold'][0]<=b['threshold'][1]<b['assessment'][0]<=b['assessment'][1]
  assert_eligible(b['fit'],b['threshold'][0],*c['evidence']['historical_allowed'])
  assert_eligible(b['threshold'],b['assessment'][0],*c['evidence']['historical_allowed'])
  assert b['assessment'][1]<=c['evidence']['historical_allowed'][1]
 p=c['prospective_reservation'];assert c['created_utc']<p['readiness_deadline']<p['target_start']<p['target_end']
 assert p['status']=='RESERVED_NOT_ACTIVATED' and not p['collection_authorized_by_S6']
 return {'status':'PASS','registered_candidates':6,'scheduled_historical_fits':12,'model_fits_performed':0,'new_truth_values_read':0,'prospective_status':p['status'],'frozen_runners_modified':False}
if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--experiment-root',type=Path,default=P.parents[1]);a=parser.parse_args()
 print(json.dumps(validate(a.experiment_root),indent=2))
