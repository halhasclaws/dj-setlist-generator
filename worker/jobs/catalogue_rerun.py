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
# The pipeline publishes under the canonical SoundCloud URL (https://soundcloud.com/..., share
# params stripped). A set stored under another form would get a second page, so it is skipped.
URL_OK = """(s.source_url not ilike '%%soundcloud%%'
               or (s.source_url ~ '^https://soundcloud\\.com/[^?#]*$'))"""
SUBMISSION_NAME = f'Catalogue re-run ({TAG.upper()})'


def _conn():
    return connect(os.environ['DATABASE_URL_DIRECT'], row_factory=dict_row)


def counts(cur) -> dict:
    cur.execute("""select status, count(*) as n from ops.set_runs
                   where source_metadata->>'catalogue_rerun' = %s group by status""", (TAG,))
    by = {r['status']: r['n'] for r in cur.fetchall()}
    cur.execute("""select count(*) as n from app.sets s
                   where s.visibility = 'public' and s.source_url is not null and """ + URL_OK + """
                     and not exists (select 1 from ops.set_runs r where r.published_set_id = s.id
                                     and r.archive_removed_at is not null)
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
    cur.execute("""insert into ops.submissions (requested_by, visibility, mode, status, artist_name, source_urls,
                   create_playlist) values (%s, 'public', 'curated_artist', 'running', %s, '[]'::jsonb, false)
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
                       where s.visibility = 'public' and s.source_url is not null and """ + URL_OK + """
                         and not exists (select 1 from ops.set_runs r where r.published_set_id = s.id
                                         and r.archive_removed_at is not null)
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
        from worker.callbacks import post_callback
        from worker.config import get_settings
        settings = get_settings()
        post_callback(settings, '/api/internal/dispatch-pending', timeout=30).raise_for_status()
        print('dispatch requested')
    except Exception as error:  # the scheduler cron dispatches anyway
        print(f'dispatch request failed ({type(error).__name__}); scheduler will pick it up')


def breakdown(cur) -> dict:
    """Why public set pages are or are not eligible (counts only)."""
    cur.execute("""
        select
          count(*) filter (where true) as public_pages,
          count(*) filter (where s.source_url is null) as no_source_url,
          count(*) filter (where s.source_url is not null and not exists
              (select 1 from ops.set_runs r where r.published_set_id = s.id)) as no_publishing_run,
          count(*) filter (where s.source_url is not null and exists
              (select 1 from ops.set_runs r where r.published_set_id = s.id) and not exists
              (select 1 from ops.set_runs r where r.published_set_id = s.id and r.archive_removed_at is null))
              as only_removed_runs,
          count(*) filter (where not exists (select 1 from ops.set_runs r where r.source_url = s.source_url))
              as no_run_for_url,
          count(*) filter (where exists (select 1 from ops.set_runs r where r.source_url = s.source_url)
              and not exists (select 1 from ops.set_runs r where r.published_set_id = s.id)) as runs_not_linked,
          count(*) filter (where s.source_platform not in ('youtube', 'soundcloud') or s.source_platform is null)
              as other_platform
        from app.sets s where s.visibility = 'public'""")
    out = dict(cur.fetchone())
    cur.execute("select count(*) as n from app.sets where visibility = 'private'")
    out['private_pages'] = cur.fetchone()['n']
    cur.execute("""select k, count(*) as n from app.sets s, jsonb_object_keys(s.metadata) k
                   where s.visibility = 'public' and not exists
                   (select 1 from ops.set_runs r where r.published_set_id = s.id)
                   group by k order by n desc limit 15""")
    out['unlinked_metadata_keys'] = {r['k']: r['n'] for r in cur.fetchall()}
    cur.execute("""select date_trunc('month', s.created_at)::date::text as m, count(*) as n from app.sets s
                   where s.visibility = 'public' and not exists
                   (select 1 from ops.set_runs r where r.published_set_id = s.id) group by 1 order by 1""")
    out['unlinked_by_month'] = {r['m']: r['n'] for r in cur.fetchall()}
    from source_url_normalizer import resolve_canonical_source_url, is_soundcloud_short_url
    cur.execute("""select s.source_url, exists (select 1 from ops.set_runs r where r.published_set_id = s.id) as linked
                   from app.sets s where s.visibility = 'public' and s.source_url ilike '%%soundcloud%%'""")
    drift = {'linked': 0, 'unlinked': 0, 'short_links': 0}
    for r in cur.fetchall():
        if is_soundcloud_short_url(r['source_url']):
            drift['short_links'] += 1
        elif resolve_canonical_source_url(r['source_url']) != r['source_url']:
            drift['linked' if r['linked'] else 'unlinked'] += 1
    out['soundcloud_url_would_change'] = drift
    cur.execute("select count(*) as n from app.sets s where s.visibility = 'public' and not " + URL_OK)
    out['skipped_url_form'] = cur.fetchone()['n']
    return out


def outcomes(cur, limit: int = 40) -> list:
    """Latest finished D06 runs: entries / identified before and after, same page, boundaries."""
    cur.execute("""
        select r.status, r.stage, left(regexp_replace(coalesce(r.error_summary, ''), 'https?://\\S+', '<url>', 'g'), 160) as err, left(r.source_metadata->>'rerun_of_set_id', 8) as set8,
               (r.published_set_id::text = r.source_metadata->>'rerun_of_set_id') as same_page,
               round(extract(epoch from (r.updated_at - r.created_at)) / 60) as minutes,
               jsonb_array_length(r.source_metadata->'rerun_snapshot'->'entries') as before_n,
               (select count(*) from jsonb_array_elements(r.source_metadata->'rerun_snapshot'->'entries') x
                 where x->>'track_id' is not null) as before_ids,
               (select count(*) from app.set_entries e where e.set_id = r.published_set_id) as after_n,
               (select count(*) from app.set_entries e where e.set_id = r.published_set_id
                 and e.track_id is not null) as after_ids,
               (select count(*) from app.set_entries e where e.set_id = r.published_set_id
                 and e.metadata ? 'provisional_boundaries') as unknown_with_bounds,
               (select count(*) from app.set_entries e where e.set_id = r.published_set_id
                 and e.track_id is null and e.end_time_seconds - e.start_time_seconds >= 240) as long_unknowns,
               (r.source_metadata ? 'boundary_curve') as curve
        from ops.set_runs r where r.source_metadata->>'catalogue_rerun' = %s
          and r.status in ('completed', 'failed', 'cancelled')
        order by r.updated_at desc limit %s""", (TAG, limit))
    return cur.fetchall()


def private_profile(cur) -> dict:
    """Shape of private sets' latest publishing runs (counts only)."""
    cur.execute("""
        with last as (
          select distinct on (s.id) s.id, r.source_url, r.source_metadata, r.submission_id, r.status
          from app.sets s join ops.set_runs r on r.target_set_id = s.id or r.published_set_id = s.id
          where s.visibility = 'private' order by s.id, r.created_at desc)
        select count(*) as private_with_run,
               count(*) filter (where source_url is null) as no_url,
               count(*) filter (where source_url ilike '%%dropbox%%') as dropbox,
               count(*) filter (where source_url ilike '%%youtu%%') as youtube,
               count(*) filter (where source_url ilike '%%soundcloud%%') as soundcloud,
               count(*) filter (where status = 'completed') as last_completed
        from last""")
    out = dict(cur.fetchone())
    cur.execute("""
        with last as (
          select distinct on (s.id) r.source_metadata from app.sets s
          join ops.set_runs r on r.target_set_id = s.id or r.published_set_id = s.id
          where s.visibility = 'private' order by s.id, r.created_at desc)
        select k, count(*) as n from last, jsonb_object_keys(source_metadata) k group by k order by n desc""")
    out['metadata_keys'] = {r['k']: r['n'] for r in cur.fetchall()}
    cur.execute("""select count(distinct collection_id) as n from app.sets where visibility = 'private'""")
    out['collections'] = cur.fetchone()['n']
    return out


def heal() -> int:
    """Finish bookkeeping for re-runs whose publication committed but whose worker
    lost the response (no page revalidation, no completed event)."""
    from worker.callbacks import post_callback
    from worker.config import get_settings
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("""select r.id, r.submission_id, r.published_set_id, s.slug,
                              r.source_metadata->'publication_result'->'affectedArtistSlugs' as artists
                       from ops.set_runs r join app.sets s on s.id = r.published_set_id
                       where r.source_metadata->>'catalogue_rerun' = %s and r.status = 'completed'
                         and not (r.source_metadata ? 'published')""", (TAG,))
        rows = cur.fetchall()
    healed = 0
    for row in rows:
        paths, tags = ['/', '/archive-preview', f"/sets/{row['slug']}", f"/archive-preview/sets/{row['slug']}"], \
            ['archive:home', 'archive:lists', f"archive:set:{row['slug']}"]
        for artist in row['artists'] or []:
            paths += [f'/artists/{artist}', f'/archive-preview/artists/{artist}']
            tags.append(f'archive:artist:{artist}')
        try:
            post_callback(get_settings(), '/api/internal/revalidate',
                          json={'paths': sorted(set(paths)), 'tags': sorted(set(tags))}, timeout=60).raise_for_status()
            with _conn() as conn, conn.cursor() as cur:
                cur.execute("""update ops.set_runs set source_metadata = source_metadata || %s::jsonb
                               where id = %s""",
                            (json.dumps({'published': {'set_id': str(row['published_set_id']), 'slug': row['slug'],
                                                       'healed': True}}), row['id']))
                cur.execute("""insert into ops.worker_events (submission_id, set_run_id, event_type, message, details)
                               values (%s, %s, 'set_run.completed', 'Publication bookkeeping completed (D06 heal)',
                               %s::jsonb)""", (row['submission_id'], row['id'],
                                                json.dumps({'published_set_id': str(row['published_set_id'])})))
                conn.commit()
            healed += 1
        except Exception as error:
            print(f'heal failed ({type(error).__name__})')
    print(json.dumps({'healed': healed, 'needing_heal': len(rows)}))
    return 0


def status() -> int:
    with _conn() as conn, conn.cursor() as cur:
        print(json.dumps(counts(cur)))
        print(json.dumps(breakdown(cur)))
        print(json.dumps(private_profile(cur), default=str))
        for row in outcomes(cur):
            print('outcome ' + json.dumps(row, default=str))
        cur.execute("""select left(r.source_metadata->>'rerun_of_set_id', 8) as set8,
                          to_char(e.created_at, 'HH24:MI:SS') as t, e.event_type
                       from ops.worker_events e join ops.set_runs r on r.id = e.set_run_id
                       where r.source_metadata->>'catalogue_rerun' = %s
                         and e.created_at > now() - interval '3 hours'
                         and e.event_type not like '%%segment%%' and e.event_type not like '%%lease%%'
                       order by e.created_at""", (TAG,))
        for row in cur.fetchall():
            print('event ' + json.dumps(row))
    return 0


def loop(limit: int, queue_target: int, interval: int, seconds: int) -> int:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        heal()
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
        heal()
        return status()
    if argv == ['loop']:
        return loop(limit, target, int(os.getenv('RERUN_INTERVAL', '300')), int(os.getenv('RERUN_LOOP_SECONDS', '19800')))
    raise SystemExit('usage: topup | status | loop')


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
