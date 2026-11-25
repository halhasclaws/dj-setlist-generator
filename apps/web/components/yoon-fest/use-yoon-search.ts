"use client";

import { useEffect, useState } from "react";
import type { YoonSearchPayload, YoonSearchResult } from "@/lib/yoon-fest/search";

type Access = "unknown" | "member" | "none";

/**
 * Private collection results for the header search panel. Asks the private
 * access route once per panel mount; only a member's browser then sends the
 * query to the private search route. Everyone else sends nothing further and
 * sees nothing new.
 */
export function useYoonSearch(open: boolean, query: string) {
  const [access, setAccess] = useState<Access>("unknown");
  const [results, setResults] = useState<YoonSearchResult[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open || access !== "unknown") return;
    const controller = new AbortController();
    fetch("/api/yoon-fest/access", { cache: "no-store", credentials: "same-origin", signal: controller.signal })
      .then((response) => setAccess(response.status === 204 ? "member" : "none"))
      .catch((error: Error) => { if (error.name !== "AbortError") setAccess("none"); });
    return () => controller.abort();
  }, [access, open]);

  useEffect(() => {
    if (!open || access !== "member" || query.length < 2) {
      setResults([]);
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    const timer = window.setTimeout(() => {
      fetch(`/api/yoon-fest/search?${new URLSearchParams({ q: query }).toString()}`, {
        cache: "no-store", credentials: "same-origin", signal: controller.signal,
      })
        .then((response) => (response.ok ? response.json() as Promise<YoonSearchPayload> : { query, results: [] }))
        .then((payload) => setResults(payload.results))
        .catch((error: Error) => { if (error.name !== "AbortError") setResults([]); })
        .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    }, 160);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [access, open, query]);

  return { results, loading };
}
