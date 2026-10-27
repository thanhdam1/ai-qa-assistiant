import type { CoverageEntry, TestCase, TestSet, Workspace } from './types'

export const typeLabels = { positive: 'Positive', negative: 'Negative', boundary: 'Boundary', integration: 'Integration' }
export const priorityLabels = { critical: 'Critical', high: 'High', medium: 'Medium', low: 'Low' }
export const targetLabels: Record<CoverageEntry['target_type'], string> = {
  requirement_obligation: 'Requirement', acceptance_criterion: 'Acceptance criterion',
  risk: 'Rủi ro', api_check: 'API finding', category: 'Nhóm test',
}

export function isCaseReady(suite: TestSet, test: TestCase) {
  return !suite.stale && !test.needs_clarification && (suite.case_readiness ?? []).some(item =>
    item.case_id === test.id && item.content_version === suite.content_version &&
    item.story_version === suite.story_version && item.environment_ready && item.test_data_ready && item.verification_ready)
}

export function currentDecisions(suite: TestSet) {
  return suite.stale ? [] : (suite.coverage_decisions ?? []).filter(item =>
    item.content_version === suite.content_version && item.story_version === suite.story_version)
}

export function targetDescription(workspace: Workspace, suite: TestSet, targetId: string): string | undefined {
  const review = workspace.reviews.find(item => item.id === suite.review_id)
  for (const criterion of review?.content.existing_acceptance_criteria ?? []) {
    if (criterion.id === targetId) return criterion.criterion
    const obligation = (criterion.obligations ?? []).find(item => item.id === targetId)
    if (obligation) return obligation.text
  }
  const risk = review?.content.risks.find(item => item.id === targetId)
  if (risk) return risk.title
  const apiReview = workspace.api_contract_reviews.find(item => item.id === suite.api_contract_review_id)
  const finding = apiReview?.content.findings.find(item => item.id === targetId)
  return finding ? `${finding.method} ${finding.path} — ${finding.title}` : undefined
}

export function hasDesignEvidence(row: CoverageEntry) {
  return row.status === 'covered' && Boolean(row.assertion_evidence?.length) && !row.unverified_aspects?.length
}
