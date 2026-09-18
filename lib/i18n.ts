import type { ErrorKey } from "./api/errors";
import type { Language } from "./api/types";

export const LANGUAGES: { code: Language; name: string; dir: "ltr" | "rtl" }[] = [
  { code: "he", name: "עברית", dir: "rtl" },
  { code: "en", name: "English", dir: "ltr" },
  { code: "pt", name: "Português", dir: "ltr" },
];

export function directionOf(code: Language): "ltr" | "rtl" {
  return LANGUAGES.find((l) => l.code === code)?.dir ?? "ltr";
}

const STRINGS = {
  en: {
    appName: "teach-me", signIn: "Sign in", subjects: "Your subjects", noSubjects: "No published subjects yet.",
    partOf: (n: number, total: number) => `Part ${n} of ${total}`, sources: "Sources", teaching: "Teaching",
    dialog: "Dialog", startRound: "Start the questions", nextRound: "Start the next round", continue: "Continue",
    submit: "Submit answer", answerPlaceholder: "Write your answer…", passed: "Part passed", failed: "Not yet",
    score: (pct: number) => `Score: ${pct}%`, roundsLeft: (n: number) => `${n} rounds left`, stalled: "Let's start this part again",
    retry: "Start again", locked: "Locked", weakSections: "We will go over:", reexplaining: "Explaining this differently…",
    keyPoints: "Key points", figurePage: (p: number) => `Page ${p}`, pageCount: (n: number) => (n === 1 ? "1 page" : `${n} pages`), language: "Language", admin: "Admin",
    questionOf: (i: number, total: number) => `Question ${i} of ${total}`, chooseOne: "Choose one",
    status: { not_started: "Not started", learning: "Reading", quizzing: "Answering", reinforcing: "Reviewing", passed: "Passed", stalled: "Stalled" } as Record<string, string>,
    grade: { correct: "Correct", partial: "Partly right", incorrect: "Not right", off_topic: "Off topic", junk: "Unclear" } as Record<string, string>,
    errors: {
      unauthorized: "Your session has ended - signing you in again.", forbidden: "You do not have access to this.",
      conflict: "This has already moved on. Reload the page to catch up.", rateLimited: "Too many requests. Wait a moment and try again.",
      unknown: "Something went wrong. Please try again.",
    } as Record<ErrorKey, string>,
    adminRoleRequired: "You need the admin role to view this page.",
    adminSubjects: "Subjects", adminUsage: "Usage", adminState: "State",
    adminVersion: (v: number | null) => (v === null ? "No outline yet" : `Version ${v}`),
    usage: { purpose: "Purpose", model: "Model", calls: "Calls", input: "Input tokens", output: "Output tokens", cost: "Cost", total: "Total" } as Record<string, string>,
  },
  he: {
    appName: "teach-me", signIn: "כניסה", subjects: "המקצועות שלך", noSubjects: "אין עדיין מקצועות זמינים.",
    partOf: (n: number, total: number) => `חלק ${n} מתוך ${total}`, sources: "מקורות", teaching: "הוראה",
    dialog: "שיחה", startRound: "התחלת השאלות", nextRound: "התחלת הסבב הבא", continue: "המשך",
    submit: "שליחת תשובה", answerPlaceholder: "כתבו את תשובתכם…", passed: "החלק הושלם", failed: "עוד לא",
    score: (pct: number) => `ציון: ${pct}%`, roundsLeft: (n: number) => `נותרו ${n} סבבים`, stalled: "נתחיל את החלק מחדש",
    retry: "התחלה מחדש", locked: "נעול", weakSections: "נחזור על:", reexplaining: "מסבירים את זה בדרך אחרת…",
    keyPoints: "נקודות מפתח", figurePage: (p: number) => `עמוד ${p}`, pageCount: (n: number) => (n === 1 ? "עמוד אחד" : `${n} עמודים`), language: "שפה", admin: "ניהול",
    questionOf: (i: number, total: number) => `שאלה ${i} מתוך ${total}`, chooseOne: "בחרו תשובה אחת",
    status: { not_started: "טרם התחיל", learning: "קריאה", quizzing: "מענה", reinforcing: "חזרה", passed: "הושלם", stalled: "נעצר" } as Record<string, string>,
    grade: { correct: "נכון", partial: "נכון חלקית", incorrect: "לא נכון", off_topic: "לא בנושא", junk: "לא ברור" } as Record<string, string>,
    errors: {
      unauthorized: "ההתחברות הסתיימה - מחברים אותך מחדש.", forbidden: "אין לך הרשאה לתוכן הזה.",
      conflict: "המצב כבר התקדם. רעננו את העמוד.", rateLimited: "יותר מדי בקשות. המתינו רגע ונסו שוב.",
      unknown: "משהו נכשל. נסו שוב.",
    } as Record<ErrorKey, string>,
    adminRoleRequired: "נדרשת הרשאת מנהל כדי לצפות בעמוד זה.",
    adminSubjects: "מקצועות", adminUsage: "שימוש", adminState: "מצב",
    adminVersion: (v: number | null) => (v === null ? "אין עדיין מתווה" : `גרסה ${v}`),
    usage: { purpose: "מטרה", model: "מודל", calls: "קריאות", input: "אסימוני קלט", output: "אסימוני פלט", cost: "עלות", total: "סה\"כ" } as Record<string, string>,
  },
  pt: {
    appName: "teach-me", signIn: "Entrar", subjects: "As suas matérias", noSubjects: "Ainda não há matérias publicadas.",
    partOf: (n: number, total: number) => `Parte ${n} de ${total}`, sources: "Fontes", teaching: "Ensino",
    dialog: "Diálogo", startRound: "Começar as perguntas", nextRound: "Começar a próxima ronda", continue: "Continuar",
    submit: "Enviar resposta", answerPlaceholder: "Escreva a sua resposta…", passed: "Parte concluída", failed: "Ainda não",
    score: (pct: number) => `Pontuação: ${pct}%`, roundsLeft: (n: number) => `${n} rondas restantes`, stalled: "Vamos recomeçar esta parte",
    retry: "Recomeçar", locked: "Bloqueado", weakSections: "Vamos rever:", reexplaining: "A explicar de outra forma…",
    keyPoints: "Pontos-chave", figurePage: (p: number) => `Página ${p}`, pageCount: (n: number) => (n === 1 ? "1 página" : `${n} páginas`), language: "Idioma", admin: "Administração",
    questionOf: (i: number, total: number) => `Pergunta ${i} de ${total}`, chooseOne: "Escolha uma",
    status: { not_started: "Não iniciado", learning: "A ler", quizzing: "A responder", reinforcing: "A rever", passed: "Concluído", stalled: "Parado" } as Record<string, string>,
    grade: { correct: "Correto", partial: "Parcialmente correto", incorrect: "Incorreto", off_topic: "Fora do tema", junk: "Pouco claro" } as Record<string, string>,
    errors: {
      unauthorized: "A sua sessão terminou - a iniciar sessão novamente.", forbidden: "Não tem acesso a isto.",
      conflict: "Isto já avançou. Recarregue a página.", rateLimited: "Demasiados pedidos. Aguarde um momento e tente novamente.",
      unknown: "Algo falhou. Tente novamente.",
    } as Record<ErrorKey, string>,
    adminRoleRequired: "É necessária a função de administrador para ver esta página.",
    adminSubjects: "Matérias", adminUsage: "Utilização", adminState: "Estado",
    adminVersion: (v: number | null) => (v === null ? "Ainda sem esboço" : `Versão ${v}`),
    usage: { purpose: "Finalidade", model: "Modelo", calls: "Chamadas", input: "Tokens de entrada", output: "Tokens de saída", cost: "Custo", total: "Total" } as Record<string, string>,
  },
};

export type Strings = (typeof STRINGS)["en"];

export function t(code: Language): Strings {
  return STRINGS[code] ?? STRINGS.en;
}
