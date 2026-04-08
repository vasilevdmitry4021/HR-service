import * as React from "react";
import { ChevronLeft, ChevronRight, MoreHorizontal } from "lucide-react";

import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

interface PaginationProps extends React.HTMLAttributes<HTMLDivElement> {
  currentPage: number;
  totalPages: number;
  onPageChange: (page: number) => void;
  showJumpTo?: boolean;
  siblingCount?: number;
}

const Pagination = React.forwardRef<HTMLDivElement, PaginationProps>(
  (
    {
      className,
      currentPage,
      totalPages,
      onPageChange,
      showJumpTo = false,
      siblingCount = 1,
      ...props
    },
    ref
  ) => {
    const [jumpToValue, setJumpToValue] = React.useState("");

    const range = (start: number, end: number) => {
      const length = end - start + 1;
      return Array.from({ length }, (_, idx) => start + idx);
    };

    const paginationRange = React.useMemo(() => {
      const totalPageNumbers = siblingCount + 5;

      if (totalPageNumbers >= totalPages) {
        return range(1, totalPages);
      }

      const leftSiblingIndex = Math.max(currentPage - siblingCount, 1);
      const rightSiblingIndex = Math.min(
        currentPage + siblingCount,
        totalPages
      );

      const shouldShowLeftDots = leftSiblingIndex > 2;
      const shouldShowRightDots = rightSiblingIndex < totalPages - 2;

      const firstPageIndex = 1;
      const lastPageIndex = totalPages;

      if (!shouldShowLeftDots && shouldShowRightDots) {
        const leftItemCount = 3 + 2 * siblingCount;
        const leftRange = range(1, leftItemCount);

        return [...leftRange, "dots", totalPages];
      }

      if (shouldShowLeftDots && !shouldShowRightDots) {
        const rightItemCount = 3 + 2 * siblingCount;
        const rightRange = range(
          totalPages - rightItemCount + 1,
          totalPages
        );
        return [firstPageIndex, "dots", ...rightRange];
      }

      if (shouldShowLeftDots && shouldShowRightDots) {
        const middleRange = range(leftSiblingIndex, rightSiblingIndex);
        return [firstPageIndex, "dots", ...middleRange, "dots", lastPageIndex];
      }

      return [];
    }, [totalPages, siblingCount, currentPage]);

    const handleJumpTo = () => {
      const page = parseInt(jumpToValue, 10);
      if (page >= 1 && page <= totalPages) {
        onPageChange(page);
        setJumpToValue("");
      }
    };

    return (
      <div
        ref={ref}
        className={cn("flex flex-col items-center gap-4", className)}
        {...props}
      >
        <nav className="flex items-center gap-1" role="navigation" aria-label="Пагинация">
          <Button
            variant="outline"
            size="icon"
            onClick={() => onPageChange(currentPage - 1)}
            disabled={currentPage === 1}
            aria-label="Предыдущая страница"
          >
            <ChevronLeft className="h-4 w-4" />
          </Button>

          {paginationRange.map((pageNumber, index) => {
            if (pageNumber === "dots") {
              return (
                <span
                  key={`dots-${index}`}
                  className="flex h-10 w-10 items-center justify-center text-muted-foreground"
                >
                  <MoreHorizontal className="h-4 w-4" />
                </span>
              );
            }

            return (
              <Button
                key={pageNumber}
                variant={currentPage === pageNumber ? "default" : "outline"}
                size="icon"
                onClick={() => onPageChange(pageNumber as number)}
                aria-current={currentPage === pageNumber ? "page" : undefined}
              >
                {pageNumber}
              </Button>
            );
          })}

          <Button
            variant="outline"
            size="icon"
            onClick={() => onPageChange(currentPage + 1)}
            disabled={currentPage === totalPages}
            aria-label="Следующая страница"
          >
            <ChevronRight className="h-4 w-4" />
          </Button>
        </nav>

        {showJumpTo && totalPages > 10 && (
          <div className="flex items-center gap-2 text-sm">
            <span className="text-muted-foreground">Перейти к странице:</span>
            <input
              type="number"
              min={1}
              max={totalPages}
              value={jumpToValue}
              onChange={(e) => setJumpToValue(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  handleJumpTo();
                }
              }}
              className="h-9 w-16 rounded-lg border-2 border-input bg-background px-2 text-center text-sm transition-all focus-visible:border-primary/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/20"
              placeholder="№"
            />
            <Button size="sm" onClick={handleJumpTo}>
              Перейти
            </Button>
          </div>
        )}
      </div>
    );
  }
);
Pagination.displayName = "Pagination";

export { Pagination };
