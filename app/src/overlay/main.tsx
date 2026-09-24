import React from "react";
import { installUiLog } from "../lib/uiLog";
import ReactDOM from "react-dom/client";
import "../i18n";
import "../fonts";
import "./overlay.css";
import { OverlayApp } from "./OverlayApp";

installUiLog();

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <OverlayApp />
  </React.StrictMode>,
);
