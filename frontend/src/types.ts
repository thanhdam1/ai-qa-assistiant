export type Severity = 'low' | 'medium' | 'high' | 'critical'
export type Status = 'draft' | 'approved'
export type TestType = 'positive' | 'negative' | 'boundary' | 'integration'
export type FindingClassification = 'requirement' | 'recommendation' | 'needs_clarification'
export type ApiFindingType = 'positive' | 'negative' | 'boundary' | 'schema' | 'security' | 'gap' | 'conflict'

export interface ReviewItem {
  proposed_ac?: string | null; resolution_status?: 'open' | 'resolved' | 'rejected'
  answer?: string | null; owner?: string | null; blocks_testability?: boolean
  related_requirement_ids?: string[]; resolved_by?: string | null
  accepted_ac?: string | null; accepted_by?: string | null
  id: string; title: string; detail: string; severity: Severity; source_reference: string; classification: FindingClassification }
export interface ExistingCriterion { source_quote?: string | null; confirmed_by?: string | null; id: string; criterion: string; source_reference: string; source_id?: string | null; revision?: number; obligations: RequirementObligation[] }
export interface RequirementObligation { source_quote?: string | null; id: string; text: string; revision?: number; supersedes?: string[] }
export interface ReviewContent {
  language: 'vi' | 'en'; business_summary: string
  existing_acceptance_criteria: ExistingCriterion[]
  missing_acceptance_criteria: ReviewItem[]; ambiguities_and_conflicts: ReviewItem[]
  stakeholder_questions: ReviewItem[]; edge_cases: ReviewItem[]; assumptions: ReviewItem[]; risks: ReviewItem[]
}
export interface UpstreamTraceItem {
  source_story_id: string
  source_story_title?: string | null
  source_version: number
  consumed_fields: string[]
  bound_rules: string[]
  contract_reference?: string | null
}

