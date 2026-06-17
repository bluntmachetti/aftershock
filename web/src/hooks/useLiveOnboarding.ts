import { useState, useCallback, useMemo } from 'react'
import { api } from '../lib/api'

export function useLiveOnboarding() {
  const audience: 'public' | 'operator' = useMemo(() => (api.hasToken() ? 'operator' : 'public'), [])

  const [drawerOpen, setDrawerOpen] = useState(false)

  const openHelp = useCallback(() => setDrawerOpen(true), [])
  const closeHelp = useCallback(() => setDrawerOpen(false), [])

  return {
    audience,
    drawerOpen,
    openHelp,
    closeHelp,
  }
}
