import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { FigureThumbnail } from "./FigureThumbnail";
import type { Strings } from "@/lib/i18n";

// Only teaching text reaches this component, so it may be rendered as Markdown. Student-written
// text (answers) is plain text and goes to QuestionCard/FeedbackCard instead.
const PROSE = "prose prose-stone max-w-none text-stone-900 [&_h1]:text-xl [&_h2]:text-lg [&_ul]:list-disc [&_ul]:ps-6 [&_ol]:list-decimal [&_ol]:ps-6 [&_p]:my-3 [&_table]:border-collapse [&_td]:border [&_th]:border [&_td]:px-2 [&_th]:px-2";

/** One source page: the index it refers to and its image once the hook has fetched it. */
export type Figure = { page: number; src: string | null };

function openFigure(src: string | null) {
  if (src) window.open(src, "_blank", "noopener,noreferrer");
}

export function TeachingPane({ title, body, keyPoints, figures, strings, reexplanation }: {
  title: string; body: string; keyPoints: string[]; figures: Figure[]; strings: Strings;
  reexplanation: string | null;
}) {
  return (
    <section className="flex flex-col gap-4 rounded-lg border border-stone-200 bg-white p-5">
      {reexplanation ? (
        <div className="rounded border border-amber-300 bg-amber-50 p-4">
          <p className="mb-2 text-sm font-medium text-amber-900">{strings.reexplaining}</p>
          <div className={PROSE}>
            <Markdown remarkPlugins={[remarkGfm]}>{reexplanation}</Markdown>
          </div>
        </div>
      ) : null}

      <h2 className="text-sm font-medium text-stone-500">{strings.teaching}</h2>
      <h3 className="text-xl font-semibold">{title}</h3>
      <div className={PROSE}>
        <Markdown remarkPlugins={[remarkGfm]}>{body}</Markdown>
      </div>

      {keyPoints.length === 0 ? null : (
        <div>
          <h3 className="text-sm font-medium text-stone-900">{strings.keyPoints}</h3>
          <ul className="mt-1 list-disc ps-6 text-sm text-stone-700">
            {keyPoints.map((point) => (
              <li key={point}>{point}</li>
            ))}
          </ul>
        </div>
      )}

      {figures.length === 0 ? null : (
        <div className="flex gap-3 overflow-x-auto pb-1">
          {figures.map(({ page, src }) => (
            <FigureThumbnail key={page} src={src} label={strings.figurePage(page)} onOpen={() => openFigure(src)} />
          ))}
        </div>
      )}
    </section>
  );
}
