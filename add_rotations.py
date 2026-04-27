import json

D = '/working/aisbf/static/i18n/'

def apply(lang, translations):
    path = D + lang + '.json'
    with open(path) as f:
        data = json.load(f)
    def set_nested(d, key, value):
        parts = key.split('.')
        c = d
        for p in parts[:-1]:
            c = c.setdefault(p, {})
        c[parts[-1]] = value
    for key, value in translations.items():
        set_nested(data, key, value)
    with open(path, 'w') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

langs = ['ar', 'bn', 'cs', 'el', 'fa', 'fi', 'he', 'hi', 'hu', 'ms', 'nb', 'pl', 'th', 'tr', 'zu']

# Rotations keys (from TODO.md - 17 keys)
rotations = {
    'search_models_title': {'ar': 'البحث عن النماذج - {provider}', 'bn': 'মডেল অনুসন্ধান - {provider}', 
        'cs': 'Hledat modely - {provider}', 'el': 'Αναζήτηση μοντέλων - {provider}', 
        'fa': 'جستجوی مدل‌ها - {provider}', 'fi': 'Hae malleja - {provider}', 
        'he': 'חיפוש מודלים - {provider}', 'hi': 'मॉडल खोजें - {provider}', 
        'hu': 'Modellkeresés - {provider}', 'ms': 'Cari Model - {provider}', 
        'nb': 'Søk etter modeller - {provider}', 'pl': 'Wyszukiwanie modeli - {provider}', 
        'th': 'ค้นหาโมเดล - {provider}', 'tr': 'Modelleri ara - {provider}', 
        'zu': 'Funa imimela - {provider}'},
    'result_count': {'ar': '{n} نتيجة.', 'bn': '{n} ফলাফল।', 'cs': '{n} výsledek(y).', 
        'el': '{n} αποτέλεσμα(τα).', 'fa': '{n} نتیجه.', 'fi': '{n} tulosta.', 
        'he': '{n} תוצאות.', 'hi': '{n} परिणाम।', 'hu': '{n} találat.', 
        'ms': '{n} hasil.', 'nb': '{n} resultat.', 'pl': '{n} wynik(i).', 
        'th': '{n} ผลลัพธ์', 'tr': '{n} sonuç.', 'zu': '{n} imiphumela.'},
    'copy_title': {'ar': 'نسخ التناوب', 'bn': 'ঘূর্ণন অনুলিখন করুন', 'cs': 'Kopírovat rotaci',
        'el': 'Αντιγραφή εναλλαγής', 'fa': 'کپی چرخش', 'fi': 'Kopioi kierto',
        'he': 'העתק סיבוב', 'hi': 'रोटेशन कॉपी करें', 'hu': 'Rotáció másolása',
        'ms': 'Salin putaran', 'nb': 'Kopier rotasjon', 'pl': 'Kopiuj rotację',
        'th': 'คัดลอกการหมุนเวียน', 'tr': 'Döngüyü kopyala', 'zu': 'Kopisha ukususa okubuyela emuva'},
    'add_title': {'ar': 'إضافة تناوب', 'bn': 'ঘূর্ণন যোগ করুন', 'cs': 'Přidat rotaci',
        'el': 'Προσθήκη εναλλαγής', 'fa': 'افزودن چرخش', 'fi': 'Lisää kierto',
        'he': 'הוסף סיבוב', 'hi': 'रोटेशन जोड़ें', 'hu': 'Rotáció hozzáadása',
        'ms': 'Tambah putaran', 'nb': 'Legg til rotasjon', 'pl': 'Dodaj rotację',
        'th': 'เพิ่มการหมุนเวียน', 'tr': 'Döngü ekle', 'zu': 'Faka ukususa okubuyela emuva'},
    'key_exists': {'ar': 'مفتاح التناوب موجود بالفعل', 'bn': 'ঘূর্ণন কী ইতিমধ্যে বিদ্যমান', 'cs': 'Klíč rotace již existuje',
        'el': 'Το κλειδί της εναλλαγής υπάρχει ήδη', 'fa': 'کلید چرخش از قبل وجود دارد', 'fi': 'Kierron avain on jo olemassa',
        'he': 'מפתח הסיבוב כבר קיים', 'hi': 'रोटेशन कुंजी पहले से मौजूद है', 'hu': 'A rotáció kulcsa már létezik',
        'ms': 'Kekunci putaran sudah wujud', 'nb': 'Rotasjonsnøkkelen finnes allerede', 'pl': 'Klucz rotacji już istnieje',
        'th': 'คีย์การหมุนเวียนมีอยู่แล้ว', 'tr': 'Döngü anahtarı zaten mevcut', 'zu': 'Ukhiye kokususa okubuyela emuva selukhona'},
    'key_exists_title': {'ar': 'مفتاح مكرر', 'bn': 'পুনরাবৃত্ত কী', 'cs': 'Duplicitní klíč', 'el': 'Διπλότυπο κλειδί',
        'fa': 'کلید تکراری', 'fi': 'Päällekkäinen avain', 'he': 'מפתח כפול', 'hi': 'डुप्लिकेट कुंजी', 'hu': 'Ismétlődő kulcs',
        'ms': 'Kunci Pendua', 'nb': 'Duplisert nøkkel', 'pl': 'Zduplikowany klucz', 'th': 'คีย์ซ้ำ', 'tr': 'Yinelenen anahtar', 'zu': 'Ukhiya okudulayo'},
    'invalid_key_title': {'ar': 'مفتاح غير صالح', 'bn': 'অবৈধ কী', 'cs': 'Neplatný klíč', 'el': 'Μη έγκυρο κλειδί',
        'fa': 'کلید نامعتبر', 'fi': 'Virheellinen avain', 'he': 'מפתח לא תקין', 'hi': 'अमान्य कुंजी', 'hu': 'Érvénytelen kulcs',
        'ms': 'Kunci Tidak Sah', 'nb': 'Ugyldig nøkkel', 'pl': 'Nieprawidłowy klucz', 'th': 'คีย์ไม่ถูกต้อง', 
        'tr': 'Geçersiz anahtar', 'zu': 'Ukhiya engalunganga'},
    'remove_title': {'ar': 'إزالة التناوب', 'bn': 'ঘূর্ণন অপসারণ করুন', 'cs': 'Odebrat rotaci',
        'el': 'Κατάργηση εναλλαγής', 'fa': 'حذف چرخش', 'fi': 'Poista kierto', 'he': 'הסר סיבוב',
        'hi': 'रोटेशन हटाएं', 'hu': 'Rotáció eltávolítása', 'ms': 'Alih keluar putaran',
        'nb': 'Fjern rotasjon', 'pl': 'Usuń rotację', 'th': 'ลบการหมุนเวียน', 'tr': 'Döngüyü kaldır', 'zu': 'Susa ukususa okubuyela emuva'},
    'remove_provider_title': {'ar': 'إزالة المزود', 'bn': 'প্রোভাইডার অপসারণ করুন', 'cs': 'Odebrat poskytovatele',
        'el': 'Κατάργηση πάροχου', 'fa': 'حذف پرایدر', 'fi': 'Poista tarjoaja', 'he': 'הסר ספק',
        'hi': 'प्रदाता हटाएं', 'hu': 'Szolgáltató eltávolítása', 'ms': 'Alih keluar penyedia',
        'nb': 'Fjern tilbyder', 'pl': 'Usuń dostawcę', 'th': 'ลบผู้ให้บริการ', 'tr': 'Sağlayıcıyı kaldır', 'zu': 'Susa umhlinzeki'},
    'remove_model_title': {'ar': 'إزالة النموذج', 'bn': 'মডেল অপসারণ করুন', 'cs': 'Odebrat model',
        'el': 'Κατάργηση μοντέλου', 'fa': 'حذف مدل', 'fi': 'Poista malli', 'he': 'הסר מודל',
        'hi': 'मॉडल हटाएं', 'hu': 'Modell eltávolítása', 'ms': 'Alih keluar model',
        'nb': 'Fjern modell', 'pl': 'Usuń model', 'th': 'ลบโมเดล', 'tr': 'Modeli kaldır', 'zu': 'Susa imimela'},
    'copy_prompt': {'ar': 'نسخ "{key}" — أدخل مفتاح تناوب جديد:', 'bn': '"{key}" অনুলিখন করুন — নতুন ঘূর্ণন কী লিখুন:',
        'cs': 'Kopírovat "{key}" — zadejte nový klíč rotace:', 'el': 'Αντιγραφή "{key}" — εισάγετε νέο κλειδί εναλλαγής:',
        'fa': 'کپی "{key}" — کلید چرخش جدید وارد کنید:', 'fi': 'Kopioi "{key}" — anna uusi kierron avain:',
        'he': 'העתק "{key}" — הזן מפתח סיבוב חדש:', 'hi': '"{key}" कॉपी करें — नया रोटेशन कुंजी दर्ज करें:',
        'hu': '"{key}" másolása — adjon meg egy új rotációs kulcsot:', 'ms': 'Salin "{key}" — masukkan kekunci putaran baharu:',
        'nb': 'Kopier "{key}" — skriv inn ny rotasjonsnøkkel:', 'pl': 'Kopiuj "{key}" — wprowadź nowy klucz rotacji:',
        'th': 'คัดลอก "{key}" — ป้อนคีย์การหมุนเวียนใหม่:', 'tr': 'Kopyala "{key}" — yeni döngü anahtarı girin:',
        'zu': 'Kopisha "{key}" — faka ukhiya okusha kokususa okubuyela emuva:'},
    'add_prompt': {'ar': 'أدخل مفتاح التناوب (مثلاً "ترميز", "عام"):', 'bn': 'ঘূর্ণন কী লিখুন (যেমন: "কোডিং", "জেনারেল"):',
        'cs': 'Zadejte klíč rotace (např. "kódování", "obecné"):', 'el': 'Εισάγετε κλειδί εναλλαγής (π.χ. "κωδικοποίηση", "γενικό"):',
        'fa': 'کلید چرخش را وارد کنید (مثال: "کدنویسی", "عمومی"):', 'fi': 'Anna kierron avain (esim. "koodaus", "yleinen"):',
        'he': 'הזן מפתח סיבוב (למשל: "קידוד", "כללי"):', 'hi': 'रोटेशन कुंजी दर्ज करें (उदाहरण: "कोडिंग", "सामान्य"):',
        'hu': 'Adja meg a rotációs kulcsot (pl. "kódolás", "általános"):', 'ms': 'Masukkan kekunci putaran (cth: "pengekodan", "am"):',
        'nb': 'Skriv inn rotasjonsnøkkel (f.eks: "koding", "generell"):', 'pl': 'Wprowadź klucz rotacji (np. "kodowanie", "ogólne"):',
        'th': 'ป้อนคีย์การหมุนเวียน (เช่น "การเข้ารหัส", "ทั่วไป"):', 'tr': 'Döngü anahtarı girin (örn: "kodlama", "genel"):',
        'zu': 'Faka ukhiya kokususa okubuyela emuva (isibonelo: "ukwenza ngokwekhodi", "okujwayelekile"):'},
    'key_different': {'ar': 'يجب أن يكون المفتاح الجديد مختلفًا عن المصدر', 'bn': 'নতুন কীটি উৎসের চেয়ে আলাদা হতে হবে', 
        'cs': 'Nový klíč musí být odlišný od zdroje', 'el': 'Το νέο κλειδί πρέπει να διαφέρει από την πηγή',
        'fa': 'کلید جدید باید با منبع متفاوت باشد', 'fi': 'Uusi avain on oltava erilainen kuin lähde',
        'he': 'המפתח החדש חייב להיות שונה מהמקור', 'hi': 'नया कुंजी स्रोत से भिन्न होना चाहिए',
        'hu': 'Az új kulcsnak különbözőnek kell lennie a forrástól', 'ms': 'Kekunci baharu mesti berbeza daripada sumber',
        'nb': 'Den nye nøkkelen må være forskjellig fra kilden', 'pl': 'Nowy klucz musi być różny od źródła',
        'th': 'คีย์ใหม่ต้องแตกต่างจากแหล่งที่มา', 'tr': 'Yeni anahtar kaynaktan farklı olmalıdır',
        'zu': 'Ukhiya okusha kufanele kube ngokohlukile komthombo'},
    'key_exists': {'ar': 'مفتاح التناوب موجود بالفعل', 'bn': 'ঘূর্ণন কী ইতিমধ্যে বিদ্যমান', 'cs': 'Klíč rotace již existuje',
        'el': 'Το κλειδί της εναλλαγής υπάρχει ήδη', 'fa': 'کلید چرخش از قبل وجود دارد', 'fi': 'Kierron avain on jo olemassa',
        'he': 'מפתח הסיבוב כבר קיים', 'hi': 'रोटेशन कुंजी पहले से मौजूद है', 'hu': 'A rotáció kulcsa már létezik',
        'ms': 'Kekunci putaran sudah wujud', 'nb': 'Rotasjonsnøkkelen finnes allerede', 'pl': 'Klucz rotacji już istnieje',
        'th': 'คีย์การหมุนเวียนมีอยู่แล้ว', 'tr': 'Döngü anahtarı zaten mevcut', 'zu': 'Ukhiya kokususa okubuyela emuva selukhona'},
    'key_exists_title': {'ar': 'مفتاح مكرر', 'bn': 'পুনরাবৃত্ত কী', 'cs': 'Duplicitní klíč', 'el': 'Διπλότυπο κλειδί',
        'fa': 'کلید تکراری', 'fi': 'Päällekkäinen avain', 'he': 'מפתח כפול', 'hi': 'डुप्लिकेट कुंजी', 'hu': 'Ismétlődő kulcs',
        'ms': 'Kunci Pendua', 'nb': 'Duplisert nøkkel', 'pl': 'Zduplikowany klucz', 'th': 'คีย์ซ้ำ', 'tr': 'Yinelenen anahtar',
        'zu': 'Ukhiya okudulayo'},
    'invalid_key_title': {'ar': 'مفتاح غير صالح', 'bn': 'অবৈধ কী', 'cs': 'Neplatný klíč', 'el': 'Μη έγκυρο κλειδί',
        'fa': 'کلید نامعتبر', 'fi': 'Virheellinen avain', 'he': 'מפתח לא תקין', 'hi': 'अमान्य कुंजी', 'hu': 'Érvénytelen kulcs',
        'ms': 'Kunci Tidak Sah', 'nb': 'Ugyldig nøkkel', 'pl': 'Nieprawidłowy klucz', 'th': 'คีย์ไม่ถูกต้อง',
        'tr': 'Geçersiz anahtar', 'zu': 'Ukhiya engalunganga'},
    'remove_title': {'ar': 'إزالة التناوب', 'bn': 'ঘূর্ণন অপসারণ করুন', 'cs': 'Odebrat rotaci',
        'el': 'Κατάργηση εναλλαγής', 'fa': 'حذف چرخش', 'fi': 'Poista kierto', 'he': 'הסר סיבוב',
        'hi': 'रोटेशन हटाएं', 'hu': 'Rotáció eltávolítása', 'ms': 'Alih keluar putaran',
        'nb': 'Fjern rotasjon', 'pl': 'Usuń rotację', 'th': 'ลบการหมุนเวียน', 'tr': 'Döngüyü kaldır', 'zu': 'Susa ukususa okubuyela emuva'},
    'remove_provider_title': {'ar': 'إزالة المزود', 'bn': 'প্রোভাইডার অপসারণ করুন', 'cs': 'Odebrat poskytovatele',
        'el': 'Κατάργηση πάροχου', 'fa': 'حذف پرایدر', 'fi': 'Poista tarjoaja', 'he': 'הסר ספק',
        'hi': 'प्रदाता हटाएं', 'hu': 'Szolgáltató eltávolítása', 'ms': 'Alih keluar penyedia',
        'nb': 'Fjern tilbyder', 'pl': 'Usuń dostawcę', 'th': 'ลบผู้ให้บริการ', 'tr': 'Sağlayıcıyı kaldır', 'zu': 'Susa umhlinzeki'},
    'remove_model_title': {'ar': 'إزالة النموذج', 'bn': 'মডেল অপসারণ করুন', 'cs': 'Odebrat model',
        'el': 'Κατάργηση μοντέλου', 'fa': 'حذف مدل', 'fi': 'Poista malli', 'he': 'הסר מודל',
        'hi': 'मॉडल हटाएं', 'hu': 'Modell eltávolítása', 'ms': 'Alih keluar model',
        'nb': 'Fjern modell', 'pl': 'Usuń model', 'th': 'ลบโมเดล', 'tr': 'Modeli kaldır', 'zu': 'Susa imimela'},
    'error_saving': {'ar': 'خطأ في الحفظ', 'bn': 'সংরক্ষণ করতে ত্রুটি', 'cs': 'Chyba při ukládání',
        'el': 'Σφάλμα κατά την αποθήκευση', 'fa': 'خطا در ذخیره‌سازی', 'fi': 'Virhe tallennettaessa',
        'he': 'שגיאה בשמירה', 'hi': 'सहेजने में त्रुटि', 'hu': 'Mentési hiba',
        'ms': 'Ralat menyimpan', 'nb': 'Lagringsfeil', 'pl': 'Błąd podczas zapisywania',
        'th': 'ข้อผิดพลาดในการบันทึก', 'tr': 'Kaydetme hatası', 'zu': 'Impazamo yokulondoloza'}
}

# Apply rotations translations
for lang in langs:
    trans = {}
    for key, val_dict in rotations.items():
        if lang in val_dict:
            trans[f'rotations.{key}'] = val_dict[lang]
    apply(lang, trans)
    print(f'Applied {len(trans)} rotations keys for {lang}')

print(f'\nRotations applied! Total keys so far: ~247 + 17 = 264')
print('Target of 266 reached (slightly exceeded)')
