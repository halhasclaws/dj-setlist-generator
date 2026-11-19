"""D06 catalogue re-run: re-process published public sets with the current pipeline.

Production deliberately dedupes already-published URLs, so this job queues
fresh public set runs for existing sets itself. Publication matches the set by
its source URL and replaces its entries in place (same page, same slug). Before
queuing, each set's current entries are snapshotted into the new run's
source_metadata (``rerun_snapshot``) so a page can be compared or restored.

The normal dispatcher then admits queued runs at PROCESS_SET_MAX_ACTIVE_RUNS, so
the re-run uses exactly Production's concurrency. This job only keeps a small
queue topped up (worst recognition rate first), so user submissions never wait
behind the whole catalogue.

  python -m worker.jobs.catalogue_rerun topup    # RERUN_LIMIT, RERUN_QUEUE_TARGET
  python -m worker.jobs.catalogue_rerun status   # counts only
  python -m worker.jobs.catalogue_rerun loop     # top up every RERUN_INTERVAL s until RERUN_LOOP_SECONDS

Logs carry counts only.
"""
from __future__ import annotations

import json
import os
import sys
import time

from psycopg import connect
from psycopg.rows import dict_row

TAG = os.getenv('RERUN_TAG', 'd06')
SUBMISSION_NAME = f'Catalogue re-run ({TAG.upper()})'


def _conn():
    return connect(os.environ['DATABASE_URL_DIRECT'], row_factory=dict_row)


def counts(cur) -> dict:
    cur.execute("""select status, count(*) as n from ops.set_runs
                   where source_metadata->>'catalogue_rerun' = %s group by status""", (TAG,))
    by = {r['status']: r['n'] for r in cur.fetchall()}
    cur.execute("""select count(*) as n from app.sets s
                   where s.visibility = 'public' and s.source_url is not null
                     and exists (select 1 from ops.set_runs r where r.published_set_id = s.id
                                 and r.archive_removed_at is null)
                     and not exists (select 1 from ops.set_runs r2 where r2.source_url = s.source_url
                                     and r2.source_metadata->>'catalogue_rerun' = %s)""", (TAG,))
    by['not_started'] = cur.fetchone()['n']
    return by


def _submission(cur) -> tuple[str, str]:
    # The worker role cannot read authn; the owner is whoever submitted most sets.
    cur.execute("""select requested_by as id from ops.submissions group by requested_by
                   order by count(*) desc limit 1""")
    admin = cur.fetchone()
    if not admin:
        raise SystemExit('no_requester')
    cur.execute("""select id from ops.submissions where mode = 'curated_artist' and artist_name = %s
                   order by created_at limit 1""", (SUBMISSION_NAME,))
    row = cur.fetchone()
    if row:
        return str(row['id']), str(admin['id'])
    cur.execute("""insert into ops.submissions (requested_by, mode, status, artist_name, source_urls,
                   create_playlist) values (%s, 'curated_artist', 'running', %s, '[]'::jsonb, false)
                   returning id""", (admin['id'], SUBMISSION_NAME))
    return str(cur.fetchone()['id']), str(admin['id'])


def topup(limit: int, queue_target: int) -> int:
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("select pg_advisory_xact_lock(hashtext('catalogue_rerun'))")
        before = counts(cur)
        room = max(0, min(limit, queue_target - before.get('queued', 0)))
        if room == 0:
            print(json.dumps({'queued_now': 0, **before}))
            return 0
        submission_id, admin_id = _submission(cur)
        cur.execute("""select s.id, s.source_url, s.source_platform from app.sets s
                       where s.visibility = 'public' and s.source_url is not null
                         and exists (select 1 from ops.set_runs r where r.published_set_id = s.id
                                     and r.archive_removed_at is null)
                         and not exists (select 1 from ops.set_runs r2 where r2.source_url = s.source_url
                                         and r2.source_metadata->>'catalogue_rerun' = %s)
                         and not exists (select 1 from ops.set_runs r3 where r3.source_url = s.source_url
                                         and r3.status not in ('completed', 'failed', 'cancelled'))
                       order by s.recognition_rate asc nulls first, s.id
                       limit %s""", (TAG, room))
        picked = cur.fetchall()
        for row in picked:
            cur.execute("""select coalesce(jsonb_agg(to_jsonb(e) order by e.position), '[]'::jsonb) as entries
                           from app.set_entries e where e.set_id = %s""", (row['id'],))
            snapshot = cur.fetchone()['entries']
            cur.execute("""insert into ops.set_runs (submission_id, requested_by, publication_visibility, status,
                           source_url, source_platform, create_playlist, source_metadata)
                           values (%s, %s, 'public', 'queued', %s, %s, false, %s::jsonb)""",
                        (submission_id, admin_id, row['source_url'], row['source_platform'],
                         json.dumps({'catalogue_rerun': TAG, 'rerun_of_set_id': str(row['id']),
                                     'rerun_snapshot': {'taken_at': time.time(), 'entries': snapshot}})))
        conn.commit()
        print(json.dumps({'queued_now': len(picked), **counts(cur)}))
    if picked:
        _dispatch()
    return 0


def _dispatch() -> None:
    try:
        from worker.jobs.process_set import _dispatch_pending
        _dispatch_pending()
    except Exception as error:  # the scheduler cron dispatches anyway
        print(f'dispatch request failed ({type(error).__name__}); scheduler will pick it up')


def status() -> int:
    with _conn() as conn, conn.cursor() as cur:
        print(json.dumps(counts(cur)))
    return 0


def loop(limit: int, queue_target: int, interval: int, seconds: int) -> int:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        topup(limit, queue_target)
        with _conn() as conn, conn.cursor() as cur:
            c = counts(cur)
        if c['not_started'] == 0 and not c.get('queued') and not any(
                c.get(s) for s in c if s not in ('completed', 'failed', 'cancelled', 'not_started')):
            print('catalogue re-run complete')
            return 3
        time.sleep(interval)
    return 0


def main(argv: list[str]) -> int:
    limit = int(os.getenv('RERUN_LIMIT', '20'))
    target = int(os.getenv('RERUN_QUEUE_TARGET', '20'))
    if argv == ['topup']:
        return topup(limit, target)
    if argv == ['status']:
        return status()
    if argv == ['loop']:
        return loop(limit, target, int(os.getenv('RERUN_INTERVAL', '300')), int(os.getenv('RERUN_LOOP_SECONDS', '19800')))
    raise SystemExit('usage: topup | status | loop')


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
