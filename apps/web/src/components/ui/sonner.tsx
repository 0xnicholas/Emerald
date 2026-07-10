"use client";

import { Toaster as SonnerToaster } from "sonner";
import { useTheme } from "next-themes";

type ToasterProps = React.ComponentProps<typeof SonnerToaster>;

function Toaster({ ...props }: ToasterProps) {
  const { theme = "system" } = useTheme();

  return (
    <SonnerToaster
      theme={theme as ToasterProps["theme"]}
      className="toaster group"
      toastOptions={{
        classNames: {
          toast:
            "group toast group-[.toaster]:bg-surface-card group-[.toaster]:text-fg-primary group-[.toaster]:border-surface-border group-[.toaster]:shadow-lg",
          description: "group-[.toast]:text-fg-muted",
          actionButton:
            "group-[.toast]:bg-brand-accent group-[.toast]:text-white",
          cancelButton:
            "group-[.toast]:bg-surface-hover group-[.toast]:text-fg-muted",
        },
      }}
      {...props}
    />
  );
}

export { Toaster };
