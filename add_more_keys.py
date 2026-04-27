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

# User overview keys
user_overview_keys = {
    'stat_total_tokens': {'ar': 'إجمالي الرموز', 'bn': 'মোট টোকেন', 'cs': 'Celkový počet tokenů',
        'el': 'Σύνολο token', 'fa': 'مجموع توکن‌ها', 'fi': 'Tokenit yhteensä',
        'he': 'סך הכל טוקנים', 'hi': 'कुल टोकन', 'hu': 'Jelzések összesen',
        'ms': 'Jumlah token', 'nb': 'Totalt antall token', 'pl': 'Łącznie tokenów',
        'th': 'จำนวนโทเค็นทั้งหมด', 'tr': 'Toplam token', 'zu': 'Ithokhani lesu'
    },
    'stat_requests_today': {'ar': 'الطلبات اليوم', 'bn': 'আজকের অনুরোধ', 'cs': 'Požadavky dnes',
        'el': 'Αιτήματα σήμερα', 'fa': 'درخواست‌های امروز', 'fi': 'Päivän pyynnöt',
        'he': 'בקשות היום', 'hi': 'आज के अनुरोध', 'hu': 'Mai kérések',
        'ms': 'Permintaan hari ini', 'nb': 'Forespørsler i dag', 'pl': 'Żądania dzisiaj',
        'th': 'คำขอวันนี้', 'tr': 'Bugünkü istekler', 'zu': 'Imikhiyelo namhlange'
    },
    'stat_active_providers': {'ar': 'مزودون نشطون', 'bn': 'সক্রিয় প্রোভাইডার', 'cs': 'Aktivní poskytovatelé',
        'el': 'Ενεργοί πάροχοι', 'fa': 'پرایدرهای فعال', 'fi': 'Aktiiviset tarjoajat',
        'he': 'ספקים פעילים', 'hi': 'सक्रिय प्रदाता', 'hu': 'Aktív szolgáltatók',
        'ms': 'Penyedia aktif', 'nb': 'Aktive tilbydere', 'pl': 'Aktywni dostawcy',
        'th': 'ผู้ให้บริการที่ใช้งานอยู่', 'tr': 'Aktif sağlayıcılar', 'zu': 'Abahlinzeki abasebenzayo'
    },
    'stat_active_rotations': {'ar': 'تناوبات نشطة', 'bn': 'সক্রিয় ঘূর্ণন', 'cs': 'Aktivní rotace',
        'el': 'Ενεργές εναλλαγές', 'fa': 'چرخش‌های فعال', 'fi': 'Aktiiviset kierröt',
        'he': 'סיבובים פעילים', 'hi': 'सक्रिय रोटेशन', 'hu': 'Aktív rotációk',
        'ms': 'Putaran aktif', 'nb': 'Aktive roter', 'pl': 'Aktywne rotacje',
        'th': 'การหมุนเวียนที่ใช้งานอยู่', 'tr': 'Aktif döngüler', 'zu': 'Ukususa okubuyela emuva okusebenzayo'
    },
    'quick_actions': {'ar': 'إجراءات سريعة', 'bn': 'দ্রুত পদক্ষেপ', 'cs': 'Rychlé akce',
        'el': 'Γρήγορες ενέργειες', 'fa': 'اقدامات سریع', 'fi': 'Pikatoiminnot',
        'he': 'פעולות מהירות', 'hi': 'त्वरित क्रियाएं', 'hu': 'Gyors műveletek',
        'ms': 'Tindakan pantas', 'nb': 'Hurtigvalg', 'pl': 'Szybkie akcje',
        'th': 'การดำเนินการด่วน', 'tr': 'Hızlı işlemler', 'zu': 'Izenzo ezesheshayo'
    },
    'subscription': {'ar': 'الاشتراك', 'bn': 'সাবস্ক্রিপশন', 'cs': 'Předplatné',
        'el': 'Συνδρομή', 'fa': 'اشتراک', 'fi': 'Tilaus',
        'he': 'מנוי', 'hi': 'सदस्यता', 'hu': 'Előfizetés',
        'ms': 'Langganan', 'nb': 'Abonnement', 'pl': 'Subskrypcja',
        'th': 'การสมัครสมาชิก', 'tr': 'Abonelik', 'zu': 'Isitifiketi'
    },
    'manage': {'ar': 'إدارة', 'bn': 'পরিচালনা', 'cs': 'Spravovat',
        'el': 'Διαχείριση', 'fa': 'مدیریت', 'fi': 'Hallitse',
        'he': 'ניהול', 'hi': 'प्रबंधन', 'hu': 'Kezelés',
        'ms': 'Urus', 'nb': 'Administrer', 'pl': 'Zarządzaj',
        'th': 'การจัดการ', 'tr': 'Yönet', 'zu': 'Phatha'
    },
    'add_payment_method': {'ar': 'إضافة طريقة دفع', 'bn': 'পেমেন্ট পদ্ধতি যোগ করুন', 'cs': 'Přidat způsob platby',
        'el': 'Προσθήκη τρόπου πληρωμής', 'fa': 'افزودن روش پرداخت', 'fi': 'Lisää maksutapa',
        'he': 'הוסף אמצעי תשלום', 'hi': 'पेमेंट मेथड जोड़े', 'hu': 'Fizetési mód hozzáadása',
        'ms': 'Tambah kaedah pembayaran', 'nb': 'Legg til betalingsmetode', 'pl': 'Dodaj metodę płatności',
        'th': 'เพิ่มวิธีการชำระเงิน', 'tr': 'Ödeme yöntemi ekle', 'zu': 'Faka indlela yokukhokha'
    },
    'unlock_more_power': {'ar': 'فتح المزيد من الإمكانات', 'bn': 'আরও ক্ষমতা উন্মোচন করুন', 'cs': 'Odemknout více síly',
        'el': 'Ξεκλείδωση περισσότερης ισχύος', 'fa': 'باز کردن قدرت بیشتر', 'fi': 'Avaa lisää voimaa',
        'he': 'פתח יותר כוח', 'hi': 'और शक्ति अनलॉक करें', 'hu': 'Több erő kinyitása',
        'ms': 'Buka lebih banyak kuasa', 'nb': 'Lås opp mer kraft', 'pl': 'Odblokuj więcej mocy',
        'th': 'ปลดล็อกพลังเพิ่มเติม', 'tr': 'Daha fazla güç açın', 'zu': 'Vula amandla amaningi'
    },
    'upgrade_plan': {'ar': 'ترقية الخطة', 'bn': 'পরিকল্পনা আপগ্রেড করুন', 'cs': 'Upgradovat plán',
        'el': 'Αναβάθμιση σχεδίου', 'fa': 'ارتقای طرح', 'fi': 'Päivitä suunnitelma',
        'he': 'שדרג תוכנית', 'hi': 'योजना अपग्रेड करें', 'hu': 'Terv frissítése',
        'ms': 'Naik taraf pelan', 'nb': 'Oppgrader plan', 'pl': 'Uaktualnij plan',
        'th': 'อัปเกรดแพลน', 'tr': 'Planı yükselt', 'zu': 'Kuthutha isimo'
    },
    'higher_plans': {'ar': '{n} خطط أعلى متاحة — المزيد من الطلبات، المزيد من المزودين',
        'bn': '{n} টি উচ্চতর পরিকল্পনা উপলব্ধ — আরও অনুরোধ, আরও প্রোভাইডারগুলো',
        'cs': 'K dispozici jsou {n} vyšší plány — více požadavků, více poskytovatelů',
        'el': 'Διαθέσιμα είναι {n} ανώτερα σχέδια — περισσότερες αιτήσεις, περισσότεροι πάροχοι',
        'fa': '{n} طرح بالاتر در دسترس است — درخواست‌های بیشتر، پرایدرهای بیشتر',
        'fi': '{n} korkeampaa suunnitelmaa saatavilla — enemmän pyyntöjä, enemmän tarjoajia',
        'he': '{n} תוכניות ברמות גבוהות יותר זמינות — יותר בקשות, יותר ספקים',
        'hi': '{n} उच्च योजनाएं उपलब्ध हैं — अधिक अनुरोध, अधिक प्रदाता',
        'hu': '{n} magasabb szintű terv érhető el — több kérés, több szolgáltató',
        'ms': '{n} pelan lebih tinggi tersedia — lebih banyak permintaan, lebih banyak penyedia',
        'nb': '{n} høyere planer tilgjengelig — flere forespørsler, flere tilbydere',
        'pl': 'Dostępne są {n} wyższe plany — więcej żądań, więcej dostawców',
        'th': 'มี {n} แผนที่สูงกว่าพร้อมให้บริการ — คำขอเพิ่มเติม ผู้ให้บริการเพิ่มเติม',
        'tr': '{n} daha yüksek plan kullanılabilir — daha fazla istek, daha fazla sağlayıcı',
        'zu': '{n} imigomo ephezulu itholakala — izicelo eziningi, abahlinzeki abaningi'
    },
    'upgrade_to': {'ar': 'الترقية إلى {name} بـ {price}/شهرياً', 'bn': '{name} এ আপগ্রেড করুন — {price}/মাস',
        'cs': 'Upgradovat na {name} za {price}/měsíc', 'el': 'Αναβάθμιση σε {name} με {price}/μήνα',
        'fa': 'ارتقا به {name} با قیمت {price}/ماه', 'fi': 'Päivitä {name}ksi hintaan {price}/kk',
        'he': 'שדרג ל-{name} במחיר של {price}/חודש', 'hi': '{name} में अपग्रेड करें — {price}/महीना',
        'hu': 'Frissítés {name}-ra ár {price}/hó', 'ms': 'Naik taraf ke {name} pada harga {price}/bulan',
        'nb': 'Oppgrader til {name} for {price}/måned', 'pl': 'Zaktualizuj do {name} za {price}/miesiąc',
        'th': 'อัปเกรดเป็น {name} ในราคา {price}/เดือน', 'tr': '{name} planına yükselt — {price}/ay',
        'zu': 'Kuthutha kube {name} kwesimo {price}/inyanga'
    },
    'api_endpoints': {'ar': 'نقاط نهاية API الخاصة بك', 'bn': 'আপনার API এন্ডপয়েন্ট',
        'cs': 'Vaše API koncové body', 'el': 'Τα endpoint API σας',
        'fa': 'نقطه پایانی‌های API شما', 'fi': 'Sinun API-päätepisteet',
        'he': 'נקודות הסיום של ה-API שלך', 'hi': 'आपके API एंडपॉइंट',
        'hu': 'Az Ön API végpontjai', 'ms': 'Titik akhir API anda',
        'nb': 'Dine API-endepunkter', 'pl': 'Twoje punkty końcowe API',
        'th': 'จุดสิ้นสุด API ของคุณ', 'tr': 'API uç noktalarınız',
        'zu': 'Iziphumo zakho ze-API'
    },
    'show_hide': {'ar': 'إظهار / إخفاء', 'bn': 'দেখান/লুকান', 'cs': 'Zobrazit / Skrýt',
        'el': 'Εμφάνιση / Απόκρυψη', 'fa': 'نمایش/مخفی کردن', 'fi': 'Näytä / Piilota',
        'he': 'הצג / הסתר', 'hi': 'दिखाएं / छुपाएं', 'hu': 'Mutat / Elrejt',
        'ms': 'Tunjuk / Sembunyi', 'nb': 'Vis / Skjul', 'pl': 'Pokaż / Ukryj',
        'th': 'แสดง / ซ่อน', 'tr': 'Göster / Gizle', 'zu': 'Bonisa / Fihla'
    },
    'auth_header_desc': {'ar': 'تضمين رمز API الخاص بك في رأس {header}:',
        'bn': 'আপনার API টোকেনটি {header} হেডারে অন্তর্ভুক্ত করুন:',
        'cs': 'Zahrňte svůj token API do hlavičky {header}:',
        'el': 'Συμπεριλάβετε το διακριτικό API σας στην κεφαλίδα {header}:',
        'fa': 'توکن API خود را در هدر {header} قرار دهید:',
        'fi': 'Sisällytä API-tokeni otsakkeeseen {header}:',
        'he': 'כלול את טוקן ה-API שלך בכותרת {header}:',
        'hi': 'अपने API टोकन को {header} हेडर में शामिल करें:',
        'hu': 'Vegye fel az API-tokenjét a(z) {header} fejlécbe:',
        'ms': 'Sertakan token API anda dalam pengepala {header}:',
        'nb': 'Inkluder API-tokenet ditt i {header}-hodet:',
        'pl': 'Dołącz swój token API do nagłówka {header}:',
        'th': 'ใส่โทเค็น API ของคุณในส่วนหัว {header}:',
        'tr': 'API tokeninizi {header} başlığına ekleyin:',
        'zu': 'Faka ithokhani le-API yakho kwi-{header} phezulu:'
    },
    'ep_models': {'ar': 'النماذج', 'bn': 'মডেল', 'cs': 'Modely',
        'el': 'Μοντέλα', 'fa': 'مدل‌ها', 'fi': 'Mallit',
        'he': 'מודלים', 'hi': 'मॉडल', 'hu': 'Modellek',
        'ms': 'Model', 'nb': 'Modeller', 'pl': 'Modele',
        'th': 'แบบจำลอง', 'tr': 'Modeller', 'zu': 'Imimela'
    },
    'ep_list_models': {'ar': 'سرد جميع النماذج الخاصة بك', 'bn': 'আপনার সমস্ত মডেল তালিকাভুক্ত করুন', 'cs': 'Seznamte se se všemi svými modely',
        'el': 'Λίστα όλων των μοντέλων σας', 'fa': 'لیست تمام مدل‌های شما', 'fi': 'Luettele kaikki mallisi',
        'he': 'הצג את כל המודלים שלך', 'hi': 'अपने सभी मॉडलों की सूची बनाएं', 'hu': 'Az összes modell listázása',
        'ms': 'Senaraikan semua model anda', 'nb': 'Vis alle modellene dine', 'pl': 'Wyświetl wszystkie swoje modele',
        'th': 'แสดงรายการแบบจำลองทั้งหมดของคุณ', 'tr': 'Tüm modellerinizi listeleyin',
        'zu': 'Bheka imodeli yakho zonke'
    },
    'ep_providers': {'ar': 'المزودون', 'bn': 'প্রোভাইডার', 'cs': 'Poskytovatelé',
        'el': 'Πάροχοι', 'fa': 'پرایدرها', 'fi': 'Tarjoajat',
        'he': 'ספקים', 'hi': 'प्रदाता', 'hu': 'Szolgáltatók',
        'ms': 'Penyedia', 'nb': 'Tilbydere', 'pl': 'Dostawcy',
        'th': 'ผู้ให้บริการ', 'tr': 'Sağlayıcılar', 'zu': 'Abahlinzeki'
    },
    'ep_list_providers': {'ar': 'سرد المزودين المكونين لديك', 'bn': 'আপনার কনফিগার করা প্রোভাইডার তালিকাভুক্ত করুন',
        'cs': 'Seznamte se se svými konfigurovanými poskytovateli', 'el': 'Λίστα των ρυθμισμένων σας παρόχων',
        'fa': 'لیست پرایدرهای پیکربندی شده شما', 'fi': 'Luettele konfiguroimat tarjoajasi',
        'he': 'הצג את ספקי השירותים המוגדרים שלך', 'hi': 'अपने कॉन्फ़िगर किए गए प्रदाताओं की सूची बनाएं', 'hu': 'A konfigurált szolgáltatók listázása',
        'ms': 'Senaraikan penyedia terkonfigurasi anda', 'nb': 'Vis de konfigurerte tilbyderne dine', 'pl': 'Wyświetl skonfigurowanych dostawców',
        'th': 'แสดงรายการผู้ให้บริการที่กำหนดค่าแล้วของคุณ', 'tr': 'Yapılandırılmış sağlayıcılarınızı listeleyin',
        'zu': 'Bheka abahlinzeki abasebenzisiwe akho'
    },
    'ep_rotations_autoselect': {'ar': 'التناوبات والاختيار التلقائي', 'bn': 'ঘূর্ণন এবং স্বয়ংক্রিয় নির্বাচন',
        'cs': 'Rotace a automatický výběr', 'el': 'Εναλλαγές και αυτόματη επιλογή',
        'fa': 'چرخش‌ها و انتخاب خودکار', 'fi': 'Kierto ja automaattinen valinta',
        'he': 'סיבובים ובחירה אוטומטית', 'hi': 'रोटेशन और स्वचालित चयन', 'hu': 'Rotációk és automatikus kiválasztás',
        'ms': 'Putaran dan pilihan automatik', 'nb': 'Roter og automatisk valg', 'pl': 'Rotacje i automatyczny wybór',
        'th': 'การหมุนเวียนและการเลือกอัตโนมัติ', 'tr': 'Döngüler ve otomatik seçim',
        'zu': 'Ukususa okubuyela emuva nokukhetha ngokuzenzekela'
    },
    'ep_list_rotations': {'ar': 'سرد التناوبات الخاصة بك', 'bn': 'আপনার ঘূর্ণন তালিকাভুক্ত করুন',
        'cs': 'Seznamte se se svými rotacemi', 'el': 'Λίστα των εναλλαγών σας',
        'fa': 'لیست چرخش‌های شما', 'fi': 'Luettele kiertosi',
        'he': 'הצג את הסיבובים שלך', 'hi': 'अपने रोटेशनों की सूची बनाएं', 'hu': 'A rotációk listázása',
        'ms': 'Senaraikan putaran anda', 'nb': 'Vis de roteringslistene dine', 'pl': 'Wyświetl listę rotacji',
        'th': 'แสดงรายการการหมุนเวียนของคุณ', 'tr': 'Rotasyonlarınızı listeleyin',
        'zu': 'Bheka ukususa okubuyela emuva kwakho'
    },
    'ep_list_autoselects': {'ar': 'سرد الاختيارات التلقائية الخاصة بك', 'bn': 'আপনার স্বয়ংক্রিয় নির্বাচন তালিকাভুক্ত করুন',
        'cs': 'Seznamte se se svými automatickými výběry', 'el': 'Λίστα των αυτόματων επιλογών σας',
        'fa': 'لیست انتخاب‌های خودکار شما', 'fi': 'Luettele automaattiset valintasi',
        'he': 'הצג את הבחירות האוטומטיות שלך', 'hi': 'अपने स्वचालित चयनों की सूची बनाएं', 'hu': 'Az automatikus kiválasztások listázása',
        'ms': 'Senaraikan pilihan automatik anda', 'nb': 'Vis de automatiske valgene dine', 'pl': 'Wyświetl listę wyborów automatycznych',
        'th': 'แสดงรายการการเลือกอัตโนมัติของคุณ', 'tr': 'Otomatik seçimlerinizi listeleyin',
        'zu': 'Bheka ukukhetha ngokuzenzekela kwakho'
    },
    'ep_chat': {'ar': 'محادثة باستخدام إعداداتك', 'bn': 'আপনার কনফিগারেশন ব্যবহার করে চ্যাট করুন',
        'cs': 'Chat pomocí vašich nastavení', 'el': 'Συνομιλία με χρήση των ρυθμίσεων σας',
        'fa': 'چت با استفاده از تنظیمات شما', 'fi': 'Keskustele asetustesi avulla',
        'he': 'צאט באמצעות ההגדרות שלך', 'hi': 'अपनी सेटिंग्स का उपयोग करके चैट करें', 'hu': 'Csevegés a beállításaid használatával',
        'ms': 'Sembang menggunakan tetapan anda', 'nb': 'Chat med innstillingene dine', 'pl': 'Czatuj używając swoich ustawień',
        'th': 'แชทโดยใช้การกำหนดค่าของคุณ', 'tr': 'Ayarlarınızı kullanarak sohbet et',
        'zu': 'Xoxa ngokusetshenziswa kwakho'
    },
    'ep_chat_desc': {'ar': 'إرسال طلبات الدردشة باستخدام إعداداتك', 'bn': 'আপনার কনফিগারেশন ব্যবহার করে চ্যাট অনুরোধ পাঠান',
        'cs': 'Odeslat chatové požadavky pomocí vašich nastavení', 'el': 'Αποστολή αιτημάτων συνομιλίας με χρήση των ρυθμίσεων σας',
        'fa': 'ارسال درخواست‌های چت با استفاده از تنظیمات شما', 'fi': 'Lähetä chat-pyyntöjä asetustesi avulla',
        'he': 'שלח בקשות צאט באמצעות ההגדרות שלך', 'hi': 'अपनी सेटिंग्स का उपयोग करके चैट अनुरोध भेजें', 'hu': 'Csevegőkérések küldése a beállítások használatával',
        'ms': 'Hantar permintaan sembang menggunakan tetapan anda', 'nb': 'Send chatforespørsler med innstillingene dine', 'pl': 'Wyślij żądania czatu używając swoich ustawień',
        'th': 'ส่งคำขอแชทโดยใช้การกำหนดค่าของคุณ', 'tr': 'Ayarlarınızı kullanarak sohbet istekleri gönderin',
        'zu': 'Thumela izicelo zengxoxo kusetshenziswa kwakho'
    },
    'ep_mcp': {'ar': 'أدوات MCP', 'bn': 'MCP টুল', 'cs': 'Nástroje MCP',
        'el': 'Εργαλεία MCP', 'fa': 'ابزارهای MCP', 'fi': 'MCP-työkalut',
        'he': 'כלי MCP', 'hi': 'MCP उपकरण', 'hu': 'MCP eszközök',
        'ms': 'Alat MCP', 'nb': 'MCP-verktøy', 'pl': 'Narzędzia MCP',
        'th': 'เครื่องมือ MCP', 'tr': 'MCP araçları', 'zu': 'Amathuluzi e-MCP'
    },
    'ep_mcp_list': {'ar': 'سرد أدوات MCP', 'bn': 'MCP টুল তালিকাভুক্ত করুন', 'cs': 'Seznamte se s nástroji MCP',
        'el': 'Λίστα εργαλείων MCP', 'fa': 'لیست ابزارهای MCP', 'fi': 'Luettele MCP-työkalut',
        'he': 'הצג את כלי ה-MCP', 'hi': 'MCP उपकरणों की सूची बनाएं', 'hu': 'Az MCP eszközök listázása',
        'ms': 'Senaraikan alat MCP', 'nb': 'Vis MCP-verktøyene', 'pl': 'Wyświetl narzędzia MCP',
        'th': 'แสดงรายการเครื่องมือ MCP', 'tr': 'MCP araçlarını listeleyin',
        'zu': 'Bheka amathuluzi e-MCP'
    },
    'ep_mcp_call': {'ar': 'استدعاء أدوات MCP', 'bn': 'MCP টুল ডাকুন', 'cs': 'Volat nástroje MCP',
        'el': 'Κλήση εργαλείων MCP', 'fa': 'فراخوانی ابزارهای MCP', 'fi': 'Kutsu MCP-työkaluja',
        'he': 'הפעלת כלי MCP', 'hi': 'MCP उपकरणों को कॉल करें', 'hu': 'Az MCP eszközök hívása',
        'ms': 'Panggil alat MCP', 'nb': 'Kall MCP-verktøy', 'pl': 'Wywołaj narzędzia MCP',
        'th': 'เรียกใช้เครื่องมือ MCP', 'tr': 'MCP araçlarını çağırın',
        'zu': 'Biza amathuluzi e-MCP'
    },
    'ep_model_formats': {'ar': 'أمثلة تنسيق النموذج', 'bn': 'মডেল বিন্যাসের উদাহরণ', 'cs': 'Příklady formátů modelů',
        'el': 'Παραδείγματα μορφής μοντέλου', 'fa': 'مثال‌های قالب مدل', 'fi': 'Mallimuotojen esimerkkejä',
        'he': 'דוגמאות עבור תבניות מודל', 'hi': 'मॉडल प्रारूप उदाहरण', 'hu': 'Modellszabályok példái',
        'ms': 'Contoh format model', 'nb': 'Eksempler på modellformater', 'pl': 'Przykłady formatów modeli',
        'th': 'ตัวอย่างรูปแบบโมเดล', 'tr': 'Model biçimi örnekleri', 'zu': 'Imizobo yemifomethi yemodeli'
    },
    'admin_access': {'ar': 'وصول المسؤول', 'bn': 'অ্যাডমিন অ্যাক্সেস', 'cs': 'Přístup správce',
        'el': 'Πρόσβαση διαχειριστή', 'fa': 'دسترسی مدیر', 'fi': 'Ylläpitäjän pääsy',
        'he': 'גישת מנהל', 'hi': 'व्यवस्थापक पहुंच', 'hu': 'Admin hozzáférés',
        'ms': 'Akses pentadbir', 'nb': 'Tilgang for administrator', 'pl': 'Dostęp administratora',
        'th': 'การเข้าถึงของผู้ดูแลระบบ', 'tr': 'Yönetici erişimi', 'zu': 'Ukufinyelela komqondisi'
    },
    'admin_access_desc': {'ar': 'كما أنك مسؤول، يمكنك أيضاً الوصول إلى التكوينات العالمية عبر تنسيقات النموذج الأقصر:',
        'bn': 'যেহেতু আপনি অ্যাডমিন, আপনি সংক্ষিপ্ত মডেল ফরম্যাটের মাধ্যমে বৈশ্বিক কনফিগারেশনগুলিতেও অ্যাক্সেস করতে পারেন:',
        'cs': 'Jako správce máte také přístup k globálním konfiguracím prostřednictvím kratších formátů modelů:',
        'el': 'Ως διαχειριστής, έχετε πρόσβαση στις παγκόσμιες ρυθμίσεις μέσω συντομότερων μορφών μοντέλου:',
        'fa': 'از آنجا که شما مدیر هستید، همچنین می‌توانید از طریق قالب‌های مدل کوتاه‌تر به پیکربندی‌های سراسری دسترسی داشته باشید:',
        'fi': 'Ylläpitäjänä sinulla on pääsy globaaleihin kokoonpanoihin myös lyhyempien mallimuotojen kautta:',
        'he': 'כיוון שאתה מנהל, יש לך גישה גם לתצורות הגלובליות דרך פורמטי מודל קצרים יותר:',
        'hi': 'चूंकि आप व्यवस्थापक हैं, आपको छोटे मॉडल प्रारूपों के माध्यम से वैश्विक कॉन्फ़िगरेशनों तक भी पहुंच है:',
        'hu': 'Mivel adminisztrátor, hozzáférhet a globális konfigurációkhoz a rövidebb modellformátumok használatával is:',
        'ms': 'Sebagai pentadbir, anda juga mempunyai akses kepada konfigurasi global melalui format model yang lebih pendek:',
        'nb': 'Som administrator har du også tilgang til globale konfigurasjoner via kortere modellformater:',
        'pl': 'Jako administrator masz również dostęp do konfiguracji globalnych za pomocą krótszych formatów modeli:',
        'th': 'ในฐานะผู้ดูแลระบบ คุณยังสามารถเข้าถึงการกำหนดค่าทั่วไปได้ผ่านทางรูปแบบโมเดลที่สั้นลง:',
        'tr': 'Yönetici olarak, daha kısa model formatları aracılığıyla küresel yapılandırmalara da erişiminiz vardır:',
        'zu': 'Njengomqondisi, unokufinyelela ngokusebenzisa imifomethi yemodeli emfushane konfigurashoni yezizwe:'
    },
    'token_required': {'ar': 'مطلوب رمز API الخاص بك لجميع نقاط النهاية.',
        'bn': 'সব এন্ডপয়েন্টের জন্য আপনার API টোকেন প্রয়োজন।',
        'cs': 'Pro všechny koncové body je vyžadován váš token API.',
        'el': 'Απαιτείται το διακριτικό API σας για όλα τα endpoints.',
        'fa': 'برای تمام نقطه پایانی‌ها، توکن API شما مورد نیاز است.',
        'fi': 'Kaikkien päätepisteiden käyttö vaatii API-tokenisi.',
        'he': 'נדרש טוקן ה-API שלך עבור כל נקודות הסיום.',
        'hi': 'सभी एंडपॉइंट्स के लिए आपके API टोकन की आवश्यकता है।',
        'hu': 'Az összes végpont használata érvényes API-tokenet igényel.',
        'ms': 'Token API anda diperlukan untuk semua titik akhir.',
        'nb': 'Ditt API-token kreves for alle endepunkter.',
        'pl': 'Wszystkie punkty końcowe wymagają Twojego tokena API.',
        'th': 'โทเค็น API ของคุณจำเป็นสำหรับทุกจุดสิ้นสุด',
        'tr': 'Tüm uç noktalar için API tokeniniz gereklidir.',
        'zu': 'Kudingeka ithokhani le-API yakho zonke iziphumo zakho.'
    },
    'manage_tokens': {'ar': 'إدارة رموزك →', 'bn': 'আপনার টোকেনগুলি পরিচালনা করুন →',
        'cs': 'Spravujte své tokeny →', 'el': 'Διαχείριση διακριτικών σας →',
        'fa': 'مدیریت توکن‌های شما →', 'fi': 'Hallitse tokeneja →',
        'he': 'נהל את הטוקנים שלך →', 'hi': 'अपने टोकन प्रबंधित करें →',
        'hu': 'Jelzései kezelése →', 'ms': 'Urus token anda →',
        'nb': 'Administrer tokenene dine →', 'pl': 'Zarządzaj swoimi tokenami →',
        'th': 'จัดการโทเค็นของคุณ →', 'tr': 'Tokenlarınızı yönetin →',
        'zu': 'Phatha amathekheni akho →'
    }
}

for lang in langs:
    trans = {}
    for key, val_dict in user_overview_keys.items():
        if lang in val_dict:
            trans[f'user_overview.{key}'] = val_dict[lang]
    apply(lang, trans)
    print(f'Applied {len(trans)} user_overview keys for {lang}')

print('\nAll user_overview keys applied!')

