export type Severity = 'low' | 'medium' | 'high' | 'critical'
export type Status = 'draft' | 'approved'
export type TestType = 'positive' | 'negative' | 'boundary' | 'integration'
export type FindingClassification = 'requirement' | 'recommendation' | 'needs_clarification'

export interface ReviewItem { id: string; title: string; detail: string; severity: Severity; source_reference: string; classification: FindingClassification }
export interface ExistingCriterion { id: string; criterion: string; source_reference: string }
export interface ReviewContent {
  language: 'vi' | 'en'; business_summary: string
  existing_acceptance_criteria: ExistingCriterion[]
  missing_acceptance_criteria: ReviewItem[]; ambiguities_and_conflicts: ReviewItem[]
  stakeholder_questions: ReviewItem[]; edge_cases: ReviewItem[]; assumptions: ReviewItem[]; risks: ReviewItem[]
}
export interface TestStep { order: number; action: string; expected_result: string }
export interface TestCase {
  id: string; title: string; objective: string; type: TestType; basis: 'requirement' | 'recommendation'; priority: Severity
  preconditions: string[]; test_data: string[]; steps: TestStep[]; expected_result: string
  requirement_traceability: string[]; assumptions: string[]; needs_clarification: boolean
}
export interface CoverageEntry { target_type: 'acceptance_criterion' | 'risk' | 'category'; target_id: string; status: 'covered' | 'needs_clarification'; test_case_ids: string[]; explanation: string }
export interface TestContent { language: 'vi' | 'en'; coverage_summary: string; test_cases: TestCase[]; coverage_matrix: CoverageEntry[] }
export interface Review {
  id: string; story_id: string; story_version: number; ai_original: ReviewContent; content: ReviewContent
  status: Status; stale: boolean; model_name: string; prompt_version: string; approved_at: string | null; created_at: string
}
export interface TestSet {
  id: string; story_id: string; review_id: string; story_version: number; ai_original: TestContent; content: TestContent
  status: Status; stale: boolean; model_name: string; prompt_version: string; approved_at: string | null; created_at: string
}
export interface Story {
  id: string; title: string; description: string; acceptance_criteria: string[]; business_context: string | null
  dependencies: string[]; language: 'auto' | 'vi' | 'en'; version: number; created_at: string; updated_at: string
}
export interface Workspace extends Story { reviews: Review[]; test_case_sets: TestSet[] }

