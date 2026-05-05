import { createBrowserRouter } from "react-router-dom";

import { RootRedirect } from "./components/RootRedirect";
import { Dashboard } from "./pages/Dashboard";
import { Kiosk } from "./pages/Kiosk";
import { WorkoutPage } from "./pages/Workout";
import { WorkoutList } from "./pages/WorkoutList";
import { WorkoutDetail } from "./pages/WorkoutDetail";

export const router = createBrowserRouter([
  { path: "/", element: <RootRedirect /> },
  // Static routes win over `/:tab` by react-router's specificity scoring,
  // so /kiosk, /workout, and /workouts mount their own pages rather than Dashboard.
  { path: "/kiosk", element: <Kiosk /> },
  { path: "/workout", element: <WorkoutPage /> },
  { path: "/workouts", element: <WorkoutList /> },
  { path: "/workouts/:sourceId", element: <WorkoutDetail /> },
  { path: "/:tab", element: <Dashboard /> },
]);
