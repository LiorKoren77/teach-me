"use client";
import { pageImageUrl } from "@/lib/api/subjects";

export function FigureThumbnail({ subjectId, pageIndex, label }: { subjectId: string; pageIndex: number; label: string }) {
  const src = pageImageUrl(subjectId, pageIndex);
  return (
    <button
      type="button"
      onClick={() => window.open(src, "_blank", "noopener,noreferrer")}
      className="shrink-0 rounded border border-stone-300 bg-white p-1 hover:border-stone-500"
    >
      {/* A page rendered on demand by the API; next/image would only add a second, needless
          optimizer in front of an endpoint that already caches its PNG. */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={src} alt={label} loading="lazy" className="block max-w-[140px]" />
      <span className="mt-1 block text-center text-xs text-stone-600">{label}</span>
    </button>
  );
}
