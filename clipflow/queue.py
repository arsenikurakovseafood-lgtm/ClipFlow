"""Persistent single-owner demo queue. Monetary units are integer micro-euros."""
import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone

from clipflow.batch import R2_IMPORT_FAILED
from clipflow.youtube import ACCESS_REFUSED

REPLACEABLE_BATCH = """state='failed' AND source_removed=0 AND finished_at>?
    AND json_extract(spec,'$.batch')=1 AND error IN (?,?)
    AND (json_extract(spec,'$.campaign_id') IS NULL OR EXISTS
        (SELECT 1 FROM campaigns c WHERE c.id=json_extract(jobs.spec,'$.campaign_id') AND c.state<>'stopped'))"""


def source_retention_seconds():
    return max(1, int(os.environ.get('CLIPFLOW_SOURCE_RETENTION_HOURS', '24'))) * 3600


def replacement_window():
    return time.time() - source_retention_seconds(), ACCESS_REFUSED, R2_IMPORT_FAILED


def workloads_paused(db):
    return bool(db.execute('SELECT paused FROM workspace_control WHERE singleton=1').fetchone()[0])


def audit(db, event, subject):
    db.execute('INSERT INTO workspace_audit (event,subject,created_at) VALUES (?,?,?)',
               (event, subject, datetime.now(timezone.utc).isoformat()))


class Limit(Exception):
    pass


