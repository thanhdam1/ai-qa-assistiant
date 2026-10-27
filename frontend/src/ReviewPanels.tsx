import { useState } from 'react'
import { AlertTriangle, BookOpen, Check, CheckCircle2, Download, FilePlus2, FlaskConical, LoaderCircle, Pencil, Plus, RefreshCw, Save, ShieldCheck, Sparkles } from 'lucide-react'
import { api } from './api'
import type { ApiContractReview, ApiContractReviewContent, ApiSpecification, Review, ReviewContent, ReviewItem, Story } from './types'

export type StoryDraft = {
  title: string; description: string; acceptance_criteria: string[]; business_context: string
  dependencies: string[]; language: 'auto' | 'vi' | 'en'
}
const emptyStory: StoryDraft = { title: '', description: '', acceptance_criteria: [], business_context: '', dependencies: [], language: 'auto' }
const sectionLabels: [keyof ReviewContent, string][] = [
  ['missing_acceptance_criteria', 'Acceptance criteria còn thiếu'], ['ambiguities_and_conflicts', 'Điểm chưa rõ & mâu thuẫn'],
  ['stakeholder_questions', 'Câu hỏi cho PO / BA'], ['edge_cases', 'Edge cases'], ['assumptions', 'Giả định'], ['risks', 'Rủi ro'],
]

interface StoryTemplate {
  id: string
  name: string
  tag: string
  title: string
  description: string
  acceptance_criteria: string[]
  business_context: string
  dependencies: string[]
}

