/*
 * Copyright (C) 2026 Stefy Lanza <stefy@nexlab.net>
 *
 * AISBF i18n (Internationalization) System
 * 
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 */

(function() {
    'use strict';

    const AVAILABLE_LANGUAGES = {
        'en': 'English',
        'de': 'Deutsch',
        'fr': 'Français',
        'es': 'Español',
        'pt': 'Português',
        'it': 'Italiano',
        'ru': 'Русский',
        'zh': '中文',
        'ja': '日本語',
        'ko': '한국어',
        'ar': 'العربية',
        'hi': 'हिन्दी',
        'tr': 'Türkçe',
        'pl': 'Polski',
        'nl': 'Nederlands',
        'sv': 'Svenska',
        'da': 'Dansk',
        'fi': 'Suomi',
        'nb': 'Norsk',
        'cs': 'Čeština',
        'sk': 'Slovenčina',
        'hu': 'Magyar',
        'ro': 'Română',
        'uk': 'Українська',
        'el': 'Ελληνικά',
        'he': 'עברית',
        'fa': 'فارسی',
        'id': 'Bahasa Indonesia',
        'th': 'ไทย',
        'vi': 'Tiếng Việt',
        'ms': 'Bahasa Melayu',
        'bn': 'বাংলা',
        'xh': 'isiXhosa',
        'zu': 'isiZulu',
        'af': 'Afrikaans',
        'eo': 'Esperanto',
        'qya': 'Quenya (Elvish)',
        'tlh': 'tlhIngan Hol (Klingon)',
        'vul': 'Vulcan'
    };

    // Detect base path from this script's src so it works behind a reverse proxy prefix
    const _scriptSrc = (document.currentScript && document.currentScript.src) || '/dashboard/static/i18n.js';
    const _staticBase = _scriptSrc.replace(/\/i18n\.js$/, '');

    let currentLang = 'en';
    let translations = {};
    let fallbackTranslations = {};

    // Get user-specific storage key
    function getStorageKey() {
        const username = document.body.dataset.username || '__guest__';
        return 'aisbf_lang_' + username;
    }

    // Deep get with fallback to English
    function getTranslation(path) {
        const keys = path.split('.');
        let value = translations;
        let fallback = fallbackTranslations;

        // Try to get from current language
        for (const key of keys) {
            if (value && typeof value === 'object' && key in value) {
                value = value[key];
            } else {
                value = null;
                break;
            }
        }

        // If found and is a string, return it
        if (typeof value === 'string') {
            return value;
        }

        // Fallback to English
        for (const key of keys) {
            if (fallback && typeof fallback === 'object' && key in fallback) {
                fallback = fallback[key];
            } else {
                fallback = null;
                break;
            }
        }

        return typeof fallback === 'string' ? fallback : path;
    }

    // Replace {n} placeholders
    function interpolate(text, params) {
        if (!params) return text;
        return text.replace(/\{(\w+)\}/g, (match, key) => {
            return params.hasOwnProperty(key) ? params[key] : match;
        });
    }

    // Translate a single element
    function translateElement(el) {
        const key = el.dataset.i18n;
        if (!key) return;

        const translation = getTranslation(key);
        
        // Handle different element types
        if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
            if (el.placeholder) {
                el.placeholder = translation;
            }
        } else {
            el.textContent = translation;
        }
    }

    // Translate all elements with data-i18n attribute
    function translatePage() {
        document.querySelectorAll('[data-i18n]').forEach(translateElement);
    }

    // Load language file
    async function loadLanguage(lang) {
        try {
            const response = await fetch(`${_staticBase}/i18n/${lang}.json`);
            if (!response.ok) throw new Error('Language file not found');
            return await response.json();
        } catch (error) {
            console.error(`Failed to load language ${lang}:`, error);
            return null;
        }
    }

    // Set language
    async function setLanguage(lang) {
        if (!AVAILABLE_LANGUAGES[lang]) {
            console.warn(`Language ${lang} not available, falling back to English`);
            lang = 'en';
        }

        // Load the selected language
        const langData = await loadLanguage(lang);
        if (!langData) {
            console.error(`Failed to load ${lang}, using English`);
            lang = 'en';
            translations = await loadLanguage('en') || {};
        } else {
            translations = langData;
        }

        // Always load English as fallback (unless we're already using English)
        if (lang !== 'en') {
            fallbackTranslations = await loadLanguage('en') || {};
        } else {
            fallbackTranslations = translations;
        }

        currentLang = lang;
        localStorage.setItem(getStorageKey(), lang);
        document.documentElement.setAttribute('lang', lang);

        // Translate the page
        translatePage();

        // Update language selector if it exists
        updateLanguageSelector();
    }

    // Update language selector UI
    function updateLanguageSelector() {
        document.querySelectorAll('.lang-btn').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.lang === currentLang);
        });
    }

    // Initialize
    async function init() {
        // Get saved language or detect from browser
        const savedLang = localStorage.getItem(getStorageKey());
        const browserLang = navigator.language.split('-')[0];
        const initialLang = savedLang || (AVAILABLE_LANGUAGES[browserLang] ? browserLang : 'en');

        await setLanguage(initialLang);
        document.dispatchEvent(new CustomEvent('i18n:ready', { detail: { lang: currentLang } }));
    }

    // Public API
    window.i18n = {
        t: getTranslation,
        setLanguage: setLanguage,
        getCurrentLanguage: () => currentLang,
        getAvailableLanguages: () => AVAILABLE_LANGUAGES,
        translatePage: translatePage,
        interpolate: interpolate
    };

    // Auto-initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
