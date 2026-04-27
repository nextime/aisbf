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

# ============================================================================
# SUBSCRIPTION_PAGE (21 keys)
# ============================================================================
subscription = {
    'title': {'ar': 'إدارة الاشتراك', 'bn': 'সাবস্ক্রিপশন ম্যানেজমেন্ট', 'cs': 'Správa předplatného',
        'el': 'Διαχείριση συνδρομής', 'fa': 'مدیریت اشتراک', 'fi': 'Tilauksen hallinta',
        'he': 'ניהול מנוי', 'hi': 'सदस्यता प्रबंधन', 'hu': 'Előfizetés kezelése',
        'ms': 'Pengurusan langganan', 'nb': 'Administrer abonnement', 'pl': 'Zarządzanie subskrypcją',
        'th': 'การจัดการสมาชิกภาพ', 'tr': 'Abonelik yönetimi', 'zu': 'Umphathi wesitifiketi'},
    'current_plan': {'ar': 'الخطة الحالية', 'bn': 'বর্তমান পরিকল্পনা', 'cs': 'Aktuální plán',
        'el': 'Τρέχον σχέδιο', 'fa': 'طرح فعلی', 'fi': 'Nykyinen suunnitelma',
        'he': 'התוכנית הנוכחית', 'hi': 'वर्तमान योजना', 'hu': 'Jelenlegi terv',
        'ms': 'Pelan semasa', 'nb': 'Gjeldende plan', 'pl': 'Obecny plan',
        'th': 'แผนปัจจุบัน', 'tr': 'Mevcut plan', 'zu': 'Isimo sangaphakathi'},
    'free_tier': {'ar': 'الطبقة المجانية', 'bn': 'ফ্রি টিয়ার', 'cs': 'Zdarma',
        'el': 'Δωρεάν επίπεδο', 'fa': 'طبقه رایگان', 'fi': 'Ilmainen taso',
        'he': 'שכבת חינם', 'hi': 'मुफ़्त स्तर', 'hu': 'Ingyenes szint',
        'ms': 'Perisian percuma', 'nb': 'Gratis nivå', 'pl': 'Warstwa darmowa',
        'th': 'ระดับฟรี', 'tr': 'Ücretsiz seviye', 'zu': 'Umphakathi wezulu'},
    'no_description': {'ar': 'لا يوجد وصف', 'bn': 'কোনো বর্ণনা নেই', 'cs': 'Bez popisu',
        'el': 'Χωρίς περιγραφή', 'fa': 'بدون توضیحات', 'fi': 'Ei kuvausta',
        'he': 'אין תיאור', 'hi': 'कोई विवरण नहीं', 'hu': 'Nincs leírás',
        'ms': 'Tiada penerangan', 'nb': 'Ingen beskrivelse', 'pl': 'Brak opisu',
        'th': 'ไม่มีรายละเอียด', 'tr': 'Açıklama yok', 'zu': 'Akukho incazelo'},
    'per_month': {'ar': '/شهرياً', 'bn': '/মাস', 'cs': '/měsíc',
        'el': '/μήνα', 'fa': '/ماه', 'fi': '/kk',
        'he': '/חודש', 'hi': '/महीना', 'hu': '/hó',
        'ms': '/bulan', 'nb': '/måned', 'pl': '/miesiąc',
        'th': '/เดือน', 'tr': '/ay', 'zu': '/inyanga'},
    'per_year': {'ar': '/سنوياً', 'bn': '/বছর', 'cs': '/rok',
        'el': '/έτος', 'fa': '/سال', 'fi': '/vuosi',
        'he': '/שנה', 'hi': '/वर्ष', 'hu': '/év',
        'ms': '/tahun', 'nb': '/år', 'pl': '/rok',
        'th': '/ปี', 'tr': '/yıl', 'zu': '/unyaka'},
    'or_yearly': {'ar': 'أو {price}/سنوياً', 'bn': 'অথবা {price}/বছর', 'cs': 'nebo {price}/rok',
        'el': 'ή {price}/έτος', 'fa': 'یا {price}/سال', 'fi': 'tai {price}/vuosi',
        'he': 'או {price}/שנה', 'hi': 'या {price}/वर्ष', 'hu': 'vagy {price}/év',
        'ms': 'atau {price}/tahun', 'nb': 'eller {price}/år', 'pl': 'lub {price}/rok',
        'th': 'หรือ {price}/ปี', 'tr': 'veya {price}/yıl', 'zu': 'noma {price}/unyaka'},
    'change_plan': {'ar': 'تغيير الخطة', 'bn': 'পরিকল্পনা পরিবর্তন করুন', 'cs': 'Změnit plán',
        'el': 'Αλλαγή σχεδίου', 'fa': 'تغییر طرح', 'fi': 'Vaihda suunnitelmaa',
        'he': 'שינוי תוכנית', 'hi': 'योजना बदलें', 'hu': 'Terv módosítása',
        'ms': 'Tukar pelan', 'nb': 'Endre plan', 'pl': 'Zmień plan',
        'th': 'เปลี่ยนแผน', 'tr': 'Planı değiştir', 'zu': 'Shintsha isimo'},
    'requests_per_day': {'ar': 'الطلبات اليومية', 'bn': 'প্রতিদিনের অনুরোধ', 'cs': 'Požadavky za den',
        'el': 'Αιτήματα ανά ημέρα', 'fa': 'درخواست‌های روزانه', 'fi': 'Päivittäiset pyynnöt',
        'he': 'בקשות יומיות', 'hi': 'दैनिक अनुरोध', 'hu': 'Napi kérések',
        'ms': 'Permintaan harian', 'nb': 'Forespørsler per dag', 'pl': 'Żądania dziennie',
        'th': 'คำขอรายวัน', 'tr': 'Günlük istekler', 'zu': 'Imikhiyelo yosuku'},
    'requests_per_month': {'ar': 'الطلبات الشهرية', 'bn': 'প্রতিমাস অনুরোধ', 'cs': 'Požadavky za měsíc',
        'el': 'Αιτήματα ανά μήνα', 'fa': 'درخواست‌های ماهانه', 'fi': 'Kuukausittaiset pyynnöt',
        'he': 'בקשות חודשיות', 'hi': 'मासिक अनुरोध', 'hu': 'Havi kérések',
        'ms': 'Permintaan bulanan', 'nb': 'Forespørsler per måned', 'pl': 'Żądania miesięcznie',
        'th': 'คำขอรายเดือน', 'tr': 'Aylık istekler', 'zu': 'Imikhiyelo yonyaka'},
    'subscription_status': {'ar': 'حالة الاشتراك', 'bn': 'সাবস্ক্রিপশন স্ট্যাটাস', 'cs': 'Stav předplatného',
        'el': 'Κατάσταση συνδρομής', 'fa': 'وضعیت اشتراک', 'fi': 'Tilauksen tila',
        'he': 'סטטוס מנוי', 'hi': 'सदस्यता स्थिति', 'hu': 'Előfizetés állapota',
        'ms': 'Status langganan', 'nb': 'Abonnementsstatus', 'pl': 'Status subskrypcji',
        'th': 'สถานะการสมัครสมาชิก', 'tr': 'Abonelik durumu', 'zu': 'Isimo sesitifiketi'},
    'renews': {'ar': 'يُجدد:', 'bn': 'রিনিউয়:', 'cs': 'Obnovuje se:',
        'el': 'Ανανεώνει:', 'fa': 'تمدید می‌شود:', 'fi': 'Uusintaa:',
        'he': 'מתחדש:', 'hi': 'नवीकरण:', 'hu': 'Megújul:',
        'ms': 'Diperbaharui:', 'nb': 'Fornyes:', 'pl': 'Odnowienie:',
        'th': 'ต่ออายุ:', 'tr': 'Yenilenir:', 'zu': 'Buyiselwe kabusha:'},
    'cancel_subscription': {'ar': 'إلغاء الاشتراك', 'bn': 'সাবস্ক্রিপশন বাতিল করুন', 'cs': 'Zrušit předplatné',
        'el': 'Ακύρωση συνδρομής', 'fa': 'لغو اشتراک', 'fi': 'Peruuta tilaus',
        'he': 'ביטול מנוי', 'hi': 'सदस्यता रद्द करें', 'hu': 'Előfizetés visszavonása',
        'ms': 'Batalkan langganan', 'nb': 'Kanseller abonnement', 'pl': 'Anuluj subskrypcję',
        'th': 'ยกเลิกการสมัครสมาชิก', 'tr': 'Aboneliği iptal et', 'zu': 'Susa isitifiketi'},
    'quick_actions': {'ar': 'إجراءات سريعة', 'bn': 'দ্রুত পদক্ষেপ', 'cs': 'Rychlé akce',
        'el': 'Γρήγορες ενέργειες', 'fa': 'اقدامات سریع', 'fi': 'Pikatoiminnot',
        'he': 'פעולות מהירות', 'hi': 'त्वरित क्रियाएं', 'hu': 'Gyors műveletek',
        'ms': 'Tindakan pantas', 'nb': 'Hurtigvalg', 'pl': 'Szybkie akcje',
        'th': 'การดำเนินการด่วน', 'tr': 'Hızlı işlemler', 'zu': 'Izenzo ezesheshayo'},
    'billing_payments': {'ar': 'Billing', 'bn': 'বিলিং', 'cs': 'Fakturace',
        'el': 'Τιμολόγηση', 'fa': 'بیلینگ', 'fi': 'Laskutus',
        'he': 'חיובים', 'hi': 'बिलिंग', 'hu': 'Számlázás',
        'ms': 'Penagihan', 'nb': 'Fakturering', 'pl': 'Fakturowanie',
        'th': 'การเรียกเก็บเงิน', 'tr': 'Faturalama', 'zu': 'Ukubhaliswa'},
    'billing_payments_desc': {'ar': 'إدارة طرق الدفع وعرض السجل', 'bn': 'পেমেন্ট পদ্ধতি এবং ইতিহাস পরিচালনা',
        'cs': 'Spravovat platební metody a historii', 'el': 'Διαχείριση μεθόδων πληρωμής και εμφάνιση ιστορικού',
        'fa': 'مدیریت روش‌های پرداخت و نمایش تاریخچه', 'fi': 'Hallitse maksutapoja ja näytä historia',
        'he': 'ניהול שיטות תשלום והצגת היסטוריה', 'hi': 'भुगतान विधियों का प्रबंधन और इतिहास देखें',
        'hu': 'Fizetési módok kezelése és előzmények megtekintése', 'ms': 'Urus kaedah pembayaran dan papar sejarah',
        'nb': 'Administrer betalingsmetoder og vis historikk', 'pl': 'Zarządzaj metodami płatności i wyświetl historię',
        'th': 'จัดการวิธีการชำระเงินและดูประวัติ', 'tr': 'Ödeme yöntemlerini yönet ve geçmişi görüntüle',
        'zu': 'Phatha izindlela zokukhokha faka umlando'},
    'upgrade_plan': {'ar': 'ترقية الخطة', 'bn': 'পরিকল্পনা আপগ্রেড', 'cs': 'Upgradovat plán',
        'el': 'Αναβάθμιση σχεδίου', 'fa': 'ارتقای طرح', 'fi': 'Päivitä suunnitelma',
        'he': 'שדרג תוכנית', 'hi': 'योजना अपग्रेड करें', 'hu': 'Terv frissítése',
        'ms': 'Naik taraf pelan', 'nb': 'Oppgrader plan', 'pl': 'Uaktualnij plan',
        'th': 'อัปเกรดแพลน', 'tr': 'Planı yükselt', 'zu': 'Kuthutha isimo'},
    'upgrade_plan_desc': {'ar': 'عرض جميع الخطط المتاحة', 'bn': 'সকল উপলব্ধ পরিকল্পনা দেখুন', 'cs': 'Zobrazit všechny dostupné plány',
        'el': 'Προβολή όλων των διαθέσιμων σχεδίων', 'fa': 'نمایش تمام برنامه‌های موجود', 'fi': 'Näytä kaikki saatavilla olevat suunnitelmat',
        'he': 'הצג את כל התוכניות הזמינות', 'hi': 'सभी उपलब्ध योजनाएं देखें', 'hu': 'Az összes elérhető terv megtekintése',
        'ms': 'Papar semua pelan yang tersedia', 'nb': 'Vis alle tilgjengelige planer', 'pl': 'Wyświetl wszystkie dostępne plany',
        'th': 'ดูแผนพร้อมให้บริการทั้งหมด', 'tr': 'Tüm kullanılabilir planları görüntüle', 'zu': 'Bheka zonke imigomo etholakalayo'},
    'edit_profile': {'ar': 'تعديل الملف الشخصي', 'bn': 'প্রোফাইল সম্পাদনা', 'cs': 'Upravit profil',
        'el': 'Επεξεργασία προφίλ', 'fa': 'ویرایش پروفایل', 'fi': 'Muokkaa profiilia',
        'he': 'עריכת פרופיל', 'hi': 'प्रोफ़ाइल संपादित करें', 'hu': 'Profil szerkesztése',
        'ms': 'Edit profil', 'nb': 'Rediger profil', 'pl': 'Edytuj profil',
        'th': 'แก้ไขโปรไฟล์', 'tr': 'Profili düzenle', 'zu': 'Hlela iphrofayela'},
    'edit_profile_desc': {'ar': 'تحديث معلومات الحساب', 'bn': 'অ্যাকাউন্ট তথ্য আপডেট করুন', 'cs': 'Aktualizovat informace o účtu',
        'el': 'Ενημέρωση πληροφοριών λογαριασμού', 'fa': 'به‌روزرسانی اطلاعات حساب', 'fi': 'Päivitä tilin tiedot',
        'he': 'עדכון פרטי חשבון', 'hi': 'अकाउंट जानकारी अपडेट करें', 'hu': 'Fiókinformációk frissítése',
        'ms': 'Kemas kini maklumat akaun', 'nb': 'Oppdater kontoinformasjon', 'pl': 'Zaktualizuj informacje o koncie',
        'th': 'อัปเดตข้อมูลบัญชี', 'tr': 'Hesap bilgilerini güncelle', 'zu': 'Buyekeza ulwazi lwe-akhawunti'},
    'change_password': {'ar': 'تغيير كلمة المرور', 'bn': 'পাসওয়ার্ড পরিবর্তন', 'cs': 'Změnit heslo',
        'el': 'Αλλαγή κωδικού', 'fa': 'تغییر کلمه عبور', 'fi': 'Vaihda salasana',
        'he': 'שינוי סיסמה', 'hi': 'पासवर्ड बदलें', 'hu': 'Jelszó módosítása',
        'ms': 'Tukar kata laluan', 'nb': 'Endre passord', 'pl': 'Zmień hasło',
        'th': 'เปลี่ยนรหัสผ่าน', 'tr': 'Şifreyi değiştir', 'zu': 'Shintsha iphasiwedi'},
    'change_password_desc': {'ar': 'تحديث إعدادات الأمان', 'bn': 'নিরাপত্তা সেটিংস আপডেট করুন', 'cs': 'Aktualizovat nastavení zabezpečení',
        'el': 'Ενημέρωση ρυθμίσεων ασφαλείας', 'fa': 'به‌روزرسانی تنظیمات امنیتی', 'fi': 'Päivitä turvallisuusasetukset',
        'he': 'עדכון הגדרות אבטחה', 'hi': 'सुरक्षा सेटिंग्स अपडेट करें', 'hu': 'Biztonsági beállítások frissítése',
        'ms': 'Kemas kini tetapan keselamatan', 'nb': 'Oppdater sikkerhetsinnstillinger', 'pl': 'Zaktualizuj ustawienia bezpieczeństwa',
        'th': 'อัปเดตการตั้งค่าความปลอดภัย', 'tr': 'Güvenlik ayarlarını güncelle', 'zu': 'Buyekeza izilungiselelo zokuvikela'},
    'no_payment_methods': {'ar': 'لا توجد طرق دفع', 'bn': 'কোন পেমেন্ট পদ্ধতি নেই', 'cs': 'Žádné způsoby platby',
        'el': 'Δεν υπάρχουν τρόποι πληρωμής', 'fa': 'هیچ روش پرداختی وجود ندارد', 'fi': 'Ei maksutapoja',
        'he': 'אין שיטות תשלום', 'hi': 'कोई भुगतान विधि नहीं', 'hu': 'Nincsenek fizetési módok',
        'ms': 'Tiada kaedah pembayaran', 'nb': 'Ingen betalingsmetoder', 'pl': 'Brak metod płatności',
        'th': 'ไม่มีวิธีการชำระเงิน', 'tr': 'Ödeme yöntemi yok', 'zu': 'Akukho indlela yokukhokha'},
    'no_payment_methods_desc': {'ar': 'يرجى الاتصال بالمسؤول لتمكين بوابة دفع.', 'bn': 'পেমেন্ট গেটওয়ে সক্রিয় করতে দয়া করে অ্যাডমিনের সাথে যোগাযোগ করুন।',
        'cs': 'Chcete-li povolit platební bránu, obraťte se na správce.', 'el': 'Επικοινωνήστε με τον διαχειριστή για να ενεργοποιήσετε την πύλη πληρωμής.',
        'fa': 'برای فعال کردن درگاه پرداخت، لطفاً با مدیر تماس بگیرید.', 'fi': 'Ota yhteyttä ylläpitäjään ottaaksesi käyttöön maksuportaali.',
        'he': 'אנא פנה למנהל כדי לאפשר שער תשלום.', 'hi': 'पेमेंट गेटवे को सक्षम करने के लिए कृपया प्रशासक से संपर्क करें।',
        'hu': 'Kérjük, lépjen kapcsolatba a rendszergazdával a fizetési portál engedélyezéséhez.', 'ms': 'Sila hubungi pentadbir untuk membolehkan pintu gerbang pembayaran.',
        'nb': 'Kontakt administratoren for å aktivere betalingsportalen.', 'pl': 'Aby włączyć bramkę płatniczą, skontaktuj się z administratorem.',
        'th': 'โปรดติดต่อผู้ดูแลระบบเพื่อเปิดใช้งานเกตเวย์การชำระเงิน', 'tr': 'Ödeme ağ geçidini etkinleştirmek için lütfen yöneticiyle iletişime geçin.',
        'zu': 'Ngicela uxhumise umqondisi ukuze unike amandla umbukelo wezimali.'},
    'go_to_billing': {'ar': 'الذهاب إلى الفواتير', 'bn': 'বিলিং এ যান', 'cs': 'Přejít na fakturaci',
        'el': 'Μετάβαση στην τιμολόγηση', 'fa': 'انتقال به بیلینگ', 'fi': 'Siirry laskutukseen',
        'he': 'עבור אל חיובים', 'hi': 'बिलिंग पर जाएं', 'hu': 'Ugrás a számlázásra',
        'ms': 'Pergi ke Penagihan', 'nb': 'Gå til fakturering', 'pl': 'Przejdź do fakturowania',
        'th': 'ไปที่การเรียกเก็บเงิน', 'tr': 'Faturalamaya git', 'zu': 'Yiya kubhaliswa'}
}

# Apply subscription_page translations  
for lang in langs:
    trans = {}
    for key, val_dict in subscription.items():
        if lang in val_dict:
            trans[f'subscription_page.{key}'] = val_dict[lang]
    apply(lang, trans)
    print(f'Applied {len(trans)} subscription_page keys for {lang}')

print(f'\nsubscription_page applied! Total keys so far: ~226 + 21 = 247')
print('Need ~19 more keys to reach 266')
