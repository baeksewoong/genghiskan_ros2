export interface NavRoute {
  path: string;
  label: string;
}

interface NavSidebarProps {
  routes: NavRoute[];
  currentPath: string;
}

export function NavSidebar({ routes, currentPath }: NavSidebarProps) {
  return (
    <nav className="nav-sidebar">
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
    </nav>
  );
}
