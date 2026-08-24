import { expect, it } from 'vitest'

import { titleCase } from './title-case.ts'

it('capitalises each word', () => {
  expect(titleCase('roman engineering')).toBe('Roman Engineering')
})

it('leaves stop words lowercase except in first position', () => {
  expect(titleCase('the story of first contact')).toBe('The Story of First Contact')
})

it('capitalises the first word even when it is a stop word', () => {
  expect(titleCase('of mice and men')).toBe('Of Mice and Men')
})

it('tolerates repeated spaces without throwing', () => {
  expect(titleCase('rome  and  ruin')).toBe('Rome  and  Ruin')
})
