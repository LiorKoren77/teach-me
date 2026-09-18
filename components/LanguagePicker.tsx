"use client";
import { LANGUAGES } from "@/lib/i18n";
import type { Language } from "@/lib/api/types";

export function LanguagePicker({ value, options, onChange, label }: {
  value: Language; options: Language[]; onChange: (code: Language) => void; label: string;
}) {
  return (
    <label className="flex items-center gap-2 text-sm">
      <span>{label}</span>
      <select className="rounded border px-2 py-1" value={value} onChange={(e) => onChange(e.target.value as Language)} aria-label={label}>
        {LANGUAGES.filter((l) => options.includes(l.code)).map((l) => (
          <option key={l.code} value={l.code}>{l.name}</option>
        ))}
      </select>
    </label>
  );
}
