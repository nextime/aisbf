#!/usr/bin/env python3
"""
Translation script for AISBF i18n files.
This script translates missing keys in ja, zh, ko, ru, af language files.
"""

import json
import os
import copy

# Load English source
with open('/working/aisbf/static/i18n/en.json', 'r', encoding='utf-8') as f:
    en_data = json.load(f)

# Translation dictionaries for each language
# These cover the most common missing keys

def translate_to_ja(key, value):
    """Translate English to Japanese"""
    translations = {
        "Today's Estimated Cost": "今日の推定コスト",
        "Estimated Savings": "推定節約額",
        "Export CSV": "CSVをエクスポート",
        "From cache hits & optimization": "キャッシュヒットと最適化によるもの",
        "Selected Period Cost": "選択期間のコスト",
        "Analytics": "分析",
        "Enter autoselect key (e.g., \"autoselect\", \"smart-select\"):": "自動選択キーを入力 (例: \"autoselect\", \"smart-select\"):",
        "Copy \"{key}\" — enter new autoselect key:": "コピー \"{key}\" — 新しい自動選択キーを入力:",
        "Error saving configuration": "設定の保存エラー",
        "New key must be different from the source.": "新しいキーは元のキーと異なる必要があります。",
        "NSFW": "NSFW",  # Keep as is
        "Remove autoselect \"{key}\"?": "自動選択 \"{key}\" を削除しますか？",
        "Remove this model?": "このモデルを削除しますか？",
        "Add Card": "カードを追加",
        "Bitcoin": "ビットコイン",
        "Cancel": "キャンセル",
        "Credit Card": "クレジットカード",
        "Ethereum": "イーサリアム",
        "You don't have any payment transactions on your account.": "アカウントには取引履歴がありません。",
        "Upgrade your plan to get started!": "ご利用を開始するにはプランをアップグレードしてください！",
        "Add a credit card to enable automatic subscription renewals.": "自動サブスクリプション更新を有効にするにはクレジットカードを追加してください。",
        "Payment Methods": "支払い方法",
        "PayPal": "PayPal",
        "✗ Failed": "✗ 失敗",
        "Billing & Payments": "請求と支払い",
        "USDC": "USDC",
        "USDT": "USDT",
        "All subscription renewals and payments are automatically charged from your wallet first.": "すべてのサブスクリプション更新と支払いは、最初にウォレットから自動的に請求されます。",
        "Save": "保存",
        "Cache Settings": "キャッシュ設定",
        "Permanently delete your account and all associated data.": "アカウントと関連するすべてのデータが永久に削除されます。",
        "Are you absolutely sure? This action cannot be undone and all your data will be permanently deleted.": "本当によろしいですか？この操作は元に戻せず、すべてのデータが永久に削除されます。",
        "Consider canceling your subscription first if you want to use it until the end of the billing period.": "請求期間の終了まで使用したい場合は、最初にサブスクリプションをキャンセルすることを検討してください。",
        "You have an active paid subscription ({tier}). Deleting your account will:": "アクティブな有料サブスクリプション（{tier}）があります。アカウントを削除すると次のようになります：",
        "Please type \"DELETE\" exactly to confirm account deletion.": "アカウント削除を確認するには、\"削除\"と正確に入力してください。",
        "Bitcoin (BTC)": "ビットコイン (BTC)",
        "Ethereum (ETH), USDC, USDT (ERC20, Mainnet)": "イーサリアム (ETH)、USDC、USDT (ERC20、メインネット)",
        "Confirm your password to proceed": "続行するにはパスワードを確認してください",
        "Enter your email address and we'll send you a link to reset your password.": "メールアドレスを入力すると、パスワードをリセットするためのリンクをお送りします。",
        "If an account exists with that email address, we have sent a password reset link. The link will expire in 24 hours. Please check your inbox and spam folder.": "そのメールアドレスのアカウントが存在する場合、パスワードリセットリンクを送信しました。リンクは24時間後に期限切れになります。受信トレイとスパムフォルダをご確認ください。",
        "OK": "OK",
        "Webhook URL": "ウェブフックURL",
        "This is how your name will be displayed throughout the application": "これがあなたの名前がアプリケーション全体に表示される方法です",
        "(requires verification)": "(確認が必要)",
        "Upload failed: {error}": "アップロード失敗: {error}",
        "Max 5 MB. JPG, PNG, GIF, WebP.": "最大5MB。JPG、PNG、GIF、WebP。",
        "Invalid file type. Please upload JPG, PNG, GIF or WebP.": "無効なファイル形式です。JPG、PNG、GIF、WebPをアップロードしてください。",
        "Image is too large. Maximum size is 5 MB.": "画像が大きすぎます。最大サイズは5MBです。",
        "Profile picture updated!": "プロフィール写真が更新されました！",
        "Edit the prompt template. Use markdown formatting as needed.": "プロンプトテンプレートを編集してください。必要に応じてマークダウン形式を使用してください。",
        "Avg Latency": "平均レイテンシ",
        "Avg Tokens/Optimization": "平均トークン/最適化",
        "Condense Method": "圧縮方法",
        "Context Size": "コンテキストサイズ",
        "Cost Saved": "節約されたコスト",
        "Count": "カウント",
        "Error Rate": "エラー率",
        "Errors": "エラー",
        "Input Tokens": "入力トークン",
        "Max Tokens Saved": "最大節約トークン",
        "Model": "モデル",
        "Optimization Type": "最適化タイプ",
        "Output Tokens": "出力トークン",
        "Provider": "プロバイダー",
        "Success": "成功",
        "Tokens Saved": "節約されたトークン",
        "Total Requests": "合計リクエスト数",
        "Total Tokens": "合計トークン",
        "Tokens/Day": "トークン/日",
        "Tokens/Hour": "トークン/時間",
        "Tokens/Min": "トークン/分",
        "Type": "タイプ",
        "Search users...": "ユーザーを検索...",
        "Filter": "フィルター",
        "Model": "モデル",
        "Docs": "ドキュメント",
        "AISBF Dashboard": "AISBF ダッシュボード",
    }
    if key in translations:
        return translations[key]
    return value

