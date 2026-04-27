#!/usr/bin/env python3
# Chinese translations for missing keys
zh_trans = {
    # Providers
    "providers.nsfw": "NSFW",
    "providers.models_fetch_error": "❌ 错误: {error}",
    "providers.rate_limit_hint": "对此提供者的请求之间的延迟时间",
    "providers.kiro_auth_hint": "选择一个身份验证方法: Kiro IDE凭据(creds_file)、kiro-cli数据库(sqlite_db)或直接凭据(refresh_token + client_id/secret)。",
    "providers.kilo_auth_hint": "选择您的身份验证方法: API密钥(为简单起见推荐)或OAuth2设备授权许可。",
    "providers.workspace_id_hint": "德国地区的工作区ID(默认: \"Default Workspace\")",
    "providers.kiro_aws_region_hint": "Kiro API的AWS区域(默认: us-east-1)",
    "providers.kiro_sqlite_hint": "kiro-cli SQLite数据库路径",
    "providers.kiro_refresh_hint": "直接身份验证的Kiro刷新令牌",
    "providers.kiro_profile_arn_hint": "AWS CodeWhisperer配置文件ARN(可选)",
    "providers.kiro_client_id_hint": "AWS SSO OIDC身份验证的OAuth客户端ID",
    "providers.kiro_client_secret_hint": "AWS SSO OIDC身份验证的OAuth客户端密钥",
    "providers.kiro_upload_creds_hint": "上传Kiro IDE凭据JSON文件",
    "providers.kiro_upload_sqlite_hint": "上传kiro-cli SQLite数据库文件",
    "providers.provider_key_hint": "这将用作配置和API端点中的提供者ID。",
    "providers.subscription_based_hint": "如果选中，此提供者基于订阅，成本将计算为$0。使用情况仍将用于分析。",
    "providers.price_prompt_hint": "留空以使用默认价格。例如: OpenAI GPT-4: $10, Anthropic Claude: $15, Google Gemini: $1.25",
    "providers.price_completion_hint": "留空以使用默认价格。例如: OpenAI GPT-4: $30, Anthropic Claude: $75, Google Gemini: $5.00",
    "providers.native_caching_hint": "降低成本的本机缓存功能(Anthropic cache_control、Google Context Caching、OpenAI和兼容Kilo的API)。",
    "providers.enable_native_caching_hint": "启用本机提供者缓存以降低成本(支持提供者节省50-70%)。",
    
    # Rotations
    "rotations.copy_prompt": "复制 \"{key}\" — 输入新的轮换键:",
    "rotations.add_prompt": "输入轮换键(例如: \"coding\", \"general\"):",
    "rotations.remove_confirm": "删除轮换 \"{key}\"?",
    "rotations.remove_provider_confirm": "删除此提供者?",
    
    # Wallet
    "wallet_page.charged_to_card": "向您的默认信用卡扣款:",
    "wallet_page.invalid_amount": "请选择或输入{min}到{max}之间的金额。",
    "wallet_page.invalid_amount_title": "无效金额",
    
    # Rate Limits
    "rate_limits_page.reset_confirm": "重置{provider}的速率限制器?",
    "rate_limits_page.reset_confirm_title": "重置速率限制器",
    "rate_limits_page.reset_all_confirm": "重置所有速率限制器? 这将清除所有已学习的速率限制。",
    "rate_limits_page.reset_all_success": "所有速率限制器已成功重置",
    
    # Signup
    "signup_page.username_hint": "仅3-50个字符: 字母、数字、下划线、连字符和点",
    "signup_page.email_hint": "您将在该地址收到验证电子邮件",
    "signup_page.password_hint": "至少8个字符，包含大写字母、小写字母和数字",
    
    # Reset
    "reset_page.intro": "请在下面输入您的新密码。",
    "reset_page.password_hint": "必须至少8个字符长",
    "reset_page.success": "您的密码已成功重置。您现在可以使用新密码登录。",
    "reset_page.go_to_login": "前往登录",
    "reset_page.invalid_token": "此密码重置链接无效或已过期。请请求新的密码重置链接。",
    "reset_page.request_new": "请求新的重置链接",
    
    # Tokens
    "tokens_page.description_placeholder": "例如: 我的应用, 家庭服务器…",
    "tokens_page.scope_api_hint": "(代理请求)",
    "tokens_page.scope_mcp_hint": "(代理工具)",
    "tokens_page.auth_header_desc": "在{header}头中的每个请求中包含令牌:",
    "tokens_page.token_scopes": "令牌范围:",
    "tokens_page.scope_api_access": "仅代理API端点({path})",
    "tokens_page.scope_mcp_access": "仅MCP工具端点({path})",
    "tokens_page.scope_both_access": "API和MCP端点",
    "tokens_page.available_endpoints": "可用端点:",
    "tokens_page.col_endpoint": "端点",
    "tokens_page.example_commands": "curl命令示例:",
    "tokens_page.delete_confirm": "删除此API令牌? 这将立即撤销访问权限且无法撤消。",
    
    # Billing
    "billing_page.col_date": "日期",
    
    # User Overview
    "user_overview.higher_plans": "{n}个更高级的计划可用 — 更多请求, 更多提供者",
    "user_overview.upgrade_to": "升级到{name}，价格{price}/月",
    "user_overview.auth_header_desc": "在每个请求中{header}头包含您的API令牌:",
    "user_overview.ep_chat_desc": "使用您的配置发送聊天请求",
    "user_overview.admin_access_desc": "作为管理员，您还可以通过更短的模型格式访问全局配置:",
    "user_overview.token_required": "所有端点都需要您的API令牌。",
    
    # Usage
    "usage_page.activity_quotas_desc": "自动重置的基于时间的限制",
    "usage_page.config_limits_desc": "为您的账户分配持久性资源",
    "usage_page.resets_midnight": "UTC午夜重置",
    "usage_page.resets_in": "{h}小时{m}分钟后重置",
    "usage_page.resets_on_1st": "每月1日重置",
    "usage_page.resets_in_days": "{n}天后重置",
    "usage_page.resets_in_days_plural": "{n}天后重置",
    "usage_page.tokens_combined": "输入+输出总和",
    "usage_page.remaining": "剩余{n}",
    "usage_page.ai_providers_desc": "已配置的提供者集成",
    "usage_page.rotations_desc": "负载均衡配置",
    "usage_page.autoselections_desc": "智能路由配置",
    "usage_page.unlimited_slots": "无限槽位可用",
    "usage_page.pct_used_slots_free": "已使用{pct}% · {n}个槽位空闲",
    "usage_page.pct_used_slots_free_plural": "已使用{pct}% · {n}个槽位空闲",
    "usage_page.upgrade_desc": "升级您的计划以解锁更多请求、提供者和自动选择。",
    
    # Subscription
    "subscription_page.no_description": "无可用描述",
    "subscription_page.billing_payments_desc": "管理支付方法并查看历史记录",
    "subscription_page.upgrade_plan_desc": "查看所有可用计划",
    "subscription_page.edit_profile_desc": "更新帐户设置",
    "subscription_page.change_password_desc": "更新安全设置",
    "subscription_page.no_payment_methods_desc": "添加支付方式以升级您的计划和管理订阅。",
    "subscription_page.go_to_billing": "前往账单和支付方式",
}

print(f'Chinese translations: {len(zh_trans)} keys')

# Apply translations
import json

def apply(lang, translations):
    D = '/working/aisbf/static/i18n/'
    path = D + lang + '.json'
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    def set_nested(d, key, value):
        parts = key.split('.')
        c = d
        for p in parts[:-1]:
            c = c.setdefault(p, {})
        c[parts[-1]] = value
    for key, value in translations.items():
        set_nested(data, key, value)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f'Applied {len(translations)} translations for {lang}')

apply('zh', zh_trans)