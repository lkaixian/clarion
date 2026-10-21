import { useEffect, useRef, useState } from "react";
import iconUrl from "leaflet/dist/images/marker-icon.png";
import iconRetinaUrl from "leaflet/dist/images/marker-icon-2x.png";
import shadowUrl from "leaflet/dist/images/marker-shadow.png";
import { getScanLocations } from "../api/client";
import { formatDateTime } from "../lib/format";
import { tr } from "../lib/i18n";

// Tile source, ONE place. The viewer's browser fetches tiles straight from OpenStreetMap
// (their IP and the viewed area are visible to OSM). For production swap this for a
// self-hosted tile server and add its origin to img-src in proxy/Caddyfile (docs/deployment.md).
export const TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';

const TIER = { public: "Public scan", responder: "Responder", paramedic: "Paramedic", clinical: "Clinician" };
export const who = (l) => [tr(TIER[l.tier] || "Scanner"), l.actor_facility].filter(Boolean).join(" - ");
export const mapsUrl = (l) => `https://www.google.com/maps/search/?api=1&query=${l.lat},${l.lng}`;
const accuracy = (l) => (l.accuracy_m != null ? `${tr("Accuracy")}: ~${Math.round(l.accuracy_m)} m` : "");

// Leaflet is imported on demand so it stays out of the main bundle. The list and the
// caption render without it, so the information is there even if the map fails to load.
export default function ScanMap({ locations }) {
  const el = useRef(null);
  const [mapError, setMapError] = useState(false);

  useEffect(() => {
    if (!locations.length || !el.current) return undefined;
    let map = null;
    let dead = false;
    (async () => {
      try {
        const [{ default: L }] = await Promise.all([import("leaflet"), import("leaflet/dist/leaflet.css")]);
        if (dead || !el.current) return;
        const base = { iconUrl, iconRetinaUrl, shadowUrl, iconSize: [25, 41], iconAnchor: [12, 41], popupAnchor: [1, -34], shadowSize: [41, 41] };
        map = L.map(el.current);
        L.tileLayer(TILE_URL, { maxZoom: 19, attribution: ATTRIBUTION }).addTo(map);
        const pts = [];
        locations.forEach((l, i) => {
          const p = [l.lat, l.lng];
          pts.push(p);
          if (l.accuracy_m != null) L.circle(p, { radius: l.accuracy_m, weight: 1 }).addTo(map);
          // newest first: index 0 is the emphasised marker
          const m = L.marker(p, {
            icon: L.icon(base),
            opacity: i === 0 ? 1 : 0.6,
            zIndexOffset: i === 0 ? 1000 : 0,
            keyboard: false, // the list below is the keyboard path
          }).addTo(map);
          const pop = document.createElement("div");
          [formatDateTime(l.created_at), who(l), accuracy(l)].filter(Boolean).forEach((t, k) => {
            const d = document.createElement(k === 0 ? "strong" : "div");
            d.textContent = t; // textContent: facility names are data, never HTML
            pop.appendChild(d);
          });
          m.bindPopup(pop);
        });
        map.fitBounds(pts, { padding: [30, 30], maxZoom: 16 });
      } catch {
        if (!dead) setMapError(true);
      }
    })();
    return () => { dead = true; if (map) map.remove(); };
  }, [locations]);

  if (!locations.length) return <p className="text-sm text-slate-500">{tr("This card has not been scanned with a shared location yet.")}</p>;

  return (
    <div>
      {mapError
        ? <p role="alert" className="mb-2 text-sm text-amber-800">{tr("The map could not be loaded. The list below still shows each place.")}</p>
        : <div ref={el} role="region" aria-label={tr("Map of where the card was scanned")} data-testid="scan-map" className="h-72 w-full rounded-lg border border-slate-200" />}
      <p className="mt-2 text-xs text-slate-500">{tr("Reported by the scanner's phone, not verified.")}</p>
      <ul className="mt-2 divide-y divide-slate-100 text-sm">
        {locations.map((l, i) => (
          <li key={l.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
            <span>
              <span className={i === 0 ? "font-semibold" : ""}>{formatDateTime(l.created_at)}</span>
              {i === 0 && <span className="ml-2 rounded bg-blue-100 px-1.5 py-0.5 text-xs text-blue-800">{tr("Latest")}</span>}
              <span className="block text-slate-600">{who(l)}{accuracy(l) && ` (${accuracy(l)})`}</span>
            </span>
            <a href={mapsUrl(l)} target="_blank" rel="noopener noreferrer" className="text-blue-700 underline">{tr("Open in Maps")}</a>
          </li>
        ))}
      </ul>
    </div>
  );
}

// Fetches and shows the places a patient's card was scanned. 403 / error never break the page.
export function ScanLocations({ patientId }) {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    let dead = false;
    setRows(null); setError(false);
    getScanLocations(patientId)
      .then((r) => { if (!dead) setRows(Array.isArray(r) ? r : []); })
      .catch((e) => { if (!dead) { if (e?.response?.status === 403) setRows([]); else setError(true); } });
    return () => { dead = true; };
  }, [patientId]);
  if (error) return <p className="text-sm text-slate-500">{tr("Could not load scan locations.")}</p>;
  if (rows === null) return <p className="text-sm text-slate-400">{tr("Loading…")}</p>;
  return <ScanMap locations={rows} />;
}
