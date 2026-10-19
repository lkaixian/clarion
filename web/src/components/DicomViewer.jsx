// P4.7: embedded DICOM viewer using dwv (MIT, the
// library the vault's PACS research note names for this -- see
// healthcare/PACS and DICOM.md). Loads every instance of one study
// straight from the authenticated backend proxy (routers/pacs.py) via
// dwv's own `requestHeaders` support -- no separate blob-fetch step.
import { useEffect, useRef, useState } from "react";
import { App, AppOptions, ViewConfig } from "dwv";
import { getDicomStudy, dicomInstanceFileUrl } from "../api/client";
import { tr } from "../lib/i18n";

const TOOLS = [
  { key: "WindowLevel", label: "Window/Level" },
  { key: "ZoomAndPan", label: "Zoom/Pan" },
  { key: "Scroll", label: "Scroll" },
  { key: "Ruler", label: "Measure" }, // Draw tool + Ruler shape, see below
];

export default function DicomViewer({ requestId, onClose }) {
  const containerRef = useRef(null);
  const appRef = useRef(null);
  const [status, setStatus] = useState("loading"); // "loading" | "ready" | "error"
  const [error, setError] = useState("");
  const [tool, setToolState] = useState("ZoomAndPan");

  useEffect(() => {
    let cancelled = false;
    let app = null;

    getDicomStudy(requestId)
      .then((study) => {
        if (cancelled || !containerRef.current) return;

        const viewConfig = new ViewConfig("dwv-layer-group");
        const options = new AppOptions({ "*": [viewConfig] });
        options.tools = {
          WindowLevel: {}, ZoomAndPan: {}, Scroll: {}, Draw: { options: ["Ruler"] },
        };
        app = new App();
        appRef.current = app;
        app.init(options);

        app.addEventListener("load", () => {
          if (cancelled) return;
          app.setTool("ZoomAndPan");
          setStatus("ready");
        });
        app.addEventListener("error", (event) => {
          if (cancelled) return;
          setError(event?.detail?.error?.message || "Could not decode this study's imaging data.");
          setStatus("error");
        });

        const token = localStorage.getItem("mb_token");
        const urls = study.instances.map((id) => dicomInstanceFileUrl(requestId, id));
        app.loadURLs(urls, {
          requestHeaders: token ? [{ name: "Authorization", value: `Bearer ${token}` }] : [],
        });
      })
      .catch((e) => {
        if (cancelled) return;
        setError(e?.response?.data?.detail || "Failed to load imaging study.");
        setStatus("error");
      });

    return () => {
      cancelled = true;
      // dwv has no public "destroy", but the app + its listeners are
      // dropped with this component's DOM on unmount -- nothing else here
      // holds a timer/interval that would outlive it.
      appRef.current = null;
    };
  }, [requestId]);

  function activateTool(key) {
    const app = appRef.current;
    if (!app || status !== "ready") return;
    setToolState(key);
    if (key === "Ruler") {
      app.setTool("Draw");
      app.setToolFeatures({ shapeName: "Ruler" });
    } else {
      app.setTool(key);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/70 z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-xl w-full max-w-4xl h-[85vh] flex flex-col overflow-hidden">
        <div className="flex items-center justify-between px-4 py-2 border-b border-slate-200">
          <div className="flex items-center gap-1">
            {TOOLS.map((t) => (
              <button
                key={t.key}
                onClick={() => activateTool(t.key)}
                disabled={status !== "ready"}
                className={`text-xs px-2.5 py-1.5 rounded disabled:opacity-40 ${
                  tool === t.key ? "bg-blue-600 text-white" : "bg-slate-100 text-slate-700 hover:bg-slate-200"
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-800 text-sm px-2">{tr("✕ Close")}</button>
        </div>

        <div className="relative flex-1 bg-black">
          {/* dwv renders its canvases into this div -- it needs a real
              pixel size, not just flex-1, so it's absolutely positioned to
              fill the parent (dwv reads clientWidth/clientHeight on load). */}
          <div id="dwv-layer-group" ref={containerRef} className="absolute inset-0" />
          {status === "loading" && (
            <p className="absolute inset-0 flex items-center justify-center text-sm text-slate-300">{tr("Loading imaging…")}</p>
          )}
          {status === "error" && (
            <p className="absolute inset-0 flex items-center justify-center text-sm text-red-300 px-6 text-center">{error}</p>
          )}
        </div>
      </div>
    </div>
  );
}