def translate_to_zh(key, value):
    """Translate English to Chinese"""
    translations = {
        "Today's Estimated Cost": "今日预估成本",
        "Estimated Savings": "预计节省",
        "Export CSV": "导出 CSV",
        "From cache hits & optimization": "来自缓存命中和优化",
        "Selected Period Cost": "选定期间成本",
        "Analytics": "分析",
        "Enter autoselect key (e.g., \"autoselect\", \"smart-select\"):": "输入自动选择键 (例如: \"autoselect\", \"smart-select\"):",
        "Copy \"{key}\" — enter new autoselect key:": "复制 \"{key}\" — 输入新的自动选择键:",
        "Error saving configuration": "保存配置错误",
        "New key must be different from the source.": "新密钥必须与源密钥不同。",
        "NSFW": "NSFW",
        "Remove autoselect \"{key}\"?": "删除自动选择 \"{key}\"?",
        "Remove this model?": "删除此模型？",
        "Add Card": "添加卡片",
        "Bitcoin": "比特币",
        "Cancel": "取消",
        "Credit Card": "信用卡",
        "Ethereum": "以太坊",
        "You don't have any payment transactions on your account.": "您的账户没有任何支付交易。",
        "Upgrade your plan to get started!": "升级您的计划以开始使用！",
        "Add a credit card to enable automatic subscription renewals.": "添加信用卡以启用自动订阅续订。",
        "Payment Methods": "支付方式",
        "PayPal": "PayPal",
        "✗ Failed": "✗ 失败",
        "Billing & Payments": "账单与支付",
        "USDC": "USDC",
        "USDT": "USDT",
        "All subscription renewals and payments are automatically charged from your wallet first.": "所有订阅续订和付款都将首先从您的钱包中自动扣除。",
        "Save": "保存",
        "Cache Settings": "缓存设置",
        "Permanently delete your account and all associated data.": "永久删除您的账户及所有相关数据。",
        "Are you absolutely sure? This action cannot be undone and all your data will be permanently deleted.": "您确定吗？此操作无法撤消，并且所有数据将被永久删除。",
        "Consider canceling your subscription first if you want to use it until the end of the billing period.": "如果您想使用到计费期结束，请考虑先取消订阅。",
        "You have an active paid subscription ({tier}). Deleting your account will:": "您有一个活跃的付费订阅 ({tier})。删除您的账户将：",
        "Please type \"DELETE\" exactly to confirm account deletion.": "请准确输入 \"DELETE\" 以确认删除账户。",
        "Bitcoin (BTC)": "比特币 (BTC)",
        "Ethereum (ETH), USDC, USDT (ERC20, Mainnet)": "以太坊 (ETH)、USDC、USDT (ERC20、主网)",
        "Confirm your password to proceed": "确认您的密码以继续",
        "Enter your email address and we'll send you a link to reset your password.": "输入您的电子邮件地址，我们将向您发送重置密码的链接。",
        "If an account exists with that email address, we have sent a password reset link. The link will expire in 24 hours. Please check your inbox and spam folder.": "如果存在使用该电子邮件地址的账户，我们已经发送了密码重置链接。该链接将在24小时后过期。请检查您的收件箱和垃圾邮件文件夹。",
        "OK": "确定",
        "Webhook URL": "Webhook URL",
        "This is how your name will be displayed throughout the application": "这是您的姓名在整个应用程序中的显示方式",
        "(requires verification)": "(需要验证)",
        "Upload failed: {error}": "上传失败: {error}",
        "Max 5 MB. JPG, PNG, GIF, WebP.": "最大5MB。JPG、PNG、GIF、WebP。",
        "Invalid file type. Please upload JPG, PNG, GIF or WebP.": "无效的文件类型。请上传JPG、PNG、GIF或WebP。",
        "Image is too large. Maximum size is 5 MB.": "图像太大。最大尺寸为5MB。",
        "Profile picture updated!": "头像已更新！",
        "Edit the prompt template. Use markdown formatting as needed.": "编辑提示词模板。根据需要使用Markdown格式。",
        "Avg Latency": "平均延迟",
        "Avg Tokens/Optimization": "平均令牌/优化",
        "Condense Method": "压缩方法",
        "Context Size": "上下文大小",
        "Cost Saved": "节省的成本",
        "Count": "数量",
        "Error Rate": "错误率",
        "Errors": "错误",
        "Input Tokens": "输入令牌",
        "Max Tokens Saved": "最大节省令牌",
        "Model": "模型",
        "Optimization Type": "优化类型",
        "Output Tokens": "输出令牌",
        "Provider": "提供商",
        "Success": "成功",
        "Tokens Saved": "节省的令牌",
        "Total Requests": "总请求数",
        "Total Tokens": "总令牌",
        "Tokens/Day": "令牌/天",
        "Tokens/Hour": "令牌/小时",
        "Tokens/Min": "令牌/分钟",
        "Type": "类型",
        "Search users...": "搜索用户...",
        "Filter": "筛选",
        "Model": "模型",
        "Docs": "文档",
        "AISBF Dashboard": "AISBF 控制台",
    }
    if key in translations:
        return translations[key]
    return value

