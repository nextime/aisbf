#!/usr/bin/env python3
# Afrikaans translations for missing keys
af_trans = {
    # Providers section
    "providers.nsfw": "NSFW",
    "providers.models_fetch_error": "❌ Fout: {error}",
    "providers.rate_limit_hint": "Tyvertraging tussen versoeke aan hierdie verskaffer",
    "providers.kiro_auth_hint": "Kies een verifikasiemetode: Kiro IDE-geloofsbriewe (creds_file), kiro-cli-databasis (sqlite_db), of direkte geloofsbriewe (refresh_token + client_id/secret).",
    "providers.kilo_auth_hint": "Kies jou verifikasiemetode: API-sleutel (aanbeveel vir eenvoud) of OAuth2-toestemmingsverlening.",
    "providers.workspace_id_hint": "Werkruimte-ID vir Duitsland-streek (verstek: \"Default Workspace\")",
    "providers.kiro_aws_region_hint": "AWS-streek vir Kiro API (verstek: us-east-1)",
    "providers.kiro_sqlite_hint": "Pad na kiro-cli SQLite-databasis",
    "providers.kiro_refresh_hint": "Kiro-verfrisgetoeken vir direkte verifikasie",
    "providers.kiro_profile_arn_hint": "AWS CodeWhisperer profiel ARN (opsioneel)",
    "providers.kiro_client_id_hint": "OAuth-kliënt-ID vir AWS SSO OIDC-verifikasie",
    "providers.kiro_client_secret_hint": "OAuth-kliëntgeheim vir AWS SSO OIDC-verifikasie",
    "providers.kiro_upload_creds_hint": "Laai Kiro IDE-geloofsbriewe JSON-lêer op",
    "providers.kiro_upload_sqlite_hint": "Laai kiro-cli SQLite-databaselêer op",
    "providers.provider_key_hint": "Dit sal gebruik word as die verskaffer-ID in die konfigurasie en API-eindpunte",
    "providers.subscription_based_hint": "Indien gekies, is hierdie verskaffer op subscriptie gebaseer en sal koste as $0 bereken. Gebruik word steeds voor analitiek gespoor.",
    "providers.price_prompt_hint": "Los leeg om verstekpryse te gebruik. Voorbeelde: OpenAI GPT-4: $10, Anthropic Claude: $15, Google Gemini: $1.25",
    "providers.price_completion_hint": "Los leeg om verstekpryse te gebruik. Voorbeelde: OpenAI GPT-4: $30, Anthropic Claude: $75, Google Gemini: $5.00",
    "providers.native_caching_hint": "Provider-eie cachingfunksies (Anthropic cache_control, Google Context Caching, OpenAI en Kilo-versoenbare API's) vir kostevermindering.",
    "providers.enable_native_caching_hint": "Aktiveer provider-eie caching vir kostevermindering (50-70% besparings vir ondersteunde verskaffers)",
    
    # Rotations
    "rotations.copy_prompt": "Kopieer \"{key}\" — voer nuwe rotasiesleutel in:",
    "rotations.add_prompt": "Voer rotasiesleutel in (bv. \"coding\", \"general\"):",
    "rotations.remove_confirm": "Verwyder rotasie \"{key}\"?",
    "rotations.remove_provider_confirm": "Verwyder hierdie verskaffer?",
    
    # Wallet
    "wallet_page.charged_to_card": "Gebied aan jou verstekkredietkaart:",
    "wallet_page.invalid_amount": "Kies of voer 'n bedrag tussen {min} en {max} in.",
    "wallet_page.invalid_amount_title": "Ongeldige Bedrag",
    
    # Rate Limits
    "rate_limits_page.reset_confirm": "Reset koersbeperker vir {provider}?",
    "rate_limits_page.reset_confirm_title": "Reset Koersbeperker",
    "rate_limits_page.reset_all_confirm": "Reset alle koersbeperkers? Dit sal alle geleerde koersbeperkings uitvee.",
    "rate_limits_page.reset_all_success": "Alle koersbeperkers suksesvol gereset",
    
    # Signup
    "signup_page.username_hint": "3-50 karakters, letters, syfers, onderstrepings, koppeltekens en punte net",
    "signup_page.email_hint": "Jy sal 'n verifikasie-e-pos ontvang by hierdie adres",
    "signup_page.password_hint": "Minstens 8 karakters met hoofletters, kleinletters en syfers",
    
    # Reset
    "reset_page.intro": "Voer jou nuwe wagwoord hieronder in.",
    "reset_page.password_hint": "Minstens 8 karakters lank",
    "reset_page.success": "Jou wagwoord is suksesvol teruggestel. Jy kan nou aanmeld met jou nuwe wagwoord.",
    "reset_page.go_to_login": "Gaan Aanmeld",
    "reset_page.invalid_token": "Hierdie wagwoordterugstelskakel is ongeldig of het verval. Versoek 'n nuwe wagwoordterugstellingskakel.",
    "reset_page.request_new": "Versoek Nuwe Terugstellsakel",
    
    # Tokens
    "tokens_page.description_placeholder": "bv. My app, Tuisbediener …",
    "tokens_page.scope_api_hint": "(proxyversoeke)",
    "tokens_page.scope_mcp_hint": "(agentgereedskap)",
    "tokens_page.auth_header_desc": "Voeg die token by elke versoek in die {header}-kopstuk:",
    "tokens_page.token_scopes": "Tokense bereike:",
    "tokens_page.scope_api_access": "Slegs API-bevoorsorging-eindpunte ({path})",
    "tokens_page.scope_mcp_access": "Slegs MCP-gereedskap-eindpunte ({path})",
    "tokens_page.scope_both_access": "Beide API- en MCP-eindpunte",
    "tokens_page.available_endpoints": "Beskikbare eindpunte:",
    "tokens_page.col_endpoint": "Eindpunt",
    "tokens_page.example_commands": "Voorbeeld-kurlopdrae:",
    "tokens_page.delete_confirm": "Vee hierdie API-token uit? Dit sal onmiddellik toegang herroep en kan nie ontdoen word nie.",
    
    # Billing
    "billing_page.col_date": "Datum",
    
    # User Overview
    "user_overview.higher_plans": "{n} hoër planne beskikbaar — meer versoeke, meer verskaffers",
    "user_overview.upgrade_to": "Gradeer op na {name} vir {price}/maand",
    "user_overview.auth_header_desc": "Sluit jou API-token in in die {header}-kopstuk:",
    "user_overview.ep_chat_desc": "Stuur kletsversoeke deur jou konfigurasies te gebruik",
    "user_overview.admin_access_desc": "As 'n admin het jy ook toegang tot globale konfigurasies via korter modelformate:",
    "user_overview.token_required": "Jou API-token word vereis vir alle eindpunte.",
    
    # Usage
    "usage_page.activity_quotas_desc": "Tyd-gebaseerde beperkings wat outomaties teruggestel word",
    "usage_page.config_limits_desc": "Voortgesette hulpbron-toewysings vir jou rekening",
    "usage_page.resets_midnight": "Terugstelling om middernag UTC",
    "usage_page.resets_in": "Terugstelling oor {h}h {m}m",
    "usage_page.resets_on_1ste": "Terugstelling op die 1ste",
    "usage_page.resets_in_days": "Terugstelling oor {n} dag",
    "usage_page.resets_in_days_plural": "Terugstelling oor {n} dae",
    "usage_page.tokens_combined": "Invoer + uitvoer gekombineer",
    "usage_page.remaining": "{n} oor",
    "usage_page.ai_providers_desc": "Geconfigureerde verskaffer-integrasies",
    "usage_page.rotations_desc": "Ladingbalansieringskonfigurasies",
    "usage_page.autoselections_desc": "Slim roeteringkonfigurasies",
    "usage_page.unlimited_slots": "Onbeperkte slots beskikbaar",
    "usage_page.pct_used_slots_free": "{pct}% gebruik · {n} slot vry",
    "usage_page.pct_used_slots_free_plural": "{pct}% gebruik · {n} slots vry",
    "usage_page.upgrade_desc": "Gradeer jou plan op om meer versoeke, verskaffers en outokeuses te ontsluit.",
    
    # Subscription
    "subscription_page.no_description": "Geen beskrywing beskikbaar",
    "subscription_page.billing_payments_desc": "Bestuur betalingsmetodes en kyk na geskiedenis",
    "subscription_page.upgrade_plan_desc": "Bekyk alle beskikbare planne",
    "subscription_page.edit_profile_desc": "Dateer rekeninginstellings op",
    "subscription_page.change_password_desc": "Update sekuriteitinstellings",
    "subscription_page.no_payment_methods_desc": "Voeg 'n kredietkaart by om jou plan te gradeer en subscripties te bestuur.",
    "subscription_page.go_to_billing": "Gaan na Fakturering & Betalingsmetodes",
}

print(f'Afrikaans translations: {len(af_trans)} keys')

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

apply('af', af_trans)