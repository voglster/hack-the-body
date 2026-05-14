import { useQuery } from "@tanstack/react-query";

import { api } from "../../api/client";
import { recoverySentence } from "../../lib/recoverySummary";

export function KioskRecoverySentence() {
  const { data } = useQuery({
    queryKey: ["summary"],
    queryFn: api.summary,
    refetchInterval: 5 * 60_000,
  });
  return (
    <section className="text-2xl text-neutral-500 italic">
      {recoverySentence(data)}
    </section>
  );
}
