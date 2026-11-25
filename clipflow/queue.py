"""Persistent single-owner demo queue. Monetary units are integer micro-euros."""
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone


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
            spending = db.execute('SELECT COALESCE(SUM(reserved),0) FROM jobs WHERE month=?',
                                  (month,)).fetchone()[0]
            storage = db.execute('SELECT COALESCE(SUM(bytes),0) FROM jobs').fetchone()[0]
            if spending + cost > budget or storage + size > quota:
                raise Limit('Demo render budget or source storage quota exhausted')
            job_id = uuid.uuid4().hex
            db.execute("""INSERT INTO jobs (id,request_key,name,spec,month,reserved,bytes)
                          VALUES (?,?,?,?,?,?,?)""", (job_id, key, name, spec, month, cost, size))
            return job_id, True

    def uploaded(self, job_id):
        with self.transaction() as db:
            db.execute("UPDATE jobs SET state='queued' WHERE id=? AND state='uploading'", (job_id,))

    def abandon(self, job_id):
        with self.transaction() as db:
            db.execute("DELETE FROM jobs WHERE id=? AND state='uploading'", (job_id,))

    def claim(self, now=None):
        now = time.time() if now is None else now
        with self.transaction() as db:
            db.execute("""UPDATE jobs SET state='failed', error='Worker lease expired twice'
                          WHERE state='running' AND lease_until<=? AND attempts>=2""", (now,))
            job = db.execute("""SELECT * FROM jobs
                WHERE state='queued' OR (state='running' AND lease_until<=?)
                ORDER BY rowid LIMIT 1""", (now,)).fetchone()
            if not job:
                return None
            token = uuid.uuid4().hex
            db.execute("""UPDATE jobs SET state='running', attempts=attempts+1,
                          lease_until=?, lease_token=? WHERE id=?""", (now + 360, token, job['id']))
            return dict(job, lease_token=token)

    def finish(self, job, *, error=None, elapsed=None, output_bytes=None):
        with self.transaction() as db:
            return bool(db.execute("""UPDATE jobs SET state=?, error=?, elapsed=?,output_bytes=?
                WHERE id=? AND lease_token=? AND state='running'""",
                ('failed' if error else 'ready', error, elapsed, output_bytes,
                 job['id'], job['lease_token'])).rowcount)

    def all(self):
        with self.transaction() as db:
            return [dict(row) for row in db.execute("""SELECT id,name,state,attempts,error,elapsed,
                reserved,output_bytes,lease_token FROM jobs ORDER BY rowid DESC""")]
