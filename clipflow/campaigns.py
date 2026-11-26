"""Single-owner campaign drafts and manual publication queue."""
import math
import time
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from clipflow.queue import audit

CHANNELS = {'youtube', 'instagram', 'tiktok'}
TRANSITIONS = {
    ('draft', 'approve'): 'active',
    ('active', 'pause'): 'paused',
    ('paused', 'resume'): 'active',
    ('draft', 'stop'): 'stopped',
    ('active', 'stop'): 'stopped',
    ('paused', 'stop'): 'stopped',
}


class Conflict(ValueError):
    pass


PLATFORM_HOSTS = {
    'youtube': {'www.youtube.com', 'youtube.com', 'youtu.be', 'm.youtube.com'},
    'instagram': {'www.instagram.com', 'instagram.com'},
    'tiktok': {'www.tiktok.com', 'tiktok.com', 'vm.tiktok.com'},
}


class Campaigns:
    def __init__(self, queue):
        self.queue = queue
        with queue.transaction() as db:
            campaign_columns = {row['name'] for row in db.execute('PRAGMA table_info(campaigns)')}
            if 'workflow' not in campaign_columns:
                db.execute("ALTER TABLE campaigns ADD COLUMN workflow TEXT NOT NULL DEFAULT 'visual'")
                db.execute('ALTER TABLE campaigns ADD COLUMN target_clips INTEGER NOT NULL DEFAULT 3')
            if 'transcription_budget' not in campaign_columns:
                db.execute('ALTER TABLE campaigns ADD COLUMN transcription_budget INTEGER NOT NULL DEFAULT 0')
            db.execute("""CREATE TABLE IF NOT EXISTS manual_posts (
                id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, job_id TEXT NOT NULL,
                scheduled_at TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'scheduled',
                UNIQUE (campaign_id, job_id)
            )""")
            columns = {row['name'] for row in db.execute('PRAGMA table_info(manual_posts)')}
            if 'post_url' not in columns:
                db.execute('ALTER TABLE manual_posts ADD COLUMN post_url TEXT')
                db.execute('ALTER TABLE manual_posts ADD COLUMN reported_at TEXT')
                db.execute("""UPDATE jobs SET review='approved' WHERE id IN (SELECT job_id FROM manual_posts)""")

    def review_clip(self, job_id, review):
        if review not in ('approved', 'rejected'):
            raise ValueError('Choose approve or reject')
        with self.queue.transaction() as db:
            changed = db.execute("""UPDATE jobs SET review=? WHERE id=? AND state='ready'
                AND (?='approved' OR NOT EXISTS (SELECT 1 FROM manual_posts p JOIN campaigns c
                ON c.id=p.campaign_id WHERE p.job_id=jobs.id AND
                (p.state='handed_off' OR c.state<>'stopped')))""", (review, job_id, review)).rowcount
            if not changed:
                raise Conflict('Only ready clips can be reviewed. Scheduled or handed-off clips cannot be rejected.')
            audit(db, 'clip_' + review, job_id)

    def report_post(self, post_id, data):
        url = data.get('url')
        if not isinstance(url, str) or not 0 < len(url) <= 500 or any(c.isspace() for c in url):
            raise ValueError('Enter the public post URL')
        parts = urlsplit(url)
        with self.queue.transaction() as db:
            row = db.execute("""SELECT p.post_url,c.channel FROM manual_posts p JOIN campaigns c
                ON c.id=p.campaign_id WHERE p.id=? AND p.state='handed_off'""", (post_id,)).fetchone()
            if not row:
                raise Conflict('Mark this clip handed off before recording a post')
            valid_path = {
                'youtube': parts.path.startswith('/shorts/') or parts.path == '/watch'
                or (parts.netloc == 'youtu.be' and len(parts.path) > 1),
                'instagram': parts.path.startswith(('/reel/', '/p/')),
                'tiktok': '/video/' in parts.path or (parts.netloc == 'vm.tiktok.com' and len(parts.path) > 1),
            }
            if parts.scheme != 'https' or parts.netloc not in PLATFORM_HOSTS[row['channel']] or not valid_path[row['channel']]:
                raise ValueError('Enter a post URL from this campaign’s platform')
            if row['post_url'] and row['post_url'] != url:
                raise Conflict('This handoff already has a recorded post URL')
            db.execute("""UPDATE manual_posts SET post_url=?,reported_at=COALESCE(reported_at,?) WHERE id=?""",
                       (url, datetime.now(timezone.utc).isoformat(), post_id))

    def create(self, data):
        def string(field, limit):
            value = data.get(field)
            if not isinstance(value, str) or not 0 < len(value.strip()) <= limit:
                raise ValueError(f'Enter a valid {field}')
            return value.strip()

        def integer(field, low, high):
            value = data.get(field)
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f'Enter a valid {field}')
            return value

        name, goal, channel = string('name', 80), string('goal', 1500), string('channel', 20)
        if channel not in CHANNELS:
            raise ValueError('Select a supported manual publishing destination')
        duration = integer('duration_days', 1, 90)
        cadence = integer('cadence_days', 1, duration)
        budget = integer('budget_cents', 0, 100000)
        workflow, target_clips = data.get('workflow', 'visual'), data.get('target_clips', 3)
        transcription_budget = data.get('transcription_budget', 0)
        if (workflow not in ('visual', 'speech', 'music', 'original') or type(target_clips) is not int
                or not 1 <= target_clips <= 10):
            raise ValueError('Select a workflow and a target of 1–10 clips')
        if type(transcription_budget) is not int or not 0 <= transcription_budget <= 100_000_000:
            raise ValueError('Enter a transcription cap between $0 and $100')
        campaign_id = uuid.uuid4().hex
        with self.queue.transaction() as db:
            db.execute("""INSERT INTO campaigns (id,name,goal,channel,duration_days,cadence_days,budget_cents,
                state,created_at,workflow,target_clips,transcription_budget) VALUES (?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?, ?, ?)""",
                       (campaign_id, name, goal, channel, duration, cadence, budget,
                        datetime.now(timezone.utc).isoformat(), workflow, target_clips, transcription_budget))
        return campaign_id

    def transition(self, campaign_id, action):
        with self.queue.transaction() as db:
            campaign = db.execute('SELECT state FROM campaigns WHERE id=?', (campaign_id,)).fetchone()
            if not campaign:
                raise Conflict('Campaign unavailable')
            state = TRANSITIONS.get((campaign['state'], action))
            if state is None:
                raise Conflict('This campaign cannot perform the requested action')
            db.execute('UPDATE campaigns SET state=? WHERE id=?', (state, campaign_id))
            audit(db, 'campaign_' + state, campaign_id)
            if state == 'stopped':
                db.execute("""UPDATE jobs SET state='cancelled',finished_at=?,spec=json_remove(spec,'$.source_url')
                    WHERE json_extract(spec,'$.campaign_id')=? AND state IN ('uploading','queued','running')""",
                    (time.time(), campaign_id))

    def schedule(self, campaign_id, data):
        job_id = data.get('job_id')
        when = data.get('scheduled_at')
        if not isinstance(job_id, str) or not isinstance(when, str):
            raise ValueError('Choose a clip and a date')
        scheduled = datetime.fromisoformat(when)
        if scheduled.tzinfo is None:
            raise ValueError('The scheduled time requires a timezone')
        scheduled = scheduled.astimezone(timezone.utc).isoformat()
        with self.queue.transaction() as db:
            campaign = db.execute('SELECT state FROM campaigns WHERE id=?', (campaign_id,)).fetchone()
            job = db.execute("SELECT state,review,json_extract(spec,'$.campaign_id') AS campaign_id FROM jobs WHERE id=?",
                             (job_id,)).fetchone()
            if (not campaign or campaign['state'] != 'active' or not job or job['state'] != 'ready'
                    or job['review'] != 'approved' or job['campaign_id'] not in (None, campaign_id)):
                raise Conflict('Select an approved clip for this active campaign')
            if db.execute('SELECT 1 FROM manual_posts WHERE campaign_id=? AND job_id=?',
                          (campaign_id, job_id)).fetchone():
                raise Conflict('This clip is already in the campaign queue')
            db.execute('INSERT INTO manual_posts (id,campaign_id,job_id,scheduled_at) VALUES (?,?,?,?)',
                       (uuid.uuid4().hex, campaign_id, job_id, scheduled))

    def schedule_batch(self, campaign_id, data):
        batch_id = data.get('batch_id')
        first = data.get('scheduled_at')
        if not isinstance(batch_id, str) or not isinstance(first, str):
            raise ValueError('Choose a finished batch and its first release date')
        origin = datetime.fromisoformat(first)
        if origin.tzinfo is None:
            raise ValueError('The scheduled time requires a timezone')
        with self.queue.transaction() as db:
            campaign = db.execute('SELECT state FROM campaigns WHERE id=?', (campaign_id,)).fetchone()
            batch = db.execute("SELECT json_extract(spec,'$.campaign_id') AS campaign_id FROM jobs WHERE id=? AND state='prepared'",
                               (batch_id,)).fetchone()
            clips = db.execute("""SELECT id, state, review, json_extract(spec,'$.release_day') AS day
                FROM jobs WHERE json_extract(spec,'$.batch_parent')=? ORDER BY rowid""", (batch_id,)).fetchall()
            if not campaign or campaign['state'] != 'active':
                raise Conflict('Approve the campaign before scheduling')
            if (not batch or batch['campaign_id'] not in (None, campaign_id) or not clips
                    or any(clip['state'] != 'ready' or clip['review'] != 'approved' for clip in clips)):
                raise Conflict('Approve all clips in this batch before scheduling it')
            rows = []
            slots = {}
            for clip in clips:
                day = clip['day']
                slot = slots.get(day, 0)
                slots[day] = slot + 1
                scheduled = (origin + timedelta(days=day - 1, minutes=15 * slot)).astimezone(timezone.utc)
                rows.append((uuid.uuid4().hex, campaign_id, clip['id'], scheduled.isoformat()))
            db.executemany("""INSERT INTO manual_posts (id,campaign_id,job_id,scheduled_at)
                VALUES (?,?,?,?) ON CONFLICT(campaign_id,job_id) DO NOTHING""", rows)

    def complete(self, post_id):
        with self.queue.transaction() as db:
            changed = db.execute("""UPDATE manual_posts SET state='handed_off'
                WHERE id=? AND state='scheduled' AND scheduled_at<=?
                AND campaign_id IN (SELECT id FROM campaigns WHERE state='active')
                AND job_id IN (SELECT id FROM jobs WHERE state='ready')""",
                (post_id, datetime.now(timezone.utc).isoformat())).rowcount
            if not changed:
                raise Conflict('Only due items in active campaigns can be handed off')

    def snapshot(self):
        now = datetime.now(timezone.utc).isoformat()
        with self.queue.transaction() as db:
            campaigns = [dict(row) for row in db.execute('SELECT * FROM campaigns ORDER BY rowid DESC')]
            posts = [dict(row) for row in db.execute("""SELECT p.id,p.campaign_id,p.job_id,p.scheduled_at,p.post_url,p.reported_at,
                c.channel,j.name,c.name AS campaign_name,
                CASE WHEN p.state='handed_off' THEN p.state
                     WHEN c.state='stopped' THEN 'cancelled'
                     WHEN j.state='expired' THEN 'asset_expired'
                     WHEN c.state='paused' THEN 'on_hold'
                     WHEN p.scheduled_at<=? THEN 'due' ELSE p.state END AS state
                FROM manual_posts p JOIN campaigns c ON c.id=p.campaign_id
                JOIN jobs j ON j.id=p.job_id ORDER BY p.scheduled_at,p.rowid""", (now,))]
        for campaign in campaigns:
            campaign['planned_posts'] = math.ceil(campaign['duration_days'] / campaign['cadence_days'])
        return {'campaigns': campaigns, 'posts': posts}
