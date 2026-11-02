import { Container, Group, Text } from '@mantine/core';
import { NavLink, Outlet } from 'react-router';

import { DEMO } from './api';

const NAV = [
  { to: '/', label: 'Claims', end: true },
  { to: '/rollout', label: 'Model rollout', end: false },
  { to: '/about', label: 'How it works', end: false },
];

export function App() {
  return (
    <>
      <header className="bar">
        <Container size="xl" py={10}>
          <Group justify="space-between" wrap="nowrap">
            <Group gap="xl" wrap="nowrap">
              <Group gap={10} wrap="nowrap">
                <img src="favicon.svg" width={28} height={28} alt="" />
                <Text fw={700} size="lg">Claimdesk</Text>
              </Group>
              <nav aria-label="Main">
                <Group gap={4} wrap="nowrap">
                  {NAV.map((n) => (
                    <NavLink key={n.to} to={n.to} end={n.end}>{n.label}</NavLink>
                  ))}
                </Group>
              </nav>
            </Group>
            <Text size="xs" c="#9fb3c8" visibleFrom="md">Kékhíd Biztosító is fictional. All documents are synthetic.</Text>
          </Group>
        </Container>
      </header>
      {DEMO && (
        <div className="demo-strip">
          Read-only demo: recorded runs of the real pipeline. Uploads and reviewer decisions are switched off.{' '}
          <a href="https://github.com/Attila-Hartmann/claimdesk#run-it-locally">Run it yourself</a>
        </div>
      )}
      <Container size="xl" py="xl" component="main">
        <Outlet />
      </Container>
    </>
  );
}
