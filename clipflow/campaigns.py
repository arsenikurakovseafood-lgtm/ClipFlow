"""Single-owner campaign drafts and manual publication queue."""
import math
import uuid
from datetime import datetime, timezone

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


class Campaigns:
    def __init__(self, queue):
        self.queue = queue
        with queue.transaction() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS campaigns (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, goal TEXT NOT NULL,
                channel TEXT NOT NULL, duration_days INTEGER NOT NULL,
                cadence_days INTEGER NOT NULL, budget_cents INTEGER NOT NULL,
                state TEXT NOT NULL, created_at TEXT NOT NULL
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS manual_posts (
                id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, job_id TEXT NOT NULL,
                scheduled_at TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'scheduled',
                UNIQUE (campaign_id, job_id)
            )""")

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
        campaign_id = uuid.uuid4().hex
        with self.queue.transaction() as db:
            db.execute("""INSERT INTO campaigns VALUES (?, ?, ?, ?, ?, ?, ?, 'draft', ?)""",
                       (campaign_id, name, goal, channel, duration, cadence, budget,
                        datetime.now(timezone.utc).isoformat()))
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
            job = db.execute('SELECT state FROM jobs WHERE id=?', (job_id,)).fetchone()
            if not campaign or campaign['state'] != 'active' or not job or job['state'] != 'ready':
                raise Conflict('Approve the campaign and select a ready clip')
            if db.execute('SELECT 1 FROM manual_posts WHERE campaign_id=? AND job_id=?',
                          (campaign_id, job_id)).fetchone():
                raise Conflict('This clip is already in the campaign queue')
            db.execute('INSERT INTO manual_posts (id,campaign_id,job_id,scheduled_at) VALUES (?,?,?,?)',
                       (uuid.uuid4().hex, campaign_id, job_id, scheduled))

    def complete(self, post_id):
        with self.queue.transaction() as db:
            changed = db.execute("""UPDATE manual_posts SET state='handed_off'
                WHERE id=? AND state='scheduled' AND scheduled_at<=?
                AND campaign_id IN (SELECT id FROM campaigns WHERE state='active')""",
                (post_id, datetime.now(timezone.utc).isoformat())).rowcount
            if not changed:
                raise Conflict('Only due items in active campaigns can be handed off')

    def snapshot(self):
        now = datetime.now(timezone.utc).isoformat()
        with self.queue.transaction() as db:
            campaigns = [dict(row) for row in db.execute('SELECT * FROM campaigns ORDER BY rowid DESC')]
            posts = [dict(row) for row in db.execute("""SELECT p.id,p.campaign_id,p.job_id,p.scheduled_at,
                c.channel,j.name,c.name AS campaign_name,
                CASE WHEN p.state='handed_off' THEN p.state
                     WHEN c.state='stopped' THEN 'cancelled'
                     WHEN c.state='paused' THEN 'on_hold'
                     WHEN p.scheduled_at<=? THEN 'due' ELSE p.state END AS state
                FROM manual_posts p JOIN campaigns c ON c.id=p.campaign_id
                JOIN jobs j ON j.id=p.job_id ORDER BY p.scheduled_at,p.rowid""", (now,))]
        for campaign in campaigns:
            campaign['planned_posts'] = math.ceil(campaign['duration_days'] / campaign['cadence_days'])
        return {'campaigns': campaigns, 'posts': posts}
