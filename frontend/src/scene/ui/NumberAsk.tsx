import { Sparkles } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { setNumberAsker, type NumberQuestion } from '../compat'

/** The editor's own question about the inventory number of a new object (instead of the browser's prompt, which a
 * browser may be told to stop showing): the next number in the building is suggested. */
export default function NumberAsk() {
  const [q, setQ] = useState<NumberQuestion | null>(null)
  const [value, setValue] = useState('')
  const [making, setMaking] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const generate = () => {
    if (!q) return
    setMaking(true); setError(null)
    q.generate().then((n) => setValue(n), () => setError('Не удалось получить номер: сервис объектов не ответил')).finally(() => setMaking(false))
  }
  const answer = useRef<((v: string | null) => void) | null>(null)
  useEffect(() => setNumberAsker((question) => new Promise((resolve) => {
    answer.current?.(null)
    answer.current = resolve
    setValue(question.suggestion)
    setError(null)
    setQ(question)
  })), [])
  const close = (v: string | null) => {
    answer.current?.(v)
    answer.current = null
    setQ(null)
  }
  const ready = q?.optional || value.trim() !== ''
  return (
    <Dialog open={!!q} onOpenChange={(open) => { if (!open) close(null) }}>
      <DialogContent className="max-w-md" data-testid="number-ask">
        <DialogHeader>
          <DialogTitle>{q?.title}</DialogTitle>
          <DialogDescription>{q?.text}</DialogDescription>
        </DialogHeader>
        <form className="grid gap-3" onSubmit={(e) => { e.preventDefault(); if (ready) close(value.trim()) }}>
          <div className="flex gap-2">
            <Input autoFocus className="flex-1" value={value} maxLength={60} aria-label="Инвентарный номер" placeholder="например, КР-0001"
              onChange={(e) => setValue(e.target.value)} onFocus={(e) => e.target.select()} />
            <Button type="button" variant="outline" disabled={making} onClick={generate}
              hint="Номера под рукой нет: система подберёт свободный — продолжит серию этого типа или начнёт новую по первым буквам названия; потом его можно поменять в карточке">
              <Sparkles className="size-4" /> Сгенерировать
            </Button>
          </div>
          {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => close(null)}
              hint={q?.optional ? 'Объект не появится в варианте' : 'Объект не будет поставлен: без инвентарного номера его нет в учёте'}>Отмена</Button>
            <Button type="submit" disabled={!ready}
              hint={ready ? 'Номер занят навсегда, даже после списания; поменять можно в карточке объекта' : 'Сначала укажите номер'}>Поставить</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
