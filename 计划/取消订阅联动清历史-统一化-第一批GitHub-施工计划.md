# 施工说明 V2.1：GitHub 取消星标联动清历史（安全第一批）

> 本文替换此前“只加白名单”的版本。原方案的当前数据盘点正确，但把可改名的
> owner/repo 当作稳定身份，且会让一次不完整的星标快照在同一轮采集中误删历史。
>
> V2.1 根据 2026-07-20 复核补齐：Actions Variable 合法命名、本轮运行新鲜度、两个状态文件
> 的一致提交、repo ID 规范类型、空快照熔断、摘要失效重审、CLAUDE.md 窄例外和原子审计写入。
>
> 项目根目录：E:\AI-news-reader\ai-news-radar-run。
>
> 本任务会影响线上归档删除，风险等级为高。未获用户明确授权前：
> **不建分支、不提交、不推送、不触发 Actions、不修改 Actions Variables。**

---

## 0. 任务卡

| 项目 | 结论 |
|---|---|
| 任务类型 | 已有项目的大功能 / 数据清理逻辑 |
| 本轮目标 | GitHub 取消星标后安全清除对应历史，不误伤仍订阅或改名的仓库 |
| 核心身份 | github_repo_identity / managed_repo_id，不是 owner/repo 展示名 |
| 上线策略 | off -> audit -> on，默认 off |
| 关键护栏 | 连续两次非空完整快照、本轮 Actions 身份绑定、状态文件哈希配对、审批摘要、全站 GitHub 身份覆盖率 |
| Git 策略 | 用户确认后创建 feature/unsubscribe-purge-github 或独立 worktree |

---

## 1. 施工前必须确认的产品决策

正式写代码前，用户必须确认以下安全默认；任何一项不同，都要先改计划，不能直接施工。

1. **自动取消星标不是同一轮马上删历史。**
   第一次完整快照缺少仓库时只记为“待确认”；第二次连续完整快照仍缺少时，才允许把受管仓库标为
   auto_disabled。历史清理仍需后续 audit 和用户批准的 on，这是为了防 GitHub 接口偶发漏回一个 star。

2. **本批只自动清理 GitHub 星标托管源。**
   条件是 managed_by=github_stars、managed_state=auto_disabled、稳定数字 managed_repo_id 已连续确认。
   手动 GitHub 源的 enabled:false 仅表示暂停，本批不自动删除其旧历史；用户要删时走现有“删除信源”的明确确认流程。

3. **首次真实候选不再硬编码为 43 条。**
   当前数据盘点为 GitHub 归档 190 条，两个受管 auto_disabled 仓库预计为 42 条：
   javaht/claude-desktop-zh-cn 31 条、bayernjf/soft-desk 11 条。
   AlkaidLab/moonlight-harmony 的 1 条是手动停用源，按第 2 条保留。最终仅以 audit 输出为准。

4. **本批不自动处理“公开星标总数为 0”。**
   空列表既可能表示用户真的取消了最后一个星标，也可能表示 GitHub 接口异常却返回了一个看似成功的空响应。
   第一批不新增第二套独立完整性证明，因此即使当前只有一个受管仓库，空快照也必须保持现有
   refused_empty_snapshot：不递增确认、不停用、不清历史，转人工处理。未来若要自动处理最后一个 star，
   必须另开方案，引入独立计数来源交叉核验，不能只靠“连续两次为空”。

5. **删除判断只能使用本轮 Actions 生成的状态。**
   github-star-autosync.json 必须与当前 GITHUB_RUN_ID、GITHUB_RUN_ATTEMPT、GITHUB_SHA 完全匹配，
   并能校验对应 purge-state 文件的 SHA256。旧状态即使写着 ok=true，也只能记录
   stale_autosync_status，一条不删。

---

## 2. 目标与边界

### 本批要实现

