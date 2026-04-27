#!/usr/bin/env python3
# Japanese translations for missing keys
ja_trans = {
    # Providers
    "providers.nsfw": "NSFW",
    "providers.models_fetch_error": "❌ エラー: {error}",
    "providers.rate_limit_hint": "このプロバイダーへのリクエスト間の遅延時間",
    "providers.kiro_auth_hint": "認証方法を選択してください: Kiro IDE 認証情報 (creds_file)、kiro-cli データベース (sqlite_db)、または直接認証情報 (refresh_token + client_id/secret)。",
    "providers.kilo_auth_hint": "認証方法を選択してください: API キー（シンプルにするために推奨）または OAuth2 デバイス認証付与。",
    "providers.workspace_id_hint": "ドイツ リージョンのワークスペース ID（デフォルト: \"Default Workspace\"）",
    "providers.kiro_aws_region_hint": "Kiro API 用 AWS リージョン（デフォルト: us-east-1）",
    "providers.kiro_sqlite_hint": "kiro-cli SQLite データベースへのパス",
    "providers.kiro_refresh_hint": "直接認証用の Kiro リフレッシュ トークン",
    "providers.kiro_profile_arn_hint": "AWS CodeWhisperer プロファイル ARN（オプション）",
    "providers.kiro_client_id_hint": "AWS SSO OIDC 認証用の OAuth クライアント ID",
    "providers.kiro_client_secret_hint": "AWS SSO OIDC 認証用の OAuth クライアント シークレット",
    "providers.kiro_upload_creds_hint": "Kiro IDE 認証情報 JSON ファイルをアップロード",
    "providers.kiro_upload_sqlite_hint": "kiro-cli SQLite データベース ファイルをアップロード",
    "providers.provider_key_hint": "これは、構成と API エンドポイントでプロバイダー ID として使用されます。",
    "providers.subscription_based_hint": "チェックした場合、このプロバイダーはサブスクリプションベースであり、コストは $0 として計算されます。使用状況は引き続き分析用に追跡されます。",
    "providers.price_prompt_hint": "デフォルトの価格設定を使用するには空のままにします。例: OpenAI GPT-4: $10、Anthropic Claude: $15、Google Gemini: $1.25",
    "providers.price_completion_hint": "デフォルトの価格設定を使用するには空のままにします。例: OpenAI GPT-4: $30、Anthropic Claude: $75、Google Gemini: $5.00",
    "providers.native_caching_hint": "コスト削減のためのプロバイダー ネイティブのキャッシュ機能 (Anthropic cache_control、Google Context Caching、OpenAI、および Kilo 互換 API)。",
    "providers.enable_native_caching_hint": "サポートされているプロバイダーのコストを削減するために、プロバイダー ネイティブのキャッシュを有効にします (50-70% の節約)。",
    
    # Rotations
    "rotations.copy_prompt": "\"{key}\" をコピー — 新しいローテーション キーを入力:",
    "rotations.add_prompt": "ローテーション キーを入力してください（例: \"coding\"、\"general\"）:",
    "rotations.remove_confirm": "ローテーション \"{key}\" を削除しますか？",
    "rotations.remove_provider_confirm": "このプロバイダーを削除しますか？",
    
    # Wallet
    "wallet_page.charged_to_card": "デフォルトのクレジット カードに請求されます:",
    "wallet_page.invalid_amount": "{min} ～ {max} の間の金額を選択または入力してください。",
    "wallet_page.invalid_amount_title": "無効な金額",
    
    # Rate Limits
    "rate_limits_page.reset_confirm": "{provider} のレート制限をリセットしますか？",
    "rate_limits_page.reset_confirm_title": "レート制限のリセット",
    "rate_limits_page.reset_all_confirm": "すべてのレート制限をリセットしますか? これにより、すべての学習済みレート制限がクリアされます。",
    "rate_limits_page.reset_all_success": "すべてのレート制限が正常にリセットされました",
    
    # Signup
    "signup_page.username_hint": "3-50 文字、文字、数字、アンダースコア、ハイフン、ドットのみ",
    "signup_page.email_hint": "このアドレスに検証メールが届きます",
    "signup_page.password_hint": "大文字、小文字、数字をそれぞれ 1 文字以上含む 8 文字以上",
    
    # Reset
    "reset_page.intro": "新しいパスワードを以下に入力してください。",
    "reset_page.password_hint": "8 文字以上である必要があります",
    "reset_page.success": "パスワードのリセットに成功しました。新しいパスワードでログインできるようになりました。",
    "reset_page.go_to_login": "ログインへ",
    "reset_page.invalid_token": "このパスワード リセット リンクは無効であるか、有効期限が切れています。新しいパスワード リセット リンクをリクエストしてください。",
    "reset_page.request_new": "新しいリセット リンクをリクエスト",
    
    # Tokens
    "tokens_page.description_placeholder": "例: マイアプリ、ホームサーバー…",
    "tokens_page.scope_api_hint": "(プロキシ リクエスト)",
    "tokens_page.scope_mcp_hint": "(エージェント ツール)",
    "tokens_page.auth_header_desc": "すべてのリクエストにトークンを {header} ヘッダーに含めます:",
    "tokens_page.token_scopes": "トークンのスコープ:",
    "tokens_page.scope_api_access": "プロキシ API エンドポイントのみ ({path})",
    "tokens_page.scope_mcp_access": "MCP ツール エンドポイントのみ ({path})",
    "tokens_page.scope_both_access": "API エンドポイントと MCP エンドポイントの両方",
    "tokens_page.available_endpoints": "利用可能なエンドポイント:",
    "tokens_page.col_endpoint": "エンドポイント",
    "tokens_page.example_commands": "curl コマンドの例:",
    "tokens_page.delete_confirm": "この API トークンを削除しますか? これにより、アクセスが直ちに取り消され、元に戻すことはできません。",
    
    # Billing
    "billing_page.col_date": "日付",
    
    # User Overview
    "user_overview.higher_plans": "{n} 個の上位プランを利用可能 — さらに多くのリクエスト、さらに多くのプロバイダー",
    "user_overview.upgrade_to": "{name} にアップグレード（{price}/月）",
    "user_overview.auth_header_desc": "すべてのエンドポイントで API トークンを {header} ヘッダーに含めます:",
    "user_overview.ep_chat_desc": "設定を使用してチャット リクエストを送信する",
    "user_overview.admin_access_desc": "管理者として、より短いモデル形式でグローバル構成にもアクセスできます:",
    "user_overview.token_required": "すべてのエンドポイントに API トークンが必要です。",
    
    # Usage
    "usage_page.activity_quotas_desc": "自動的にリセットされる時間ベースの制限",
    "usage_page.config_limits_desc": "アカウントへの永続的なリソース割り当て",
    "usage_page.resets_midnight": "UTC の午前 0 時にリセット",
    "usage_page.resets_in": "{h} 時間 {m} 分後にリセット",
    "usage_page.resets_on_1st": "毎月 1 日にリセット",
    "usage_page.resets_in_days": "{n} 日後にリセット",
    "usage_page.resets_in_days_plural": "{n} 日後にリセット",
    "usage_page.tokens_combined": "入力 + 出力を組み合わせたもの",
    "usage_page.remaining": "{n} 残り",
    "usage_page.ai_providers_desc": "構成済みのプロバイダー統合",
    "usage_page.rotations_desc": "負荷分散構成",
    "usage_page.autoselections_desc": "スマート ルーティング構成",
    "usage_page.unlimited_slots": "無制限のスロットが利用可能",
    "usage_page.pct_used_slots_free": "{pct}% 使用済み · {n} スロット空き",
    "usage_page.pct_used_slots_free_plural": "{pct}% 使用済み · {n} スロット空き",
    "usage_page.upgrade_desc": "より多くのリクエスト、プロバイダー、自動選択を利用できるようにプランをアップグレードしてください。",
    
    # Subscription
    "subscription_page.no_description": "説明がありません",
    "subscription_page.billing_payments_desc": "支払い方法を管理し、履歴を確認する",
    "subscription_page.upgrade_plan_desc": "利用可能なすべてのプランを表示",
    "subscription_page.edit_profile_desc": "アカウント設定を更新",
    "subscription_page.change_password_desc": "セキュリティ設定を更新",
    "subscription_page.no_payment_methods_desc": "プランをアップグレードしてサブスクリプションを管理するには、支払い方法を追加してください。",
    "subscription_page.go_to_billing": "請求と支払い方法へ",
}

print(f'Japanese translations: {len(ja_trans)} keys')

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

apply('ja', ja_trans)