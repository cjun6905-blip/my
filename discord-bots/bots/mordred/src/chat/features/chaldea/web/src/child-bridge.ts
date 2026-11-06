export interface BridgeData {
  accessToken: string
  user: { id: string; username?: string } | null
}

export function setupChildBridge(): Promise<BridgeData | null> {
  if (window.parent === window) return Promise.resolve(null)
  return new Promise((resolve) => {
    const timeout = window.setTimeout(() => {
      window.removeEventListener('message', handler)
      resolve(null)
    }, 6000)
    const handler = (event: MessageEvent) => {
      if (event.data?.type !== 'AUTH_DATA' || !event.data.accessToken) return
      window.clearTimeout(timeout)
      window.removeEventListener('message', handler)
      resolve({
        accessToken: event.data.accessToken,
        user: event.data.user || null,
      })
    }
    window.addEventListener('message', handler)
    window.parent.postMessage({ type: 'CHILD_READY' }, '*')
  })
}

