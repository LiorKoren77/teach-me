"use client";

// A fixed box, so a page that arrives late does not push the teaching text around: a portrait
// page scaled to 140px wide is about 198px tall, and anything else is fitted inside that.
const WIDTH = 140;
const HEIGHT = 198;

// Presentational: the bytes are fetched by hooks/usePageImage and arrive here as an object URL
// (`null` while it is on the way, or if it failed), and opening it is the caller's business.
export function FigureThumbnail({ src, label, onOpen }: { src: string | null; label: string; onOpen: () => void }) {
  return (
    <button
      type="button"
      onClick={onOpen}
      disabled={src === null}
      aria-label={label}
      className="shrink-0 rounded border border-stone-300 bg-white p-1 enabled:hover:border-stone-500"
    >
      {src === null ? (
        <span aria-hidden="true" className="block animate-pulse rounded bg-stone-100" style={{ width: WIDTH, height: HEIGHT }} />
      ) : (
        /* A page rendered on demand by the API and already fetched; next/image would only add a
           second, needless optimizer in front of an object URL it cannot read anyway. */
        /* eslint-disable-next-line @next/next/no-img-element */
        <img src={src} alt={label} width={WIDTH} height={HEIGHT} className="block object-contain" />
      )}
      <span className="mt-1 block text-center text-xs text-stone-600" style={{ width: WIDTH }}>
        {label}
      </span>
    </button>
  );
}
