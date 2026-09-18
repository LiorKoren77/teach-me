import type { Language } from "./api/types";

export const LANGUAGE_COOKIE = "teachme_lang";

export function readLanguage(): Language {
  if (typeof document === "undefined") return "en";
  const match = document.cookie.match(new RegExp(`${LANGUAGE_COOKIE}=(he|en|pt)`));
  if (match) return match[1] as Language;
  try {
    const stored = window.localStorage.getItem(LANGUAGE_COOKIE);
    if (stored === "he" || stored === "en" || stored === "pt") return stored;
  } catch {
    /* storage unavailable */
  }
  return "en";
}

export function writeLanguage(code: Language): void {
  document.cookie = `${LANGUAGE_COOKIE}=${code}; path=/; max-age=31536000; samesite=lax`;
  try {
    window.localStorage.setItem(LANGUAGE_COOKIE, code);
  } catch {
    /* storage unavailable */
  }
}
