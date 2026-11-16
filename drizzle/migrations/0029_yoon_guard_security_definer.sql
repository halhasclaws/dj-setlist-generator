-- The Yoon write guard reads the registry with SELECT *, but the app roles
-- (set_list_dev_app, and set_list_app after 0028) may read only five columns
-- of ops.yoon_versions and two of ops.yoon_reserved_versions. As SECURITY
-- INVOKER the guard therefore failed every app-role insert into
-- ops.submissions, including ordinary public submissions ("permission denied
-- for table yoon_versions"). Run the guard as its owner instead: the checks
-- are unchanged and the app roles keep their narrow column grants. Every name
-- in the guard is schema-qualified; search_path is pinned.
ALTER FUNCTION ops.yoon_mutation_guard() SECURITY DEFINER SET search_path = pg_catalog, pg_temp;
