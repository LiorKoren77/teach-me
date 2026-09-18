import { expect, test } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import { t } from "../lib/i18n";

// Clerk's own testing guidance: `clerkSetup()` fetches a Testing Token once so the sign-in form
// is not blocked by bot protection in a headless browser, and `setupClerkTestingToken(page)`
// attaches it per test. Both come from `@clerk/testing`, a package this worktree does not
// depend on (adding a dependency is outside this change's scope - see the README's "End-to-end
// tests" section for the one-time `npm install --save-dev @clerk/testing` an operator runs
// before configuring Clerk for e2e). It is therefore imported dynamically - and, so `next
// build`'s typecheck does not need its (possibly absent) type declarations, through a variable
// rather than a string literal - and only once the skip below has already established that a
// real Clerk test user is configured; without that, `npm run e2e` never touches this package.
const CLERK_TESTING_MODULE = "@clerk/testing/playwright";
const CLERK_SECRET_KEY = process.env.CLERK_SECRET_KEY;
const CLERK_USERNAME = process.env.E2E_CLERK_USER_USERNAME;
const CLERK_PASSWORD = process.env.E2E_CLERK_USER_PASSWORD;

test.skip(!process.env.CLERK_SECRET_KEY || !process.env.E2E_CLERK_USER_USERNAME, "Clerk test credentials not configured");

// The seeded subject (scripts/e2e-backend.sh) teaches he and en; the app defaults to en with no
// language cookie set, which is the state a fresh browser context starts in.
const strings = t("en");
const SUBJECT_ID_FILE = path.join(__dirname, ".subject-id");

// The fake-stack question and grading responders that ship on the merged branch
// (api/teachme/generation/fake_responders.py and api/teachme/grading/fake_responders.py on
// stage-4-frontend; not present in this worktree's stage-3 backend) are deterministic: every
// free-text question's expected_answer is exactly "Fake expected answer.", and the one
// multiple-choice question a bank always carries has choices A-D with B correct. Answering
// exactly that text, or picking "B", makes the fake grader return `correct` and the fake
// relevance check return `on_topic` no matter which questions a round samples.
const FREE_TEXT_ANSWER = "Fake expected answer.";
const MULTIPLE_CHOICE_ANSWER = "B";
const MAX_QUESTIONS_PER_ROUND = 30; // a seatbelt against a stuck loop, not a tuned round size.

test.describe("learn: happy path", () => {
  test.beforeAll(async () => {
    const { clerkSetup } = await import(CLERK_TESTING_MODULE);
    await clerkSetup({ secretKey: CLERK_SECRET_KEY });
  });

  test("reads part 1, answers a full round, and passes it", async ({ page }) => {
    const subjectId = fs.readFileSync(SUBJECT_ID_FILE, "utf-8").trim();

    const { setupClerkTestingToken } = await import(CLERK_TESTING_MODULE);
    await setupClerkTestingToken({ page });

    await page.goto("/");
    await page.getByRole("button", { name: strings.signIn }).click();

    // Clerk's own prebuilt <SignIn/>, rendered in the modal SignInButton opens - field labels
    // are Clerk's copy, not this app's i18n.
    await page.getByLabel(/email address|username/i).fill(CLERK_USERNAME!);
    await page.getByRole("button", { name: "Continue", exact: true }).click();
    await page.getByLabel("Password", { exact: true }).fill(CLERK_PASSWORD!);
    await page.getByRole("button", { name: "Continue", exact: true }).click();
    await expect(page.getByRole("button", { name: strings.signIn })).toBeHidden();

    await page.goto(`/learn/${subjectId}`);

    // Part 1's teaching text is above the dialog; read it, then start the round.
    await expect(page.getByRole("heading", { name: strings.dialog })).toBeVisible();
    await expect(page.getByText(strings.partOf(1, 1))).toBeVisible();
    await page.getByRole("button", { name: strings.startRound }).click();

    const passed = page.getByText(strings.passed, { exact: true });
    const freeTextBox = page.getByLabel(strings.answerPlaceholder);
    const mcOption = page.getByLabel(MULTIPLE_CHOICE_ANSWER, { exact: true });

    // Answer every question of the round: multiple-choice picks the fixed correct option, free
    // text echoes the fixed expected answer (see the comment on FREE_TEXT_ANSWER above).
    for (let i = 0; i < MAX_QUESTIONS_PER_ROUND; i++) {
      await expect(passed.or(freeTextBox).or(mcOption)).toBeVisible();
      if (await passed.isVisible()) break;

      if (await mcOption.isVisible()) {
        await mcOption.check();
      } else {
        await freeTextBox.fill(FREE_TEXT_ANSWER);
      }
      await Promise.all([
        page.waitForResponse((res) => res.request().method() === "POST" && res.url().includes("/answer")),
        page.getByRole("button", { name: strings.submit }).click(),
      ]);
    }

    await expect(passed).toBeVisible();
    // The progress strip shows part 1 passed.
    await expect(page.getByText(strings.status.passed, { exact: true })).toBeVisible();
  });
});
