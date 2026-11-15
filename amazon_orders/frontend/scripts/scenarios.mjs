// Synthetic scenarios shared by visual and WCAG checks.
export const screens = [
  ['overview', '/'],
  ['orders', '/orders'],
  ['detail', '/orders/DEMO-01048'],
  ['deadlines', '/deadlines'],
  ['statistics', '/statistics'],
  ['settings', '/settings'],
  ...['auth_required', 'in_progress'].flatMap((state) =>
    [
      ['overview', '/'],
      ['settings', '/settings']
    ].map(([name, route]) => [`${name}-${state}`, route, state])
  )
];
export function screenUrl(route, authState) {
  return `http://127.0.0.1:5173/${authState ? `?mock_auth=${authState}` : ''}#${route}`;
}
