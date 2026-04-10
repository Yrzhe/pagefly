import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider, useAuth } from '@/hooks/useAuth'
import { AppLayout } from '@/components/layout/AppLayout'
import { LandingPage } from '@/pages/LandingPage'
import { LoginPage } from '@/pages/LoginPage'
import { DashboardPage } from '@/pages/DashboardPage'
import { KnowledgePage } from '@/pages/KnowledgePage'
import { WikiPage } from '@/pages/WikiPage'
import { WorkspacePage } from '@/pages/WorkspacePage'
import { GraphPage } from '@/pages/GraphPage'
import { ApiPage } from '@/pages/ApiPage'
import { SearchPage } from '@/pages/SearchPage'
import { SettingsPage } from '@/pages/SettingsPage'

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { isAuthenticated } = useAuth()
  if (!isAuthenticated) return <Navigate to="/login" replace />
  return <>{children}</>
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/" element={<LandingPage />} />
          <Route path="/login" element={<LoginPage />} />
          <Route
            path="/dashboard"
            element={
              <ProtectedRoute>
                <AppLayout>
                  <DashboardPage />
                </AppLayout>
              </ProtectedRoute>
            }
          />
          <Route
            path="/knowledge"
            element={
              <ProtectedRoute>
                <AppLayout>
                  <KnowledgePage />
                </AppLayout>
              </ProtectedRoute>
            }
          />
          <Route
            path="/wiki"
            element={
              <ProtectedRoute>
                <AppLayout>
                  <WikiPage />
                </AppLayout>
              </ProtectedRoute>
            }
          />
          <Route
            path="/workspace"
            element={
              <ProtectedRoute>
                <AppLayout>
                  <WorkspacePage />
                </AppLayout>
              </ProtectedRoute>
            }
          />
          <Route
            path="/graph"
            element={
              <ProtectedRoute>
                <AppLayout>
                  <GraphPage />
                </AppLayout>
              </ProtectedRoute>
            }
          />
          <Route
            path="/api"
            element={
              <ProtectedRoute>
                <AppLayout>
                  <ApiPage />
                </AppLayout>
              </ProtectedRoute>
            }
          />
          <Route
            path="/search"
            element={
              <ProtectedRoute>
                <AppLayout>
                  <SearchPage />
                </AppLayout>
              </ProtectedRoute>
            }
          />
          <Route
            path="/settings"
            element={
              <ProtectedRoute>
                <AppLayout>
                  <SettingsPage />
                </AppLayout>
              </ProtectedRoute>
            }
          />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  )
}
