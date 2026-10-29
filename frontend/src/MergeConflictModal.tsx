import { useState } from 'react'
import {
  AlertCircle,
  ArrowRight,
  CheckCircle2,
  GitMerge,
  ShieldCheck,
  Sparkles,
  UserCheck,
  X,
} from 'lucide-react'
import { api } from './api'
import type { MergeConflictItem } from './types'

interface MergeConflictModalProps {
  storyId: string
  conflicts: MergeConflictItem[]
  onClose: () => void
  onResolved: () => void
}

export function MergeConflictModal({
  storyId,
  conflicts,
  onClose,
  onResolved,
}: MergeConflictModalProps) {
  const [resolvingId, setResolvingId] = useState<string | null>(null)
  const [resolvedMap, setResolvedMap] = useState<Record<string, 'keep_qa' | 'apply_ai'>>({})
  const [error, setError] = useState<string | null>(null)

  async function handleResolve(caseId: string, action: 'keep_qa' | 'apply_ai') {
    setResolvingId(caseId)
    setError(null)
    try {
      await api.resolveConflict(storyId, { case_id: caseId, action })
      setResolvedMap(prev => ({ ...prev, [caseId]: action }))
      onResolved()
    } catch (err: any) {
      setError(err?.message || 'Không thể giải quyết xung đột')
    } finally {
      setResolvingId(null)
    }
  }

  const allResolved = conflicts.every(c => Boolean(resolvedMap[c.case_id]))

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true">
      <div className="conflict-modal-card">
        <div className="conflict-modal-header">
          <div className="header-title-group">
            <div className="conflict-icon-badge">
              <GitMerge size={22} />
            </div>
            <div>
              <h3>Đối Soát & Giải Quyết Xung Đột 3-Way Merge</h3>
              <p>Bảo toàn 100% chỉnh sửa thủ công của QA · Zero Overwrite Guarantee</p>
            </div>
          </div>
          <button className="icon-button close-btn" onClick={onClose} aria-label="Đóng">
            <X size={18} />
          </button>
        </div>

        {error && (
          <div className="conflict-error-banner">
            <AlertCircle size={16} />
            <span>{error}</span>
          </div>
        )}

        <div className="conflict-intro-note">
          <ShieldCheck size={16} className="note-icon" />
          <span>
            Hệ thống phát hiện các Test Case dưới đây đã được QA hiệu đính thủ công trước đó.
            Quy tắc bảo mật không cho phép AI tự động ghi đè. Vui lòng đối chiếu 2 cột và lựa chọn:
          </span>
        </div>

        <div className="conflict-cases-list">
          {conflicts.map(item => {
            const resolvedAction = resolvedMap[item.case_id]
            const isResolving = resolvingId === item.case_id

            return (
              <div key={item.case_id} className={`conflict-case-item ${resolvedAction ? 'is-resolved' : ''}`}>
                <div className="case-item-topbar">
                  <div className="case-id-tag">
                    <strong>{item.case_id}</strong>
                    <span>{item.title}</span>
                  </div>
                  {resolvedAction ? (
                    <span className="badge badge-approved resolved-pill">
                      <CheckCircle2 size={13} />
                      Đã xử lý: {resolvedAction === 'keep_qa' ? 'Giữ bản của QA' : 'Áp dụng đề xuất AI'}
                    </span>
                  ) : (
                    <span className="badge badge-stale pending-pill">
                      Chờ QA quyết định
                    </span>
                  )}
                </div>

                <div className="diff-columns-grid">
                  {/* Left Column: QA Version */}
                  <div className="diff-column qa-column">
                    <div className="column-header qa-hdr">
                      <UserCheck size={15} />
                      <span>BẢN CỦA QA (Đang áp dụng)</span>
                    </div>
                    <div className="diff-content-box">
                      <label>Kỳ vọng thực tế (Expected Result):</label>
                      <div className="code-diff-box qa-text">
                        {item.qa_version.expected_result || '(Chưa nhập kỳ vọng)'}
                      </div>

                      {item.qa_version.test_data && item.qa_version.test_data.length > 0 && (
                        <>
                          <label>Dữ liệu kiểm thử (Test Data):</label>
                          <ul className="diff-list">
                            {item.qa_version.test_data.map((td, idx) => (
                              <li key={idx}><code>{td}</code></li>
                            ))}
                          </ul>
                        </>
                      )}
                    </div>
                    <div className="column-action">
                      <button
                        className={`button ${resolvedAction === 'keep_qa' ? '' : 'button-ghost'} full-width`}
                        disabled={isResolving}
                        onClick={() => handleResolve(item.case_id, 'keep_qa')}
                      >
                        <UserCheck size={14} />
                        {resolvedAction === 'keep_qa' ? '✓ Đang giữ bản QA' : 'Giữ bản của tôi'}
                      </button>
                    </div>
                  </div>

                  {/* Right Column: AI Proposal */}
                  <div className="diff-column ai-column">
                    <div className="column-header ai-hdr">
                      <Sparkles size={15} />
                      <span>ĐỀ XUẤT MỚI CỦA AI (Theo Story cha)</span>
                    </div>
                    <div className="diff-content-box">
                      <label>Kỳ vọng đề xuất:</label>
                      <div className="code-diff-box ai-text">
                        {item.ai_proposal.expected_result || '(Không có thay đổi)'}
                      </div>

                      {item.ai_proposal.test_data && item.ai_proposal.test_data.length > 0 && (
                        <>
                          <label>Dữ liệu kiểm thử mới:</label>
                          <ul className="diff-list">
                            {item.ai_proposal.test_data.map((td, idx) => (
                              <li key={idx}><code>{td}</code></li>
                            ))}
                          </ul>
                        </>
                      )}
                    </div>
                    <div className="column-action">
                      <button
                        className={`button ${resolvedAction === 'apply_ai' ? '' : 'button-ghost'} full-width`}
                        disabled={isResolving}
                        onClick={() => handleResolve(item.case_id, 'apply_ai')}
                      >
                        <Sparkles size={14} />
                        {resolvedAction === 'apply_ai' ? '✓ Đã nhận đề xuất AI' : 'Áp dụng đề xuất AI'}
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            )
          })}
        </div>

        <div className="conflict-modal-footer">
          <span className="footer-status-text">
            {allResolved
              ? '✓ Tất cả các xung đột đã được quyết định an toàn.'
              : `Còn ${conflicts.length - Object.keys(resolvedMap).length} case chờ bạn xác nhận.`}
          </span>
          <button className="button" onClick={onClose}>
            {allResolved ? 'Hoàn tất & Đóng' : 'Đóng đối soát'}
          </button>
        </div>
      </div>
    </div>
  )
}
