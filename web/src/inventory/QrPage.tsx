import { useQuery } from "@tanstack/react-query";
import { Navigate, useParams } from "react-router";
import { get } from "@/lib/api";
import { Empty, Loading } from "@/ui/misc";

// QR-метка (5.4.7): постоянная ссылка /q/<код> открывает карточку — после входа и при правах
export function QrPage() {
  const { code } = useParams();
  const target = useQuery({ queryKey: ["qr", code], queryFn: () => get<{ href: string }>(`/api/q/${code}`), retry: false });
  if (target.isLoading) return <Loading />;
  if (!target.data) return <Empty title="Метка не найдена">Такой метки нет — или эта вещь вам недоступна.</Empty>;
  return <Navigate to={target.data.href} replace />;
}
