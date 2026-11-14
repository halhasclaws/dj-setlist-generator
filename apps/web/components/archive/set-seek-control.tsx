"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";

import { formatDuration } from "@/lib/archive/utils";

const seekKeys = new Set(["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home", "End", "PageUp", "PageDown"]);

/** Preview a gesture locally; the owning player receives only its final seek.
 * Key this component by source identity so an old gesture cannot seek a new set.
 */
export function SetSeekControl({
  currentTime, duration, disabled = false, className, id, label = "Seek within set", onCommit,
  appearance = "native", renderBefore,
}: {
  currentTime: number;
  duration: number;
  disabled?: boolean;
  className?: string;
  id?: string;
  label?: string;
  onCommit: (seconds: number) => void;
  appearance?: "native" | "timeline";
  renderBefore?: (displayedTime: number) => ReactNode;
}) {
  const total = Number.isFinite(duration) ? Math.max(0, duration) : 0;
  const clampPosition = (value: number) => Math.max(0, Math.min(value, total));
  const position = Number.isFinite(currentTime) ? clampPosition(currentTime) : 0;
  const unavailable = disabled || total <= 0;
  const [draft, setDraft] = useState<number | null>(null);
  const gesture = useRef<{ kind: "pointer" | "keyboard"; pointerId?: number; value: number | null; cancelled?: boolean; tracked?: boolean; touch?: boolean; startX?: number; startValue?: number; tapValue?: number | null; left?: number; width?: number } | null>(null);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; gesture.current = null; };
  }, []);

  const cancel = () => {
    if (gesture.current) gesture.current.cancelled = true;
    setDraft(null);
  };
  useEffect(() => {
    if (gesture.current) gesture.current.cancelled = true;
    setDraft(null);
  }, [unavailable, total]);
  const commit = (value: number) => {
    gesture.current = null;
    setDraft(null);
    if (mounted.current && !unavailable && Number.isFinite(value)) onCommit(clampPosition(value));
  };
  // Spotify-style scrubbing. A click or tap jumps to that spot. With a mouse or
  // pen, dragging jumps to the press point and follows the cursor. With a
  // finger, dragging moves relative to the current time, so the playhead does
  // not jump under the thumb. The track handles this itself because iOS Safari
  // only moves a native range from its thumb.
  const dragThreshold = 4;
  const trackRect = (element: HTMLElement) => {
    const rect = element.getBoundingClientRect();
    return rect.width > 0 ? rect : null;
  };
  const valueAt = (clientX: number, left: number, width: number) =>
    clampPosition(Math.round((clientX - left) / width * total));
  const displayed = unavailable ? position : draft ?? position;
  const valueText = `${formatDuration(displayed)} of ${formatDuration(total)}`;

  return (
    <div className="set-seek-control">
      {renderBefore?.(displayed)}
      <div className={appearance === "timeline" ? "set-seek-timeline" : undefined}>
        <input
          id={id}
          className={appearance === "timeline" ? "set-seek-input" : className}
          type="range"
          min={0}
          max={total}
          step={1}
          value={displayed}
          aria-label={label}
          aria-valuetext={valueText}
          disabled={unavailable}
          onPointerDown={(event) => {
            if (unavailable || event.button !== 0 || event.isPrimary === false || (gesture.current && !gesture.current.cancelled)) return;
            const rect = Number.isFinite(event.clientX) ? trackRect(event.currentTarget) : null;
            const touch = event.pointerType === "touch";
            const pressed = rect ? valueAt(event.clientX, rect.left, rect.width) : null;
            gesture.current = { kind: "pointer", pointerId: event.pointerId, tracked: rect !== null, touch,
              startX: event.clientX, startValue: position, tapValue: pressed, left: rect?.left, width: rect?.width,
              value: touch ? null : pressed };
            setDraft(touch ? position : pressed ?? position);
            event.currentTarget.setPointerCapture?.(event.pointerId);
          }}
          onPointerMove={(event) => {
            const current = gesture.current;
            if (current?.kind !== "pointer" || !current.tracked || current.cancelled || current.pointerId !== event.pointerId) return;
            const width = current.width ?? 1;
            let value: number;
            if (current.touch) {
              const dx = event.clientX - (current.startX ?? event.clientX);
              if (!Number.isFinite(dx) || (current.value === null && Math.abs(dx) < dragThreshold)) return;
              value = clampPosition(Math.round((current.startValue ?? position) + dx / width * total));
            } else {
              if (!Number.isFinite(event.clientX)) return;
              value = valueAt(event.clientX, current.left ?? 0, width);
            }
            current.value = value;
            setDraft(value);
          }}
          onChange={(event) => {
            if (unavailable || gesture.current?.cancelled) return;
            const seconds = Number(event.currentTarget.value);
            if (!Number.isFinite(seconds)) return;
            const value = clampPosition(seconds);
            if (gesture.current?.tracked) return; // pointer position owns this gesture
            if (gesture.current) {
              gesture.current.value = value;
              setDraft(value);
            } else {
              // Screen readers and other native range controls may change the
              // value without a pointer/key gesture. Each is a complete action.
              commit(value);
            }
          }}
          onPointerUp={(event) => {
            const current = gesture.current;
            if (current?.kind !== "pointer" || current.pointerId !== event.pointerId) return;
            // A finger lifted without dragging is a tap: seek to where it landed.
            const value = current.value ?? (current.tracked ? current.tapValue ?? null : null);
            if (current.cancelled || value === null) { cancel(); gesture.current = null; }
            else commit(value);
            if (event.currentTarget.hasPointerCapture?.(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
          }}
          onPointerCancel={(event) => {
            if (gesture.current?.pointerId === event.pointerId) cancel();
          }}
          onLostPointerCapture={(event) => {
            if (gesture.current?.pointerId === event.pointerId) cancel();
          }}
          onKeyDown={(event) => {
            if (event.key === "Escape") { event.preventDefault(); cancel(); return; }
            if (event.repeat && gesture.current?.cancelled) return;
            if (!unavailable && seekKeys.has(event.key) && (!gesture.current || gesture.current.cancelled)) {
              gesture.current = { kind: "keyboard", value: null };
              setDraft(position);
            }
          }}
          onKeyUp={(event) => {
            if (!seekKeys.has(event.key) || gesture.current?.kind !== "keyboard") return;
            const value = gesture.current.value;
            if (gesture.current.cancelled || value === null) { cancel(); gesture.current = null; }
            else commit(value);
          }}
          onFocus={() => { if (gesture.current?.cancelled) gesture.current = null; }}
          onBlur={cancel}
        />
        {appearance === "timeline" ? (
          <div className={className} aria-hidden="true">
            <div className="dock-progress-fill" id={id ? `${id}Fill` : undefined}
              style={{ width: `${total > 0 ? displayed / total * 100 : 0}%` }} />
          </div>
        ) : null}
      </div>
    </div>
  );
}
