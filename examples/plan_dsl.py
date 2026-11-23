"""Выгрузка плана в intervals.icu: инвариант сумм DSL (упрощённая выдержка).

План недели хранится в БД как JSON. Каждый день содержит distance_km
(попадает в НАЗВАНИЕ события календаря) и icu_workout — DSL-этапы, которые
intervals.icu превращает в структуру на часах.

Жёсткий инвариант: сумма ВСЕХ дистанционных шагов DSL = distance_km дня,
иначе название «Long Run 15 км» не совпадёт с этапами, прокрученными на
часах. Источник: plan_push.py (reconcile_day_distances / dsl_distance_totals),
сокращено и обезличено.
"""
import re

# Шаг DSL: "1.5km", "500mtr", "40mtr" (после санитайзера) — с множителем
# блока повторов "6x" (блок заканчивается пустой строкой).
DSL_DIST_RE = re.compile(r"(\d+(?:[.,]\d+)?)(km|mtr)", re.I)
REPEAT_LINE_RE = re.compile(r"^(\d+)x\s*\S")


def dsl_distance_totals(icu_workout: str) -> dict:
    """Суммы дистанционных шагов DSL (км): total / warmup / cooldown."""
    out = {"total": 0.0, "warmup": 0.0, "cooldown": 0.0}
    mult = 1
    for line in (icu_workout or "").splitlines():
        stripped = line.strip()
        if not stripped:
            mult = 1  # пустая строка заканчивает блок повторов
            continue
        mx = REPEAT_LINE_RE.fullmatch(stripped)
        if mx:
            mult = int(mx.group(1))
            continue
        for m in DSL_DIST_RE.finditer(stripped):
            km = float(str(m.group(1)).replace(",", "."))
            if m.group(2).lower() == "mtr":
                km /= 1000.0
            out["total"] += km * mult
            if "размин" in stripped.lower():
                out["warmup"] += km * mult
            elif "замин" in stripped.lower():
                out["cooldown"] += km * mult
    return out


def reconcile_day_distances(day: dict) -> bool:
    """Согласовать distance_km с суммой шагов DSL. Два класса расхождений:

    1) distance_km описывала только основной этап ("бег 8 км" при
       разминке 1.5 + 8 + заминке 1.5 = 11 в DSL) -> заголовок := сумма
       всех шагов (название события должно показывать полный день);
    2) DSL ошибся арифметикой (этапы 14 при заголовке 15) -> правится
       самый большой шаг DSL под заголовок (fix_dsl_distance_sum).

    Тестовые дни пропускаются: дистанция теста в названии считается
    отдельно и по конвенции не входит в полный день.
    """
    if not isinstance(day, dict):
        return False
    if re.search(r"тест|test", str(day.get("type") or ""), re.I):
        return False

    totals = dsl_distance_totals(day.get("icu_workout", ""))
    total = round(totals["total"], 2)
    if total <= 0:
        return False
    d = round(float(day.get("distance_km") or 0), 2)

    if d <= 0:                      # заголовка не было — берём сумму этапов
        day["distance_km"] = total
        return True
    if abs(d - total) < 0.05:       # сходится
        return False

    # Заголовок был "только основной этап"? Тогда полный день = сумма DSL.
    main_implied = round(total - totals["warmup"] - totals["cooldown"], 2)
    if main_implied > 0 and abs(d - main_implied) < 0.05:
        day["distance_km"] = total
        return True

    # Иначе DSL ошибся арифметикой: чиним самый большой шаг под заголовок
    # (рабочие отрезки по рецепту main_set "6x800" защищены от растяжения).
    day["icu_workout"] = fix_dsl_distance_sum(day["icu_workout"], d)
    return True


def fix_dsl_distance_sum(icu_workout: str, distance_km: float) -> str:
    """Правка самого крупного дистанционного шага так, чтобы сумма
    шагов стала равна distance_km (упрощённо: без защиты повторов)."""
    totals = dsl_distance_totals(icu_workout)
    diff = round(distance_km - totals["total"], 2)
    if abs(diff) < 0.05:
        return icu_workout
    # масштабируем самый большой немаркированный шаг на недостающую дельту
    best, best_km = None, 0.0
    for line in icu_workout.splitlines():
        for m in DSL_DIST_RE.finditer(line):
            km = float(str(m.group(1)).replace(",", "."))
            if m.group(2).lower() == "mtr":
                km /= 1000.0
            if km > best_km:
                best, best_km = m, km
    if best is None:
        return icu_workout
    new_km = max(0.1, best_km + diff)
    return icu_workout[:best.start()] + f"{round(new_km, 2)}km" + icu_workout[best.end():]


if __name__ == "__main__":
    # День «по рецепту»: 8 км в заголовке, но DSL - полный день 11 км.
    day = {
        "type": "easy",
        "distance_km": 8,
        "icu_workout": "Разминка 1.5km Z1\nОсновной этап 8km Z2\nЗаминка 1.5km Z1",
    }
    reconcile_day_distances(day)
    print(day["distance_km"])  # 11.0 — название события совпадёт с часами
