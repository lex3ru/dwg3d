import { Construction } from "lucide-react";
import { useLocation } from "react-router";
import { useMe } from "@/lib/auth";
import { PageBody } from "@/shell/Shell";
import { findItem, STAGES, titleFor } from "@/shell/menu";
import { Card, PageHeader } from "@/ui/misc";

// Раздел, который появится на следующем этапе: что в нём будет и когда (10.1)
export function Placeholder({ title, stage, about }: { title?: string; stage?: number; about?: string }) {
  const me = useMe();
  const item = findItem(useLocation().pathname);
  const name = title ?? (item ? titleFor(item, me.role) : "Раздел");
  const when = stage ?? item?.stage ?? 0;
  return (
    <PageBody>
      <PageHeader title={name} />
      <Card className="flex items-start gap-4 p-6 max-md:p-4">
        <Construction className="mt-0.5 size-6 shrink-0 text-ink-3" aria-hidden />
        <div className="flex flex-col gap-2">
          <div className="font-medium">
            Раздел появится на этапе {when} «{STAGES[when]}»
          </div>
          <p className="m-0 text-sm text-ink-2">{about ?? item?.about}</p>
        </div>
      </Card>
    </PageBody>
  );
}
