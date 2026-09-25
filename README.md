# Mlbb-savdo — MLBB akkaunt savdosi uchun Telegram bot

Mobile Legends: Bang Bang (MLBB) akkauntlarini **xavfsiz sotish va sotib olish**
uchun to'liq tayyor Telegram bot. Python, aiogram 3.x va aiosqlite asosida yozilgan.

## ✨ Imkoniyatlar

| Bo'lim | Tavsif |
| --- | --- |
| 🔍 Akkaunt qidirish | Xaridor so'rovi anketasi (sotib olish / almashtirish) → moderatsiya → kanal |
| 💰 Akkaunt sotish | 7 bosqichli anketa: rank → skinlar → narx → VIP → aloqa → izoh → 10 tagacha rasm |
| 🎲 Tasodifiy akkaunt | Bazadan tasodifiy aktiv e'lonni ko'rsatadi |
| 💵 Narx bo'yicha saralash | 100k gacha / 100k–400k / 400k+ oralig'i |
| ⭐️ Sevimlilarim | E'lonlarni saqlash va ro'yxatini ko'rish |
| 🔍 Akkauntni baholatish | Skrinshotlarni adminga yuborib, bozor narxini admin baholashidan olish |
| 🛡️ Firibgarni tekshirish | Qora ro'yxatdan username yoki ID bo'yicha tekshirish |
| 📋 Mening e'lonlarim | Holatni ko'rish, «Sotildi» belgilash, 24 soatda bir marta UP |
| 🛡️ Garant xizmati | Xavfsiz bitim jarayoni va Moonton akkauntni o'tkazish ro'yxati |
| 📊 Statistika | Foydalanuvchilar, aktiv e'lonlar, sotilgan akkauntlar |
| 🔄 Almashish (Barter) | Sotish anketasida rejim tanlash — narx o'rniga «🎯 Talab» ko'rsatiladi |
| 📉 Narxni tushirish | Kanaldagi e'lon avtomatik yangilanadi, sevimlilarga darhol push xabar boradi |
| ↗️ Ulashish | Har bir e'londa «Do'stlarga ulashish» tugmasi (`?start=view_{id}`) |
| ❓ Qoʻllanma | Xavfsiz sotib olish, garant qoidalari va e'lon berish bo'yicha qo'llanma |
| 📥 Takliflar va bitimlar | Kelgan takliflarni qabul/rad etish yoki javob yozish, bitim holatini kuzatish |
| 🔔 Qidiruv obunasi | Narx oralig'i + kalit so'z bo'yicha obuna — mos yangi e'lon chiqsa darhol xabar |
| ⭐️ Reyting va sharhlar | Sotuvchiga 1–5 baho va izoh; reyting e'lon kartochkasida ko'rinadi |
| 💬 E'lonni bo'lishish | Sotuvgan e'longa izoh qoldirish — izohlar e'lon kartasida barchaga ko'rinadi |
| ✅ Sotuvchini tasdiqlash | Admin sotuvchini tasdiqlaydi, e'lon kartochkasida `✅` ishonch belgisi chiqadi |
| 🚨 Sotuvchini shikoyat qilish | E'lon kartasidan sabab tanlab shikoyat yuborish; admin panelida ko'rib chiqiladi |
| 📈 Narx statistikasi | Faqat sotilgan e'lonlar bo'yicha rank kesimidagi o'rtacha narx va bozor tavsiyasi |
| ⭐️ Botga baho | Botga 1–10 baho va izoh; o'rtacha baho statistikada, past bahoda admin xabardor |
| ✏️ Tahrirlash | Aktiv/moderatsiyadagi e'londa narx, izoh va aloqani o'zgartirish |
| 🔄 E'lonni yangilash | `LISTING_TTL_DAYS` tugagach e'lon arxivlanadi va bir tugma bilan yangilanadi |
| 🔎 O'xshash e'lonlar | Kartochkadan shu narx oralig'idagi boshqa e'lonlarni ko'rish |
| 🎁 Referal | Taklif havolasi, taklif qilinganlar soni va bepul VIP e'lon kreditlari |
| 🤝 Bitim kuzatuvi | «Yangi → Garant → Yakunlandi» bosqichlari, ikkala tomonga xabar |
| 🚨 Anti-fraud tekshiruvi | E'lon/so'rov joylanishida aloqa va username qora ro'yxat bilan solishtiriladi |
| 🌟 Kunning tanlovi | Har kuni belgilangan vaqtda kanalga tanlangan (VIP ustuvor) e'lon |
| 🕗 Kunlik hisobot | Har kuni 23:59 da adminlarga yangi a'zolar/e'lonlar/sotuvlar hisoboti |
| 💾 Zaxira nusxa | Har kuni bazaning SQLite nusxasi olinadi, eskilari tozalanadi, admin yuklab oladi |
| 🧹 Chatni tozalash | `/clean` — chatdagi barcha bot xabarlarini bir zumda o'chiradi |
| 🛠️ Admin panel | Moderatsiya, tarqatish, adminlar, kanallar, qidiruv, qora ro'yxat, analitika, zaxira |
| 🐢 Anti-flood | Har bir foydalanuvchi uchun so'rovlar chegarasi + bosqichli mute |
| ⏱ Self-destruct | Bot xabarlari belgilangan vaqtdan keyin o'z-o'zidan o'chadi |
| ⚙️ Bot ichidagi sozlamalar | Narx chegaralari, vaqtlar, kanal, garant, anti-flood, xabar TTL va AI — hammasi bot ichidan; `.env` shart emas |
| 🤖 AI moderatsiya | E'lonlarni AI orqali tekshirish; admin bir tugma bilan yoqadi/o'chiradi, kalitni bot ichida kiritadi va istalgan e'lonni qo'lda qayta tekshiradi |

