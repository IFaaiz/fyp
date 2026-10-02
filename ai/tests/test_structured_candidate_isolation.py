import importlib.util
import unittest
from pathlib import Path
from src.datasets.global_leakage import build_global_index,identity_from_row

SCRIPT=Path(__file__).resolve().parents[1]/'scripts/isolate_structured_candidates.py'
spec=importlib.util.spec_from_file_location('isolate_candidates',SCRIPT)
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


def packet(sid,body):
    return {'source_id':sid,'current_message':body}


class IsolationTests(unittest.TestCase):
    def test_history_and_all_reserved_components_are_protected(self):
        old=' '.join('oldproject'+str(i) for i in range(40))
        new=' '.join('newproject'+str(i) for i in range(40))
        unused=' '.join('unusedproject'+str(i) for i in range(40))
        unique=' '.join('trainingproject'+str(i) for i in range(40))
        history=[packet('historical',old)]
        reserved=[packet('old-copy',old),packet('new-eval',new),packet('unused-reserve',unused)]
        train=[packet('eval-copy',new),packet('unused-copy',unused),packet('train-ok',unique)]
        index=build_global_index(identity_from_row(r,'enron','ENRON') for r in history+reserved+train)
        selected,retained,bad_reserved,bad_train,assignments,count=module.select_isolated(index,train,reserved,history,1)
        self.assertEqual([r['source_id'] for r in selected],['new-eval'])
        self.assertEqual([r['source_id'] for r in retained],['train-ok'])
        self.assertEqual(set(bad_train),{'enron:eval-copy','enron:unused-copy'})
        self.assertIn('enron:old-copy',bad_reserved)
        self.assertEqual(index.partition_conflicts(assignments),[])

    def test_unindexed_sources_and_reservation_shortage_fail_closed(self):
        index=build_global_index([])
        with self.assertRaises(ValueError):module.select_isolated(index,[],[packet('unknown','x')],[],1)
        with self.assertRaises(ValueError):module.select_isolated(index,[],[],[],1)


if __name__=='__main__':unittest.main()
