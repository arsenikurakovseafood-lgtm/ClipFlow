import tempfile
import unittest
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock

from clipflow.campaigns import Campaigns, Conflict
from clipflow.insights import Insights
from clipflow.publishing import process_publication
from clipflow.queue import Queue


class CampaignTests(unittest.TestCase):
    def test_ten_clips_fit_in_three_days(self):
        with tempfile.TemporaryDirectory() as root:
            queue = Queue(Path(root) / 'jobs.sqlite3')
            campaigns = Campaigns(queue)
            start = datetime.now(timezone.utc) + timedelta(hours=1)
            campaign_id = campaigns.create({'name': 'Shorts', 'goal': 'Ten cuts in three days',
                'channel': 'youtube', 'duration_days': 3, 'cadence_days': 1, 'target_clips': 10,
                'budget_cents': 0, 'release_start': start.isoformat()})
            campaigns.transition(campaign_id, 'approve')
            spec = json.dumps({'campaign_id': campaign_id})
            for index in range(10):
                job, _ = queue.reserve(str(index), 'Cut', spec, 4, cost=0, budget=0, quota=100)
                queue.uploaded(job)
                queue.finish(queue.claim(), output_bytes=4)
                campaigns.review_clip(job, 'approved')
            posts = campaigns.snapshot()['posts']
            self.assertEqual(len(posts), 10)
            self.assertEqual(posts[0]['scheduled_at'], start.isoformat())
            self.assertLess(datetime.fromisoformat(posts[-1]['scheduled_at']), start + timedelta(days=3))

    def test_approved_clips_enter_release_queue_once_and_wait_while_paused(self):
        with tempfile.TemporaryDirectory() as root:
            queue = Queue(Path(root) / 'jobs.sqlite3')
            campaigns = Campaigns(queue)
            start = datetime.now(timezone.utc) + timedelta(days=2)
            campaign = campaigns.create({'name': 'Shorts', 'goal': 'Find strong interview clips',
                'channel': 'youtube', 'duration_days': 7, 'cadence_days': 2,
                'budget_cents': 0, 'release_start': start.isoformat()})
            campaigns.transition(campaign, 'approve')
            spec = json.dumps({'campaign_id': campaign})
            ids = []
            for index in range(3):
                job_id, _ = queue.reserve(str(index), 'Clip', spec, 4, cost=0, budget=0, quota=100)
                queue.uploaded(job_id)
                queue.finish(queue.claim(), output_bytes=4)
                ids.append(job_id)
            campaigns.review_clip(ids[0], 'rejected')
            self.assertEqual(campaigns.snapshot()['posts'], [])
            campaigns.review_clip(ids[1], 'approved')
            campaigns.review_clip(ids[1], 'approved')
            campaigns.transition(campaign, 'pause')
            campaigns.review_clip(ids[2], 'approved')
            self.assertEqual([post['state'] for post in campaigns.snapshot()['posts']], ['on_hold'])
            campaigns = Campaigns(Queue(queue.path))
            campaigns.transition(campaign, 'resume')
            posts = campaigns.snapshot()['posts']
            self.assertEqual([post['job_id'] for post in posts], ids[1:])
            self.assertEqual([post['scheduled_at'] for post in posts],
                             [start.isoformat(), (start + timedelta(days=2)).isoformat()])

    def test_youtube_publication_requires_confirmation_and_collects_checkpoints(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            queue = Queue(root / 'jobs.sqlite3')
            campaigns = Campaigns(queue)
            start = datetime.now(timezone.utc) - timedelta(minutes=1)
            campaign = campaigns.create({'name': 'Shorts', 'goal': 'Promote an interview',
                'channel': 'youtube', 'duration_days': 7, 'cadence_days': 1, 'budget_cents': 0,
                'release_start': start.isoformat(), 'publication_mode': 'youtube', 'publication_consent': True})
            campaigns.transition(campaign, 'approve')
            job_id, _ = queue.reserve('fixture', 'Clip', json.dumps({'campaign_id': campaign}),
                                      4, cost=0, budget=0, quota=100)
            queue.uploaded(job_id)
            queue.finish(queue.claim(), output_bytes=4)
            campaigns.review_clip(job_id, 'approved')
            publisher = Mock()
            publisher.upload.side_effect = lambda path, title, approved: 'abcdefghijk' if approved() else None
            self.assertTrue(process_publication(queue, publisher, root))
            self.assertEqual(campaigns.snapshot()['posts'][0]['state'], 'uploaded')
            post_id = campaigns.snapshot()['posts'][0]['id']
            for privacy, wanted in [('private', 'uploaded'), ('public', 'published')]:
                with queue.transaction() as db:
                    db.execute('UPDATE manual_posts SET checked_at=? WHERE id=?', (start.isoformat(), post_id))
                publisher.inspect.return_value = {'status': {'privacyStatus': privacy, 'uploadStatus': 'processed'},
                                                  'statistics': {'viewCount': '300', 'likeCount': '31'}}
                self.assertTrue(process_publication(queue, publisher, root))
                self.assertEqual(campaigns.snapshot()['posts'][0]['state'], wanted)
            with queue.transaction() as db:
                db.execute('UPDATE manual_posts SET reported_at=? WHERE id=?',
                           ((start - timedelta(hours=24)).isoformat(), post_id))
            insights = Insights(queue)
            insights.collect_checkpoint(publisher)
            with queue.transaction() as db:
                checkpoint = db.execute('SELECT source,hours,views,likes FROM post_metrics').fetchone()
            self.assertEqual(tuple(checkpoint), ('youtube', 24, 300, 31))
            self.assertEqual(publisher.upload.call_count, 1)

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
