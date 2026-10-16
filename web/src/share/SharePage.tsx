import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router";
import { ApiError, post } from "@/lib/api";
import { Loading } from "@/ui/misc";

// Ссылка на просмотр (5.7.2, С21): гость открывает /share/<ключ> — сервер заводит сеанс гостя,
// дальше — план и 3D здания
export function SharePage() {
  const { token } = useParams();
  const navigate = useNavigate();
  const client = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    post<{ building_id: string }>(`/api/share/${token}`)
      .then(async (link) => {
        await client.invalidateQueries({ queryKey: ["me"] });
        navigate(`/plan/${link.building_id}`, { replace: true });
      })
      .catch((e: ApiError) => setError(e.message));
  }, [token, client, navigate]);
  if (!error) return <Loading />;
  return (
    <div className="mx-auto mt-24 max-w-md rounded-xl border border-line bg-surface p-6 text-center">
      <h1 className="m-0 mb-2 text-lg font-semibold">Ссылка не действует</h1>
      <p className="m-0 text-sm text-ink-2">{error}</p>
    </div>
  );
}
