"use client";

import { Button } from "@/components/ui/button";

type Props = {
  url: string | null | undefined;
  className?: string;
  size?: "default" | "sm" | "lg" | "icon";
  /** Подпись ссылки (по умолчанию — для HeadHunter) */
  label?: string;
};

export function HhResumeLinkButton({
  url,
  className,
  size = "sm",
  label = "Посмотреть на HH",
}: Props) {
  const href = url?.trim();
  if (!href) return null;

  return (
    <Button asChild variant="outline" size={size} className={className}>
      <a href={href} target="_blank" rel="noopener noreferrer">
        {label}
      </a>
    </Button>
  );
}
