"""Guards for the optimization benchmark's evaluation boundaries."""
import unittest
import numpy as np
from src.models.optimization_benchmark import decode,score_probabilities,load_partition,group_components,balanced_folds
from src.models.optimization_runtime import marginal_probabilities

class OptimizationBoundaryTests(unittest.TestCase):
 def test_development_api_cannot_open_test(self):
  with self.assertRaisesRegex(ValueError,'TEST is sealed'):load_partition('test')

 def test_hierarchy_uses_conditional_function_probability(self):
  p=np.array([[.8,0,0,0,0,0,0,0,.49],[.99,0,0,0,0,0,0,0,.51]])
  self.assertEqual(decode(p,mode='hierarchical'),[['MEETING'],['NON_PROJECT']])
  m=score_probabilities([['MEETING'],['NON_PROJECT']],p,mode='hierarchical')
  self.assertEqual(m['macro_f1'],2/9)
  self.assertEqual(m['scope_classification']['accuracy'],1)

 def test_scope_gate_can_be_project_without_any_function(self):
  m=score_probabilities([['MEETING']],np.zeros((1,9)),mode='hierarchical')
  self.assertEqual(m['scope_classification']['project_recall'],1)
  self.assertEqual(m['scope_classification']['unassigned_records'],1)
  self.assertEqual(m['micro_f1'],0)

 def test_ensemble_converts_conditional_scores_before_blending(self):
  conditional=np.array([[.8,0,0,0,0,0,0,0,.25]])
  marginal=marginal_probabilities(conditional,'hierarchical')
  self.assertAlmostEqual(marginal[0,0],.6)
  self.assertEqual(marginal[0,8],.25)
  self.assertEqual(conditional[0,0],.8)

 def test_fitted_lexical_hierarchy_returns_conditional_function(self):
  from src.models.optimization_lexical import make_model
  rows=[{'subject':'Team meeting','authored_message':'Project review meeting tomorrow','labels':['MEETING']},
        {'subject':'Weekly review','authored_message':'Project team meeting agenda','labels':['MEETING']},
        {'subject':'Lunch offer','authored_message':'Discount lunch restaurant promotion','labels':['NON_PROJECT']}]
  model=make_model(profile='word_1_1',algorithm='logistic',c=1,task='hierarchical',use_domain=False).fit(rows)
  p=model.predict_proba(rows)
  self.assertEqual(p.shape,(3,9))
  # MEETING is constant-positive among project training rows. It must stay
  # conditional1 rather than being multiplied by imperfect PROJECT scope.
  np.testing.assert_array_equal(p[:,0],np.ones(3))

 def test_transitive_groups_and_source_qualified_threads_remain_together(self):
  rows=[{'source_dataset':'a','thread_id':'t','snapshot_provenance':{'leakage_group_id':'g1'},'labels':['MEETING']},
        {'source_dataset':'a','thread_id':'t','snapshot_provenance':{'leakage_group_id':'g2'},'labels':['MEETING']},
        {'source_dataset':'a','thread_id':'u','snapshot_provenance':{'leakage_group_id':'g2'},'labels':['DEADLINE']},
        {'source_dataset':'b','thread_id':'t','snapshot_provenance':{'leakage_group_id':'g3'},'labels':['NON_PROJECT']}]
  self.assertEqual(group_components(rows),[[0,1,2],[3]])
  folds=balanced_folds(rows,n=2,seed=1)
  owner={i:k for k,f in enumerate(folds) for i in f}
  self.assertEqual(owner[0],owner[1]);self.assertEqual(owner[1],owner[2])

if __name__=='__main__':unittest.main()
