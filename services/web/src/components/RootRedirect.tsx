/** Bare `/` → the last-used tab (or `today` cold-start). Keeps the
 *  app's home URL stable even though the user's actual landing page
 *  varies. Lives in its own file so the route table can stay
 *  data-only (Vite's fast-refresh likes that). */
import { Navigate } from "react-router-dom";

import { TAB_KEY, VALID_TABS } from "./BottomNav";

export function RootRedirect() {
  const saved = typeof window === "undefined" ? null : localStorage.getItem(TAB_KEY);
  const tab = saved && (VALID_TABS as readonly string[]).includes(saved)
    ? saved : "today";
  return <Navigate to={`/${tab}`} replace />;
}
