import type { Review, ReviewContent, Story, TestContent, TestSet, Workspace } from './types'

const BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000/api'

export class ApiError extends Error {
  constructor(public code: string, message: string, public details: unknown = {}) { super(message) }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${BASE}${path}`, { ...options, headers: { 'Content-Type': 'application/json', ...options.headers } })
  if (!response.ok) {
    const body = await response.json().catch(() => ({ error: { code: 'network_error', message: response.statusText } }))
    throw new ApiError(body.error?.code ?? 'unknown_error', body.error?.message ?? 'Có lỗi xảy ra', body.error?.details)
  }
  return response.json() as Promise<T>
}

export const api = {
  listStories: () => request<Story[]>('/stories'),
  getStory: (id: string) => request<Workspace>(`/stories/${id}`),
  createStory: (body: Omit<Story, 'id' | 'version' | 'created_at' | 'updated_at'>) =>
    request<Story>('/stories', { method: 'POST', body: JSON.stringify(body) }),
  updateStory: (id: string, body: Partial<Story>) => request<Story>(`/stories/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  generateReview: (storyId: string) => request<Review>(`/stories/${storyId}/requirement-reviews`, {
    method: 'POST', headers: { 'Idempotency-Key': crypto.randomUUID() }, body: '{}',
  }),
  updateReview: (id: string, content: ReviewContent) => request<Review>(`/requirement-reviews/${id}`, { method: 'PATCH', body: JSON.stringify({ content }) }),
  approveReview: (id: string) => request<Review>(`/requirement-reviews/${id}/approve`, { method: 'POST', body: '{}' }),
  generateTests: (storyId: string, reviewId: string) => request<TestSet>(`/stories/${storyId}/test-case-sets`, {
    method: 'POST', headers: { 'Idempotency-Key': crypto.randomUUID() }, body: JSON.stringify({ review_id: reviewId }),
  }),
  updateTests: (id: string, content: TestContent) => request<TestSet>(`/test-case-sets/${id}`, { method: 'PATCH', body: JSON.stringify({ content }) }),
  approveTests: (id: string) => request<TestSet>(`/test-case-sets/${id}/approve`, { method: 'POST', body: '{}' }),
  exportUrl: (kind: 'requirement-reviews' | 'test-case-sets', id: string, format: 'json' | 'csv') => `${BASE}/${kind}/${id}/export?format=${format}`,
}

