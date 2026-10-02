import { useEffect, useState } from 'react'
import { projectChecks, type ProjectChecks } from '@/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

/** Checks of the engineering systems; the section is hidden from the menu when there is nothing to report. */
export function useChecks(pid: string) {
  const [c, setC] = useState<ProjectChecks | null>(null)
  useEffect(() => { projectChecks(pid).then(setC).catch(() => setC(null)) }, [pid])
  return c
}

export default function Checks({ c }: { c: ProjectChecks }) {
  return (
    <Card>
      <CardHeader><CardTitle>Проверки систем <span className="ml-1 font-normal text-muted-foreground">{c.fire.length}</span></CardTitle></CardHeader>
      <CardContent className="grid gap-3">
        <p className="m-0 text-sm text-muted-foreground">
          Пожарная сигнализация: помещения, где извещателей меньше, чем нужно по площади (один дымовой защищает около 55 м², тепловой — около 27 м²).
          Уточняйте по нормам для высоты потолка.
        </p>
        <ul className="m-0 grid list-none gap-1 p-0">
          {c.fire.slice(0, 50).map((x) => (
            <li key={x.room_id} className="flex flex-wrap items-center gap-3 rounded-lg px-2 py-2 hover:bg-secondary/60">
              <Badge variant="destructive">{x.has} из {x.need}</Badge>
              <div className="min-w-0 flex-1 basis-48">
                <b>{x.room}</b>
                <div className="truncate text-xs text-muted-foreground">{[x.drawing, x.floor].filter(Boolean).join(' · ')} · {x.area.toFixed(1)} м²</div>
              </div>
              <Button asChild variant="secondary" size="sm"><a href={`#/f/${x.drawing_id}`}>Открыть</a></Button>
            </li>
          ))}
        </ul>
        {c.fire.length > 50 && <p className="m-0 text-sm text-muted-foreground">…и ещё {c.fire.length - 50}</p>}
      </CardContent>
    </Card>
  )
}
