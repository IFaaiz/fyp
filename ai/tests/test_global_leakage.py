import unittest
from src.datasets.global_leakage import IdentityRecord as R, build_global_index, identity_from_row


class GlobalLeakageTests(unittest.TestCase):
    def test_origin_cross_source_and_transitive_thread_isolation(self):
        rows = [R('e','enron','ENRON',origin_ids=(('enron_file','mail/1'),)),
                R('m','mailex','ENRON',thread_id='thread-a',origin_ids=(('enron_file','mail/1'),)),
                R('m2','mailex','ENRON',thread_id='thread-a')]
        index = build_global_index(rows)
        self.assertEqual(len({x['leakage_group_id'] for x in index.records.values()}),1)
        self.assertEqual(index.training_exclusions(['e','m2'],['m']),
                         {'e':'protected_component_overlap','m2':'protected_component_overlap'})
        self.assertEqual(len(index.partition_conflicts({'e':'train','m':'test'})),1)

    def test_sentence_copy_is_protected_and_export_has_no_source_text(self):
        sentence='Please deliver the revised project installation estimates before next Friday morning.'
        rows=[R('e','enron','ENRON',body='Hello colleagues. '+sentence+' Thank you for your help.'),
              R('p','parakweet','ENRON',body=sentence,fragment=True)]
        index=build_global_index(rows)
        self.assertEqual(index.records['e']['leakage_group_id'],index.records['p']['leakage_group_id'])
        self.assertEqual(index.training_exclusions(['p'],['e'])['p'],'protected_component_overlap')
        self.assertNotIn(sentence,str(index.export()))

    def test_short_generic_content_and_cross_dataset_thread_ids_do_not_join(self):
        rows=[R('a','enron','ENRON',body='Thanks',thread_id='1'),
              R('b','mailex','ENRON',body='Thanks',thread_id='1')]
        index=build_global_index(rows)
        self.assertNotEqual(index.records['a']['leakage_group_id'],index.records['b']['leakage_group_id'])
        self.assertEqual(index.training_exclusions(['a'],['b'])['a'],
                         'unresolved_origin_or_fragment_in_protected_overlap_family')

    def test_message_id_cross_family_and_order_are_stable(self):
        rows=[R('z','airspace','AIRSPACE',message_id='<ID@host>'),
              R('a','enron','ENRON',message_id='id@host')]
        self.assertEqual(build_global_index(rows).export(),build_global_index(reversed(rows)).export())
        self.assertEqual(build_global_index(rows).records['a']['leakage_group_id'],
                         build_global_index(rows).records['z']['leakage_group_id'])

    def test_fail_closed_unknown_ids_duplicate_ids_and_wrong_origin(self):
        with self.assertRaises(ValueError): R('m','mailex','MAILEx')
        with self.assertRaises(ValueError): build_global_index([R('a','enron','ENRON'),R('a','enron','ENRON')])
        with self.assertRaises(ValueError): build_global_index([]).training_exclusions(['unindexed'],[])

    def test_source_filename_does_not_become_rfc_message_identity(self):
        row=identity_from_row({'source_id':'msg-0.txt','source_message_id':'msg-0.txt','body':'opaque'},'radar_action','RADAR_ACTION')
        self.assertIsNone(row.message_id)
        self.assertEqual(row.record_id,'radar_action:msg-0.txt')

    def test_unverified_simulator_thread_metadata_does_not_group_messages(self):
        rows=[identity_from_row({'source_id':str(i),'source_thread_id':'0',
                                 'thread_id':None,'body':'message '+str(i)},
                                'airspace','AIRSPACE') for i in range(2)]
        self.assertTrue(all(r.thread_id is None for r in rows))
        index=build_global_index(rows)
        self.assertNotEqual(index.records['airspace:0']['leakage_group_id'],
                            index.records['airspace:1']['leakage_group_id'])
        verified=identity_from_row({'source_id':'x','source_thread_id':'real',
                                    'source_thread_verified':True},'cerec','ENRON')
        self.assertEqual(verified.thread_id,'real')

    def test_long_body_containment_survives_removed_signature(self):
        body=' '.join('term'+str(i) for i in range(40))
        index=build_global_index([R('a','enron','ENRON',body=body+' '+ ' '.join('signature'+str(i) for i in range(20))),
                                  R('b','cerec','ENRON',body=body)])
        self.assertEqual(index.records['a']['leakage_group_id'],index.records['b']['leakage_group_id'])

    def test_protected_email_inside_large_quoted_context_is_excluded(self):
        body=' '.join('projectterm'+str(i) for i in range(25))
        context=' '.join('contextterm'+str(i) for i in range(150))+' '+body
        quoted=identity_from_row({'source_id':'quoted','current_message':'Please see below.',
                                 'raw_body':context},'enron','ENRON')
        protected=R('protected','enron','ENRON',body=body)
        index=build_global_index([protected,quoted])
        self.assertEqual(set(index.records),{'protected','enron:quoted'})
        self.assertEqual(index.training_exclusions(['enron:quoted'],['protected']),
                         {'enron:quoted':'protected_component_overlap'})
        self.assertNotIn(body,str(index.export()))

    def test_context_source_and_authored_aliases_are_indexed(self):
        body=' '.join('protectedterm'+str(i) for i in range(30))
        for field in ('source_text','authored_message','original_source_text','source_body'):
            with self.subTest(field=field):
                row=identity_from_row({'source_id':'reply','current_message':'Got it.',
                                       'thread_context':[{field:body}]},'enron','ENRON')
                index=build_global_index([row,R('protected','enron','ENRON',body=body)])
                self.assertIn('enron:reply',index.training_exclusions(['enron:reply'],['protected']))

    def test_long_reconstructed_derivative_still_needs_original_identity(self):
        row=identity_from_row({'source_id':'turn-1','body':' '.join('reconstructed'+str(i) for i in range(80)),
                               'overlap_identity_complete':True},'mailex','ENRON')
        self.assertFalse(row.identity_complete)
        index=build_global_index([row,R('protected','enron','ENRON',origin_ids=(('enron_canonical_id','real'),))])
        self.assertIn(row.record_id,index.training_exclusions([row.record_id],['protected']))


if __name__=='__main__': unittest.main()
