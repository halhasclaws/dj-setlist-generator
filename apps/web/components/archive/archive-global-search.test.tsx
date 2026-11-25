// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

describe("header search panel focus", () => {
  let root: Root;
  let host: HTMLDivElement;
  const fetchMock = vi.fn();

  const trigger = () => host.querySelector<HTMLButtonElement>('button[title="Search"]')!;
  const input = () => host.querySelector<HTMLInputElement>('input[type="search"]');

  beforeEach(async () => {
    vi.resetModules();
    vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
    vi.stubGlobal("fetch", fetchMock);
    fetchMock.mockImplementation(async () => new Response(null, { status: 404 }));
    const { ArchiveGlobalSearch } = await import("./archive-global-search");
    host = document.createElement("div");
    document.body.append(host);
    root = createRoot(host);
    await act(async () => root.render(<ArchiveGlobalSearch />));
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    host.remove();
    vi.unstubAllGlobals();
    vi.resetAllMocks();
  });

  it("focuses the input inside the click itself, so iOS opens the keyboard", async () => {
    let focusedDuringClick: Element | null = null;
    // Runs after React's own click handler, still inside the same dispatch.
    host.addEventListener("click", () => {
      focusedDuringClick = document.activeElement;
    });

    await act(async () => trigger().click());

    expect(input()).not.toBeNull();
    expect(focusedDuringClick).toBe(input());
    expect(document.activeElement).toBe(input());
  });

  it("focuses the input when the / shortcut opens the panel", async () => {
    let focusedDuringKey: Element | null = null;
    const key = new KeyboardEvent("keydown", { bubbles: true, cancelable: true, key: "/" });
    window.addEventListener("keydown", () => { focusedDuringKey = document.activeElement; });

    await act(async () => { document.body.dispatchEvent(key); });

    expect(key.defaultPrevented).toBe(true);
    expect(focusedDuringKey).toBe(input());
    expect(document.activeElement).toBe(input());
  });

  it("closes again on a second click of the icon", async () => {
    await act(async () => trigger().click());
    await act(async () => trigger().click());
    expect(input()).toBeNull();
  });
});
