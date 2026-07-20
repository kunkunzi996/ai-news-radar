# 施工说明：GitHub 星标定时自动同步（Actions 云端版）

> 给 Codex 的任务说明。请严格按本文件执行，不要自由发挥，不要顺手改其它无关代码。
> 主工作区：`E:\AI-news-reader\ai-news-radar-run`（当前 `master` 与 `origin/master` 一致，
> 但本计划文件本身未跟踪，因此不能称为“工作区干净”）。
> **动工第一步：从最新 `origin/master` 新建独立工作树
> `E:\AI-news-reader\ai-news-radar-github-star-autosync`，分支
> `feature/github-star-autosync`**（用户已同意分支施工）。先检查目标路径和分支均不存在；
> 若已存在则停下汇报，禁止删除或覆盖。主工作区及两份 stash 一律不碰。
> 改完不要 commit / push，停下等用户验收授权。

---

## 施工前门禁（真正动代码时执行，本轮完善计划书不执行）

1. 在主工作区只读核对 `git status --short --branch`、`git stash list`、`git worktree list`，
   确认两个保护 stash 都在；禁止恢复、drop 或改写它们。
2. 执行 `git fetch origin` 获取最新远端基线，不在主工作区切分支。
3. 检查 `feature/github-star-autosync` 分支和目标工作树路径是否已存在；任一存在都停下汇报，
   不得用删除目录、强制覆盖或复用来“处理干净”。
