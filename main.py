import asyncio
import random
import re
from typing import Any, Dict, List, Tuple

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star


class QQGroupVerifyPlugin(Star):
    """QQ 群成员入群动态验证插件"""

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)

        # --- 分群启用配置 ---
        raw_groups = config.get("enabled_groups", [])
        self.enabled_groups: List[str] = [str(g) for g in raw_groups] if raw_groups else []

        # --- 重试上限 ---
        self.max_retries: int = config.get("max_retries", 3)

        # --- 时间控制 ---
        self.verification_timeout: int = config.get("verification_timeout", 300)
        self.kick_countdown_warning_time: int = config.get("kick_countdown_warning_time", 60)
        self.kick_delay: int = config.get("kick_delay", 5)

        # --- 自定义消息模板 ---
        self.new_member_prompt: str = config.get(
            "new_member_prompt",
            "{at_user} 欢迎加入本群！请在 {timeout} 分钟内 @我 并回答下面的问题以完成验证：\n{question}",
        )
        self.welcome_message: str = config.get(
            "welcome_message",
            "{at_user} 验证成功，欢迎你的加入！",
        )
        self.wrong_answer_prompt: str = config.get(
            "wrong_answer_prompt",
            "{at_user} 答案错误，请重新回答验证。这是你的新问题：\n{question}",
        )
        self.countdown_warning_prompt: str = config.get(
            "countdown_warning_prompt",
            "{at_user} 验证即将超时，请尽快查看我（BOT）的验证消息进行人机验证！",
        )
        self.failure_message: str = config.get(
            "failure_message",
            "{at_user} 验证超时，你将在 {countdown} 秒后被请出本群。",
        )
        self.kick_message: str = config.get(
            "kick_message",
            "{at_user} 因未在规定时间内完成验证，已被请出本群。",
        )

        # 待验证状态: key = "uid_gid"
        # value = {"gid": int, "uid": str, "answer": int, "retries": int, "task": Task, "bot": bot}
        self.pending: Dict[str, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    async def terminate(self):
        """插件卸载/停用时取消所有待验证任务"""
        async with self._lock:
            for key, info in self.pending.items():
                task = info.get("task")
                if task and not task.done():
                    task.cancel()
            self.pending.clear()
        logger.info("[QQ Verify] 插件已卸载，所有验证任务已清理。")

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------

    @staticmethod
    def _make_pending_key(uid: str, gid: int) -> str:
        return f"{uid}_{gid}"

    def _is_group_enabled(self, gid: int) -> bool:
        """检查该群是否开启了验证功能"""
        if not self.enabled_groups:
            return True
        return str(gid) in self.enabled_groups

    @staticmethod
    def _generate_math_problem() -> Tuple[str, int]:
        """生成一个 100 以内的加减法问题"""
        op_type = random.choice(["add", "sub"])
        if op_type == "add":
            num1 = random.randint(0, 100)
            num2 = random.randint(0, 100 - num1)
            answer = num1 + num2
            question = f"{num1} + {num2} = ?"
        else:
            num1 = random.randint(1, 100)
            num2 = random.randint(0, num1)
            answer = num1 - num2
            question = f"{num1} - {num2} = ?"
        return question, answer

    # ------------------------------------------------------------------
    # 事件入口
    # ------------------------------------------------------------------

    @filter.platform_adapter_type(filter.PlatformAdapterType.AIOCQHTTP)
    @filter.event_message_type(filter.EventMessageType.ALL)
    async def handle_event(self, event: AstrMessageEvent):
        """监听 aiocqhttp 平台的所有事件，分发到入群/退群/验证消息处理"""
        if not event.message_obj or not event.message_obj.raw_message:
            return
        raw = event.message_obj.raw_message
        if not isinstance(raw, dict):
            return

        post_type = raw.get("post_type")
        gid = raw.get("group_id")

        if post_type == "notice":
            notice_type = raw.get("notice_type")
            if notice_type == "group_increase":
                if gid and not self._is_group_enabled(gid):
                    return
                # 排除机器人自己入群
                if str(raw.get("user_id")) == str(event.get_self_id()):
                    return
                await self._on_member_join(event)
                event.stop_event()
            elif notice_type == "group_decrease":
                await self._on_member_leave(event)
                event.stop_event()

        elif post_type == "message" and raw.get("message_type") == "group":
            if gid and not self._is_group_enabled(gid):
                return
            await self._on_group_message(event)

    # ------------------------------------------------------------------
    # 入群处理
    # ------------------------------------------------------------------

    async def _on_member_join(self, event: AstrMessageEvent):
        """新成员入群，启动验证"""
        raw = event.message_obj.raw_message
        uid = str(raw.get("user_id"))
        gid = raw.get("group_id")
        await self._start_verification(event, uid, gid, is_new=True)

    # ------------------------------------------------------------------
    # 退群处理
    # ------------------------------------------------------------------

    async def _on_member_leave(self, event: AstrMessageEvent):
        """成员离开，清理验证状态"""
        raw = event.message_obj.raw_message
        uid = str(raw.get("user_id"))
        gid = raw.get("group_id")
        key = self._make_pending_key(uid, gid)

        async with self._lock:
            info = self.pending.pop(key, None)
        if info:
            task = info.get("task")
            if task and not task.done():
                task.cancel()
            logger.info(f"[QQ Verify] 待验证用户 {uid} 已离开群 {gid}，清理验证状态。")

    # ------------------------------------------------------------------
    # 验证消息处理
    # ------------------------------------------------------------------

    async def _on_group_message(self, event: AstrMessageEvent):
        """处理群消息，判断是否为验证回答"""
        uid = str(event.get_sender_id())
        raw = event.message_obj.raw_message
        gid = raw.get("group_id")
        key = self._make_pending_key(uid, gid)

        async with self._lock:
            info = self.pending.get(key)
        if not info:
            return

        # 校验是否 @机器人
        bot_id = str(event.get_self_id())
        at_me = False
        msg_segments = raw.get("message", [])
        if isinstance(msg_segments, list):
            for seg in msg_segments:
                if seg.get("type") == "at" and str(seg.get("data", {}).get("qq")) == bot_id:
                    at_me = True
                    break
        if not at_me:
            return

        # 提取数字答案
        text = event.message_str.strip()
        matches = re.findall(r"-?\d+", text)
        if not matches:
            return
        try:
            user_answer = int(matches[-1])
        except (ValueError, TypeError):
            return

        correct_answer = info.get("answer")

        if user_answer == correct_answer:
            # 验证成功
            async with self._lock:
                removed = self.pending.pop(key, None)
            if removed:
                task = removed.get("task")
                if task and not task.done():
                    task.cancel()

            logger.info(f"[QQ Verify] 用户 {uid} 在群 {gid} 验证成功。")
            nickname = raw.get("sender", {}).get("card", "") or raw.get("sender", {}).get("nickname", uid)
            at_user = f"[CQ:at,qq={uid}]"
            welcome_msg = self.welcome_message.format(at_user=at_user, member_name=nickname)
            bot = info.get("bot", event.bot)
            await bot.api.call_action("send_group_msg", group_id=gid, message=welcome_msg)
            event.stop_event()
        else:
            # 验证失败
            async with self._lock:
                info["retries"] = info.get("retries", 0) + 1
                retries = info["retries"]

            if self.max_retries > 0 and retries >= self.max_retries:
                # 超过重试上限，直接踢出
                async with self._lock:
                    removed = self.pending.pop(key, None)
                if removed:
                    task = removed.get("task")
                    if task and not task.done():
                        task.cancel()

                logger.info(f"[QQ Verify] 用户 {uid} 在群 {gid} 答错超过 {self.max_retries} 次，执行踢出。")
                bot = info.get("bot", event.bot)
                at_user = f"[CQ:at,qq={uid}]"
                try:
                    await bot.api.call_action(
                        "send_group_msg",
                        group_id=gid,
                        message=f"{at_user} 答错次数过多，你将被请出本群。",
                    )
                    await asyncio.sleep(self.kick_delay)
                    await bot.api.call_action(
                        "set_group_kick", group_id=gid, user_id=int(uid), reject_add_request=False
                    )
                except Exception as e:
                    logger.error(f"[QQ Verify] 重试上限踢人失败: {e}")
            else:
                # 重新出题
                logger.info(f"[QQ Verify] 用户 {uid} 在群 {gid} 回答错误 (第 {retries} 次)，重新出题。")
                await self._start_verification(event, uid, gid, is_new=False)

            event.stop_event()

    # ------------------------------------------------------------------
    # 验证流程核心
    # ------------------------------------------------------------------

    async def _start_verification(self, event: AstrMessageEvent, uid: str, gid: int, is_new: bool):
        """为用户启动或重启验证流程"""
        key = self._make_pending_key(uid, gid)

        # 清理旧任务（仅新入群时清理，答错重试时保留计时）
        if is_new:
            async with self._lock:
                old_info = self.pending.pop(key, None)
            if old_info:
                old_task = old_info.get("task")
                if old_task and not old_task.done():
                    old_task.cancel()

        question, answer = self._generate_math_problem()
        logger.info(f"[QQ Verify] 为用户 {uid} 在群 {gid} 生成验证: {question} (答案: {answer})")

        # 获取昵称
        nickname = uid
        bot = event.bot
        try:
            user_info = await bot.api.call_action(
                "get_group_member_info", group_id=gid, user_id=int(uid)
            )
            nickname = user_info.get("card", "") or user_info.get("nickname", uid)
        except Exception as e:
            logger.warning(f"[QQ Verify] 获取用户 {uid} 昵称失败: {e}")

        at_user = f"[CQ:at,qq={uid}]"

        if is_new:
            # 新入群：启动超时任务
            task = asyncio.create_task(self._timeout_kick(key, uid, gid, nickname, bot))
            async with self._lock:
                self.pending[key] = {
                    "gid": gid,
                    "uid": uid,
                    "answer": answer,
                    "retries": 0,
                    "task": task,
                    "bot": bot,
                }
            prompt = self.new_member_prompt.format(
                at_user=at_user,
                member_name=nickname,
                question=question,
                timeout=self.verification_timeout // 60,
            )
        else:
            # 答错重试：只更新答案，保留原有超时任务
            async with self._lock:
                if key in self.pending:
                    self.pending[key]["answer"] = answer
            prompt = self.wrong_answer_prompt.format(at_user=at_user, question=question)

        await bot.api.call_action("send_group_msg", group_id=gid, message=prompt)

    # ------------------------------------------------------------------
    # 超时踢出协程
    # ------------------------------------------------------------------

    async def _timeout_kick(self, key: str, uid: str, gid: int, nickname: str, bot):
        """超时后警告并踢出用户"""
        try:
            # 等待到警告时间点
            wait_before_warning = self.verification_timeout - self.kick_countdown_warning_time
            if wait_before_warning > 0:
                await asyncio.sleep(wait_before_warning)

            async with self._lock:
                if key not in self.pending:
                    return

            at_user = f"[CQ:at,qq={uid}]"

            # 发送超时警告
            if self.kick_countdown_warning_time > 0:
                warning_msg = self.countdown_warning_prompt.format(at_user=at_user, member_name=nickname)
                try:
                    await bot.api.call_action("send_group_msg", group_id=gid, message=warning_msg)
                except Exception as e:
                    logger.warning(f"[QQ Verify] 发送超时警告失败: {e}")

                await asyncio.sleep(self.kick_countdown_warning_time)

            async with self._lock:
                if key not in self.pending:
                    return

            # 验证超时通知
            failure_msg = self.failure_message.format(
                at_user=at_user, member_name=nickname, countdown=self.kick_delay
            )
            try:
                await bot.api.call_action("send_group_msg", group_id=gid, message=failure_msg)
            except Exception:
                pass

            await asyncio.sleep(self.kick_delay)

            async with self._lock:
                if key not in self.pending:
                    return

            # 执行踢人
            try:
                await bot.api.call_action(
                    "set_group_kick", group_id=gid, user_id=int(uid), reject_add_request=False
                )
                logger.info(f"[QQ Verify] 用户 {uid} ({nickname}) 验证超时，已从群 {gid} 踢出。")
                kick_msg = self.kick_message.format(at_user=at_user, member_name=nickname)
                await bot.api.call_action("send_group_msg", group_id=gid, message=kick_msg)
            except Exception as e:
                logger.error(f"[QQ Verify] 踢人失败 (权限不足?): {e}")

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[QQ Verify] 超时踢出流程异常 (用户 {uid}, 群 {gid}): {e}")
        finally:
            async with self._lock:
                self.pending.pop(key, None)
