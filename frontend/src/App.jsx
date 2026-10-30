import { Navigate, Route, Routes } from 'react-router-dom'
import ProtectedRoute from './app/ProtectedRoute.jsx'
import { PortfolioProvider } from './app/PortfolioContext.jsx'
import AppShell from './layouts/AppShell.jsx'
import AuthPage from './pages/AuthPage.jsx'
import DashboardPage from './pages/DashboardPage.jsx'
import LandingPage from './pages/LandingPage.jsx'
import MutualFundsPage from './pages/MutualFundsPage.jsx'
import StocksPage from './pages/StocksPage.jsx'
import PortfolioInsightsPage from './pages/PortfolioInsightsPage.jsx'
import ResearchPage from './pages/ResearchPage.jsx'
import AssistantPage from './pages/AssistantPage.jsx'
import ReportsPage from './pages/ReportsPage.jsx'
import SettingsPage from './pages/SettingsPage.jsx'
import ImportPortfolioPage from './pages/ImportPortfolioPage.jsx'

export default function App() {
  return <Routes>
    <Route path="/" element={<LandingPage />} />
    <Route path="/login" element={<AuthPage mode="login" />} />
    <Route path="/signup" element={<AuthPage mode="signup" />} />
    <Route path="/app" element={<ProtectedRoute><PortfolioProvider><AppShell /></PortfolioProvider></ProtectedRoute>}>
      <Route index element={<Navigate to="dashboard" replace />} />
      <Route path="dashboard" element={<DashboardPage />} />
      <Route path="investments" element={<Navigate to="/app/import" replace />} />
      <Route path="import" element={<ImportPortfolioPage />} />
      <Route path="mutual-funds" element={<MutualFundsPage />} />
      <Route path="stocks" element={<StocksPage />} />
      <Route path="performance" element={<PortfolioInsightsPage section="performance" />} />
      <Route path="overlap" element={<PortfolioInsightsPage section="overlap" />} />
      <Route path="sectors" element={<PortfolioInsightsPage section="sectors" />} />
      <Route path="research" element={<ResearchPage />} />
      <Route path="assistant" element={<AssistantPage />} />
      <Route path="reports" element={<ReportsPage />} />
      <Route path="settings" element={<SettingsPage />} />
    </Route>
    <Route path="*" element={<Navigate to="/" replace />} />
  </Routes>
}
