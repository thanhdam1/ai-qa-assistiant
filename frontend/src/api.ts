import type {
  ApiContractReview,
  ApiContractReviewContent,
  ApiSpecification,
  CanonicalTestContract,
  CaseReadiness,
  CoverageDecision,
  Review,
  ReviewContent,
  Story,
  TestContent,
  TestSet,
  Workspace,
  ZeroGapSuiteResponse,
} from './types'

const BASE = (import.meta.env.VITE_API_URL ?? 'http://localhost:8000/api').replace(/\/+$/, '')

export class ApiError extends Error {
  constructor(public code: string, message: string, public details: unknown = {}) { super(message) }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const isFormData = typeof FormData !== 'undefined' && options.body instanceof FormData
  const response = await fetch(`${BASE}${path}`, { ...options, headers: isFormData ? options.headers : { 'Content-Type': 'application/json', ...options.headers } })
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
  uploadApiSpecification: (storyId: string, file: File) => {
    const form = new FormData(); form.append('file', file)
    return request<ApiSpecification>(`/stories/${storyId}/api-specifications`, { method: 'POST', body: form })
  },
  generateApiContractReview: (specId: string) => request<ApiContractReview>(`/api-specifications/${specId}/contract-reviews`, {
    method: 'POST', headers: { 'Idempotency-Key': crypto.randomUUID() }, body: '{}',
  }),
  updateApiContractReview: (id: string, content: ApiContractReviewContent) => request<ApiContractReview>(`/api-contract-reviews/${id}`, { method: 'PATCH', body: JSON.stringify(content) }),
  approveApiContractReview: (id: string) => request<ApiContractReview>(`/api-contract-reviews/${id}/approve`, { method: 'POST', body: '{}' }),
  generateReview: (storyId: string) => request<Review>(`/stories/${storyId}/requirement-reviews`, {
    method: 'POST', headers: { 'Idempotency-Key': crypto.randomUUID() }, body: '{}',
  }),
  updateReview: (id: string, content: ReviewContent) => request<Review>(`/requirement-reviews/${id}`, { method: 'PATCH', body: JSON.stringify({ content }) }),
  approveReview: (id: string) => request<Review>(`/requirement-reviews/${id}/approve`, { method: 'POST', body: '{}' }),
  generateTests: (storyId: string, reviewId: string, apiContractReviewId?: string) => request<TestSet>(`/stories/${storyId}/test-case-sets`, {
    method: 'POST', headers: { 'Idempotency-Key': crypto.randomUUID() }, body: JSON.stringify({ review_id: reviewId, api_contract_review_id: apiContractReviewId ?? null }),
  }),
  updateTests: (id: string, content: TestContent) => request<TestSet>(`/test-case-sets/${id}`, { method: 'PATCH', body: JSON.stringify({ content }) }),
  approveTests: (id: string) => request<TestSet>(`/test-case-sets/${id}/approve`, { method: 'POST', body: '{}' }),
  decideCoverage: (id: string, body: Pick<CoverageDecision, 'target_type' | 'target_id' | 'disposition' | 'decided_by' | 'assertion_case_id' | 'assertion' | 'reason' | 'owner'>) => request<TestSet>(`/test-case-sets/${id}/coverage-decisions`, { method: 'PUT', body: JSON.stringify(body) }),
  acceptCoverage: (id: string, accepted_by: string) => request<TestSet>(`/test-case-sets/${id}/coverage-accept`, { method: 'POST', body: JSON.stringify({ accepted_by }) }),
  assessCaseReadiness: (id: string, caseId: string, body: Pick<CaseReadiness, 'assessed_by' | 'environment_ready' | 'test_data_ready' | 'verification_ready' | 'note'>) => request<TestSet>(`/test-case-sets/${id}/cases/${caseId}/readiness`, { method: 'PUT', body: JSON.stringify(body) }),
  exportUrl: (kind: 'requirement-reviews' | 'api-contract-reviews' | 'test-case-sets', id: string, format: 'json' | 'csv' | 'xlsx') => `${BASE}/${kind}/${id}/export?format=${format}`,
  getZeroGapContract: (storyId: string, sourceCode?: string) =>
    request<CanonicalTestContract>(`/stories/${storyId}/zero-gap-contract`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source_code: sourceCode || null }),
    }),
  generateZeroGapSuite: (storyId: string, sourceCode?: string, existingFlaggedIds?: string[]) =>
    request<ZeroGapSuiteResponse>(`/stories/${storyId}/zero-gap-suite`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        source_code: sourceCode || null,
        existing_flagged_ids: existingFlaggedIds || [],
      }),
    }),
  exportZeroGapSuiteExcel: async (storyId: string, suite: ZeroGapSuiteResponse) => {
    const res = await fetch(`${BASE}/stories/${storyId}/zero-gap-suite/export`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(suite),
    })
    if (!res.ok) {
      throw new Error(`Xuất Excel thất bại: ${res.statusText}`)
    }
    const blob = await res.blob()
    const url = window.URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `zero-gap-test-suite-${storyId.slice(0, 8)}.xlsx`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    window.URL.revokeObjectURL(url)
  },
}

