import { describe, expect, it, vi } from 'vitest'

import { ProjectId } from '@domain/shared/identifier.ts'

import type { HttpClient } from './http-client.ts'
import { HttpOntologyRepository } from './ontology-repository.ts'

const project = ProjectId('11111111-1111-4111-8111-111111111111')

/** The two levers are query parameters on URLs this repository builds by hand,
 *  which is the one place a typo in either would be invisible: the server
 *  ignores an unknown parameter and answers the default, so a misspelt
 *  `include_examined` reads as a corpus with nothing left to do and a misspelt
 *  `strict` reads as a lenient pass that quietly stayed strict. Nothing else in
 *  the stack can tell either from a working request. */
describe('HttpOntologyRepository levers', () => {
  it('asks for the examined documents only when a re-read wants them', async () => {
    const get = vi.fn().mockResolvedValue({ sourceIds: [] })
    const repository = new HttpOntologyRepository({ get } as unknown as HttpClient)

    await repository.ungrouped(project)
    await repository.ungrouped(project, { includeExamined: true })

    expect(get.mock.calls.map((call) => call[0] as string)).toEqual([
      // Bare, not `?include_examined=false`: the ordinary sweep's request is
      // unchanged by this feature existing.
      `/api/projects/${project}/sources/ungrouped`,
      `/api/projects/${project}/sources/ungrouped?include_examined=true`,
    ])
  })

  it('sends strict=false only for a lenient pass', async () => {
    const post = vi.fn().mockResolvedValue({ sourceId: 's1', found: 1 })
    const repository = new HttpOntologyRepository({ post } as unknown as HttpClient)

    await repository.discover(project, 's1')
    await repository.discover(project, 's1', { strict: true })
    await repository.discover(project, 's1', { strict: false })

    expect(post.mock.calls.map((call) => call[0] as string)).toEqual([
      `/api/projects/${project}/sources/s1/ontology`,
      `/api/projects/${project}/sources/s1/ontology`,
      `/api/projects/${project}/sources/s1/ontology?strict=false`,
    ])
  })
})
