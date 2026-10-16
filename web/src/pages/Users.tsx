import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, Plus } from "lucide-react";
import { useState, type FormEvent } from "react";
import { ApiError, get, post } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import type { User } from "@/lib/types";
import { useCard } from "@/shell/context";
import { PageBody } from "@/shell/Shell";
import { Button } from "@/ui/button";
import { Dialog } from "@/ui/dialog";
import { Choice, Field, FormError, Input } from "@/ui/form";
import { Card, Chip, Empty, Loading, PageHeader } from "@/ui/misc";

export const ROLE_TITLES = { admin: "администратор", viewer: "просмотр", guest: "гость по ссылке" } as const;

export function UserState({ user }: { user: User }) {
  if (user.blocked) return <Chip tone="bad">заблокирована</Chip>;
  if (user.locked_until) return <Chip tone="warn">вход закрыт до {formatDateTime(user.locked_until).slice(-5)}</Chip>;
  if (user.must_change_password) return <Chip tone="muted">временный пароль</Chip>;
  return <Chip tone="ok">действует</Chip>;
}

export function buildingsText(user: User) {
  if (user.role === "admin") return "все";
  if (!user.buildings.length) return "не выданы";
  return user.buildings.map((b) => b.name).join(", ");
}

// 6.5.10: ФИО, роль, здания, заблокирована ли, последний вход
export function Users() {
  const users = useQuery({ queryKey: ["users"], queryFn: () => get<{ items: User[] }>("/api/users") });
  const [card, setCard] = useCard();
  const [creating, setCreating] = useState(false);
  const [issued, setIssued] = useState<{ user: User; password: string; reset?: boolean } | null>(null);
  return (
    <PageBody>
      <PageHeader
        title="Пользователи"
        subtitle="Учётные записи и доступ к зданиям"
        actions={
          <Button variant="primary" onClick={() => setCreating(true)}>
            <Plus /> Завести учётную запись
          </Button>
        }
      />
      <Card className="overflow-hidden">
        {users.isLoading ? (
          <Loading />
        ) : !users.data?.items.length ? (
          <Empty title="Учётных записей нет" />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-sm">
              <thead>
                <tr className="text-left text-xs text-ink-2">
                  {["ФИО", "Имя для входа", "Роль", "Здания", "Состояние", "Последний вход"].map((h) => (
                    <th key={h} className="border-b border-line px-4 py-2.5 font-medium whitespace-nowrap">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {users.data.items.map((user) => (
                  <tr
                    key={user.id}
                    onClick={() => setCard(`user:${user.id}`)}
                    className={`cursor-pointer hover:bg-surface-2 ${card === `user:${user.id}` ? "bg-accent-soft hover:bg-accent-soft" : ""}`}
                  >
                    <td className="border-b border-line px-4 py-3">
                      <button type="button" className="cursor-pointer border-0 bg-transparent p-0 text-left font-medium text-ink" onClick={() => setCard(`user:${user.id}`)}>
                        {user.full_name}
                      </button>
                    </td>
                    <td className="border-b border-line px-4 py-3 font-mono text-[13px]">{user.login}</td>
                    <td className="border-b border-line px-4 py-3">{ROLE_TITLES[user.role]}</td>
                    <td className="border-b border-line px-4 py-3 text-ink-2">{buildingsText(user)}</td>
                    <td className="border-b border-line px-4 py-3">
                      <UserState user={user} />
                    </td>
                    <td className="border-b border-line px-4 py-3 whitespace-nowrap text-ink-2">{formatDateTime(user.last_login_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      <CreateUserDialog
        open={creating}
        onOpenChange={setCreating}
        onCreated={(user, password) => {
          setCreating(false);
          setIssued({ user, password });
        }}
      />
      <IssuedPasswordDialog issued={issued} onClose={() => setIssued(null)} />
    </PageBody>
  );
}

function CreateUserDialog({
  open,
  onOpenChange,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (user: User, password: string) => void;
}) {
  const client = useQueryClient();
  const [form, setForm] = useState({ full_name: "", login: "", role: "viewer", password: "", building_ids: [] as string[] });
  const [error, setError] = useState<ApiError | null>(null);
  const create = useMutation({
    mutationFn: () => post<{ user: User; temporary_password: string }>("/api/users", form),
    onSuccess: (result) => {
      client.invalidateQueries({ queryKey: ["users"] });
      setForm({ full_name: "", login: "", role: "viewer", password: "", building_ids: [] });
      onCreated(result.user, result.temporary_password);
    },
    onError: (e) => setError(e as ApiError),
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    create.mutate();
  };
  const fieldError = (name: string) => (error?.field === name ? error.message : undefined);
  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        setError(null);
        onOpenChange(o);
      }}
      title="Новая учётная запись"
      description="Человек войдёт с временным паролем и при первом входе сменит его."
    >
      <form id="create-user" onSubmit={submit} className="flex flex-col gap-4">
        <Field label="ФИО" error={fieldError("full_name")}>
          {(p) => <Input {...p} value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} placeholder="Петрова Елена Алексеевна" required autoFocus />}
        </Field>
        <Field label="Имя для входа" hint="Латиница или кириллица, цифры, точка, дефис; без пробелов." error={fieldError("login")}>
          {(p) => <Input {...p} value={form.login} onChange={(e) => setForm({ ...form, login: e.target.value })} placeholder="petrova" autoCapitalize="none" required />}
        </Field>
        <fieldset className="m-0 flex flex-col gap-2 border-0 p-0">
          <legend className="mb-1.5 p-0 text-[13px] font-medium">Роль</legend>
          <Choice name="role" value="viewer" checked={form.role === "viewer"} onChange={() => setForm({ ...form, role: "viewer" })} title="Просмотр" description="Смотрит выданные здания: план, 3D, расстановку, карточки — без стоимости, инвентарных номеров и проектов. Ничего не меняет." />
          <Choice name="role" value="admin" checked={form.role === "admin"} onChange={() => setForm({ ...form, role: "admin" })} title="Администратор" description="Видит и меняет всё во всех зданиях, заводит учётные записи." />
        </fieldset>
        {form.role === "viewer" && <BuildingsPicker value={form.building_ids} onChange={(building_ids) => setForm({ ...form, building_ids })} />}
        <Field label="Временный пароль" hint="Можно не заполнять — система придумает сама и покажет." error={fieldError("password")}>
          {(p) => <Input {...p} value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} autoComplete="off" />}
        </Field>
        <FormError message={error && !error.field ? error.message : null} />
        <div className="flex justify-end gap-2">
          <Button onClick={() => onOpenChange(false)}>Отмена</Button>
          <Button type="submit" variant="primary" disabled={create.isPending}>
            Завести
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

// «Просмотр» выдаётся на здание (2.3)
export function BuildingsPicker({ value, onChange, disabled }: { value: string[]; onChange: (ids: string[]) => void; disabled?: boolean }) {
  const list = useQuery({ queryKey: ["buildings", false], queryFn: () => get<{ items: { id: string; name: string; address: string }[] }>("/api/buildings") });
  const items = list.data?.items ?? [];
  return (
    <fieldset className="m-0 flex flex-col gap-1.5 border-0 p-0">
      <legend className="mb-1.5 p-0 text-[13px] font-medium">Здания</legend>
      {list.isLoading ? null : !items.length ? (
        <p className="m-0 rounded-lg bg-surface-2 px-3 py-2.5 text-[13px] text-ink-2">Зданий в системе пока нет — их создают в «Управление › Здания». Без выданных зданий «просмотр» ничего не видит.</p>
      ) : (
        items.map((b) => (
          <label key={b.id} className="flex cursor-pointer items-center gap-2.5 rounded-lg border border-line-strong px-3 py-2 text-sm hover:bg-surface-2">
            <input type="checkbox" disabled={disabled} checked={value.includes(b.id)} onChange={(e) => onChange(e.target.checked ? [...value, b.id] : value.filter((x) => x !== b.id))} />
            <span className="flex flex-col">
              {b.name}
              {b.address && <span className="text-[12px] text-ink-2">{b.address}</span>}
            </span>
          </label>
        ))
      )}
    </fieldset>
  );
}

export function IssuedPasswordDialog({ issued, onClose }: { issued: { user: User; password: string; reset?: boolean } | null; onClose: () => void }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    if (!issued) return;
    try {
      await navigator.clipboard.writeText(issued.password);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };
  return (
    <Dialog
      open={issued !== null}
      onOpenChange={(o) => {
        if (!o) {
          setCopied(false);
          onClose();
        }
      }}
      title={issued?.reset ? "Пароль сброшен" : "Учётная запись заведена"}
      description={issued ? `${issued.user.full_name}, имя для входа «${issued.user.login}».` : undefined}
      footer={<Button variant="primary" onClick={onClose}>Готово</Button>}
    >
      <div className="flex flex-col gap-2">
        <div className="text-[13px] font-medium">Временный пароль</div>
        <div className="flex items-center gap-2">
          <code className="flex-1 rounded-lg border border-line-strong bg-surface-2 px-3 py-2 font-mono text-lg tracking-wide">{issued?.password}</code>
          <Button onClick={copy} aria-label="Скопировать пароль">
            <Copy /> {copied ? "Скопирован" : "Скопировать"}
          </Button>
        </div>
        <p className="m-0 text-[13px] text-ink-2">
          Передайте его человеку. Больше система его не покажет; при первом входе попросит сменить.
        </p>
      </div>
    </Dialog>
  );
}
