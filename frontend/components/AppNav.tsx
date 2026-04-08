"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/stores/auth-store";

const links = [
  { href: "/search", label: "Поиск" },
  { href: "/history", label: "История" },
  { href: "/favorites", label: "Избранное" },
  { href: "/estaff-exports", label: "Выгрузки e-staff" },
  { href: "/settings", label: "Настройки" },
];

export function AppNav() {
  const pathname = usePathname();
  const router = useRouter();
  const accessToken = useAuthStore((s) => s.accessToken);
  const clearSession = useAuthStore((s) => s.clearSession);
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    setMenuOpen(false);
  }, [pathname]);

  if (!accessToken) return null;

  function logout() {
    clearSession();
    router.push("/login");
  }

  return (
    <>
      <header className="relative sticky top-0 z-30 border-b-2 bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
        <div className="mx-auto flex h-16 max-w-7xl items-center justify-between gap-4 px-4 lg:px-6">
          <div className="flex items-center gap-8">
            <Link href="/search" className="flex items-center gap-2">
              <span className="text-xl font-display font-bold tracking-tight text-primary">
                HR Service
              </span>
            </Link>
            <nav className="hidden items-center gap-1.5 md:flex">
              {links.map((l) => (
                <Link key={l.href} href={l.href}>
                  <span
                    className={cn(
                      "rounded-lg px-4 py-2 text-sm font-medium transition-all",
                      pathname === l.href
                        ? "bg-primary text-primary-foreground shadow-sm"
                        : "text-foreground/70 hover:bg-secondary hover:text-foreground",
                    )}
                  >
                    {l.label}
                  </span>
                </Link>
              ))}
            </nav>
          </div>

          <div className="flex w-full items-center justify-end gap-3 md:w-auto md:justify-end">
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="md:hidden"
              aria-expanded={menuOpen}
              aria-controls="mobile-nav"
              aria-label={menuOpen ? "Закрыть меню" : "Открыть меню"}
              onClick={() => setMenuOpen((o) => !o)}
            >
              {menuOpen ? (
                <span className="text-2xl leading-none" aria-hidden>
                  ×
                </span>
              ) : (
                <span className="flex flex-col gap-1.5" aria-hidden>
                  <span className="block h-0.5 w-5 rounded-full bg-foreground transition-all" />
                  <span className="block h-0.5 w-5 rounded-full bg-foreground transition-all" />
                  <span className="block h-0.5 w-5 rounded-full bg-foreground transition-all" />
                </span>
              )}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              type="button"
              className="hidden sm:inline-flex"
              onClick={logout}
            >
              Выйти
            </Button>
          </div>
        </div>

        {menuOpen && (
          <>
            <button
              type="button"
              aria-label="Закрыть меню"
              className="fixed inset-0 z-40 bg-background/80 backdrop-blur-sm md:hidden animate-fade-in"
              onClick={() => setMenuOpen(false)}
            />
            <nav
              id="mobile-nav"
              className="absolute left-0 right-0 top-full z-50 border-b-2 bg-background px-4 py-4 shadow-float md:hidden animate-slide-in"
            >
              <ul className="flex flex-col gap-1.5">
                {links.map((l, index) => (
                  <li 
                    key={l.href}
                    style={{ animationDelay: `${index * 50}ms` }}
                    className="animate-fade-in"
                  >
                    <Link
                      href={l.href}
                      className={cn(
                        "block rounded-lg px-4 py-3 text-sm font-medium transition-all",
                        pathname === l.href
                          ? "bg-primary text-primary-foreground shadow-sm"
                          : "text-foreground/70 hover:bg-secondary hover:text-foreground",
                      )}
                    >
                      {l.label}
                    </Link>
                  </li>
                ))}
                <li className="pt-3 border-t mt-2">
                  <Button
                    variant="outline"
                    size="sm"
                    type="button"
                    className="w-full"
                    onClick={logout}
                  >
                    Выйти
                  </Button>
                </li>
              </ul>
            </nav>
          </>
        )}
      </header>
      
      {/* Mobile Bottom Navigation */}
      <nav className="fixed bottom-0 left-0 right-0 z-30 border-t-2 bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60 md:hidden">
        <div className="flex items-center justify-around px-2 py-2">
          {links.slice(0, 4).map((l) => (
            <Link
              key={l.href}
              href={l.href}
              className={cn(
                "flex flex-col items-center gap-1 rounded-lg px-3 py-2 text-xs font-medium transition-colors",
                pathname === l.href
                  ? "text-primary"
                  : "text-muted-foreground hover:text-foreground"
              )}
            >
              <span className={cn(
                "h-1.5 w-1.5 rounded-full transition-all",
                pathname === l.href ? "bg-primary scale-100" : "bg-transparent scale-0"
              )} />
              <span className="text-center leading-tight">{l.label}</span>
            </Link>
          ))}
        </div>
      </nav>
    </>
  );
}
