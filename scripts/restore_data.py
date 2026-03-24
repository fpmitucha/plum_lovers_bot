"""
Скрипт восстановления данных из переписки с ботом.

Запуск:
    cd ~/plum_lovers_bot
    source .venv/bin/activate
    python scripts/restore_data.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from bot.config import settings
from bot.models.models import Application, Roster, Profile, Base


# ─── ОДОБРЕННЫЕ ЗАЯВКИ ───────────────────────────────────────────────────────
# (telegram_id, "username", "slug", "status")
APPROVED_USERS = [
    (839178711, "ynarlk", "iana-arutiunova-Innopolis-MFAI-04-1-25", "done"),
    (8421106062, "qq_tyomshik", "artem-tuchkov-Innopolis-AI360-01-1-25", "done"),
    (8421106062, "qq_tyomshik", "ivan-ivanov-Harward-CSE-77-3-21", "done"),
    (8421106062, "qq_tyomshik", "artem-tuchkov-Innopolis-AI360-01-1-25", "done"),
    (8363888304, "sonechka_mipt", "sonecha-test-MIPT-AMI-01-1-25", "done"),
    (766018020, "gefest0v", "samat-khanbikov-Innopolis-MFAI-03-1-25", "done"),
    (1310237734, "kk0sta", "konstantin-kutashov-Innopolis-CSE-04-1-25", "done"),
    (1394573511, "anonymous1510", "alexander-harlamov-Sfedu-SE-13-1-25", "done"),
    (949672961, "DXozai7", "artem-fedorov-Innopolis-MFAI-02-1-25", "done"),
    (5164717048, "Milanachchka", "Milana-Kartashova-Innopolis-MFAI-01-1-25", "done"),
    (846960701, "layrrrn", "kirill-larin-Innopolis-MFAI-04-1-25", "done"),
    (1262350361, "kirka_0082", "kirill-ermolaev-Innopolis-MFAI-03-1-25", "done"),
    (1173002189, "velzebubin", "ivan-nikolaev-Innopolis-MFAI-07-1-25", "done"),
    (1737977805, "avbaf", "alexey-zolotarev-Innopolis-MFAI-02-1-25", "done"),
    (1707416321, "rasul228800", "rasul-yamaltdinov-innopolis-MFAI-01-1-25", "done"),
    (2108745808, "chugun_nya", "takhir-salikhov-Innopolis-MFAI-04-1-25", "done"),
    (995736418, "ekir98", "erik-demin-innopolis-MFAI-1-1-25", "done"),
    (1096213078, "LSG22601", "Son-Gi-Lee-Innopolis-MFAI-05-25", "done"),
    (898960231, "lAmirkhan", "amirkhan-sakhapov-Innopolis-MFAI-05-1-25", "done"),
    (5617644513, "richard_weiss", "mikhail-sukharev-Innopolis-MFAI-02-1-25", "done"),
    (718836232, "ch1ya", "ivan-ivanov-Innopolis-MFAI-07-1-25", "done"),
    (6586397582, "adelya_star", "adelia-karimova-Innopolis-University-B25-MFAI-02", "done"),
    (6606936797, "mipt_off", "ivan-ivanov-Harward-CSE-77-3-21", "done"),
    (1413004486, "dofi4ka", "vladislav-konovalov-Innopolis-DSAI-02-4-25", "done"),
    (953020066, "MaestroPlaya", "alexander-zavialov-Innopolis-MFAI-04-1-25", "done"),
    (839178711, "ynarlk", "iana-arutiunova-Innopolis-MFAI-04-1-25", "done"),
    (5688793342, "vlhnv", "khamza-valikhanov-Innopolis-CSE-5-1-25", "done"),
    (820713535, "lipllis", "sofya-aleksandrova-Innopolis-AI360-01-1-25", "done"),
    (792066210, "hisavodyatel", "Amir-Khisamiev-Innopolis-MFAI-03-1-25", "done"),
    (846489302, "danya9a", "danila-safronov-inno-MFAI-06-1-25", "done"),
    (771238383, "Igor_Istochnik", "evgeniy-obmanshchin-innopolis-CSE-02-1-25", "done"),
    (1521036354, "kus_hihih", "mariia-smirnova-Innopolis-MFAI-05-1-25", "done"),
    (1247019277, "beukhkirill", "kirill-beukh-innopolis-MFAI-05-1-25", "done"),
    (1803600003, "Cubovan", "ivan-lavrusevich-Innopolis-MFAI-03-1-25", "done"),
    (942616752, "kvzrrr", "mikhail-kruchinin-Innopolis-MFAI-04-1-25", "done"),
    (2110122275, "farhaatyy", "Farhat-Fahrutdinov-Innopolis-Bachelor-MFAI-01-25", "done"),
    (1021611591, "answer569", "sergei-anisimov-innopolis-CSE-04-1-25", "done"),
    (1070111128, "Sokovikov07", "Alexander-Sokovikov-Innopolis-RO-01-1-25", "done"),
    (5290862597, "Radmir5252", "radmir-iakupov-Innopolis-DSAI-05-1-25", "done"),
    (259348818, "Busy_fox13", "andrey-lisin-Innopolis-MFAI-02-1-25", "done"),
    (1451783126, "pvwwell", "pavel-lykin-Innopolis-MFAI-07-1-25", "done"),
    (1048297740, "serasergeev", "sergei-sergeev-Innopolis-MFAI-04-1-25", "done"),
    (2040812170, "Kar_karych_e", "Karina-Ermakova-Innopolis-MFAI-04-1-25", "done"),
    (1325016161, "Leo0742", "leonid-bolbachan-Innopolis-DSAI-03-1-25", "done"),
    (1959277390, "dnlnr87", "Daniil-Nuriev-Innopolis-MFAI-03-1-25", "done"),
    (1254579200, "OladickBoy", "popov-vladislav-Innopolis-MFAI-5-1-25", "done"),
    (5557805350, "aiomatg", "gaziz-gubaidullin-Innopolis-MFAI-05-1-25", "done"),
    (1702333830, "Ar5en1y", "arsenii-vozmilov-Innopolis-MFAI-03-1-25", "done"),
    (1068369780, "demmboo", "ilya-rudnev-Innopolis-MFAI-02-1-25", "done"),
    (1913171250, "hidan4ikk", "maksim-firsanov-Innopolis-MFAI-01-1-25", "done"),
    (983028785, "troshak", "dana-troshina-Innopolis-AI360-01-1-25", "done"),
    (1650293488, "e_h_ehehe", "alexandra-harlova-innopolis-MFAI-05-1-25", "done"),
    (514602339, "priaet1", "albina-khafizova-innopolis-MFAI-04-1-25", "done"),
    (1372426950, "kirill_povasin", "kirill-pivasin-mfai-mfai-04-9-25", "done"),
    (1209124800, "cheplik", "danil-madanov-innopolis-MFAI-04-1-25", "done"),
    (1209872121, "Penorva", "zakhar-fedotov-Innopolis-MFAI-03-1-25", "done"),
    (813944683, "ka1zed", "Konstantin-Zharenov-Innopolis-MFAI-04-1-25", "done"),
    (6518161659, "Danilanab", "danila-naboishchikov-innopolis-cse-2-1-25", "done"),
    (1487667692, "retardvad3r", "radis-sadriev-Innopolis-MFAI-07-1-25", "done"),
    (2092234253, "hwww8s", "rostislav-chebelev-Innopolis-RO-01-1-25", "done"),
    (811407310, "adelinahaf", "adelina-khafizova-Innopolis-DSAI-04-1-25", "done"),
    (870850127, "Madina2726", "Madina-valetova-Innopolis-dsai-01-1-25", "done"),
    (2014522339, "pchelikkk", "roman-korotkov-innopolis-DSAI-01-1-25", "done"),
    (7279387747, "None", "takhir-salikhov-Innopolis-MFAI-04-1-24", "done"),
    (1014750594, "iamchudin", "dmitrii-chudin-Innopolis-CSE-02-1-25", "done"),
    (6441836565, "bl_lynx", "Stepan-Mescheryakov-NSTU", "done"),
    (1751101664, "jinseisieko", "egor-kolesov-innopolis-CSE-01-1-25", "done"),
    (1058697990, "leoligh", "lev-svetoshev-IU-MFAI-03-1-25", "done"),
    (1414602443, "ultramarinedash", "renat-itishnik-kai-ks-4101-1-25", "done"),
    (1766413422, "fedyaan", "anna-fedotova-Innopolis-CSE-03-1-2025", "done"),
    (5544744659, "ShinmenTakez0", "Kamal-Isaev-Innopolis-MFAI-06-01-25", "done"),
    (1868535776, "gnomsky228", "ermakov-mikhail-innopolis-MFAI-06-1-25", "done"),
    (521697810, "MementoOW", "Mukharlyamov-Timur-IU-MFAI-02-1-25", "done"),
    (948732512, "sffxcx", "sofia-bondar-Innopolis-MFAI-07-1-25", "done"),
    (5021966471, "Ad_lynz", "svetlana-kulakova-nsu-avtf-abs527-1-25", "done"),
    (1381264507, "dashaaa_365", "daria-babushkina-Innopolis-DSAI-06-1-25", "done"),
    (704658354, "kroko_one", "Dmitriy-Bogdanov-IU-ro-01-01-25", "done"),
    (1528372442, "frnzd_flm", "Danila-Bekov-IU-DSAI-04-1-25", "done"),
    (1069559918, "kamillkaaaaa", "kamilla-iarullina-Innopolis-DSAI-03-1-25", "done"),
    (1242750200, "kamil_dv", "Kamil-Dudikov-IU-CSE-05-1-25", "done"),
    (5010569378, "lerrrrraaa", "valeria-kazakova-Innopolis-MFAI-2-1-25", "done"),
    (1167396547, "whyasd666", "Belichenko-Egor-Innopolis-MFAI-07-1-25", "done"),
    (1753914250, "DinarNaguma", "dinar-latypov-Bachelor-MFAI-05-1-25", "done"),
    (5246752281, "Fasanchick", "Alexandr-Kopylov-Innopolis-MFAI-03-1-25", "done"),
    (1119732245, "ExoZara", "egor-balnikev-Politexspb-AMI-1-1-25", "done"),
    (1119732245, "ExoZara", "egor-balnikev-Politexspb-AMI-1-1-25", "done"),
    (1005525870, "babidzhonus", "azamat-mukhtashev-Innopolis-MFAI-06-1-25", "done"),
    (1537974754, "ottobisss", "iudin-sergey-Innopolis-MFAI-4-1-25", "done"),
    (1531794499, "haavoittaya", "Kozlov-Stanislav-Innopolis-MFAI-01-01-25", "done"),
    (1920896257, "UnicodeUser", "matvey-druzhinin-innopolis-mfai-06-01-25", "done"),
    (1257966003, "Mansiks1", "mansur-umakhanov-innopolis-MFAI-04-1-25", "done"),
    (2139345864, "ber_malay", "alik-galiullin-Innopolis-AI360-01-1-25", "done"),
    (5189148791, "Kuku_Kukareku", "Roman-Rusak-Innopolis-MFAI-02-F25-25", "done"),
    (6005481641, "uzbek9987", "kim-ruslan-Innopolis-MFAI-06-1-25", "done"),
    (704208904, "n_ill_k_iggers", "salman-nasyrov-Innopolis-AI360-1-1-25", "done"),
    (1366977178, "le_minet", "nikita-lamzenkov-innopolis-mfai-01-1-25", "done"),
    (1247767770, "darkIllidan", "nikita-ionov-Innopolis-CSE-04-1-25", "done"),
    (717690156, "poon4ik7", "rolan-muliukin-Innopolis-CSE-06-2-24", "done"),
    (5289052814, "Kassiboo", "timur-bikmetov-Innopolis-CSE-05-2-2024", "done"),
    (828707602, "Daniel_WagnerD", "daniel-wagner-SPSUE-linguistics-L2502-1-25", "done"),
    (802035705, "DirectorOfSweetLife", "yaroslav-moskvin-innopolis-DSAI-01-1-25", "done"),
    (7239658882, "synhles", "Egor-Lesnix-Innopolis-DSAI-04-1-25", "done"),
    (7922829247, "Olegananin1", "oleg-ananin-Innopolis-MFAI-01-1-25", "done"),
    (802093686, "Hijey1", "ilhom-nematov-Innopolis-MFAI-07-1-25", "done"),
    (1796999738, "aaalexandrov21", "aleksandrov-andrei-Innopolis-MFAI-02-1-25", "done"),
    (1915402937, "Blazeball1", "Alekseev-rostislav-Alexandrovich-VISH-12-25-21", "done"),
    (1944350082, "maksimsolovyev21", "Maxim-Solovyov-VISH-11-1-25-21", "done"),
    (1334361836, "bulkinadivane", "bulat-kamalov-Innopolis-MFAI-01-1-25", "done"),
    (876744758, "pixel4lex", "aleksei-kovalenko-Innopolis-MFAI-02-2-24", "done"),
    (1071665344, "silver9221", "emil-krutikov-Innopolis-MFAI-4-1-25", "done"),
    (1174010710, "Schwanz228", "Tofig-Giyasbeyli-Innopolis-MFAI-05-1-25", "done"),
    (534420229, "tridimishel", "mishel-triandafilidi-Innopolis-MFAI-3-1-25", "done"),
    (1812632445, "karpit4", "timur-valliulin-iu-mfai-03-1-25", "done"),
    (8421106062, "qq_tyomshik", "ivan-ivanov-Harward-CSE-77-3-21", "done"),
]

# ─── ОТКЛОНЁННЫЕ ЗАЯВКИ (только для истории, НЕ добавляются в roster/profiles) ──
REJECTED_USERS = [
    (2120704934, "senior_Pyth0n", "ivan-ivanych-Harward-CSE-77-3-21"),
    (5544744659, "ShinmenTakez0", "ivan-ivanov-Harward-CSE-77-3-21"),
    (5544744659, "ShinmenTakez0", "ivan-ivanov-Harward-CSE-77-3-21"),
    (7239658882, "JustLittleMolly", "Egor-lesnix-innopolis-DSAI-04-1-2025"),
    (7239658882, "JustLittleMolly", "Egor-Lesnix-Innopolis-DSAI-04-1-25"),
    (7296787481, "wowadisaster", "ivan-ivanov-innopolis-MFAI-04-1-25"),
    (1005525870, "babidzhonus", "babidzhon-babidzhonov-Innopolis-MFAI-06-1-25"),
    (7239658882, "JustLittleMolly", "Egor-Lesnix-Innopolis-DSAI-04-1-25"),
]

# ─── КАРМА ───────────────────────────────────────────────────────────────────
# username -> points (переопределение для тех кто есть в APPROVED_USERS)
KARMA_OVERRIDES = {
    "qq_tyomshik": 241,
    "akazadira": 70,
    "chugun_nya": 60,
    "avbaf": 52,
    "velzebubin": 32,
    "ekir98": 30,
    "anonymous1510": 27,
    "gefest0v": 23,
    "kk0sta": 23,
    "ch1ya": 22,
}


async def restore(session: AsyncSession) -> None:
    restored_apps = 0
    restored_roster = 0
    restored_profiles = 0
    restored_rejected = 0

    seen_slugs = set()
    seen_profiles = set()

    for telegram_id, username, slug, status in APPROVED_USERS:
        app = Application(user_id=telegram_id, username=username, slug=slug, status=status)
        session.add(app)
        restored_apps += 1

        if slug not in seen_slugs:
            session.add(Roster(slug=slug))
            seen_slugs.add(slug)
            restored_roster += 1

        if telegram_id not in seen_profiles:
            karma = KARMA_OVERRIDES.get(username.lower(), 10)
            session.add(Profile(user_id=telegram_id, username=username, points=karma))
            seen_profiles.add(telegram_id)
            restored_profiles += 1

    for telegram_id, username, slug in REJECTED_USERS:
        app = Application(user_id=telegram_id, username=username, slug=slug, status="rejected")
        session.add(app)
        restored_rejected += 1

    await session.commit()
    print("✅ Восстановлено:")
    print(f"   Одобренные заявки: {restored_apps}")
    print(f"   Отклонённые заявки: {restored_rejected}")
    print(f"   Реестр (roster):    {restored_roster}")
    print(f"   Профили:            {restored_profiles}")


async def main() -> None:
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with session_maker() as session:
        await restore(session)
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())