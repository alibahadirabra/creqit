# Copyright (c) 2015, creqit Technologies Pvt. Ltd. and Contributors
# License: MIT. See LICENSE
import json
from collections import defaultdict
from typing import TYPE_CHECKING, Union

import creqit
from creqit import _
from creqit.model.docstatus import DocStatus
from creqit.utils import cint

if TYPE_CHECKING:
	from creqit.model.document import Document
	from creqit.workflow.doctype.workflow.workflow import Workflow


class WorkflowStateError(creqit.ValidationError):
	pass


class WorkflowTransitionError(creqit.ValidationError):
	pass


class WorkflowPermissionError(creqit.ValidationError):
	pass


def get_workflow_name(doctype):
	workflow_name = creqit.cache.hget("workflow", doctype)
	if workflow_name is None:
		workflow_name = creqit.db.get_value("Workflow", {"document_type": doctype, "is_active": 1}, "name")
		creqit.cache.hset("workflow", doctype, workflow_name or "")

	return workflow_name


@creqit.whitelist()
def get_transitions(
	doc: Union["Document", str, dict], workflow: "Workflow" = None, raise_exception: bool = False
) -> list[dict]:
	"""Return list of possible transitions for the given doc"""
	from creqit.model.document import Document

	if not isinstance(doc, Document):
		doc = creqit.get_doc(creqit.parse_json(doc))
		doc.load_from_db()

	if doc.is_new():
		return []

	doc.check_permission("read")

	workflow = workflow or get_workflow(doc.doctype)
	current_state = doc.get(workflow.workflow_state_field)

	if not current_state:
		if raise_exception:
			raise WorkflowStateError
		else:
			creqit.throw(_("Workflow State not set"), WorkflowStateError)

	transitions = []
	roles = creqit.get_roles()

	for transition in workflow.transitions:
		if transition.state == current_state and transition.allowed in roles:
			if not is_transition_condition_satisfied(transition, doc):
				continue
			transitions.append(transition.as_dict())

	return transitions


def get_workflow_safe_globals():
	# access to creqit.db.get_value, creqit.db.get_list, and date time utils.
	return dict(
		creqit=creqit._dict(
			db=creqit._dict(get_value=creqit.db.get_value, get_list=creqit.db.get_list),
			session=creqit.session,
			utils=creqit._dict(
				now_datetime=creqit.utils.now_datetime,
				add_to_date=creqit.utils.add_to_date,
				get_datetime=creqit.utils.get_datetime,
				now=creqit.utils.now,
			),
		)
	)


def is_transition_condition_satisfied(transition, doc) -> bool:
	if not transition.condition:
		return True
	else:
		return creqit.safe_eval(transition.condition, get_workflow_safe_globals(), dict(doc=doc.as_dict()))


@creqit.whitelist()
def apply_workflow(doc, action):
	"""Allow workflow action on the current doc"""
	doc = creqit.get_doc(creqit.parse_json(doc))
	doc.load_from_db()
	workflow = get_workflow(doc.doctype)
	transitions = get_transitions(doc, workflow)
	user = creqit.session.user

	# find the transition
	transition = None
	for t in transitions:
		if t.action == action:
			transition = t

	if not transition:
		creqit.throw(_("Not a valid Workflow Action"), WorkflowTransitionError)

	if not has_approval_access(user, doc, transition):
		creqit.throw(_("Self approval is not allowed"))

	# update workflow state field
	doc.set(workflow.workflow_state_field, transition.next_state)

	# find settings for the next state
	next_state = next(d for d in workflow.states if d.state == transition.next_state)

	# update any additional field
	if next_state.update_field:
		doc.set(next_state.update_field, next_state.update_value)

	new_docstatus = cint(next_state.doc_status)
	if doc.docstatus.is_draft() and new_docstatus == DocStatus.draft():
		doc.save()
	elif doc.docstatus.is_draft() and new_docstatus == DocStatus.submitted():
		doc.submit()
	elif doc.docstatus.is_submitted() and new_docstatus == DocStatus.submitted():
		doc.save()
	elif doc.docstatus.is_submitted() and new_docstatus == DocStatus.cancelled():
		doc.cancel()
	else:
		creqit.throw(_("Illegal Document Status for {0}").format(next_state.state))

	doc.add_comment("Workflow", _(next_state.state))

	return doc


@creqit.whitelist()
def can_cancel_document(doctype):
	workflow = get_workflow(doctype)
	cancelling_states = [s.state for s in workflow.states if s.doc_status == "2"]
	if not cancelling_states:
		return True

	for transition in workflow.transitions:
		if transition.next_state in cancelling_states:
			return False
	return True


def validate_workflow(doc):
	"""Validate Workflow State and Transition for the current user.

	- Check if user is allowed to edit in current state
	- Check if user is allowed to transition to the next state (if changed)
	"""
	workflow = get_workflow(doc.doctype)

	current_state = None
	if getattr(doc, "_doc_before_save", None):
		current_state = doc._doc_before_save.get(workflow.workflow_state_field)
	next_state = doc.get(workflow.workflow_state_field)

	if not next_state:
		next_state = workflow.states[0].state
		doc.set(workflow.workflow_state_field, next_state)

	if not current_state:
		current_state = workflow.states[0].state

	state_row = [d for d in workflow.states if d.state == current_state]
	if not state_row:
		creqit.throw(
			_("{0} is not a valid Workflow State. Please update your Workflow and try again.").format(
				creqit.bold(current_state)
			)
		)
	state_row = state_row[0]

	# if transitioning, check if user is allowed to transition
	if current_state != next_state:
		bold_current = creqit.bold(current_state)
		bold_next = creqit.bold(next_state)

		if not doc._doc_before_save:
			# transitioning directly to a state other than the first
			# e.g from data import
			creqit.throw(
				_("Workflow State transition not allowed from {0} to {1}").format(bold_current, bold_next),
				WorkflowPermissionError,
			)

		transitions = get_transitions(doc._doc_before_save)
		transition = [d for d in transitions if d.next_state == next_state]
		if not transition:
			creqit.throw(
				_("Workflow State transition not allowed from {0} to {1}").format(bold_current, bold_next),
				WorkflowPermissionError,
			)


