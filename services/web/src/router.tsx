import { createBrowserRouter } from "react-router-dom";

import { RootRedirect } from "./components/RootRedirect";
import { Dashboard } from "./pages/Dashboard";
import { Kiosk } from "./pages/Kiosk";
import { WorkoutPage } from "./pages/Workout";

export const router = createBrowserRouter([
  { path: "/", element: <RootRedirect /> },
  // Static routes win over `/:tab` by react-router's specificity scoring,
  // so /kiosk and /workout mount their own pages rather than Dashboard.
  { path: "/kiosk", element: <Kiosk /> },
  { path: "/workout", element: <WorkoutPage /> },
  { path: "/:tab", element: <Dashboard /> },
]);
