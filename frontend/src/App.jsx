import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom'
import { lazy, Suspense } from 'react'
import { AuthProvider } from './contexts/AuthContext'
import { LanguageProvider } from './contexts/LanguageContext'
const Login = lazy(() => import('./pages/Login'))
const Dashboard = lazy(() => import('./pages/Dashboard'))
const Repository = lazy(() => import('./pages/Repository'))
const ProjectWizard = lazy(() => import('./pages/ProjectWizard'))
const ProjectDetails = lazy(() => import('./pages/ProjectDetails'))
const LOCoverageDashboard = lazy(() => import('./pages/LOCoverageDashboard'))
const PlanBuilder = lazy(() => import('./pages/PlanBuilder'))
const EpvoComparison = lazy(() => import('./pages/EpvoComparison'))
const ResearchDashboard = lazy(() => import('./pages/ResearchDashboard'))
const PrerequisiteGraph = lazy(() => import('./pages/PrerequisiteGraph'))
const CourseSyllabus = lazy(() => import('./pages/CourseSyllabus'))

function App() {
    return (
        <LanguageProvider>
            <AuthProvider>
                <Router>
                    <Suspense fallback={<div style={{ padding: 40, textAlign: 'center' }}>Загрузка…</div>}><Routes>
                        <Route path="/login" element={<Login />} />
                        <Route path="/" element={<Dashboard />} />
                        <Route path="/repository" element={<Repository />} />
                        <Route path="/projects/new" element={<ProjectWizard />} />
                        <Route path="/projects/:id" element={<ProjectDetails />} />
                        <Route path="/projects/:id/coverage" element={<LOCoverageDashboard />} />
                        <Route path="/projects/:id/plan" element={<PlanBuilder />} />
                        <Route path="/projects/:id/epvo" element={<EpvoComparison />} />
                        <Route path="/research" element={<ResearchDashboard />} />
                        <Route path="/projects/:id/graph" element={<PrerequisiteGraph />} />
                        <Route path="/projects/:id/syllabus/:kind/:entityId" element={<CourseSyllabus />} />
                    </Routes></Suspense>
                </Router>
            </AuthProvider>
        </LanguageProvider>
    )
}

export default App
