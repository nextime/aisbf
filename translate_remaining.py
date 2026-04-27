#!/usr/bin/env python3
"""
Translate remaining keys in language files.
Focus on high-priority keys mentioned in the issue.
"""

import json

def get_remaining_translations_ja():
    """Get translations for remaining keys in Japanese"""
    return {
        "NSFW": "NSFW",
        "Privacy": "プライバシー",
        "PayPal": "PayPal",
        "USDC": "USDC",
        "USDT": "USDT",
        "OK": "OK",
        "Reset Prompt": "プロンプトをリセット",
        "Are you sure you want to reset this prompt to the default admin configuration?": "このプロンプトをデフォルトの管理者設定にリセットしてもよろしいですか？",
        "✗ Authorization denied by user.": "✗ 認証がユーザーによって拒否されました。",
        "❌ Error checking {provider} auth: {error}": "❌ {provider} の認証確認エラー: {error}",
        "✗ Error completing authentication: {error}": "✗ 認証完了エラー: {error}",
        "✗ Authorization code expired. Please try again.": "✗ 認証コードが期限切れです。再試行してください。",
        "❌ {provider} authentication failed: {error}": "❌ {provider} 認証失敗: {error}",
        "✗ Error: {error}": "✗ エラー: {error}",
        "✗ Failed to start authentication: {error}": "✗ 認証開始失敗: {error}",
        "✓ {provider} authentication successful! Credentials saved.": "✓ {provider} 認証成功！資格情報を保存しました。",
        "✗ Authentication timeout. Please try again.": "✗ 認証タイムアウト。再試行してください。",
        "✅ {provider} authentication is valid. Expires in: {expiry}": "✅ {provider} 認証は有効です。期限切れまで: {expiry}",
        "Cache time-to-live in seconds (Google Context Caching only)": "キャッシュの有効期間（秒）（Google Context Cachingのみ）",
        "Checking {provider} authentication status...": "{provider} の認証ステータスを確認しています...",
        "CLI credentials saved: {name}": "CLI 資格情報を保存しました: {name}",
        "Default token limit per day for models in this provider": "このプロバイダーのモデルの1日あたりのデフォルトトークン制限",
        "Default token limit per hour for models in this provider": "このプロバイダーのモデルの1時間あたりのデフォルトトークン制限",
        "Default token limit per minute for models in this provider": "このプロバイダーのモデルの1分あたりのデフォルトトークン制限",
        "Min Cacheable Tokens": "最小キャッシュ可能トークン",
        "Minimum token count for content to be cacheable (default: 1000)": "コンテンツをキャッシュ可能にするための最小トークン数（デフォルト: 1000）",
        "Prompt Cache Key (OpenAI/Kilo)": "プロンプトキャッシュキー（OpenAI/Kilo）",
        "Optional cache key for OpenAI/Kilo load balancer routing optimization": "OpenAI/Kilo ロードバランサールーティング最適化のためのオプションのキャッシュキー",
        "Configure specific models for this provider, or leave empty to automatically fetch all available models from the provider's API.": "このプロバイダーに特定のモデルを設定するか、空のままにしてプロバイダーのAPIから利用可能なすべてのモデルを自動的にフェッチします。",
        "Model Filter (for auto-fetched models)": "モデルフィルター（自動取得モデル用）",
        "When no models are manually configured, only expose models whose ID contains this filter word (case-insensitive wildcard matching).": "モデルが手動で構成されていない場合、このフィルター単語を含むIDを持つモデルのみを公開します（大文字と小文字を区別しないワイルドカード一致）。",
        "Rate Limit TPM (Tokens Per Minute)": "レート制限 TPM（トークン/分）",
        "Rate Limit TPH (Tokens Per Hour)": "レート制限 TPH（トークン/時）",
        "Rate Limit TPD (Tokens Per Day)": "レート制限 TPD（トークン/日）",
        "Condense Context (%)": "コンテキスト圧縮（％）",
        "Condense Method (conversational, semantic, hierarchical, algorithmic)": "圧縮方法（会話型、意味論的、階層的、アルゴリズム的）",
        "Standard provider configuration.": "標準プロバイダー構成。",
        "Uploading file: {pct}%": "ファイルをアップロードしています: {pct}%",
        "Uploading CLI credentials: {pct}%": "CLI 資格情報をアップロードしています: {pct}%",
        "CLI credentials saved: {name}": "CLI 資格情報を保存しました: {name}",
        "Upload failed: {error}": "アップロード失敗: {error}",
        "Fetching models...": "モデルを取得中...",
        "Checking {provider} authentication status...": "{provider} の認証ステータスを確認しています...",
        "✅ {provider} authentication is valid. Expires in: {expiry}": "✅ {provider} 認証は有効です。期限切れまで: {expiry}",
        "❌ {provider} authentication failed: {error}": "❌ {provider} 認証失敗: {error}",
        "❌ Error checking {provider} auth: {error}": "❌ {provider} の認証確認エラー: {error}",
        "✓ {provider} authentication successful! Credentials saved.": "✓ {provider} 認証成功！資格情報を保存しました。",
        "✗ Authentication timeout. Please try again.": "✗ 認証タイムアウト。再試行してください。",
        "✗ Authorization denied by user.": "✗ 認証がユーザーによって拒否されました。",
        "✗ Authorization code expired. Please try again.": "✗ 認証コードが期限切れです。再試行してください。",
        "✗ Failed to start authentication: {error}": "✗ 認証開始失敗: {error}",
        "✗ Error completing authentication: {error}": "✗ 認証完了エラー: {error}",
        "✗ Error: {error}": "✗ エラー: {error}",
        "Not authenticated": "未認証",
        "Remove provider \"{key}\"?": "プロバイダー \"{key}\" を削除しますか？",
        "Remove Model": "モデルを削除",
        "Are you sure you want to reset this prompt to the default admin configuration?": "このプロンプトをデフォルトの管理者設定にリセットしてもよろしいですか？",
        "Reset Prompt": "プロンプトをリセット",
    }

