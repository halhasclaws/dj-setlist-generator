-- Russell, Nov 16 2026: Yoon sets need no special treatment beyond who may
-- view them. Approved pipeline changes (re-recognition, re-clustering, track
-- boundaries, new runs, media or source updates, deletes) apply to Yoon sets
-- like any other set. The write guard therefore keeps only privacy:
--   * a set, submission or run in a Yoon collection must stay private;
--   * a set, submission or run in a Yoon collection cannot leave it;
--   * evidence rows (entries, media, artists, source links, leases, hits) of
--     a Yoon set or run cannot be re-parented onto another set or run.
-- Removed: frozen/approval gates, fresh-run rule, media and source fingerprint
-- pins, slug and identity pins, delete blocks, unregistered-write and v2
-- payload checks, registry lock and family/release quiescence checks.
-- Unchanged: ops.yoon_audience_guard still blocks membership changes in Yoon
-- collections, 0018's scope triggers and CHECKs, and the read gates.
-- Only the function body changes; triggers stay attached, so no table locks
-- beyond the catalog update are taken on a live database.
CREATE OR REPLACE FUNCTION ops.yoon_mutation_guard() RETURNS trigger
 LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
DECLARE j jsonb; oldj jsonb; parent_key text; old_parent uuid; visibility_key text;
BEGIN
 IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
 j := to_jsonb(NEW);
 IF TG_TABLE_NAME NOT IN ('sets', 'submissions', 'set_runs') THEN
  IF TG_OP = 'UPDATE' THEN
   parent_key := CASE WHEN TG_TABLE_NAME IN ('set_run_leases', 'segment_hits') THEN 'set_run_id' ELSE 'set_id' END;
   oldj := to_jsonb(OLD);
   IF (j->>parent_key) IS DISTINCT FROM (oldj->>parent_key) THEN
    old_parent := (oldj->>parent_key)::uuid;
    IF (parent_key = 'set_id' AND ops.yoon_collection_scope((SELECT collection_id FROM app.sets WHERE id = old_parent)))
       OR (parent_key = 'set_run_id' AND ops.yoon_collection_scope((SELECT collection_id FROM ops.set_runs WHERE id = old_parent))) THEN
     RAISE EXCEPTION 'yoon_evidence_reparent';
    END IF;
   END IF;
  END IF;
  RETURN NEW;
 END IF;
 IF TG_OP = 'UPDATE' THEN
  oldj := to_jsonb(OLD);
  IF ops.yoon_collection_scope((oldj->>'collection_id')::uuid)
     AND (j->>'collection_id') IS DISTINCT FROM (oldj->>'collection_id') THEN
   RAISE EXCEPTION 'yoon_leaves_private_collection';
  END IF;
 END IF;
 visibility_key := CASE WHEN TG_TABLE_NAME = 'set_runs' THEN 'publication_visibility' ELSE 'visibility' END;
 IF ops.yoon_collection_scope((j->>'collection_id')::uuid)
    AND (j->>visibility_key) IS DISTINCT FROM 'private' THEN
  RAISE EXCEPTION 'yoon_must_stay_private';
 END IF;
 RETURN NEW;
END $$;
