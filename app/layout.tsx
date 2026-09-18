import { ClerkProvider } from "@clerk/nextjs";
import { cookies } from "next/headers";
import type { ReactNode } from "react";
import "./globals.css";
import { directionOf } from "@/lib/i18n";
import { LANGUAGE_COOKIE } from "@/lib/language";
import type { Language } from "@/lib/api/types";

export const metadata = { title: "teach-me" };

export default async function RootLayout({ children }: { children: ReactNode }) {
  const store = await cookies();
  const raw = store.get(LANGUAGE_COOKIE)?.value;
  const language: Language = raw === "he" || raw === "pt" ? raw : "en";
  return (
    <ClerkProvider>
      <html lang={language} dir={directionOf(language)}>
        <body className="min-h-screen bg-stone-50 text-stone-900 antialiased">{children}</body>
      </html>
    </ClerkProvider>
  );
}