def get_remaining_translations_zh():
    """Get translations for remaining keys in Chinese"""
    return {
        "NSFW": "NSFW",
        "Privacy": "隐私",
        "PayPal": "PayPal",
        "USDC": "USDC",
        "USDT": "USDT",
        "OK": "确定",
        "Reset Prompt": "重置提示词",
        "Are you sure you want to reset this prompt to the default admin configuration?": "您确定要将此提示词重置为默认管理员配置吗？",
        "✗ Authorization denied by user.": "✗ 授权被用户拒绝。",
        "❌ Error checking {provider} auth: {error}": "❌ 检查 {provider} 认证错误: {error}",
        "✗ Error completing authentication: {error}": "✗ 完成认证错误: {error}",
        "✗ Authorization code expired. Please try again.": "✗ 授权代码已过期。请重试。",
        "❌ {provider} authentication failed: {error}": "❌ {provider} 认证失败: {error}",
        "✗ Error: {error}": "✗ 错误: {error}",
        "✗ Failed to start authentication: {error}": "✗ 启动认证失败: {error}",
        "✓ {provider} authentication successful! Credentials saved.": "✓ {provider} 认证成功！凭据已保存。",
        "✗ Authentication timeout. Please try again.": "✗ 认证超时。请重试。",
        "✅ {provider} authentication is valid. Expires in: {expiry}": "✅ {provider} 认证有效。有效期至: {expiry}",
        "Cache time-to-live in seconds (Google Context Caching only)": "缓存生存时间（秒）（仅适用于 Google Context Caching）",
        "Checking {provider} authentication status...": "正在检查 {provider} 认证状态...",
        "CLI credentials saved: {name}": "CLI 凭据已保存: {name}",
        "Default token limit per day for models in this provider": "此提供商模型的每日默认令牌限制",
        "Default token limit per hour for models in this provider": "此提供商模型的每小时默认令牌限制",
        "Default token limit per minute for models in this provider": "此提供商模型的每分钟默认令牌限制",
        "Min Cacheable Tokens": "最小可缓存令牌",
        "Minimum token count for content to be cacheable (default: 1000)": "内容可缓存的最小令牌数（默认：1000）",
        "Prompt Cache Key (OpenAI/Kilo)": "提示缓存键（OpenAI/Kilo）",
        "Optional cache key for OpenAI/Kilo load balancer routing optimization": "OpenAI/Kilo 负载均衡器路由优化的可选缓存键",
        "Configure specific models for this provider, or leave empty to automatically fetch all available models from the provider's API.": "为此提供商配置特定模型，或留空以自动从提供商的API获取所有可用模型。",
        "Model Filter (for auto-fetched models)": "模型过滤器（用于自动获取的模型）",
        "When no models are manually configured, only expose models whose ID contains this filter word (case-insensitive wildcard matching).": "当没有手动配置模型时，仅公开其ID包含此过滤词的模型（不区分大小写的通配符匹配）。",
        "Rate Limit TPM (Tokens Per Minute)": "速率限制 TPM（令牌/分钟）",
        "Rate Limit TPH (Tokens Per Hour)": "速率限制 TPH（令牌/小时）",
        "Rate Limit TPD (Tokens Per Day)": "速率限制 TPD（令牌/天）",
        "Condense Context (%)": "压缩上下文（%）",
        "Condense Method (conversational, semantic, hierarchical, algorithmic)": "压缩方法（对话式、语义式、层次式、算法式）",
        "Standard provider configuration.": "标准提供商配置。",
        "Uploading file: {pct}%": "正在上传文件: {pct}%",
        "Uploading CLI credentials: {pct}%": "正在上传 CLI 凭据: {pct}%",
        "CLI credentials saved: {name}": "CLI 凭据已保存: {name}",
        "Upload failed: {error}": "上传失败: {error}",
        "Fetching models...": "正在获取模型...",
        "Checking {provider} authentication status...": "正在检查 {provider} 认证状态...",
        "✅ {provider} authentication is valid. Expires in: {expiry}": "✅ {provider} 认证有效。有效期至: {expiry}",
        "❌ {provider} authentication failed: {error}": "❌ {provider} 认证失败: {error}",
        "❌ Error checking {provider} auth: {error}": "❌ 检查 {provider} 认证错误: {error}",
        "✓ {provider} authentication successful! Credentials saved.": "✓ {provider} 认证成功！凭据已保存。",
        "✗ Authentication timeout. Please try again.": "✗ 认证超时。请重试。",
        "✗ Authorization denied by user.": "✗ 授权被用户拒绝。",
        "✗ Authorization code expired. Please try again.": "✗ 授权代码已过期。请重试。",
        "✗ Failed to start authentication: {error}": "✗ 启动认证失败: {error}",
        "✗ Error completing authentication: {error}": "✗ 完成认证错误: {error}",
        "✗ Error: {error}": "✗ 错误: {error}",
        "Not authenticated": "未认证",
        "Remove provider \"{key}\"?": "删除提供商 \"{key}\"?",
        "Remove Model": "删除模型",
        "Are you sure you want to reset this prompt to the default admin configuration?": "您确定要将此提示词重置为默认管理员配置吗？",
        "Reset Prompt": "重置提示词",
    }

