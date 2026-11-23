"""Утренний разбор: сравнение тренировки с планом ПО ДАТЕ (упрощённая выдержка).

Планировщик ставит атлету утреннюю задачу в его индивидуальное время.
Воркер синхронизирует факт из intervals.icu и разбирает вчерашнюю
тренировку. Ключевая деталь: запланированный день ищется СОПОСТАВЛЕНИЕМ
ДАТ — метки дней в названиях событий ICU могут быть ошибочными, поэтому
им доверять нельзя.

Источники: ai_coach/adjuster.py (analyze_last_workout) и
scripts/worker.py (run_morning_greeting), сокращено и обезличено.
"""
import json
from datetime import date, timedelta

DAY_OFFSETS = ["monday", "tuesday", "wednesday", "thursday",
               "friday", "saturday", "sunday"]


def find_planned_day(plan_row: dict, activity_date: date) -> dict:
    """Найти запланированный день по дате активности.

    plan_row: строка coach.training_plans (week_start_date + plan_json).
    Метки [СР] в названиях событий могут врать — сопоставляем только дату:
    week_start_date + offset(день недели) == дата активности.
    """
    plan_data = json.loads(plan_row["plan_json"])
    days = plan_data.get("plan_json") if isinstance(plan_data.get("plan_json"), dict) else plan_data

    week_start = plan_row["week_start_date"]
    planned_day_en = None
    for offset, day_en in enumerate(DAY_OFFSETS):
        if week_start + timedelta(days=offset) == activity_date:
            planned_day_en = day_en
            break
    return days.get(planned_day_en, {}) if planned_day_en else {}


def clean_planned_for_prompt(planned: dict) -> dict:
    """Чистая копия дня для промпта: без следов прошлых разборов.

    Повторный экспресс-анализ делается С НУЛЯ: старый вердикт
    (status/actual/analysis) не должен попадать в контекст, иначе модель
    якорится на него вместо свежих кругов с часов.
    """
    return {k: v for k, v in planned.items()
            if k not in ("status", "actual", "analysis", "nutrition")}


def compare_plan_vs_fact(planned: dict, activity: dict) -> dict:
    """Сравнение цель/факт: цель из плана, факт из данных часов."""
    return {
        "goal": {
            "type": planned.get("type"),
            "distance_km": planned.get("distance_km"),
            "target_hr_zones": planned.get("target_hr_zones"),
            "target_pace": planned.get("target_pace"),
            "main_set": (planned.get("workout_structure") or {}).get("main_set", ""),
        },
        "fact": {
            "date": activity["date"],                       # ISO-дата
            "distance_km": round(activity.get("distance_meters", 0) / 1000, 1),
            "avg_hr": activity.get("avg_hr"),
            # Средний пульс за ВСЮ тренировку включает разминку/заминку —
            # для оценки целевых этапов промпт использует круги, не среднее
            "laps": activity.get("laps", []),
        },
    }


if __name__ == "__main__":
    plan_row = {
        "week_start_date": date(2026, 11, 16),   # понедельник
        "plan_json": json.dumps({
            "saturday": {
                "type": "long",
                "distance_km": 22,
                "target_hr_zones": "Z2-Z3",
                "workout_structure": {"main_set": "ровный длительный"},
            },
        }),
    }
    # Пробежка была в субботу той же недели — день найден по дате:
    planned = find_planned_day(plan_row, date(2026, 11, 21))
    print(planned["type"], planned["distance_km"])  # long 22
    print(clean_planned_for_prompt(planned).keys())  # без status/actual/analysis
