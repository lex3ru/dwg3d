import { Building2 } from 'lucide-react'
import type { Me } from '../api'

/** The personal cabinet's first page. Buildings arrive with the buildings service (stage 1). */
export function Buildings({ me }: { me: Me }) {
  return (
    <section>
      <h1 className="text-xl font-semibold">Мои здания</h1>
      <div className="mt-6 flex flex-col items-center gap-2 rounded-lg border border-dashed bg-card px-6 py-14 text-center">
        <Building2 className="size-8 text-muted-foreground" />
        <p className="font-medium">Зданий пока нет</p>
        <p className="max-w-md text-sm text-muted-foreground">
          {me.user.is_admin
            ? 'Здесь появятся здания, созданные из чертежей. Загрузка чертежей станет доступна на следующем этапе.'
            : 'Здесь появятся здания, к которым вам выдадут доступ. Обратитесь к администратору здания.'}
        </p>
      </div>
    </section>
  )
}