def get_remaining_translations_ko():
    """Get translations for remaining keys in Korean"""
    return {
        "NSFW": "NSFW",
        "Privacy": "개인정보",
        "PayPal": "PayPal",
        "USDC": "USDC",
        "USDT": "USDT",
        "OK": "확인",
        "Reset Prompt": "프롬프트 재설정",
        "Are you sure you want to reset this prompt to the default admin configuration?": "이 프롬프트를 기본 관리자 구성으로 재설정하시겠습니까?",
        "✗ Authorization denied by user.": "✗ 사용자에 의한 승인 거부.",
        "❌ Error checking {provider} auth: {error}": "❌ {provider} 인증 확인 오류: {error}",
        "✗ Error completing authentication: {error}": "✗ 인증 완료 오류: {error}",
        "✗ Authorization code expired. Please try again.": "✗ 인증 코드가 만료되었습니다. 다시 시도하세요.",
        "❌ {provider} authentication failed: {error}": "❌ {provider} 인증 실패: {error}",
        "✗ Error: {error}": "✗ 오류: {error}",
        "✗ Failed to start authentication: {error}": "✗ 인증 시작 실패: {error}",
        "✓ {provider} authentication successful! Credentials saved.": "✓ {provider} 인증 성공! 자격 증명이 저장되었습니다.",
        "✗ Authentication timeout. Please try again.": "✗ 인증 시간 초과. 다시 시도하세요.",
        "✅ {provider} authentication is valid. Expires in: {expiry}": "✅ {provider} 인증이 유효합니다. 만료 시간: {expiry}",
        "Cache time-to-live in seconds (Google Context Caching only)": "캐시 수명(초)(Google Context Caching 전용)",
        "Checking {provider} authentication status...": "{provider} 인증 상태 확인 중...",
        "CLI credentials saved: {name}": "CLI 자격 증명 저장됨: {name}",
        "Default token limit per day for models in this provider": "이 공급자의 모델에 대한 일일 기본 토큰 제한",
        "Default token limit per hour for models in this provider": "이 공급자의 모델에 대한 시간당 기본 토큰 제한",
        "Default token limit per minute for models in this provider": "이 공급자의 모델에 대한 분당 기본 토큰 제한",
        "Min Cacheable Tokens": "최소 캐시 가능 토큰",
        "Minimum token count for content to be cacheable (default: 1000)": "캐시 가능하도록 만들 콘텐츠의 최소 토큰 수(기본값: 1000)",
        "Prompt Cache Key (OpenAI/Kilo)": "프롬프트 캐시 키(OpenAI/Kilo)",
        "Optional cache key for OpenAI/Kilo load balancer routing optimization": "OpenAI/Kilo 로드 밸런서 라우팅 최적화를 위한 선택적 캐시 키",
        "Configure specific models for this provider, or leave empty to automatically fetch all available models from the provider's API.": "이 공급자에 대해 특정 모델을 구성하거나 비워 두어서 공급자의 API에서 사용 가능한 모든 모델을 자동으로 가져옵니다.",
        "Model Filter (for auto-fetched models)": "모델 필터(자동 가져온 모델용)",
        "When no models are manually configured, only expose models whose ID contains this filter word (case-insensitive wildcard matching).": "수동으로 모델을 구성하지 않은 경우 ID에 이 필터 단어가 포함된 모델만 노출합니다(대소문자 구분 없는 와일드카드 일치).",
        "Rate Limit TPM (Tokens Per Minute)": "속도 제한 TPM(분당 토큰)",
        "Rate Limit TPH (Tokens Per Hour)": "속도 제한 TPH(시간당 토큰)",
        "Rate Limit TPD (Tokens Per Day)": "속도 제한 TPD(일당 토큰)",
        "Condense Context (%)": "컨텍스트 압축(%)",
        "Condense Method (conversational, semantic, hierarchical, algorithmic)": "압축 방법(대화형, 의미론적, 계층적, 알고리즘적)",
        "Standard provider configuration.": "표준 공급자 구성.",
        "Uploading file: {pct}%": "파일 업로드 중: {pct}%",
        "Uploading CLI credentials: {pct}%": "CLI 자격 증명 업로드 중: {pct}%",
        "CLI credentials saved: {name}": "CLI 자격 증명 저장됨: {name}",
        "Upload failed: {error}": "업로드 실패: {error}",
        "Fetching models...": "모델 가져오는 중...",
        "Checking {provider} authentication status...": "{provider} 인증 상태 확인 중...",
        "✅ {provider} authentication is valid. Expires in: {expiry}": "✅ {provider} 인증이 유효합니다. 만료 시간: {expiry}",
        "❌ {provider} authentication failed: {error}": "❌ {provider} 인증 실패: {error}",
        "❌ Error checking {provider} auth: {error}": "❌ {provider} 인증 확인 오류: {error}",
        "✓ {provider} authentication successful! Credentials saved.": "✓ {provider} 인증 성공! 자격 증명이 저장되었습니다.",
        "✗ Authentication timeout. Please try again.": "✗ 인증 시간 초과. 다시 시도하세요.",
        "✗ Authorization denied by user.": "✗ 사용자에 의한 승인 거부.",
        "✗ Authorization code expired. Please try again.": "✗ 인증 코드가 만료되었습니다. 다시 시도하세요.",
        "✗ Failed to start authentication: {error}": "✗ 인증 시작 실패: {error}",
        "✗ Error completing authentication: {error}": "✗ 인증 완료 오류: {error}",
        "✗ Error: {error}": "✗ 오류: {error}",
        "Not authenticated": "인증되지 않음",
        "Remove provider \"{key}\"?": "공급자 \"{key}\" 제거?",
        "Remove Model": "모델 제거",
        "Are you sure you want to reset this prompt to the default admin configuration?": "이 프롬프트를 기본 관리자 구성으로 재설정하시겠습니까?",
        "Reset Prompt": "프롬프트 재설정",
    }

