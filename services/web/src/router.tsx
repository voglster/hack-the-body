import { createBrowserRouter } from "react-router-dom";

import { Dashboard } from "./pages/Dashboard";
import { Kiosk } from "./pages/Kiosk";

export const router = createBrowserRouter([
  { path: "/", element: <Dashboard /> },
  { path: "/kiosk", element: <Kiosk /> },
]);
