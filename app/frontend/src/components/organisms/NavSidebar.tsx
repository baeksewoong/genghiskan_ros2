export interface NavRoute {
  path: string;
  label: string;
}

interface NavSidebarProps {
  routes: NavRoute[];
  currentPath: string;
  open: boolean;
  onToggle: () => void;
}

export function NavSidebar({ routes, currentPath, open, onToggle }: NavSidebarProps) {
  return (
    <nav className={`nav-sidebar${open ? "" : " collapsed"}`}>
      <div className="nav-toggle-row">
        <button
          type="button"
          className="nav-toggle"
          onClick={onToggle}
          aria-expanded={open}
          aria-label={open ? "네비게이션 접기" : "네비게이션 펼치기"}
          title={open ? "네비게이션 접기" : "네비게이션 펼치기"}
        >
          {open ? "«" : "»"}
        </button>
      </div>
      {open && (
        <>
          <h2>페이지</h2>
          <ul>
            {routes.map((route) => (
              <li key={route.path}>
                <a href={route.path} className={route.path === currentPath ? "active" : ""}>
                  {route.label}
                </a>
              </li>
            ))}
          </ul>
        </>
      )}
    </nav>
  );
}
