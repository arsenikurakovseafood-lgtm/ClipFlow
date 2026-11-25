import tempfile
import unittest
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
            campaign.schedule(identifier, payload)
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
