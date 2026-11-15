import { afterEach, expect, it, vi } from "vitest";
import { traceAudioTiming } from "./audio-timing";
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });
it("keeps playback diagnostics disabled by default", () => {
  const info = vi.spyOn(console, "info").mockImplementation(() => {});
  traceAudioTiming("play-command", "soundcloud");
  vi.stubGlobal("window", { location: { search: "?other=1" } });
  traceAudioTiming("play-command", "soundcloud");
  expect(info).not.toHaveBeenCalled();
});
it("logs only local relative timing when explicitly requested", () => {
  const info = vi.spyOn(console, "info").mockImplementation(() => {});
  vi.stubGlobal("window", { location: { search: "?audioTiming=1" } });
  traceAudioTiming("play-command", "soundcloud");
  expect(info).toHaveBeenCalledWith(expect.stringMatching(/^\[audio-timing\] \d+\.\d soundcloud play-command$/));
});
it("keeps a session-local log only when enabled", async () => {
  vi.spyOn(console, "info").mockImplementation(() => {});
  const store = new Map<string, string>();
  const sessionStorage = { getItem: (key: string) => store.get(key) ?? null, setItem: (key: string, value: string) => { store.set(key, value); } };
  vi.stubGlobal("window", { location: { search: "?other=1" }, sessionStorage });
  const { readAudioTimingLog, clearAudioTimingLog } = await import("./audio-timing");
  traceAudioTiming("ignored", "page");
  expect(readAudioTimingLog()).toEqual([]);
  vi.stubGlobal("window", { location: { search: "?audioTiming=1" }, sessionStorage });
  clearAudioTimingLog();
  traceAudioTiming("session:play", "native-audio");
  expect(readAudioTimingLog()).toEqual([expect.stringMatching(/native-audio session:play$/)]);
  expect(JSON.parse(store.get("audio-timing-log")!)).toHaveLength(1);
});