- GitHub 星标同步以稳定数字 repo ID 判断同一仓库；改名、转移所有者或大小写变化不能删掉仍订阅的历史。
- 星标快照必须来自两个不同 GITHUB_RUN_ID 的连续、非空、完整运行，且同一 repo ID 都缺失，才允许自动停采该受管仓库。
- 只有在 STAR_SUBSCRIPTION_CLEANUP_MODE=on 且审批摘要匹配时，才从 data/archive.json 删除对应 repo ID 的历史。
- audit 只生成候选与摘要，不修改 archive.json 或派生展示内容。
- 任一身份、状态、摘要、覆盖率、快照完整性不成立时，GitHub 清理 fail-safe：**一条不删**。

### 本批明确不做

- 不把 GitHub 加入 ENUMERABLE_SUBSCRIPTION_SITE_IDS，该通用名单继续只服务 B站 / 抖音。
- 不按 record.source、target、URL 或 owner/repo 清理 GitHub。
- 不动 opmlrss、we_mp_rss_jsonl、小红书和现有 B站 / 抖音清理契约。
- 不改变手动 GitHub 源“停用即暂停”的既有含义；如要统一手动语义，另开方案。
- 不使用 --force-subscription-cleanup 绕过 GitHub 的任何护栏。
- 不删除任何文件；本任务只会在获得批准的 on 阶段删除归档 JSON 中的精确 item。

---

## 3. 架构选择

GitHub 的 owner/repo 是展示地址，不是主键：仓库可改名或转移。当前归档已经保存
github_repo_identity，受管源配置也保存 managed_repo_id，两者才是稳定身份。

GitHub 不复用 B站 / 抖音的名称型 filter_archive_by_subscriptions()，而是走独立的
“受管 repo ID + 两次非空完整快照 + 本轮运行绑定 + audit/on”路径。这样能解决改名、单个 star 取消、一次接口漏项，
并保证代码合入默认没有删除行为。

~~~text
GitHub 完整公开星标快照
        |
        v
github_star_autosync.py
  - 连续缺失计数
  - 第二次才 auto_disabled
  - 写入本轮 run ID / attempt / SHA、状态文件哈希与已确认 repo ID
        |
        v
scripts/radar/cli.py
  off   : 不删
  audit : 生成候选与 approval_digest，不改 archive
  on    : 当前运行匹配 + 状态文件配对 + digest 一致 + 身份覆盖完整
          -> 仅按 github_repo_identity 精确删除
~~~

---

## 4. 数据契约

### 4.1 新增的持久化确认状态

新增 data/github-star-purge-state.json，只包含公开 repo 的数字 ID 和确认次数，禁止写入 token、cookie、
私有仓库名或 API 响应原文。

~~~json
{
  "version": 1,
  "account_id": 284580915,
  "last_complete_snapshot_at": "2026-07-20T00:00:00Z",
  "last_snapshot_run_id": "12345678901",
  "last_snapshot_run_attempt": "1",
  "last_snapshot_head_sha": "40位提交SHA",
  "absence_confirmations": {
    "1219719583": 2,
    "1276562170": 1
  }
}
~~~

- “完整”必须同时满足既有账号 ID、HTTP 响应、响应结构、逐页 Link、数量上限和分页结束校验，
  并新增显式重复 repo ID 校验；本批还要求公开星标列表非空。
- 只有两个不同 GITHUB_RUN_ID 的连续非空完整快照才能把同一 repo 的确认次数从 0 -> 1 -> 2；
  同一 run 的重新执行不能冒充第二轮确认。
- repo 重新出现时立即清零并恢复为活跃态。
- 空快照、账户不一致或采集失败时，不递增也不清零已有的合法确认状态，并禁止清理；
  状态文件缺失或非法时在内存中按 0 次处理，只能由下一次非空完整快照重新初始化。
- 状态文件必须使用现有原子 JSON 写入能力；写入后计算文件 SHA256，供本轮 autosync 状态配对。

### 4.2 当前轮同步状态

扩展 data/github-star-autosync.json，保留现有字段，并增加：

