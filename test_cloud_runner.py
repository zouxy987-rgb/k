import os,tempfile,unittest
from unittest.mock import patch,MagicMock
from cloud_runner import evaluate,send_email
TARGETS=['first@example.test','second@example.test']
class CloudTests(unittest.TestCase):
    def test_transport_exception_fails_closed(self):
        with patch('cloud_runner.collect',side_effect=OSError('DNS failed')):
            report,raw=evaluate(1793700000)
        self.assertEqual(report['status'],'FAIL');self.assertIsNone(raw)
    def test_missing_smtp_not_success(self):
        with patch.dict(os.environ,{},clear=True):
            with self.assertRaises(RuntimeError):send_email('test','test')
    def test_recipient_refusal_not_success_and_deduplicated(self):
        smtp=MagicMock();smtp.send_message.return_value={TARGETS[1]:(550,b'rejected')}
        with tempfile.TemporaryDirectory() as p,patch.dict(os.environ,{'SMTP_USER':'test@example.com','SMTP_APP_PASSWORD':'TEST_ONLY','MAIL_TO':','.join(TARGETS)},clear=True),patch('cloud_runner.smtplib.SMTP_SSL',return_value=smtp):
            r=send_email('test','test','test-key',p)
            self.assertFalse(r['submitted_to_smtp']);self.assertEqual(r['accepted_recipients'],[TARGETS[0]])
            again=send_email('test','test','test-key',p)
            self.assertTrue(again['duplicate_suppressed']);self.assertEqual(smtp.send_message.call_count,1)
    def test_uncertain_submission_not_blindly_retried(self):
        smtp=MagicMock();smtp.send_message.side_effect=OSError('connection lost after DATA')
        with tempfile.TemporaryDirectory() as p,patch.dict(os.environ,{'SMTP_USER':'test@example.com','SMTP_APP_PASSWORD':'TEST_ONLY','MAIL_TO':','.join(TARGETS)},clear=True),patch('cloud_runner.smtplib.SMTP_SSL',return_value=smtp):
            r=send_email('test','test','test-key',p);self.assertTrue(r['delivery_uncertain'])
            self.assertTrue(send_email('test','test','test-key',p)['duplicate_suppressed'])
if __name__=='__main__':unittest.main()