def get_remaining_translations_ru():
    """Get translations for remaining keys in Russian"""
    return {
        "NSFW": "NSFW",
        "Privacy": "Конфиденциальность",
        "PayPal": "PayPal",
        "USDC": "USDC",
        "USDT": "USDT",
        "OK": "OK",
        "Reset Prompt": "Сбросить промпт",
        "Are you sure you want to reset this prompt to the default admin configuration?": "Вы уверены, что хотите сбросить этот промпт до конфигурации по умолчанию?",
        "✗ Authorization denied by user.": "✗ Авторизация отклонена пользователем.",
        "❌ Error checking {provider} auth: {error}": "❌ Ошибка проверки аутентификации {provider}: {error}",
        "✗ Error completing authentication: {error}": "✗ Ошибка завершения аутентификации: {error}",
        "✗ Authorization code expired. Please try again.": "✗ Код авторизации истек. Пожалуйста, попробуйте снова.",
        "❌ {provider} authentication failed: {error}": "❌ Ошибка аутентификации {provider}: {error}",
        "✗ Error: {error}": "✗ Ошибка: {error}",
        "✗ Failed to start authentication: {error}": "✗ Не удалось начать аутентификацию: {error}",
        "✓ {provider} authentication successful! Credentials saved.": "✓ Аутентификация {provider} успешна! Учетные данные сохранены.",
        "✗ Authentication timeout. Please try again.": "✗ Тайм-аут аутентификации. Пожалуйста, попробуйте снова.",
        "✅ {provider} authentication is valid. Expires in: {expiry}": "✅ Аутентификация {provider} действительна. Истекает через: {expiry}",
        "Cache time-to-live in seconds (Google Context Caching only)": "Время жизни кеша в секундах (только для Google Context Caching)",
        "Checking {provider} authentication status...": "Проверка статуса аутентификации {provider}...",
        "CLI credentials saved: {name}": "Учетные данные CLI сохранены: {name}",
        "Default token limit per day for models in this provider": "Лимит токенов по умолчанию в день для моделей этого провайдера",
        "Default token limit per hour for models in this provider": "Лимит токенов по умолчанию в час для моделей этого провайдера",
        "Default token limit per minute for models in this provider": "Лимит токенов по умолчанию в минуту для моделей этого провайдера",
        "Min Cacheable Tokens": "Минимальное количество токенов для кэширования",
        "Minimum token count for content to be cacheable (default: 1000)": "Минимальное количество токенов для кэшируемого контента (по умолчанию: 1000)",
        "Prompt Cache Key (OpenAI/Kilo)": "Ключ кэша промпта (OpenAI/Kilo)",
        "Optional cache key for OpenAI/Kilo load balancer routing optimization": "Необязательный ключ кэша для оптимизации маршрутизации балансировщика нагрузки OpenAI/Kilo",
        "Configure specific models for this provider, or leave empty to automatically fetch all available models from the provider's API.": "Настройте определенные модели для этого провайдера или оставьте пустым, чтобы автоматически получить все доступные модели из API провайдера.",
        "Model Filter (for auto-fetched models)": "Фильтр моделей (для автоматически получаемых моделей)",
        "When no models are manually configured, only expose models whose ID contains this filter word (case-insensitive wildcard matching).": "Когда модели не настроены вручную, отображаются только те модели, идентификатор которых содержит это слово-фильтр (сопоставление с подстановочными знаками без учета регистра).",
        "Rate Limit TPM (Tokens Per Minute)": "Лимит скорости TPM (токенов в минуту)",
        "Rate Limit TPH (Tokens Per Hour)": "Лимит скорости TPH (токенов в час)",
        "Rate Limit TPD (Tokens Per Day)": "Лимит скорости TPD (токенов в день)",
        "Condense Context (%)": "Контекст сжатия (%)",
        "Condense Method (conversational, semantic, hierarchical, algorithmic)": "Метод сжатия (разговорный, семантический, иерархический, алгоритмический)",
        "Standard provider configuration.": "Стандартная конфигурация провайдера.",
        "Uploading file: {pct}%": "Загрузка файла: {pct}%",
        "Uploading CLI credentials: {pct}%": "Загрузка учетных данных CLI: {pct}%",
        "CLI credentials saved: {name}": "Учетные данные CLI сохранены: {name}",
        "Upload failed: {error}": "Ошибка загрузки: {error}",
        "Fetching models...": "Получение моделей...",
        "Checking {provider} authentication status...": "Проверка статуса аутентификации {provider}...",
        "✅ {provider} authentication is valid. Expires in: {expiry}": "✅ Аутентификация {provider} действительна. Истекает через: {expiry}",
        "❌ {provider} authentication failed: {error}": "❌ Ошибка аутентификации {provider}: {error}",
        "❌ Error checking {provider} auth: {error}": "❌ Ошибка проверки аутентификации {provider}: {error}",
        "✓ {provider} authentication successful! Credentials saved.": "✓ Аутентификация {provider} успешна! Учетные данные сохранены.",
        "✗ Authentication timeout. Please try again.": "✗ Тайм-аут аутентификации. Пожалуйста, попробуйте снова.",
        "✗ Authorization denied by user.": "✗ Авторизация отклонена пользователем.",
        "✗ Authorization code expired. Please try again.": "✗ Код авторизации истек. Пожалуйста, попробуйте снова.",
        "✗ Failed to start authentication: {error}": "✗ Не удалось начать аутентификацию: {error}",
        "✗ Error completing authentication: {error}": "✗ Ошибка завершения аутентификации: {error}",
        "✗ Error: {error}": "✗ Ошибка: {error}",
        "Not authenticated": "Не аутентифицирован",
        "Remove provider \"{key}\"?": "Удалить провайдера \"{key}\"?",
        "Remove Model": "Удалить модель",
        "Are you sure you want to reset this prompt to the default admin configuration?": "Вы уверены, что хотите сбросить этот промпт до конфигурации по умолчанию?",
        "Reset Prompt": "Сбросить промпт",
    }