~~~json
{
  "version": 2,
  "workflow_run_id": "12345678901",
  "workflow_run_attempt": "1",
  "workflow_head_sha": "40位提交SHA",
  "snapshot_complete": true,
  "snapshot_completed_at": "2026-07-20T00:00:00Z",
  "purge_state_sha256": "sha256...",
  "pending_absent_repo_ids": ["1219719583"],
  "confirmed_absent_repo_ids": ["1276562170"]
}
~~~

audit/on 必须先比对状态里的 workflow_run_id、workflow_run_attempt、workflow_head_sha 与当前
GITHUB_RUN_ID、GITHUB_RUN_ATTEMPT、GITHUB_SHA，并重算 purge-state 文件 SHA256。任一不一致都记录
stale_autosync_status 或 purge_state_digest_mismatch 并跳过。finished_at / snapshot_completed_at 只用于展示，
不能用“时间看起来很新”代替运行身份校验。这样即使同步进程在写文件前崩溃、工作区留下上一轮 ok=true，
后续采集也不能使用旧确认名单删除历史。

当前状态的 ok=false、snapshot_complete=false 或字段不完整时，本轮 GitHub 清理同样必须跳过。
只有当前轮 confirmed_absent_repo_ids 才能成为候选，不能仅凭持久化计数删除。

### 4.3 repo ID 规范类型

- GitHub API 和现有 config/online-sources.json 的 managed_repo_id 继续使用正整数，不改既有配置 schema。
- 进入清理边界后统一规范为不带前导零的十进制字符串；github_repo_identity、状态文件的对象键、
  pending/confirmed 列表和 digest 输入全部使用该字符串形式。
- Python 边界必须显式拒绝 bool、浮点数、0、负数、空白、+123 和 001 这类非规范值；禁止依赖
  bool 是 int 子类或 JSON 自动类型转换。
- 比较前只允许通过同一个 normalize_repo_identity() 辅助函数转换，不能在各模块临时 str(...)。

### 4.4 审计与批准摘要

新增 data/github-star-subscription-cleanup.json。audit 与 on 都写入，但只有 on 可标记 applied:true。

~~~json
{
  "version": 1,
  "mode": "audit",
  "applied": false,
  "skip_reason": "",
  "candidate_repo_ids": ["1219719583"],
  "candidate_item_ids": ["..."],
  "candidate_counts": {"1219719583": 31},
  "workflow_run_id": "12345678901",
  "archive_sha256_before": "sha256...",
  "purge_state_sha256": "sha256...",
  "approval_digest": "sha256..."
}
~~~

审计文件必须使用现有原子 JSON 写入能力，不能直接 write_text 覆盖。approval_digest 由候选 repo ID、
候选 item ID、候选记录稳定身份和内容摘要计算，不纳入无关新新闻。
on 模式额外要求 Actions Variable
STAR_SUBSCRIPTION_CLEANUP_APPROVAL_DIGEST 与本轮重算的摘要完全一致，否则只记录
approval_digest_mismatch，不删数据。

摘要是对“这一批精确 item”的一次性批准，不承诺跨轮永久有效。若 audit 到 on 之间有条目被 180 天窗口
自然裁掉，或候选发生任何变化，摘要失配是预期的安全结果；标准处理只能是切回 audit、清空旧摘要、
重跑并重新人工审核，再填写新摘要，禁止复用旧摘要或放宽 digest 内容。

---

## 5. 涉及文件

### 必改代码

1. scripts/github_star_autosync.py
   - 读取和原子写入 github-star-purge-state.json。
   - 读取 GITHUB_RUN_ID / GITHUB_RUN_ATTEMPT / GITHUB_SHA，生成 schema 2 本轮状态；状态最后写入，
     并携带 purge-state 的实际 SHA256。
   - 对每个受管 repo ID 做连续完整快照缺失计数。
   - 第一次缺失只报告 pending，配置仍保持 active。
   - 第二次连续缺失才允许传入自动停用集合；现有数量/比例熔断在“已确认集合”上继续生效。
   - 任何空快照都保持现有 refused_empty_snapshot，不增加确认次数、不自动停用并转人工。

