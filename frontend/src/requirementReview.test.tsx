import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import { ReviewPanel } from './ReviewPanels'
import { api } from './api'
import type { Review } from './types'

const review: Review = {
  id: 'review', story_id: 'story', story_version: 1, status: 'draft', stale: false,
  model_name: 'test', prompt_version: 'review-v5', approved_at: null, created_at: '',
  content: { language: 'en', business_summary: 'Login',
    existing_acceptance_criteria: [{ id: 'REQ', criterion: 'Wrong password returns HTTP 200', source_reference: 'acceptance_criteria[0]', obligations: [] }],
    missing_acceptance_criteria: [{ id: 'F', title: 'Test view_count', detail: 'Business context mentions views but lacks an AC', severity: 'high', source_reference: 'business_context', classification: 'recommendation', proposed_ac: 'Viewing a valid product increases view_count by 1' }],
    stakeholder_questions: [], assumptions: [], ambiguities_and_conflicts: [], edge_cases: [], risks: [] },
  ai_original: {} as Review['content'],
}
const noop = async () => {}
const props = { sourceCriteria: ['Wrong password returns HTTP 401'], busy: '', requiresApiReview: false,
  onApprove: noop, onSave: noop, onGenerateTests: noop, onRegenerate: noop, onAcceptFinding: noop }

describe('requirement review', () => {
  it('shows original source and flags changed interpretation before approval', () => {
    const html = renderToStaticMarkup(<ReviewPanel {...props} review={review} />)
    expect(html).toContain('Wrong password returns HTTP 401')
    expect(html).toContain('Cần QA xác nhận')
    expect(html).toContain('Xem trước &amp; thêm AC')
  })
  it('does not offer acceptance from a stale review', () => {
    const html = renderToStaticMarkup(<ReviewPanel {...props} review={{ ...review, stale: true }} />)
    expect(html).not.toContain('Xem trước &amp; thêm AC')
  })
  it('shows accepted AC and attribution instead of another acceptance button', () => {
    const content = structuredClone(review.content)
    content.missing_acceptance_criteria[0].accepted_ac = 'AC-11: Valid views increment view_count'
    content.missing_acceptance_criteria[0].accepted_by = 'PO'
    const html = renderToStaticMarkup(<ReviewPanel {...props} review={{ ...review, content }} />)
    expect(html).toContain('AC-11: Valid views increment view_count')
    expect(html).not.toContain('Xem trước &amp; thêm AC')
  })
  it('sends explicit confirmed behavior and source version, never finding analysis', async () => {
    const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{}', { status: 200 }))
    try {
      await api.acceptRecommendation('story', 'F', 'review', 3, 'Viewing a product', 'view_count +1', 'PO')
      const payload = JSON.parse(fetch.mock.calls[0][1]?.body as string)
      expect(payload).toEqual({ finding_id: 'F', review_id: 'review', expected_story_version: 3,
        custom_text: 'Viewing a product', expected_result: 'view_count +1', confirmed_by: 'PO' })
      expect(JSON.stringify(payload)).not.toContain('Business context mentions')
    } finally { fetch.mockRestore() }
  })
})