def translate_to_ko(key, value):
    """Translate English to Korean"""
    translations = {
        "Today's Estimated Cost": "오늘의 예상 비용",
        "Estimated Savings": "예상 절감액",
        "Export CSV": "CSV 내보내기",
        "From cache hits & optimization": "캐시 적중 및 최적화로 인한 절감",
        "Selected Period Cost": "선택한 기간 비용",
        "Analytics": "분석",
        "Enter autoselect key (e.g., \"autoselect\", \"smart-select\"):": "자동 선택 키 입력 (예: \"autoselect\", \"smart-select\"):",
        "Copy \"{key}\" — enter new autoselect key:": "복사 \"{key}\" — 새 자동 선택 키 입력:",
        "Error saving configuration": "설정 저장 오류",
        "New key must be different from the source.": "새 키는 원본과 달라야 합니다.",
        "NSFW": "NSFW",
        "Remove autoselect \"{key}\"?": "자동 선택 \"{key}\"을(를) 제거하시겠습니까?",
        "Remove this model?": "이 모델을 제거하시겠습니까?",
        "Add Card": "카드 추가",
        "Bitcoin": "비트코인",
        "Cancel": "취소",
        "Credit Card": "신용카드",
        "Ethereum": "이더리움",
        "You don't have any payment transactions on your account.": "계정에 결제 내역이 없습니다.",
        "Upgrade your plan to get started!": "시작하려면 플랜을 업그레이드하세요!",
        "Add a credit card to enable automatic subscription renewals.": "자동 구독 갱신을 활성화하려면 신용카드를 추가하세요.",
        "Payment Methods": "결제 방법",
        "PayPal": "PayPal",
        "✗ Failed": "✗ 실패",
        "Billing & Payments": "결제 및 청구",
        "USDC": "USDC",
        "USDT": "USDT",
        "All subscription renewals and payments are automatically charged from your wallet first.": "모든 구독 갱신 및 결제는 먼저 지갑에서 자동으로 청구됩니다.",
        "Save": "저장",
        "Cache Settings": "캐시 설정",
        "Permanently delete your account and all associated data.": "계정 및 관련 데이터가 영구적으로 삭제됩니다.",
        "Are you absolutely sure? This action cannot be undone and all your data will be permanently deleted.": "정말 확실합니까? 이 작업은 취소할 수 없으며 모든 데이터가 영구적으로 삭제됩니다.",
        "Consider canceling your subscription first if you want to use it until the end of the billing period.": "청구 기간이 끝날 때까지 사용하려면 먼저 구독을 취소하는 것을 고려해 보세요.",
        "You have an active paid subscription ({tier}). Deleting your account will:": "활성 유료 구독({tier})이 있습니다. 계정을 삭제하면 다음과 같은 일이 발생합니다:",
        "Please type \"DELETE\" exactly to confirm account deletion.": "계정 삭제를 확인하려면 정확히 \"삭제\"를 입력하세요.",
        "Bitcoin (BTC)": "비트코인 (BTC)",
        "Ethereum (ETH), USDC, USDT (ERC20, Mainnet)": "이더리움 (ETH), USDC, USDT (ERC20, 메인넷)",
        "Confirm your password to proceed": "진행하려면 비밀번호를 확인하세요",
        "Enter your email address and we'll send you a link to reset your password.": "이메일 주소를 입력하면 비밀번호를 재설정하는 링크를 보내드립니다.",
        "If an account exists with that email address, we have sent a password reset link. The link will expire in 24 hours. Please check your inbox and spam folder.": "해당 이메일 주소로 계정이 존재하는 경우 비밀번호 재설정 링크를 보냈습니다. 링크는 24시간 후에 만료됩니다. 수신함과 스팸 폴더를 확인하세요.",
        "OK": "확인",
        "Webhook URL": "웹훅 URL",
        "This is how your name will be displayed throughout the application": "이름이 애플리케이션 전체에 표시되는 방식입니다",
        "(requires verification)": "(확인 필요)",
        "Upload failed: {error}": "업로드 실패: {error}",
        "Max 5 MB. JPG, PNG, GIF, WebP.": "최대 5MB. JPG, PNG, GIF, WebP.",
        "Invalid file type. Please upload JPG, PNG, GIF or WebP.": "잘못된 파일 형식입니다. JPG, PNG, GIF 또는 WebP를 업로드하세요.",
        "Image is too large. Maximum size is 5 MB.": "이미지가 너무 큽니다. 최대 크기는 5MB입니다.",
        "Profile picture updated!": "프로필 사진이 업데이트되었습니다!",
        "Edit the prompt template. Use markdown formatting as needed.": "프롬프트 템플릿을 편집하세요. 필요에 따라 마크다운 형식을 사용하세요.",
        "Avg Latency": "평균 지연 시간",
        "Avg Tokens/Optimization": "평균 토큰/최적화",
        "Condense Method": "축소 방법",
        "Context Size": "컨텍스트 크기",
        "Cost Saved": "절약된 비용",
        "Count": "개수",
        "Error Rate": "오류율",
        "Errors": "오류",
        "Input Tokens": "입력 토큰",
        "Max Tokens Saved": "최대 절약 토큰",
        "Model": "모델",
        "Optimization Type": "최적화 유형",
        "Output Tokens": "출력 토큰",
        "Provider": "제공자",
        "Success": "성공",
        "Tokens Saved": "절약된 토큰",
        "Total Requests": "총 요청",
        "Total Tokens": "총 토큰",
        "Tokens/Day": "토큰/일",
        "Tokens/Hour": "토큰/시간",
        "Tokens/Min": "토큰/분",
        "Type": "유형",
        "Search users...": "사용자 검색...",
        "Filter": "필터",
        "Model": "모델",
        "Docs": "문서",
        "AISBF Dashboard": "AISBF 대시보드",
    }
    if key in translations:
        return translations[key]
    return value