2. scripts/radar/server/github_stars.py
   - 给 merge_github_star_sources() 增加仅供自动同步使用的“允许自动停用 repo ID 集合”参数。
   - 手动 Preview/Apply 不传该参数，保持既有人工确认行为。
   - 未二次确认的缺失仓库必须保持 active，不能被 merge 顺手改成 auto_disabled。

3. scripts/radar/config_runtime.py
   - 新增只读取 managed_by=github_stars / managed_repo_id 的受管 GitHub 身份投影辅助函数。
   - 提供唯一的 normalize_repo_identity() 边界转换；配置保留整数，清理域统一使用规范十进制字符串。
   - 不把 GitHub 塞进 source_config_enabled_subscription_names() 的名称名单。

4. scripts/radar/pipeline.py
   - 新增独立的 GitHub 清理提案 / 应用函数，只比较 record.github_repo_identity 与确认过的数字 repo ID。
   - 任一 GitHub 归档记录缺少 github_repo_identity，或候选 repo ID 不能与当前 auto_disabled 受管源一一对应，
     必须熔断整个 GitHub 清理，不删一条。
   - 不修改现有 B站 / 抖音 filter_archive_by_subscriptions() 语义。

5. scripts/radar/cli.py
   - 解析 STAR_SUBSCRIPTION_CLEANUP_MODE，只接受 off/audit/on，缺省和非法值均为 off。
   - 读取当前轮 GitHub autosync 状态、持久化确认状态和 Actions 审批摘要；audit/on 先完成
     run ID / attempt / SHA 与 purge-state SHA256 配对。
   - audit 保持 archive 原对象；on 才替换为精确删除后的 archive。
   - 将模式、候选、熔断原因、approval digest、是否应用写入 source-status.json，并用原子方式写审计文件。

6. scripts/audit_github_star_cleanup.py（新增）
   - 只读预览工具，读取 archive、配置、状态、确认状态，打印候选 repo ID / item ID / 数量 / 摘要 / 跳过原因。
   - 不提供 force 参数，不写文件。

7. scripts/restore_github_subscription_cleanup.py（新增）
   - 按 archive 记录的 id 字段全量预检查，任一冲突则整批拒绝。
   - CLI 参数继续使用 --item-id，与现有微信恢复工具和审计字段 candidate_item_ids 保持一致；
     它在内部明确映射到 record["id"]，不是读取一个名为 item_id 的 JSON 字段。
   - 只允许恢复 github_foundation_sunshine_releases 的 item，不允许整份 archive 覆盖。
   - 默认 dry-run，只有 --apply 才写回。

8. .github/workflows/update-news.yml
   - 在更新数据步骤传入：

