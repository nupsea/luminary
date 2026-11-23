import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import "../index.css"

import { MobileApp } from "./MobileApp"

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <MobileApp />
  </StrictMode>,
)
