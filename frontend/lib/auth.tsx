"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import * as api from "./api";

const TOKEN_KEY = "token";

interface AuthContextValue {
  user: api.User | null;
  token: string | null;
  // True until the stored token has been checked against /auth/me.
  loading: boolean;
  signIn: (email: string, password: string) => Promise<void>;
  signUp: (name: string, email: string, password: string) => Promise<void>;
  signOut: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<api.User | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  // Restore the session once on mount. localStorage is browser-only, so
  // this runs as an effect. Every setState happens after an await or in a
  // promise callback — never synchronously in the effect body.
  useEffect(() => {
    let active = true;

    async function restore() {
      const stored = window.localStorage.getItem(TOKEN_KEY);
      if (!stored) return;
      try {
        const me = await api.me(stored);
        if (!active) return;
        setToken(stored);
        setUser(me);
      } catch {
        // Expired or revoked token: drop it rather than showing a stale
        // identity that every request would reject.
        if (!active) return;
        window.localStorage.removeItem(TOKEN_KEY);
      }
    }

    restore().finally(() => {
      if (active) setLoading(false);
    });

    return () => {
      active = false;
    };
  }, []);

  const signIn = useCallback(async (email: string, password: string) => {
    const { access_token } = await api.login(email, password);
    window.localStorage.setItem(TOKEN_KEY, access_token);
    setToken(access_token);
    setUser(await api.me(access_token));
  }, []);

  const signUp = useCallback(
    async (name: string, email: string, password: string) => {
      await api.register(name, email, password);
      // Registration always creates a patient account; sign in right away.
      await signIn(email, password);
    },
    [signIn]
  );

  const signOut = useCallback(() => {
    window.localStorage.removeItem(TOKEN_KEY);
    setToken(null);
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider
      value={{ user, token, loading, signIn, signUp, signOut }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (context === null) {
    throw new Error("useAuth must be used inside <AuthProvider>");
  }
  return context;
}
