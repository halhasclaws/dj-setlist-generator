-- Production app role: give set_list_app the same Yoon registry ACL that
-- 0024 gives set_list_dev_app. 0024 sealed only the worker and development
-- roles, so on Production the app role kept the broad default privileges
-- (full DML on the registry tables, EXECUTE on the guard functions).
-- No-op where set_list_app does not exist (development).
DO $yoon_prod_app_acl$
DECLARE target_role text;
BEGIN
 FOREACH target_role IN ARRAY ARRAY['set_list_app'] LOOP
  IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=target_role) THEN CONTINUE; END IF;
  EXECUTE format('REVOKE ALL ON TABLE ops.yoon_reserved_versions,ops.yoon_version_collections,ops.yoon_version_families,ops.yoon_versions,ops.yoon_release_reviews,ops.yoon_version_history FROM %I',target_role);
  EXECUTE format('REVOKE ALL ON FUNCTION ops.yoon_sha(jsonb) FROM %I',target_role);
  EXECUTE format('REVOKE ALL ON FUNCTION ops.yoon_audience(uuid) FROM %I',target_role);
  EXECUTE format('REVOKE ALL ON FUNCTION ops.yoon_source_fingerprint(uuid) FROM %I',target_role);
  EXECUTE format('REVOKE ALL ON FUNCTION ops.yoon_media_fingerprint(uuid) FROM %I',target_role);
  EXECUTE format('REVOKE ALL ON FUNCTION ops.yoon_collection_scope(uuid) FROM %I',target_role);
  EXECUTE format('REVOKE ALL ON FUNCTION ops.yoon_is_v2(jsonb) FROM %I',target_role);
  EXECUTE format('REVOKE ALL ON FUNCTION app.yoon_version_readable(uuid,boolean) FROM %I',target_role);
  EXECUTE format('REVOKE ALL ON FUNCTION app.yoon_submission_version_readable(uuid) FROM %I',target_role);
  EXECUTE format('REVOKE ALL ON FUNCTION ops.yoon_registry_lock() FROM %I',target_role);
  EXECUTE format('REVOKE ALL ON FUNCTION ops.yoon_run_busy(uuid) FROM %I',target_role);
  EXECUTE format('REVOKE ALL ON FUNCTION ops.assert_yoon_version_identity(uuid) FROM %I',target_role);
  EXECUTE format('REVOKE ALL ON FUNCTION ops.assert_yoon_version_execution(uuid,text,text) FROM %I',target_role);
  EXECUTE format('REVOKE ALL ON FUNCTION ops.yoon_version_snapshot(uuid) FROM %I',target_role);
  EXECUTE format('REVOKE ALL ON FUNCTION ops.yoon_immutable_registry() FROM %I',target_role);
  EXECUTE format('REVOKE ALL ON FUNCTION ops.yoon_registration_check() FROM %I',target_role);
  EXECUTE format('REVOKE ALL ON FUNCTION ops.yoon_mutation_guard() FROM %I',target_role);
  EXECUTE format('REVOKE ALL ON FUNCTION ops.yoon_bootstrap_check() FROM %I',target_role);
  EXECUTE format('REVOKE ALL ON FUNCTION ops.yoon_audience_guard() FROM %I',target_role);
  EXECUTE format('REVOKE ALL ON FUNCTION ops.select_yoon_version(uuid,uuid,bigint,uuid,text,text,text,boolean) FROM %I',target_role);
  EXECUTE format('REVOKE ALL ON FUNCTION ops.initialize_yoon_version_execution(uuid) FROM %I',target_role);
  EXECUTE format('REVOKE ALL ON FUNCTION ops.yoon_selection_receipt_check() FROM %I',target_role);
  EXECUTE format('REVOKE ALL ON FUNCTION ops.yoon_release_receipt_check() FROM %I',target_role);
  IF target_role='set_list_app' THEN
   EXECUTE format('GRANT SELECT(set_id,submission_id) ON ops.yoon_reserved_versions TO %I',target_role);
   EXECUTE format('GRANT SELECT(set_id,submission_id,logical_set_id,collection_id,released) ON ops.yoon_versions TO %I',target_role);
   EXECUTE format('GRANT SELECT(logical_set_id,selected_set_id) ON ops.yoon_version_families TO %I',target_role);
   EXECUTE format('GRANT SELECT(collection_id) ON ops.yoon_version_collections TO %I',target_role);
  ELSE
   EXECUTE format('GRANT SELECT ON ops.yoon_reserved_versions,ops.yoon_versions,ops.yoon_version_families TO %I',target_role);
   EXECUTE format('GRANT SELECT(collection_id,audience_sha256) ON ops.yoon_version_collections TO %I',target_role);
   EXECUTE format('GRANT EXECUTE ON FUNCTION ops.yoon_sha(jsonb),ops.yoon_audience(uuid),ops.yoon_source_fingerprint(uuid),ops.yoon_media_fingerprint(uuid),ops.yoon_registry_lock(),ops.yoon_run_busy(uuid),ops.assert_yoon_version_identity(uuid),ops.assert_yoon_version_execution(uuid,text,text) TO %I',target_role);
  END IF;
  EXECUTE format('GRANT EXECUTE ON FUNCTION app.yoon_version_readable(uuid,boolean),app.yoon_submission_version_readable(uuid),ops.yoon_collection_scope(uuid),ops.yoon_is_v2(jsonb) TO %I',target_role);
 END LOOP;
END $yoon_prod_app_acl$;
