"""Guard source reservation against prior exposure and nonreproducible sampling."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SCRIPT=Path(__file__).resolve().parents[1]/'scripts/prepare_structured_candidate_reservoir.py'
spec=importlib.util.spec_from_file_location('structured_candidates',SCRIPT)
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


class StructuredCandidateTests(unittest.TestCase):
    def test_collects_ids_from_nested_values_and_map_keys(self):
        first='enron-'+'a'*24;second='enron-'+'b'*24;found=set()
        module.collect_ids({'ids':[first],'decisions':{second:{'label':'MEETING'}},
                            'text':'Sentence mentioning '+first},found)
        self.assertEqual(found,{first,second})

    def test_sampling_excludes_exposed_ids_and_retains_private_views(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'source.jsonl'
            rows=[{'email_id':'enron-'+format(i,'024x'),'current_message':'current content '*10,
                   'raw_body':'raw view '+str(i),'labels':['MEETING'],'subject':'source'} for i in range(15)]
            path.write_text('\n'.join(json.dumps(r) for r in rows),encoding='utf-8')
            excluded={rows[0]['email_id'],rows[1]['email_id']}
            a,stats,history=module.sample_candidates(path,excluded,8,2026)
            b,_,_=module.sample_candidates(path,excluded,8,2026)
            self.assertEqual(a,b)
            self.assertFalse({r['email_id'] for r in a}&excluded)
            self.assertEqual({r['source_id'] for r in history},excluded)
            self.assertTrue(all(r['fyp_labels'] is None and r['structured_annotation'] is None for r in a))
            self.assertTrue(all('labels' not in r for r in a))
            self.assertEqual(stats['historical_ids_missing_from_full_source'],0)
            self.assertEqual(stats['eligible_unseen_rows'],13)

    def test_shortage_and_missing_source_identity_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'source.jsonl';path.write_text('',encoding='utf-8')
            with self.assertRaises(ValueError):module.sample_candidates(path,set(),2,1)
            path.write_text(json.dumps({'email_id':'guessed','current_message':'x'*200}),encoding='utf-8')
            with self.assertRaises(ValueError):module.sample_candidates(path,set(),2,1)


if __name__=='__main__':unittest.main()