const STORY_TEMPLATES: StoryTemplate[] = [
  {
    id: 'payment',
    name: 'Chuyển tiền & Thanh toán',
    tag: 'Giao dịch',
    title: 'Chuyển tiền nhanh nội bộ giữa hai tài khoản thanh toán',
    description: 'As a khách hàng cá nhân đã xác thực danh tính (KYC),\nI want chuyển tiền nhanh tới tài khoản người nhận trong cùng hệ thống,\nSo that người nhận nhận được tiền ngay lập tức mà không phải chờ đợi.',
    acceptance_criteria: [
      'AC1 (Kịch bản thành công): Khi số dư khả dụng >= số tiền chuyển + phí và mã OTP hợp lệ, giao dịch thành công. Số dư người chuyển giảm và người nhận tăng ngay lập tức.',
      'AC2 (Validation số dư): Khi số dư khả dụng < số tiền chuyển + phí, hệ thống từ chối với mã lỗi "INSUFFICIENT_BALANCE", thông báo "Số dư khả dụng không đủ để thực hiện giao dịch" và giữ nguyên số dư.',
      'AC3 (Ràng buộc hạn mức & Biên): Số tiền chuyển tối thiểu là 10,000 VND và tối đa 50,000,000 VND/giao dịch. Nếu nhập ngoài khoảng này, hệ thống báo lỗi hạn mức tương ứng trước khi cho phép xác nhận.',
      'AC4 (Chống trùng lặp / Idempotency): Khi gửi yêu cầu với Idempotency-Key đã tồn tại trong vòng 5 phút, hệ thống không tạo giao dịch mới mà trả về kết quả của giao dịch ban đầu.',
      'AC5 (Side effects & Thông báo): Sau khi giao dịch thành công, hệ thống gửi thông báo biến động số dư qua SMS/Email cho cả hai bên và lưu vết audit log.'
    ],
    business_context: '- Phí chuyển tiền: 0 VND cho gói tài khoản chuẩn.\n- Trạng thái tài khoản: Cả tài khoản nguồn và đích phải ở trạng thái ACTIVE (không bị phong toả hoặc khoá một chiều).\n- Hạn mức ngày: Tối đa 200,000,000 VND/ngày/khách hàng.\n- Dữ liệu thử nghiệm: Tài khoản nguồn 1010001 (số dư 5,000,000 VND), Tài khoản đích 1010002.',
    dependencies: ['Core Banking Account Service', 'Notification Service (SMS/Email)', 'OTP Verification Engine', 'Audit Log Service']
  },
  {
    id: 'auth',
    name: 'Đăng nhập & Xác thực',
    tag: 'Bảo mật',
    title: 'Đăng nhập bằng Email và Mật khẩu có bảo vệ Brute-force',
    description: 'As a người dùng đã có tài khoản trên hệ thống,\nI want đăng nhập bằng email và mật khẩu của mình,\nSo that tôi có thể truy cập an toàn vào không gian làm việc và dữ liệu cá nhân.',
    acceptance_criteria: [
      'AC1 (Kịch bản thành công): Khi nhập đúng email đã đăng ký và mật khẩu chính xác, hệ thống đăng nhập thành công, cấp cặp Access Token (hạn 15 phút) và Refresh Token (hạn 7 ngày).',
      'AC2 (Validation thông tin sai): Khi nhập sai email hoặc mật khẩu, hệ thống hiển thị thông báo lỗi chung "Email hoặc mật khẩu không chính xác" (không tiết lộ email có tồn tại hay không) và không cấp token.',
      'AC3 (Chống brute-force / Khoá tạm thời): Khi đăng nhập thất bại 5 lần liên tiếp trong 15 phút từ cùng một IP/tài khoản, tạm khoá đăng nhập 30 phút và trả về mã lỗi 429 "ACCOUNT_TEMPORARILY_LOCKED".',
      'AC4 (Định dạng & Ràng buộc biên): Email phải đúng định dạng chuẩn RFC 5322; Mật khẩu cho phép từ 8 đến 64 ký tự, trường mật khẩu không được phép để trống.',
      'AC5 (Phân quyền Role): Sau khi đăng nhập, hệ thống trả về thông tin user profile gồm vai trò (Role: ADMIN / QA / VIEWER) để phân quyền màn hình hiển thị tương ứng.'
    ],
    business_context: '- Mật khẩu được hash bằng bcrypt (cost factor >= 12).\n- Token lưu an toàn qua HttpOnly Cookie hoặc Authorization Bearer header.\n- Dữ liệu thử nghiệm: user_active@example.com (pass: ValidPass@123), user_locked@example.com.',
    dependencies: ['Identity & User Database', 'Redis Session Cache', 'Rate Limiter Service']
  },
  {
    id: 'crud',
    name: 'Tạo mới & Validate biểu mẫu',
    tag: 'CRUD Form',
    title: 'Tạo mới hồ sơ khách hàng doanh nghiệp',
    description: 'As a chuyên viên quan hệ khách hàng (RM),\nI want nhập và tạo mới hồ sơ thông tin doanh nghiệp vào hệ thống,\nSo that doanh nghiệp có thể được thẩm định mở tài khoản thanh toán.',
    acceptance_criteria: [
      'AC1 (Kịch bản thành công): Khi điền đầy đủ và hợp lệ các trường bắt buộc (Mã số thuế, Tên doanh nghiệp, Người đại diện, Số điện thoại, Email), hồ sơ được lưu thành công ở trạng thái "PENDING_REVIEW".',
      'AC2 (Kiểm tra trùng lặp - Duplicate Check): Khi Mã số thuế đã tồn tại trên hệ thống, từ chối tạo mới với mã 409 Conflict và thông báo "Mã số thuế này đã được đăng ký".',
      'AC3 (Validation định dạng & Biên): Mã số thuế bắt buộc đúng 10 hoặc 13 chữ số; Số điện thoại phải đúng định dạng 10 chữ số của các nhà mạng Việt Nam; Email phải đúng định dạng.',
      'AC4 (Thiếu trường bắt buộc): Khi thiếu bất kỳ trường bắt buộc nào, hệ thống đánh dấu đỏ trường tương ứng và hiển thị thông báo lỗi cụ thể dưới từng ô nhập liệu.',
      'AC5 (Phân quyền): Chỉ người dùng có vai trò "RELATIONSHIP_MANAGER" hoặc "ADMIN" mới được phép tạo hồ sơ. Các vai trò khác bị từ chối với mã lỗi 403 Forbidden.'
    ],
    business_context: '- Kiểm tra chéo thông tin mã số thuế với Cổng đăng ký doanh nghiệp quốc gia (nếu service online).\n- Tên doanh nghiệp tự động viết hoa toàn bộ và chuẩn hoá khoảng trắng trước khi lưu.\n- Ghi log audit: User ID, thời gian tạo, địa chỉ IP.',
    dependencies: ['Enterprise Customer Service DB', 'National Business Registry Mock API', 'Audit Log Service']
  },
  {
    id: 'search',
    name: 'Tìm kiếm, Lọc & Phân trang',
    tag: 'Tìm kiếm',
    title: 'Tìm kiếm và lọc danh sách đơn hàng',
    description: 'As a nhân viên chăm sóc khách hàng (CSKH),\nI want tìm kiếm đơn hàng theo từ khoá và lọc theo trạng thái, khoảng ngày,\nSo that tôi có thể nhanh chóng tra cứu tiến độ đơn hàng và hỗ trợ khách hàng kịp thời.',
    acceptance_criteria: [
      'AC1 (Kịch bản thành công): Khi tìm kiếm theo Mã đơn hàng, Tên khách hàng hoặc Số điện thoại, hệ thống trả về danh sách các đơn hàng khớp với từ khoá.',
      'AC2 (Không có kết quả): Khi không có bản ghi nào khớp với điều kiện tìm kiếm hoặc bộ lọc, hệ thống hiển thị màn hình trống với thông báo "Không tìm thấy đơn hàng nào phù hợp".',
      'AC3 (Bộ lọc kết hợp): Cho phép lọc đồng thời theo nhiều trạng thái (NEW, PROCESSING, COMPLETED, CANCELLED) và khoảng ngày tạo (Từ ngày - Đến ngày).',
      'AC4 (Phân trang & Giới hạn): Mặc định hiển thị 20 kết quả/trang; hỗ trợ chọn hiển thị 50 hoặc 100 kết quả; hiển thị tổng số kết quả tìm được và nút chuyển trang.',
      'AC5 (Hiệu năng & Tiếng Việt): Hỗ trợ tìm kiếm tiếng Việt không phân biệt hoa/thường và có dấu hoặc không dấu; thời gian phản hồi không quá 1000ms.'
    ],
    business_context: '- Dữ liệu tìm kiếm được đánh index trên các cột order_code, phone_number, customer_name.\n- Khoảng ngày tìm kiếm mặc định là 30 ngày gần nhất nếu người dùng không chọn ngày.',
    dependencies: ['Order Database / Elasticsearch', 'Customer Support Dashboard']
  },
  {
    id: 'bdd',
    name: 'Khung chuẩn BDD (Given-When-Then)',
    tag: 'Khung mẫu',
    title: '[Tính năng] Mô tả ngắn gọn tính năng',
    description: 'As a [vai trò người dùng],\nI want [hành động mong muốn thực hiện],\nSo that [mục tiêu hoặc lợi ích nghiệp vụ đạt được].',
    acceptance_criteria: [
      'AC1 (Kịch bản thành công): Given [tiền đề hợp lệ] When [người dùng thực hiện hành động] Then [hệ thống xử lý thành công và cập nhật kết quả cụ thể].',
      'AC2 (Validation lỗi): When [nhập sai hoặc thiếu trường dữ liệu X] Then hệ thống báo lỗi [mã lỗi / thông báo cụ thể] và giữ nguyên dữ liệu ban đầu.',
      'AC3 (Ràng buộc biên & Giới hạn): Khi [giá trị đạt ngưỡng min/max hoặc độ dài N ký tự] Then hệ thống [chấp nhận/từ chối] với thông báo [thông báo cụ thể].',
      'AC4 (Bảo mật / Phân quyền): Khi [người dùng chưa đăng nhập hoặc không có quyền role X] Then hệ thống chặn truy cập với mã lỗi 401/403.'
    ],
    business_context: '- Quy tắc tính toán / Công thức nghiệp vụ: [Mô tả chi tiết công thức hoặc bảng giá]\n- Dữ liệu tiền đề (Preconditions): [Tài khoản / Môi trường / Trạng thái ban đầu]\n- Dữ liệu thử nghiệm (Test Data): [Mẫu tài khoản test và số liệu cụ thể]',
    dependencies: ['Database Service', 'Authentication Service']
  }
]

