import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from uuid import uuid4
from unittest.mock import Mock

from clipflow.campaigns import Campaigns, Conflict
from clipflow.insights import Insights, recommendations
from clipflow.queue import Limit, Queue


class InsightsTests(unittest.TestCase):
    def test_reported_post_updates_and_confirmed_cash_excludes_pending(self):
        with tempfile.TemporaryDirectory() as root:
            queue = Queue(Path(root) / 'jobs.sqlite3')
            campaigns, insights = Campaigns(queue), Insights(queue)
            clip, _ = queue.reserve('fixture', 'Clip', '{}', 10, cost=0, budget=0, quota=100)
            queue.uploaded(clip)
            queue.finish(queue.claim(), output_bytes=10)
            campaigns.review_clip(clip, 'approved')
            campaign = campaigns.create({'name': 'A', 'goal': 'Track results', 'channel': 'youtube',
                                         'duration_days': 3, 'cadence_days': 1, 'budget_cents': 0})
            campaigns.transition(campaign, 'approve')
            campaigns.schedule(campaign, {'job_id': clip, 'scheduled_at': '2025-01-01T00:00:00+00:00'})
            post = campaigns.snapshot()['posts'][0]['id']
            with self.assertRaises(Conflict):
                insights.record_metrics(post, {'hours': 24, 'views': 100})
            campaigns.complete(post)
            with self.assertRaises(ValueError):
                campaigns.report_post(post, {'url': 'https://www.instagram.com/reel/fixture/'})
            campaigns.report_post(post, {'url': 'https://www.youtube.com/shorts/abcdefghijk'})
            opener = Mock()
            opener.open.return_value = BytesIO(b'{"items":[{"id":"abcdefghijk","statistics":{"viewCount":"70"}}]}')
            insights.read_youtube(post, 'fixture-key', opener)
            with self.assertRaises(Limit):
                insights.read_youtube(post, 'fixture-key', opener)
            request = opener.open.call_args.args[0]
            self.assertEqual(request.host, 'www.googleapis.com')
            self.assertNotIn('fixture-key', request.full_url)
            insights.record_metrics(post, {'hours': 24, 'views': 100})
            insights.record_metrics(post, {'hours': 24, 'views': 120, 'clicks': 3})
            key = str(uuid4())
            payment = {'key': key, 'kind': 'affiliate', 'cents': 800, 'note': 'Receipt', 'state': 'pending'}
            insights.add_entry(payment)
            insights.add_entry(payment)
            snapshot = insights.snapshot()
            self.assertEqual(len(snapshot['metrics']), 1)
            self.assertEqual(snapshot['metrics'][0]['views'], 120)
            self.assertIsNone(snapshot['metrics'][0]['likes'])
            self.assertEqual(snapshot['youtube'][0]['views'], 70)
            self.assertIsNone(snapshot['youtube'][0]['comments'])
            self.assertEqual(snapshot['totals']['pending']['income'], 800)
            self.assertEqual(snapshot['totals']['confirmed']['income'], 0)
            insights.confirm_entry(key)
            self.assertEqual(insights.snapshot()['totals']['confirmed']['income'], 800)

    def test_suggestions_require_comparable_clips_and_reported_clicks(self):
        common = dict(campaign_id='campaign', campaign='Campaign', hours=24, views=200, conversions=None)
        observations = [dict(common, creative='question', clicks=12) for _ in range(3)]
        observations += [dict(common, creative='statement', clicks=2) for _ in range(3)]
        self.assertEqual(recommendations(observations[:-1]), [])
        decision = recommendations(observations)[0]
        self.assertEqual((decision['candidate'], decision['measure'], decision['rate']), ('question', 'clicks', 0.06))
