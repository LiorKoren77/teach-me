"use client";
import { useClerk } from "@clerk/nextjs";
import { useCallback, useEffect, useRef, useState } from "react";
import { errorKeyOf, type ErrorKey } from "@/lib/api/errors";

/**
 * What every failed request goes through: the reader gets a translated message for the key, the
 * backend's `detail` goes to the console, and a caller whose session is gone is sent to Clerk's
 * sign-in rather than shown a message it can do nothing about.
 *
 * The returned function keeps one identity for the life of the component, so an effect can hold
 * it in its dependencies without refetching.
 */
export function useApiErrorReport(): (failure: unknown) => ErrorKey {
  const { redirectToSignIn } = useClerk();
  const redirect = useRef(redirectToSignIn);
  useEffect(() => {
    redirect.current = redirectToSignIn;
  }, [redirectToSignIn]);

  return useCallback((failure: unknown) => {
    const key = errorKeyOf(failure);
    console.debug("api request failed", failure);
    if (key === "unauthorized") void redirect.current?.();
    return key;
  }, []);
}

/** The same, holding the key for a screen to render. */
export function useApiError() {
  const report = useApiErrorReport();
  const [error, setError] = useState<ErrorKey | null>(null);
  const fail = useCallback(
    (failure: unknown) => {
      setError(report(failure));
    },
    [report],
  );
  const clear = useCallback(() => setError(null), []);
  return { error, fail, clear };
}