const AC_SNIPPETS = [
  { label: '+ Thành công (Happy path)', text: 'AC: Given [tiền đề hợp lệ] When [thực hiện hành động] Then [kết quả mong đợi cụ thể]' },
  { label: '+ Báo lỗi / Validation', text: 'AC: When [nhập sai/thiếu trường X] Then hệ thống báo lỗi [mã lỗi/thông báo] và giữ nguyên dữ liệu' },
  { label: '+ Biên & Giới hạn', text: 'AC: Khi [giá trị đạt min/max hoặc độ dài N] thì hệ thống [chấp nhận/từ chối] với thông báo [cụ thể]' },
  { label: '+ Quyền & Bảo mật', text: 'AC: Khi [người dùng chưa đăng nhập hoặc không có quyền] Then hệ thống chặn với mã 401/403' },
  { label: '+ Tác vụ ngầm (Side effects)', text: 'AC: Sau khi hoàn tất thành công Then hệ thống [gửi email xác nhận] và [lưu audit log]' },
]

const BUSINESS_RULES_SCAFFOLD = `- Quy tắc tính toán / Công thức nghiệp vụ: [Mô tả chi tiết công thức, phí, tỉ lệ]
- Dữ liệu tiền đề (Preconditions): [Trạng thái tài khoản, vai trò hoặc cấu hình bắt buộc]
- Dữ liệu thử nghiệm mẫu (Test data): [Tài khoản mẫu, dữ liệu test cụ thể]
- Ràng buộc môi trường: [Hệ thống chạy trên môi trường staging, mock dịch vụ bên ngoài]`

