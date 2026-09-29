import { useQuery } from "@tanstack/react-query";

import { api } from "../../api/client";
import { describeActivity, type Tone } from "../../lib/recentActivity";

const POLL_MS = 10_000;
const TONE: Record<Tone, string> = {
  done: "text-emerald-300", undone: "text-amber-300", waiting: "text-neutral-400", "needs-you": "text-amber-300",
};

/** Confirms every log and undo for a few minutes — a remote press has no screen of its own. */
export function KioskRecent() {
  const { data } = useQuery({ queryKey: ["capture-recent"], queryFn: api.recentActivity, refetchInterval: POLL_MS });
  if (!data?.length) return null;
  return (
    <section className="flex flex-col gap-2 rounded-2xl border border-neutral-800 bg-neutral-950 px-6 py-4">
      {data.slice(0, 4).map((item) => {
        const line = describeActivity(item);
        return (
          <p key={`${item.at}-${item.kind}-${item.label}`} className={`text-4xl ${TONE[line.tone]}`}>
            <span className="inline-block w-12">{line.icon}</span>{line.text}
          </p>
        );
      })}
    </section>
  );
}
