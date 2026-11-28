import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from clipflow.queue import Limit, Queue


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.TemporaryDirectory()
        self.addCleanup(self.root.cleanup)
        self.path = Path(self.root.name) / 'jobs.sqlite3'
        self.queue = Queue(self.path)

    def reserve(self, key):
        return self.queue.reserve(key, 'fixture', json.dumps({}), 8,
                                  cost=3, budget=3, quota=20)

    def test_concurrent_reservations_cannot_overspend(self):
        def try_reserve(key):
            try:
                return self.reserve(key)
            except Limit:
                return None
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(try_reserve, map(str, range(8))))
        self.assertEqual(sum(bool(result) for result in results), 1)

    def test_restart_reclaims_expired_lease_and_fences_old_worker(self):
        job_id, created = self.reserve('same')
        self.assertTrue(created)
        self.assertEqual(self.reserve('same'), (job_id, False))
        self.queue.uploaded(job_id)
        first = self.queue.claim(now=0)
        restarted = Queue(self.path)
        self.assertIsNone(restarted.claim(now=359))
        second = restarted.claim(now=360)
        self.assertEqual(second['id'], job_id)
        self.assertFalse(self.queue.finish(first, output_bytes=5))
        self.assertTrue(restarted.finish(second, output_bytes=5))
        self.assertEqual(restarted.all()[0]['state'], 'ready')
