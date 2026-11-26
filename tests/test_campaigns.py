import tempfile
import unittest
import json
from pathlib import Path

from clipflow.campaigns import Campaigns, Conflict
from clipflow.queue import Queue


class CampaignTests(unittest.TestCase):
    def test_review_pause_resume_handoff_and_restart(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'jobs.sqlite3'
            queue = Queue(path)
            campaign = Campaigns(queue)
            job_id, _ = queue.reserve('fixture', 'Fixture clip', '{}', 4, cost=0, budget=0, quota=8)
            queue.uploaded(job_id)
            queue.finish(queue.claim(), output_bytes=4)
            identifier = campaign.create({'name': 'Test release', 'goal': 'Release a music teaser',
                                          'channel': 'youtube', 'duration_days': 10,
                                          'cadence_days': 3, 'budget_cents': 250})
            payload = {'job_id': job_id, 'scheduled_at': '2020-01-01T12:00:00+02:00'}
            self.assertEqual(campaign.snapshot()['campaigns'][0]['planned_posts'], 4)
            with self.assertRaises(Conflict):
                campaign.schedule(identifier, payload)
            campaign.transition(identifier, 'approve')
            with self.assertRaises(Conflict):
                campaign.schedule(identifier, payload)
            campaign.review_clip(job_id, 'approved')
            campaign.schedule(identifier, payload)
            with self.assertRaises(Conflict):
                campaign.review_clip(job_id, 'rejected')
            with self.assertRaises(Conflict):
                campaign.schedule(identifier, payload)
            item = campaign.snapshot()['posts'][0]
            self.assertEqual(item['scheduled_at'], '2020-01-01T10:00:00+00:00')
            campaign.transition(identifier, 'pause')
            campaign = Campaigns(Queue(path))
            self.assertEqual(campaign.snapshot()['posts'][0]['state'], 'on_hold')
            with self.assertRaises(Conflict):
                campaign.complete(item['id'])
            campaign.transition(identifier, 'resume')
            campaign.complete(item['id'])
            campaign.transition(identifier, 'stop')
            self.assertEqual(campaign.snapshot()['posts'][0]['state'], 'handed_off')
            with self.assertRaises(Conflict):
                campaign.transition(identifier, 'resume')

    def test_linked_jobs_follow_campaign_pause_and_stop(self):
        with tempfile.TemporaryDirectory() as root:
            queue = Queue(Path(root) / 'jobs.sqlite3')
            campaigns = Campaigns(queue)
            identifier = campaigns.create({'name': 'Preview', 'goal': 'Test pause', 'channel': 'youtube',
                                           'duration_days': 3, 'cadence_days': 1, 'budget_cents': 0})
            campaigns.transition(identifier, 'approve')
            job_id, _ = queue.reserve('fixture', 'Linked', json.dumps({'campaign_id': identifier}),
                                      4, cost=0, budget=0, quota=8)
            queue.uploaded(job_id)
            campaigns.transition(identifier, 'pause')
            self.assertIsNone(queue.claim())
            campaigns.transition(identifier, 'resume')
            queue.control(True)
            self.assertTrue(Queue(queue.path).control()['paused'])
            self.assertIsNone(queue.claim())
            queue.control(False)
            job = queue.claim()
            self.assertEqual(job['id'], job_id)
            campaigns.transition(identifier, 'stop')
            self.assertFalse(queue.finish(job, output_bytes=4))
            self.assertEqual(queue.get(job_id)['state'], 'cancelled')

    def test_campaign_transcription_cap_is_shared_by_its_jobs(self):
        with tempfile.TemporaryDirectory() as root:
            queue = Queue(Path(root) / 'jobs.sqlite3')
            campaigns = Campaigns(queue)
            identifier = campaigns.create({'name': 'Promo', 'goal': 'Test paid cap', 'channel': 'youtube',
                                           'duration_days': 3, 'cadence_days': 1, 'budget_cents': 0,
                                           'transcription_budget': 9000})
            campaigns.transition(identifier, 'approve')
            for index, amount in enumerate((6000, 4500, 3000)):
                job_id, _ = queue.reserve(str(index), 'Linked', json.dumps({'campaign_id': identifier}),
                                          4, cost=0, budget=0, quota=100)
                queue.uploaded(job_id)
                job = queue.claim()
                self.assertEqual(queue.reserve_transcription(job, amount, 15000), index != 1)
                queue.finish(job, output_bytes=4)
