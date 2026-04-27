#!/usr/bin/env python3
# Russian translations for missing keys
ru_trans = {
    # Providers
    "providers.nsfw": "NSFW",
    "providers.models_fetch_error": "❌ Ошибка: {error}",
    "providers.rate_limit_hint": "Задержка между запросами к этому провайдеру",
    "providers.kiro_auth_hint": "Выберите один метод аутентификации: учетные данные Kiro IDE (creds_file), база данных kiro-cli (sqlite_db) или прямые учетные данные (refresh_token + client_id/secret).",
    "providers.kilo_auth_hint": "Выберите метод аутентификации: API-ключ (рекомендуется для простоты) или грант авторизации устройства OAuth2.",
    "providers.workspace_id_hint": "Идентификатор рабочей области для региона Германии (по умолчанию: \"Default Workspace\")",
    "providers.kiro_aws_region_hint": "Регион AWS для API Kiro (по умолчанию: us-east-1)",
    "providers.kiro_sqlite_hint": "Путь к базе данных SQLite kiro-cli",
    "providers.kiro_refresh_hint": "Токен обновления Kiro для прямой аутентификации",
    "providers.kiro_profile_arn_hint": "ARN профиля AWS CodeWhisperer (необязательно)",
    "providers.kiro_client_id_hint": "Идентификатор клиента OAuth для аутентификации AWS SSO OIDC",
    "providers.kiro_client_secret_hint": "Секрет клиента OAuth для аутентификации AWS SSO OIDC",
    "providers.kiro_upload_creds_hint": "Загрузить файл учетных данных Kiro IDE JSON",
    "providers.kiro_upload_sqlite_hint": "Загрузить файл базы данных SQLite kiro-cli",
    "providers.provider_key_hint": "Это будет использоваться в качестве идентификатора провайдера в конфигурации и конечных точках API.",
    "providers.subscription_based_hint": "Если отмечено, этот провайдер основан на подписке, и затраты будут рассчитываться как $0. Использование все равно отслеживается для аналитики.",
    "providers.price_prompt_hint": "Оставьте пустым, чтобы использовать цены по умолчанию. Примеры: OpenAI GPT-4: $10, Anthropic Claude: $15, Google Gemini: $1.25",
    "providers.price_completion_hint": "Оставьте пустым, чтобы использовать цены по умолчанию. Примеры: OpenAI GPT-4: $30, Anthropic Claude: $75, Google Gemini: $5.00",
    "providers.native_caching_hint": "Функции собственного кэширования провайдера (Anthropic cache_control, Google Context Caching, OpenAI и совместимые с Kilo API) для снижения затрат.",
    "providers.enable_native_caching_hint": "Включить собственное кэширование провайдера для снижения затрат (экономия 50–70% для поддерживаемых провайдеров).",
    
    # Rotations
    "rotations.copy_prompt": "Копировать \"{key}\" — введите новый ключ ротации:",
    "rotations.add_prompt": "Введите ключ ротации (например, \"coding\", \"general\"):",
    "rotations.remove_confirm": "Удалить ротацию \"{key}\"?",
    "rotations.remove_provider_confirm": "Удалить этого провайдера?",
    
    # Wallet
    "wallet_page.charged_to_card": "Списано с вашей кредитной карты по умолчанию:",
    "wallet_page.invalid_amount": "Выберите или введите сумму между {min} и {max}.",
    "wallet_page.invalid_amount_title": "Недопустимая сумма",
    
    # Rate Limits
    "rate_limits_page.reset_confirm": "Сбросить ограничитель скорости для {provider}?",
    "rate_limits_page.reset_confirm_title": "Сбросить ограничитель скорости",
    "rate_limits_page.reset_all_confirm": "Сбросить все ограничители скорости? Это очистит все изученные ограничения скорости.",
    "rate_limits_page.reset_all_success": "Все ограничители скорости успешно сброшены",
    
    # Signup
    "signup_page.username_hint": "Только 3-50 символов: буквы, цифры, подчеркивания, дефисы и точки",
    "signup_page.email_hint": "Вы получите подтверждающее письмо на этот адрес",
    "signup_page.password_hint": "Минимум 8 символов с заглавными, строчными буквами и цифрами",
    
    # Reset
    "reset_page.intro": "Пожалуйста, введите новый пароль ниже.",
    "reset_page.password_hint": "Должно быть не менее 8 символов",
    "reset_page.success": "Ваш пароль успешно сброшен. Теперь вы можете войти с новым паролем.",
    "reset_page.go_to_login": "Перейти к входу",
    "reset_page.invalid_token": "Эта ссылка для сброса пароля недействительна или истекла. Пожалуйста, запросите новую ссылку для сброса пароля.",
    "reset_page.request_new": "Запросить новую ссылку для сброса",
    
    # Tokens
    "tokens_page.description_placeholder": "напр. Мое приложение, Домашний сервер…",
    "tokens_page.scope_api_hint": "(прокси-запросы)",
    "tokens_page.scope_mcp_hint": "(инструменты агента)",
    "tokens_page.auth_header_desc": "Добавьте токен в каждый запрос в заголовке {header}:",
    "tokens_page.token_scopes": "Области токена:",
    "tokens_page.scope_api_access": "Только конечные точки API прокси ({path})",
    "tokens_page.scope_mcp_access": "Только конечные точки инструментов MCP ({path})",
    "tokens_page.scope_both_access": "Обе конечные точки API и MCP",
    "tokens_page.available_endpoints": "Доступные конечные точки:",
    "tokens_page.col_endpoint": "Конечная точка",
    "tokens_page.example_commands": "Примеры команд curl:",
    "tokens_page.delete_confirm": "Удалить этот API-токен? Это немедленно отменит доступ и не может быть отменено.",
    
    # Billing
    "billing_page.col_date": "Дата",
    
    # User Overview
    "user_overview.higher_plans": "{n} доступных более высоких планов — больше запросов, больше провайдеров",
    "user_overview.upgrade_to": "Обновить до {name} за {price}/мес",
    "user_overview.auth_header_desc": "Включите ваш API-токен в заголовок {header} для каждого запроса:",
    "user_overview.ep_chat_desc": "Отправляйте чат-запросы, используя ваши конфигурации",
    "user_overview.admin_access_desc": "Как администратор, вы также получаете доступ к глобальным конфигурациям через более короткие форматы моделей:",
    "user_overview.token_required": "Ваш API-токен требуется для всех конечных точек.",
    
    # Usage
    "usage_page.activity_quotas_desc": "Ограничения на основе времени, которые автоматически сбрасываются",
    "usage_page.config_limits_desc": "Постоянные распределения ресурсов для вашей учетной записи",
    "usage_page.resets_midnight": "Сброс в полночь по UTC",
    "usage_page.resets_in": "Сброс через {h}ч {m}м",
    "usage_page.resets_on_1st": "Сброс 1-го числа",
    "usage_page.resets_in_days": "Сброс через {n} день",
    "usage_page.resets_in_days_plural": "Сброс через {n} дней",
    "usage_page.tokens_combined": "Ввод + вывод в совокупности",
    "usage_page.remaining": "{n} осталось",
    "usage_page.ai_providers_desc": "Интеграции настроенных провайдеров",
    "usage_page.rotations_desc": "Конфигурации балансировки нагрузки",
    "usage_page.autoselections_desc": "Конфигурации интеллектуальной маршрутизации",
    "usage_page.unlimited_slots": "Неограниченные слоты доступны",
    "usage_page.pct_used_slots_free": "{pct}% использовано · {n} слот свободен",
    "usage_page.pct_used_slots_free_plural": "{pct}% использовано · {n} слотов свободно",
    "usage_page.upgrade_desc": "Улучшите свой план, чтобы разблокировать больше запросов, провайдеров и автоматических выборов.",
    
    # Subscription
    "subscription_page.no_description": "Нет описания",
    "subscription_page.billing_payments_desc": "Управление методами оплаты и просмотр истории",
    "subscription_page.upgrade_plan_desc": "Просмотр всех доступных планов",
    "subscription_page.edit_profile_desc": "Обновление настроек аккаунта",
    "subscription_page.change_password_desc": "Обновление настроек безопасности",
    "subscription_page.no_payment_methods_desc": "Добавьте метод оплаты, чтобы обновить свой план и управлять подписками.",
    "subscription_page.go_to_billing": "Перейти к выставлению счетов и методам оплаты",
}

print(f'Russian translations: {len(ru_trans)} keys')

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

apply('ru', ru_trans)