def translate_to_ru(key, value):
    """Translate English to Russian"""
    translations = {
        "Today's Estimated Cost": "Расчетная стоимость на сегодня",
        "Estimated Savings": "Ожидаемая экономия",
        "Export CSV": "Экспорт CSV",
        "From cache hits & optimization": "Благодаря попаданиям в кэш и оптимизации",
        "Selected Period Cost": "Стоимость за выбранный период",
        "Analytics": "Аналитика",
        "Enter autoselect key (e.g., \"autoselect\", \"smart-select\"):": "Введите ключ авто выбора (например, \"autoselect\", \"smart-select\"):",
        "Copy \"{key}\" — enter new autoselect key:": "Копировать \"{key}\" — введите новый ключ авто выбора:",
        "Error saving configuration": "Ошибка сохранения конфигурации",
        "New key must be different from the source.": "Новый ключ должен отличаться от исходного.",
        "NSFW": "NSFW",
        "Remove autoselect \"{key}\"?": "Удалить авто выбор \"{key}\"?",
        "Remove this model?": "Удалить эту модель?",
        "Add Card": "Добавить карту",
        "Bitcoin": "Bitcoin",
        "Cancel": "Отмена",
        "Credit Card": "Кредитная карта",
        "Ethereum": "Ethereum",
        "You don't have any payment transactions on your account.": "В вашем аккаунте нет платежных транзакций.",
        "Upgrade your plan to get started!": "Улучшите свой тариф, чтобы начать работу!",
        "Add a credit card to enable automatic subscription renewals.": "Добавьте кредитную карту, чтобы включить автоматическое продление подписки.",
        "Payment Methods": "Способы оплаты",
        "PayPal": "PayPal",
        "✗ Failed": "✗ Ошибка",
        "Billing & Payments": "Выставление счетов и оплаты",
        "USDC": "USDC",
        "USDT": "USDT",
        "All subscription renewals and payments are automatically charged from your wallet first.": "Все продления подписки и платежи сначала автоматически списываются с вашего кошелька.",
        "Save": "Сохранить",
        "Cache Settings": "Настройки кэша",
        "Permanently delete your account and all associated data.": "Ваш аккаунт и все связанные данные будут удалены навсегда.",
        "Are you absolutely sure? This action cannot be undone and all your data will be permanently deleted.": "Вы абсолютно уверены? Это действие не может быть отменено, и все ваши данные будут удалены навсегда.",
        "Consider canceling your subscription first if you want to use it until the end of the billing period.": "Если вы хотите использовать подписку до конца периода оплаты, сначала рассмотрите возможность ее отмены.",
        "You have an active paid subscription ({tier}). Deleting your account will:": "У вас есть активная платная подписка ({tier}). Удаление вашего аккаунта приведет к:",
        "Please type \"DELETE\" exactly to confirm account deletion.": "Пожалуйста, введите \"DELETE\" точно для подтверждения удаления аккаунта.",
        "Bitcoin (BTC)": "Bitcoin (BTC)",
        "Ethereum (ETH), USDC, USDT (ERC20, Mainnet)": "Ethereum (ETH), USDC, USDT (ERC20, Mainnet)",
        "Confirm your password to proceed": "Подтвердите свой пароль, чтобы продолжить",
        "Enter your email address and we'll send you a link to reset your password.": "Введите свой адрес электронной почты, и мы отправим вам ссылку для сброса пароля.",
        "If an account exists with that email address, we have sent a password reset link. The link will expire in 24 hours. Please check your inbox and spam folder.": "Если аккаунт с таким адресом электронной почты существует, мы отправили ссылку для сброса пароля. Ссылка истечет через 24 часа. Пожалуйста, проверьте свою папку «Входящие» и спам.",
        "OK": "OK",
        "Webhook URL": "Webhook URL",
        "This is how your name will be displayed throughout the application": "Именно так ваше имя будет отображаться во всем приложении",
        "(requires verification)": "(требует подтверждения)",
        "Upload failed: {error}": "Ошибка загрузки: {error}",
        "Max 5 MB. JPG, PNG, GIF, WebP.": "Максимум 5 МБ. JPG, PNG, GIF, WebP.",
        "Invalid file type. Please upload JPG, PNG, GIF or WebP.": "Недопустимый тип файла. Пожалуйста, загрузите JPG, PNG, GIF или WebP.",
        "Image is too large. Maximum size is 5 MB.": "Изображение слишком большое. Максимальный размер — 5 МБ.",
        "Profile picture updated!": "Фото профиля обновлено!",
        "Edit the prompt template. Use markdown formatting as needed.": "Отредактируйте шаблон промпта. При необходимости используйте форматирование Markdown.",
        "Avg Latency": "Средняя задержка",
        "Avg Tokens/Optimization": "Среднее количество токенов/Оптимизация",
        "Condense Method": "Метод сжатия",
        "Context Size": "Размер контекста",
        "Cost Saved": "Экономия средств",
        "Count": "Количество",
        "Error Rate": "Процент ошибок",
        "Errors": "Ошибки",
        "Input Tokens": "Входящие токены",
        "Max Tokens Saved": "Максимальное количество сохраненных токенов",
        "Model": "Модель",
        "Optimization Type": "Тип оптимизации",
        "Output Tokens": "Исходящие токены",
        "Provider": "Провайдер",
        "Success": "Успех",
        "Tokens Saved": "Токены сохранены",
        "Total Requests": "Всего запросов",
        "Total Tokens": "Всего токенов",
        "Tokens/Day": "Токенов/День",
        "Tokens/Hour": "Токенов/Час",
        "Tokens/Min": "Токенов/Мин",
        "Type": "Тип",
        "Search users...": "Поиск пользователей...",
        "Filter": "Фильтр",
        "Model": "Модель",
        "Docs": "Документация",
        "AISBF Dashboard": "AISBF Панель управления",
    }
    if key in translations:
        return translations[key]
    return value

