# Copyright (c) 2015, creqit Technologies Pvt. Ltd. and Contributors
# License: MIT. See LICENSE
"""
Events:
	always
	daily
	monthly
	weekly
"""

import datetime
import os
import random
import time
from typing import NoReturn

import pytz
import setproctitle
from croniter import CroniterBadCronError
from filelock import FileLock, Timeout

import creqit
from creqit.utils import cint, get_bench_path, get_datetime, get_sites, now_datetime
from creqit.utils.background_jobs import set_niceness
from creqit.utils.caching import redis_cache

DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"
DEFAULT_SCHEDULER_TICK = 4 * 60


def cprint(*args, **kwargs):
	"""Prints only if called from STDOUT"""
	try:
		os.get_terminal_size()
		print(*args, **kwargs)
	except Exception:
		pass


def _proctitle(message):
	setproctitle.setthreadtitle(f"creqit-scheduler: {message}")


def start_scheduler() -> NoReturn:
	"""Run enqueue_events_for_all_sites based on scheduler tick.
	Specify scheduler_interval in seconds in common_site_config.json"""

	tick = get_scheduler_tick()
	set_niceness()

	lock_path = os.path.abspath(os.path.join(get_bench_path(), "config", "scheduler_process"))

	try:
		lock = FileLock(lock_path)
		lock.acquire(blocking=False)
	except Timeout:
		creqit.logger("scheduler").debug("Scheduler already running")
		return

	while True:
		_proctitle("idle")
		time.sleep(sleep_duration(tick))
		enqueue_events_for_all_sites()


def sleep_duration(tick):
	if tick != DEFAULT_SCHEDULER_TICK:
		# Assuming user knows what they want.
		return tick

	# Sleep until next multiple of tick.
	# This makes scheduler aligned with real clock,
	# so event scheduled at 12:00 happen at 12:00 and not 12:00:35.
	minutes = tick // 60
	now = datetime.datetime.now(pytz.UTC)
	left_minutes = minutes - now.minute % minutes
	next_execution = now.replace(second=0) + datetime.timedelta(minutes=left_minutes)

	return (next_execution - now).total_seconds()


def enqueue_events_for_all_sites() -> None:
	"""Loop through sites and enqueue events that are not already queued"""

	with creqit.init_site():
		sites = get_sites()

	# Sites are sorted in alphabetical order, shuffle to randomize priorities
	random.shuffle(sites)

	for site in sites:
		try:
			enqueue_events_for_site(site=site)
		except Exception:
			creqit.logger("scheduler").debug(f"Failed to enqueue events for site: {site}", exc_info=True)


def enqueue_events_for_site(site: str) -> None:
	def log_exc():
		creqit.logger("scheduler").error(f"Exception in Enqueue Events for Site {site}", exc_info=True)

	try:
		_proctitle(f"scheduling events for {site}")
		creqit.init(site)
		creqit.connect()
		if is_scheduler_inactive():
			return

		enqueue_events()

		creqit.logger("scheduler").debug(f"Queued events for site {site}")
	except Exception as e:
		if creqit.db.is_access_denied(e):
			creqit.logger("scheduler").debug(f"Access denied for site {site}")
		log_exc()

	finally:
		creqit.destroy()


def enqueue_events() -> list[str] | None:
	if schedule_jobs_based_on_activity():
		enqueued_jobs = []
		all_jobs = creqit.get_all("Scheduled Job Type", filters={"stopped": 0}, fields="*")
		random.shuffle(all_jobs)
		for job_type in all_jobs:
			job_type = creqit.get_doc(doctype="Scheduled Job Type", **job_type)
			try:
				if job_type.enqueue():
					enqueued_jobs.append(job_type.method)
			except CroniterBadCronError:
				creqit.logger("scheduler").error(
					f"Invalid Job on {creqit.local.site} - {job_type.name}", exc_info=True
				)

		return enqueued_jobs


def is_scheduler_inactive(verbose=True) -> bool:
	if creqit.local.conf.maintenance_mode:
		if verbose:
			cprint(f"{creqit.local.site}: Maintenance mode is ON")
		return True

	if creqit.local.conf.pause_scheduler:
		if verbose:
			cprint(f"{creqit.local.site}: creqit.conf.pause_scheduler is SET")
		return True

	if is_scheduler_disabled(verbose=verbose):
		return True

	return False


def is_scheduler_disabled(verbose=True) -> bool:
	if creqit.conf.disable_scheduler:
		if verbose:
			cprint(f"{creqit.local.site}: creqit.conf.disable_scheduler is SET")
		return True

	scheduler_disabled = not creqit.utils.cint(
		creqit.db.get_single_value("System Settings", "enable_scheduler")
	)
	if scheduler_disabled:
		if verbose:
			cprint(f"{creqit.local.site}: SystemSettings.enable_scheduler is UNSET")
	return scheduler_disabled


def toggle_scheduler(enable):
	creqit.db.set_single_value("System Settings", "enable_scheduler", int(enable))


def enable_scheduler():
	toggle_scheduler(True)


def disable_scheduler():
	toggle_scheduler(False)


@redis_cache(ttl=60 * 60)
def schedule_jobs_based_on_activity(check_time=None):
	"""Return True for active sites as defined by `Activity Log`.
	Also return True for inactive sites once every 24 hours based on `Scheduled Job Log`."""
	if is_dormant(check_time=check_time):
		# ensure last job is one day old
		last_job_timestamp = _get_last_creation_timestamp("Scheduled Job Log")
		if not last_job_timestamp:
			return True
		else:
			if ((check_time or now_datetime()) - last_job_timestamp).total_seconds() >= 86400:
				# one day is passed since jobs are run, so lets do this
				return True
			else:
				# schedulers run in the last 24 hours, do nothing
				return False
	else:
		# site active, lets run the jobs
		return True


def is_dormant(check_time=None):
	# Assume never dormant if developer_mode is enabled
	if creqit.conf.developer_mode:
		return False
	last_activity_log_timestamp = _get_last_creation_timestamp("Activity Log")
	since = (creqit.get_system_settings("dormant_days") or 4) * 86400
	if not last_activity_log_timestamp:
		return True
	if ((check_time or now_datetime()) - last_activity_log_timestamp).total_seconds() >= since:
		return True
	return False


def _get_last_creation_timestamp(doctype):
	timestamp = creqit.db.get_value(doctype, filters={}, fieldname="creation", order_by="creation desc")
	if timestamp:
		return get_datetime(timestamp)


@creqit.whitelist()
def activate_scheduler():
	from creqit.installer import update_site_config

	creqit.only_for("Administrator")

	if creqit.local.conf.maintenance_mode:
		creqit.throw(creqit._("Scheduler can not be re-enabled when maintenance mode is active."))

	if is_scheduler_disabled():
		enable_scheduler()
	if creqit.conf.pause_scheduler:
		update_site_config("pause_scheduler", 0)


@creqit.whitelist()
def get_scheduler_status():
	if is_scheduler_inactive():
		return {"status": "inactive"}
	return {"status": "active"}


def get_scheduler_tick() -> int:
	conf = creqit.get_conf()
	return cint(conf.scheduler_tick_interval) or DEFAULT_SCHEDULER_TICK
