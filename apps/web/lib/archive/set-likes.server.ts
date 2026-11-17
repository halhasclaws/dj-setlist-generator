import "server-only";

import { and, desc, eq, inArray } from "drizzle-orm";

import { readableSetPredicate } from "@/lib/archive/access-policy";
import { getDb, type AppDb } from "@/lib/db/client";
import { sets, userSetLikes } from "@/lib/db/schema";

// Liked sets (N10). A like is one row per (user, set); unliking deletes it.
// Every read and write is limited to sets the user can read, so a private
// collection's likes stay visible only to its members.

export const MAX_LIKED_SET_IDS = 2000;

export const listUserLikedSetIds = async (
  userId: string,
  setIds?: string[],
  deps: { db?: AppDb } = {},
): Promise<string[]> => {
  const db = deps.db ?? getDb();
  const filter = setIds ? [...new Set(setIds)].filter(Boolean).slice(0, 200) : null;
  if (filter && filter.length === 0) return [];

  const rows = await db
    .select({ setId: userSetLikes.setId })
    .from(userSetLikes)
    .innerJoin(sets, eq(sets.id, userSetLikes.setId))
    .where(
      and(
        eq(userSetLikes.userId, userId),
        readableSetPredicate(userId),
        filter ? inArray(userSetLikes.setId, filter) : undefined,
      ),
    )
    .orderBy(desc(userSetLikes.createdAt))
    .limit(MAX_LIKED_SET_IDS);

  return rows.map((row) => row.setId);
};

// Returns the saved state, or null when the set is missing or not readable.
export const setUserSetLiked = async (
  userId: string,
  setId: string,
  liked: boolean,
  deps: { db?: AppDb; now?: Date } = {},
): Promise<boolean | null> => {
  const db = deps.db ?? getDb();
  const [readable] = await db
    .select({ id: sets.id })
    .from(sets)
    .where(and(eq(sets.id, setId), readableSetPredicate(userId)))
    .limit(1);
  if (!readable) return null;

  if (liked) {
    await db
      .insert(userSetLikes)
      .values({ createdAt: deps.now ?? new Date(), setId, userId })
      .onConflictDoNothing({ target: [userSetLikes.userId, userSetLikes.setId] });
    return true;
  }

  await db
    .delete(userSetLikes)
    .where(and(eq(userSetLikes.userId, userId), eq(userSetLikes.setId, setId)));
  return false;
};
