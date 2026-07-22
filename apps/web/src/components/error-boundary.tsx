"use client";

import { Component, type ReactNode } from "react";
import { AlertTriangle, RefreshCw, Home } from "lucide-react";
import { Button } from "@/components/ui/button";

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
  onError?: (error: Error, errorInfo: React.ErrorInfo) => void;
}

interface State {
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  override state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  override componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    this.props.onError?.(error, errorInfo);
    console.error("[ErrorBoundary]", error, errorInfo);
  }

  override render() {
    if (this.state.error) {
      if (this.props.fallback) {
        return this.props.fallback;
      }

      return (
        <div className="flex min-h-[400px] flex-col items-center justify-center rounded-[18px] border border-surface-border bg-surface-card/60 p-8 text-center backdrop-blur-md">
          <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-bg-error/30">
            <AlertTriangle className="h-7 w-7 text-text-error" />
          </div>
          <h2 className="mb-1 text-lg font-semibold text-fg-primary">
            Something went wrong
          </h2>
          <p className="mb-6 max-w-sm text-sm text-fg-muted">
            An unexpected error occurred. Try refreshing the page, or go back to the dashboard.
          </p>
          <div className="flex items-center gap-3">
            <Button
              variant="outline"
              onClick={() => window.location.reload()}
            >
              <RefreshCw className="h-4 w-4 mr-1.5" />
              Refresh Page
            </Button>
            <Button
              onClick={() => {
                window.location.href = "/";
              }}
            >
              <Home className="h-4 w-4 mr-1.5" />
              Go Home
            </Button>
          </div>
          <details className="mt-6 w-full max-w-md">
            <summary className="cursor-pointer text-xs text-fg-faint hover:text-fg-muted">
              Error details
            </summary>
            <pre className="mt-2 max-h-32 overflow-auto rounded-lg bg-surface-hover/50 p-3 text-left text-xs font-mono text-fg-muted">
              {this.state.error.message}
              {"\n"}
              {this.state.error.stack?.split("\n").slice(1, 4).join("\n")}
            </pre>
          </details>
        </div>
      );
    }

    return this.props.children;
  }
}
