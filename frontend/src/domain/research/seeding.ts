/** Where one seeding run has got to.
 *
 * Unlike `Extraction`, this is not folded from a stream of notes -- the
 * server has nothing durable to fold either (see `seeding.py`'s module
 * docstring), so the catch-up route just hands back the one frame a run is
 * currently at. There is exactly one to read, not a sequence to accumulate.
 */
export type SeedingStatus = 'running' | 'done' | 'failed'

export interface SeedingRun {
  readonly runId: string
  readonly status: SeedingStatus
  /** The subject this run was asked to seed. Present on every status the
   *  wire actually sends today, but typed nullable because a status this
   *  build does not yet recognise should not force a caller to invent one. */
  readonly subject: string | null
  /** The model's own account of what it did, once a run has finished. */
  readonly reply: string | null
  /** Why a run failed. `null` on anything but `failed`. */
  readonly detail: string | null
}
