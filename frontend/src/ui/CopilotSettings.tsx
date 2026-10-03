import { CheckCircle2, PlugZap, XCircle } from 'lucide-react'
import { useEffect, useState } from 'react'
import { checkCopilot, getCopilotSettings, saveCopilotSettings, type CopilotSettings as Settings } from '@/api'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

/** The copilot's model (admins): an OpenAI-compatible endpoint, its key and model, the limits. */
export default function CopilotSettings({ onClose }: { onClose: () => void }) {
  const [cfg, setCfg] = useState<Settings | null>(null)
  const [key, setKey] = useState('')
  const [dropKey, setDropKey] = useState(false)
  const [models, setModels] = useState<string[]>([])
  const [test, setTest] = useState<{ ok: boolean; text: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => { getCopilotSettings().then(setCfg).catch((e) => setErr((e as Error).message)) }, [])
  const set = (patch: Partial<Settings>) => setCfg((c) => (c ? { ...c, ...patch } : c))

  const runCheck = async () => {
    if (!cfg) return
    setBusy(true)
    setTest(null)
    try {
      const r = await checkCopilot({ base_url: cfg.base_url, model: cfg.model, ...(key ? { api_key: key } : {}) })
      if (r.models?.length) setModels(r.models)
      setTest(r.ok
        ? { ok: true, text: `Модель отвечает${r.answer ? `: «${r.answer}»` : ''}. Инструкции и инструменты копилота — около ${r.prompt_tokens} токенов в каждом запросе: окно контекста модели должно быть заметно больше.` }
        : { ok: false, text: r.error ?? 'Ошибка' })
    } catch (e) { setTest({ ok: false, text: (e as Error).message }) }
    setBusy(false)
  }
  const save = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!cfg) return
    setBusy(true)
    setErr(null)
    try {
      const out = await saveCopilotSettings({
        enabled: cfg.enabled, base_url: cfg.base_url, model: cfg.model, daily_limit: cfg.daily_limit,
        max_steps: cfg.max_steps, temperature: cfg.temperature,
        ...(dropKey ? { api_key: '' } : key ? { api_key: key } : {}),
      })
      setCfg(out)
      setKey('')
      setDropKey(false)
      onClose()
    } catch (ex) { setErr((ex as Error).message) }
    setBusy(false)
  }
  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="max-w-lg">
        <form className="grid gap-4" onSubmit={save}>
          <DialogHeader>
            <DialogTitle>Копилот</DialogTitle>
            <DialogDescription>
              Встроенный помощник во вьювере. Модель — внешняя, с OpenAI-совместимым API (Ollama, vLLM, LM Studio, OpenRouter и др.).
              Копилот работает с проектом от имени пользователя: отвечает, показывает, а изменения только предлагает.
            </DialogDescription>
          </DialogHeader>
          {!cfg ? <p className="m-0 text-sm text-muted-foreground">{err ?? 'Загрузка…'}</p> : (
            <>
              <label className="flex items-center gap-2 text-sm font-medium">
                <input type="checkbox" className="accent-primary" checked={cfg.enabled} onChange={(e) => set({ enabled: e.target.checked })} />
                Копилот включён
              </label>
              <Label>Адрес API
                <Input value={cfg.base_url} placeholder="https://host/v1 или http://localhost:11434/v1" onChange={(e) => set({ base_url: e.target.value })} />
                <span className="text-xs font-normal text-muted-foreground">До <code>/chat/completions</code>; запросы к нему делает сервер программы.</span>
              </Label>
              <Label>API-ключ
                <Input type="password" autoComplete="new-password" value={key} disabled={dropKey}
                  placeholder={cfg.api_key_set ? `задан (${cfg.api_key_hint}) — оставьте пустым, чтобы не менять` : 'не задан (локальным моделям обычно не нужен)'}
                  onChange={(e) => setKey(e.target.value)} />
                {cfg.api_key_set && (
                  <span className="flex items-center gap-2 text-xs font-normal text-muted-foreground">
                    <input type="checkbox" className="accent-primary" checked={dropKey} onChange={(e) => { setDropKey(e.target.checked); setKey('') }} />
                    удалить сохранённый ключ
                  </span>
                )}
              </Label>
              <Label>Модель
                <Input value={cfg.model} list="copilot-models" placeholder="имя модели у провайдера" onChange={(e) => set({ model: e.target.value })} />
                <datalist id="copilot-models">{models.map((m) => <option key={m} value={m} />)}</datalist>
                <span className="text-xs font-normal text-muted-foreground">
                  Нужна модель с вызовом функций (tools) и окном контекста от 16 тыс. токенов; «Проверить» подскажет доступные.
                  Ollama по умолчанию даёт 4 тыс. — задайте <code>OLLAMA_CONTEXT_LENGTH=16384</code> или больше. На процессоре без видеокарты
                  крупные модели отвечают минутами.
                </span>
              </Label>
              <div className="grid grid-cols-3 gap-3">
                <Label>Запросов в день
                  <Input type="number" min={0} value={cfg.daily_limit} onChange={(e) => set({ daily_limit: Number(e.target.value) })} />
                  <span className="text-xs font-normal text-muted-foreground">на пользователя; 0 — без лимита</span>
                </Label>
                <Label>Шагов на вопрос
                  <Input type="number" min={1} max={50} value={cfg.max_steps} onChange={(e) => set({ max_steps: Number(e.target.value) })} />
                </Label>
                <Label>Температура
                  <Input type="number" min={0} max={2} step={0.1} value={cfg.temperature ?? ''} placeholder="по умолч."
                    onChange={(e) => set({ temperature: e.target.value === '' ? null : Number(e.target.value) })} />
                </Label>
              </div>
              {test && (
                <p className={`m-0 flex items-start gap-2 text-sm ${test.ok ? 'text-success' : 'text-destructive'}`}>
                  {test.ok ? <CheckCircle2 className="size-4 shrink-0" /> : <XCircle className="size-4 shrink-0" />} {test.text}
                </p>
              )}
              {err && <p className="m-0 text-sm text-destructive">{err}</p>}
            </>
          )}
          <DialogFooter>
            <Button type="button" variant="secondary" disabled={!cfg?.base_url || !cfg?.model || busy} onClick={runCheck}><PlugZap /> Проверить</Button>
            <Button type="button" variant="secondary" onClick={onClose}>Отмена</Button>
            <Button disabled={!cfg || busy}>Сохранить</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
