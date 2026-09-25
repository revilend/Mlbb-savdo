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
| 🧮 Narx kalkulyatori | Rank va skin toifalari asosida real bozor narxini hisoblaydi |
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

## 📁 Tuzilma

```
.
├── env.example          # .env uchun namuna (nusxalab .env qiling)
├── requirements.txt
├── config.py            # .env dan sozlamalar
├── database.py          # aiosqlite qatlami (9 jadval)
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
│   └── test_features2.py  # sharhlar, taklif/bitim, obuna, referal, muddat, analitika
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
    ├── subscriptions.py # saqlangan qidiruv (obuna)
    ├── calculator.py    # narx kalkulyatori
    ├── scam_check.py    # firibgarni tekshirish
    ├── my_listings.py   # mening e'lonlarim (sold / UP / tahrir / yangilash)
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
   GARANT_USERNAME=my_garant      # garant akkunti (@ belgisisiz)
   ```

   Anti-flood, xabarlarni tozalash, kunlik hisobot, e'lon muddati, kunning
   tanlovi va zaxira nusxa sozlamalari ham `env.example` faylida izohlari
   bilan keltirilgan (`FLOOD_*`, `SELF_DESTRUCT_*`, `DIGEST_*`,
   `LISTING_TTL_DAYS`, `FEATURED_*`, `BACKUP_*`, `REFERRAL_REWARD_VIP`).

5. Botni kanalga **administrator** qilib qo'shing (a'zolikni tekshirishi va
   e'lon joylashi uchun shart).

6. Ishga tushiring:

   ```bash
   python main.py
   ```

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

Suite **172 ta test**dan iborat va tashqi tarmoqqa umuman murojaat qilmaydi
(Telegram API soxtalashtiriladi, vaqt `Clock` fixture'i bilan boshqariladi,
shuning uchun testlar tez va deterministik).

| Fayl | Testlar | Qamrov |
| --- | --- | --- |
| `test_anti_flood.py` | 30 | sürgülü oyna, ogohlantirish throttling, mute va uning tugashi, purge, jimgina rejim, callback kafolati, bypass, GC, `build_anti_flood()` |
| `test_self_destruct.py` | 40 | `temporary`/`permanent`, `MessageRegistry`, rejalashtirish qoidalari (kanal/guruh himoyasi), haqiqiy o'chirish, `shutdown()`, session zanjiri integratsiyasi, `sweep_chat()`, foydalanuvchi tozalagichi |
| `test_features.py` | 37 | barter/rejim anketasi, narx tushirish (kanal + sevimlilar), ulashish tugmasi, qo'llanma, kunlik hisobot, admin va kanal boshqaruvi, yangi DB ustunlari |
| `test_features2.py` | 65 | sharhlar va reyting, taklif/bitim oqimi, obuna va mos e'lon xabari, referal, e'lon tahriri va yangilash, o'xshash e'lonlar, muddat/tanlov/zaxira fon vazifalari, analitika |

**Regressiya himoyasi:** `test_default_settings_are_gentle` sukut qiymatlar
yumshoq rejimda qolishini kafolatlaydi — kimdir chegaralarni qattiqlashtirsa,
test darhol yiqiladi.

## 🧾 Ma'lumotlar bazasi

`market_database.sqlite3` fayli birinchi ishga tushirishda avtomatik yaratiladi.

- `settings` — dinamik sozlamalar (kanallar, adminlar ro'yxati)
- `users` — foydalanuvchilar (`referred_by`, `free_vip` bilan)
- `listings` — e'lonlar (`sell` / `buy`, `listing_mode` `sell`/`trade`, `expires_at`)
- `favorites` — sevimlilar
- `blacklist` — firibgarlar ro'yxati
- `reviews` — sotuvchi reytingi va sharhlari
- `saved_searches` — «🔔 Qidiruv obunasi» shartlari
- `offers` — takliflar va ularning holati
- `deals` — bitimlar va kuzatuv bosqichlari

Eski bazalar avtomatik yangilanadi: `_MIGRATIONS` ro'yxati yetishmayotgan
ustunlarni (masalan `listings.expires_at`, `users.free_vip`) `ALTER TABLE`
bilan qo'shadi va bu amal idempotent.

Zaxira nusxalar `BACKUP_DIR` (sukut: `backups/`) ichida
`market_backup_YYYY-MM-DD_HH-MM-SS.sqlite3` ko'rinishida saqlanadi va
`BACKUP_KEEP` tadan ortig'i avtomatik o'chiriladi.
