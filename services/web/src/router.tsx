import { createBrowserRouter } from "react-router-dom";

import { RootRedirect } from "./components/RootRedirect";
import { Dashboard } from "./pages/Dashboard";
import { Kiosk } from "./pages/Kiosk";

export const router = createBrowserRouter([
  { path: "/", element: <RootRedirect /> },
  // Static routes win over `/:tab` by react-router's specificity scoring,
  // so /kiosk continues to mount the Kiosk page rather than Dashboard.
  { path: "/kiosk", element: <Kiosk /> },
  { path: "/:tab", element: <Dashboard /> },
]);
