import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import ReactDOM from "react-dom/client";
import { RouterProvider } from "react-router-dom";

import { AuthGate } from "./components/AuthGate";
import "./index.css";
import { router } from "./router";

const queryClient = new QueryClient();

// Register the service worker (PWA shell + offline fallback). The browser
// only honors this over HTTPS or localhost, so dev over plain http to a LAN
// IP will silently skip — that's fine.
if ("serviceWorker" in navigator && window.location.protocol === "https:") {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {
      // ignore — no UX impact if registration fails
    });
  });
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <AuthGate>
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </AuthGate>
  </React.StrictMode>,
);
