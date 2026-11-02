import '@mantine/core/styles.css';
import './app.css';

import { createTheme, MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { createHashRouter, RouterProvider } from 'react-router';

import { App } from './App';
import { About } from './pages/About';
import { ClaimDetail } from './pages/ClaimDetail';
import { Claims } from './pages/Claims';
import { Rollout } from './pages/Rollout';

const theme = createTheme({
  primaryColor: 'kek',
  colors: {
    kek: ['#eaf3fb', '#d3e4f3', '#a6c8e8', '#76aadc', '#4f91d2', '#3780cc', '#2a76c9', '#1d64b1', '#12569f', '#12355b'],
  },
  fontFamily: "'IBM Plex Sans', system-ui, sans-serif",
  fontFamilyMonospace: "'IBM Plex Mono', ui-monospace, monospace",
  headings: { fontFamily: "'IBM Plex Sans', system-ui, sans-serif", fontWeight: '650' },
  defaultRadius: 'md',
});

// Hash routing: works on any static host (GitHub Pages) without server rewrites.
const router = createHashRouter([
  {
    path: '/',
    element: <App />,
    children: [
      { index: true, element: <Claims /> },
      { path: 'claims/:id', element: <ClaimDetail /> },
      { path: 'rollout', element: <Rollout /> },
      { path: 'about', element: <About /> },
    ],
  },
]);

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <MantineProvider theme={theme}>
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { refetchOnWindowFocus: false } } })}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </MantineProvider>
  </StrictMode>,
);
