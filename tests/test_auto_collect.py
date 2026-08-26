import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.radar.server import auto_collect

DOUYIN_SEC_UID = "MS4wLjABAAAACsVvwoWhwaNZkd4kOY7bu6UhcfCiYmd_k_wcUnN9bYo8jOANJ1iyts7MXQB8nsZ0"
DOUYIN_SEC_UID_2 = "MS4wLjABAAAAbsEkiVbKt7yhYoBK8_PkNTQoPAgRiLzOyrBc-sYHSdo"


def douyin_source(sec_uid=DOUYIN_SEC_UID, *, source_id="online_douyin_1", enabled=True, name="测试博主"):
    return {
        "id": source_id,
        "name": name,
        "type": auto_collect.DOUYIN_SOURCE_TYPE,
        "enabled": enabled,
        "locator": f"https://www.douyin.com/user/{sec_uid}",
        "target": name,
    }


def wechat_source(*, source_id="online_wechat_1", enabled=True, name="猫笔刀 (WeRSS)"):
    return {
        "id": source_id,
        "name": name,
        "type": auto_collect.WECHAT_SOURCE_TYPE,
        "enabled": enabled,
        "locator": "",
        "target": "猫笔刀",
    }


def bilibili_source(*, source_id="online_bilibili_1", enabled=True):
    return {
        "id": source_id,
        "name": "某 UP",
        "type": "bilibili_dynamic",
        "enabled": enabled,
        "locator": "123456",
    }


def config_of(*sources):
    return {"sources": list(sources)}


class DetectAddedBridgeSourcesTests(unittest.TestCase):
    def test_added_douyin_source_is_detected(self):
        previous = config_of(bilibili_source())
        current = config_of(bilibili_source(), douyin_source())
        detected = auto_collect.detect_added_bridge_sources(previous, current)
        self.assertEqual(detected["douyin_sec_uids"], [DOUYIN_SEC_UID])
        self.assertFalse(detected["wechat_added"])

    def test_added_wechat_source_is_detected(self):
        previous = config_of(bilibili_source())
        current = config_of(bilibili_source(), wechat_source())
        detected = auto_collect.detect_added_bridge_sources(previous, current)
        self.assertFalse(detected["wechat_added"])
        self.assertEqual(detected["douyin_sec_uids"], [])
        self.assertFalse(auto_collect.has_pending_work(detected))

    def test_removed_source_does_not_trigger(self):
        previous = config_of(bilibili_source(), douyin_source())
        current = config_of(bilibili_source())
        detected = auto_collect.detect_added_bridge_sources(previous, current)
        self.assertFalse(auto_collect.has_pending_work(detected))

    def test_disabled_source_does_not_trigger(self):
        previous = config_of(douyin_source())
        current = config_of(douyin_source(enabled=False))
        detected = auto_collect.detect_added_bridge_sources(previous, current)
        self.assertFalse(auto_collect.has_pending_work(detected))

    def test_renamed_source_does_not_trigger(self):
        previous = config_of(douyin_source(name="旧名字"))
        current = config_of(douyin_source(name="新名字"))
        detected = auto_collect.detect_added_bridge_sources(previous, current)
        self.assertFalse(auto_collect.has_pending_work(detected))

    def test_reenabled_source_counts_as_added(self):
        # 停用期间历史可能已被清理，重新启用需要重新采一次。
        previous = config_of(douyin_source(enabled=False))
        current = config_of(douyin_source(enabled=True))
        detected = auto_collect.detect_added_bridge_sources(previous, current)
        self.assertEqual(detected["douyin_sec_uids"], [DOUYIN_SEC_UID])

    def test_missing_previous_config_never_triggers(self):
        # 首次写入时 previous 为空，不能把存量源全当成新增。
        detected = auto_collect.detect_added_bridge_sources(None, config_of(douyin_source()))
        self.assertFalse(auto_collect.has_pending_work(detected))

    def test_unparsable_locator_is_skipped(self):
        previous = config_of()
        broken = douyin_source()
        broken["locator"] = "not-a-url"
        detected = auto_collect.detect_added_bridge_sources(previous, config_of(broken))
        self.assertEqual(detected["douyin_sec_uids"], [])

    def test_non_bridge_source_does_not_trigger(self):
        previous = config_of()
        detected = auto_collect.detect_added_bridge_sources(previous, config_of(bilibili_source()))
        self.assertFalse(auto_collect.has_pending_work(detected))

    def test_parse_douyin_sec_uid(self):
        self.assertEqual(
            auto_collect.parse_douyin_sec_uid(f"https://www.douyin.com/user/{DOUYIN_SEC_UID}"),
            DOUYIN_SEC_UID,
        )
        self.assertEqual(auto_collect.parse_douyin_sec_uid(""), "")
        self.assertEqual(auto_collect.parse_douyin_sec_uid(None), "")
        self.assertEqual(auto_collect.parse_douyin_sec_uid("https://example.com/foo"), "")


