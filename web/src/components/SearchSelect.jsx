import { useEffect, useMemo, useRef, useState } from "react";
import { tr } from "../lib/i18n";

const MAX_SHOWN = 50;

// Narrowing match: every typed word must appear somewhere in the label, so each extra
// word or letter shrinks the list. Labels that start with the typed text come first.
export function filterOptions(options, query) {
  const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return options;
  const q = query.trim().toLowerCase();
  const hits = options.filter((o) => {
    const l = o.label.toLowerCase();
    return words.every((w) => l.includes(w));
  });
  return [...hits.filter((o) => o.label.toLowerCase().startsWith(q)), ...hits.filter((o) => !o.label.toLowerCase().startsWith(q))];
}

// A type-to-search picker. `value` is the chosen option id ("" for none); `onChange(id)` fires
// when one is picked, and with "" as soon as the typed text no longer matches the pick.
export default function SearchSelect({ id, options, value, onChange, placeholder = "Type to search", required = false, disabled = false }) {
  const selected = options.find((o) => o.id === value) || null;
  const [text, setText] = useState(selected ? selected.label : "");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const boxRef = useRef(null);
  const listId = `${id}-list`;

  // The parent changed the value (e.g. switched source, form reset): follow it.
  useEffect(() => {
    setText(selected ? selected.label : (value ? text : ""));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value, selected?.label]);

  useEffect(() => {
    if (!open) return undefined;
    const close = (e) => { if (boxRef.current && !boxRef.current.contains(e.target)) setOpen(false); };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  const matches = useMemo(() => filterOptions(options, selected && text === selected.label ? "" : text), [options, text, selected]);
  const shown = matches.slice(0, MAX_SHOWN);

  function pick(o) {
    onChange(o.id);
    setText(o.label);
    setOpen(false);
  }

  function onType(e) {
    setText(e.target.value);
    setOpen(true);
    setActive(0);
    if (value) onChange(""); // typing again means "not that one any more"
  }

  function onKeyDown(e) {
    if (e.key === "ArrowDown") { e.preventDefault(); setOpen(true); setActive((a) => Math.min(a + 1, shown.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
    else if (e.key === "Enter" && open && shown[active]) { e.preventDefault(); pick(shown[active]); }
    else if (e.key === "Escape") setOpen(false);
  }

  return (
    <div ref={boxRef} className="relative">
      <input
        id={id} type="text" role="combobox" aria-expanded={open} aria-controls={listId} aria-autocomplete="list"
        aria-activedescendant={open && shown[active] ? `${id}-opt-${active}` : undefined}
        autoComplete="off" className="field-input" placeholder={placeholder} value={text} disabled={disabled}
        required={required && !value}
        onChange={onType} onFocus={() => setOpen(true)} onKeyDown={onKeyDown}
      />
      {open && (
        <ul id={listId} role="listbox"
          className="absolute z-20 mt-1 max-h-64 w-full overflow-y-auto rounded-lg border border-slate-200 bg-white shadow-lg">
          {shown.length === 0 && <li role="option" aria-disabled="true" aria-selected="false" className="px-3 py-2 text-sm text-slate-500">{tr("No match. Keep typing or clear the box.")}</li>}
          {shown.map((o, i) => (
            <li
              key={o.id} id={`${id}-opt-${i}`} role="option" aria-selected={o.id === value}
              onMouseDown={(e) => { e.preventDefault(); pick(o); }}
              onMouseEnter={() => setActive(i)}
              className={`cursor-pointer px-3 py-2 text-sm ${i === active ? "bg-blue-50 text-blue-900" : "text-slate-800"}`}
            >
              {o.label}
            </li>
          ))}
          {matches.length > MAX_SHOWN && (
            <li role="option" aria-disabled="true" aria-selected="false" className="border-t border-slate-100 px-3 py-1.5 text-xs text-slate-500">
              Showing {MAX_SHOWN} of {matches.length}. Type more to narrow.
            </li>
          )}
        </ul>
      )}
    </div>
  );
}
