import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { createApi, fetchSession } from "./api/client";
import { Alert } from "./components/ui";
import "./index.css";

const container = document.getElementById("root");
if (container === null) {
  throw new Error("Missing #root element");
}
const root = createRoot(container);

fetchSession().then(
  (session) => {
    // Mutations echo the CSRF token from the session in X-GREGraph-Token.
    const api = createApi({ token: session.csrf_token });
    root.render(
      <StrictMode>
        <App session={session} api={api} />
      </StrictMode>,
    );
  },
  (error: unknown) => {
    const message = error instanceof Error ? error.message : "Unknown error";
    root.render(
      <StrictMode>
        <main className="mx-auto max-w-lg p-6">
          <Alert>Could not start GREGraph: {message}</Alert>
        </main>
      </StrictMode>,
    );
  },
);