def get_remaining_translations_af():
    """Get translations for remaining keys in Afrikaans"""
    return {
        "NSFW": "NSFW",
        "Privacy": "Privaatheid",
        "PayPal": "PayPal",
        "USDC": "USDC",
        "USDT": "USDT",
        "OK": "OK",
        "Reset Prompt": "Stel prompterfris",
        "Are you sure you want to reset this prompt to the default admin configuration?": "Is u seker dat u hierdie promt na die verstek-administrateurkonfigurasie wil stel?",
        "✗ Authorization denied by user.": "✗ Toegunning geweier deur gebruiker.",
        "❌ Error checking {provider} auth: {error}": "❌ Fout by die kontrole van {provider} verifikasie: {error}",
        "✗ Error completing authentication: {error}": "✗ Fout met voltooiing van verifikasie: {error}",
        "✗ Authorization code expired. Please try again.": "✗ Vergunningkode het verval. Probeer asseblief weer.",
        "❌ {provider} authentication failed: {error}": "❌ {provider} verifikasie misluk: {error}",
        "✗ Error: {error}": "✗ Fout: {error}",
        "✗ Failed to start authentication: {error}": "✗ Kon nie verifikasie begin nie: {error}",
        "✓ {provider} authentication successful! Credentials saved.": "✓ {provider} verifikasie suksesvol! Kredensials gestoor.",
        "✗ Authentication timeout. Please try again.": "✗ Verifikasie het uitgetel. Probeer asseblief weer.",
        "✅ {provider} authentication is valid. Expires in: {expiry}": "✅ {provider} verifikasie is geldig. Verval in: {expiry}",
        "Cache time-to-live in seconds (Google Context Caching only)": "Kas tyd-tot-lewens in sekondes (slegs vir Google Context Caching)",
        "Checking {provider} authentication status...": "Kontroleer {provider} verifikasiestatus...",
        "CLI credentials saved: {name}": "CLI-kredensials gestoor: {name}",
        "Default token limit per day for models in this provider": "Verstek tokenlimiet per dag vir modelle in hierdie verskaffer",
        "Default token limit per hour for models in this provider": "Verstek tokenlimiet per uur vir modelle in hierdie verskaffer",
        "Default token limit per minute for models in this provider": "Verstek tokenlimiet per minuut vir modelle in hierdie verskaffer",
        "Min Cacheable Tokens": "Min Kasbare Tekens",
        "Minimum token count for content to be cacheable (default: 1000)": "Minimum tekenaantal vir inhoud om kasbaar te wees (verstek: 1000)",
        "Prompt Cache Key (OpenAI/Kilo)": "Opdragkasleutel (OpenAI/Kilo)",
        "Optional cache key for OpenAI/Kilo load balancer routing optimization": "Opsionele kasleutel vir OpenAI/Kilo-ladingbalanseroprotimering",
        "Configure specific models for this provider, or leave empty to automatically fetch all available models from the provider's API.": "Stel spesifieke modelle vir hierdie verskaffer in, of laat leeg om outomaties alle beskikbare modelle van die verskaffer se API te haal.",
        "Model Filter (for auto-fetched models)": "Modelfilter (vir outomaties-gehaalde modelle)",
        "When no models are manually configured, only expose models whose ID contains this filter word (case-insensitive wildcard matching).": "Wanneer geen modelle handmatig gekonfigureer is nie, blootstel slegs modelle waase ID hierdie filterwoord bevat (hoofdletterongegevoerde jokerteken passing).",
        "Rate Limit TPM (Tokens Per Minute)": "Tempolimiet TPM (Tekens Per Minuut)",
        "Rate Limit TPH (Tokens Per Hour)": "Tempolimiet TPH (Tekens Per Uur)",
        "Rate Limit TPD (Tokens Per Day)": "Tempolimiet TPD (Tekens Per Dag)",
        "Condense Context (%)": "Saamvat Konteks (%)",
        "Condense Method (conversational, semantic, hierarchical, algorithmic)": "Saamvatmetode (gespreksvormig, semanties, hiërargies, algoritmies)",
        "Standard provider configuration.": "Standaard verskaffer konfigurasie.",
        "Uploading file: {pct}%": "Lêer word opgelaai: {pct}%",
        "Uploading CLI credentials: {pct}%": "CLI-kredensials word opgelaai: {pct}%",
        "CLI credentials saved: {name}": "CLI-kredensials gestoor: {name}",
        "Upload failed: {error}": "Oplaai het misluk: {error}",
        "Fetching models...": "Modelle word gehaal...",
        "Checking {provider} authentication status...": "Kontroleer {provider} verifikasiestatus...",
        "✅ {provider} authentication is valid. Expires in: {expiry}": "✅ {provider} verifikasie is geldig. Verval in: {expiry}",
        "❌ {provider} authentication failed: {error}": "❌ {provider} verifikasie misluk: {error}",
        "❌ Error checking {provider} auth: {error}": "❌ Fout by die kontrole van {provider} verifikasie: {error}",
        "✓ {provider} authentication successful! Credentials saved.": "✓ {provider} verifikasie suksesvol! Kredensials gestoor.",
        "✗ Authentication timeout. Please try again.": "✗ Verifikasie het uitgetel. Probeer asseblief weer.",
        "✗ Authorization denied by user.": "✗ Toegunning geweier deur gebruiker.",
        "✗ Authorization code expired. Please try again.": "✗ Vergunningkode het verval. Probeer asseblief weer.",
        "✗ Failed to start authentication: {error}": "✗ Kon nie verifikasie begin nie: {error}",
        "✗ Error completing authentication: {error}": "✗ Fout met voltooiing van verifikasie: {error}",
        "✗ Error: {error}": "✗ Fout: {error}",
        "Not authenticated": "Nie geverifieer nie",
        "Remove provider \"{key}\"?": "Verwyder verskaffer \"{key}\"?",
        "Remove Model": "Verwyder Model",
        "Are you sure you want to reset this prompt to the default admin configuration?": "Is u seker dat u hierdie promt na die verstek-administrateurkonfigurasie wil stel?",
        "Reset Prompt": "Stel prompterfris",
    }

