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
  /** null — ещё не загружено с сервера */
  isAdmin: boolean | null;
  isSuperAdmin: boolean | null;
  canWriteIntegrationSettings: boolean | null;
  canManageIntegrationEditors: boolean | null;
  canRevokeIntegrationEditorAccess: boolean | null;
  _hasHydrated: boolean;
  setSession: (tokens: {
    accessToken: string;
    refreshToken: string;
    email?: string | null;
    isAdmin?: boolean | null;
    isSuperAdmin?: boolean | null;
    canWriteIntegrationSettings?: boolean | null;
    canManageIntegrationEditors?: boolean | null;
    canRevokeIntegrationEditorAccess?: boolean | null;
  }) => void;
  clearSession: () => void;
};

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      accessToken: null,
      refreshToken: null,
      email: null,
      isAdmin: null,
      isSuperAdmin: null,
      canWriteIntegrationSettings: null,
      canManageIntegrationEditors: null,
      canRevokeIntegrationEditorAccess: null,
      _hasHydrated: false,
      setSession: (tokens) =>
        set((state) => ({
          accessToken: tokens.accessToken,
          refreshToken: tokens.refreshToken,
          email:
            "email" in tokens ? (tokens.email ?? null) : state.email,
          isAdmin:
            "isAdmin" in tokens
              ? (tokens.isAdmin ?? null)
              : state.isAdmin,
          isSuperAdmin:
            "isSuperAdmin" in tokens
              ? (tokens.isSuperAdmin ?? null)
              : state.isSuperAdmin,
          canWriteIntegrationSettings:
            "canWriteIntegrationSettings" in tokens
              ? (tokens.canWriteIntegrationSettings ?? null)
              : state.canWriteIntegrationSettings,
          canManageIntegrationEditors:
            "canManageIntegrationEditors" in tokens
              ? (tokens.canManageIntegrationEditors ?? null)
              : state.canManageIntegrationEditors,
          canRevokeIntegrationEditorAccess:
            "canRevokeIntegrationEditorAccess" in tokens
              ? (tokens.canRevokeIntegrationEditorAccess ?? null)
              : state.canRevokeIntegrationEditorAccess,
        })),
      clearSession: () =>
        set({
          accessToken: null,
          refreshToken: null,
          email: null,
          isAdmin: null,
          isSuperAdmin: null,
          canWriteIntegrationSettings: null,
          canManageIntegrationEditors: null,
          canRevokeIntegrationEditorAccess: null,
        }),
    }),
    {
      name: "hr-auth",
      storage: createJSONStorage(getAuthStorage),
      skipHydration: true,
      partialize: (s) => ({
        accessToken: s.accessToken,
        refreshToken: s.refreshToken,
        email: s.email,
        isAdmin: s.isAdmin,
        isSuperAdmin: s.isSuperAdmin,
        canWriteIntegrationSettings: s.canWriteIntegrationSettings,
        canManageIntegrationEditors: s.canManageIntegrationEditors,
        canRevokeIntegrationEditorAccess: s.canRevokeIntegrationEditorAccess,
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
