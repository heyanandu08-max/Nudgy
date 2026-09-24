import React from "react";
import { installUiLog } from "./lib/uiLog";
import ReactDOM from "react-dom/client";
import "./i18n";
import "./fonts";
import "./index.css";
import App from "./App";

installUiLog();

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
