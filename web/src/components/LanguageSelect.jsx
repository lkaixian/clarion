import { LANGUAGES, setLang, useLang } from "../lib/i18n";

export default function LanguageSelect({ className = "" }) {
  const { lang, t } = useLang();
  return (
    <select
      aria-label={t("Language")} value={lang} onChange={(e) => setLang(e.target.value)}
      className={`rounded-lg border border-slate-300 bg-white px-2 py-1 text-xs text-slate-700 ${className}`}
    >
      {LANGUAGES.map(([code, name]) => <option key={code} value={code} lang={code}>{name}</option>)}
    </select>
  );
}
