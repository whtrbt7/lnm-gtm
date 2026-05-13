import { describe, test, expect } from 'vitest'
import { buildGadsAccountName } from './create-mcc-account.js'

describe('buildGadsAccountName', () => {
  test('uses last word of account name as last name', () => {
    const result = buildGadsAccountName('John Smith', 'Smith Auto', 'Chicago North', new Date('2026-05-12T00:00:00Z'))
    expect(result).toBe('Smith | Smith Auto - Chicago North - 2026-05-12')
  })

  test('handles single-word account name', () => {
    const result = buildGadsAccountName('Smith', 'Smith Auto', 'Main St', new Date('2026-05-12T00:00:00Z'))
    expect(result).toBe('Smith | Smith Auto - Main St - 2026-05-12')
  })

  test('handles extra whitespace in account name', () => {
    const result = buildGadsAccountName('  John  Smith  ', 'Smith Auto', 'North', new Date('2026-05-12T00:00:00Z'))
    expect(result).toBe('Smith | Smith Auto - North - 2026-05-12')
  })
})
