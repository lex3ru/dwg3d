import { useEffect, useState } from 'react'
import { getJob, type Job } from '../api'
import { setProjectRole } from '../session'

/** Polls a drawing's job while it is queued or running; the last state stays after a failed request. */
export function useJobPolling(jobId: string | null, nonce: number) {
  const [job, setJob] = useState<Job | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    if (!jobId) return
    let stop = false
    let timer: number | undefined
    const tick = async () => {
      try {
        const j = await getJob(jobId)
        if (stop) return
        setProjectRole(j.my_role)
        setJob(j)
        setError(null)
        if (j.status === 'queued' || j.status === 'running') timer = window.setTimeout(tick, 600)
      } catch (e) {
        if (!stop) {
          setError(String((e as Error).message))
          timer = window.setTimeout(tick, 2000)
        }
      }
    }
    tick()
    return () => { stop = true; window.clearTimeout(timer) }
  }, [jobId, nonce])
  return { job, setJob, error }
}
