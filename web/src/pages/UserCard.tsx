import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound, Lock, LockOpen } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router";
import { ApiError, get, patch, post, query } from "@/lib/api";
import { useMe } from "@/lib/auth";
import { formatDateTime } from "@/lib/format";
import type { JournalEntry, Page, User } from "@/lib/types";
import { useCardTitle } from "@/shell/context";
import { Button } from "@/ui/button";
import { Dialog } from "@/ui/dialog";
import { Choice, Field, FormError, Input } from "@/ui/form";
import { Loading } from "@/ui/misc";
import { EntryView } from "./Journal";
import { BuildingsPicker, IssuedPasswordDialog, ROLE_TITLES, UserState } from "./Users";

// Карточка учётной записи (6.5.10): роль, здания, «Сбросить пароль», «Заблокировать»
export function UserCard({ id }: { id: string }) {
  const me = useMe();
  const client = useQueryClient();
  const user = useQuery({ queryKey: ["users", id], queryFn: () => get<User>(`/api/users/${id}`) });
  const history = useQuery({
    queryKey: ["journal", "user", id],
    queryFn: () => get<Page<JournalEntry>>(`/api/journal${query({ ref: `user:${id}`, limit: 8 })}`),
  });
  useCardTitle(user.data?.full_name);

  const [form, setForm] = useState({ full_name: "", role: "viewer", building_ids: [] as string[] });
  const [error, setError] = useState<ApiError | null>(null);
  const [confirm, setConfirm] = useState<"reset" | "block" | null>(null);
  const [issued, setIssued] = useState<{ user: User; password: string; reset: boolean } | null>(null);
  useEffect(() => {
    if (user.data) setForm({ full_name: user.data.full_name, role: user.data.role, building_ids: user.data.buildings.map((b) => b.id) });
    setError(null);
  }, [user.data]);

  const refresh = () => client.invalidateQueries({ queryKey: ["users"] });
  const onError = (e: Error) => setError(e as ApiError);
  const save = useMutation({
    mutationFn: () => patch<User>(`/api/users/${id}`, { version: user.data!.version, ...form }),
    onSuccess: refresh,
    onError,
  });
  const reset = useMutation({
    mutationFn: () => post<{ user: User; temporary_password: string }>(`/api/users/${id}/reset-password`),
    onSuccess: (r) => {
      setConfirm(null);
      setIssued({ user: r.user, password: r.temporary_password, reset: true });
      refresh();
    },
    onError: (e) => {
      setConfirm(null);
      onError(e);
    },
  });
  const block = useMutation({
    mutationFn: () => post<User>(`/api/users/${id}/${user.data!.blocked ? "unblock" : "block"}`),
    onSuccess: () => {
      setConfirm(null);
      refresh();
    },
    onError: (e) => {
      setConfirm(null);
      onError(e);
    },
  });

  if (user.isLoading) return <Loading />;
  if (!user.data) return <p className="text-sm text-ink-2">Учётная запись не найдена.</p>;
  const u = user.data;
  const self = u.id === me.id;
  const dirty =
    form.full_name !== u.full_name || form.role !== u.role || [...form.building_ids].sort().join() !== u.buildings.map((b) => b.id).sort().join();

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-2">
        <div className="text-xs text-ink-2">Учётная запись</div>
        <h2 className="m-0 text-xl font-semibold">{u.full_name}</h2>
        <div className="flex flex-wrap items-center gap-2 text-sm text-ink-2">
          <span className="font-mono text-[13px]">{u.login}</span>
          <UserState user={u} />
        </div>
        <div className="text-[13px] text-ink-2">
          Последний вход: {formatDateTime(u.last_login_at)} · заведена {formatDateTime(u.created_at)}
        </div>
      </div>

      <form
        className="flex flex-col gap-4"
        onSubmit={(e) => {
          e.preventDefault();
          setError(null);
          save.mutate();
        }}
      >
        <Field label="ФИО" error={error?.field === "full_name" ? error.message : undefined}>
          {(p) => <Input {...p} value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} />}
        </Field>
        <fieldset className="m-0 flex flex-col gap-2 border-0 p-0">
          <legend className="mb-1.5 p-0 text-[13px] font-medium">Роль</legend>
          {(["viewer", "admin"] as const).map((role) => (
            <Choice
              key={role}
              name={`role-${id}`}
              value={role}
              checked={form.role === role}
              disabled={self}
              onChange={() => setForm({ ...form, role })}
              title={ROLE_TITLES[role][0]!.toUpperCase() + ROLE_TITLES[role].slice(1)}
            />
          ))}
          {self && <p className="m-0 text-[13px] text-ink-2">Свою роль сменить нельзя — это сделает другой администратор.</p>}
        </fieldset>
        {form.role === "viewer" ? (
          <BuildingsPicker value={form.building_ids} onChange={(building_ids) => setForm({ ...form, building_ids })} />
        ) : (
          <p className="m-0 text-[13px] text-ink-2">Администратору доступны все здания.</p>
        )}
        {error && (
          <div className="flex flex-col gap-2">
            <FormError message={error.field === "full_name" ? null : error.message} />
            {error.code === "stale" && (
              <Button size="sm" onClick={() => user.refetch()}>
                Обновить
              </Button>
            )}
          </div>
        )}
        {dirty && (
          <div className="flex gap-2">
            <Button type="submit" variant="primary" disabled={save.isPending}>
              Сохранить
            </Button>
            <Button onClick={() => setForm({ full_name: u.full_name, role: u.role, building_ids: u.buildings.map((b) => b.id) })}>Отменить</Button>
          </div>
        )}
      </form>

      {!self && (
        <div className="flex flex-wrap gap-2 border-t border-line pt-4">
          <Button onClick={() => setConfirm("reset")}>
            <KeyRound /> Сбросить пароль
          </Button>
          <Button variant={u.blocked ? "secondary" : "danger"} onClick={() => setConfirm("block")}>
            {u.blocked ? <LockOpen /> : <Lock />} {u.blocked ? "Разблокировать" : "Заблокировать"}
          </Button>
        </div>
      )}

      <div className="flex flex-col gap-2 border-t border-line pt-4">
        <div className="flex items-center justify-between">
          <h3 className="m-0 text-sm font-semibold">История</h3>
          <Link to={`/journal${query({ ref: `user:${id}` })}`} className="text-[13px] text-accent">
            Весь журнал →
          </Link>
        </div>
        {history.data?.items.length ? (
          <ul className="m-0 flex list-none flex-col p-0">
            {history.data.items.map((entry) => (
              <EntryView key={entry.id} entry={entry} compact />
            ))}
          </ul>
        ) : (
          <p className="m-0 text-[13px] text-ink-2">Записей нет.</p>
        )}
      </div>

      <Dialog
        open={confirm === "reset"}
        onOpenChange={(o) => !o && setConfirm(null)}
        title="Сбросить пароль?"
        description={`${u.full_name} получит новый временный пароль, все его открытые сеансы закончатся; при входе система попросит сменить пароль.`}
        footer={
          <>
            <Button onClick={() => setConfirm(null)}>Отмена</Button>
            <Button variant="primary" onClick={() => reset.mutate()} disabled={reset.isPending}>
              Сбросить
            </Button>
          </>
        }
      />
      <Dialog
        open={confirm === "block"}
        onOpenChange={(o) => !o && setConfirm(null)}
        title={u.blocked ? "Разблокировать учётную запись?" : "Заблокировать учётную запись?"}
        description={
          u.blocked
            ? `${u.full_name} снова сможет входить со своим паролем.`
            : `${u.full_name} не сможет войти, открытые сеансы закончатся сразу. Данные и история остаются.`
        }
        footer={
          <>
            <Button onClick={() => setConfirm(null)}>Отмена</Button>
            <Button variant={u.blocked ? "primary" : "danger"} onClick={() => block.mutate()} disabled={block.isPending}>
              {u.blocked ? "Разблокировать" : "Заблокировать"}
            </Button>
          </>
        }
      />
      <IssuedPasswordDialog issued={issued} onClose={() => setIssued(null)} />
    </div>
  );
}
