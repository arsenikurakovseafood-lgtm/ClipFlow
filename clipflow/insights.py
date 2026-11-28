"""Campaign checkpoints and a EUR cash ledger for the owner workspace."""
from datetime import datetime, timedelta, timezone
from uuid import UUID

from clipflow.campaigns import Conflict
from clipflow.platform_metrics import youtube_statistics, youtube_video_id
from clipflow.queue import Limit, workloads_paused

WINDOWS = (24, 72, 168)
METRICS = ('views', 'likes', 'comments', 'shares', 'saves', 'clicks', 'conversions')
INCOME = ('subscription', 'paid_campaign', 'affiliate', 'platform')
EXPENSE = ('api', 'render', 'storage', 'publishing', 'fees', 'tax')
STATES = ('confirmed', 'pending', 'estimated')


class Insights:
    def __init__(self, queue):
        self.queue = queue
        with queue.transaction() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS post_metrics (
                post_id TEXT NOT NULL, hours INTEGER NOT NULL, views INTEGER NOT NULL,
                likes INTEGER, comments INTEGER, shares INTEGER, saves INTEGER, clicks INTEGER,
                conversions INTEGER, recorded_at TEXT NOT NULL, PRIMARY KEY (post_id,hours)
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS ledger_entries (
                id TEXT PRIMARY KEY, campaign_id TEXT, kind TEXT NOT NULL, cents INTEGER NOT NULL,
                state TEXT NOT NULL, note TEXT NOT NULL, recorded_at TEXT NOT NULL
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS youtube_metrics (
                post_id TEXT PRIMARY KEY, views INTEGER NOT NULL, likes INTEGER, comments INTEGER,
                observed_at TEXT NOT NULL
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS youtube_reads (
                post_id TEXT NOT NULL, requested_at TEXT NOT NULL
            )""")
            if 'source' not in {row['name'] for row in db.execute('PRAGMA table_info(post_metrics)')}:
                db.execute("ALTER TABLE post_metrics ADD COLUMN source TEXT NOT NULL DEFAULT 'manual'")
            db.execute("""CREATE TABLE IF NOT EXISTS youtube_checkpoint_reads (
                post_id TEXT NOT NULL, hours INTEGER NOT NULL, attempted_at TEXT NOT NULL,
                PRIMARY KEY (post_id, hours)
            )""")

    def collect_checkpoint(self, publisher, now=None):
        now = datetime.now(timezone.utc) if now is None else now
        with self.queue.transaction() as db:
            if workloads_paused(db):
                return
            post = db.execute("""SELECT p.id,p.provider_id,w.hours
                FROM manual_posts p JOIN campaigns c ON c.id=p.campaign_id
                CROSS JOIN (SELECT 24 AS hours UNION ALL SELECT 72 UNION ALL SELECT 168) w
                LEFT JOIN post_metrics m ON m.post_id=p.id AND m.hours=w.hours
                LEFT JOIN youtube_checkpoint_reads r ON r.post_id=p.id AND r.hours=w.hours
                WHERE p.state='published' AND p.provider_id IS NOT NULL AND c.state='active' AND m.post_id IS NULL
                AND julianday(?) BETWEEN julianday(p.reported_at)+w.hours/24.0
                    AND julianday(p.reported_at)+(w.hours+12)/24.0
                AND (r.attempted_at IS NULL OR r.attempted_at<=?)
                ORDER BY p.reported_at,w.hours LIMIT 1""",
                (now.isoformat(), (now - timedelta(minutes=30)).isoformat())).fetchone()
            if not post:
                return
            db.execute("""INSERT INTO youtube_checkpoint_reads VALUES (?,?,?) ON CONFLICT(post_id,hours)
                DO UPDATE SET attempted_at=excluded.attempted_at""", (post['id'], post['hours'], now.isoformat()))
        try:
            video = publisher.inspect(post['provider_id'])
            if video['status']['privacyStatus'] != 'public':
                return
            stats = video['statistics']
            counts = [int(stats[field]) if field in stats else None
                      for field in ('viewCount', 'likeCount', 'commentCount')]
            if counts[0] is None or any(value is not None and not 0 <= value <= 10**14 for value in counts):
                return
        except (OSError, KeyError, TypeError, ValueError):
            return
        with self.queue.transaction() as db:
            db.execute("""INSERT OR IGNORE INTO post_metrics
                (post_id,hours,views,likes,comments,recorded_at,source) VALUES (?,?,?,?,?,?,'youtube')""",
                (post['id'], post['hours'], *counts, now.isoformat()))

    def read_youtube(self, post_id, api_key, opener=None):
        if not api_key:
            raise Conflict('YouTube Data API is not configured in this workspace')
        now = datetime.now(timezone.utc)
        day = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        recent = (now - timedelta(minutes=10)).isoformat()
        with self.queue.transaction() as db:
            if workloads_paused(db):
                raise Conflict('Workspace processing is paused')
            post = db.execute("""SELECT p.post_url FROM manual_posts p JOIN campaigns c ON c.id=p.campaign_id
                WHERE p.id=? AND c.channel='youtube'""", (post_id,)).fetchone()
            video_id = youtube_video_id(post['post_url']) if post and post['post_url'] else None
            if not video_id:
                raise Conflict('Record the YouTube post URL first')
            if db.execute('SELECT COUNT(*) FROM youtube_reads WHERE requested_at>=?', (day,)).fetchone()[0] >= 100:
                raise Limit('The workspace has reached its daily YouTube read limit')
            if db.execute('SELECT 1 FROM youtube_reads WHERE post_id=? AND requested_at>=?', (post_id, recent)).fetchone():
                raise Limit('Wait ten minutes before requesting this post again')
            db.execute('DELETE FROM youtube_reads WHERE requested_at<?', (min(day, recent),))
            db.execute('INSERT INTO youtube_reads VALUES (?,?)', (post_id, now.isoformat()))
        stats = youtube_statistics(video_id, api_key, opener)
        with self.queue.transaction() as db:
            db.execute("""INSERT INTO youtube_metrics VALUES (?,?,?,?,?) ON CONFLICT(post_id) DO UPDATE
                SET views=excluded.views,likes=excluded.likes,comments=excluded.comments,observed_at=excluded.observed_at""",
                (post_id, stats['views'], stats['likes'], stats['comments'], now.isoformat()))

    def expire_platform_metrics(self, now):
        cutoff = datetime.fromtimestamp(now, timezone.utc) - timedelta(days=29)
        with self.queue.transaction() as db:
            db.execute('DELETE FROM youtube_metrics WHERE observed_at<=?', (cutoff.isoformat(),))
            db.execute("DELETE FROM post_metrics WHERE source='youtube' AND recorded_at<=?", (cutoff.isoformat(),))
            db.execute('DELETE FROM youtube_checkpoint_reads WHERE attempted_at<=?', (cutoff.isoformat(),))

    def record_metrics(self, post_id, data):
        hours = data.get('hours')
        counts = [data.get(metric) for metric in METRICS]
        if (type(hours) is not int or hours not in WINDOWS or counts[0] is None
                or any(value is not None and (type(value) is not int or not 0 <= value <= 1_000_000_000)
                       for value in counts)):
            raise ValueError('Select a checkpoint and enter valid platform counts. Views are required.')
        with self.queue.transaction() as db:
            post = db.execute('SELECT delivery FROM manual_posts WHERE id=? AND post_url IS NOT NULL', (post_id,)).fetchone()
            if not post or post['delivery'] != 'manual':
                raise Conflict('Record a manually published post URL before adding owner-reported metrics')
            db.execute("""INSERT INTO post_metrics
                (post_id,hours,views,likes,comments,shares,saves,clicks,conversions,recorded_at) VALUES (?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(post_id,hours) DO UPDATE SET views=excluded.views, likes=excluded.likes,
                comments=excluded.comments, shares=excluded.shares, saves=excluded.saves,
                clicks=excluded.clicks, conversions=excluded.conversions,
                recorded_at=excluded.recorded_at,source='manual'""",
                (post_id, hours, *counts, datetime.now(timezone.utc).isoformat()))

    def add_entry(self, data):
        campaign_id, kind, cents, state, note = (data.get(key) for key in
                                                 ('campaign_id', 'kind', 'cents', 'state', 'note'))
        key = data.get('key')
        if (kind not in (*INCOME, *EXPENSE) or state not in STATES or type(cents) is not int
                or not 0 < cents <= 100_000_000 or not isinstance(note, str) or not 0 < len(note.strip()) <= 240
                or (campaign_id is not None and not isinstance(campaign_id, str))
                or not isinstance(key, str) or len(key) != 36):
            raise ValueError('Enter a category, amount, status and short reference')
        if str(UUID(key)) != key:
            raise ValueError('Invalid payment entry key')
        values = (campaign_id, kind, cents, state, note.strip())
        with self.queue.transaction() as db:
            if campaign_id and not db.execute('SELECT 1 FROM campaigns WHERE id=?', (campaign_id,)).fetchone():
                raise Conflict('Campaign unavailable')
            db.execute('INSERT OR IGNORE INTO ledger_entries VALUES (?,?,?,?,?,?,?)',
                       (key, *values, datetime.now(timezone.utc).isoformat()))
            row = db.execute('SELECT campaign_id,kind,cents,state,note FROM ledger_entries WHERE id=?', (key,)).fetchone()
            if tuple(row) != values:
                raise Conflict('This entry key was already used for a different payment')

    def confirm_entry(self, entry_id):
        with self.queue.transaction() as db:
            if not db.execute("UPDATE ledger_entries SET state='confirmed' WHERE id=? AND state='pending'",
                              (entry_id,)).rowcount:
                raise Conflict('Only a pending entry can be confirmed')

    def snapshot(self):
        with self.queue.transaction() as db:
            entries = [dict(row) for row in db.execute('SELECT * FROM ledger_entries ORDER BY rowid DESC LIMIT 200')]
            totals = {state: {'income': 0, 'expense': 0} for state in STATES}
            for row in db.execute('SELECT state,kind,sum(cents) AS cents FROM ledger_entries GROUP BY state,kind'):
                totals[row['state']]['income' if row['kind'] in INCOME else 'expense'] += row['cents']
            metrics = [dict(row) for row in db.execute("""SELECT m.*,c.id AS campaign_id,c.name AS campaign,
                c.channel,p.post_url,j.name AS clip,
                COALESCE(json_extract(j.spec,'$.creative'),'manual') AS creative
                FROM post_metrics m JOIN manual_posts p ON p.id=m.post_id
                JOIN campaigns c ON c.id=p.campaign_id JOIN jobs j ON j.id=p.job_id
                ORDER BY m.recorded_at DESC""")]
            provider_usage = {'transcription_reserved_micro_usd': db.execute(
                'SELECT COALESCE(SUM(micro_usd),0) FROM transcription_usage').fetchone()[0],
                'render_seconds': db.execute('SELECT COALESCE(SUM(elapsed),0) FROM jobs').fetchone()[0],
                'storage_reserved_bytes': db.execute('SELECT COALESCE(SUM(bytes),0) FROM jobs').fetchone()[0]}
            youtube = [dict(row) for row in db.execute("""SELECT m.*,c.name AS campaign,j.name AS clip
                FROM youtube_metrics m JOIN manual_posts p ON p.id=m.post_id JOIN campaigns c ON c.id=p.campaign_id
                JOIN jobs j ON j.id=p.job_id WHERE m.observed_at>? ORDER BY m.observed_at DESC LIMIT 200""",
                ((datetime.now(timezone.utc) - timedelta(days=29)).isoformat(),))]
        return {'entries': entries, 'totals': totals, 'metrics': metrics[:200],
                'decisions': recommendations(metrics), 'usage': provider_usage, 'youtube': youtube}


def recommendations(metrics):
    # A record only competes with the same campaign, channel and measurement window.
    groups = {}
    for row in metrics:
        groups.setdefault((row['campaign_id'], row['hours'], row.get('source', 'manual')), []).append(row)
    decisions = []
    for (campaign_id, hours, source), rows in groups.items():
        cohorts = {}
        for row in rows:
            cohorts.setdefault(row['creative'], []).append(row)
        available = {name: clips for name, clips in cohorts.items()
                     if len(clips) >= 3 and sum(clip['views'] for clip in clips) >= 300}
        if len(available) < 2:
            continue
        fields = ('likes',) if source == 'youtube' else ('conversions', 'clicks')
        measure = next((key for key in fields
                        if all(clip[key] is not None for clips in available.values() for clip in clips)), None)
        if not measure:
            continue
        rates = {name: sum(clip[measure] for clip in clips) / sum(clip['views'] for clip in clips)
                 for name, clips in available.items()}
        leader, runner_up = sorted(rates, key=rates.get, reverse=True)[:2]
        if rates[leader] <= rates[runner_up] or sum(clip[measure] for clip in available[leader]) < 5:
            continue
        decisions.append({'campaign_id': campaign_id, 'campaign': rows[0]['campaign'],
                          'hours': hours, 'measure': measure,
                          'candidate': leader, 'comparison': runner_up, 'count': len(available[leader]),
                          'rate': rates[leader], 'comparison_rate': rates[runner_up]})
    return decisions[:20]
