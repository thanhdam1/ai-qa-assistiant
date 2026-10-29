import { useEffect, useState } from 'react'
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  FileDiff,
  GitMerge,
  Loader2,
  RefreshCw,
  ShieldAlert,
  Sparkles,
  X,
} from 'lucide-react'
import { api } from './api'
import { MergeConflictModal } from './MergeConflictModal'
import type {
  AsyncJob,
  MergeConflictItem,
  StoryImpactAnalysisReport,
  Workspace,
} from './types'

interface ImpactAlertBannerProps {
  workspace: Workspace
  onRefresh: () => Promise<void>
  onOpenJourneyGraph: () => void
}

export function ImpactAlertBanner({
  workspace,
  onRefresh,
  onOpenJourneyGraph,
}: ImpactAlertBannerProps) {
  const [report, setReport] = useState<StoryImpactAnalysisReport | null>(null)
  const [loadingReport, setLoadingReport] = useState(false)
  const [resyncing, setResyncing] = useState(false)
  const [jobStatus, setJobStatus] = useState<string>('')
  const [conflicts, setConflicts] = useState<MergeConflictItem[]>([])
  const [showConflictModal, setShowConflictModal] = useState(false)
  const [showDiffModal, setShowDiffModal] = useState(false)
  const [bannerDismissed, setBannerDismissed] = useState(false)
  const [successMsg, setSuccessMsg] = useState<string | null>(null)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)

  // Fetch real-time impact analysis
  useEffect(() => {
    let isCurrent = true
    async function loadImpact() {
      setLoadingReport(true)
      try {
        const data = await api.getImpactAnalysis(workspace.id)
        if (isCurrent) {
          setReport(data)
          setBannerDismissed(false)
        }
      } catch (err) {
        console.warn('Failed to load impact report', err)
      } finally {
        if (isCurrent) setLoadingReport(false)
      }
    }
    void loadImpact()
    return () => {
      isCurrent = false
    }
  }, [workspace.id, workspace.version, workspace.updated_at])

  // Check if this story has suspect_stale upstream dependencies
  const upstreamImpacts = report?.upstream_impacts || []
  const hasImpacts =
    report?.has_impacted_dependencies ||
    upstreamImpacts.length > 0 ||
    (workspace.upstream_dependencies || []).some(
      d => d.impact_status === 'suspect_stale'
    )

  if (!hasImpacts || bannerDismissed) {
    return null
  }

  const primaryImpact = upstreamImpacts[0]
  const impactedCaseCount = upstreamImpacts.reduce(
    (acc, cur) => acc + (cur.impacted_case_ids?.length || 0),
    0
  )
  const impactedCaseIds = Array.from(
    new Set(upstreamImpacts.flatMap(u => u.impacted_case_ids || []))
  )

  async function handleStartResync() {
    setResyncing(true)
    setErrorMsg(null)
    setSuccessMsg(null)
    setJobStatus('Đang khởi tạo job chạy nền...')

    try {
      const initResp = await api.reSyncDependencies(workspace.id)
      const jobId = initResp.job_id
      setJobStatus('Đang phân tích đối soát ngữ nghĩa & 3-Way Merge...')

      // Poll job progress every 900ms
      const pollTimer = setInterval(async () => {
        try {
          const job = await api.getJobStatus(jobId)
          if (job.status === 'completed') {
            clearInterval(pollTimer)
            setResyncing(false)
            setJobStatus('')
            const result = job.result || {}
            const conflictList = (result.conflicts || []) as MergeConflictItem[]

            if (conflictList.length > 0) {
              setConflicts(conflictList)
              setShowConflictModal(true)
              setSuccessMsg(
                `Đã đồng bộ xong. Phát hiện ${conflictList.length} test case cần QA đối soát thủ công.`
              )
            } else {
              setSuccessMsg(
                `✓ Đồng bộ thành công! Đã tự động cập nhật ${result.updated_cases?.length || 0} Test Case do AI sinh.`
              )
            }
            await onRefresh()
          } else if (job.status === 'failed') {
            clearInterval(pollTimer)
            setResyncing(false)
            setJobStatus('')
            setErrorMsg(job.error_message || 'Job đồng bộ thất bại')
          } else {
            setJobStatus(`Đang xử lý chạy nền (${job.progress || 30}%)...`)
          }
        } catch (pollErr: any) {
          clearInterval(pollTimer)
          setResyncing(false)
          setErrorMsg(pollErr?.message || 'Lỗi khi tra cứu tiến trình job')
        }
      }, 900)
    } catch (err: any) {
      setResyncing(false)
      setErrorMsg(err?.message || 'Không thể bắt đầu đồng bộ')
    }
  }

  return (
    <>
      <section className="impact-alert-banner" role="alert" aria-live="assertive">
        <div className="banner-left-section">
          <div className="alert-icon-wrap pulse-amber">
            <ShieldAlert size={24} />
          </div>
          <div className="alert-text-body">
            <div className="alert-title-row">
              <strong>CẢNH BÁO TÁC ĐỘNG HỒI QUY (CROSS-STORY REGRESSION IMPACT)</strong>
              <span className="badge badge-stale alert-badge">Suspect Stale</span>
            </div>
            <p className="alert-description">
              Story thượng nguồn{' '}
              <strong>[{primaryImpact ? primaryImpact.source_story_title : 'Upstream Story'}]</strong>{' '}
              đã cập nhật phiên bản{' '}
              <span className="version-pill">
                v{primaryImpact?.synced_source_version || 1} → v{primaryImpact?.current_source_version || 2}
              </span>.
              {impactedCaseIds.length > 0 ? (
                <>
                  {' '}Có <strong>{impactedCaseIds.length} Test Case</strong> (
                  <code>{impactedCaseIds.join(', ')}</code>) bị ảnh hưởng bởi thay đổi quy tắc.
                </>
              ) : (
                ' Hợp đồng dữ liệu có thể bị lệch pha, cần kiểm tra lại kịch bản kiểm thử.'
              )}
            </p>

            {successMsg && (
              <div className="banner-success-note">
                <CheckCircle2 size={14} />
                <span>{successMsg}</span>
              </div>
            )}

            {errorMsg && (
              <div className="banner-error-note">
                <AlertTriangle size={14} />
                <span>{errorMsg}</span>
              </div>
            )}
          </div>
        </div>

        <div className="banner-actions-section">
          {resyncing ? (
            <div className="resync-progress-indicator">
              <Loader2 size={16} className="spin text-amber" />
              <span>{jobStatus}</span>
            </div>
          ) : (
            <div className="banner-btn-group">
              <button
                className="button button-ghost banner-diff-btn"
                onClick={() => setShowDiffModal(true)}
              >
                <FileDiff size={15} />
                Xem Chi Tiết Lệch Pha (Diff)
              </button>
              <button
                className="button banner-resync-btn"
                onClick={handleStartResync}
                title="Khởi tạo Background Job đối soát và chạy 3-Way Merge Engine"
              >
                <RefreshCw size={15} />
                Đồng Bộ Lại (Re-sync)
              </button>
            </div>
          )}
          <button
            className="icon-button dismiss-btn"
            onClick={() => setBannerDismissed(true)}
            aria-label="Ẩn cảnh báo tạm thời"
          >
            <X size={16} />
          </button>
        </div>
      </section>

      {/* Side-by-side Merge Conflict Modal */}
      {showConflictModal && (
        <MergeConflictModal
          storyId={workspace.id}
          conflicts={conflicts}
          onClose={() => setShowConflictModal(false)}
          onResolved={async () => {
            await onRefresh()
          }}
        />
      )}

      {/* Impact Details Modal */}
      {showDiffModal && (
        <div className="modal-backdrop" role="dialog" aria-modal="true">
          <div className="conflict-modal-card diff-modal-card">
            <div className="conflict-modal-header">
              <div className="header-title-group">
                <div className="conflict-icon-badge">
                  <FileDiff size={22} />
                </div>
                <div>
                  <h3>Báo Cáo Phân Tích Lệch Pha & Vi Phạm Hợp Đồng</h3>
                  <p>
                    Đối chiếu Delta giữa Story thượng nguồn và ràng buộc hợp đồng (Binding Contract)
                  </p>
                </div>
              </div>
              <button
                className="icon-button close-btn"
                onClick={() => setShowDiffModal(false)}
                aria-label="Đóng"
              >
                <X size={18} />
              </button>
            </div>

            <div className="impact-details-content">
              {upstreamImpacts.map((imp, idx) => (
                <div key={idx} className="impact-section-box">
                  <div className="impact-source-title">
                    <span className="pill-source">Thượng nguồn: {imp.source_story_title}</span>
                    <span className="pill-version">
                      v{imp.synced_source_version} → v{imp.current_source_version}
                    </span>
                    <span className="badge badge-stale">Nghi ngờ lệch pha</span>
                  </div>

                  {imp.stale_reason && (
                    <div className="stale-reason-box">
                      <strong>Nguyên nhân phát hiện:</strong>
                      <p>{imp.stale_reason.reason || imp.stale_reason.summary || 'Quy tắc nghiệp vụ thay đổi'}</p>
                      {imp.stale_reason.matched_tokens && (
                        <div className="tokens-row">
                          <small>Từ khóa hợp đồng giao thoa:</small>
                          {imp.stale_reason.matched_tokens.map((tk: string, i: number) => (
                            <code key={i}>{tk}</code>
                          ))}
                        </div>
                      )}
                    </div>
                  )}

                  <div className="impacted-cases-breakdown">
                    <h4>Danh sách Test Case bị ảnh hưởng ({imp.impacted_case_ids?.length || 0}):</h4>
                    {imp.impacted_cases && imp.impacted_cases.length > 0 ? (
                      <div className="impacted-cases-grid">
                        {imp.impacted_cases.map(c => (
                          <div key={c.case_id} className="impacted-tc-card">
                            <div className="tc-hdr">
                              <strong>{c.case_id}</strong>
                              <span>{c.title}</span>
                            </div>
                            <p className="tc-reason">{c.reason}</p>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <p className="empty-subtext">
                        {imp.impacted_case_ids?.length > 0
                          ? `Các mã test case: ${imp.impacted_case_ids.join(', ')}`
                          : 'Chưa có test case nào bị ảnh hưởng trực tiếp.'}
                      </p>
                    )}
                  </div>
                </div>
              ))}
            </div>

            <div className="conflict-modal-footer">
              <button
                className="button button-ghost"
                onClick={() => {
                  setShowDiffModal(false)
                  onOpenJourneyGraph()
                }}
              >
                Mở E2E Journey Graph <ArrowRight size={14} />
              </button>
              <button
                className="button"
                onClick={() => {
                  setShowDiffModal(false)
                  void handleStartResync()
                }}
              >
                <RefreshCw size={14} />
                Đồng Bộ Lại Kịch Bản Ngay
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
