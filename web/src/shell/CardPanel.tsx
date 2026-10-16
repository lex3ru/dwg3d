import { X } from "lucide-react";
import type { ReactNode } from "react";
import { UnitCard } from "@/inventory/UnitCard";
import { UserCard } from "@/pages/UserCard";
import { Button } from "@/ui/button";
import { useCard } from "./context";

// Какая карточка открывается по ?card=<вид>:<id>. Новые виды (помещение, предмет,
// инвентарная единица, документ, тип) добавляются сюда на своих этапах.
const CARDS: Record<string, (id: string) => ReactNode> = {
  user: (id) => <UserCard id={id} />,
  unit: (id) => <UnitCard id={id} />,
};

export function CardPanel() {
  const [card, setCard] = useCard();
  if (!card) return null;
  const [kind, id] = [card.slice(0, card.indexOf(":")), card.slice(card.indexOf(":") + 1)];
  const render = CARDS[kind];
  return (
    <aside
      aria-label="Карточка"
      className="flex w-[420px] shrink-0 flex-col border-l border-line bg-surface max-lg:fixed max-lg:inset-y-0 max-lg:right-0 max-lg:z-30 max-lg:shadow-2xl max-md:inset-0 max-md:w-full"
    >
      <div className="flex justify-end px-3 pt-3">
        <Button variant="ghost" size="icon" aria-label="Закрыть карточку" onClick={() => setCard(null)}>
          <X />
        </Button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-5 pb-6">
        {render ? render(id) : <p className="text-sm text-ink-2">Такой карточки нет.</p>}
      </div>
    </aside>
  );
}
