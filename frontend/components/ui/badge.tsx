import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium ring-1 ring-inset transition-colors",
  {
    variants: {
      variant: {
        default:
          "bg-primary/10 text-primary ring-primary/20",
        secondary:
          "bg-secondary text-secondary-foreground ring-border",
        destructive:
          "bg-destructive/10 text-destructive ring-destructive/20",
        success:
          "bg-success/10 text-success ring-success/20",
        warning:
          "bg-accent/10 text-accent ring-accent/20",
        outline: "text-foreground ring-border",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {
  pulse?: boolean;
  dot?: boolean;
}

function Badge({ className, variant, pulse = false, dot = false, children, ...props }: BadgeProps) {
  return (
    <div className={cn(badgeVariants({ variant }), className)} {...props}>
      {dot && (
        <span 
          className={cn(
            "h-1.5 w-1.5 rounded-full",
            pulse && "animate-pulse-glow",
            variant === "success" && "bg-success",
            variant === "destructive" && "bg-destructive",
            variant === "warning" && "bg-accent",
            variant === "default" && "bg-primary",
            !variant && "bg-primary"
          )}
        />
      )}
      {children}
    </div>
  );
}

export { Badge, badgeVariants };