def completed(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(args=["schtasks"], returncode=returncode, stdout=stdout, stderr=stderr)


class DispatchTriggerTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_command_triggers_the_scheduled_task(self):
        command = auto_collect.build_collect_task_command("DouyinCollectAndPush")
        self.assertEqual(command, ["schtasks", "/run", "/tn", "DouyinCollectAndPush"])

    def test_task_name_defaults_and_can_be_overridden(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(auto_collect.COLLECT_TASK_ENV, None)
            self.assertEqual(auto_collect.collect_task_name(), auto_collect.DEFAULT_COLLECT_TASK)
        with patch.dict(os.environ, {auto_collect.COLLECT_TASK_ENV: "OtherTask"}):
            self.assertEqual(auto_collect.collect_task_name(), "OtherTask")

    def test_single_trigger_covers_both_channels(self):
        # 计划任务只跑抖音；即使同时检测到微信新增，也只触发这一次任务。
        detected = {"douyin_sec_uids": [DOUYIN_SEC_UID], "wechat_added": True, "added_names": ["A", "B"]}
        with patch.object(auto_collect, "_trigger", return_value=completed()) as trigger:
            result = auto_collect.dispatch_bridge_collect(self.root, detected, execute=True, watch=False)
        self.assertEqual(trigger.call_count, 1)
        self.assertTrue(result["triggered"])

    def test_execute_false_does_not_trigger(self):
        detected = {"douyin_sec_uids": [DOUYIN_SEC_UID], "wechat_added": False, "added_names": []}
        with patch.object(auto_collect, "_trigger") as trigger:
            result = auto_collect.dispatch_bridge_collect(self.root, detected, execute=False)
        trigger.assert_not_called()
        self.assertFalse(result["triggered"])
        self.assertEqual(result["command"][:3], ["schtasks", "/run", "/tn"])

    def test_no_work_does_not_trigger(self):
        detected = {"douyin_sec_uids": [], "wechat_added": False, "added_names": []}
        with patch.object(auto_collect, "_trigger") as trigger:
            result = auto_collect.dispatch_bridge_collect(self.root, detected, execute=True, watch=False)
        trigger.assert_not_called()
        self.assertFalse(result["triggered"])

    def test_busy_task_is_recorded_without_retry(self):
        # 任务已在运行时 schtasks 返回非零：记录即可，不重试（那轮同样会采到新源）。
        detected = {"douyin_sec_uids": [DOUYIN_SEC_UID], "wechat_added": False, "added_names": []}
        with patch.object(auto_collect, "_trigger", return_value=completed(1, stderr="already running")) as trigger:
            result = auto_collect.dispatch_bridge_collect(self.root, detected, execute=True, watch=False)
        self.assertEqual(trigger.call_count, 1)
        self.assertFalse(result["triggered"])
        self.assertIn("already running", result["error"])

    def test_trigger_exception_is_swallowed(self):
        detected = {"douyin_sec_uids": [DOUYIN_SEC_UID], "wechat_added": False, "added_names": []}
        with patch.object(auto_collect, "_trigger", side_effect=OSError("schtasks missing")):
            result = auto_collect.dispatch_bridge_collect(self.root, detected, execute=True, watch=False)
        self.assertFalse(result["triggered"])
        self.assertIn("schtasks missing", result["error"])

    def test_status_file_written_under_logs_with_reason(self):
        detected = {
            "douyin_sec_uids": [DOUYIN_SEC_UID],
            "wechat_added": False,
            "added_names": ["新博主"],
        }
        with patch.object(auto_collect, "_trigger", return_value=completed()):
            auto_collect.dispatch_bridge_collect(self.root, detected, execute=True, watch=False)
        path = auto_collect.status_path(self.root)
        self.assertTrue(path.exists())
        self.assertEqual(path.parent.name, "logs")
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(len(payload["runs"]), 1)
        self.assertTrue(payload["runs"][0]["ok"])
        self.assertEqual(payload["runs"][0]["reason"]["added_names"], ["新博主"])

    def test_watcher_started_only_when_trigger_succeeded(self):
        detected = {"douyin_sec_uids": [DOUYIN_SEC_UID], "wechat_added": False, "added_names": ["新博主"]}
        with patch.object(auto_collect, "_trigger", return_value=completed()), \
                patch.object(auto_collect, "start_refresh_watcher") as watcher:
            result = auto_collect.dispatch_bridge_collect(self.root, detected, execute=True, watch=True)
        watcher.assert_called_once()
        # 看门人拿到的必须是触发原因，后面要写进标记文件供追溯。
        self.assertEqual(watcher.call_args[0][1]["added_names"], ["新博主"])
        self.assertTrue(result["watching"])

    def test_watcher_not_started_when_task_was_busy(self):
        detected = {"douyin_sec_uids": [DOUYIN_SEC_UID], "wechat_added": False, "added_names": []}
        with patch.object(auto_collect, "_trigger", return_value=completed(1, stderr="already running")), \
                patch.object(auto_collect, "start_refresh_watcher") as watcher:
            auto_collect.dispatch_bridge_collect(self.root, detected, execute=True, watch=True)
        watcher.assert_not_called()

    def test_watcher_failure_does_not_break_dispatch(self):
        detected = {"douyin_sec_uids": [DOUYIN_SEC_UID], "wechat_added": False, "added_names": []}
        with patch.object(auto_collect, "_trigger", return_value=completed()), \
                patch.object(auto_collect, "start_refresh_watcher", side_effect=RuntimeError("no thread")):
            result = auto_collect.dispatch_bridge_collect(self.root, detected, execute=True, watch=True)
        # 采集已经触发成功，看门人起不来不能反过来判它失败。
        self.assertTrue(result["triggered"])
        self.assertFalse(result["watching"])
        self.assertIn("no thread", result["watch_error"])

    def test_status_history_is_capped(self):
        detected = {"douyin_sec_uids": [DOUYIN_SEC_UID], "wechat_added": False, "added_names": []}
        with patch.object(auto_collect, "_trigger", return_value=completed()):
            for _ in range(auto_collect.STATUS_HISTORY_LIMIT + 5):
                auto_collect.dispatch_bridge_collect(self.root, detected, execute=True, watch=False)
        payload = json.loads(auto_collect.status_path(self.root).read_text(encoding="utf-8"))
        self.assertEqual(len(payload["runs"]), auto_collect.STATUS_HISTORY_LIMIT)


class PendingCollectTests(unittest.TestCase):
    """保存只登记、同步才派发——防止采集拖慢紧随其后的 git push。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        auto_collect.take_pending_collect()  # 清空跨用例残留
        self.addCleanup(auto_collect.take_pending_collect)
        self.addCleanup(self._tmp.cleanup)

    def test_save_registers_without_dispatching(self):
        previous = config_of()
        current = config_of(douyin_source())
        with patch.object(auto_collect, "dispatch_bridge_collect") as dispatch:
            result = auto_collect.handle_saved_config(self.root, previous, current)
        dispatch.assert_not_called()
        self.assertTrue(result["pending"])

    def test_no_added_source_registers_nothing(self):
        previous = config_of(douyin_source())
        current = config_of(douyin_source())
        result = auto_collect.handle_saved_config(self.root, previous, current)
        self.assertFalse(result["pending"])
        self.assertIsNone(auto_collect.take_pending_collect())

    def test_flush_dispatches_registered_work(self):
        auto_collect.handle_saved_config(self.root, config_of(), config_of(douyin_source()))
        with patch.object(auto_collect, "dispatch_bridge_collect", return_value={"triggered": True}) as dispatch:
            result = auto_collect.flush_pending_collect(self.root)
        dispatch.assert_called_once()
        self.assertEqual(dispatch.call_args[0][1]["douyin_sec_uids"], [DOUYIN_SEC_UID])
        self.assertTrue(result["triggered"])

    def test_flush_without_registration_does_nothing(self):
        with patch.object(auto_collect, "dispatch_bridge_collect") as dispatch:
            result = auto_collect.flush_pending_collect(self.root)
        dispatch.assert_not_called()
        self.assertFalse(result["triggered"])

    def test_flush_clears_registration_so_next_sync_is_idle(self):
        auto_collect.handle_saved_config(self.root, config_of(), config_of(douyin_source()))
        with patch.object(auto_collect, "dispatch_bridge_collect", return_value={"triggered": True}):
            auto_collect.flush_pending_collect(self.root)
        with patch.object(auto_collect, "dispatch_bridge_collect") as dispatch:
            auto_collect.flush_pending_collect(self.root)
        dispatch.assert_not_called()

    def test_multiple_saves_merge_into_one_dispatch(self):
        # 连续加两个源再同步一次：合并成一轮采集，不重复触发。
        auto_collect.handle_saved_config(self.root, config_of(), config_of(douyin_source()))
        auto_collect.handle_saved_config(
            self.root,
            config_of(douyin_source()),
            config_of(douyin_source(), wechat_source()),
        )
        with patch.object(auto_collect, "dispatch_bridge_collect", return_value={"triggered": True}) as dispatch:
            auto_collect.flush_pending_collect(self.root)
        dispatch.assert_called_once()
        merged = dispatch.call_args[0][1]
        self.assertEqual(merged["douyin_sec_uids"], [DOUYIN_SEC_UID])
        self.assertFalse(merged["wechat_added"])


class SaveHookIsolationTests(unittest.TestCase):
    """钩子挂在保存流程上，但绝不允许影响保存本身。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "data").mkdir(parents=True, exist_ok=True)
        self.addCleanup(self._tmp.cleanup)

    def test_hook_failure_does_not_break_save(self):
        from scripts.local_server import save_online_source_config
        from scripts.radar.server.online_sources import write_online_source_config

        sources = [{"name": "张三", "type": "bilibili_dynamic", "locator": "111"}]
        write_online_source_config(self.root, {"sources": sources})
        new_sources = sources + [
            {
                "name": "新博主",
                "type": auto_collect.DOUYIN_SOURCE_TYPE,
                "locator": f"https://www.douyin.com/user/{DOUYIN_SEC_UID}",
            }
        ]

        with patch(
            "scripts.local_server._auto_collect_api.handle_saved_config",
            side_effect=RuntimeError("boom"),
        ):
            result = save_online_source_config(self.root, {"sources": new_sources})

        # 保存必须照常成功，异常只体现在 auto_collect 字段里。
        self.assertEqual(len(result["config"]["sources"]), 2)
        self.assertFalse(result["auto_collect"]["pending"])
        self.assertIn("boom", result["auto_collect"]["error"])

    def test_hook_receives_previous_and_current_config(self):
        from scripts.local_server import save_online_source_config
        from scripts.radar.server.online_sources import write_online_source_config

        sources = [{"name": "张三", "type": "bilibili_dynamic", "locator": "111"}]
        write_online_source_config(self.root, {"sources": sources})
        new_sources = sources + [
            {
                "name": "新博主",
                "type": auto_collect.DOUYIN_SOURCE_TYPE,
                "locator": f"https://www.douyin.com/user/{DOUYIN_SEC_UID}",
            }
        ]

        with patch(
            "scripts.local_server._auto_collect_api.handle_saved_config",
            return_value={"triggered": True, "jobs": []},
        ) as hook:
            save_online_source_config(self.root, {"sources": new_sources})

        hook.assert_called_once()
        _root, previous_config, current_config = hook.call_args[0]
        previous_types = {source["type"] for source in previous_config["sources"]}
        current_types = {source["type"] for source in current_config["sources"]}
        self.assertNotIn(auto_collect.DOUYIN_SOURCE_TYPE, previous_types)
        self.assertIn(auto_collect.DOUYIN_SOURCE_TYPE, current_types)


if __name__ == "__main__":
    unittest.main()