export function StatusBadge({ status, stale }: { status: string; stale: boolean }) {
  if (stale) return <span className="badge badge-stale">Stale</span>
  return <span className={`badge badge-${status}`}>{status === 'approved' ? 'Đã duyệt' : 'Bản nháp'}</span>
}

export function Button({ children, busy, variant = 'primary', ...props }: React.ButtonHTMLAttributes<HTMLButtonElement> & { busy?: boolean; variant?: string }) {
  return <button className={`button button-${variant}`} disabled={busy || props.disabled} {...props}>{busy ? <LoaderCircle className="spin" size={17} /> : children}</button>
}

export function Notice({ error, clear }: { error: string; clear: () => void }) {
  return <div className="notice"><AlertTriangle size={18} /><span>{error}</span><button onClick={clear}>×</button></div>
}

export function StoryForm({ initial, onSave, onCancel, busy }: { initial?: Story; onSave: (data: StoryDraft) => Promise<void>; onCancel: () => void; busy: boolean }) {
  const [form, setForm] = useState(() => initial ? { title: initial.title, description: initial.description, acceptance_criteria: initial.acceptance_criteria, business_context: initial.business_context ?? '', dependencies: initial.dependencies, language: initial.language } : emptyStory)
  const [criteria, setCriteria] = useState(form.acceptance_criteria.join('\n'))
  const [dependencies, setDependencies] = useState(form.dependencies.join('\n'))

  function applyTemplate(tpl: StoryTemplate) {
    setForm({
      title: tpl.title,
      description: tpl.description,
      acceptance_criteria: tpl.acceptance_criteria,
      business_context: tpl.business_context,
      dependencies: tpl.dependencies,
      language: form.language,
    })
    setCriteria(tpl.acceptance_criteria.join('\n'))
    setDependencies(tpl.dependencies.join('\n'))
  }

  function appendAcSnippet(text: string) {
    const nextCriteria = criteria.trim() ? `${criteria.trim()}\n${text}` : text
    setCriteria(nextCriteria)
  }

  function appendBusinessScaffold() {
    const nextContext = form.business_context.trim() ? `${form.business_context.trim()}\n\n${BUSINESS_RULES_SCAFFOLD}` : BUSINESS_RULES_SCAFFOLD
    setForm({ ...form, business_context: nextContext })
  }

  // Requirement Quality Assessment
  const criteriaList = criteria.split('\n').map(x => x.trim()).filter(Boolean)
  const checks = [
    { label: 'Tiêu đề rõ ràng (> 5 ký tự)', passed: form.title.trim().length >= 6 },
    { label: 'Mô tả mục tiêu nghiệp vụ (User Story)', passed: form.description.trim().length >= 25 },
    { label: `Có ít nhất 2 Acceptance Criteria (${criteriaList.length}/2)`, passed: criteriaList.length >= 2 },
    { label: 'Có kịch bản lỗi / validation hoặc giới hạn biên', passed: criteriaList.some(ac => /lỗi|error|từ chối|fail|chặn|hạn mức|tối đa|tối thiểu|min|max|không hợp lệ|invalid|401|403|404|422|500/i.test(ac)) },
    { label: 'Có Quy tắc nghiệp vụ (Business context & rules)', passed: form.business_context.trim().length >= 15 },
  ]
  const passedCount = checks.filter(c => c.passed).length
  const qualityLevel = passedCount >= 4 ? 'high' : passedCount === 3 ? 'medium' : 'low'
  const qualityText = passedCount >= 4
    ? `Rất chi tiết (${passedCount}/5) — Tối ưu cho AI sinh test 100% không gap`
    : passedCount === 3
    ? `Độ chi tiết khá (${passedCount}/5) — Nên bổ sung thêm kịch bản lỗi / biên`
    : `Cần thêm chi tiết (${passedCount}/5) — Dễ phát sinh Coverage Gap`

  return <div className="card form-card">
    <div className="card-heading">
      <div>
        <span className="eyebrow">User story & Requirement Builder</span>
        <h2>{initial ? 'Cập nhật story' : 'Tạo story mới với Requirement chi tiết'}</h2>
      </div>
    </div>

    {/* Section 1: Template Selection */}
    <div className="story-form-templates">
      <div className="template-header">
        <h4><BookOpen size={16} /> Mẫu yêu cầu chi tiết (Chọn nhanh để xem cấu trúc chuẩn)</h4>
        <small>Tự động điền đầy đủ Happy path, Validation, Biên & Ràng buộc</small>
      </div>
      <div className="template-pills">
        {STORY_TEMPLATES.map(tpl => (
          <button
            type="button"
            key={tpl.id}
            className="template-pill"
            onClick={() => applyTemplate(tpl)}
            title={`Áp dụng mẫu: ${tpl.name}`}
          >
            <Sparkles size={13} />
            <span>{tpl.name}</span>
            <span className="template-tag">{tpl.tag}</span>
          </button>
        ))}
      </div>
    </div>

    {/* Section 2: Requirement Quality Assessment Meter */}
    <div className="quality-meter-card">
      <div className="quality-meter-header">
        <strong><ShieldCheck size={17} /> Đánh giá độ chi tiết của Requirement</strong>
        <span className={`quality-score-badge ${qualityLevel}`}>
          {qualityLevel === 'high' ? <CheckCircle2 size={13} /> : <AlertTriangle size={13} />}
          {qualityText}
        </span>
      </div>
      <div className="quality-checklist">
        {checks.map((chk, idx) => (
          <div key={idx} className={`quality-check-item ${chk.passed ? 'done' : ''}`}>
            {chk.passed ? <CheckCircle2 size={14} /> : <AlertTriangle size={14} />}
            <span>{chk.label}</span>
          </div>
        ))}
      </div>
      <div className="quality-tip-text">
        💡 <b>Mẹo QA</b>: Viết rõ kết quả mong đợi (Given-When-Then), mã lỗi và hạn mức giúp AI sinh 100% test case có Assertion Evidence, loại bỏ hoàn toàn các cảnh báo Coverage Gap.
      </div>
    </div>

    {/* Section 3: Title & Description */}
    <label>
      <div className="field-header-row">
        <span>Tiêu đề story <small className="muted">(Tóm tắt tính năng)</small></span>
        <span className="field-counter">{form.title.length}/240</span>
      </div>
      <input
        value={form.title}
        maxLength={240}
        required
        onChange={e => setForm({ ...form, title: e.target.value })}
        placeholder="Ví dụ: Chuyển tiền nhanh nội bộ giữa hai tài khoản thanh toán"
      />
    </label>

    <label>
      <div className="field-header-row">
        <span>Mô tả User Story <small className="muted">(Định dạng: As a… I want… So that…)</small></span>
        <span className="field-counter">{form.description.length}/30000</span>
      </div>
      <textarea
        value={form.description}
        required
        rows={6}
        onChange={e => setForm({ ...form, description: e.target.value })}
        placeholder="As a [vai trò người dùng]&#10;I want [hành động mong muốn thực hiện]&#10;So that [lợi ích hoặc mục tiêu đạt được]"
      />
    </label>

    {/* Section 4: Acceptance Criteria with Quick Inserters */}
    <div className="form-grid">
      <div>
        <label>
          <div className="field-header-row">
            <span>Acceptance criteria hiện có</span>
            <span className="field-counter">{criteriaList.length} tiêu chí</span>
          </div>
          <div className="ac-builder-bar">
            <span className="ac-builder-label">Chèn mẫu:</span>
            {AC_SNIPPETS.map((snip, idx) => (
              <button
                type="button"
                key={idx}
                className="ac-snippet-pill"
                onClick={() => appendAcSnippet(snip.text)}
                title="Bấm để chèn tiêu chí này vào danh sách"
              >
                <Plus size={11} /> {snip.label}
              </button>
            ))}
          </div>
          <textarea
            rows={7}
            value={criteria}
            onChange={e => setCriteria(e.target.value)}
            placeholder="Mỗi dòng là một tiêu chí (AC)&#10;Ví dụ: AC1 (Happy path): Given... When... Then...&#10;AC2 (Validation lỗi): When... Then..."
          />
        </label>
      </div>

      <div>
        <label>
          <div className="field-header-row">
            <span>Business context & Quy tắc nghiệp vụ</span>
            <button
              type="button"
              className="scaffold-btn"
              onClick={appendBusinessScaffold}
              title="Chèn khung quy tắc nghiệp vụ chuẩn"
            >
              <Plus size={12} /> Chèn khung quy tắc
            </button>
          </div>
          <textarea
            rows={9}
            value={form.business_context}
            onChange={e => setForm({ ...form, business_context: e.target.value })}
            placeholder="- Công thức / Quy tắc tính phí, hạn mức&#10;- Trạng thái tiền đề (Preconditions)&#10;- Tài khoản test & Dữ liệu mẫu (Test data)"
          />
        </label>
      </div>

      <label>
        <div className="field-header-row">
          <span>Dependencies & Dịch vụ liên quan</span>
          <span className="field-counter">{dependencies.split('\n').filter(Boolean).length} mục</span>
        </div>
        <textarea
          rows={4}
          value={dependencies}
          onChange={e => setDependencies(e.target.value)}
          placeholder="Mỗi dòng là một dependency (Core Banking, SMS Service, Auth DB...)"
        />
      </label>

      <label>
        <div className="field-header-row">
          <span>Ngôn ngữ tài liệu</span>
        </div>
        <select
          value={form.language}
          onChange={e => setForm({ ...form, language: e.target.value as 'auto' | 'vi' | 'en' })}
        >
          <option value="auto">Tự nhận diện theo nội dung</option>
          <option value="vi">Tiếng Việt</option>
          <option value="en">English</option>
        </select>
      </label>
    </div>

    {/* Section 5: Form Actions */}
    <div className="actions">
      <Button variant="ghost" onClick={onCancel}>Huỷ</Button>
      <Button
        busy={busy}
        disabled={!form.title.trim() || !form.description.trim()}
        onClick={() => onSave({
          ...form,
          acceptance_criteria: criteria.split('\n').map(x => x.trim()).filter(Boolean),
          dependencies: dependencies.split('\n').map(x => x.trim()).filter(Boolean),
        })}
      >
        <Save size={17} /> Lưu story & Requirement
      </Button>
    </div>
  </div>
}

