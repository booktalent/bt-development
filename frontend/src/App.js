import React from "react";
import "./App.css";
import "./styles/iter39.css";
import "./styles/iter42.css";
import "./styles/iter43.css";
import "./styles/iter44.css";
import "./styles/iter45.css";
import "./styles/iter44_recap.css";
import "./styles/iter45_cart.css";
import "./styles/iter46_planner.css";
import "./styles/iter65_row_flash.css";
import { BrowserRouter, Routes, Route, Navigate, useLocation } from "react-router-dom";
import { HelmetProvider } from "react-helmet-async";
import { AuthProvider, useAuth } from "./lib/auth";
import { ToastProvider } from "./lib/toast";
import Announcements from "./components/Announcements";

import Landing from "./pages/Landing";
import Auth from "./pages/Auth";
import ForgotPassword from "./pages/ForgotPassword";
import { ManagerDashboard, LeadBoard, LeadDetail } from "./pages/manager/ManagerCRM";
import ManagerLeaderboard from "./pages/manager/ManagerLeaderboard";
import ManagerChat from "./pages/manager/ManagerChat";
import { TrustPage, NotificationPreferences } from "./pages/Iter92Pages";
import Search from "./pages/Search";
import ArtistProfile from "./pages/ArtistProfile";
import BookingFlow from "./pages/BookingFlow";
import BookingDetail from "./pages/BookingDetail";
import PaymentReturn from "./pages/PaymentReturn";
import Footer from "./components/Footer";
import CustomerDashboard from "./pages/CustomerDashboard";
import ArtistDashboard from "./pages/ArtistDashboard";
import AdminDashboard from "./pages/AdminDashboard";
import { CorporateDashboard } from "./pages/RoleDashboards";
import NotFound from "./pages/NotFound";
import CmsPage from "./pages/CmsPage";
import HelpCenter from "./pages/HelpCenter";
import CategoryLanding from "./pages/CategoryLanding";
import CityLanding from "./pages/CityLanding";
import BlogList from "./pages/BlogList";
import BlogArticle from "./pages/BlogArticle";
import RecapPage from "./pages/RecapPage";
import EventPlannerPage from "./pages/EventPlannerPage";
import AgencyDashboardV2 from "./pages/agency/AgencyDashboardV2";

function Protected({ children, roles }) {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) return <div className="loading"><div className="spinner" /></div>;
  if (!user) {
    // Iter 73.1 — Preserve the full path+search+hash so post-login /
    // signup returns the user to the exact URL (with pkg/city/date /
    // event_id etc. intact for the BookingFlow). Without this the
    // `Protected` guard was silently dropping deep-link state.
    const next = `${location.pathname}${location.search}${location.hash}`;
    return <Navigate to={`/login?next=${encodeURIComponent(next)}`} replace />;
  }
  if (roles && !roles.includes(user.role)) return <Navigate to="/" replace />;
  return children;
}

// Role guards — hoisted as module constants so identity is stable and
// `Protected` doesn't see a new prop reference on every parent render.
const ROLES_CUSTOMER = ["customer"];
const ROLES_ARTIST = ["artist"];
const ROLES_AGENCY = ["agency"];
const ROLES_CORPORATE = ["corporate"];
const ROLES_ADMIN = ["admin"];

// Iter 63.6 — Global site footer on every page. We only skip the pages
// that already render their own footer (Landing) or where a footer would
// interrupt the flow (booking wizard + payment return + auth screens).
//
// Iter 80 — Uses `useLocation()` so it re-evaluates on every client-side
// navigation. The old `window.location.pathname` read wasn't reactive, so
// after admin → home nav the previous render's footer stayed on screen
// AND Landing's own <Footer /> appeared, showing two footers.
function GlobalFooter() {
  const { pathname } = useLocation();
  if (pathname === "/" || pathname === "/login" || pathname === "/signup") return null;
  if (pathname === "/forgot-password" || pathname === "/reset-password") return null;
  if (pathname.startsWith("/book/") || pathname === "/booking/payment-return") return null;
  return <Footer />;
}

function App() {
  return (
    <div className="App">
      <HelmetProvider>
        <BrowserRouter>
          <AuthProvider>
            <ToastProvider>
              <Announcements />
              <Routes>
                <Route path="/" element={<Landing />} />
                <Route path="/login" element={<Auth mode="signin" />} />
                <Route path="/signup" element={<Auth mode="signup" />} />
                <Route path="/forgot-password" element={<ForgotPassword />} />
                <Route path="/reset-password" element={<ForgotPassword />} />
                <Route path="/manager" element={<ManagerDashboard />} />
                <Route path="/manager/leaderboard" element={<ManagerLeaderboard />} />
                <Route path="/manager/chat" element={<ManagerChat />} />
                {/* Iter 92 — Public trust page + per-user notification prefs */}
                <Route path="/trust" element={<TrustPage />} />
                <Route path="/settings/notifications" element={<Protected><NotificationPreferences /></Protected>} />
                <Route path="/manager/leads" element={<LeadBoard />} />
                <Route path="/manager/leads/:id" element={<LeadDetail />} />
                <Route path="/search" element={<Search />} />
                <Route path="/discover" element={<Search />} />

                {/* SEO-friendly public pages */}
                <Route path="/artist/:id" element={<ArtistProfile />} />
                <Route path="/page/:slug" element={<CmsPage />} />
                <Route path="/help" element={<HelpCenter />} />
                <Route path="/artists/city/:slug" element={<CityLanding />} />
                <Route path="/artists/:slug" element={<CategoryLanding />} />
                <Route path="/blog" element={<BlogList />} />
                <Route path="/blog/:slug" element={<BlogArticle />} />
                <Route path="/recap/:event_id" element={<RecapPage />} />
                <Route path="/planner" element={<EventPlannerPage />} />

                <Route path="/book/:id" element={<Protected><BookingFlow /></Protected>} />
                <Route path="/booking/payment-return" element={<Protected><PaymentReturn /></Protected>} />
                <Route path="/bookings/:id" element={<Protected><BookingDetail /></Protected>} />
                <Route path="/customer" element={<Protected roles={ROLES_CUSTOMER}><CustomerDashboard /></Protected>} />
                <Route path="/artist" element={<Protected roles={ROLES_ARTIST}><ArtistDashboard /></Protected>} />
                <Route path="/agency/*" element={<Protected roles={ROLES_AGENCY}><AgencyDashboardV2 /></Protected>} />
                <Route path="/corporate" element={<Protected roles={ROLES_CORPORATE}><CorporateDashboard /></Protected>} />
                <Route path="/admin" element={<Protected roles={ROLES_ADMIN}><AdminDashboard /></Protected>} />
                <Route path="*" element={<NotFound />} />
              </Routes>
              <GlobalFooter />
            </ToastProvider>
          </AuthProvider>
        </BrowserRouter>
      </HelmetProvider>
    </div>
  );
}

export default App;
