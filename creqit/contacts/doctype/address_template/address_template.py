# Copyright (c) 2015, creqit Technologies and contributors
# License: MIT. See LICENSE

import creqit
from creqit import _
from creqit.model.document import Document
from creqit.utils.jinja import validate_template


class AddressTemplate(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from creqit.types import DF

		country: DF.Link
		is_default: DF.Check
		template: DF.Code | None
	# end: auto-generated types

	def validate(self):
		validate_template(self.template)

		if not self.template:
			self.template = get_default_address_template()

		if not self.is_default and not self._get_previous_default():
			self.is_default = 1
			if creqit.get_system_settings("setup_complete"):
				creqit.msgprint(_("Setting this Address Template as default as there is no other default"))

	def on_update(self):
		if self.is_default and (previous_default := self._get_previous_default()):
			creqit.db.set_value("Address Template", previous_default, "is_default", 0)

	def on_trash(self):
		if self.is_default:
			creqit.throw(_("Default Address Template cannot be deleted"))

	def _get_previous_default(self) -> str | None:
		return creqit.db.get_value("Address Template", {"is_default": 1, "name": ("!=", self.name)})


@creqit.whitelist()
def get_default_address_template() -> str:
	"""Return the default address template."""
	from pathlib import Path

	return (Path(__file__).parent / "address_template.jinja").read_text()
