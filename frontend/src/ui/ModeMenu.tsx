import { ChevronDown } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { DropdownMenu, DropdownMenuContent, DropdownMenuLabel, DropdownMenuRadioGroup, DropdownMenuRadioItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { CUSTOM, MODES, type ModeDef } from '@/viewmodes'

/** The view modes of the scene (top right): one choice instead of a dozen switches. */
export default function ModeMenu({ mode, onMode }: { mode: ModeDef | null; onMode: (m: ModeDef) => void }) {
  const Icon = (mode ?? CUSTOM).icon
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="secondary" aria-label="Режим вида" title="Режим вида: готовые наборы слоёв и отображения (клавиши 1–5)"
          className="h-10 gap-1.5 rounded-full border-0 bg-float px-3 shadow-md backdrop-blur @max-4xl:px-2.5">
          <Icon className="size-4" /> <span className="@max-4xl:hidden">{(mode ?? CUSTOM).label}</span> <ChevronDown className="size-3.5 text-muted-foreground" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-72">
        <DropdownMenuLabel>Режим вида</DropdownMenuLabel>
        <DropdownMenuRadioGroup value={mode?.id ?? ''} onValueChange={(v) => { const m = MODES.find((x) => x.id === v); if (m) onMode(m) }}>
          {MODES.map((m) => (
            <DropdownMenuRadioItem key={m.id} value={m.id} className="items-start">
              <m.icon className="mt-0.5" />
              <span className="grid">
                <span>{m.label} <kbd className="ml-1 rounded border border-border px-1 text-[10px] text-muted-foreground">{m.key}</kbd></span>
                <span className="text-xs text-muted-foreground">{m.hint}</span>
              </span>
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
        {!mode && <p className="m-0 px-2 py-1.5 text-xs text-muted-foreground">Сейчас — свой вид: настройки изменены вручную.</p>}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
