import { beforeEach, describe, expect, it } from "vitest";

import { useAuthStore } from "./auth-store";

describe("useAuthStore", () => {
  beforeEach(() => {
    localStorage.clear();
    useAuthStore.setState({
      accessToken: null,
      refreshToken: null,
      email: null,
      _hasHydrated: true,
    });
  });

  it("setSession сохраняет токены и email", () => {
    useAuthStore.getState().setSession({
      accessToken: "a",
      refreshToken: "r",
      email: "u@example.com",
    });
    const s = useAuthStore.getState();
    expect(s.accessToken).toBe("a");
    expect(s.refreshToken).toBe("r");
    expect(s.email).toBe("u@example.com");
  });

  it("clearSession очищает состояние", () => {
    useAuthStore.getState().setSession({
      accessToken: "a",
      refreshToken: "r",
    });
    useAuthStore.getState().clearSession();
    const s = useAuthStore.getState();
    expect(s.accessToken).toBeNull();
    expect(s.refreshToken).toBeNull();
  });
});