4. 确认不存在后执行：

   ```powershell
   git worktree add E:\AI-news-reader\ai-news-radar-github-star-autosync `
     -b feature/github-star-autosync origin/master
   ```

5. 新工作树必须满足：当前分支为 `feature/github-star-autosync`、起点为最新
   `origin/master`、初始状态干净。后续所有代码和测试操作只在新工作树进行。
6. 本计划文件留在主工作区且未跟踪，执行者继续按绝对路径只读本文件，不要为了让新工作树
   看见它而复制、暂存或提交。

---

## 背景（为什么做这个）

GitHub 星标同步 V3 已于 2026-07-16 真实上线（手动路径：本地面板「预览 GitHub 星标 →
确认并同步」）。但它是**手动一次性动作**：用户在 GitHub 取消星标后，若不回面板再同步
一次，线上配置里该源仍是 `active`，Actions 每轮照采。

**现网遗留问题（本计划一并解决，不许提前手工修）**：`bayernjf/soft-desk` 已取消星标
多日，但线上 `config/online-sources.json` 里仍是 `enabled: true / managed_state: active`
（source id `online_github_repo_1276562170`），新 release 持续刷出（2026-07-18 排查确认）。
**禁止**任何人手工改配置停用它——它就是本功能上线后第一轮 Actions 的真实验收用例，
必须由自动同步来修（见「人工验收清单」第 2 条）。

当初 V3 不做自动同步的三个原因，现在都有了着落：

1. "自动停用须人工确认"——因为怕不完整星标快照误停用。现在 `fetch_github_star_snapshot`
   已实现完整翻页校验，任何中间页失败/畸形/超限都整次抛错，不会产生半截快照；且停用
   是可逆的（`auto_disabled`，不删源、不删历史、不触发退订清理），误停最坏代价是漏采几十分钟。
2. "真实配置 push 须用户逐次授权"——针对的是**本机脏工作区**上那套 stash/rebase 编排。
   本方案跑在 Actions runner 的干净 checkout 上，与本机 Git 编排完全无关；用户对"Actions
   自动提交配置"的授权在本计划验收时一次性给出。
3. MVP 范围裁剪——现在 V3 已验收，属于正常的第二期。

**现状（已读真代码核实，本地与远端一致）**：

- `.github/workflows/update-news.yml`：每小时 `:07`/`:37` 定时跑，`Update data` 步骤已有
  `GITHUB_TOKEN: ${{ github.token }}`，最后一步只提交 `data/`。
- `scripts/radar/server/github_stars.py`：纯函数
  `fetch_github_star_snapshot(session, *, username/account_id)`、
  `merge_github_star_sources(config, *, account, repositories)`（返回
  `{config, summary, requires_confirmation, config_changed}`，合并真值表含新增/停用/恢复/
  改名/收编）。`create_github_stars_session()` **不带 token**（本次在新 CLI 层补，不改该文件）。
- `scripts/radar/server/online_sources.py`：可复用 `_read_online_json_config`、
  `ensure_public_online_paths`、`render_online_opml_bytes`、`_online_file_matches`、
  `validate_online_config_schema`、`online_user_sources_from_config`、`build_online_config`、
  `render_json_bytes`、`atomic_replace_bytes`、`write_json_atomic`、`utc_timestamp`。
  其中 `apply_online_source_config_operation`（本地 Git 事务版，manifest/stash 那套）
  **云端绝不复用**，但其写盘口径（`no_change` 判定、先 OPML 后 JSON、变更时刷新
  `updated_at`）是本 CLI 的对齐样板。
- 线上配置已绑定 `kunkunzi996`（account_id `284580915`），15 个受管 `github_release` 源。

**已确认的产品决策**：

1. 自动同步跑在 GitHub Actions（每轮采集前），本机无需开机；本机那套 Git 事务不碰。
2. 只在"已绑定"时工作；首次绑定、解绑、收编手动源仍走本地面板手动操作。
3. 取消星标→自动停用**不再逐个人工确认**（这正是需求），保留四道保险：
   快照不完整整次中止（现成）；星标数为 0 且将产生停用时熔断；单轮停用超过 3 个或
   超过原活跃受管源 50% 时熔断；需收编手动源时整轮跳过。三类熔断均转本地面板人工同步。
4. `no_change` 的准确口径：`config/online-sources.json`、`feeds/online-sources.opml`、
   `updated_at` 和“配置：GitHub星标自动同步”提交都不动。状态文件是运行心跳，允许每轮刷新
   `finished_at` 并随正常 `data/` 快照提交；不得再描述为“整仓库零写入、Git 历史零变化”。
5. 每轮写 schema 1 状态文件 `data/github-star-autosync.json`（随 `git add data/` 自动入库）；
   即使后续普通数据采集失败，也允许单独提交这份公开状态。
6. 本次不改前端；不新增 source type / site_id。
7. soft-desk 遗留问题由上线首轮自动修复，不单独手工处理。

---

## 一、目标（要做成什么样）

用户在 GitHub 取消/新增星标后，**正常情况下约 30 分钟内**（下一轮 Actions），线上配置自动
停用/新增对应源，之后的采集立即生效，全程无需用户操作。GitHub API、Actions 或 push 失败时
转为下一次成功运行重试，不承诺硬性 30 分钟。无变化轮次不改两个配置文件、不刷新 `updated_at`、
不产生配置提交；状态心跳和其它采集数据仍可产生 `data/` 提交。
上线后第一轮运行自动停用 `bayernjf/soft-desk`，解决现网遗留问题。

**本次范围只做"已绑定账号的云端自动增/停/恢复/改名"，不做：**
首次自动绑定、自动解绑、自动收编手动源、本机定时任务、前端展示状态文件、
删除任何源记录或历史条目、手工修改线上配置。

---

## 二、关键技术点

1. **云端不走本地 Git 事务** → runner checkout 干净，CLI 不使用 manifest/stash/rebase，
   commit/push 由 workflow 完成。CLI 内禁止执行任何 git 命令。
2. **写盘口径与 `apply_online_source_config_operation` 逐行对齐** → 变更时用不带
   `updated_at` 的 `build_online_config` 刷新时间戳；先写 OPML 再写 JSON；写前做
   `derived_opml_mismatch` 同款一致性闸。`config_changed` 判定直接用 merge 返回值
   （digest 比较，天然排除 `updated_at`，保证幂等）。
3. **双文件成对安全** → “原子写”只能保护单个文件，不能天然保护 JSON+OPML 两个文件。
   CLI 必须先渲染并备份两个文件，再依次写入；任一步写入或写后校验失败，都用备份恢复两者。
   workflow 再加第二道闸：同步步骤失败且两个配置文件仍有 diff 时，整轮阻断，禁止采集和提交。
4. **收编（adopted）保留人工确认** → `summary["adopted"]` 非空时本轮整体不写，
   状态文件提示去本地面板手动同步。不改 `merge_github_star_sources`。
5. **空快照熔断** → `starred_count == 0` 且将产生停用时拒绝写入（防 API 返回
   "合法但空"的列表导致无人值守全量停用）。用户真要清空全部星标时走本地面板手动同步。
6. **数量骤降熔断** → 非空快照若会一次停用超过 3 个源，或超过同步前活跃受管源的 50%，
   返回 `refused_mass_disable` 且两个配置文件不写。完整翻页只能证明请求过程完整，不能证明
   上游返回的内容在业务上合理；用户确实批量取消星标时改走本地面板人工确认。
7. **token** → CLI 从 `GITHUB_TOKEN` 环境变量给 session 加 `Authorization: Bearer`
   （照 `scripts/radar/fetchers/subscriptions.py` 中 `fetch_github_repo_subscription`
   约 220 行起的现有写法），Actions 内置 `github.token` 限额 1000 次/小时，每轮仅 2 次请求。
8. **提交编排与失败解耦** → 配置变更单独成中文提交 `配置：GitHub星标自动同步`，先于
   数据/状态提交，最后一次 push 带出。提交步骤使用 `always() && !cancelled()`：普通数据采集
   失败时，已安全完成的星标配置和状态仍可推送；但同步失败留下配置 diff 时由安全闸整轮阻断。
   含配置的 push 不在 `paths-ignore: data/**` 内，会自触发一轮新 run；下一轮 `no_change`
   不再产生配置提交，随后只有 `data/**` 时不会继续触发，属预期的单次收敛。

### 已知且可接受的运行特性（不需要额外修复）

1. **配置已写好，但状态文件写入时崩溃**：状态文件写入位于 `run_autosync()` 的保护范围之外。
   极端情况下，两个配置文件已成对写好，随后 `data/github-star-autosync.json` 写入失败，CLI 会以
   非零状态退出。workflow 安全闸会看到“同步步骤失败但配置有 diff”，于是阻断本轮后续采集和提交。
   runner 是一次性的，未 push 的本地改动会随 runner 销毁，远端不会残留半成品；下一轮从干净
   checkout 重新同步即可自愈。代价只是浪费一轮运行，属于宁可延迟、也不冒险提交的预期取舍。
2. **数量骤降熔断会持续保持**：如果用户确实一次取消 4 个星标等，当前配置与 GitHub 快照之间的
   差异不会自行消失，因此以后每轮都会继续返回 `refused_mass_disable`，直到用户去本地面板完成
   一次人工 Preview/Apply。这个“持续拒绝”是设计意图，不是死循环或故障；状态文件会通过
   `outcome=refused_mass_disable` 和 `summary.disabled` 明确写出原因及待停用的公开仓库，方便定位。

---

## 三、文件清单

**新建**

1. `scripts/github_star_autosync.py` —— 自动同步 CLI（约 250 行，含成对回滚与写后校验）
2. `tests/test_github_star_autosync.py` —— 专项单测

**修改**

3. `.github/workflows/update-news.yml` —— 新增同步步骤、安全闸，给数据步骤加 id，并重整提交步骤
4. `README.md`、`README.en.md`、`docs/SOURCE_COVERAGE.md` —— 补自动同步真实口径；同时修正
   README 中“V3 尚未真实上线”的过期描述
5. `PROJECT_STATE.md`、`HANDOFF.md` —— **只在真实验收通过后**更新

**明确不改**：`scripts/radar/server/github_stars.py`、`scripts/radar/server/online_sources.py`
（一行都不改，纯复用）、任何前端文件、`config/online-sources.json`（**严禁**手工编辑，
包括提前停用 soft-desk）、任何 `data/*.json` 手工内容、Actions secrets/vars。

---

## 四、后端改动（详细步骤）

### 4.1 新建 `scripts/github_star_autosync.py`

入口样式照 `scripts/update_news.py` 开头的 `sys.path` 引导写。完整代码：

```python
#!/usr/bin/env python3
"""GitHub 星标自动同步：供 Actions 在每轮采集前调用。

拉当前星标快照 -> merge_github_star_sources 算出新配置 ->
成对安全写 config/online-sources.json 与 feeds/online-sources.opml。
Git 提交由 workflow 负责；本脚本不执行任何 git 命令。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests  # noqa: E402

from scripts.radar.server import github_stars as _github_stars  # noqa: E402
from scripts.radar.server import online_sources as _online_sources  # noqa: E402

STATUS_FILENAME = Path("data") / "github-star-autosync.json"
MAX_AUTOMATIC_DISABLE_COUNT = 3


class AutosyncError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _status(
    outcome: str,
    *,
    ok: bool,
    account: dict | None = None,
    snapshot: dict | None = None,
    summary: dict | None = None,
    error_code: str = "",
) -> dict:
    payload = {
        "version": 1,
        "ok": ok,
        "outcome": outcome,
        "finished_at": _online_sources.utc_timestamp(),
        "error_code": error_code,
    }
    if account is not None:
        payload["account_id"] = account.get("id")
        payload["account_login"] = account.get("login")
    if snapshot is not None:
        payload["starred_count"] = snapshot.get("starred_count")
        payload["private_skipped_count"] = snapshot.get("private_skipped_count")
    if summary is not None:
        payload["summary"] = summary
    return payload


def _active_managed_source_count(config: dict, account_id: int) -> int:
    return sum(
        1
        for source in config["sources"]
        if source.get("managed_by") == "github_stars"
        and source.get("managed_account_id") == account_id
        and source.get("managed_state") == "active"
    )


def _write_config_pair(
    root_dir: Path,
    *,
    config_path: Path,
    opml_path: Path,
    config_content: bytes,
    opml_content: bytes,
) -> None:
    # 两次 os.replace 只能分别保证单文件完整；这里额外负责成对回滚与写后校验。
    try:
        config_before = config_path.read_bytes()
        opml_before = opml_path.read_bytes()
    except OSError as exc:
        raise AutosyncError("config_pair_backup_failed") from exc

    try:
        _online_sources.atomic_replace_bytes(opml_path, opml_content)
        _online_sources.atomic_replace_bytes(config_path, config_content)
        try:
            written_config = _online_sources._read_online_json_config(root_dir)
            expected_opml, _ = _online_sources.render_online_opml_bytes(
                written_config["sources"]
            )
            if config_path.read_bytes() != config_content:
                raise AutosyncError("config_pair_postcheck_failed")
            if not _online_sources._online_file_matches(opml_path, opml_content):
                raise AutosyncError("config_pair_postcheck_failed")
            if not _online_sources._online_file_matches(opml_path, expected_opml):
                raise AutosyncError("config_pair_postcheck_failed")
        except AutosyncError:
            raise
        except Exception as exc:
            raise AutosyncError("config_pair_postcheck_failed") from exc
    except Exception as exc:
        rollback_failed = False
        # 两个文件都恢复，不根据“可能写过哪个”做猜测。
        for path, content in (
            (config_path, config_before),
            (opml_path, opml_before),
        ):
            try:
                _online_sources.atomic_replace_bytes(path, content)
            except Exception:
                rollback_failed = True
        if rollback_failed:
            raise AutosyncError("config_pair_rollback_failed") from exc
        code = exc.code if isinstance(exc, AutosyncError) else "config_pair_write_failed"
        raise AutosyncError(code) from exc


def run_autosync(
    root_dir: Path,
    *,
    dry_run: bool = False,
    session: requests.Session | None = None,
) -> dict:
    config = _online_sources._read_online_json_config(root_dir)
    binding = config.get("github_star_sync")
    if binding is None:
        return _status("skipped_not_bound", ok=True)

    # 与 apply_online_source_config_operation 相同的派生文件一致性闸：
    # OPML 与当前 JSON 对不上说明仓库状态异常，宁可跳过也不写。
    config_path, opml_path = _online_sources.ensure_public_online_paths(root_dir)
    expected_opml, _ = _online_sources.render_online_opml_bytes(config["sources"])
    if not _online_sources._online_file_matches(opml_path, expected_opml):
        return _status("aborted_opml_mismatch", ok=False)

    owned_session = session is None
    active_session = session or _github_stars.create_github_stars_session()
    token = str(os.environ.get("GITHUB_TOKEN") or "").strip()
    if token:
        active_session.headers["Authorization"] = f"Bearer {token}"
    try:
        snapshot = _github_stars.fetch_github_star_snapshot(
            active_session,
            account_id=binding["account_id"],
        )
    finally:
        if owned_session:
            active_session.close()

    merge = _github_stars.merge_github_star_sources(
        config,
        account=snapshot["account"],
        repositories=snapshot["repositories"],
    )
    summary = merge["summary"]
    account = snapshot["account"]
    if not merge["config_changed"]:
        return _status("no_change", ok=True, account=account, snapshot=snapshot, summary=summary)
    if summary["adopted"]:
        # 收编手动源必须人工确认（沿用 V3 规则），本轮整体不写。
        return _status(
            "manual_confirmation_required",
            ok=False,
            account=account,
            snapshot=snapshot,
            summary=summary,
        )
    if snapshot["starred_count"] == 0 and summary["disabled"]:
        # 熔断：星标列表“合法但全空”时拒绝无人值守全量停用，转人工。
        return _status(
            "refused_empty_snapshot",
            ok=False,
            account=account,
            snapshot=snapshot,
            summary=summary,
        )
    active_managed_count = _active_managed_source_count(
        config, binding["account_id"]
    )
    disabled_count = len(summary["disabled"])
    if disabled_count > MAX_AUTOMATIC_DISABLE_COUNT or (
        active_managed_count > 0
        and disabled_count * 2 > active_managed_count
    ):
        # 非空但数量骤降也可能是上游“合法但不合理”的残缺结果，转人工确认。
        return _status(
            "refused_mass_disable",
            ok=False,
            account=account,
            snapshot=snapshot,
            summary=summary,
        )
    if dry_run:
        return _status("dry_run", ok=True, account=account, snapshot=snapshot, summary=summary)

    # 写盘口径与 apply_online_source_config_operation 对齐：
    # 变更时用不带 updated_at 的 build_online_config 刷新时间戳，先 OPML 后 JSON。
    normalized_candidate = _online_sources.validate_online_config_schema(
        merge["config"], existing=True
    )
    user_sources = _online_sources.online_user_sources_from_config(normalized_candidate)
    candidate = _online_sources.build_online_config(
        user_sources,
        github_star_sync=normalized_candidate.get("github_star_sync"),
    )
    config_content = _online_sources.render_json_bytes(candidate)
    opml_content, _ = _online_sources.render_online_opml_bytes(user_sources)
    _write_config_pair(
        root_dir,
        config_path=config_path,
        opml_path=opml_path,
        config_content=config_content,
        opml_content=opml_content,
    )
    return _status("synced", ok=True, account=account, snapshot=snapshot, summary=summary)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="GitHub 星标自动同步（Actions 用）")
    parser.add_argument("--root", default=".", help="仓库根目录")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印将发生的变化，不写任何文件（含状态文件）",
    )
    args = parser.parse_args(argv)
    root_dir = Path(args.root).resolve()
    try:
        status = run_autosync(root_dir, dry_run=args.dry_run)
    except (
        AutosyncError,
        _github_stars.GitHubStarsError,
        _online_sources.OnlineSourcesError,
    ) as exc:
        status = _status("failed", ok=False, error_code=exc.code)
    except Exception:
        # 不把上游响应、路径或其它内部细节写进公开状态文件。
        status = _status("failed", ok=False, error_code="autosync_internal_error")
    if not args.dry_run:
        _online_sources.write_json_atomic(root_dir / STATUS_FILENAME, status)
    print(json.dumps(status, ensure_ascii=False))
    return 0 if status.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

> 安全要点（必须遵守）：
> - **绝不调用** `prepare_manual_online_config` / `write_online_source_config` /
>   `save_online_source_config_transaction` —— 那是"普通保存"路径，会计算退订清理
>   delta（pending-purge）。项目铁律：星标同步**永不**产生退订清理。
> - **绝不调用** `apply_online_source_config_operation` / `fresh_git_preflight` ——
>   本地 Git 事务，云端禁止；CLI 内不执行任何 git 命令。
> - 停用只能由 `merge_github_star_sources` 纯函数翻字段，CLI 自己不改任何 source。
> - “原子写”只保护单文件；两个配置文件必须经过备份、成对恢复和写后派生一致性校验。
>   `config_pair_rollback_failed` 属于危险失败，workflow 必须发现残留 diff 并阻断整轮。
> - 状态文件只含公开信息：账号 login/id、数量、公开 repo 名。私有仓库只有数量。

### 4.2 修改 `.github/workflows/update-news.yml`

**改动一**：在 `Install dependencies` 步骤之后、`Fetch Douyin bridge JSONL` 之前，插入
同步步骤和失败残留安全闸：

```yaml
      - name: Sync GitHub stars
        id: github_star_sync
        continue-on-error: true
        env:
          GITHUB_TOKEN: ${{ github.token }}
        run: |
          # 星标自动同步：取消星标自动停用、新星标自动接管。
          # 任何失败（限流/需人工确认/熔断）都不阻塞后面的正常采集。
          python scripts/github_star_autosync.py --root .

      - name: Guard GitHub star sync writes
        id: github_star_guard
        if: ${{ always() }}
        run: |
          # 预期失败必须保持两个配置文件零 diff；否则说明回滚没完成，整轮禁止继续。
          if [ "${{ steps.github_star_sync.outcome }}" != "success" ] && \
             ! git diff --quiet -- config/online-sources.json feeds/online-sources.opml; then
            echo "::error::GitHub star sync failed with unsafe config changes; refusing to continue"
            git status --short -- config/online-sources.json feeds/online-sources.opml
            exit 1
          fi
```

**改动二**：给现有 `Update data` 步骤增加 id，其余采集命令不动：

```yaml
      - name: Update data
        id: update_data
```

**改动三**：把现有 `Commit and push changes` 步骤替换为下面版本。目的有三个：

1. 同步失败且留下危险配置 diff 时，安全闸失败，本步骤不执行。
2. 普通数据采集失败时，已安全完成的配置和状态仍可提交、推送。
3. 数据采集失败时只精确暂存状态文件，不得把半成品 `data/**` 一起提交。

```yaml
      - name: Commit and push changes
        if: ${{ always() && !cancelled() && steps.github_star_guard.outcome == 'success' }}
        env:
          EMAIL_DIGEST_PUBLISH: ${{ secrets.EMAIL_DIGEST_PUBLISH || vars.EMAIL_DIGEST_PUBLISH }}
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          has_commit=0

          # 只有同步步骤成功时才允许提交配置；失败状态下即使有 diff 也绝不暂存。
          if [ "${{ steps.github_star_sync.outcome }}" = "success" ] && \
             ! git diff --quiet -- config/online-sources.json feeds/online-sources.opml; then
            git add config/online-sources.json feeds/online-sources.opml
            git commit -m "配置：GitHub星标自动同步"
            has_commit=1
          fi

          # 状态文件是独立心跳；普通采集失败时也允许精确提交它。
          if [ -f data/github-star-autosync.json ]; then
            git add data/github-star-autosync.json
          fi

          if [ "${{ steps.update_data.outcome }}" = "success" ]; then
            # 正常采集成功才暂存完整 data 目录。
            git add data/
            if [ -f data/email-digest.json ] && [ "$EMAIL_DIGEST_PUBLISH" = "1" ]; then
              git add -f data/email-digest.json
            fi
            # 保留原有自检：正常采集成功后，data 下不得残留未暂存生成物。
            if [ -n "$(git status --porcelain --untracked-files=all -- data/ | grep -v '^[MADRC]' || true)" ]; then
              echo "::error::Generated files under data/ were not staged:"
              git status --porcelain --untracked-files=all -- data/ | grep -v '^[MADRC]'
              exit 1
            fi
            data_commit_message="数据：更新 AI 新闻快照"
          else
            echo "::warning::Update data failed or was skipped; committing only safe GitHub star status/config changes"
            data_commit_message="状态：记录 GitHub 星标自动同步"
          fi

          if ! git diff --cached --quiet; then
            git commit -m "$data_commit_message"
            has_commit=1
          fi
          if [ "$has_commit" -eq 0 ]; then
            echo "No changes to commit"
            exit 0
          fi
          git push
```

除上述明确位置外，不改 `paths-ignore`、`concurrency`、桥接步骤或采集参数。原有 data
自检逻辑只包进“Update data 成功”分支，内容和安全目的保持不变。

### 4.3 新建 `tests/test_github_star_autosync.py`

夹具优先复用 `tests/test_github_stars.py` 里现成的 `FakeResponse`、`FakeSession`、
`public_repo`、`managed_source`、`manual_source`、`config_with`（pytest 默认 import 模式下
`from test_github_stars import ...` 可用；若导入失败就把这几个小夹具复制过来，不改原文件）。
**注意现成 `FakeSession` 没有 `headers` 属性，不能原样用于 token 用例**；在新测试文件中
定义一个很薄的子类，不改原测试文件：

```python
class AutosyncFakeSession(FakeSession):
    def __init__(self, responses):
        super().__init__(responses)
        self.headers: dict[str, str] = {}
```

临时仓库夹具参考 `tests/test_online_sources.py` 里"写配置 + OPML 到 tmp 目录"的现有写法：

```python
def write_repo_fixture(root: Path, config: dict) -> dict:
    normalized = online_sources.validate_online_config_schema(copy.deepcopy(config), existing=True)
    user_sources = online_sources.online_user_sources_from_config(normalized)
    candidate = online_sources.build_online_config(
        user_sources,
        updated_at=normalized.get("updated_at"),
        github_star_sync=normalized.get("github_star_sync"),
    )
    (root / "data").mkdir(parents=True, exist_ok=True)
    online_sources.write_json_atomic(root / "config" / "online-sources.json", candidate)
    opml, _ = online_sources.render_online_opml_bytes(candidate["sources"])
    online_sources.atomic_replace_bytes(root / "feeds" / "online-sources.opml", opml)
    return candidate
```

AutosyncFakeSession 的响应序列为两条：`GET /user/{id}` 的账号响应 + starred 首页响应（无 Link 头
即单页）。**必测用例（每条新分支都要有）**：

1. 未绑定 → `skipped_not_bound`，两个配置文件字节不变。
2. `no_change` → 配置字节逐字节不变、`updated_at` 不变、OPML 不变。
3. 新增星标 → `synced`：配置多出 `online_github_repo_<id>` 受管源、OPML 同步重生成、
   `updated_at` 刷新、digest 变化。
4. 取消星标 → `synced`：目标源 `enabled=False`、`managed_state=auto_disabled`，
   **源记录仍在**，其它源逐字段不动。
5. `starred_count==0` 且有停用 → `refused_empty_snapshot`，不写文件，`ok=False`。
6. 非空快照但单轮会停用 4/15 个源 → `refused_mass_disable`，两个配置文件不写。
7. 数量骤降边界 → 单轮停用 3/15 个允许同步；单轮停用超过原活跃源 50% 拒绝同步。
8. `summary["adopted"]` 非空（星标里有一个与已启用手动源同名的 repo）→
   `manual_confirmation_required`，不写文件。
9. 磁盘 OPML 被改得与 JSON 不一致 → `aborted_opml_mismatch`，不写文件。
10. 设了 `GITHUB_TOKEN` 环境变量 → session 请求头带 `Authorization: Bearer xxx`；
   未设则不带（用 `unittest.mock.patch.dict(os.environ)`）。
11. fetch 抛 `github_upstream_rate_limited` → `main()` 返回 1、配置不写、
   状态文件仍写入且 `error_code` 正确。
12. 未预期的普通 `ValueError` / JSON 解析错误 → `main()` 返回 1，公开状态只写
    `autosync_internal_error`，不泄露路径或上游响应正文。
13. `--dry-run` → 任何文件（含状态文件）都不写，stdout 有 JSON。
14. `main()` 正常路径 → 状态文件落在 `data/github-star-autosync.json`，为合法 schema 1 JSON。
15. 故障注入：第一次 OPML 写成功、第二次 JSON 写失败 → 抛 `config_pair_write_failed`，
    两个文件都逐字节恢复为旧内容。
16. 故障注入：两次写成功但写后一致性校验失败 → 抛 `config_pair_postcheck_failed`，
    两个文件都逐字节恢复为旧内容。
17. 故障注入：写入失败后，至少一次恢复也失败 → 抛 `config_pair_rollback_failed`，绝不能返回
    `synced`；这是 workflow “失败且残留配置 diff 就阻断整轮”的对应危险分支。
18. 状态心跳语义 → 连续两次 `no_change` 时两个配置文件和 `updated_at` 不变；状态文件的
    `finished_at` 允许刷新，测试不得错误断言整仓库零写入。

### 4.4 文档口径（`README.md` / `README.en.md` / `docs/SOURCE_COVERAGE.md`）

先删除或改写 README 中“V3 尚待真实账号首次 Preview/Apply、不能描述为已上线”的过期段落；
`PROJECT_STATE.md` 已记录 V3 于 2026-07-16 完成真实上线，三份用户文档不得继续互相矛盾。

再在 GitHub 星标同步相关段落补充真实口径（中英各自对应）：
"已绑定账号的星标每轮采集前自动同步（约每 30 分钟）：取消星标自动停用（历史保留、随
`archive_days` 老化），新星标自动接管；**收编已有手动源、首次绑定、解绑仍需在本地面板
手动操作**。空快照或数量骤降会熔断并转人工。状态见
`data/github-star-autosync.json`。无配置变化时配置文件和 `updated_at` 不变，但状态心跳仍会刷新。"

---

## 五、前端改动

无（本次不做前端展示；状态文件已为将来面板展示留好数据）。

---

## 六、自测（改完必须跑，全绿才算完成）

在独立工作树 `E:\AI-news-reader\ai-news-radar-github-star-autosync` 根目录依次执行。
独立 worktree 不重复创建 `.venv`，只读复用主工作区现有虚拟环境：

```powershell
$python = 'E:\AI-news-reader\ai-news-radar-run\.venv\Scripts\python.exe'
& $python -m py_compile scripts\github_star_autosync.py
& $python -m pytest tests\test_github_star_autosync.py -q
& $python -m pytest tests -q
git check-ignore data/github-star-autosync.json; if ($LASTEXITCODE -eq 0) { throw "状态文件被 gitignore 拦住了" }
& $python scripts\github_star_autosync.py --root . --dry-run
git diff --check
git status --short --branch
```

- 全量 pytest 不许有新失败。
- 专项测试必须真实覆盖“双文件第二次写入失败后恢复原字节”和“非空快照数量骤降熔断”，
  不能只测正常路径。
- `--dry-run` 走真实匿名 API（只读、2 次请求）：预期输出 JSON 里 `disabled` 含
  `bayernjf/soft-desk`（它正是当前待停用的真实案例），且工作区零文件变更
  （运行前后比较，`git status` 只应看到本计划清单内的施工改动）。若真实星标状态已变化，
  不得硬凑该断言；先向用户报告外部基线变化，再更新真实验收用例。
- 人工审查 workflow diff：同步步骤必须有 `id`；失败残留闸必须在普通采集前；提交步骤必须
  带 `always() && !cancelled()`，且只有 `Update data` 成功才可 `git add data/`。
- 全绿后**停下汇报，不要 commit**。

---

## 七、人工验收清单（交给用户在真实环境点）

1. 用户确认后，先在功能分支做一个功能完整、测试全绿的中文提交，再按用户授权合并进
   `master` 并普通 push；禁止直接在主工作区施工或强推。
2. push 会触发一轮 Actions（或到 GitHub 网页手动 Run workflow）。看 `Sync GitHub stars`
   与 `Guard GitHub star sync writes` 步骤日志——**第一轮就是真实验收，也是修掉 soft-desk
   遗留问题的那一轮**：
   当前线上配置里 soft-desk 仍是 active 而星标已取消，本轮应产出提交
   `配置：GitHub星标自动同步`，diff 恰好是 soft-desk 的 `enabled: true→false`、
   `managed_state: active→auto_disabled` 加 `updated_at` 刷新，其它源一个不动。
3. 第一轮核对两个配置文件始终成对一致：JSON 能通过 schema 校验，按 JSON 重新渲染的 OPML
   与仓库 OPML 字节一致；不存在只改其中一个文件的提交。
4. 等下一轮定时（约 30 分钟）：不再有配置提交，两个配置文件和 `updated_at` 不变；公网
   `data/github-star-autosync.json` 显示 `no_change` 且 `finished_at` 刷新。允许正常 `data/`
   心跳提交，这不算幂等失败。
5. 【单测覆盖不到，务必亲手做】在 GitHub 真实取消或加回一个星标 → 等下一轮 →
   配置自动停用/恢复；加回时 `re_enabled` 且 source id 不变。
6. 【单测覆盖不到】本地面板联动：自动同步推了配置提交后，本地「保存/同步到线上」会被
   stale/preflight 拦（远端配置变了）——确认提示正常出现、按提示先更新本地即可恢复。
   这是既有保护，不是回归。
7. 浏览器打开公网页面：GitHub Release 平台不再新增 soft-desk 条目（历史条目仍在、
   随 180 天窗口自然老化，属预期）。
8. 若第一轮普通 `Update data` 恰好失败，仍应看到安全完成的配置/状态提交已推送；Actions
   整体可以因采集失败显示红色，但不得丢掉配置提交，也不得提交半成品 `data/**`。

---

## 八、红线（务必遵守）

- 动工只能在独立工作树 `E:\AI-news-reader\ai-news-radar-github-star-autosync` 和分支
  `feature/github-star-autosync`；主工作区、未跟踪计划文件及两个 stash 一律不碰。
- 施工完成后不要自行 commit / push，先停下等用户验收授权；获授权后提交信息必须中文，
  且每个提交都要功能完整、业务可用。
- 只动"文件清单"里的文件；`github_stars.py` 与 `online_sources.py` **一行都不许改**；
  `config/online-sources.json` **严禁手工编辑**（soft-desk 必须由自动同步在线上修，
  不许提前手工停用）。
- 绝不走普通保存/退订清理路径（`prepare_manual_online_config` 等），星标同步永不产生
  pending-purge；绝不删除任何 source 记录或 `data/archive.json` 历史条目。
- CLI 内不执行任何 git 命令；不用本地 Git 事务函数。
- 不批量删除文件。
- 不动 Actions secrets/vars；不改 `paths-ignore`、`concurrency`、桥接步骤和采集参数。
  data 自检只允许按本计划包进 `Update data` 成功分支，不得删除或弱化。
- workflow 的配置、数据、状态提交信息全部用中文；不加 `--no-verify`。

---

## 遵循的规范

- `CLAUDE.md`：清理历史条目的禁区（采集/同步不删源；星标停用不触发清理）、
  「同步线上」git 编排禁区（那段本地代码本次完全不碰）、新增数据源必查清单
  （本次无新 type/site_id，不触发）。
- 星标同步 V3 的既定硬约束（继续有效）：取消星标只自动停用、不删源、不删历史、
  不产生 pending-purge；合并真值表以 `merge_github_star_sources` 现有实现为准，不改语义；
  历史条目仍按全局 `archive_days` 自然老化，不承诺永久保留。
  本计划只放宽"每个自动停用都需人工确认"这一条，以完整性校验 + 空快照熔断 +
  数量骤降熔断 + 收编转人工 + 双文件失败回滚作为替代保险。