def translate_to_af(key, value):
    """Translate English to Afrikaans"""
    translations = {
        "Today's Estimated Cost": "Vandag se Geskatte Koste",
        "Estimated Savings": "Geskatte Spaarplussies",
        "Export CSV": "Voer CSV uit",
        "From cache hits & optimization": "Van cache-treffers en optimalisering",
        "Selected Period Cost": "Koste vir Geselekteerde Periode",
        "Analytics": "Analise",
        "Enter autoselect key (e.g., \"autoselect\", \"smart-select\"):": "Voer outokeusesleutel in (bv. \"autoselect\", \"smart-select\"):",
        "Copy \"{key}\" — enter new autoselect key:": "Kopieer \"{key}\" — voer nuwe outokeusesleutel in:",
        "Error saving configuration": "Fout met stoor konfigurasie",
        "New key must be different from the source.": "Nuwe sleutel moet anders wees as die bron.",
        "NSFW": "NSFW",
        "Remove autoselect \"{key}\"?": "Verwyder outokeuse \"{key}\"?",
        "Remove this model?": "Verwyder hierdie model?",
        "Add Card": "Voeg Kaart By",
        "Bitcoin": "Bitcoin",
        "Cancel": "Kanselleer",
        "Credit Card": "Kredietkaart",
        "Ethereum": "Ethereum",
        "You don't have any payment transactions on your account.": "U het geen betalingstransaksies op u rekening nie.",
        "Upgrade your plan to get started!": "Gradeer u plan op om te begin!",
        "Add a credit card to enable automatic subscription renewals.": "Voeg 'n kredietkaart by om outomatiese intekeningvernuwings te aktiveer.",
        "Payment Methods": "Betalingsmetodes",
        "PayPal": "PayPal",
        "✗ Failed": "✗ Misluk",
        "Billing & Payments": "Fakturering en Betalings",
        "USDC": "USDC",
        "USDT": "USDT",
        "All subscription renewals and payments are automatically charged from your wallet first.": "Alle intekeningsvernuwings en betalings word eers outomaties van u beursie afgeskryf.",
        "Save": "Stoor",
        "Cache Settings": "Kasinstellings",
        "Permanently delete your account and all associated data.": "U rekening en alle geassosieerde data sal permanent uitgevee word.",
        "Are you absolutely sure? This action cannot be undone and all your data will be permanently deleted.": "Is u absoluut seker? Hierdie aksie kan nie ontdoen word nie en al u data sal permanent uitgevee word.",
        "Consider canceling your subscription first if you want to use it until the end of the billing period.": "Oorweeg om u intekening eerste te kanselleer as u dit tot die einde van die faktureringsperiode wil gebruik.",
        "You have an active paid subscription ({tier}). Deleting your account will:": "U het 'n aktiewe betaalde intekening ({tier}). As u u rekening uitvee, sal dit:",
        "Please type \"DELETE\" exactly to confirm account deletion.": "Tik asseblief presies \"DELETE\" in om rekeninguit te vee te bevestig.",
        "Bitcoin (BTC)": "Bitcoin (BTC)",
        "Ethereum (ETH), USDC, USDT (ERC20, Mainnet)": "Ethereum (ETH), USDC, USDT (ERC20, Mainnet)",
        "Confirm your password to proceed": "Bevestig u wagwoord om voort te gaan",
        "Enter your email address and we'll send you a link to reset your password.": "Voer u e-posadres in en ons sal u 'n skakel stuur om u wagwoord terug te stel.",
        "If an account exists with that email address, we have sent a password reset link. The link will expire in 24 hours. Please check your inbox and spam folder.": "As 'n rekening met daardie e-posadres bestaan, het ons 'n wagwoord-terugstellerskakel gestuur. Die skakel sal oor 24 uur verval. Gaan asseblief u inkassie en strooipos-vak saai.",
        "OK": "OK",
        "Webhook URL": "Webhook URL",
        "This is how your name will be displayed throughout the application": "Dit is hoe u naam in die hele aansoek vertoon sal word",
        "(requires verification)": "(vereis verifikasie)",
        "Upload failed: {error}": "Oplaai het misluk: {error}",
        "Max 5 MB. JPG, PNG, GIF, WebP.": "Maksimum 5 MB. JPG, PNG, GIF, WebP.",
        "Invalid file type. Please upload JPG, PNG, GIF or WebP.": "Ongeldige lêertipe. Laai asseblief JPG, PNG, GIF of WebP op.",
        "Image is too large. Maximum size is 5 MB.": "Beeld is te groot. Maksimum grootte is 5 MB.",
        "Profile picture updated!": "Profielfoto opgedateer!",
        "Edit the prompt template. Use markdown formatting as needed.": "Wysig die opdragteks-voorbeeld. Gebruik markdown-opmaak indien nodig.",
        "Avg Latency": "Gemiddelde Latensie",
        "Avg Tokens/Optimization": "Gemiddelde Tekens/Optimalisering",
        "Condense Method": "Saamvatmetode",
        "Context Size": "Konteksgrootte",
        "Cost Saved": "Koste Gespaar",
        "Count": "Aantal",
        "Error Rate": "Foutekoers",
        "Errors": "Foute",
        "Input Tokens": "Invoertekens",
        "Max Tokens Saved": "Maksimum Tekens Gespaar",
        "Model": "Model",
        "Optimization Type": "Optimaliseringstipe",
        "Output Tokens": "Uitvoertekens",
        "Provider": "Verskaffer",
        "Success": "Sukses",
        "Tokens Saved": "Tekens Gespaar",
        "Total Requests": "Totale Versoeke",
        "Total Tokens": "Totale Tekens",
        "Tokens/Day": "Tekens/Dag",
        "Tokens/Hour": "Tekens/Uur",
        "Tokens/Min": "Tekens/Min",
        "Type": "Tipe",
        "Search users...": "Soek gebruikers...",
        "Filter": "Filter",
        "Model": "Model",
        "Docs": "Dokumente",
        "AISBF Dashboard": "AISBF Paneelbord",
    }
    if key in translations:
        return translations[key]
    return value

