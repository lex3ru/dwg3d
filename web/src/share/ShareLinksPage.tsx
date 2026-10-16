import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, Link2, Plus } from "lucide-react";
import { useEffect, useState } from "react";
import { today } from "@/inventory/types";
import { ApiError, get, post } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import type { BuildingSummary } from "@/pages/Buildings";
import { lastBuilding } from "@/pages/PlanIndex";
import { PageBody } from "@/shell/Shell";
import { Button } from "@/ui/button";
import { Dialog } from "@/ui/dialog";
import { Field, FormError, Input } from "@/ui/form";
import { Card, Chip, Empty, Loading, PageHeader, type Tone } from "@/ui/misc";

interface ShareLink {
  id: string;
  building_id: string;
  building: string;
  note: string;
  created_by: string;
  created_at: string;
  expires_at: string;
  revoked_at: string | null;
  status: "active" | "expired" | "revoked";
  status_title: string;
  opened: number;
  last_opened_at: string | null;
  token?: string;
}

const TONE: Record<ShareLink["status"], Tone> = { active: "ok", expired: "muted", revoked: "bad" };

// Ссылки на просмотр (5.7.2, С21): подрядчику — план и 3D здания без учётной записи, до срока
export function ShareLinksPage() {
  const client = useQueryClient();
  const list = useQuery({ queryKey: ["share-links"], queryFn: () => get<{ items: ShareLink[] }>("/api/share-links") });
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const revoke = useMutation({
    mutationFn: (id: string) => post(`/api/share-links/${id}/revoke`),
    onSuccess: () => client.invalidateQueries({ queryKey: ["share-links"] }),
    onError: (e) => setError((e as ApiError).message),
  });
  return (
    <PageBody>
      <PageHeader
        title="Ссылки на просмотр"
        subtitle="По ссылке — план и 3D здания с текущей расстановкой, без учёта, проектов и стоимости. Открытия — в журнале."
        actions={
          <Button variant="primary" onClick={() => setCreating(true)}>
            <Plus /> Выдать ссылку
          </Button>
        }
      />
      <FormError message={error} />
      <Card className="overflow-x-auto">
        {list.isLoading ? (
          <Loading />
        ) : !list.data?.items.length ? (
          <Empty title="Ссылок нет">Например, охранной организации нужен план с камерами — выдайте ссылку до конца работ и отзовите, когда они закончатся.</Empty>
        ) : (
          <table className="w-full border-collapse text-[13px]">
            <thead>
              <tr className="text-left text-xs text-ink-2">
                {["Здание", "Для кого", "Действует до", "Состояние", "Открывали", ""].map((h) => (
                  <th key={h} className="border-b border-line px-3 py-2 font-medium">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {list.data.items.map((l) => (
                <tr key={l.id}>
                  <td className="border-b border-line px-3 py-2 font-medium">{l.building}</td>
                  <td className="border-b border-line px-3 py-2">
                    {l.note || "—"}
                    <span className="block text-[11px] text-ink-3">
                      выдал {l.created_by}, {formatDateTime(l.created_at)}
                    </span>
                  </td>
                  <td className="border-b border-line px-3 py-2">{formatDateTime(l.expires_at)}</td>
                  <td className="border-b border-line px-3 py-2">
                    <Chip tone={TONE[l.status]}>{l.status_title}</Chip>
                  </td>
                  <td className="border-b border-line px-3 py-2">
                    {l.opened}
                    {l.last_opened_at && <span className="block text-[11px] text-ink-3">последний раз {formatDateTime(l.last_opened_at)}</span>}
                  </td>
                  <td className="border-b border-line px-3 py-2 text-right">
                    {l.status === "active" && (
                      <Button size="sm" variant="danger" onClick={() => revoke.mutate(l.id)}>
                        Отозвать
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
      <NewLink open={creating} onClose={() => setCreating(false)} />
    </PageBody>
  );
}

function NewLink({ open, onClose }: { open: boolean; onClose: () => void }) {
  const client = useQueryClient();
  const buildings = useQuery({ queryKey: ["buildings", false], queryFn: () => get<{ items: BuildingSummary[] }>("/api/buildings") });
  const [building, setBuilding] = useState("");
  const [until, setUntil] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState<ApiError | null>(null);
  const [made, setMade] = useState<ShareLink | null>(null);
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!open) return;
    const items = buildings.data?.items ?? [];
    setBuilding(items.find((b) => b.id === lastBuilding())?.id ?? items[0]?.id ?? "");
    const end = new Date();
    end.setMonth(end.getMonth() + 1, 0); // до конца месяца
    setUntil(end.toLocaleDateString("sv-SE"));
    setNote("");
    setError(null);
    setMade(null);
    setCopied(false);
  }, [open, buildings.data]);
  const url = made?.token ? `${window.location.origin}/share/${made.token}` : "";
  const create = useMutation({
    mutationFn: () => post<ShareLink>("/api/share-links", { building_id: building, until, note }),
    onSuccess: (l) => {
      setMade(l);
      client.invalidateQueries({ queryKey: ["share-links"] });
    },
    onError: (e) => setError(e as ApiError),
  });
  return (
    <Dialog
      open={open}
      onOpenChange={(o) => !o && onClose()}
      title={made ? "Ссылка выдана" : "Выдать ссылку на просмотр"}
      description={made ? "Скопируйте и отправьте её: больше она не показывается. Отозвать можно в списке." : undefined}
      footer={
        made ? (
          <Button variant="primary" onClick={onClose}>
            Готово
          </Button>
        ) : (
          <>
            <Button onClick={onClose}>Отмена</Button>
            <Button variant="primary" disabled={!building || !until || create.isPending} onClick={() => create.mutate()}>
              <Link2 /> Выдать
            </Button>
          </>
        )
      }
    >
      {made ? (
        <div className="flex items-center gap-2">
          <Input readOnly value={url} aria-label="Ссылка" className="flex-1 font-mono text-[12px]" onFocus={(e) => e.target.select()} />
          <Button
            onClick={async () => {
              try {
                await navigator.clipboard.writeText(url);
                setCopied(true);
              } catch {
                /* выделите и скопируйте вручную */
              }
            }}
          >
            <Copy /> {copied ? "Скопировано" : "Копировать"}
          </Button>
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          <Field label="Здание">
            {(p) => (
              <select {...p} value={building} onChange={(e) => setBuilding(e.target.value)} className="h-9 rounded-lg border border-line-strong bg-surface px-2 text-sm max-md:h-11">
                {buildings.data?.items.map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.name}
                  </option>
                ))}
              </select>
            )}
          </Field>
          <Field label="Действует до (включительно)" error={error?.field === "until" ? error.message : undefined}>
            {(p) => <Input {...p} type="date" min={today()} value={until} onChange={(e) => setUntil(e.target.value)} />}
          </Field>
          <Field label="Для кого" hint="Видно в списке ссылок и в журнале открытий.">
            {(p) => <Input {...p} placeholder="ЧОП «Щит», монтаж камер" value={note} onChange={(e) => setNote(e.target.value)} />}
          </Field>
          <FormError message={error && error.field !== "until" ? error.message : null} />
        </div>
      )}
    </Dialog>
  );
}
