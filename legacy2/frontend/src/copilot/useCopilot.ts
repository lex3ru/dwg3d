import { useEffect, useState } from 'react'
import { copilotStatus, type CopilotStatus } from '../api'

/** Whether the copilot is there for this user (the system administrator set a model up) and whether its pane is open. */
export function useCopilot(building: string | null) {
  const [status, setStatus] = useState<CopilotStatus | null>(null)
  const [open, setOpen] = useState(() => sessionStorage.getItem('twin.copilot.open') === '1')
  useEffect(() => { copilotStatus(building).then(setStatus) }, [building])
  useEffect(() => { sessionStorage.setItem('twin.copilot.open', open ? '1' : '0') }, [open])
  return { status: status?.enabled ? status : null, open, setOpen }
}
