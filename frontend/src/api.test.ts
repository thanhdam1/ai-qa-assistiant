import { describe, expect, it } from 'vitest'
import { api, ApiError } from './api'

describe('API client', () => {
  it('builds encoded export URLs from the configured API root', () => {
    expect(api.exportUrl('test-case-sets', 'set-123', 'csv')).toMatch(
      /\/test-case-sets\/set-123\/export\?format=csv$/,
    )
  })

  it('preserves typed API error information', () => {
    const error = new ApiError('stale_version', 'Story is stale', { version: 2 })
    expect(error).toBeInstanceOf(Error)
    expect(error.code).toBe('stale_version')
    expect(error.details).toEqual({ version: 2 })
  })
})
