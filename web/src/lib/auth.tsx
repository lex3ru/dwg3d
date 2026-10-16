import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useContext, useEffect, type ReactNode } from "react";
import { ApiError, get } from "./api";
import type { Me } from "./types";

const MeContext = createContext<Me | null>(null);

export function useMeQuery() {
  return useQuery<Me | null>({
    queryKey: ["me"],
    queryFn: async () => {
      try {
        return await get<Me>("/api/auth/me");
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) return null;
        throw e;
      }
    },
    staleTime: 60_000,
  });
}

export function MeProvider({ me, children }: { me: Me; children: ReactNode }) {
  const client = useQueryClient();
  useEffect(() => {
    // сеанс кончился (бездействие, блокировка) — на вход
    const onLost = () => client.setQueryData(["me"], null);
    window.addEventListener("app:unauthenticated", onLost);
    return () => window.removeEventListener("app:unauthenticated", onLost);
  }, [client]);
  return <MeContext.Provider value={me}>{children}</MeContext.Provider>;
}

export function useMe(): Me {
  const me = useContext(MeContext);
  if (!me) throw new Error("useMe outside MeProvider");
  return me;
}

export const isAdmin = (me: Me) => me.role === "admin";
