from __future__ import annotations

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger


def build_scheduler(
    cron_expression: str,
    run_job,
    job_id: str = "paper_bag_monthly_report",
    timezone: str = "Asia/Shanghai",
) -> BlockingScheduler:
    minute, hour, day, month, day_of_week = cron_expression.split()
    scheduler = BlockingScheduler(timezone=timezone)
    scheduler.add_job(
        run_job,
        CronTrigger(
            minute=minute,
            hour=hour,
            day=day,
            month=month,
            day_of_week=day_of_week,
        ),
        id=job_id,
        replace_existing=True,
    )
    return scheduler