def translate_file_with_dict(filepath, translations):
    """Translate a language file using the provided translation dictionary"""
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # Track changes
    changes_made = []
    
    def update_dict(d, path=""):
        for key, value in d.items():
            current_path = f"{path}.{key}" if path else key
            if isinstance(value, dict):
                update_dict(value, current_path)
            elif isinstance(value, str) and value in translations:
                # Found a match, translate it
                old_value = value
                new_value = translations[value]
                d[key] = new_value
                changes_made.append((current_path, old_value, new_value))
    
    # Apply translations
    update_dict(data)
    
    # Save updated file
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    # Print changes
    if changes_made:
        print(f"\n{'='*80}")
        print(f"Updates made: {len(changes_made)}")
        print(f"{'='*80}")
        
        for path, old_val, new_val in changes_made[:30]:  # Show first 30
            print(f"  {path}")
            print(f"    FROM: {old_val[:60]}..." if len(old_val) > 60 else f"    FROM: {old_val}")
            print(f"    TO:   {new_val[:60]}..." if len(new_val) > 60 else f"    TO:   {new_val}")
            print()
        
        if len(changes_made) > 30:
            print(f"  ... and {len(changes_made) - 30} more changes")
    
    return len(changes_made)

def translate_files():
    """Translate all language files with remaining keys"""
    total = 0
    
    translations_map = {
        'ja': get_remaining_translations_ja(),
        'zh': get_remaining_translations_zh(),
        'ko': get_remaining_translations_ko(),
        'ru': get_remaining_translations_ru(),
        'af': get_remaining_translations_af(),
    }
    
    for lang_code, translations in translations_map.items():
        filepath = f'/working/aisbf/static/i18n/{lang_code}.json'
        changes = translate_file_with_dict(filepath, translations)
        total += changes
    
    print(f"\n{'='*80}")
    print(f"TOTAL NEW TRANSLATIONS: {total}")
    print(f"{'='*80}")
    
    return total

if __name__ == '__main__':
    translate_files()