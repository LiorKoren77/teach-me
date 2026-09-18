import type { ErrorKey } from "./api/errors";
import type { Grade, Language, PartStatus } from "./api/types";

export const LANGUAGES: { code: Language; name: string; dir: "ltr" | "rtl" }[] = [
  { code: "he", name: "עברית", dir: "rtl" },
  { code: "en", name: "English", dir: "ltr" },
  { code: "pt", name: "Português", dir: "ltr" },
];

export function directionOf(code: Language): "ltr" | "rtl" {
  return LANGUAGES.find((l) => l.code === code)?.dir ?? "ltr";
}

/**
 * Every string the UI shows, declared once. The table below is typed `Record<Language, Strings>`,
 * so a key missing from he or pt - or a formatter whose arguments drift - is a compile error
 * rather than an English word appearing in a Hebrew screen.
 */
export interface Strings {
  appName: string;
  signIn: string;
  subjects: string;
  noSubjects: string;
  partOf: (n: number, total: number) => string;
  partsPassed: (n: number, total: number) => string;
  sources: string;
  teaching: string;
  dialog: string;
  startRound: string;
  nextRound: string;
  continue: string;
  submit: string;
  answerPlaceholder: string;
  passed: string;
  failed: string;
  score: (pct: number) => string;
  roundsLeft: (n: number) => string;
  stalled: string;
  retry: string;
  locked: string;
  weakSections: string;
  reexplaining: string;
  /** The re-explanation stopped at the model's token ceiling, so it stops mid-thought. */
  truncated: string;
  keyPoints: string;
  /** Caption for a page image whose page prints no number of its own. */
  figure: string;
  figurePage: (printed: string) => string;
  pageCount: (n: number) => string;
  language: string;
  admin: string;
  questionOf: (i: number, total: number) => string;
  chooseOne: string;
  status: Record<PartStatus, string>;
  grade: Record<Grade, string>;
  errors: Record<ErrorKey, string>;
  adminRoleRequired: string;
  adminSubjects: string;
  adminUsage: string;
  /** Subject states and source ingestion statuses, keyed by the value the API sends. */
  adminState: Record<string, string>;
  sourceStatus: Record<string, string>;
  adminVersion: (v: number | null) => string;
  usage: Record<string, string>;
  // Admin upload pane and subject actions (stage 5).
  uploadSources: string;
  chooseFile: string;
  upload: string;
  uploading: string;
  acceptedTypes: (types: string) => string;
  uploadLocked: string;
  noSources: string;
  deleteSource: string;
  reingestSource: string;
  confirmDelete: (filename: string) => string;
  confirmReingest: (filename: string) => string;
  /** The language the ingestion detected in a source, as the ISO code the API reports. */
  detectedLanguage: (code: string) => string;
  subjectActions: string;
  generate: string;
  publish: string;
  unpublish: string;
  /** Job kinds and states, keyed by the value the API sends. */
  jobKind: Record<string, string>;
  jobStatus: Record<string, string>;
  jobLine: (kind: string, status: string) => string;
  partsReady: (ready: number, total: number) => string;
  questionsReady: (n: number) => string;
  failedParts: (positions: string) => string;
  publishable: (version: number) => string;
  notPublishable: string;
  publishedVersion: (v: number | null) => string;
}