~~~yaml
STAR_SUBSCRIPTION_CLEANUP_MODE: ${{ vars.STAR_SUBSCRIPTION_CLEANUP_MODE || 'off' }}
STAR_SUBSCRIPTION_CLEANUP_APPROVAL_DIGEST: ${{ vars.STAR_SUBSCRIPTION_CLEANUP_APPROVAL_DIGEST || '' }}
~~~

   GitHub 官方规定 Actions 配置变量名不能以 GITHUB_ 开头，参考
   [Variables reference](https://docs.github.com/en/actions/reference/workflows-and-actions/variables#naming-conventions-for-configuration-variables)。
   代码、工作流和上线手册全部使用 STAR_ 前缀，不能只改 GitHub 界面里的名字。

   - 保持现有“普通数据采集成功才 git add data/”规则。
   - 扩展 GitHub star guard：若 purge-state 有变化但 autosync 不是本轮成功状态，或两个文件哈希不匹配，
     整轮失败，禁止暂存这份确认进度。
   - 心跳块显式同时暂存 data/github-star-autosync.json 和 data/github-star-purge-state.json；即使普通采集失败，
     两者也必须在同一个状态提交中入库，不能只提交 autosync。若 purge-state 没变化，Git 自然只记录状态差异。

9. scripts/radar/common.py
   - 仅改注释：GitHub 不是容器，但故意不进入名称型 ENUMERABLE_SUBSCRIPTION_SITE_IDS，
     因为它走稳定 repo ID 的专用清理契约。

### 必改测试与文档

- 新增 tests/test_github_subscription_cleanup.py。
- 扩展 tests/test_github_star_autosync.py 与 tests/test_orphan_subscription_cleanup.py。
- 更新 README.md；实际上线验收结束后更新 PROJECT_STATE.md、HANDOFF.md。
- CLAUDE.md 必须在“清理历史条目的禁区”中，紧邻微信例外新增“GitHub 星标托管清理窄例外”，
  明写：仅 github_stars 受管源、稳定 repo ID、两个不同 run 的非空完整快照、本轮状态配对、
  off/audit/on + 一次性审批摘要、全量身份覆盖、空快照熔断和按 record.id 精确恢复。
  不能只写一句“已支持 GitHub”，也不能改宽原有“只有配置保存路径 + 两个窄例外可删历史”的铁律。

### 明确不改

- subscriptions_store.py 的本机手动删除路径。
- opmlrss / we_mp_rss_jsonl / 小红书。
- 前端交互、数据库、依赖、部署结构。

---

## 6. 分步施工

### 6.1 身份与状态层

1. 实现状态文件读写、schema 校验和账户绑定校验。
2. 在完整快照中计算每个 active / auto-disabled 受管 repo 的连续缺失次数。
3. 把 merge_github_star_sources() 的自动停用限制为“本轮已二次确认”的 repo ID。
4. 保留现有空快照、数量骤降、账户不一致、分页失败等熔断；任何失败都不增加确认次数。

### 6.2 专用清理层

1. 从当前配置取得 managed_state=auto_disabled 的受管 repo ID。
2. 与本轮成功 autosync 输出的 confirmed ID 求交集。
3. 校验 archive 中全部 GitHub 记录都有 github_repo_identity；当前基线必须是 190/190 覆盖。
4. 只按 github_repo_identity 生成候选；source 仅用于审计展示，绝不能作为判断依据。
5. 生成 approval_digest 与审计记录。
6. off 不清理；audit 不替换 archive；on 且 digest 一致才应用。

### 6.3 强制 fail-safe 条件

命中任意一项，GitHub 清理必须跳过并记录原因：

- 当前 autosync 失败、快照不完整、账号不一致或状态文件缺失。
- autosync 的 run ID / attempt / SHA 不是当前 Actions，或 purge-state SHA256 不匹配。
- 公开星标快照为空；本批不把连续空快照视为自动清理证据。
- 连续缺失不足两次。
- 候选 source 不是 github_stars 托管的 auto_disabled 源。
- managed_repo_id、github_repo_identity、候选状态三者无法一一对应。
- 任一 GitHub archive 记录没有稳定身份。
- audit/on 模式非法，或 on 的审批摘要不匹配。
- 候选规模触发现有自动同步数量 / 比例熔断。

--force-subscription-cleanup 对这些条件没有任何放行作用。

---

## 7. 测试清单

### 自动同步

1. 一个仓库第一次缺失：配置仍 active，状态只记录 pending。
2. 同一仓库第二次连续缺失：才变 auto_disabled 并列入 confirmed。
3. 第一次缺失后重新出现：计数清零，保持或恢复 active。
4. 无论受管仓库数量是多少，空快照都 refused_empty_snapshot，已有计数不变且不自动停用。
5. 网络失败、分页失败、账户不一致、非法旧状态都不递增确认次数。
6. 上一轮 ok=true 状态残留、本轮同步在写文件前崩溃：run ID 不匹配，清理为 0。
7. 同一 run ID 的不同 attempt、同一 attempt 的错误 SHA、purge-state 哈希不匹配：全部熔断。
8. 普通采集失败时，autosync 与 purge-state 仍作为一对进入同一个心跳提交；不得出现只推进其中一个文件。

### 清理逻辑

1. auto_disabled 受管仓库按 github_repo_identity 删除，source 即使是旧名称也不影响判断。
2. 仓库改名但 repo ID 不变：历史保留，不能误删。
3. 一次只漏一个 star：第一次没有停用、更没有删除。
4. 取消最后一个 star 会得到空快照，本批必须 refused_empty_snapshot 并转人工，不能自动停用或清理。
5. 手动 enabled:false GitHub 源不进入自动候选。
6. archive 缺 stable identity、状态无效、候选与配置不一致时，全 GitHub 通道熔断。
7. audit 模式 archive 字节不变；on 模式只删除候选 item；其它通道零变化。
8. approval digest 不匹配时不删；匹配时才删。
9. audit 后因 180 天窗口裁掉一个候选导致摘要变化：on 不删；切回 audit 后生成新摘要才能再次批准。
10. managed_repo_id 为整数、github_repo_identity 为规范字符串时能正确命中；bool、float、0、负数、
    +123、001 和其它非规范类型必须熔断，不能误比较。
11. 审计文件原子替换失败时，旧文件保持完整，不能留下半截 JSON；archive 不应用候选。
12. 恢复脚本的 --item-id 精确读取 record.id，只恢复指定 GitHub item，保留清理后新增的其它数据；
    混合冲突整批拒绝。
13. 旧 B站 / 抖音清理与 --force-subscription-cleanup 回归不变，且 force 不能影响 GitHub 专用路径。

### 命令

~~~powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_github_star_autosync.py tests/test_github_subscription_cleanup.py tests/test_orphan_subscription_cleanup.py
.\.venv\Scripts\python.exe -m pytest -q
git diff --check
~~~

不得用 unittest discover 代替全量 pytest；仓库含大量顶层 pytest 用例。

---

## 8. 本地 dry-run

代码完成、专项测试和全量 pytest 都通过后，在项目根目录运行：

~~~powershell
.\.venv\Scripts\python.exe -m scripts.audit_github_star_cleanup --source-config config/online-sources.json --archive data/archive.json --state data/github-star-purge-state.json --status data/github-star-autosync.json
~~~

必须核对：

- 归档所有 GitHub 项都有 github_repo_identity；当前基线应为 190/190。
- 候选只来自已连续确认的受管 auto_disabled repo ID。
- 当前基线稳定后，预期是两个受管仓库共约 42 条；手动停用的 moonlight-harmony 不在候选。
- 没有活跃 GitHub repo、B站、抖音、RSS、微信或小红书条目。
- 输出清楚说明当前模式、是否具备完整快照、是否满足二次确认、approval digest 和任一跳过原因。
- 输出 recorded run ID / attempt / SHA、是否匹配当前运行、purge-state SHA256 配对结果。

只要候选包含不应删除的 repo、身份覆盖不是 100%、或状态表示 fail-safe，立即停下汇报。

---

## 9. 上线灰度与人工验收

### 阶段 A：代码合入但保持 off

1. 用户授权后，在 feature 分支 / worktree 完成代码和本地验收。
2. 用户审核变更后再提交、推送、合并。建议中文提交信息：
   功能：新增 GitHub 星标历史清理安全门
3. 合入后 STAR_SUBSCRIPTION_CLEANUP_MODE 保持未设置或 off。
4. 等至少两次不同 GITHUB_RUN_ID 的成功、非空、完整定时 Actions 星标同步，确认状态稳定；
   同一 run 的 re-run 不算第二次，这期间 archive 不得减少。

### 阶段 B：线上 audit

1. 用户手动把 Actions Variable 设为 STAR_SUBSCRIPTION_CLEANUP_MODE=audit。
2. 用户授权后触发或等待一轮 Actions。
3. 检查 data/github-star-subscription-cleanup.json：
   - applied=false；
   - 候选仅为审查过的受管仓库；
   - 输出 approval digest；
   - archive.json 与本轮清理前的 GitHub item 集合完全相同。
4. 在真实浏览器打开公网 GitHub 栏目，确认历史尚未消失。

### 阶段 C：线上 on

1. 用户确认 audit 的候选 item 与数量后，手动设置：

~~~text
STAR_SUBSCRIPTION_CLEANUP_APPROVAL_DIGEST=<audit 输出的 digest>
STAR_SUBSCRIPTION_CLEANUP_MODE=on
~~~

2. 用户授权后运行一轮 Actions。
3. 检查审计文件 applied=true、删除 item ID、候选数量、前后归档数量和 source-status 的清理状态。
4. 在真实浏览器检查：
   - 两个已确认取消星标的仓库历史消失；
   - 至少抽查三个仍订阅仓库，历史、数量和页面卡片正常；
   - 改名模拟或既有改名测试对应仓库历史未丢；
   - 页面没有控制台错误。
5. 验收完成后立即把 STAR_SUBSCRIPTION_CLEANUP_MODE 改回 off，并清空
   STAR_SUBSCRIPTION_CLEANUP_APPROVAL_DIGEST，避免一次性批准长期留在线上。

### 摘要不匹配的固定处理

若 on 轮出现 approval_digest_mismatch，不猜原因、不重复运行 on：

1. 把 STAR_SUBSCRIPTION_CLEANUP_MODE 改回 audit，并清空旧审批摘要。
2. 等待或授权运行一轮完整 Actions，确认 applied=false 和新候选清单。
3. 重新人工核对候选 repo ID、record.id、数量与 archive_sha256_before。
4. 只把这轮的新摘要填回变量，再切 on 执行一次；候选为空则直接回 off，不做删除。

### 阶段 D：反向验证

用户重新给一个已清理仓库加星标，等两轮同步及一次采集后，确认它重新启用并按现有首采回填规则重新出现。

---

## 10. 回滚

1. **先由用户把 STAR_SUBSCRIPTION_CLEANUP_MODE 改回 off 并清空审批摘要**，阻止下一轮继续清理。
2. 代码问题用普通 git revert，禁止 reset --hard、强推或改写历史。
3. 数据恢复只按审计文件中的 candidate_item_ids 精确恢复：

~~~powershell
.\.venv\Scripts\python.exe scripts/restore_github_subscription_cleanup.py --current data/archive.json --before <从清理提交父提交取得的 archive.json> --item-id <candidate_item_ids 中的 record.id> --apply
~~~

4. 恢复前后核对总条数、GitHub repo ID 分布、其它 site_id 分布及 SHA256；禁止用旧
   archive.json 整文件覆盖当前归档。

---

## 11. 红线

- 没有用户确认的二次缺失语义、手动源边界、分支策略和线上变量授权，不能开始代码施工。
- 不把 GitHub 再塞进名称型白名单，不按名称清理，不使用 generic force 绕过稳定身份门。
- 不因“当前 42 / 43 条看起来对”跳过状态、摘要或两次快照校验。
- 不把空快照当成完整删除证据，不使用旧 run 状态，不允许 autosync / purge-state 单文件推进。
- 不改容器型 RSS / 微信清理逻辑，不顺手重构无关模块。
- 不提交私密文件、token、cookie、OPML 或本机运行状态。
- 全部验收通过前不 commit / push；完成后向用户报告实际候选、摘要、模式、测试结果与未验证风险。

## 12. 第二批预告

RSS / YouTube、手动 GitHub 停用语义和其它通道的统一化是独立任务。它们必须各自先定义稳定身份、
完整性证明、audit/on 灰度和精确回滚方式，不能复用本批的 repo ID 契约强行接入。
