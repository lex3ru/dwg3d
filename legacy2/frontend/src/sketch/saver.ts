/**
 * Saving a document that changes while it is being saved: one save at a time,
 * the newest value after it, over the version the server last confirmed. A
 * conflict (someone else saved meanwhile) stops saving until `reset`.
 */
export type SaverState = 'saving' | 'saved' | 'conflict' | 'failed'

export class Conflict extends Error {}

export class Saver<T> {
  private version = 0
  private saved: T | null = null
  private latest: T | null = null
  private running: Promise<void> | null = null
  private stopped = false
  private send: (value: T, version: number) => Promise<number>
  private report: (state: SaverState, error?: Error) => void

  /** `send` stores the value over `version` and gives the new version, or throws Conflict */
  constructor(send: (value: T, version: number) => Promise<number>, report: (state: SaverState, error?: Error) => void) {
    this.send = send
    this.report = report
  }

  /** what the server has, as just loaded */
  reset(value: T, version: number): void {
    this.saved = this.latest = value
    this.version = version
    this.stopped = false
  }

  /** the value now; false when there is nothing to save (it is the saved one) or saving has stopped */
  change(value: T): boolean {
    if (this.stopped) return false
    this.latest = value
    return this.dirty
  }

  get dirty(): boolean { return this.latest !== this.saved }

  /** saves what is not saved yet; resolves when the server has the newest value */
  save(): Promise<void> {
    if (this.running) return this.running
    if (this.stopped) return Promise.resolve()
    if (!this.dirty) {                    // back to what is saved (undone): nothing to send, and it is saved
      this.report('saved')
      return Promise.resolve()
    }
    const p = this.run()
    this.running = p
    // cleared once over, and only if still this one: a promise kept after it ended would stop all saving
    p.then(() => {}, () => {}).then(() => { if (this.running === p) this.running = null })
    return p
  }

  private async run(): Promise<void> {
    try {
      while (this.latest !== null && this.dirty && !this.stopped) {
        const sent = this.latest
        this.report('saving')
        this.version = await this.send(sent, this.version)
        this.saved = sent
      }
      if (!this.stopped) this.report('saved')
    } catch (e) {
      if (e instanceof Conflict) this.stopped = true
      this.report(e instanceof Conflict ? 'conflict' : 'failed', e as Error)
      throw e
    }
  }
}
