import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";

// Turn a PNG data-URL (canvas.toDataURL("image/png") output) into a Blob so
// callers can POST it as multipart form-data. Also tolerates a bare base64
// string (no "data:...," prefix). Returns null for empty input.
export function dataUrlToPngBlob(dataUrl) {
  if (!dataUrl) return null;
  const comma = dataUrl.indexOf(",");
  const b64 = comma >= 0 ? dataUrl.slice(comma + 1) : dataUrl;
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i += 1) bytes[i] = bin.charCodeAt(i);
  return new Blob([bytes], { type: "image/png" });
}

// CSS layout size of the pad. The backing <canvas> store is scaled up by
// devicePixelRatio (below) so strokes stay crisp on HiDPI screens.
const WIDTH = 360;
const HEIGHT = 140;

// Raw-<canvas> signature capture (no drawing library — see the repo's
// no-external-deps rule). One <canvas> the user draws on with pointer events
// (covers mouse + touch + stylus in one code path). `onChange` fires with
// the current PNG data-URL on every stroke-end, and with null on clear / when
// nothing has been drawn. An imperative ref also exposes { toDataURL, toBlob,
// clear, isEmpty } for callers that need to pull the value on submit.
const SignaturePad = forwardRef(function SignaturePad(
  { onChange, disabled = false, className = "" },
  ref,
) {
  const canvasRef = useRef(null);
  const ctxRef = useRef(null);
  const drawingRef = useRef(false);
  const dirtyRef = useRef(false); // has anything been drawn since the last clear?
  const [showHint, setShowHint] = useState(true);

  // Size the backing store at devicePixelRatio while keeping the element laid
  // out at WIDTH x HEIGHT CSS px, then prime the white background + stroke
  // style. Runs once — the pad is a fixed size.
  useEffect(() => {
    const canvas = canvasRef.current;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = WIDTH * dpr;
    canvas.height = HEIGHT * dpr;
    const ctx = canvas.getContext("2d");
    ctx.scale(dpr, dpr);
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, WIDTH, HEIGHT);
    ctx.lineWidth = 2;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.strokeStyle = "#1e293b"; // slate-800
    ctxRef.current = ctx;
  }, []);

  // Map a pointer event to canvas coordinates, correcting for any CSS scaling
  // of the element vs. its logical WIDTH/HEIGHT.
  function pointFromEvent(e) {
    const rect = canvasRef.current.getBoundingClientRect();
    return {
      x: (e.clientX - rect.left) * (WIDTH / rect.width),
      y: (e.clientY - rect.top) * (HEIGHT / rect.height),
    };
  }

  function currentDataUrl() {
    return dirtyRef.current ? canvasRef.current.toDataURL("image/png") : null;
  }

  function handlePointerDown(e) {
    if (disabled) return;
    e.preventDefault();
    drawingRef.current = true;
    dirtyRef.current = true;
    setShowHint(false);
    const { x, y } = pointFromEvent(e);
    const ctx = ctxRef.current;
    ctx.beginPath();
    ctx.moveTo(x, y);
    // Draw a tiny segment so a single tap (no movement) still leaves a dot.
    ctx.lineTo(x + 0.01, y + 0.01);
    ctx.stroke();
    if (e.pointerId != null && canvasRef.current.setPointerCapture) {
      try { canvasRef.current.setPointerCapture(e.pointerId); } catch { /* not fatal */ }
    }
  }

  function handlePointerMove(e) {
    if (!drawingRef.current) return;
    e.preventDefault();
    const { x, y } = pointFromEvent(e);
    const ctx = ctxRef.current;
    ctx.lineTo(x, y);
    ctx.stroke();
  }

  function handlePointerUp() {
    if (!drawingRef.current) return;
    drawingRef.current = false;
    onChange?.(currentDataUrl());
  }

  function clear() {
    const ctx = ctxRef.current;
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, WIDTH, HEIGHT);
    dirtyRef.current = false;
    drawingRef.current = false;
    setShowHint(true);
    onChange?.(null);
  }

  useImperativeHandle(ref, () => ({
    toDataURL: currentDataUrl,
    toBlob: () => dataUrlToPngBlob(currentDataUrl()),
    clear,
    isEmpty: () => !dirtyRef.current,
  }));

  return (
    <div className={className}>
      <canvas
        ref={canvasRef}
        // touch-action:none stops the browser from scrolling/zooming the page
        // out from under a finger mid-stroke.
        style={{ width: WIDTH, height: HEIGHT, touchAction: "none" }}
        className={`border border-slate-300 rounded-lg bg-white ${
          disabled ? "opacity-50" : "cursor-crosshair"
        }`}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerLeave={handlePointerUp}
        onPointerCancel={handlePointerUp}
      />
      <div className="mt-1 flex items-center gap-3">
        <button
          type="button"
          onClick={clear}
          disabled={disabled}
          className="text-xs text-blue-700 disabled:opacity-50"
        >
          Clear
        </button>
        {showHint && <span className="text-xs text-slate-400">Draw your signature above</span>}
      </div>
    </div>
  );
});

export default SignaturePad;
