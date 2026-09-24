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
| 🧹 Chatni tozalash | `/clean` — chatdagi barcha bot xabarlarini bir zumda o'chiradi |
| 🛠️ Admin panel | Moderatsiya, tarqatish, kanal sozlamasi, foydalanuvchi qidirish, qora ro'yxat |
| 🐢 Anti-flood | Har bir foydalanuvchi uchun so'rovlar chegarasi + bosqichli mute |
| ⏱ Self-destruct | Bot xabarlari belgilangan vaqtdan keyin o'z-o'zidan o'chadi |

## 📁 Tuzilma

```
.
├── env.example          # .env uchun namuna (nusxalab .env qiling)
├── requirements.txt
├── config.py            # .env dan sozlamalar
├── database.py          # aiosqlite qatlami (5 jadval)
├── keyboards.py         # barcha klaviatura va tugma matnlari
├── states.py            # FSM holatlari
├── main.py              # ishga tushirish nuqtasi
├── pytest.ini           # test konfiguratsiyasi
├── requirements-dev.txt # pytest va boshqa dev kutubxonalar
├── tests/
│   ├── conftest.py        # fixture'lar, soxta Telegram obyektlari, boshqariladigan vaqt
│   ├── test_anti_flood.py # anti-flood middleware testlari
│   └── test_self_destruct.py # TTL / reyestr / tozalagich testlari
├── middlewares/
│   ├── anti_flood.py      # spamga qarshi cheklov (sliding window + mute)
│   └── self_destruct.py   # o'z-o'zini o'chiruvchi xabarlar + /clean reyestri
└── handlers/
    ├── common.py        # /start, obuna tekshiruvi, bekor qilish, statistika, /admin
    ├── sell.py          # sotish anketasi
    ├── search.py        # xaridor so'rovi
    ├── catalog.py       # katalog, filtr, bitim so'rovi
    ├── favorites.py     # sevimlilar
    ├── offers.py        # narx taklifi
    ├── calculator.py    # narx kalkulyatori
    ├── scam_check.py    # firibgarni tekshirish
    ├── my_listings.py   # mening e'lonlarim (sold / UP)
    ├── garant.py        # garant xizmati
    └── admin.py         # admin panel
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

   Anti-flood va xabarlarni tozalash sozlamalari ham `env.example` faylida
   izohlari bilan keltirilgan (`FLOOD_*`, `SELF_DESTRUCT_*`).

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

Suite **68 ta test**dan iborat va tashqi tarmoqqa umuman murojaat qilmaydi
(Telegram API soxtalashtiriladi, vaqt `Clock` fixture'i bilan boshqariladi,
shuning uchun testlar tez va deterministik).

| Fayl | Testlar | Qamrov |
| --- | --- | --- |
| `test_anti_flood.py` | 28 | sürgülü oyna, ogohlantirish throttling, mute va uning tugashi, purge, jimgina rejim, callback kafolati, bypass, GC, `build_anti_flood()` |
| `test_self_destruct.py` | 40 | `temporary`/`permanent`, `MessageRegistry`, rejalashtirish qoidalari (kanal/guruh himoyasi), haqiqiy o'chirish, `shutdown()`, session zanjiri integratsiyasi, `sweep_chat()`, foydalanuvchi tozalagichi |

**Regressiya himoyasi:** `test_default_settings_are_gentle` sukut qiymatlar
yumshoq rejimda qolishini kafolatlaydi — kimdir chegaralarni qattiqlashtirsa,
test darhol yiqiladi.

## 🧾 Ma'lumotlar bazasi

`market_database.sqlite3` fayli birinchi ishga tushirishda avtomatik yaratiladi.

- `settings` — dinamik sozlamalar (majburiy kanal va h.k.)
- `users` — foydalanuvchilar
- `listings` — e'lonlar (`sell` / `buy`)
- `favorites` — sevimlilar
- `blacklist` — firibgarlar ro'yxati
