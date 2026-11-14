// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const useSession = vi.fn();
const signIn = vi.fn();
vi.mock("next-auth/react", () => ({ useSession: () => useSession(), signIn: (...args: unknown[]) => signIn(...args) }));

import { SpotifySaveButton } from "./spotify-save-button";

const TRACK = "7crxOiKNyPIb2rkCkCWlH7";

describe("SpotifySaveButton (N07)", () => {
  let root: Root;
  let host: HTMLDivElement;
  const fetchMock = vi.fn();
  const button = () => host.querySelector<HTMLButtonElement>(".spotify-save-chip");
  const click = () => act(async () => { button()!.click(); });

  beforeEach(async () => {
    vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
    vi.stubGlobal("fetch", fetchMock);
    useSession.mockReturnValue({ status: "authenticated" });
    host = document.createElement("div"); document.body.append(host); root = createRoot(host);
    await act(async () => root.render(<SpotifySaveButton trackId={TRACK} label="Chambray – Feelin' Good" />));
  });
  afterEach(async () => {
    await act(async () => root.unmount());
    host.remove(); vi.unstubAllGlobals(); vi.resetAllMocks();
  });

  it("saves, then removes on a second press", async () => {
    fetchMock.mockImplementation(async () => new Response(JSON.stringify({}), { status: 200 }));
    expect(button()!.getAttribute("aria-pressed")).toBe("false");
    await click();
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ trackId: TRACK, saved: true });
    expect(button()!.dataset.state).toBe("saved");
    expect(button()!.getAttribute("aria-pressed")).toBe("true");
    await click();
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({ trackId: TRACK, saved: false });
    expect(button()!.dataset.state).toBe("idle");
  });

  it("offers to reconnect Spotify when the library permission is missing", async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify({ reason: "connect", error: "Reconnect" }), { status: 409 }));
    await click();
    expect(button()!.dataset.state).toBe("connect");
    await click();
    expect(signIn).toHaveBeenCalledWith("spotify", expect.objectContaining({ callbackUrl: expect.stringContaining("spotify=connected") }));
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("is hidden when signed out", async () => {
    useSession.mockReturnValue({ status: "unauthenticated" });
    await act(async () => root.render(<SpotifySaveButton trackId={TRACK} label="x" />));
    expect(button()).toBeNull();
  });
});
