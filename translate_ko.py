#!/usr/bin/env python3
# Korean translations for missing keys
ko_trans = {
    # Providers
    "providers.nsfw": "NSFW",
    "providers.models_fetch_error": "❌ 오류: {error}",
    "providers.rate_limit_hint": "이 공급자에 대한 요청 간 지연 시간",
    "providers.kiro_auth_hint": "인증 방법 선택: Kiro IDE 자격 증명(creds_file), kiro-cli 데이터베이스(sqlite_db), 또는 직접 자격 증명(refresh_token + client_id/secret).",
    "providers.kilo_auth_hint": "인증 방법 선택: API 키(단순함을 위해 권장) 또는 OAuth2 디바이스 권한 부여.",
    "providers.workspace_id_hint": "독일 리전용 작업 영역 ID(기본값: \"Default Workspace\")",
    "providers.kiro_aws_region_hint": "Kiro API용 AWS 리전(기본값: us-east-1)",
    "providers.kiro_sqlite_hint": "kiro-cli SQLite 데이터베이스 경로",
    "providers.kiro_refresh_hint": "직접 인증을 위한 Kiro 리프레시 토큰",
    "providers.kiro_profile_arn_hint": "AWS CodeWhisperer 프로필 ARN(선택 사항)",
    "providers.kiro_client_id_hint": "AWS SSO OIDC 인증용 OAuth 클라이언트 ID",
    "providers.kiro_client_secret_hint": "AWS SSO OIDC 인증용 OAuth 클라이언트 시크릿",
    "providers.kiro_upload_creds_hint": "Kiro IDE 자격 증명 JSON 파일 업로드",
    "providers.kiro_upload_sqlite_hint": "kiro-cli SQLite 데이터베이스 파일 업로드",
    "providers.provider_key_hint": "이는 구성 및 API 엔드포인트에서 공급자 ID로 사용됩니다.",
    "providers.subscription_based_hint": "선택한 경우 이 공급자는 구독 기반이며 비용은 $0으로 계산됩니다. 사용량은 여전히 분석을 위해 추적됩니다.",
    "providers.price_prompt_hint": "기본 가격 설정을 사용하려면 비워 두십시오. 예: OpenAI GPT-4: $10, Anthropic Claude: $15, Google Gemini: $1.25",
    "providers.price_completion_hint": "기본 가격 설정을 사용하려면 비워 두십시오. 예: OpenAI GPT-4: $30, Anthropic Claude: $75, Google Gemini: $5.00",
    "providers.native_caching_hint": "비용 절감을 위한 공급자 네이티브 캐싱 기능(Anthropic cache_control, Google Context Caching, OpenAI 및 Kilo 호환 API).",
    "providers.enable_native_caching_hint": "지원되는 공급자의 비용을 절감하기 위해 공급자 네이티브 캐싱을 활성화합니다(50-70% 절감).",
    
    # Rotations
    "rotations.copy_prompt": "\"{key}\" 복사 - 새 로테이션 키 입력:",
    "rotations.add_prompt": "로테이션 키를 입력하십시오(예: \"coding\", \"general\"):",
    "rotations.remove_confirm": "로테이션 \"{key}\"을(를) 삭제하시겠습니까?",
    "rotations.remove_provider_confirm": "이 공급자를 삭제하시겠습니까?",
    
    # Wallet
    "wallet_page.charged_to_card": "기본 신용 카드에 청구됩니다:",
    "wallet_page.invalid_amount": "{min} ~ {max} 사이의 금액을 선택하거나 입력하십시오.",
    "wallet_page.invalid_amount_title": "잘못된 금액",
    
    # Rate Limits
    "rate_limits_page.reset_confirm": "{provider}의 속도 제한을 재설정하시겠습니까?",
    "rate_limits_page.reset_confirm_title": "속도 제한 재설정",
    "rate_limits_page.reset_all_confirm": "모든 속도 제한을 재설정하시겠습니까? 이렇게 하면 모든 학습된 속도 제한이 지워집니다.",
    "rate_limits_page.reset_all_success": "모든 속도 제한이 성공적으로 재설정되었습니다",
    
    # Signup
    "signup_page.username_hint": "문자, 숫자, 밑줄, 하이픈, 점만 포함하여 3-50자",
    "signup_page.email_hint": "이 주소로 확인 이메일을 받게 됩니다",
    "signup_page.password_hint": "대문자, 소문자, 숫자를 각각 1자 이상 포함한 8자 이상",
    
    # Reset
    "reset_page.intro": "새 비밀번호를 아래에 입력하십시오.",
    "reset_page.password_hint": "8자 이상이어야 합니다",
    "reset_page.success": "비밀번호가 성공적으로 재설정되었습니다. 이제 새 비밀번호로 로그인할 수 있습니다.",
    "reset_page.go_to_login": "로그인으로 이동",
    "reset_page.invalid_token": "이 비밀번호 재설정 링크가 유효하지 않거나 만료되었습니다. 새 비밀번호 재설정 링크를 요청하십시오.",
    "reset_page.request_new": "새 재설정 링크 요청",
    
    # Tokens
    "tokens_page.description_placeholder": "예: 내 앱, 홈 서버…",
    "tokens_page.scope_api_hint": "(프록시 요청)",
    "tokens_page.scope_mcp_hint": "(에이전트 도구)",
    "tokens_page.auth_header_desc": "모든 요청에 {header} 헤더에 토큰을 포함하십시오:",
    "tokens_page.token_scopes": "토큰 범위:",
    "tokens_page.scope_api_access": "프록시 API 엔드포인트만 ({path})",
    "tokens_page.scope_mcp_access": "MCP 도구 엔드포인트만 ({path})",
    "tokens_page.scope_both_access": "API 및 MCP 엔드포인트 모두",
    "tokens_page.available_endpoints": "사용 가능한 엔드포인트:",
    "tokens_page.col_endpoint": "엔드포인트",
    "tokens_page.example_commands": "curl 명령어 예시:",
    "tokens_page.delete_confirm": "이 API 토큰을 삭제하시겠습니까? 이 작업은 즉시 액세스를 취소하며 취소할 수 없습니다.",
    
    # Billing
    "billing_page.col_date": "날짜",
    
    # User Overview
    "user_overview.higher_plans": "{n}개의 상위 플랜 사용 가능 — 요청 및 공급자 증가",
    "user_overview.upgrade_to": "{name}으로 업그레이드({price}/월)",
    "user_overview.auth_header_desc": "모든 엔드포인트에서 {header} 헤더에 API 토큰을 포함하십시오:",
    "user_overview.ep_chat_desc": "구성을 사용하여 채팅 요청 보내기",
    "user_overview.admin_access_desc": "관리자로서 더 짧은 모델 형식을 통해 전역 구성에도 액세스할 수 있습니다:",
    "user_overview.token_required": "모든 엔드포인트에 API 토큰이 필요합니다.",
    
    # Usage
    "usage_page.activity_quotas_desc": "자동으로 재설정되는 시간 기반 제한",
    "usage_page.config_limits_desc": "계정에 대한 영구적인 리소스 할당",
    "usage_page.resets_midnight": "UTC 오전 0시에 재설정",
    "usage_page.resets_in": "{h}시간 {m}분 후 재설정",
    "usage_page.resets_on_1st": "매월 1일에 재설정",
    "usage_page.resets_in_days": "{n}일 후 재설정",
    "usage_page.resets_in_days_plural": "{n}일 후 재설정",
    "usage_page.tokens_combined": "입력 + 출력 결합",
    "usage_page.remaining": "{n} 남음",
    "usage_page.ai_providers_desc": "구성된 공급자 통합",
    "usage_page.rotations_desc": "로드 밸런싱 구성",
    "usage_page.autoselections_desc": "스마트 라우팅 구성",
    "usage_page.unlimited_slots": "무제한 슬롯 사용 가능",
    "usage_page.pct_used_slots_free": "{pct}% 사용됨 · {n} 슬롯 남음",
    "usage_page.pct_used_slots_free_plural": "{pct}% 사용됨 · {n} 슬롯 남음",
    "usage_page.upgrade_desc": "더 많은 요청, 공급자 및 자동 선택을 잠금 해제하려면 플랜을 업그레이드하십시오.",
    
    # Subscription
    "subscription_page.no_description": "설명 없음",
    "subscription_page.billing_payments_desc": "결제 방법 관리 및 기록 보기",
    "subscription_page.upgrade_plan_desc": "사용 가능한 모든 플랜 보기",
    "subscription_page.edit_profile_desc": "계정 설정 업데이트",
    "subscription_page.change_password_desc": "보안 설정 업데이트",
    "subscription_page.no_payment_methods_desc": "플랜을 업그레이드하고 구독을 관리하려면 결제 방법을 추가하십시오.",
    "subscription_page.go_to_billing": "청구 및 결제 방법으로 이동",
}

print(f'Korean translations: {len(ko_trans)} keys')

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

apply('ko', ko_trans)