def get_workflow(doctype) -> "Workflow":
	return creqit.get_cached_doc("Workflow", get_workflow_name(doctype))


def has_approval_access(user, doc, transition):
	return user == "Administrator" or transition.get("allow_self_approval") or user != doc.get("owner")


def get_workflow_state_field(workflow_name):
	return get_workflow_field_value(workflow_name, "workflow_state_field")


def send_email_alert(workflow_name):
	return get_workflow_field_value(workflow_name, "send_email_alert")


def get_workflow_field_value(workflow_name, field):
	return creqit.get_cached_value("Workflow", workflow_name, field)


@creqit.whitelist()
def bulk_workflow_approval(docnames, doctype, action):
	docnames = json.loads(docnames)
	if len(docnames) < 20:
		_bulk_workflow_action(docnames, doctype, action)
	elif len(docnames) <= 500:
		creqit.msgprint(_("Bulk {0} is enqueued in background.").format(action), alert=True)
		creqit.enqueue(
			_bulk_workflow_action,
			docnames=docnames,
			doctype=doctype,
			action=action,
			queue="short",
			timeout=1000,
		)
	else:
		creqit.throw(_("Bulk approval only support up to 500 documents."), title=_("Too Many Documents"))


def _bulk_workflow_action(docnames, doctype, action):
	# dictionaries for logging
	failed_transactions = defaultdict(list)
	successful_transactions = defaultdict(list)

	creqit.clear_messages()
	for idx, docname in enumerate(docnames, 1):
		message_dict = {}
		try:
			show_progress(docnames, _("Applying: {0}").format(action), idx, docname)
			apply_workflow(creqit.get_doc(doctype, docname), action)
			creqit.db.commit()
		except Exception as e:
			if not creqit.message_log:
				# Exception is	raised manually and not from msgprint or throw
				message = f"{e.__class__.__name__}"
				if e.args:
					message += f" : {e.args[0]}"
				message_dict = {"docname": docname, "message": message}
				failed_transactions[docname].append(message_dict)

			creqit.db.rollback()
			creqit.log_error(
				title=f"Workflow {action} threw an error for {doctype} {docname}",
				reference_doctype="Workflow",
				reference_name=action,
			)
		finally:
			if not message_dict:
				if creqit.message_log:
					messages = creqit.get_message_log()
					for message in messages:
						creqit.message_log.pop()
						message_dict = {"docname": docname, "message": message.get("message")}

						if message.get("raise_exception", False):
							failed_transactions[docname].append(message_dict)
						else:
							successful_transactions[docname].append(message_dict)
				else:
					successful_transactions[docname].append({"docname": docname, "message": None})

	if failed_transactions and successful_transactions:
		indicator = "orange"
	elif failed_transactions:
		indicator = "red"
	else:
		indicator = "green"

	print_workflow_log(failed_transactions, _("Failed Transactions"), doctype, indicator)
	print_workflow_log(successful_transactions, _("Successful Transactions"), doctype, indicator)


def print_workflow_log(messages, title, doctype, indicator):
	if messages.keys():
		msg = f"<h4>{title}</h4>"

		for doc in messages.keys():
			if len(messages[doc]):
				html = f"<details><summary>{creqit.utils.get_link_to_form(doctype, doc)}</summary>"
				for log in messages[doc]:
					if log.get("message"):
						html += "<div class='small text-muted' style='padding:2.5px'>{}</div>".format(
							log.get("message")
						)
				html += "</details>"
			else:
				html = f"<div>{doc}</div>"
			msg += html

		creqit.msgprint(
			msg, title=_("Workflow Status"), indicator=indicator, is_minimizable=True, realtime=True
		)


@creqit.whitelist()
def get_common_transition_actions(docs, doctype):
	common_actions = []
	if isinstance(docs, str):
		docs = json.loads(docs)
	try:
		for i, doc in enumerate(docs, 1):
			if not doc.get("doctype"):
				doc["doctype"] = doctype
			actions = [
				t.get("action")
				for t in get_transitions(doc, raise_exception=True)
				if has_approval_access(creqit.session.user, doc, t)
			]
			if not actions:
				return []
			common_actions = actions if i == 1 else set(common_actions).intersection(actions)
			if not common_actions:
				return []
	except WorkflowStateError:
		pass

	return list(common_actions)


def show_progress(docnames, message, i, description):
	n = len(docnames)
	if n >= 5:
		creqit.publish_progress(float(i) * 100 / n, title=message, description=description)


def set_workflow_state_on_action(doc, workflow_name, action):
	workflow = creqit.get_doc("Workflow", workflow_name)
	workflow_state_field = workflow.workflow_state_field

	# If workflow state of doc is already correct, don't set workflow state
	for state in workflow.states:
		if state.state == doc.get(workflow_state_field) and doc.docstatus == cint(state.doc_status):
			return

	action_map = {"update_after_submit": "1", "submit": "1", "cancel": "2"}
	docstatus = action_map[action]
	for state in workflow.states:
		if state.doc_status == docstatus:
			doc.set(workflow_state_field, state.state)
			return
