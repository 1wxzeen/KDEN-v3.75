import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from boundaries import cutoff,eligible_dates,assert_eligible,require_forward_lineage

class Boundaries(unittest.TestCase):
 def test_new_year(self):self.assertEqual(str(cutoff('2025-01-01')),'2024-12-30')
 def test_leap_day(self):self.assertEqual(str(cutoff('2024-03-01')),'2024-02-28')
 def test_include_cutoff_exclude_late(self):self.assertEqual(eligible_dates(['2024-12-29','2024-12-30','2024-12-31'],'2025-01-01','2021-01-01','2025-09-06'),['2024-12-29','2024-12-30'])
 def test_reserved_still_forbidden(self):
  with self.assertRaises(ValueError):assert_eligible(['2025-09-07'],'2026-01-01','2021-01-01','2025-09-06')
 def test_duplicate_fails(self):
  with self.assertRaises(ValueError):eligible_dates(['2023-01-01']*2,'2024-01-01','2021-01-01','2025-09-06')
 def fixture(self):return {'target_date':'2025-01-01','allowed_start':'2021-01-01','allowed_end':'2025-09-06',**{k:{'first_assessment_date':'2025-01-01','label_dates':['2024-12-30']} for k in ('base_fit','base_selection','preprocessing','reliability_fit','threshold_fit')}}
 def test_all_stages_valid(self):self.assertTrue(require_forward_lineage(self.fixture()))
 def test_each_stage_rejects_late_label(self):
  for stage in ('base_fit','base_selection','preprocessing','reliability_fit','threshold_fit'):
   with self.subTest(stage=stage):
    row=self.fixture();row[stage]['label_dates']=['2024-12-31']
    with self.assertRaises(ValueError):require_forward_lineage(row)
 def test_future_decision_rejected(self):
  row=self.fixture();row['base_selection']['first_assessment_date']='2025-01-02'
  with self.assertRaises(ValueError):require_forward_lineage(row)
if __name__=='__main__':unittest.main()
