"""Карточка тренировки: кэш AI-фонов и счётчик variety (упрощённая выдержка).

Карточка /card рисуется PIL за миллисекунды; дорогое — только AI-фон.
Поэтому фон кэшируется на диске: ключ = модель + полный промпт + хеш
набора фото-референсов (герой/питомец). Промах — генерация под локом
(чтобы TG и VK, запросившие одно и то же одновременно, не генерировали
дважды) и атомарная запись.

Каждое нажатие /card прокручивает variety — сцена меняется, а не отдаётся
кэш-клон. Источник: card_bg.py (get_background / bump_variety),
сокращено и обезличено.
"""
import hashlib
import threading
from pathlib import Path

IMAGE_MODEL = "gemini-2.5-flash-image"   # image-модель через AI-шлюз
CACHE_DIR = Path("card_bg")

_REALISM = "фотореализм, естественный свет"
_SUBJECT_CLAUSE = "включи в сцену героя с фото-референсов"
_TIME_BUCKETS = {
    "morning": "рассветное утро, прохладно, лёгкий туман",
    "day": "солнечный день, длинные тени",
    "evening": "закат, тёплое боковое освещение",
    "night": "ночной город, огни фонарей",
}

_locks: dict = {}
_locks_guard = threading.Lock()


def _cache_lock(name: str) -> threading.Lock:
    """Лок на имя (в оригинале — файловый, общий для двух процессов ботов)."""
    with _locks_guard:
        return _locks.setdefault(name, threading.Lock())


def _atomic_write(path: Path, data: bytes) -> None:
    """Атомарная запись: частично записанный PNG не попадёт в кэш."""
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def build_prompt(start_hour: int, variety: int, weather: dict | None) -> str:
    """Промпт = сцена по времени суток + погода + реализм."""
    bucket = ("morning" if start_hour < 11 else
              "day" if start_hour < 17 else
              "evening" if start_hour < 22 else "night")
    clauses = [_TIME_BUCKETS[bucket]]
    if weather and weather.get("condition"):
        clauses.append(f"погода: {weather['condition']}")   # «лёгкий дождь»…
    clauses.append(_REALISM)
    return ", ".join(clauses)


def get_background(start_hour: int = 8, variety: int = 0,
                   weather: dict | None = None,
                   subject_photos: list[bytes] | None = None) -> bytes | None:
    """Байты PNG фона: кэш → при промахе генерация под локом."""
    prompt = build_prompt(start_hour, variety, weather)
    if subject_photos:
        prompt += ", " + _SUBJECT_CLAUSE

    # Хеш НАБОРА фото: отсортированные хеши файлов — порядок не важен
    photos_key = ""
    if subject_photos:
        photos_key = hashlib.sha1(
            b"".join(sorted(hashlib.sha1(p).digest() for p in subject_photos))
        ).hexdigest()[:12]

    # Ключ включает МОДЕЛЬ: смена модели не коллизирует со старым кэшем
    key = hashlib.sha1(
        f"{IMAGE_MODEL}|{prompt}|{photos_key}".encode()).hexdigest()[:16]
    cache_file = CACHE_DIR / f"{key}.png"
    if cache_file.exists():
        return cache_file.read_bytes()

    lock = _cache_lock(key)
    try:
        if cache_file.exists():          # вторая платформа дождалась готового
            return cache_file.read_bytes()
        png = _generate(prompt, subject_photos)   # вызов image-модели
        if png:
            CACHE_DIR.mkdir(exist_ok=True)
            _atomic_write(cache_file, png)
    finally:
        lock.close()
    return png


def bump_variety(athlete_id: str, base: int = 0) -> int:
    """Счётчик разнообразия: каждый /card берёт следующую сцену.

    Общий для TG и VK одного атлета — под локом, чтобы нажатия в двух
    ботах не теряли инкременты. В оригинале счётчик живёт на диске и
    переживает рестарты.
    """
    with _cache_lock(f"variety_{athlete_id}"):
        counter_file = CACHE_DIR / f".variety_{athlete_id}"
        try:
            n = int(counter_file.read_text().strip() or 0)
        except OSError:
            n = 0
        n += 1
        CACHE_DIR.mkdir(exist_ok=True)
        _atomic_write(counter_file, str(n).encode())
        return base + n


def _generate(prompt: str, subject_photos: list[bytes] | None) -> bytes | None:
    """Заглушка: в оригинале — вызов image-модели с фото-референсами."""
    raise NotImplementedError


if __name__ == "__main__":
    print(build_prompt(7, 0, {"condition": "лёгкий дождь"}))
    # -> рассветное утро, ..., погода: лёгкий дождь, фотореализм, ...
    v1 = bump_variety("demo_athlete", base=3)
    print("variety:", v1)  # 4 — следующий /card покажет следующую сцену
