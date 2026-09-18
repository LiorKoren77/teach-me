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
    keyPoints: "Key points", figurePage: (p: number) => `Page ${p}`, language: "Language", admin: "Admin",
    questionOf: (i: number, total: number) => `Question ${i} of ${total}`, chooseOne: "Choose one",
    status: { not_started: "Not started", learning: "Reading", quizzing: "Answering", reinforcing: "Reviewing", passed: "Passed", stalled: "Stalled" } as Record<string, string>,
  },
  he: {
    appName: "teach-me", signIn: "כניסה", subjects: "המקצועות שלך", noSubjects: "אין עדיין מקצועות זמינים.",
    partOf: (n: number, total: number) => `חלק ${n} מתוך ${total}`, sources: "מקורות", teaching: "הוראה",
    dialog: "שיחה", startRound: "התחלת השאלות", nextRound: "התחלת הסבב הבא", continue: "המשך",
    submit: "שליחת תשובה", answerPlaceholder: "כתבו את תשובתכם…", passed: "החלק הושלם", failed: "עוד לא",
    score: (pct: number) => `ציון: ${pct}%`, roundsLeft: (n: number) => `נותרו ${n} סבבים`, stalled: "נתחיל את החלק מחדש",
    retry: "התחלה מחדש", locked: "נעול", weakSections: "נחזור על:", reexplaining: "מסבירים את זה בדרך אחרת…",
    keyPoints: "נקודות מפתח", figurePage: (p: number) => `עמוד ${p}`, language: "שפה", admin: "ניהול",
    questionOf: (i: number, total: number) => `שאלה ${i} מתוך ${total}`, chooseOne: "בחרו תשובה אחת",
    status: { not_started: "טרם התחיל", learning: "קריאה", quizzing: "מענה", reinforcing: "חזרה", passed: "הושלם", stalled: "נעצר" } as Record<string, string>,
  },
  pt: {
    appName: "teach-me", signIn: "Entrar", subjects: "As suas matérias", noSubjects: "Ainda não há matérias publicadas.",
    partOf: (n: number, total: number) => `Parte ${n} de ${total}`, sources: "Fontes", teaching: "Ensino",
    dialog: "Diálogo", startRound: "Começar as perguntas", nextRound: "Começar a próxima ronda", continue: "Continuar",
    submit: "Enviar resposta", answerPlaceholder: "Escreva a sua resposta…", passed: "Parte concluída", failed: "Ainda não",
    score: (pct: number) => `Pontuação: ${pct}%`, roundsLeft: (n: number) => `${n} rondas restantes`, stalled: "Vamos recomeçar esta parte",
    retry: "Recomeçar", locked: "Bloqueado", weakSections: "Vamos rever:", reexplaining: "A explicar de outra forma…",
    keyPoints: "Pontos-chave", figurePage: (p: number) => `Página ${p}`, language: "Idioma", admin: "Administração",
    questionOf: (i: number, total: number) => `Pergunta ${i} de ${total}`, chooseOne: "Escolha uma",
    status: { not_started: "Não iniciado", learning: "A ler", quizzing: "A responder", reinforcing: "A rever", passed: "Concluído", stalled: "Parado" } as Record<string, string>,
  },
};

export type Strings = (typeof STRINGS)["en"];

export function t(code: Language): Strings {
  return STRINGS[code] ?? STRINGS.en;
}
