"use client";

import * as React from "react";

import { cn } from "@/lib/utils";

export type SheetProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  children: React.ReactNode;
  className?: string;
};

export function Sheet({ open, onOpenChange, children, className }: SheetProps) {
  React.useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onOpenChange(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onOpenChange]);

  React.useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [open]);

  if (!open) return null;

  return (
    <div className={cn("fixed inset-0 z-50", className)} role="presentation">
      <button
        type="button"
        aria-label="Закрыть панель"
        className="absolute inset-0 bg-black/50 animate-in fade-in duration-200"
        onClick={() => onOpenChange(false)}
      />
      {children}
    </div>
  );
}

export type SheetContentProps = React.HTMLAttributes<HTMLDivElement> & {
  side?: "right" | "left";
};

export function SheetContent({
  className,
  side = "right",
  children,
  ...props
}: SheetContentProps) {
  return (
    <div
      role="dialog"
      aria-modal="true"
      className={cn(
        "absolute top-0 flex h-full w-full max-w-md flex-col border bg-background shadow-lg outline-none",
        side === "right" &&
          "right-0 animate-in slide-in-from-right duration-300",
        side === "left" && "left-0 animate-in slide-in-from-left duration-300",
        className,
      )}
      onClick={(e) => e.stopPropagation()}
      {...props}
    >
      {children}
    </div>
  );
}
