import { Sparkles } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Tip } from '@/components/ui/tooltip'
import { Select } from '@/components/ui/select'
import { setNumberAsker, type NumberAnswer, type NumberQuestion } from '../compat'

/** The editor's own question about the inventory number of a new object (instead of the browser's prompt, which a
 * browser may be told to stop showing): the next number in the building is suggested, an empty one puts the object
 * on the plan off the books; a type with makes and models asks which one, if known. */
export default function NumberAsk() {
  const [q, setQ] = useState<NumberQuestion | null>(null)
  const [value, setValue] = useState('')
  const [product, setProduct] = useState('')
  const [making, setMaking] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const generate = () => {
    if (!q) return
    setMaking(true); setError(null)
    q.generate().then((n) => setValue(n), () => setError('Не удалось получить номер: сервис объектов не ответил')).finally(() => setMaking(false))
  }
  const answer = useRef<((v: NumberAnswer | null) => void) | null>(null)
  useEffect(() => setNumberAsker((question) => new Promise((resolve) => {
    answer.current?.(null)
    answer.current = resolve
    setValue(question.suggestion)
    setProduct('')
    setError(null)
    setQ(question)
  })), [])
  const close = (v: string | null) => {
    answer.current?.(v == null ? null : { number: v, product: product || null })
    answer.current = null
    setQ(null)
  }
  const money = (p: NumberQuestion['products'][number]) => (p.price != null ? ` — ${p.price.toLocaleString('ru')} ${p.currency}` : '')
  const ready = true
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
          {q && q.products.length > 0 && (
            <label className="grid gap-1 text-sm text-muted-foreground">Марка и модель
              <Tip label="Какой именно модели этот объект: по ней считается цена варианта и заполняется карточка; можно оставить «не указана» и выбрать в карточке потом">
                <Select className="h-9" value={product} aria-label="Марка и модель" onChange={(e) => setProduct(e.target.value)}>
                  <option value="">не указана</option>
                  {q.products.map((p) => <option key={p.id} value={p.id}>{p.label}{money(p)}</option>)}
                </Select>
              </Tip>
            </label>
          )}
          {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => close(null)}
              hint={q?.optional ? 'Объект не появится в варианте' : 'Объект не будет поставлен'}>Отмена</Button>
            <Button type="submit" disabled={!ready}
              hint={value.trim() ? 'Номер занят навсегда, даже после списания; поменять можно в карточке объекта'
                : 'Без номера объект встанет на план без учёта; поставить на учёт можно потом из его карточки'}>Поставить</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