function FindingList({ title, items }: { title: string; items: ReviewItem[] }) {
  return <section className="finding-section"><div className="section-title"><h3>{title}</h3><span>{items.length}</span></div>{items.length === 0 ? <p className="empty">Không có phát hiện.</p> : <div className="finding-grid">{items.map(item => <article className="finding" key={item.id}><div><span className={`severity severity-${item.severity}`}>{item.severity}</span><code>{item.id}</code><span className={`classification classification-${item.classification}`}>{item.classification === 'requirement' ? 'Requirement' : item.classification === 'recommendation' ? 'Đề xuất AI' : 'Cần xác nhận'}</span></div><h4>{item.title}</h4><p>{item.detail}</p><small>Nguồn: {item.source_reference}</small></article>)}</div>}</section>
}

function JsonEditor<T>({ value, onSave, onCancel, busy }: { value: T; onSave: (value: T) => Promise<void>; onCancel: () => void; busy: boolean }) {
  const [text, setText] = useState(JSON.stringify(value, null, 2)); const [error, setError] = useState('')
  return <div className="json-editor"><p>Chỉnh sửa dữ liệu có cấu trúc. API sẽ kiểm tra schema trước khi lưu.</p><textarea value={text} rows={26} spellCheck={false} onChange={e => setText(e.target.value)} />{error && <small className="field-error">{error}</small>}<div className="actions"><Button variant="ghost" onClick={onCancel}>Huỷ</Button><Button busy={busy} onClick={async () => { try { await onSave(JSON.parse(text) as T) } catch (e) { setError(e instanceof SyntaxError ? 'JSON không hợp lệ.' : String(e)) } }}><Save size={17} /> Lưu thay đổi</Button></div></div>
}

