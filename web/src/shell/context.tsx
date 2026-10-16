import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { useSearchParams } from "react-router";

// Карточка справа (6.3): открывается поверх раздела, у открытой карточки свой адрес
// (?card=user:<id>), закрывается — раздел остаётся на месте.

interface ShellState {
  cardTitle: string | null;
  setCardTitle: (title: string | null) => void;
}

const Ctx = createContext<ShellState>({ cardTitle: null, setCardTitle: () => {} });

export function ShellProvider({ children }: { children: ReactNode }) {
  const [cardTitle, setCardTitle] = useState<string | null>(null);
  return <Ctx.Provider value={{ cardTitle, setCardTitle }}>{children}</Ctx.Provider>;
}

export const useShell = () => useContext(Ctx);

// Заголовок открытой карточки — в строку «где я»
export function useCardTitle(title: string | null | undefined) {
  const { setCardTitle } = useShell();
  useEffect(() => {
    setCardTitle(title ?? null);
    return () => setCardTitle(null);
  }, [title, setCardTitle]);
}

export function useCard(): [string | null, (card: string | null) => void] {
  const [params, setParams] = useSearchParams();
  const card = params.get("card");
  const open = (next: string | null) =>
    setParams(
      (p) => {
        const out = new URLSearchParams(p);
        if (next) out.set("card", next);
        else out.delete("card");
        return out;
      },
      { replace: false },
    );
  return [card, open];
}
