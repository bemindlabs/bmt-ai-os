"use client";

import { createContext, use, useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { isAuthenticated, getUser, type AuthUser } from "@/lib/auth";

// ---------- Context ----------

interface AuthContextValue {
  user: AuthUser | null;
  setUser: (user: AuthUser | null) => void;
}

const AuthContext = createContext<AuthContextValue>({
  user: null,
  setUser: () => {},
});

export function useAuth(): AuthContextValue {
  return use(AuthContext);
}

// ---------- Provider ----------

interface AuthProviderProps {
  children: React.ReactNode;
}

export function AuthProvider({ children }: AuthProviderProps) {
  const pathname = usePathname();
  const router = useRouter();
  const [checked, setChecked] = useState(false);
  const [user, setUser] = useState<AuthUser | null>(null);

  useEffect(() => {
    const authed = isAuthenticated();
    if (!authed && pathname !== "/login") {
      router.replace("/login");
      return;
    }
    setUser(getUser());
    setChecked(true);
  }, [pathname, router]);

  // Avoid flash of protected content while auth check is pending
  if (!checked && pathname !== "/login") {
    return null;
  }

  return (
    <AuthContext value={{ user, setUser }}>
      {children}
    </AuthContext>
  );
}