## 📁 Tuzilma

```
.
├── env.example          # .env uchun namuna (nusxalab .env qiling)
├── requirements.txt
├── config.py            # .env dan standart sozlamalar
├── settings.py          # bot ichidan boshqariladigan runtime sozlamalar reyestri
├── ai.py                # OpenAI-mos AI moderatsiya mijozi
├── database.py          # aiosqlite qatlami (12 jadval)
├── keyboards.py         # barcha klaviatura va tugma matnlari
├── states.py            # FSM holatlari
├── main.py              # ishga tushirish nuqtasi + fon vazifalari
├── pytest.ini           # test konfiguratsiyasi
├── requirements-dev.txt # pytest va boshqa dev kutubxonalar
├── tests/
│   ├── conftest.py        # fixture'lar, soxta Telegram obyektlari, boshqariladigan vaqt
│   ├── test_anti_flood.py # anti-flood middleware testlari
│   ├── test_self_destruct.py # TTL / reyestr / tozalagich testlari
│   ├── test_features.py   # barter, narx tushirish, ulashish, kunlik hisobot, admin panel
│   ├── test_features2.py  # sharhlar, taklif/bitim, obuna, referal, muddat, analitika
│   ├── test_features3.py  # bot ichidagi sozlamalar, AI moderatsiya va sozlamalar paneli
│   └── test_features4.py  # bozor statistikasi, shikoyat, komment, bot bahosi, tasdiqlash
├── middlewares/
│   ├── anti_flood.py      # spamga qarshi cheklov (sliding window + mute)
│   └── self_destruct.py   # o'z-o'zini o'chiruvchi xabarlar + /clean reyestri
└── handlers/
    ├── common.py        # /start, obuna tekshiruvi, bekor qilish, statistika, referal, /admin
    ├── sell.py          # sotish anketasi
    ├── search.py        # xaridor so'rovi
    ├── catalog.py       # katalog, filtr, o'xshash e'lonlar, bitim so'rovi
    ├── favorites.py     # sevimlilar
    ├── offers.py        # narx taklifi
    ├── inbox.py         # takliflar va bitimlar bo'limi
    ├── reviews.py       # sotuvchi reytingi va sharhlari
    ├── market.py        # narx statistikasi, bozor tavsiyasi, sotuvchini shikoyat qilish
    ├── comments.py      # e'lonni bo'lishish (izohlar)
    ├── bot_rating.py    # botga 1–10 baho berish
    ├── subscriptions.py # saqlangan qidiruv (obuna)
    ├── calculator.py    # admin yordamida akkaunt baholash
    ├── scam_check.py    # firibgarni tekshirish
    ├── my_listings.py   # mening e'lonlarim (sold / UP / tahrir / yangilash)
    ├── moderation.py    # AI moderatsiya natijasini qo'llash (avto-tasdiq/rad)
    ├── settings_panel.py # «⚙️ Sozlamalar» paneli (bot ichidan boshqaruv)
    ├── garant.py        # garant xizmati
    └── admin.py         # admin panel (analitika, zaxira nusxa bilan)
```