export function ReviewPanel({ review, sourceCriteria, onApprove, onSave, onGenerateTests, onRegenerate, apiReviewId, requiresApiReview, busy }: { review: Review; sourceCriteria: string[]; onApprove: () => Promise<void>; onSave: (c: ReviewContent) => Promise<void>; onGenerateTests: () => Promise<void>; onRegenerate: () => Promise<void>; apiReviewId?: string; requiresApiReview: boolean; busy: string }) {
  const [editing, setEditing] = useState(false)
  return <div className="card"><div className="card-heading"><div><span className="eyebrow">Requirement review · v{review.story_version}</span><h2>Phân tích yêu cầu</h2></div><StatusBadge status={review.status} stale={review.stale} /></div>
    {editing ? <JsonEditor value={review.content} busy={busy === 'save-review'} onCancel={() => setEditing(false)} onSave={async c => { await onSave(c); setEditing(false) }} /> : <>
      <div className="summary"><Sparkles size={20} /><div><strong>Tóm tắt nghiệp vụ</strong><p>{review.content.business_summary}</p></div></div>
      <p className="human-review-note">AC hiện có là requirement từ story. Các AC còn thiếu chỉ là recommendation của AI; mục <b>needs_clarification</b> cần PO/BA xác nhận trước khi coi là quy tắc nghiệp vụ.</p>
      {new Set(review.content.existing_acceptance_criteria.filter(item => item.source_id?.startsWith('SRC-AC-')).map(item => item.source_id)).size < sourceCriteria.length && <p className="notice">AI chưa trích đủ acceptance criteria gốc. QA cần bổ sung các mục còn thiếu trước khi phê duyệt.</p>}
      {apiReviewId && <p className="coverage">Bộ test tiếp theo sẽ kết hợp API Contract Review đã duyệt.</p>}
      {requiresApiReview && !apiReviewId && <p className="notice">Duyệt API Contract Review hiện tại trước khi sinh test cho story này.</p>}
      <section className="finding-section"><div className="section-title"><h3>Acceptance criteria hiện có</h3><span>{review.content.existing_acceptance_criteria.length}</span></div><div className="criteria-list">{review.content.existing_acceptance_criteria.map(x => <div key={x.id}><code>{x.id}</code><span>{x.criterion}</span><small>{(x.obligations ?? []).map(item => item.text).join(' · ')}</small></div>)}</div></section>
      {sectionLabels.map(([key, label]) => <FindingList key={key} title={label} items={review.content[key] as ReviewItem[]} />)}
      <div className="actions split"><div><a className="button button-ghost" href={api.exportUrl('requirement-reviews', review.id, 'json')}><Download size={16} /> JSON</a><a className="button button-ghost" href={api.exportUrl('requirement-reviews', review.id, 'csv')}><Download size={16} /> CSV</a></div><div>{review.stale ? <Button busy={busy === 'generate-review'} onClick={onRegenerate}><RefreshCw size={16} /> Phân tích version hiện tại</Button> : <><Button variant="ghost" onClick={() => setEditing(true)}><Pencil size={16} /> Chỉnh sửa</Button>{review.status !== 'approved' && <Button busy={busy === 'approve-review'} onClick={onApprove}><Check size={17} /> Phê duyệt</Button>}{review.status === 'approved' && <Button busy={busy === 'generate-tests'} disabled={requiresApiReview && !apiReviewId} onClick={onGenerateTests}><FlaskConical size={17} /> Sinh test case</Button>}</>}</div></div>
    </>}
  </div>
}

