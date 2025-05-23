# Copyright (c) 2023, creqit Technologies and contributors
# For license information, please see license.txt

# import creqit
from creqit.model.document import Document


class WorkspaceCustomBlock(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from creqit.types import DF

		custom_block_name: DF.Link | None
		label: DF.Data | None
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
	# end: auto-generated types

	pass
