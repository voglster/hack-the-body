/**
 * Tab state lives in the URL (path `/today`, `/food`, `/trends`,
 * `/more`) so browser back/forward, deep links, and PWA refresh all
 * work. The last-used tab is mirrored to localStorage purely so the
 * bare `/` redirect knows where to send a returning user; the URL is
 * the source of truth in-app.
 */
import { useEffect } from "react";
import { useNavigate, useParams } from "react-router-dom";

export type Tab = "today" | "food" | "trends" | "more";

export const VALID_TABS = ["today", "food", "trends", "more"] as const;
export const TAB_KEY = "htb.activeTab";

export function useActiveTab(): [Tab, (t: Tab) => void] {
  const { tab: rawTab } = useParams<{ tab?: string }>();
  const navigate = useNavigate();
  const tab: Tab = (VALID_TABS as readonly string[]).includes(rawTab ?? "")
    ? (rawTab as Tab) : "today";
  // Mirror to localStorage so RootRedirect ("/") sends a returning
  // user back to the same tab they had open.
  useEffect(() => {
    if (typeof window !== "undefined") localStorage.setItem(TAB_KEY, tab);
  }, [tab]);
  const setTab = (t: Tab): void => { void navigate(`/${t}`); };
  return [tab, setTab];
}
