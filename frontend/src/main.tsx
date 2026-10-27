import { MotionConfig } from "framer-motion";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import AnimatedRoutes from "./components/AnimatedRoutes";
import Nav from "./components/Nav";
import { AuthProvider, useAuth } from "./lib/auth";
import { Login, Signup } from "./pages/Auth";
import "./index.css";
import "./theme.css";

/** Signed out: only the Log in and Create account pages. Signed in: the app. */
function App() {
  const { user } = useAuth();
  const location = useLocation();

  if (user === undefined) return <div className="skeleton" style={{ height: "100vh", borderRadius: 0 }} aria-busy="true" />;

  if (user === null) {
    return (
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/signup" element={<Signup />} />
        <Route path="*" element={<Navigate to="/login" replace state={{ from: location.pathname + location.search }} />} />
      </Routes>
    );
  }

  if (location.pathname === "/login" || location.pathname === "/signup") {
    // Back to the page they were trying to open before being sent to log in.
    const from = (location.state as { from?: string } | null)?.from;
    return <Navigate to={from && from !== "/login" && from !== "/signup" ? from : "/"} replace />;
  }

  return (
    <div className="shell">
      <Nav />
      <main className="content" id="main">
        <div className="page">
          <AnimatedRoutes />
        </div>
      </main>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <MotionConfig reducedMotion="user">
      <BrowserRouter>
        <AuthProvider>
          <App />
        </AuthProvider>
      </BrowserRouter>
    </MotionConfig>
  </StrictMode>,
);
