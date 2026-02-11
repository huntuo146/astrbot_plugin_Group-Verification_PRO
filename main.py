import asyncio
import random
import re
from typing import Dict, Any, Tuple, List

from astrbot.api import logger
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register


@register(
    "qq_member_verify",
    "huotuo146",
    "QQ群成员动态验证插件 PRO",
    "2.1.1",
    "https://github.com/huntuo146/astrbot_plugin_Group-Verification_PRO"
)
class QQGroupVerifyPlugin(Star):
    def __init__(self, context: Context, config: Dict[str, Any]):
        super().__init__(context)
        self.context = context

        # --- 分群启用配置 ---
        raw_groups = config.get("enabled_groups", [])
        # 兼容处理：确保群号是字符串列表
        self.enabled_groups: List[str] = [str(g) for g in raw_groups] if raw_groups else []

        # --- 时间控制 ---
        self.verification_timeout = config.get("verification_timeout", 300)
        self.kick_countdown_warning_time = config.get("kick_countdown_warning_time", 60)
        self.kick_delay = config.get("kick_delay", 5)

        # --- 自定义消息模板 ---
        self.new_member_prompt = config.get(
            "new_member_prompt",
            "{at_user} 欢迎加入本群！请在 {timeout} 分钟内 @我 并回答下面的问题以完成验证：\n{question}"
        )
        self.welcome_message = config.get(
            "welcome_message",
            "{at_user} 验证成功，欢迎你的加入！"
        )
        self.wrong_answer_prompt = config.get(
            "wrong_answer_prompt",
            "{at_user} 答案错误，请重新回答验证。这是你的新问题：\n{question}"
        )
        self.countdown_warning_prompt = config.get(
            "countdown_warning_prompt",
            "{at_user} 验证即将超时，请尽快查看我的验证消息进行人机验证！"
        )
        self.failure_message = config.get(
            "failure_message",
            "{at_user} 验证超时，你将在 {countdown} 秒后被请出本群。"
        )
        self.kick_message = config.get(
            "kick_message",
            "{at_user} 因未在规定时间内完成验证，已被请出本群。"
        )

        # 待处理的验证: { "user_id": {"gid": group_id, "answer": correct_answer, "task": asyncio.Task} }
        self.pending: Dict[str, Dict[str, Any]] = {}

    def _is_group_enabled(self, gid: int) -> bool:
        """检查该群是否开启了验证功能"""
        if not self.enabled_groups:
            return True
        return str(gid) in self.enabled_groups

    def _generate_math_problem(self) -> Tuple[str, int]:
        """生成一个100以内的加减法问题"""
        op_type = random.choice(['add', 'sub'])
        if op_type == 'add':
            num1 = random.randint(0, 100)
            num2 = random.randint(0, 100 - num1)
            answer = num1 + num2
            question = f"{num1} + {num2} = ?"
            return question, answer
        else:  # 'sub'
            num1 = random.randint(1, 100)
            num2 = random.randint(0, num1)
            answer = num1 - num2
            question = f"{num1} - {num2} = ?"
            return question, answer

    # 这里移除了 strict 过滤，改用内部判断，防止漏掉 notice 事件
    @filter.event_message_type(filter.EventMessageType.ALL) 
    async def handle_event(self, event: AstrMessageEvent):
        # 1. 平台校验
        if event.get_platform_name() != "aiocqhttp":
            return

        # 2. 安全校验 (修复报错的核心部分)
        # 某些事件可能没有 message_obj 或 raw_message，必须判空
        if not event.message_obj or not event.message_obj.raw_message:
            return
        
        raw = event.message_obj.raw_message
        
        # 确保 raw 是字典类型，防止后续 .get() 报错
        if not isinstance(raw, dict):
            return

        post_type = raw.get("post_type")
        gid = raw.get("group_id")
        
        # 3. 处理入群/退群通知
        if post_type == "notice":
            notice_type = raw.get("notice_type")
            
            if notice_type == "group_increase":
                # 入群验证
                if gid and not self._is_group_enabled(gid):
                    return 
                # 排除机器人自己进群的情况
                if str(raw.get("user_id")) == str(event.get_self_id()):
                    return
                await self._process_new_member(event)
                
            elif notice_type == "group_decrease":
                # 退群清理
                await self._process_member_decrease(event)
        
        # 4. 处理群消息（验证答案）
        elif post_type == "message" and raw.get("message_type") == "group":
            if gid and not self._is_group_enabled(gid):
                return
            await self._process_verification_message(event)

    async def _process_new_member(self, event: AstrMessageEvent):
        """处理新成员入群"""
        raw = event.message_obj.raw_message
        uid = str(raw.get("user_id"))
        gid = raw.get("group_id")
        
        await self._start_verification_process(event, uid, gid, is_new_member=True)

    async def _start_verification_process(self, event: AstrMessageEvent, uid: str, gid: int, is_new_member: bool):
        """为用户启动或重启验证流程"""
        # 清理旧任务
        if uid in self.pending:
            old_task = self.pending[uid].get("task")
            if old_task and not old_task.done():
                old_task.cancel()

        question, answer = self._generate_math_problem()
        logger.info(f"[QQ Verify] 为用户 {uid} 在群 {gid} 生成验证问题: {question} (答案: {answer})")

        nickname = uid
        try:
            # 尝试获取最新昵称
            user_info = await event.bot.api.call_action("get_group_member_info", group_id=gid, user_id=int(uid))
            nickname = user_info.get("card", "") or user_info.get("nickname", uid)
        except Exception as e:
            logger.warning(f"[QQ Verify] 获取用户 {uid} 昵称失败: {e}")

        # 启动超时踢出任务
        task = asyncio.create_task(self._timeout_kick(uid, gid, nickname))
        self.pending[uid] = {"gid": gid, "answer": answer, "task": task}

        at_user = f"[CQ:at,qq={uid}]"
        
        if is_new_member:
            prompt_message = self.new_member_prompt.format(
                at_user=at_user,
                member_name=nickname,
                question=question,
                timeout=self.verification_timeout // 60
            )
        else:
            prompt_message = self.wrong_answer_prompt.format(
                at_user=at_user,
                question=question
            )

        await event.bot.api.call_action("send_group_msg", group_id=gid, message=prompt_message)

    async def _process_verification_message(self, event: AstrMessageEvent):
        """处理群消息以进行验证"""
        uid = str(event.get_sender_id())
        
        # 如果该用户不在待验证列表中，直接忽略
        if uid not in self.pending:
            return
        
        text = event.message_str.strip()
        raw = event.message_obj.raw_message
        gid = self.pending[uid]["gid"]
        
        # 校验群号
        current_gid = raw.get("group_id")
        if current_gid and str(current_gid) != str(gid):
            return

        # 校验是否 @机器人
        bot_id = str(event.get_self_id())
        # 解析消息段中的 @
        at_me = False
        if isinstance(raw.get("message"), list):
            for seg in raw.get("message"):
                if seg.get("type") == "at" and str(seg.get("data", {}).get("qq")) == bot_id:
                    at_me = True
                    break
        
        if not at_me:
            return
        
        try:
            # 提取消息中的最后一个数字作为答案（兼容 "答案是15" 这种格式）
            matches = re.findall(r'(\d+)', text)
            if not matches:
                return
            user_answer = int(matches[-1]) 
        except (ValueError, TypeError):
            return

        correct_answer = self.pending[uid].get("answer")

        if user_answer == correct_answer:
            # --- 验证成功 ---
            logger.info(f"[QQ Verify] 用户 {uid} 在群 {gid} 验证成功。")
            if uid in self.pending:
                self.pending[uid]["task"].cancel()
                self.pending.pop(uid, None)

            nickname = raw.get("sender", {}).get("card", "") or raw.get("sender", {}).get("nickname", uid)
            welcome_msg = self.welcome_message.format(at_user=f"[CQ:at,qq={uid}]", member_name=nickname)
            await event.bot.api.call_action("send_group_msg", group_id=gid, message=welcome_msg)
            event.stop_event()
        else:
            # --- 验证失败，重试 ---
            logger.info(f"[QQ Verify] 用户 {uid} 在群 {gid} 回答错误。重新生成问题。")
            await self._start_verification_process(event, uid, gid, is_new_member=False)
            event.stop_event()

    async def _process_member_decrease(self, event: AstrMessageEvent):
        """处理成员离开"""
        raw = event.message_obj.raw_message
        uid = str(raw.get("user_id"))
        if uid in self.pending:
            self.pending[uid]["task"].cancel()
            self.pending.pop(uid, None)
            logger.info(f"[QQ Verify] 待验证用户 {uid} 已离开，清理其验证状态。")

    async def _timeout_kick(self, uid: str, gid: int, nickname: str):
        """处理超时、警告和踢出的协程"""
        try:
            # 等待警告时间
            wait_before_warning = self.verification_timeout - self.kick_countdown_warning_time
            if wait_before_warning > 0:
                await asyncio.sleep(wait_before_warning)

            if uid not in self.pending: return

            bot = self.context.get_platform("aiocqhttp").get_client()
            at_user = f"[CQ:at,qq={uid}]"
            
            # 发送超时警告
            if self.kick_countdown_warning_time > 0:
                warning_msg = self.countdown_warning_prompt.format(at_user=at_user, member_name=nickname)
                try:
                    await bot.api.call_action("send_group_msg", group_id=gid, message=warning_msg)
                except Exception as e:
                    logger.warning(f"[QQ Verify] 发送超时警告失败: {e}")
                
                # 等待剩余时间
                await asyncio.sleep(self.kick_countdown_warning_time)

            if uid not in self.pending: return

            # --- 验证最终超时 ---
            failure_msg = self.failure_message.format(at_user=at_user, member_name=nickname, countdown=self.kick_delay)
            try:
                await bot.api.call_action("send_group_msg", group_id=gid, message=failure_msg)
            except Exception:
                pass
            
            await asyncio.sleep(self.kick_delay)

            if uid not in self.pending: return # 最终检查
            
            # 执行踢人
            try:
                await bot.api.call_action("set_group_kick", group_id=gid, user_id=int(uid), reject_add_request=False)
                logger.info(f"[QQ Verify] 用户 {uid} ({nickname}) 验证超时，已从群 {gid} 踢出。")
                
                kick_msg = self.kick_message.format(at_user=at_user, member_name=nickname)
                await bot.api.call_action("send_group_msg", group_id=gid, message=kick_msg)
            except Exception as e:
                logger.error(f"[QQ Verify] 踢人失败 (权限不足?): {e}")

        except asyncio.CancelledError:
            # 任务被取消（验证成功或用户退群）
            pass
        except Exception as e:
            logger.error(f"[QQ Verify] 踢出流程发生未知错误 (用户 {uid}): {e}")
        finally:
            # 确保清理
            if uid in self.pending:
                self.pending.pop(uid, None)
