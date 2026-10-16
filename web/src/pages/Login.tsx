import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { ApiError, post } from "@/lib/api";
import type { Me } from "@/lib/types";
import { homeFor } from "@/shell/menu";
import { PasswordForm } from "@/shell/PasswordDialog";
import { Button } from "@/ui/button";
import { Field, FormError, Input } from "@/ui/form";

function Frame({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <div className="flex min-h-dvh items-center justify-center bg-ground px-4 py-10">
      <div className="flex w-full max-w-sm flex-col gap-6">
        <div className="flex items-center gap-3">
          <img src="/favicon.svg" alt="" className="size-10" />
          <div className="flex flex-col leading-tight">
            <span className="font-semibold">Планировка и учёт</span>
            <span className="text-sm text-ink-2">имущества здания</span>
          </div>
        </div>
        <div className="flex flex-col gap-5 rounded-xl border border-line bg-surface p-6 max-md:p-5">
          <div className="flex flex-col gap-1">
            <h1 className="m-0 text-xl font-semibold">{title}</h1>
            {subtitle && <p className="m-0 text-sm text-ink-2">{subtitle}</p>}
          </div>
          {children}
        </div>
      </div>
    </div>
  );
}

// 6.5.11: имя и пароль; после входа — главная или план; ссылка, открытая до входа,
// открывается после него
export function Login() {
  const client = useQueryClient();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [login, setLogin] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const submit = useMutation({
    mutationFn: () => post<Me>("/api/auth/login", { login, password }),
    onSuccess: (me) => {
      client.setQueryData(["me"], me);
      const next = params.get("next");
      navigate(next && next.startsWith("/") && !next.startsWith("//") ? next : homeFor(me.role), { replace: true });
    },
    onError: (e) => setError((e as ApiError).message),
  });
  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    submit.mutate();
  };
  return (
    <Frame title="Вход">
      <form onSubmit={onSubmit} className="flex flex-col gap-4">
        <Field label="Имя для входа">
          {(p) => <Input {...p} autoComplete="username" autoCapitalize="none" value={login} onChange={(e) => setLogin(e.target.value)} required autoFocus />}
        </Field>
        <Field label="Пароль">
          {(p) => <Input {...p} type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />}
        </Field>
        <FormError message={error} />
        <Button type="submit" variant="primary" disabled={submit.isPending}>
          Войти
        </Button>
        <p className="m-0 text-[13px] text-ink-2">Учётную запись выдаёт администратор системы. Забыли пароль — попросите его сбросить.</p>
      </form>
    </Frame>
  );
}

// 5.7.1: при первом входе с временным паролем сменить его обязательно
export function ForcedPassword({ me }: { me: Me }) {
  const navigate = useNavigate();
  return (
    <Frame title="Смените временный пароль" subtitle={`${me.full_name}, вы вошли с временным паролем. Придумайте свой — дальше вход будет с ним.`}>
      <PasswordForm submitLabel="Сменить и продолжить" onDone={() => navigate(homeFor(me.role), { replace: true })} />
    </Frame>
  );
}
