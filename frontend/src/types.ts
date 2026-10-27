export type Severity = 'low' | 'medium' | 'high' | 'critical'
export type Status = 'draft' | 'approved'
export type TestType = 'positive' | 'negative' | 'boundary' | 'integration'
export type FindingClassification = 'requirement' | 'recommendation' | 'needs_clarification'
export type ApiFindingType = 'positive' | 'negative' | 'boundary' | 'schema' | 'security' | 'gap' | 'conflict'

export interface ReviewItem { id: string; title: string; detail: string; severity: Severity; source_reference: string; classification: FindingClassification }
export interface ExistingCriterion { id: string; criterion: string; source_reference: string; source_id?: string | null; revision?: number; obligations: RequirementObligation[] }
export interface RequirementObligation { id: string; text: string; revision?: number; supersedes?: string[] }
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
  requirement_traceability: string[]; api_traceability: string[]; api_method: string | null; api_path: string | null
  api_request: string | null; expected_status_codes: number[]; assumptions: string[]; needs_clarification: boolean
}
export interface CoverageAssertion { test_case_id: string; assertion: string; verifies_business_outcome: boolean }
export interface CoverageEntry { target_type: 'acceptance_criterion' | 'requirement_obligation' | 'risk' | 'category' | 'api_check'; target_id: string; status: 'covered' | 'needs_clarification'; test_case_ids: string[]; explanation: string; assertion_evidence?: CoverageAssertion[]; unverified_aspects?: string[] }
export interface TestContent { language: 'vi' | 'en'; coverage_summary: string; test_cases: TestCase[]; coverage_matrix: CoverageEntry[] }
export interface ApiOperation { operation_id: string; method: string; path: string; summary: string }
export interface ApiSpecification {
  id: string; story_id: string; title: string; file_name: string; openapi_version: string; version: number
  operations: ApiOperation[]; checksum: string; stale: boolean; created_at: string
}
export interface ApiContractFinding {
  id: string; operation_id: string; method: string; path: string; type: ApiFindingType; title: string; detail: string
  severity: Severity; classification: FindingClassification; source_reference: string
  story_reference: string | null
  expected_status_codes: number[]; needs_clarification: boolean
}
export interface ApiContractReviewContent { language: 'vi' | 'en'; summary: string; operations: ApiOperation[]; findings: ApiContractFinding[] }
export interface ApiContractReview {
  id: string; story_id: string; specification_id: string; story_version: number
  ai_original: ApiContractReviewContent; content: ApiContractReviewContent; status: Status; stale: boolean
  model_name: string; prompt_version: string; approved_at: string | null; created_at: string; updated_at: string
}
export interface Review {
  id: string; story_id: string; story_version: number; ai_original: ReviewContent; content: ReviewContent
  status: Status; stale: boolean; model_name: string; prompt_version: string; approved_at: string | null; created_at: string
}
export interface TestSet {
  id: string; story_id: string; review_id: string; api_contract_review_id: string | null
  story_version: number; ai_original: TestContent; content: TestContent
  generation_info?: { quarantined_api_case_ids?: string[] }
  status: Status; stale: boolean; model_name: string; prompt_version: string; approved_at: string | null; created_at: string
  review_status: Status; coverage_status: 'complete' | 'partial' | 'unsubstantiated'
  coverage_acceptance_status: 'pending' | 'accepted'; execution_readiness: 'not_assessed' | 'partial' | 'ready'
  coverage_target_count: number; candidate_coverage_count: number; qa_confirmed_target_count: number; gap_decision_count: number
  content_version: number; coverage_accepted_at: string | null; coverage_accepted_by: string | null
  coverage_decisions: CoverageDecision[]; case_readiness: CaseReadiness[]
}
export type GapDisposition = 'confirmed' | 'accepted_risk' | 'deferred' | 'blocked' | 'not_applicable'
export interface CoverageDecision { target_type: CoverageEntry['target_type']; target_id: string; disposition: GapDisposition; decided_by: string; decided_at: string; assertion_case_id: string | null; assertion: string | null; reason: string | null; owner: string | null; story_version: number; content_version: number }
export interface CaseReadiness { case_id: string; assessed_by: string; environment_ready: boolean; test_data_ready: boolean; verification_ready: boolean; note: string | null; story_version: number; content_version: number }
export interface Story {
  id: string; title: string; description: string; acceptance_criteria: string[]; business_context: string | null
  dependencies: string[]; language: 'auto' | 'vi' | 'en'; version: number; created_at: string; updated_at: string
}
export interface Workspace extends Story {
  reviews: Review[]; test_case_sets: TestSet[]; api_specifications: ApiSpecification[]; api_contract_reviews: ApiContractReview[]
}

