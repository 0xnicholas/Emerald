"use client";

import { ErrorBoundary } from "@/components/error-boundary";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html className="dark">
      <body className="bg-surface-base text-fg-primary antialiased">
        <div className="flex min-h-screen items-center justify-center p-4">
          <ErrorBoundary
            fallback={null}
          >
            <div className="flex flex-col items-center gap-4 text-center">
              <h1 className="text-lg font-semibold">Critical Error</h1>
              <p className="text-sm text-fg-muted">{error.message}</p>
              <button
                onClick={reset}
                className="rounded-lg bg-brand-accent px-4 py-2 text-sm font-medium text-white hover:bg-brand-accent/90"
              >
                Try again
              </button>
            </div>
          </ErrorBoundary>
        </div>
      </body>
    </html>
  );
}
