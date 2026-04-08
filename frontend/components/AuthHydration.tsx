"use client";

import { useEffect, useSyncExternalStore } from "react";
import { useAuthStore } from "@/stores/auth-store";

/** Вызывает гидрацию auth-store из localStorage и устанавливает _hasHydrated после завершения. */
export function AuthHydration({ children }: { children: React.ReactNode }) {
  const hasHydrated = useSyncExternalStore(
    useAuthStore.persist.onFinishHydration,
    () => useAuthStore.persist.hasHydrated(),
    () => false,
  );

  useEffect(() => {
    if (!hasHydrated) {
      useAuthStore.persist.rehydrate();
    }
  }, [hasHydrated]);

  useEffect(() => {
    if (hasHydrated) {
      useAuthStore.setState({ _hasHydrated: true });
    }
  }, [hasHydrated]);

  return <>{children}</>;
}
