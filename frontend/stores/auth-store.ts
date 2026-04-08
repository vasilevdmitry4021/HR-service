"use client";

import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

import { bindAuthStore } from "@/lib/api";

/** На сервере Next.js нет localStorage; без этого persist не создаёт api.persist и падает AuthHydration. */
function getAuthStorage() {
  if (typeof window === "undefined") {
    return {
      getItem: () => null,
      setItem: () => {},
      removeItem: () => {},
    };
  }
  return window.localStorage;
}

export type AuthState = {
  accessToken: string | null;
  refreshToken: string | null;
  email: string | null;
  _hasHydrated: boolean;
  setSession: (tokens: {
    accessToken: string;
    refreshToken: string;
    email?: string | null;
  }) => void;
  clearSession: () => void;
};

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      accessToken: null,
      refreshToken: null,
      email: null,
      _hasHydrated: false,
      setSession: ({ accessToken, refreshToken, email }) =>
        set({ accessToken, refreshToken, email: email ?? null }),
      clearSession: () =>
        set({ accessToken: null, refreshToken: null, email: null }),
    }),
    {
      name: "hr-auth",
      storage: createJSONStorage(getAuthStorage),
      skipHydration: true,
      partialize: (s) => ({
        accessToken: s.accessToken,
        refreshToken: s.refreshToken,
        email: s.email,
      }),
    },
  ),
);

if (typeof window !== "undefined") {
  bindAuthStore(
    () => {
      const s = useAuthStore.getState();
      if (!s.accessToken || !s.refreshToken) return null;
      return { accessToken: s.accessToken, refreshToken: s.refreshToken };
    },
    (t) => {
      if (!t) useAuthStore.getState().clearSession();
      else useAuthStore.getState().setSession(t);
    },
  );
}
