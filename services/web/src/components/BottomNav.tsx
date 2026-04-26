/**
 * Bottom tab nav. Pixel-9 thumb-zone friendly: fixed, 56px-tall hit
 * targets, respects iOS safe-area-inset, persists choice to localStorage
 * so a refresh keeps the user where they were.
 */
import { useEffect, useState } from "react";

export type Tab = "today" | "food" | "trends" | "more";

const TAB_KEY = "htb.activeTab";

const TABS: { id: Tab; label: string; icon: string }[] = [
  { id: "today",  label: "Today",  icon: "●" },
  { id: "food",   label: "Food",   icon: "🍴" },
  { id: "trends", label: "Trends", icon: "📊" },
  { id: "more",   label: "More",   icon: "⋯" },
];

export function useActiveTab(): [Tab, (t: Tab) => void] {
  const [tab, setTabState] = useState<Tab>(() => {
    const saved = (typeof window !== "undefined") ? localStorage.getItem(TAB_KEY) : null;
    return (saved as Tab) || "today";
  });
  useEffect(() => {
    if (typeof window !== "undefined") localStorage.setItem(TAB_KEY, tab);
  }, [tab]);
  return [tab, setTabState];
}

export function BottomNav({ active, onChange }: {
  active: Tab; onChange: (t: Tab) => void;
}) {
  return (
    <nav
      className="fixed bottom-0 inset-x-0 z-20 bg-neutral-950/95 backdrop-blur border-t border-neutral-900"
      style={{ paddingBottom: "env(safe-area-inset-bottom)" }}
    >
      <div className="max-w-6xl mx-auto grid grid-cols-4">
        {TABS.map(t => {
          const isActive = t.id === active;
          return (
            <button
              key={t.id}
              onClick={() => onChange(t.id)}
              className={`flex flex-col items-center justify-center gap-0.5 py-2 min-h-[56px] ${
                isActive ? "text-emerald-400" : "text-neutral-500 active:text-neutral-300"
              }`}
              aria-current={isActive ? "page" : undefined}
            >
              <span className="text-base leading-none">{t.icon}</span>
              <span className="text-[11px] leading-none">{t.label}</span>
            </button>
          );
        })}
      </div>
    </nav>
  );
}