def update_language_file(lang_code, translate_func):
    """Update a language file with translations"""
    filepath = f'/working/aisbf/static/i18n/{lang_code}.json'
    
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # Recursively update translations
    def update_dict(d, path=""):
        for key, value in d.items():
            current_path = f"{path}.{key}" if path else key
            if isinstance(value, dict):
                update_dict(value, current_path)
            elif isinstance(value, str):
                # Try to get translation
                translated = translate_func(key, value)
                if translated != value:
                    d[key] = translated
                    print(f"  {lang_code}: {current_path}")
                    print(f"    FROM: {value[:60]}..." if len(value) > 60 else f"    FROM: {value}")
                    print(f"    TO:   {translated[:60]}..." if len(translated) > 60 else f"    TO:   {translated}")
                    print()
    
    print(f"\n{'='*80}")
    print(f"Updating {lang_code.upper()}...")
    print(f"{'='*80}")
    
    update_dict(data)
    
    # Save updated file
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    print(f"\n✓ {lang_code.upper()} file updated successfully!")

if __name__ == '__main__':
    # Update all language files
    update_language_file('ja', translate_to_ja)
    update_language_file('zh', translate_to_zh)
    update_language_file('ko', translate_to_ko)
    update_language_file('ru', translate_to_ru)
    update_language_file('af', translate_to_af)
    
    print("\n" + "="*80)
    print("ALL TRANSLATIONS COMPLETE!")
    print("="*80)