"use client";

import { Toaster } from "sonner";

export function AppToaster() {
  return (
    <Toaster
      richColors
      position="top-right"
      closeButton
      toastOptions={{ classNames: { toast: "font-sans" } }}
    />
  );
}
