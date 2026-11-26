import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { api, clearSession, getStoredUser, getToken, setSession } from "./api";

interface AuthUser {
  id: number;
  name: string;
  email: string;
  locale: string;
}

interface DemoResult {
  token: string;
  user: AuthUser;
  family_id: number;
  case_id: number;
  scenarios: { key: string; title: string; description: string; case_id: number; status: string }[];
}

interface AuthValue {
  user: AuthUser | null;
  ready: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (name: string, email: string, password: string) => Promise<void>;
  demoLogin: () => Promise<DemoResult>;
  logout: () => void;
  refreshUser: () => Promise<void>;
}

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(getStoredUser());
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const token = getToken();
    if (!token) {
      setReady(true);
      return;
    }
    api
      .get<{ user: AuthUser }>("/api/auth/me")
      .then((data) => {
        setUser(data.user);
        const current = getStoredUser();
        if (current) setSession(token, { ...current, ...data.user });
      })
      .catch(() => {
        clearSession();
        setUser(null);
      })
      .finally(() => setReady(true));
  }, []);

  useEffect(() => {
    const listener = () => setUser(getStoredUser());
    window.addEventListener("duco-auth", listener);
    return () => window.removeEventListener("duco-auth", listener);
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const data = await api.post<{ token: string; user: AuthUser }>("/api/auth/login", { email, password });
    setSession(data.token, data.user);
    setUser(data.user);
  }, []);

  const register = useCallback(async (name: string, email: string, password: string) => {
    const data = await api.post<{ token: string; user: AuthUser }>("/api/auth/register", { name, email, password });
    setSession(data.token, data.user);
    setUser(data.user);
  }, []);

  const demoLogin = useCallback(async () => {
    const data = await api.post<DemoResult>("/api/demo/seed", {});
    setSession(data.token, data.user);
    setUser(data.user);
    return data;
  }, []);

  const logout = useCallback(() => {
    clearSession();
    setUser(null);
  }, []);

  const refreshUser = useCallback(async () => {
    const data = await api.get<{ user: AuthUser }>("/api/settings/profile");
    setUser(data.user);
    const token = getToken();
    if (token) setSession(token, data.user);
  }, []);

  const value = useMemo(
    () => ({ user, ready, login, register, demoLogin, logout, refreshUser }),
    [user, ready, login, register, demoLogin, logout, refreshUser]
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside AuthProvider");
  return context;
}
