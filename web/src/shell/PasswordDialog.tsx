import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { ApiError, post } from "@/lib/api";
import type { Me } from "@/lib/types";
import { Button } from "@/ui/button";
import { Dialog } from "@/ui/dialog";
import { Field, FormError, Input } from "@/ui/form";

export function PasswordForm({ onDone, submitLabel = "Сменить пароль" }: { onDone?: () => void; submitLabel?: string }) {
  const client = useQueryClient();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [repeat, setRepeat] = useState("");
  const [error, setError] = useState<ApiError | null>(null);
  const change = useMutation({
    mutationFn: () => post<Me>("/api/auth/password", { current, new: next }),
    onSuccess: (me) => {
      client.setQueryData(["me"], me);
      onDone?.();
    },
    onError: (e) => setError(e as ApiError),
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (next !== repeat) {
      setError(new ApiError(400, "mismatch", "Пароли не совпадают.", "repeat"));
      return;
    }
    setError(null);
    change.mutate();
  };
  const fieldError = (name: string) => (error?.field === name ? error.message : undefined);
  return (
    <form onSubmit={submit} className="flex flex-col gap-4">
      <Field label="Текущий пароль" error={fieldError("current")}>
        {(p) => <Input {...p} type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} required />}
      </Field>
      <Field label="Новый пароль" hint="Не короче 10 знаков." error={fieldError("new")}>
        {(p) => <Input {...p} type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} required />}
      </Field>
      <Field label="Новый пароль ещё раз" error={fieldError("repeat")}>
        {(p) => <Input {...p} type="password" autoComplete="new-password" value={repeat} onChange={(e) => setRepeat(e.target.value)} required />}
      </Field>
      <FormError message={error && !error.field ? error.message : null} />
      <Button type="submit" variant="primary" disabled={change.isPending}>
        {submitLabel}
      </Button>
    </form>
  );
}

export function PasswordDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title="Смена пароля">
      {open && <PasswordForm onDone={() => onOpenChange(false)} />}
    </Dialog>
  );
}
