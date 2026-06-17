import { useState, useCallback, useMemo } from 'react'
import { api } from '../lib/api'

const BRIEFING_KEY_PREFIX = 'aftershock-live-briefing-seen-v1'

function storageGet(key: string): boolean {
  try {
    return localStorage.getItem(key) === '1'
  } catch {
    return false
  }
}

function storageSet(key: string, value: string): void {
  try {
    localStorage.setItem(key, value)
  } catch {
    /* private mode / storage disabled */
  }
}

export function useLiveOnboarding() {
  const audience: 'public' | 'operator' = useMemo(() => (api.hasToken() ? 'operator' : 'public'), [])

  const [bannerDismissed, setBannerDismissed] = useState<boolean>(() =>
    storageGet(`${BRIEFING_KEY_PREFIX}-${audience}`),
  )

  const [drawerOpen, setDrawerOpen] = useState(false)

  const dismissBanner = useCallback(() => {
    setBannerDismissed(true)
    storageSet(`${BRIEFING_KEY_PREFIX}-${audience}`, '1')
  }, [audience])

  const openHelp = useCallback(() => setDrawerOpen(true), [])
  const closeHelp = useCallback(() => setDrawerOpen(false), [])

  return {
    audience,
    bannerDismissed,
    drawerOpen,
    dismissBanner,
    openHelp,
    closeHelp,
  }
}