const STRINGS: Record<Language, Strings> = {
  en: {
    appName: "teach-me", signIn: "Sign in", subjects: "Your subjects", noSubjects: "No published subjects yet.",
    partOf: (n: number, total: number) => `Part ${n} of ${total}`,
    partsPassed: (n: number, total: number) => `${n} of ${total} parts passed`, sources: "Sources", teaching: "Teaching",
    dialog: "Dialog", startRound: "Start the questions", nextRound: "Start the next round", continue: "Continue",
    submit: "Submit answer", answerPlaceholder: "Write your answer…", passed: "Part passed", failed: "Not yet",
    score: (pct: number) => `Score: ${pct}%`, roundsLeft: (n: number) => `${n} rounds left`, stalled: "Let's start this part again",
    retry: "Start again", locked: "Locked", weakSections: "We will go over:", reexplaining: "Explaining this differently…",
    truncated: "This explanation was cut short at its length limit.",
    keyPoints: "Key points", figure: "Figure", figurePage: (printed: string) => `Page ${printed}`, pageCount: (n: number) => (n === 1 ? "1 page" : `${n} pages`), language: "Language", admin: "Admin",
    questionOf: (i: number, total: number) => `Question ${i} of ${total}`, chooseOne: "Choose one",
    status: { not_started: "Not started", learning: "Reading", quizzing: "Answering", reinforcing: "Reviewing", passed: "Passed", stalled: "Stalled" },
    grade: { correct: "Correct", partial: "Partly right", incorrect: "Not right", off_topic: "Off topic", junk: "Unclear" },
    errors: {
      unauthorized: "Your session has ended - signing you in again.", forbidden: "You do not have access to this.",
      conflict: "This has already moved on. Reload the page to catch up.",
      payloadTooLarge: "That file is too large to upload.", unsupportedType: "That file type is not accepted.",
      rateLimited: "Too many requests. Wait a moment and try again.",
      unknown: "Something went wrong. Please try again.",
    },
    adminRoleRequired: "You need the admin role to view this page.",
    adminSubjects: "Subjects", adminUsage: "Usage",
    adminState: { draft: "Draft", published: "Published" },
    sourceStatus: { uploaded: "Uploaded", extracting: "Extracting", chunking: "Chunking", indexing: "Indexing", ready: "Ready", failed: "Failed" },
    adminVersion: (v: number | null) => (v === null ? "No outline yet" : `Version ${v}`),
    usage: { purpose: "Purpose", model: "Model", calls: "Calls", input: "Input tokens", output: "Output tokens", cost: "Cost", total: "Total" },
    uploadSources: "Upload sources", chooseFile: "Choose a file", upload: "Upload", uploading: "Uploading…",
    acceptedTypes: (types: string) => `Accepted: ${types}`,
    uploadLocked: "A published subject is locked; unpublish it to change its sources.", noSources: "No sources yet.",
    deleteSource: "Delete", reingestSource: "Re-ingest",
    confirmDelete: (filename: string) => `Delete ${filename} and everything indexed from it?`,
    confirmReingest: (filename: string) => `Ingest ${filename} again from the start?`,
    detectedLanguage: (code: string) => `Language: ${code}`,
    subjectActions: "Subject", generate: "Generate", publish: "Publish", unpublish: "Unpublish",
    jobKind: { ingest_source: "Ingesting", generate_subject: "Generating", generate_unit: "Generating" },
    jobStatus: { queued: "Queued", running: "Running", done: "Done", failed: "Failed" },
    jobLine: (kind: string, status: string) => `${kind}: ${status}`,
    partsReady: (ready: number, total: number) => `${ready} of ${total} parts ready`,
    questionsReady: (n: number) => `${n} questions`,
    failedParts: (positions: string) => `Parts that failed: ${positions}`,
    publishable: (version: number) => `Version ${version} is ready to publish`,
    notPublishable: "Not every language is complete yet.",
    publishedVersion: (v: number | null) => (v === null ? "Not published" : `Published version ${v}`),
  },
  he: {
    appName: "teach-me", signIn: "כניסה", subjects: "המקצועות שלך", noSubjects: "אין עדיין מקצועות זמינים.",
    partOf: (n: number, total: number) => `חלק ${n} מתוך ${total}`,
    partsPassed: (n: number, total: number) => `${n} מתוך ${total} חלקים הושלמו`, sources: "מקורות", teaching: "הוראה",
    dialog: "שיחה", startRound: "התחלת השאלות", nextRound: "התחלת הסבב הבא", continue: "המשך",
    submit: "שליחת תשובה", answerPlaceholder: "כתבו את תשובתכם…", passed: "החלק הושלם", failed: "עוד לא",
    score: (pct: number) => `ציון: ${pct}%`, roundsLeft: (n: number) => `נותרו ${n} סבבים`, stalled: "נתחיל את החלק מחדש",
    retry: "התחלה מחדש", locked: "נעול", weakSections: "נחזור על:", reexplaining: "מסבירים את זה בדרך אחרת…",
    truncated: "ההסבר נקטע בגלל מגבלת האורך.",
    keyPoints: "נקודות מפתח", figure: "איור", figurePage: (printed: string) => `עמוד ${printed}`, pageCount: (n: number) => (n === 1 ? "עמוד אחד" : `${n} עמודים`), language: "שפה", admin: "ניהול",
    questionOf: (i: number, total: number) => `שאלה ${i} מתוך ${total}`, chooseOne: "בחרו תשובה אחת",
    status: { not_started: "טרם התחיל", learning: "קריאה", quizzing: "מענה", reinforcing: "חזרה", passed: "הושלם", stalled: "נעצר" },
    grade: { correct: "נכון", partial: "נכון חלקית", incorrect: "לא נכון", off_topic: "לא בנושא", junk: "לא ברור" },
    errors: {
      unauthorized: "ההתחברות הסתיימה - מחברים אותך מחדש.", forbidden: "אין לך הרשאה לתוכן הזה.",
      conflict: "המצב כבר התקדם. רעננו את העמוד.",
      payloadTooLarge: "הקובץ גדול מדי להעלאה.", unsupportedType: "סוג הקובץ אינו נתמך.",
      rateLimited: "יותר מדי בקשות. המתינו רגע ונסו שוב.",
      unknown: "משהו נכשל. נסו שוב.",
    },
    adminRoleRequired: "נדרשת הרשאת מנהל כדי לצפות בעמוד זה.",
    adminSubjects: "מקצועות", adminUsage: "שימוש",
    adminState: { draft: "טיוטה", published: "פורסם" },
    sourceStatus: { uploaded: "הועלה", extracting: "מחלץ טקסט", chunking: "מפצל", indexing: "מאנדקס", ready: "מוכן", failed: "נכשל" },
    adminVersion: (v: number | null) => (v === null ? "אין עדיין מתווה" : `גרסה ${v}`),
    usage: { purpose: "מטרה", model: "מודל", calls: "קריאות", input: "אסימוני קלט", output: "אסימוני פלט", cost: "עלות", total: "סה\"כ" },
    uploadSources: "העלאת מקורות", chooseFile: "בחירת קובץ", upload: "העלאה", uploading: "מעלים…",
    acceptedTypes: (types: string) => `סוגים נתמכים: ${types}`,
    uploadLocked: "מקצוע שפורסם נעול; בטלו את הפרסום כדי לשנות את המקורות.", noSources: "אין עדיין מקורות.",
    deleteSource: "מחיקה", reingestSource: "עיבוד מחדש",
    confirmDelete: (filename: string) => `למחוק את ${filename} ואת כל מה שנאנדקס ממנו?`,
    confirmReingest: (filename: string) => `לעבד מחדש את ${filename} מההתחלה?`,
    detectedLanguage: (code: string) => `שפה: ${code}`,
    subjectActions: "מקצוע", generate: "יצירת תוכן", publish: "פרסום", unpublish: "ביטול פרסום",
    jobKind: { ingest_source: "מעבד מקור", generate_subject: "יוצר תוכן", generate_unit: "יוצר תוכן" },
    jobStatus: { queued: "בתור", running: "רץ", done: "הסתיים", failed: "נכשל" },
    jobLine: (kind: string, status: string) => `${kind}: ${status}`,
    partsReady: (ready: number, total: number) => `${ready} מתוך ${total} חלקים מוכנים`,
    questionsReady: (n: number) => `${n} שאלות`,
    failedParts: (positions: string) => `חלקים שנכשלו: ${positions}`,
    publishable: (version: number) => `גרסה ${version} מוכנה לפרסום`,
    notPublishable: "לא כל השפות הושלמו עדיין.",
    publishedVersion: (v: number | null) => (v === null ? "לא פורסם" : `פורסמה גרסה ${v}`),
  },
  pt: {
    appName: "teach-me", signIn: "Entrar", subjects: "As suas matérias", noSubjects: "Ainda não há matérias publicadas.",
    partOf: (n: number, total: number) => `Parte ${n} de ${total}`,
    partsPassed: (n: number, total: number) => `${n} de ${total} partes concluídas`, sources: "Fontes", teaching: "Ensino",
    dialog: "Diálogo", startRound: "Começar as perguntas", nextRound: "Começar a próxima ronda", continue: "Continuar",
    submit: "Enviar resposta", answerPlaceholder: "Escreva a sua resposta…", passed: "Parte concluída", failed: "Ainda não",
    score: (pct: number) => `Pontuação: ${pct}%`, roundsLeft: (n: number) => `${n} rondas restantes`, stalled: "Vamos recomeçar esta parte",
    retry: "Recomeçar", locked: "Bloqueado", weakSections: "Vamos rever:", reexplaining: "A explicar de outra forma…",
    truncated: "Esta explicação foi cortada no seu limite de comprimento.",
    keyPoints: "Pontos-chave", figure: "Figura", figurePage: (printed: string) => `Página ${printed}`, pageCount: (n: number) => (n === 1 ? "1 página" : `${n} páginas`), language: "Idioma", admin: "Administração",
    questionOf: (i: number, total: number) => `Pergunta ${i} de ${total}`, chooseOne: "Escolha uma",
    status: { not_started: "Não iniciado", learning: "A ler", quizzing: "A responder", reinforcing: "A rever", passed: "Concluído", stalled: "Parado" },
    grade: { correct: "Correto", partial: "Parcialmente correto", incorrect: "Incorreto", off_topic: "Fora do tema", junk: "Pouco claro" },
    errors: {
      unauthorized: "A sua sessão terminou - a iniciar sessão novamente.", forbidden: "Não tem acesso a isto.",
      conflict: "Isto já avançou. Recarregue a página.",
      payloadTooLarge: "Esse ficheiro é demasiado grande para carregar.", unsupportedType: "Esse tipo de ficheiro não é aceite.",
      rateLimited: "Demasiados pedidos. Aguarde um momento e tente novamente.",
      unknown: "Algo falhou. Tente novamente.",
    },
    adminRoleRequired: "É necessária a função de administrador para ver esta página.",
    adminSubjects: "Matérias", adminUsage: "Utilização",
    adminState: { draft: "Rascunho", published: "Publicado" },
    sourceStatus: { uploaded: "Carregado", extracting: "A extrair", chunking: "A dividir", indexing: "A indexar", ready: "Pronto", failed: "Falhou" },
    adminVersion: (v: number | null) => (v === null ? "Ainda sem esboço" : `Versão ${v}`),
    usage: { purpose: "Finalidade", model: "Modelo", calls: "Chamadas", input: "Tokens de entrada", output: "Tokens de saída", cost: "Custo", total: "Total" },
    uploadSources: "Carregar fontes", chooseFile: "Escolher um ficheiro", upload: "Carregar", uploading: "A carregar…",
    acceptedTypes: (types: string) => `Aceites: ${types}`,
    uploadLocked: "Uma matéria publicada está bloqueada; retire a publicação para alterar as fontes.", noSources: "Ainda não há fontes.",
    deleteSource: "Eliminar", reingestSource: "Reprocessar",
    confirmDelete: (filename: string) => `Eliminar ${filename} e tudo o que foi indexado a partir dele?`,
    confirmReingest: (filename: string) => `Processar ${filename} novamente desde o início?`,
    detectedLanguage: (code: string) => `Idioma: ${code}`,
    subjectActions: "Matéria", generate: "Gerar", publish: "Publicar", unpublish: "Retirar publicação",
    jobKind: { ingest_source: "A processar", generate_subject: "A gerar", generate_unit: "A gerar" },
    jobStatus: { queued: "Em fila", running: "Em curso", done: "Concluído", failed: "Falhou" },
    jobLine: (kind: string, status: string) => `${kind}: ${status}`,
    partsReady: (ready: number, total: number) => `${ready} de ${total} partes prontas`,
    questionsReady: (n: number) => `${n} perguntas`,
    failedParts: (positions: string) => `Partes que falharam: ${positions}`,
    publishable: (version: number) => `A versão ${version} está pronta para publicar`,
    notPublishable: "Ainda não estão todos os idiomas completos.",
    publishedVersion: (v: number | null) => (v === null ? "Não publicado" : `Versão publicada ${v}`),
  },
};

export function t(code: Language): Strings {
  return STRINGS[code] ?? STRINGS.en;
}
