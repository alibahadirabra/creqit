# Copyright (c) 2015, creqit Technologies and contributors
# License: MIT. See LICENSE

import creqit
from creqit.model.document import Document


class OAuthBearerToken(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from creqit.types import DF

		access_token: DF.Data | None
		client: DF.Link | None
		expiration_time: DF.Datetime | None
		expires_in: DF.Int
		refresh_token: DF.Data | None
		scopes: DF.Text | None
		status: DF.Literal["Active", "Revoked"]
		user: DF.Link | None
	# end: auto-generated types

	def validate(self):
		if not self.expiration_time:
			self.expiration_time = creqit.utils.datetime.datetime.strptime(
				self.creation, "%Y-%m-%d %H:%M:%S.%f"
			) + creqit.utils.datetime.timedelta(seconds=self.expires_in)
