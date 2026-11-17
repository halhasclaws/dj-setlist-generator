-- N10 liked sets: one row per (signed-in user, liked set). Unliking deletes
-- the row. Additive only; no existing table or row changes.
CREATE TABLE IF NOT EXISTS "app"."user_set_likes" (
  "user_id" text NOT NULL,
  "set_id" uuid NOT NULL,
  "created_at" timestamp with time zone DEFAULT now() NOT NULL,
  CONSTRAINT "user_set_likes_user_id_set_id_pk" PRIMARY KEY("user_id", "set_id")
);
--> statement-breakpoint
DO $$ BEGIN
 ALTER TABLE "app"."user_set_likes" ADD CONSTRAINT "user_set_likes_user_id_users_id_fk" FOREIGN KEY ("user_id") REFERENCES "authn"."users"("id") ON DELETE cascade ON UPDATE no action;
EXCEPTION
 WHEN duplicate_object THEN null;
END $$;
--> statement-breakpoint
DO $$ BEGIN
 ALTER TABLE "app"."user_set_likes" ADD CONSTRAINT "user_set_likes_set_id_sets_id_fk" FOREIGN KEY ("set_id") REFERENCES "app"."sets"("id") ON DELETE cascade ON UPDATE no action;
EXCEPTION
 WHEN duplicate_object THEN null;
END $$;
--> statement-breakpoint
CREATE INDEX IF NOT EXISTS "user_set_likes_set_id_idx" ON "app"."user_set_likes" USING btree ("set_id");
--> statement-breakpoint
-- The app roles read and write likes; the worker roles only read (like other
-- app tables). Explicit grants, because default privileges apply only when the
-- migrator role creates the table. Roles missing on a branch are skipped.
DO $set_likes_acl$
DECLARE r text;
BEGIN
 FOREACH r IN ARRAY ARRAY['set_list_app','set_list_dev_app'] LOOP
  IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname=r) THEN
   EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE app.user_set_likes TO %I', r);
  END IF;
 END LOOP;
 FOREACH r IN ARRAY ARRAY['set_list_worker','set_list_dev_worker'] LOOP
  IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname=r) THEN
   EXECUTE format('GRANT SELECT ON TABLE app.user_set_likes TO %I', r);
  END IF;
 END LOOP;
END $set_likes_acl$;
