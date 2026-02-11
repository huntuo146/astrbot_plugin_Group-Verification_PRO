# 🤖 QQ群成员动态数学题验证插件 PRO

<div align="center">
  
![Version](https://img.shields.io/badge/version-2.1.2-blue.svg)  
![License](https://img.shields.io/badge/license-AGPLv3-green.svg)  
![Platform](https://img.shields.io/badge/platform-AstrBot-purple.svg)  

一个智能、高度可定制的QQ群验证工具，通过动态数学题有效拦截机器人，保护您的群聊安宁  

[功能简介](#features) • [安装方法](#installation) • [配置说明](#configuration) • [使用教程](#usage) • [常见问题](#faq) • [更新日志](#changelog) • [作者及许可](#author)

</div>

---

<a id="features"></a>
## ✨ 功能简介

本插件为 AstrBot 提供了强大的新成员智能验证功能，能有效过滤广告机器人和可疑用户，全面提升群聊质量。

- 🧠 **动态数学题验证**：新成员需回答随机生成的 100 以内加减法问题，代替呆板的静态关键词，极大提升验证强度。
- 🏢 **分群启用 (White-list)**：支持指定特定群号开启验证，未在名单内的群组将不触发验证流程，更加灵活。
- 🔄 **错误重试机制**：回答错误后自动生成新题并重置计时，给予真实用户改正机会。
- ⏱️ **多段式时间控制**：自定义验证总时长、超时前警告时机、失败后踢出延迟等。
- 🎨 **完全可定制化消息**：欢迎语、错误提示、超时警告、踢出公告等均可自定义，支持丰富变量。
- 🔍 **实时监测**：自动检测新成员入群并立即发起验证流程。

---

<a id="installation"></a>
## 📥 安装方法

<details>
<summary>展开查看详细安装步骤</summary>

1. 打开 AstrBot 插件管理界面。  
2. 在插件市场搜索 `astrbot_plugin_Group-Verification_PRO` 并安装。  
3. 安装完成后，进入插件配置页面进行参数设置。  
4. 保存配置并重启机器人，或在插件管理中手动重载本插件。  

</details>

---

<a id="configuration"></a>
## ⚙️ 配置说明

### 配置项详情

| 配置项 | 类型 | 说明 |
| :--- | :--- | :--- |
| `enabled_groups` | list | **启用插件的群号列表**。留空则全局生效，否则仅对名单内的群生效。 |
| `verification_timeout` | int | 验证总超时时间（秒），默认 `300`。 |
| `kick_countdown_warning_time` | int | 超时前发送警告秒数，设为 `0` 可禁用，默认 `60`。 |
| `kick_delay` | int | 发送“验证超时”消息后延迟踢出秒数，默认 `5`。 |
| `new_member_prompt` | string | 新成员入群时发送的欢迎及验证提示语。 |
| `welcome_message` | string | 验证成功后的祝贺提示语。 |
| `wrong_answer_prompt` | string | 回答错误后的提示语（自动附带新题）。 |
| `failure_message` | string | 验证失败前的“最后通牒”消息。 |
| `kick_message` | string | 成员被踢出后在群内的公开通知。 |

### 支持的模板变量

- `{at_user}` — @目标用户 的 CQ 码
- `{member_name}` — 用户的群名片或 QQ 昵称
- `{question}` — 随机生成的数学题 (例如 `76 + 24 = ?`)
- `{timeout}` — 验证超时时长（分钟）
- `{countdown}` — 踢出前的延迟秒数

---

<a id="usage"></a>
## 📝 使用教程

1. **白名单设置**：在 `enabled_groups` 中填入需要开启验证的群号。若保持为空，则插件会对机器人加入的所有群组生效。
2. **验证流程**：新成员入群后，机器人会 @ 该成员并出题。成员需在规定时间内 @ 机器人并回复数字答案。
3. **容错机制**：如果成员回复错误，系统会提示错误并立即更换题目，重新开始计时，避免因手抖导致的误踢。
4. **清理逻辑**：如果成员在验证期间主动退群，系统会自动撤销验证任务，释放资源。

---

<a id="faq"></a>
## ❓ 常见问题

- **Q: 为什么输入正确答案没反应？** A: 请确保回复时 **@了机器人**。为了避免干扰日常聊天，插件仅识别 @ 机器人的验证消息。
- **Q: 机器人没有踢人权限？** A: 请确保机器人帐号拥有 **群管理员** 或 **群主** 权限。
- **Q: 如何彻底关闭某个群的验证？** A: 如果你设置了 `enabled_groups`，只需将该群号移出列表；如果列表为空，则需要在 AstrBot 插件管理中禁用本插件。

---

<a id="changelog"></a>
## 📋 更新日志

### ​v2.1.2 (2026-2-11）
​此版本重点解决了在复杂网络环境下或接收特殊事件时插件崩溃的问题。
# ​🐛 修复：解决了在处理非标准事件时，由于 raw_message 为空导致的 'NoneType' object has no attribute 'get' 严重报错。
# ​🔧 优化：将事件过滤器调整为 EventMessageType.ALL，确保能更稳健地捕获入群通知（Notice）事件。
# ​🛡️ 健壮性：增加了防御性编程检查，确保在数据异常或平台 API 调用失败时插件不会崩溃，并能记录错误日志。

### v2.1.0 - 2025-12-21
* [新增] **分群启用功能**：新增 `enabled_groups` 配置项，支持设置白名单模式。
* [优化] 完善数学题重试逻辑，确保每次回答错误后生成的题目具有随机性。
* [优化] 更新所有说明文档以匹配最新白名单逻辑。

### v1.0.4 - 2025-08-08
* [关键修复] 解决了因 `from astrbot.api.bot import Bot` 语句在部分版本中不兼容导致的 `ModuleNotFoundError` 问题。
* [兼容性] 移除特定导入和类型提示，确保在不同 AstrBot 版本中加载成功。

### v1.0.3 - 2025-08-07
* [修复] 修复了 `_timeout_kick` 函数中存在的不完整代码行导致的语法错误。

### v1.0.2 - 2025-08-07
* [健壮性] 重构消息格式化逻辑，即使模板缺少占位符（如 `{member_name}`）也不会导致插件崩溃。
* [优化] 升级答案提取算法，智能识别用户回复中的数字，提高识别准确率。
* [解耦] 移除平台硬编码，不再硬编码 `aiocqhttp` 平台，为未来适配其他 OneBot 实现打下基础。

### v1.0.1 - 2025-08-07
* [重大升级] 核心验证方式从静态关键词升级为 **100以内动态数学题验证**。
* [功能] 新增验证超时前警告、错误重试、自定义踢出延迟功能。
* [重构] 优化验证逻辑与状态管理，提升并发处理稳定性。

---

<a id="author"></a>
## 👤 作者及许可

- **作者**：huotuo146  
- 🌐 GitHub：[huntuo146](https://github.com/huntuo146)  
- 📧 Email：[2996603469@qq.com](mailto:2996603469@qq.com)  
- 🔗 项目地址：[astrbot_plugin_Group-Verification_PRO](https://github.com/huntuo146/astrbot_plugin_Group-Verification_PRO)  

本项目采用 [AGPLv3 许可证](LICENSE) 开源。

---

<div align="center">
<p>如果您觉得这个插件有用，请考虑给项目一个 ⭐Star！</p>
<sub>Made with ❤️ by huotuo146</sub>
</div>
