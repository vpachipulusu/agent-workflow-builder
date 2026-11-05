import { useState, useEffect } from 'react'
import { Routes, Route, NavLink, useLocation } from 'react-router-dom'
import AgentBuilderPage from './components/AgentBuilderPage'
import WorkflowBuilderPage from './components/WorkflowBuilderPage'
import HomePage from './components/HomePage'
import WeekendSaverPage from './components/weekend-saver/WeekendSaverPage'

export default function App() {
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [darkMode, setDarkMode] = useState(() => {
    const saved = localStorage.getItem('theme')
    return saved === 'dark'
  })
  const location = useLocation()

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', darkMode ? 'dark' : 'light')
    localStorage.setItem('theme', darkMode ? 'dark' : 'light')
  }, [darkMode])

  const closeSidebar = () => setSidebarOpen(false)

  // Close sidebar on route change (mobile)
  const navLinkClass = ({ isActive }: { isActive: boolean }) =>
    `sidebar-link ${isActive ? 'active' : ''}`

  return (
    <div className={`app-layout ${sidebarCollapsed ? 'sidebar-collapsed' : ''}`}>
      {/* Mobile header */}
      <div className="mobile-header">
        <button className="mobile-hamburger" onClick={() => setSidebarOpen(!sidebarOpen)}>
          {sidebarOpen ? '✕' : '☰'}
        </button>
        <span className="mobile-title">MAF Code Builder</span>
      </div>

      {/* Overlay */}
      <div
        className={`sidebar-overlay ${sidebarOpen ? 'sidebar-overlay--visible' : ''}`}
        onClick={closeSidebar}
      />

      {/* Sidebar */}
      <nav className={`sidebar ${sidebarOpen ? 'sidebar--open' : ''}`}>
        <div className="sidebar-brand">
          <div className="sidebar-brand-icon">⚡</div>
          {!sidebarCollapsed && (
            <div className="sidebar-brand-text">
              <h1>Agent Framework</h1>
              <span className="sidebar-subtitle">Code Builder</span>
            </div>
          )}
        </div>

        {!sidebarCollapsed && <div className="sidebar-section">ナビゲーション</div>}

        <NavLink to="/" end className={navLinkClass} onClick={closeSidebar}>
          <span className="sidebar-link-icon">🏠</span>
          {!sidebarCollapsed && 'ホーム'}
        </NavLink>
        <NavLink to="/agents" className={navLinkClass} onClick={closeSidebar}>
          <span className="sidebar-link-icon">🤖</span>
          {!sidebarCollapsed && 'エージェント'}
        </NavLink>
        <NavLink to="/workflows" className={navLinkClass} onClick={closeSidebar}>
          <span className="sidebar-link-icon">🔀</span>
          {!sidebarCollapsed && 'ワークフロー'}
        </NavLink>
        <NavLink to="/weekend-saver" className={navLinkClass} onClick={closeSidebar}>
          <span className="sidebar-link-icon">🌙</span>
          {!sidebarCollapsed && 'Weekend Saver'}
        </NavLink>

        <div style={{ flex: 1 }} />
        <button
          className="sidebar-theme-btn"
          onClick={() => setDarkMode(prev => !prev)}
          title={darkMode ? 'ライトモードに切替' : 'ダークモードに切替'}
        >
          {darkMode ? '☀️' : '🌙'}
          {!sidebarCollapsed && (darkMode ? ' ライト' : ' ダーク')}
        </button>
        <button
          className="sidebar-collapse-btn"
          onClick={() => setSidebarCollapsed(prev => !prev)}
          title={sidebarCollapsed ? 'サイドバーを開く' : 'サイドバーを閉じる'}
        >
          {sidebarCollapsed ? '»' : '«'}
        </button>
      </nav>

      <main className="main-content">
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/agents" element={<AgentBuilderPage />} />
          <Route path="/workflows" element={<WorkflowBuilderPage />} />
          <Route path="/weekend-saver" element={<WeekendSaverPage />} />
        </Routes>
      </main>
    </div>
  )
}
