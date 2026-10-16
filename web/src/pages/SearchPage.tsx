import { useSearchParams } from "react-router";
import { PageBody } from "@/shell/Shell";
import { SearchBox } from "@/shell/Topbar";
import { PageHeader } from "@/ui/misc";

// Поиск на телефоне — отдельной вкладкой (6.3)
export function SearchPage() {
  const [params] = useSearchParams();
  return (
    <PageBody>
      <PageHeader title="Поиск" />
      <SearchBox autoFocus initial={params.get("q") ?? ""} />
    </PageBody>
  );
}
