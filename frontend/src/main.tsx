import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { LoginGate } from "./modules/auth/LoginGate";
import "./theme/tokens.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <LoginGate>
      <App />
    </LoginGate>
  </StrictMode>,
);