## 🚀 O'rnatish

1. **Python 3.10+** o'rnatilgan bo'lishi kerak.

2. Kutubxonalarni o'rnating:

   ```bash
   pip install -r requirements.txt
   ```

3. `.env` faylini yarating:

   ```bash
   cp env.example .env
   ```

4. `.env` faylini to'ldiring:

   ```env
   BOT_TOKEN=123456789:AA...      # @BotFather dan
   ADMIN_ID=123456789             # @userinfobot dan
   DEFAULT_CHANNEL_ID=@mlbb_savdo # e'lonlar joylanadigan kanal
   GARANT_USERNAME=mlbbSATORU     # garant akkunti (@ belgisisiz)
   ```

   > **Faqat shu ikkitasi majburiy:** `BOT_TOKEN` va `ADMIN_ID`. Qolgan
   > hamma narsani bot ichidan sozlash mumkin — loyihani sotib olgan kishi
   > `.env` fayliga tegishi shart emas (pastdagi «Bot ichidan boshqaruv»
   > bo'limiga qarang).

   `env.example` faylida barcha sozlamalar (`FLOOD_*`, `SELF_DESTRUCT_*`,
   `DIGEST_*`, `LISTING_TTL_DAYS`, `FEATURED_*`, `BACKUP_*`, `AI_*`,
   `REFERRAL_REWARD_VIP`) izohlari bilan keltirilgan — ular standart
   qiymat bo'lib qoladi.

5. Botni kanalga **administrator** qilib qo'shing (a'zolikni tekshirishi va
   e'lon joylashi uchun shart).

6. Ishga tushiring:

   ```bash
   python main.py
   ```

## ☁️ Render'da joylash

Loyiha uchun `render.yaml` fayli tayyor. Render'da **Background Worker** yaratish uchun:

1. GitHub repositoriyasini Render'ga ulang.
2. **New → Blueprint** tanlang va shu repository'ni ko'rsating.
3. Render so'raydigan `BOT_TOKEN` va `ADMIN_ID` qiymatlarini kiriting.
4. `AI_API_KEY` ni faqat AI moderatsiyani yoqish kerak bo'lsa kiriting.
5. Botni kanalda administrator qilib qo'shing va deployni boshlang.

`render.yaml` botni `/var/data` doimiy diskinga ulaydi. Shu sababli SQLite baza va zaxira nusxalari Render redeploy qilinganda ham saqlanadi. Render Worker va doimiy disk uchun to'lovli reja kerak bo'lishi mumkin.

Muhim environment qiymatlari:

- `BOT_TOKEN` — BotFather tokeni, majburiy.
- `ADMIN_ID` — asosiy admin Telegram ID, majburiy.
- `DB_PATH` — `/var/data/market_database.sqlite3`, Render diskka ulangan.
- `BACKUP_DIR` — `/var/data/backups`, zaxira nusxalari shu yerda.
- `AI_API_KEY` — ixtiyoriy, faqat AI moderatsiya yoqilgan bo'lsa kerak.

Render'da `.env` faylini yuklash shart emas. Render Dashboard → **Environment** orqali maxfiy qiymatlarni kiriting; ular GitHub'ga yozilmaydi.

## ⚙️ Bot qanday ishlaydi

1. Foydalanuvchi `/start` bosadi → obuna tekshiriladi → asosiy menyu.
2. «💰 Akkaunt sotish» orqali anketa to'ldiriladi va `pending` holatida saqlanadi.
3. Admin xabar oladi va «✅ Kanalga chiqarish» yoki «❌ Rad etish» ni tanlaydi.
4. Tasdiqlangach e'lon kanalga avtomatik hashtaglar bilan chiqadi
   (`#MythicGlory #45kof #2500k #Mlbb #Savdo`).
5. Xaridor «🛡️ Admin orqali sotib olish» yoki «💬 Narx taklif qilish» orqali
   bog'lanadi.
6. Sotuvchi «✅ Sotildi deb belgilash» bosganda kanaldagi e'lon
   «🔴 SOTILDI» sarlavhasi bilan yangilanadi va tugmalar olib tashlanadi.
7. «📉 Narxni tushirish» orqali eski narx ustidan chizilib, kanaldagi e'lon
   «🔥 NARX TUSHDI» bilan yangilanadi va sevimlilarga push xabar ketadi.
8. Yuborilgan har bir taklif bazaga saqlanadi: sotuvchi «📥 Takliflar va
   bitimlar» bo'limida qabul/rad etadi yoki javob yozadi, xaridor esa holatni
   kuzatadi.
9. «🛡️ Admin orqali sotib olish» bitim qayd etadi — admin «🛡️ Garantga o'tdi»,
   «✅ Yakunlandi» yoki «❌ Bekor qilindi» tugmalari bilan holatni boshqaradi
   va ikkala tomonga xabar boradi.
10. Bitimdan so'ng e'lon kartochkasidagi «⭐️ Sharh qoldirish» orqali sotuvchiga
    1–5 baho beriladi; o'rtacha reyting keyingi kartochkalarda ko'rinadi.
11. «🔔 Qidiruv obunasi» shartlariga mos yangi e'lon tasdiqlanganda obunachi
    avtomatik xabardor qilinadi.
12. E'lon `LISTING_TTL_DAYS` (sukut: 14 kun) amal qiladi. Muddat tugasa e'lon
    arxivlanadi, kanaldagi post yangilanadi va egasi «🔄 Yangilash» tugmasini
    oladi.
13. Har kuni `FEATURED_HOUR` da kanalga «🌟 Kunning tanlovi» e'lon joylanadi,
    `BACKUP_HOUR` da bazaning zaxira nusxasi olinadi.
14. Har kuni 23:59 da barcha adminlarga kunlik hisobot (yangi a'zolar,
    e'lonlar, sotuvlar) yuboriladi.
15. AI moderatsiya yoqilgan bo'lsa yangi e'lon darhol AI orqali tekshiriladi:
    admin xabarida AI xulosasi (qaror, ishonch, sabab) ko'rinadi va sozlamaga
    qarab e'lon avtomatik tasdiqlanadi yoki rad etiladi. AI oʻchirilgan boʻlsa
    admin «🤖 AI tekshiruvi (qoʻlda)» tugmasi bilan istalgan eʼlonni qayta
    tekshirishi mumkin.

## ⚙️ Bot ichidan boshqaruv (sozlamalar paneli)

Asosiy menyudagi **«⚙️ Sozlamalar»** bo'limi (admin panelda ham mavjud)
orqali botni `.env` fayliga tegmasdan boshqarish mumkin:

| Bo'lim | Nima sozlanadi |
| --- | --- |
| 💰 Narx va e'lonlar | eng kam/yuqori narx, rasm va izoh chegarasi, e'lon muddati, UP tanaffusi, oʻxshash narx farqi, referal mukofoti |
| ⏰ Vaqt va hisobot | vaqt mintaqasi, kunlik hisobot vaqti, kunning tanlovi vaqti |
| 📣 Kanal va garant | asosiy e'lon kanali, garant akkaunti |
| 🤖 AI moderatsiya | yoqilgan/o'chirilgan, API kaliti, manzil, model, avto-qarorlar, ishonch chegarasi, qo'shimcha qoidalar |
| 💾 Zaxira nusxa | yoqilgan/o'chirilgan, papka, soat, saqlanadigan nusxalar soni |
| 🐢 Anti-flood | yoqilgan/o'chirilgan, oyna, hodisa chegarasi, mute vaqti, jimgina rejim, xabarlarni o'chirish |
| ⏱ Xabarlar va tozalash | self-destruct TTL, `/clean` chegarasi |

Ish printsipi:

- `.env` dagi qiymatlar — **standart** qiymat bo'lib qoladi;
- bot ichidan kiritilgan qiymat `settings` jadvalida `cfg:<KALIT>`
  ko'rinishida saqlanadi va har doim ustuvor;
- har bir sozlama yonida ✏️ (bot ichidan o'zgartirilgan) yoki • (standart)
  belgisi va **«↩️ Standart qiymat»** tugmasi bor;
- **AI kaliti** kabi maxfiy qiymatlar faqat niqoblangan holda ko'rsatiladi
  (`sk-o…cdef`) va kiritilganda xabar chatdan o'chiriladi;
- noto'g'ri qiymat (masalan harf o'rniga son kutilsa) saqlanmaydi — nima
  xato ekani tushunarli qilib aytiladi;
- anti-flood va self-destruct kabi ba'zi sozlamalar **qayta ishga tushgach**
  kuchga kiradi (panel buni ogohlantiradi).

## 🤖 AI moderatsiya

AI moderatsiya e'lonni matni bo'yicha tekshiradi (rank, skinlar, narx, izoh,
aloqa) va **TASDIQLASH / RAD ETISH / QO'LDA TEKSHIRISH** tavsiyasini ishonch
darajasi bilan beradi. Bot **OpenAI-mos** `chat/completions` API'si bilan
ishlaydi, shuning uchun bitta kalit bilan OpenRouter, OpenAI, Groq, DeepInfra,
Together, Mistral yoki o'z serveringizdan foydalanish mumkin. Qoʻshimcha ravishda
**Google Gemini** ham qoʻllab-quvvatlanadi — `AI_PROVIDER=gemini` yoki `AIza...`
boshlanuvchi kalit kiritilsa, bot provaydnerni oʻzi aniqlaydi (`auto`).

Eʼlon **rasmlari** ham tahlil qilinadi: birinchi 3 ta rasm yuklab, modelga
base64 koʻrinishida yuboriladi. Rasm yuklanmasa ham moderatsiya davom etadi.

**Admin panelidagi «🤖 AI» bo'limi** — bitta ekranda to'liq boshqaruv:

| Tugma | Vazifasi |
| --- | --- |
| ✅ AI tekshiruvni yoqish / ⛔️ oʻchirish | AI moderatsiyani bir bosishda yoqadi yoki oʻchiradi (kalit bo'lmasa ogohlantiradi) |
| 🔑 AI API kalitini kiritish | kalitni bot ichida kiritish (kiritilgan xabar chatdan o'chiriladi) |
| 🔌 Ulanishni tekshirish | kalit, manzil va modelni darhol tekshiradi |
| ⚙️ Barcha sozlamalar | model, `AI_PROVIDER`, `AI_BASE_URL`, avto-qarorlar, ishonch chegarasi, qo'shimcha qoidalar |
| 📋 Modellarni koʻrish | kalitingizga mavjud modellarni roʻyxatlab, toʻgʻrisini bir tugma bilan tanlash |

Ekranning yuqorisida joriy holat (yoqilgan/oʻchiqilgan), niqoblangan kalit,
model va manzil ko'rinib turadi.

**Kalitni bot ichida qo'shish:**

1. Admin panel → **🤖 AI** (yoki ⚙️ Sozlamalar → 🤖 AI moderatsiya) →
   **AI API kaliti** (kalitni oddiy xabar qilib yuboring — u avtomatik
   o'chiriladi).
2. **AI modelini** tanlang (masalan `openai/gpt-4o-mini`) va kerak bo'lsa
   `AI_BASE_URL` ni o'zgartiring.
3. **AI tekshiruvni yoqing** va «🔌 Ulanishni tekshirish» tugmasini bosing —
   kalit va ulanish darhol tekshiriladi.

**Qo'lda tekshirish:** har bir moderatsiya kartochkasida
«🤖 AI tekshiruvi (qoʻlda)» tugmasi bor — admin istalgan e'lonni (AI
avtomatik ishlagan yoki ishlamagan bo'lsa ham) bir bosishda qayta tekshirishi
va natijani darhol ko'rishi mumkin. AI oʻchirilgan yoki kalit kiritilmagan
boʻlsa, tugma nima yetishmayotganini aniq aytadi.

Qo'shimcha imkoniyatlar:

| Sozlama | Natija |
| --- | --- |
| `AI_AUTO_APPROVE=true` | AI ishonchli deb topsa e'lon avtomatik kanalga chiqadi (admin baribir xabardor qilinadi) |
| `AI_REJECT_SCAMS=true` | AI firibgarlik/spam deb topsa e'lon avtomatik rad etiladi |
| `AI_MIN_CONFIDENCE` | avtomatik qaror uchun minimal ishonch darajasi (sukut: 70%) |
| `AI_EXTRA_RULES` | AI uchun qo'shimcha qoidalar (masalan «10 000 so'mdan past narxni rad et») |

AI yoqilmagan bo'lsa bot avvalgidek ishlayveradi — moderatsiya faqat admin
qo'lda amalga oshiradi.

## 🐢 Anti-flood (spam himoyasi)

`AntiFloodMiddleware` `message` va `callback_query` uchun **outer middleware**
sifatida ulanadi — ya'ni routerlar ishga tushishidan oldin hodisani to'xtata oladi.

> Sukut bo'yicha **yumshatilgan rejim** yoqilgan: oddiy foydalanuvchi cheklovni
> umuman sezmaydi. Maqsad — botni Telegram tomonidan `429 Too Many Requests`
> bilan bloklanishdan himoya qilish, foydalanuvchini jazolash emas.

1. **Sürgülü oyna** — `FLOOD_WINDOW_SECONDS` (5s) ichida `FLOOD_MAX_EVENTS`
   (12) tadan ko'p hodisa yuborilsa, ortiqchalari o'tkazib yuboriladi.
2. **Ogohlantirish** — yumshoq ohangda; ogohlantirish xabari
   `FLOOD_WARNING_TTL` soniyadan keyin o'chadi va `FLOOD_NOTICE_COOLDOWN`
   bilan cheklanadi (spam bo'lmaydi).
3. **Mute** — faqat `FLOOD_VIOLATION_LIMIT` (5) marta buzgach,
   `FLOOD_MUTE_SECONDS` (30s) davomida cheklanadi. Qolgan vaqt ko'rsatiladi.
4. **Purge** — sukut bo'yicha **o'chirilgan** (`FLOOD_DELETE_MESSAGES=false`),
   ya'ni foydalanuvchining xabarlari o'chirilmaydi.
5. **Xotira himoyasi** — uzoq tinch turgan foydalanuvchilar holati avtomatik
   tozalanadi, hisob `FLOOD_MUTE_RESET_SECONDS` dan keyin nolga tushadi.

**Qo'shimcha rejimlar**

| Sozlama | Natija |
| --- | --- |
| `FLOOD_NOTIFY=false` | **Jimgina rejim** — ogohlantirish ham, mute xabari ham yo'q; takroriy so'rovlar shunchaki o'tkazib yuboriladi |
| `FLOOD_DELETE_MESSAGES=true` | Spam xabarlar chatdan ham o'chiriladi |
| `FLOOD_PROTECTION=false` | Himoya butunlay o'chadi (middleware ulanmaydi) |

Callback so'rovlar **har doim** javob oladi (aks holda Telegram mijozida
"yuklanmoqda" belgisi qolib ketadi). Administrator sukut bo'yicha cheklovdan ozod.

## ⏱ Self-destruct (o'z-o'zini o'chiruvchi xabarlar)

`SelfDestructMiddleware` **session (API so'rov) darajasida** ishlaydi, shuning uchun
`send_message`, `send_photo`, `send_media_group`, `copy_message` va boshqa barcha
yuborish yo'llari avtomatik qamrab olinadi.

| Holat | Xatti-harakat |
| --- | --- |
| Shaxsiy chat | Xabar `SELF_DESTRUCT_DEFAULT_TTL` soniyadan keyin o'chadi |
| Kanal / guruh (`chat_id < 0`) | **Hech qachon** o'chirilmaydi |
| `SELF_DESTRUCT_SKIP_CHAT_IDS` | Chetlab o'tiladi (ADMIN_ID sukut bo'yicha qo'shilgan) |
| `temporary(10)` | Shu blok ichidagi xabarlar 10 soniyadan keyin o'chadi |
| `permanent()` | Shu blok ichidagi xabarlar doim qoladi |

Handler ichida boshqarish:

```python
from middlewares import permanent, temporary

with temporary(10):
    await message.answer("Bu xabar 10 soniyadan keyin o'chadi")

with permanent():
    await message.answer("Bu xabar doim qoladi")
```

Ichki ro'yxatga oluvchi (`MessageRegistry`) tufayli `/clean` buyrug'i chatdagi
barcha bot xabarlarini bir zumda tozalaydi va asosiy menyuni qayta ko'rsatadi.

## 🛡️ Xavfsizlik

- Barcha foydalanuvchi matni HTML uchun ekranlanadi (`html.escape`).
- Bitimlar garant orqali yakunlanishi tavsiya etiladi.
- Firibgarlar qora ro'yxat orqali tekshiriladi.
- Kanaldagi e'lonlar va administrator xabarlari hech qachon avtomatik o'chirilmaydi.

## 🧪 Testlar

```bash
pip install -r requirements-dev.txt
pytest                 # barcha testlar (~2 sekund)
pytest tests/test_anti_flood.py -v
pytest -k "mute or window"
```

Suite **345 ta test**dan iborat va tashqi tarmoqqa umuman murojaat qilmaydi
(Telegram API soxtalashtiriladi, vaqt `Clock` fixture'i bilan boshqariladi,
shuning uchun testlar tez va deterministik).

| Fayl | Testlar | Qamrov |
| --- | --- | --- |
| `test_anti_flood.py` | 30 | sürgülü oyna, ogohlantirish throttling, mute va uning tugashi, purge, jimgina rejim, callback kafolati, bypass, GC, `build_anti_flood()` |
| `test_self_destruct.py` | 42 | `temporary`/`permanent`, `MessageRegistry`, rejalashtirish qoidalari (kanal/guruh himoyasi), haqiqiy o'chirish, `shutdown()`, session zanjiri integratsiyasi, `sweep_chat()`, foydalanuvchi tozalagichi |
| `test_features.py` | 37 | barter/rejim anketasi, narx tushirish (kanal + sevimlilar), ulashish tugmasi, qo'llanma, kunlik hisobot, admin va kanal boshqaruvi, yangi DB ustunlari |
| `test_features2.py` | 86 | sharhlar va reyting, taklif/bitim oqimi, obuna va mos e'lon xabari, referal, e'lon tahriri va yangilash, o'xshash e'lonlar, muddat/tanlov/zaxira fon vazifalari, analitika |
| `test_features3.py` | 98 | bot ichidagi sozlamalar (validatsiya, niqoblash, standartga qaytarish, guruhlar), AI javobini tahlil qilish, HTTP mijozi (qayta urinish, xato xaritalari), avto-tasdiq/rad, qoʻlda tekshirish, AI yoqish/oʻchirish paneli, sozlamalar paneli navigatsiyasi va admin cheklovi |
| `test_features4.py` | 52 | narx statistikasi (rank guruhlari, davr tanlash, bozor tavsiyasi), shikoyat oqimi (sabab, izoh, takrorlik), e'lon kommentlari, botga 1–10 baho (past bahoda admin ogohlantirishi), sotuvchini tasdiqlash va admin panelidagi shikoyatlar |

**Regressiya himoyasi:** `test_default_settings_are_gentle` sukut qiymatlar
yumshoq rejimda qolishini kafolatlaydi — kimdir chegaralarni qattiqlashtirsa,
test darhol yiqiladi.

## 🧾 Ma'lumotlar bazasi

`market_database.sqlite3` fayli birinchi ishga tushirishda avtomatik yaratiladi.

- `settings` — dinamik sozlamalar: adminlar ro'yxati, kanallar va bot ichidan
  kiritilgan barcha `cfg:*` qiymatlar (narx, vaqt, AI kaliti va hokazo)
- `users` — foydalanuvchilar (`referred_by`, `free_vip`, `is_verified` bilan)
- `listings` — e'lonlar (`sell` / `buy`, `listing_mode` `sell`/`trade`, `expires_at`)
- `favorites` — sevimlilar
- `blacklist` — firibgarlar ro'yxati
- `reviews` — sotuvchi reytingi va sharhlari
- `saved_searches` — «🔔 Qidiruv obunasi» shartlari
- `offers` — takliflar va ularning holati
- `deals` — bitimlar va kuzatuv bosqichlari
- `reports` — sotuvchi ustidan shikoyatlar va ularning holati
- `listing_comments` — e'longa qoldirilgan izohlar
- `bot_ratings` — botga berilgan baholar (1–10) va izohlar

Eski bazalar avtomatik yangilanadi: `_MIGRATIONS` ro'yxati yetishmayotgan
ustunlarni (masalan `listings.expires_at`, `users.free_vip`, `users.is_verified`) `ALTER TABLE`
bilan qo'shadi va bu amal idempotent.

Zaxira nusxalar `BACKUP_DIR` (sukut: `backups/`) ichida
`market_backup_YYYY-MM-DD_HH-MM-SS.sqlite3` ko'rinishida saqlanadi va
`BACKUP_KEEP` tadan ortig'i avtomatik o'chiriladi.

### Bazani tiklash

Admin panelidagi **♻️ Bazani tiklash** tugmasi orqali Telegram'dan `.sqlite3`
backup faylini yuklash mumkin. Bot faylni SQLite signature, `PRAGMA
integrity_check` va asosiy jadvallar (`settings`, `users`, `listings`) bo'yicha
tekshiradi. Faqat tekshiruvdan o'tgan faylga tasdiqlash oynasi ko'rsatiladi.

Tasdiqlashdan oldin joriy baza `market_database.sqlite3.pre_restore_...`
nomi bilan zaxiralanadi. Baza fayli atomik almashtiriladi; yangi fayl ochilmasa
yoki sxema mos kelmasa, avvalgi baza qaytariladi. Tiklash muvaffaqiyatli
bo'lsa, bot sozlamalari va adminlar ro'yxati qayta o'qiladi.

> ⚠️ Tiklash joriy bazadagi barcha foydalanuvchi, e'lon, taklif va bitim
> ma'lumotlarini almashtiradi. Faqat ishonchli va to'g'ri nusxani yuklang.
> Render'dagi disk vaqtincha bo'lsa, eng muhim zaxiralarni Telegram'dan
> tashqarida ham saqlang.
