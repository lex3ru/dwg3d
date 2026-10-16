import { useQuery } from "@tanstack/react-query";
import { ChevronDown, Plus } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router";
import { ApiError, get, post, query } from "@/lib/api";
import { cn } from "@/lib/cn";
import { PageBody } from "@/shell/Shell";
import { Button } from "@/ui/button";
import { FormError } from "@/ui/form";
import { Card, Chip, Empty, Loading, PageHeader } from "@/ui/misc";
import { PlacePicker } from "./parts";
import { KINDS, dateRu, money, type Doc, type DocKind } from "./types";

export const STATUS: Record<Doc["status"], [string, "muted" | "ok" | "warn"]> = {
  draft: ["черновик", "warn"],
  posted: ["проведён", "ok"],
  cancelled: ["отменён", "muted"],
};

// 6.5.6: список документов с фильтрами по виду, дате, месту, состоянию
export function DocumentsPage() {
  const navigate = useNavigate();
  const [kind, setKind] = useState("");
  const [status, setStatus] = useState("");
  const [since, setSince] = useState("");
  const [until, setUntil] = useState("");
  const [place, setPlace] = useState<string | null>(null);
  const [menu, setMenu] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const params = { kind, status, since, until, place: place ?? undefined };
  const list = useQuery({ queryKey: ["inventory", "documents", params], queryFn: () => get<{ items: Doc[] }>(`/api/inventory/documents${query(params)}`) });
  const create = async (k: DocKind) => {
    setMenu(false);
    try {
      const doc = await post<Doc>("/api/inventory/documents", { kind: k, header: {} });
      navigate(`/documents/${doc.id}`);
    } catch (e) {
      setError((e as ApiError).message);
    }
  };
  const input = "h-9 rounded-lg border border-line-strong bg-surface px-2 text-sm max-md:h-11";
  return (
    <PageBody>
      <PageHeader
        title="Документы"
        subtitle="Имущество меняет место, количество и стоимость только документами"
        actions={
          <div className="relative">
            <Button variant="primary" onClick={() => setMenu(!menu)} aria-expanded={menu}>
              <Plus /> Новый документ <ChevronDown />
            </Button>
            {menu && (
              <div role="menu" className="absolute right-0 z-20 mt-1 flex w-56 flex-col rounded-lg border border-line bg-surface p-1 shadow-lg">
                {(Object.keys(KINDS) as DocKind[]).map((k) => (
                  <button key={k} role="menuitem" type="button" onClick={() => void create(k)} className="cursor-pointer rounded-md border-0 bg-transparent px-3 py-2 text-left text-sm hover:bg-surface-2">
                    {KINDS[k]}
                  </button>
                ))}
              </div>
            )}
          </div>
        }
      />
      <FormError message={error} />
      <div className="flex flex-wrap items-center gap-2">
        <select aria-label="Вид" value={kind} onChange={(e) => setKind(e.target.value)} className={input}>
          <option value="">все виды</option>
          {(Object.keys(KINDS) as DocKind[]).map((k) => (
            <option key={k} value={k}>
              {KINDS[k]}
            </option>
          ))}
        </select>
        <select aria-label="Состояние документа" value={status} onChange={(e) => setStatus(e.target.value)} className={input}>
          <option value="">любые</option>
          <option value="draft">черновики</option>
          <option value="posted">проведённые</option>
          <option value="cancelled">отменённые</option>
        </select>
        <label className="flex items-center gap-1.5 text-[13px] text-ink-2">
          с <input type="date" aria-label="С даты" value={since} onChange={(e) => setSince(e.target.value)} className={input} />
          по <input type="date" aria-label="По дату" value={until} onChange={(e) => setUntil(e.target.value)} className={input} />
        </label>
        <PlacePicker value={place} onChange={setPlace} allowEmpty emptyTitle="любое место" className="w-auto max-w-xs" />
      </div>
      <Card className="overflow-x-auto">
        {list.isLoading ? (
          <Loading />
        ) : !list.data?.items.length ? (
          <Empty title="Документов нет" />
        ) : (
          <table className="w-full border-collapse text-[13px]">
            <thead>
              <tr className="text-left text-xs text-ink-2">
                {["Документ", "Дата", "Откуда", "Куда", "Строк", "Сумма", "Состояние"].map((h) => (
                  <th key={h} className="border-b border-line px-3 py-2 font-medium">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {list.data.items.map((d) => (
                <tr key={d.id} className="cursor-pointer hover:bg-surface-2" onClick={() => navigate(`/documents/${d.id}`)}>
                  <td className="border-b border-line px-3 py-2 font-medium">
                    <Link to={`/documents/${d.id}`} className={cn("text-ink", d.status === "cancelled" && "line-through")}>
                      {d.title}
                    </Link>
                    {d.basis && <div className="text-[11px] text-ink-3">{d.basis}</div>}
                  </td>
                  <td className="border-b border-line px-3 py-2">{dateRu(d.date)}</td>
                  <td className="border-b border-line px-3 py-2">{d.from_title || "—"}</td>
                  <td className="border-b border-line px-3 py-2">{d.to_title || "—"}</td>
                  <td className="border-b border-line px-3 py-2 font-mono">{d.lines as unknown as number}</td>
                  <td className="border-b border-line px-3 py-2 font-mono">{money(d.total)}</td>
                  <td className="border-b border-line px-3 py-2">
                    <Chip tone={STATUS[d.status][1]}>{STATUS[d.status][0]}</Chip>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </PageBody>
  );
}