class Queue:
    def __init__(self, path):
        self.path = path
        with self.transaction() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, request_key TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL, spec TEXT NOT NULL,
                state TEXT NOT NULL DEFAULT 'uploading',
                month TEXT NOT NULL, reserved INTEGER NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0, lease_until REAL,
                lease_token TEXT, error TEXT, elapsed REAL, bytes INTEGER NOT NULL,
                output_bytes INTEGER
            )""")

            columns = {row['name'] for row in db.execute('PRAGMA table_info(jobs)')}
            if 'finished_at' not in columns:
                db.execute('ALTER TABLE jobs ADD COLUMN finished_at REAL')
                db.execute("UPDATE jobs SET finished_at=? WHERE state IN ('ready','failed')", (time.time(),))
            if 'source_removed' not in columns:
                db.execute('ALTER TABLE jobs ADD COLUMN source_removed INTEGER NOT NULL DEFAULT 0')
            if 'review' not in columns:
                db.execute("ALTER TABLE jobs ADD COLUMN review TEXT NOT NULL DEFAULT 'pending'")
            db.execute("""CREATE TABLE IF NOT EXISTS transcription_usage (
                job_id TEXT PRIMARY KEY, month TEXT NOT NULL, micro_usd INTEGER NOT NULL,
                captions TEXT
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS campaigns (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, goal TEXT NOT NULL,
                channel TEXT NOT NULL, duration_days INTEGER NOT NULL,
                cadence_days INTEGER NOT NULL, budget_cents INTEGER NOT NULL,
                state TEXT NOT NULL, created_at TEXT NOT NULL
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS workspace_control (
                singleton INTEGER PRIMARY KEY CHECK(singleton=1), paused INTEGER NOT NULL
            )""")
            db.execute('INSERT OR IGNORE INTO workspace_control VALUES (1,0)')
            db.execute("""CREATE TABLE IF NOT EXISTS workspace_audit (
                event TEXT NOT NULL, subject TEXT NOT NULL, created_at TEXT NOT NULL
            )""")

    def control(self, pause=None):
        with self.transaction() as db:
            current = workloads_paused(db)
            if pause is not None and pause != current:
                db.execute('UPDATE workspace_control SET paused=? WHERE singleton=1', (pause,))
                audit(db, 'workloads_paused' if pause else 'workloads_resumed', 'workspace')
            events = [dict(row) for row in db.execute('SELECT * FROM workspace_audit ORDER BY rowid DESC LIMIT 20')]
            return {'paused': current if pause is None else pause, 'events': events}

    def bind_owner(self, owner_id):
        with self.transaction() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS owner_binding (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1), owner_id TEXT NOT NULL
            )""")
            db.execute('INSERT OR IGNORE INTO owner_binding VALUES (1,?)', (owner_id,))
            actual = db.execute('SELECT owner_id FROM owner_binding WHERE singleton=1').fetchone()
            if actual['owner_id'] != owner_id:
                raise ValueError('This workspace is already bound to a different owner')

    def cached_captions(self, job_id):
        with self.transaction() as db:
            row = db.execute('SELECT captions FROM transcription_usage WHERE job_id=?',
                             (job_id,)).fetchone()
            return json.loads(row['captions']) if row and row['captions'] is not None else None

    def reserve_transcription(self, job, cost, budget):
        month = datetime.now(timezone.utc).strftime('%Y-%m')
        with self.transaction() as db:
            if workloads_paused(db):
                return False
            current = db.execute("SELECT 1 FROM jobs WHERE id=? AND lease_token=? AND state='running'",
                                 (job['id'], job['lease_token'])).fetchone()
            attempted = db.execute('SELECT 1 FROM transcription_usage WHERE job_id=?',
                                   (job['id'],)).fetchone()
            used = db.execute('SELECT COALESCE(SUM(micro_usd),0) FROM transcription_usage WHERE month=?',
                              (month,)).fetchone()[0]
            if not current or attempted or used + cost > budget:
                return False
            db.execute('INSERT INTO transcription_usage (job_id,month,micro_usd) VALUES (?,?,?)',
                       (job['id'], month, cost))
            return True

    def save_captions(self, job, cues):
        with self.transaction() as db:
            db.execute("""UPDATE transcription_usage SET captions=? WHERE job_id=? AND
                EXISTS (SELECT 1 FROM jobs WHERE id=? AND lease_token=? AND state='running')""",
                (json.dumps([asdict(cue) for cue in cues]), job['id'], job['id'], job['lease_token']))

    @contextmanager
    def transaction(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            db.execute('BEGIN IMMEDIATE')
            with db:
                yield db
        finally:
            db.close()

    def reserve(self, key, name, spec, size, *, cost, budget, quota):
        month = datetime.now(timezone.utc).strftime('%Y-%m')
        with self.transaction() as db:
            old = db.execute('SELECT id FROM jobs WHERE request_key=?', (key,)).fetchone()
            if old:
                return old['id'], False
            campaign_id = json.loads(spec).get('campaign_id')
            if campaign_id and not db.execute("SELECT 1 FROM campaigns WHERE id=? AND state='active'",
                                               (campaign_id,)).fetchone():
                raise Limit('Approve or resume the campaign before rendering')
            spending = db.execute('SELECT COALESCE(SUM(reserved),0) FROM jobs WHERE month=?',
                                  (month,)).fetchone()[0]
            storage = db.execute('SELECT COALESCE(SUM(bytes),0) FROM jobs').fetchone()[0]
            if spending + cost > budget or storage + size > quota:
                raise Limit('Demo render budget or source storage quota exhausted')
            job_id = uuid.uuid4().hex
            db.execute("""INSERT INTO jobs (id,request_key,name,spec,month,reserved,bytes)
                          VALUES (?,?,?,?,?,?,?)""", (job_id, key, name, spec, month, cost, size))
            return job_id, True

    def get(self, job_id):
        with self.transaction() as db:
            row = db.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
            return dict(row) if row else None

    def uploaded(self, job_id, spec=None):
        with self.transaction() as db:
            return bool(db.execute("""UPDATE jobs SET state='queued',spec=COALESCE(?,spec)
                WHERE id=? AND state='uploading'""", (spec, job_id)).rowcount)

    def can_replace_batch_source(self, job_id):
        with self.transaction() as db:
            return db.execute(f'SELECT 1 FROM jobs WHERE id=? AND {REPLACEABLE_BATCH}',
                              (job_id, *replacement_window())).fetchone() is not None

    def replace_batch_source(self, job_id, folder, *, staged=None, source_url=None):
        with self.transaction() as db:
            changed = db.execute(f"""UPDATE jobs SET state='queued', attempts=0, error=NULL,
                finished_at=NULL, lease_token=NULL, lease_until=NULL,
                spec=json_set(spec,'$.source_url',?) WHERE id=? AND {REPLACEABLE_BATCH}""",
                (source_url, job_id, *replacement_window())).rowcount
            if changed:
                if staged is not None:
                    staged.replace(folder / 'source')
                else:
                    (folder / 'source').unlink(missing_ok=True)
            return bool(changed)

    def abandon(self, job_id):
        with self.transaction() as db:
            db.execute("DELETE FROM jobs WHERE id=? AND state='uploading'", (job_id,))

    def claim(self, now=None):
        now = time.time() if now is None else now
        with self.transaction() as db:
            if workloads_paused(db):
                return None
            db.execute("""UPDATE jobs SET state='failed', error='Worker lease expired twice', finished_at=?, spec=json_remove(spec,'$.source_url')
                          WHERE state='running' AND lease_until<=? AND attempts>=2""", (now, now))
            job = db.execute("""SELECT * FROM jobs
                WHERE (state='queued' OR (state='running' AND lease_until<=?))
                AND (json_extract(spec,'$.campaign_id') IS NULL OR EXISTS
                    (SELECT 1 FROM campaigns c WHERE c.id=json_extract(jobs.spec,'$.campaign_id') AND c.state='active'))
                ORDER BY rowid LIMIT 1""", (now,)).fetchone()
            if not job:
                return None
            token = uuid.uuid4().hex
            spec = json.loads(job['spec'])
            lease_seconds = 600 if spec.get('automatic_captions') or spec.get('storage') == 'r2' or spec.get('batch') else 360
            db.execute("""UPDATE jobs SET state='running', attempts=attempts+1,
                          lease_until=?, lease_token=? WHERE id=?""", (now + lease_seconds, token, job['id']))
            return dict(job, lease_token=token)

    def finish(self, job, *, error=None, elapsed=None, output_bytes=None):
        with self.transaction() as db:
            return bool(db.execute("""UPDATE jobs SET state=?, error=?, elapsed=?,output_bytes=?,finished_at=?,
                spec=json_remove(spec,'$.source_url')
                WHERE id=? AND lease_token=? AND state='running'""",
                ('failed' if error else 'ready', error, elapsed, output_bytes, time.time(),
                 job['id'], job['lease_token'])).rowcount)

    def expand_batch(self, job, children, max_bytes, detail):
        with self.transaction() as db:
            changed = db.execute("""UPDATE jobs SET state='prepared',error=?,finished_at=?,
                bytes=bytes-?,spec=json_remove(spec,'$.source_url') WHERE id=? AND lease_token=? AND state='running'""",
                (detail, time.time(), 2 * max_bytes * (json.loads(job['spec'])['count'] - len(children)),
                 job['id'], job['lease_token'])).rowcount
            if not changed:
                return False
            db.executemany("""INSERT INTO jobs (id,request_key,name,spec,state,month,reserved,bytes)
                VALUES (?,?,?,?,'queued',?,0,0)""",
                [(clip_id, clip_id, name, json.dumps(spec), job['month'])
                 for clip_id, name, spec in children])
            return True

    def expiring(self, source_cutoff, output_cutoff):
        with self.transaction() as db:
            # Retire the clip before deletion. An interrupted cleanup can be retried.
            db.execute("""UPDATE jobs SET state='expired'
                WHERE state IN ('ready','failed','prepared','cancelled') AND finished_at<=?
                  AND NOT EXISTS (SELECT 1 FROM jobs AS child
                    WHERE json_extract(child.spec,'$.batch_parent')=jobs.id
                    AND child.state IN ('queued','running','ready','failed'))""", (output_cutoff,))
            return [dict(row) for row in db.execute("""SELECT id, spec, lease_token, state
                FROM jobs WHERE (state='expired' AND (bytes>0 OR source_removed=0))
                    OR (state IN ('ready','failed','prepared','cancelled') AND source_removed=0 AND finished_at<=?
                        AND NOT EXISTS (SELECT 1 FROM jobs AS child
                        WHERE json_extract(child.spec,'$.batch_parent')=jobs.id
                        AND child.state IN ('queued','running')))
                ORDER BY finished_at LIMIT 100""", (source_cutoff,))]

    def reclaimed(self, job, source_bytes):
        with self.transaction() as db:
            if job['state'] == 'expired':
                db.execute("UPDATE jobs SET bytes=0,source_removed=1 WHERE id=? AND state='expired'",
                           (job['id'],))
            else:
                db.execute("""UPDATE jobs SET bytes=MAX(0,bytes-?),source_removed=1
                    WHERE id=? AND source_removed=0""", (source_bytes, job['id']))

    def all(self):
        with self.transaction() as db:
            return [dict(row) for row in db.execute(f"""SELECT id,name,state,attempts,error,elapsed,
                reserved,output_bytes,lease_token,review,
                CASE WHEN {REPLACEABLE_BATCH} THEN 1 ELSE 0 END AS source_replaceable,
                json_extract(spec,'$.campaign_id') AS campaign_id,
                json_extract(spec,'$.release_day') AS release_day,
                json_extract(spec,'$.release_days') AS release_days,
                json_extract(spec,'$.reference') AS reference,
                json_extract(spec,'$.batch_parent') AS batch_parent FROM jobs ORDER BY rowid DESC""",
                replacement_window())]
