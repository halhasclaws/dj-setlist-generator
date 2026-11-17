// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const useSession = vi.fn();
const signIn = vi.fn();
vi.mock("next-auth/react", async () => {
  const { createContext } = await vi.importActual<typeof import("react")>("react");
  return { SessionContext: createContext<unknown>(undefined), signIn: (...args: unknown[]) => signIn(...args) };
});

const A = "4e1b45fc-1a38-4bfd-8831-5b7e98fb2c99";
const B = "0f9d6a51-2b51-4d0c-9a51-0b3c8a1f7d22";

describe("liked sets UI (N10)", () => {
  let root: Root;
  let host: HTMLDivElement;
  const fetchMock = vi.fn();
  const pills = () => [...host.querySelectorAll<HTMLButtonElement>("button[aria-pressed]")];

  const render = async (node: (mod: typeof import("./set-likes")) => React.ReactNode) => {
    const mod = await import("./set-likes");
    const { SessionContext } = await import("next-auth/react");
    host = document.createElement("div");
    document.body.append(host);
    root = createRoot(host);
    await act(async () => root.render(
      <SessionContext.Provider value={useSession() as never}>{node(mod)}</SessionContext.Provider>,
    ));
    return mod;
  };

  beforeEach(() => {
    vi.resetModules();
    vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
    vi.stubGlobal("fetch", fetchMock);
    useSession.mockReturnValue({ status: "authenticated" });
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) =>
      init?.method === "PUT"
        ? new Response(JSON.stringify({ ok: true }), { status: 200 })
        : new Response(JSON.stringify({ likedSetIds: [A] }), { status: 200 }));
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    host.remove();
    vi.unstubAllGlobals();
    vi.resetAllMocks();
  });

  it("loads the viewer's likes once and shares them across pills", async () => {
    await render(({ SetLikePill }) => (<><SetLikePill setId={A} /><SetLikePill setId={B} /><SetLikePill setId={A} /></>));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(pills().map((pill) => pill.getAttribute("aria-pressed"))).toEqual(["true", "false", "true"]);
    expect(pills()[0].querySelector("path")!.getAttribute("fill")).toBe("currentColor");
    expect(pills()[1].querySelector("path")!.getAttribute("fill")).toBe("none");
    expect(pills()[0].textContent).toBe("");
  });

  it("one tap likes, a second tap unlikes, with no separate button", async () => {
    await render(({ SetLikePill }) => <SetLikePill setId={B} />);
    await act(async () => pills()[0].click());
    expect(pills()[0].getAttribute("aria-pressed")).toBe("true");
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({ liked: true, setId: B });
    await act(async () => pills()[0].click());
    expect(pills()[0].getAttribute("aria-pressed")).toBe("false");
    expect(JSON.parse(fetchMock.mock.calls[2][1].body)).toEqual({ liked: false, setId: B });
  });

  it("reverts when the save fails", async () => {
    await render(({ SetLikePill }) => <SetLikePill setId={B} />);
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    fetchMock.mockImplementationOnce(async () => new Response("{}", { status: 500 }));
    await act(async () => pills()[0].click());
    expect(pills()[0].getAttribute("aria-pressed")).toBe("false");
  });

  it("asks a signed-out viewer to sign in instead of liking", async () => {
    useSession.mockReturnValue({ status: "unauthenticated" });
    await render(({ SetLikePill, LikedFilterButton }) => (<><SetLikePill setId={B} /><LikedFilterButton active={false} onChange={() => undefined} /></>));
    expect(fetchMock).not.toHaveBeenCalled();
    await act(async () => pills()[0].click());
    await act(async () => pills()[1].click());
    expect(signIn).toHaveBeenCalledTimes(2);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("stays inert with no session provider", async () => {
    const mod = await import("./set-likes");
    host = document.createElement("div");
    document.body.append(host);
    root = createRoot(host);
    await act(async () => root.render(<mod.SetLikePill setId={B} />));
    await act(async () => pills()[0].click());
    expect(fetchMock).not.toHaveBeenCalled();
    expect(signIn).not.toHaveBeenCalled();
  });

  it("uses the server's liked state on the set page before the list loads", async () => {
    fetchMock.mockImplementation(() => new Promise(() => undefined));
    await render(({ SetLikePill }) => <SetLikePill initialLiked setId={B} size="page" />);
    expect(pills()[0].getAttribute("aria-pressed")).toBe("true");
  });

  it("the Liked filter toggles on and off and says only 'Liked'", async () => {
    const onChange = vi.fn();
    await render(({ LikedFilterButton }) => <LikedFilterButton active={false} onChange={onChange} />);
    expect(pills()[0].textContent).toBe("Liked");
    await act(async () => pills()[0].click());
    expect(onChange).toHaveBeenCalledWith(true);
  });
});
