"use client";
import { useCallback, useSyncExternalStore } from "react";
import type { Language } from "@/lib/api/types";
import { readLanguage, writeLanguage } from "@/lib/language";

// The preference lives in a cookie (so the server layout can set <html dir>) with
// localStorage as a fallback: an external store, read through useSyncExternalStore so
// the server snapshot and the first client render agree.
function subscribe(onStoreChange: () => void) {
  window.addEventListener("storage", onStoreChange);
  return () => window.removeEventListener("storage", onStoreChange);
}

const serverSnapshot = (): Language => "en";

export function useLanguage(): { language: Language; chooseLanguage: (code: Language) => void } {
  const language = useSyncExternalStore(subscribe, readLanguage, serverSnapshot);
  const chooseLanguage = useCallback((code: Language) => {
    writeLanguage(code);
    // The root layout reads the cookie on the server to set lang and dir.
    window.location.reload();
  }, []);
  return { language, chooseLanguage };
}
