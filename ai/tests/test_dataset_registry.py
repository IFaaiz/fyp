import unittest
from copy import deepcopy
from src.datasets.registry import validate_registry, require_training_source


class RegistryGatesTests(unittest.TestCase):
    def setUp(self):
        self.row={'dataset_name':'MailEx','dataset_id':'mailex','version':'fixture',
                  'official_source':'https://example.invalid/fixture','download_url':None,
                  'origin_corpus':'Enron','overlap_family':'ENRON','license':{'status':'fixture'},
                  'redistribution_allowed':None,'raw_text_allowed_in_git':False,
                  'intended_component':['events'],'original_labels':['Request_Action'],
                  'mapping_policy':{'fyp_labels_generated':False},'checksum':None,
                  'download_date':None,'local_path':None,'status':'source_review_pending',
                  'training_permitted':False}

    def test_research_pending_is_valid_but_cannot_train(self):
        registry={'datasets':[self.row]}
        self.assertEqual(validate_registry(registry),[])
        with self.assertRaises(ValueError):require_training_source(registry,'mailex')

    def test_bad_overlap_and_automatic_fyp_mapping_fail(self):
        self.row['overlap_family']='MAILEx';self.row['mapping_policy']['fyp_labels_generated']=True
        self.assertEqual(len(validate_registry({'datasets':[self.row]})),2)

    def test_source_license_and_code_license_do_not_bypass_integration(self):
        self.row.update(status='integrated_auxiliary',training_permitted=True)
        self.assertGreater(len(validate_registry({'datasets':[self.row]})),1)

    def test_no_raw_text_in_git_and_duplicate_ids(self):
        self.row['raw_text_allowed_in_git']=True
        errors=validate_registry({'datasets':[self.row,deepcopy(self.row)]})
        self.assertTrue(any('duplicate' in e for e in errors))
        self.assertTrue(any('Git-ignored' in e for e in errors))

    def test_malformed_permission_identity_and_checksum_fail_closed(self):
        self.row['dataset_id'] = ['not', 'a', 'string']
        self.assertTrue(validate_registry({'datasets': [self.row]}))
        self.row['dataset_id'] = 'mailex'
        self.row['redistribution_allowed'] = 1
        self.row.update(status='integrated_auxiliary', training_permitted=True,
                        checksum={'algorithm': 'sha256', 'files': [{'path': 'fixture', 'sha256': 'invalid'}]})
        errors = validate_registry({'datasets': [self.row]})
        self.assertTrue(any('permission' in e for e in errors))
        self.assertTrue(any('checksum at index' in e for e in errors))
        with self.assertRaises(ValueError):
            require_training_source({'datasets': [self.row]}, 'mailex')


if __name__=='__main__':unittest.main()