export interface TestStep { order: number; action: string; expected_result: string }
export interface TestCase {
  id: string; title: string; objective: string; type: TestType; basis: 'requirement' | 'recommendation'; priority: Severity
  preconditions: string[]; test_data: string[]; steps: TestStep[]; expected_result: string
  requirement_traceability: string[]; api_traceability: string[]; api_method: string | null; api_path: string | null
  api_request: string | null; expected_status_codes: number[]; assumptions: string[]; needs_clarification: boolean
  is_customized?: boolean
  upstream_traceability?: UpstreamTraceItem[]
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
export interface CaseReadiness { case_id: string; assessed_by: string; environment_ready: boolean; test_data_ready: boolean; verification_ready: boolean; note: string | null; story_version: number; content_version: number; assessed_at?: string }
export interface Story {
  id: string; title: string; description: string; acceptance_criteria: string[]; business_context: string | null
  dependencies: string[]; language: 'auto' | 'vi' | 'en'; version: number; created_at: string; updated_at: string
}
export interface StoryDependency {
  id: string
  source_story_id: string
  target_story_id: string
  dependency_type: 'precondition' | 'data_fixture' | 'schema_contract' | string
  synced_source_version: number
  target_story_version: number
  binding_contract: {
    consumed_outputs?: string[]
    bound_rules?: string[]
  }
  impact_status: 'synced' | 'suspect_stale' | 'broken' | string
  stale_reason?: {
    summary?: string
    reason?: string
    delta_summary?: string
    upstream_version?: number
    matched_tokens?: string[]
    [key: string]: any
  } | null
  impacted_case_ids: string[]
  created_at: string
  updated_at: string
}

export interface DependencyNode {
  id: string
  title: string
  version: number
  dependency_type: string
  impact_status: string
  synced_source_version: number
  current_source_version: number
  stale_reason?: any
  impacted_case_ids: string[]
}

export interface StoryDependencyTree {
  story_id: string
  story_title: string
  story_version: number
  upstream: DependencyNode[]
  downstream: DependencyNode[]
}

export interface ImpactedCaseDetail {
  case_id: string
  title: string
  reason: string
}

export interface ImpactReportItem {
  dependency_id: string
  source_story_id: string
  source_story_title: string
  target_story_id: string
  target_story_title: string
  synced_source_version: number
  current_source_version: number
  impact_status: string
  stale_reason?: any
  impacted_case_ids: string[]
  impacted_cases: ImpactedCaseDetail[]
}

export interface StoryImpactAnalysisReport {
  story_id: string
  story_title: string
  story_version: number
  has_impacted_dependencies: boolean
  upstream_impacts: ImpactReportItem[]
  downstream_impacts: ImpactReportItem[]
}

export interface MergeConflictItem {
  case_id: string
  title: string
  qa_version: {
    expected_result: string
    steps: any[]
    test_data: string[]
  }
  ai_proposal: {
    expected_result: string
    steps: any[]
    test_data: string[]
  }
  conflict_fields: string[]
}

export interface AsyncJob {
  id: string
  job_type: string
  story_id?: string | null
  status: 'pending' | 'processing' | 'completed' | 'failed'
  progress: number
  result?: {
    story_id?: string
    updated_cases?: string[]
    preserved_cases?: string[]
    conflicts?: MergeConflictItem[]
    synced_dependencies?: string[]
    [key: string]: any
  } | null
  error_message?: string | null
  created_at: string
  updated_at: string
}

export interface Workspace extends Story {
  reviews: Review[]; test_case_sets: TestSet[]; api_specifications: ApiSpecification[]; api_contract_reviews: ApiContractReview[]
  upstream_dependencies?: StoryDependency[]
  downstream_dependencies?: StoryDependency[]
}

// Zero-Gap v2.0 Architecture Types
export type ResolutionStatus = 'covered_automated' | 'healed_by_delta' | 'needs_clarification' | 'accepted_risk' | 'deferred'

export interface AtomicRequirement {
  req_id: string
  clause_text: string
  source_ac: string
}

export interface BVAPartitionItem {
  bva_id: string
  endpoint: string
  field_path: string
  partition_type: string
  test_value: any
  expected_http_status: number
}

export interface ASTBranchNode {
  branch_id: string
  function_name: string
  condition_expression: string
  line_number: number
}

export interface CanonicalTestContract {
  mode: string
  requirements: AtomicRequirement[]
  bva_matrix: BVAPartitionItem[]
  ast_branches: ASTBranchNode[]
  cyclomatic_complexity: number
  spec_conflicts: string[]
}

export interface TestCaseSkeleton {
  test_case_id: string
  title: string
  category: string
  covered_req_ids: string[]
  covered_bva_ids: string[]
  covered_ast_ids: string[]
}

export interface DetailedTestCase extends TestCaseSkeleton {
  priority: string
  preconditions: string[]
  test_steps: string[]
  test_data_payload: Record<string, any>
  expected_http_status: number
  expected_result: string
  resolution_status: ResolutionStatus
}

export interface GapForQA {
  target_id: string
  gap_type: string
  reason: string
  status: ResolutionStatus
}

export interface ZeroGapSuiteResponse {
  effective_coverage_pct: number
  verification_mode: string
  retries_used: number
  test_cases: DetailedTestCase[]
  gaps_for_qa: GapForQA[]
}

export interface CollectionMember {
  id: string
  collection_id: string
  story_id: string
  story_title: string
  story_version: number
  sequence_order: number
  role_in_flow: 'entry_point' | 'intermediate' | 'terminal'
  test_cases_count: number
  test_set_status: string
}

export interface StoryCollection {
  id: string
  name: string
  code: string
  description?: string | null
  collection_type: string
  execution_order: string[]
  health_status: 'synced' | 'suspect_stale' | 'broken'
  metadata_info?: Record<string, any>
  created_at: string
  updated_at: string
  members: CollectionMember[]
  total_stories: number
  total_test_cases: number
}

export interface CollectionDiscoveryResult {
  discovered_collections_count: number
  synced_collections: StoryCollection[]
}


