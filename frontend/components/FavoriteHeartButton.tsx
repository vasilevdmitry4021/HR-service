"use client";

import { Heart, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type Props = {
  inFavorites: boolean;
  disabled?: boolean;
  busy?: boolean;
  onClick: () => void;
  className?: string;
};

export function FavoriteHeartButton({
  inFavorites,
  disabled,
  busy,
  onClick,
  className,
}: Props) {
  return (
    <Button
      type="button"
      variant="outline"
      size="icon"
      className={cn("shrink-0 rounded-full", className)}
      disabled={disabled || busy}
      aria-label={
        inFavorites ? "Убрать из избранного" : "Добавить в избранное"
      }
      onClick={onClick}
    >
      {busy ? (
        <Loader2 className="h-5 w-5 shrink-0 animate-spin" aria-hidden />
      ) : (
        <Heart
          className={cn(
            "h-5 w-5 shrink-0 transition-colors",
            inFavorites
              ? "fill-black stroke-black"
              : "fill-white stroke-neutral-900",
          )}
          strokeWidth={1.5}
          aria-hidden
        />
      )}
    </Button>
  );
}