export function ApiContractPanel({ specs, reviews, onUpload, onGenerate, onSave, onApprove, busy }: {
  specs: ApiSpecification[]; reviews: ApiContractReview[]
  onUpload: (file: File) => Promise<void>; onGenerate: (specId: string) => Promise<void>
  onSave: (reviewId: string, content: ApiContractReviewContent) => Promise<void>
  onApprove: (reviewId: string) => Promise<void>; busy: string
}) {
  const [file, setFile] = useState<File | null>(null)
  const [editing, setEditing] = useState(false)
  const currentSpec = specs.find(spec => !spec.stale) ?? specs[0]
  const review = currentSpec && reviews.find(item => item.specification_id === currentSpec.id)
  return <div className="card api-contract-panel">
    <div className="card-heading"><div><span className="eyebrow">API Contract Agent · {review?.model_name ?? 'AI provider'}</span><h2>OpenAPI contract</h2></div>{currentSpec && <StatusBadge status={review?.status ?? 'draft'} stale={currentSpec.stale || !!review?.stale} />}</div>
    <p className="coverage">Tải OpenAPI 3.x JSON/YAML để phân tích endpoint, request, response và schema. QA cần duyệt contract review trước khi dùng để sinh test.</p>
    <div className="api-upload"><input type="file" accept=".json,.yaml,.yml,application/json,text/yaml" onChange={event => setFile(event.target.files?.[0] ?? null)} /><Button busy={busy === 'upload-api'} disabled={!file} onClick={async () => { if (file) { await onUpload(file); setFile(null) } }}><FilePlus2 size={16} /> Tải OpenAPI</Button><small>JSON/YAML · tối đa 1 MB · chỉ hỗ trợ $ref nội bộ</small></div>
    {specs.filter(spec => spec.stale).length > 0 && <details className="api-history"><summary>Spec cũ ({specs.filter(spec => spec.stale).length})</summary>{specs.filter(spec => spec.stale).map(spec => <p key={spec.id}>{spec.title} · v{spec.version} · stale</p>)}</details>}
    {!currentSpec ? <p className="empty">Chưa có OpenAPI spec gắn với story này.</p> : <>
      <div className="api-spec-meta"><div><strong>{currentSpec.title}</strong><small>{currentSpec.file_name} · OpenAPI {currentSpec.openapi_version} · v{currentSpec.version}</small></div><span>{currentSpec.operations.length} operations</span></div>
      {!review || review.stale ? <div className="actions"><Button busy={busy === 'generate-api-review'} disabled={currentSpec.stale} onClick={() => onGenerate(currentSpec.id)}><Sparkles size={16} /> {review ? 'Phân tích lại API Contract' : 'Chạy API Contract Agent'}</Button></div> : editing ? <JsonEditor value={review.content} busy={busy === 'save-api-review'} onCancel={() => setEditing(false)} onSave={async content => { await onSave(review.id, content); setEditing(false) }} /> : <>
        <div className="summary"><Sparkles size={20} /><div><strong>Phân tích contract</strong><p>{review.content.summary}</p></div></div>
        <div className="api-operations"><div className="section-title"><h3>Operations</h3><span>{review.content.operations.length}</span></div>{review.content.operations.map(operation => <div key={operation.operation_id}><code>{operation.method}</code><b>{operation.path}</b><small>{operation.summary || operation.operation_id}</small></div>)}</div>
        <div className="api-findings"><div className="section-title"><h3>Checks và điểm cần làm rõ</h3><span>{review.content.findings.length}</span></div>{review.content.findings.length === 0 ? <p className="empty">Không có phát hiện.</p> : review.content.findings.map(finding => <article className="finding" key={finding.id}><div><span className={`type type-${finding.type === 'schema' || finding.type === 'security' ? 'boundary' : finding.type === 'conflict' ? 'gap' : finding.type}`}>{finding.type}</span><span className={`severity severity-${finding.severity}`}>{finding.severity}</span><code>{finding.id}</code></div><h4>{finding.method} {finding.path} · {finding.title}</h4><p>{finding.detail}</p><small>Nguồn OpenAPI: {finding.source_reference}{finding.story_reference && ` · Story: ${finding.story_reference}`} · {finding.classification}</small>{finding.expected_status_codes.length > 0 && <p>Status theo spec: {finding.expected_status_codes.join(', ')}</p>}</article>)}</div>
        <div className="actions split"><div><a className="button button-ghost" href={api.exportUrl('api-contract-reviews', review.id, 'json')}><Download size={16} /> JSON</a><a className="button button-ghost" href={api.exportUrl('api-contract-reviews', review.id, 'csv')}><Download size={16} /> CSV</a></div><div><Button variant="ghost" disabled={review.stale} onClick={() => setEditing(true)}><Pencil size={16} /> Chỉnh sửa</Button>{review.status !== 'approved' && <Button busy={busy === 'approve-api-review'} disabled={review.stale} onClick={() => onApprove(review.id)}><Check size={17} /> Duyệt API review</Button>}</div></div>
      </>}
    </>}
  </div>
}
