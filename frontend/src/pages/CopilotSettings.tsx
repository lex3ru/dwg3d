import { useEffect, useState } from 'react'
import { checkCopilot, getCopilotSettings, putCopilotSettings, type CopilotCheck, type CopilotSettings as Settings } from '../api'
import { Badge } from '../components/ui/badge'
import { Button } from '../components/ui/button'
import { Input } from '../components/ui/input'
import { Label } from '../components/ui/label'
import { Switch } from '../components/ui/switch'

/** For the system administrator: which model the copilot talks to, and whether it is on at all. */
export function CopilotSettings() {
  const [saved, setSaved] = useState<Settings | null>(null)
  const [form, setForm] = useState({ base_url: '', model: '', api_key: '', daily_limit: '200', max_steps: '12', temperature: '' })
  const [dropKey, setDropKey] = useState(false)
  const [check, setCheck] = useState<CopilotCheck | 'busy' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState<string | null>(null)
  const take = (s: Settings) => {
    setSaved(s)
    setForm({ base_url: s.base_url, model: s.model, api_key: '', daily_limit: String(s.daily_limit), max_steps: String(s.max_steps),
      temperature: s.temperature === null ? '' : String(s.temperature) })
    setDropKey(false)
  }
  useEffect(() => { getCopilotSettings().then(take, (e: Error) => setError(e.message)) }, [])
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => setForm(f => ({ ...f, [k]: e.target.value }))
  const change = () => ({
    base_url: form.base_url, model: form.model, daily_limit: Number(form.daily_limit), max_steps: Number(form.max_steps),
    temperature: form.temperature.trim() === '' ? null : Number(form.temperature),
    ...(dropKey ? { api_key: '' } : form.api_key ? { api_key: form.api_key } : {}),
  })
  const save = (enabled?: boolean) => {
    setError(null); setDone(null)
    putCopilotSettings({ ...change(), ...(enabled === undefined ? {} : { enabled }) })
      .then(s => { take(s); setDone(enabled === undefined ? 'Сохранено' : enabled ? 'Помощник включён' : 'Помощник выключен') }, (e: Error) => setError(e.message))
  }
  const probe = () => {
    setCheck('busy'); setError(null)
    checkCopilot({ base_url: form.base_url, model: form.model, ...(form.api_key ? { api_key: form.api_key } : {}) })
      .then(setCheck, (e: Error) => setCheck({ ok: false, error: e.message }))
  }
  if (!saved) return <div><h2 className="text-base font-semibold">Помощник (копилот)</h2>{error && <p role="alert" className="mt-2 text-sm text-destructive">{error}</p>}</div>
  const models = check && check !== 'busy' && check.ok ? check.models ?? [] : []
  return (
    <div data-testid="copilot-settings">
      <div className="flex items-center gap-3">
        <h2 className="text-base font-semibold">Помощник (копилот)</h2>
        {saved.enabled ? <Badge variant="success">включён</Badge> : <Badge variant="default">выключен</Badge>}
      </div>
      <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
        Модель с OpenAI-совместимым API: локальная (vLLM, SGLang, Ollama — из контейнера она видна как
        http://host.docker.internal:&lt;порт&gt;/v1) или внешняя. Пока модель не задана и не включена, кнопки помощника у пользователей нет.
      </p>
      <div className="mt-3 grid max-w-2xl gap-3 sm:grid-cols-2">
        <div className="grid gap-1 sm:col-span-2">
          <Label htmlFor="cp-url">Адрес API</Label>
          <Input id="cp-url" value={form.base_url} onChange={set('base_url')} placeholder="http://host.docker.internal:8000/v1" />
        </div>
        <div className="grid gap-1">
          <Label htmlFor="cp-model">Модель</Label>
          <Input id="cp-model" value={form.model} onChange={set('model')} list="cp-models" placeholder="deepseek-v4" />
          <datalist id="cp-models">{models.map(m => <option key={m} value={m} />)}</datalist>
        </div>
        <div className="grid gap-1">
          <Label htmlFor="cp-key">Ключ API {saved.api_key_set && !dropKey && <span className="text-muted-foreground">(задан {saved.api_key_hint})</span>}</Label>
          <Input id="cp-key" type="password" value={form.api_key} onChange={set('api_key')} autoComplete="off" disabled={dropKey}
            placeholder={saved.api_key_set ? 'оставить прежний' : 'не нужен для локальной модели'} />
          {saved.api_key_set && (
            <label className="flex items-center gap-2 text-xs text-muted-foreground">
              <input type="checkbox" checked={dropKey} onChange={e => setDropKey(e.target.checked)} /> удалить сохранённый ключ
            </label>
          )}
        </div>
        <div className="grid gap-1">
          <Label htmlFor="cp-limit">Запросов к модели на пользователя в день (0 — без лимита)</Label>
          <Input id="cp-limit" type="number" min={0} max={100000} value={form.daily_limit} onChange={set('daily_limit')} />
        </div>
        <div className="grid gap-1">
          <Label htmlFor="cp-steps">Шагов на один вопрос</Label>
          <Input id="cp-steps" type="number" min={1} max={50} value={form.max_steps} onChange={set('max_steps')} />
        </div>
        <div className="grid gap-1">
          <Label htmlFor="cp-temp">Температура (пусто — как у модели)</Label>
          <Input id="cp-temp" type="number" min={0} max={2} step={0.1} value={form.temperature} onChange={set('temperature')} />
        </div>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Button variant="outline" onClick={probe} disabled={check === 'busy' || !form.base_url || !form.model}
          hint="Спросить у модели по этому адресу, отвечает ли она; настройки при этом не сохраняются">Проверить</Button>
        <Button onClick={() => save()} hint="Сохранить адрес, модель, ключ и лимиты; включение — отдельным переключателем">Сохранить</Button>
        <label className="ml-2 flex items-center gap-2 text-sm">
          <Switch checked={saved.enabled} disabled={!saved.base_url || !saved.model} aria-label="Включить помощника"
            onCheckedChange={v => save(v)} />
          включить для пользователей
        </label>
        {done && <span className="text-sm text-muted-foreground" role="status">{done}</span>}
      </div>
      {check === 'busy' && <p className="mt-2 text-sm text-muted-foreground">Проверяю…</p>}
      {check && check !== 'busy' && (
        check.ok
          ? <p className="mt-2 text-sm" data-testid="copilot-check">Модель отвечает: «{check.answer}». Подсказка и инструменты занимают около {check.prompt_tokens} токенов на каждый запрос{check.models?.length ? `; доступных моделей: ${check.models.length}` : ''}.</p>
          : <p className="mt-2 text-sm text-destructive" data-testid="copilot-check">Не получилось: {check.error}</p>
      )}
      {error && <p role="alert" className="mt-2 text-sm text-destructive">{error}</p>}
    </div>
  )
}
