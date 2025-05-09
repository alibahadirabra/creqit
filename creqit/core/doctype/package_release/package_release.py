# Copyright (c) 2021, creqit Technologies and contributors
# For license information, please see license.txt

import os
import subprocess

import creqit
from creqit.model.document import Document
from creqit.modules.export_file import export_doc
from creqit.query_builder.functions import Max


class PackageRelease(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from creqit.types import DF

		major: DF.Int
		minor: DF.Int
		package: DF.Link
		patch: DF.Int
		path: DF.SmallText | None
		publish: DF.Check
		release_notes: DF.MarkdownEditor | None
	# end: auto-generated types

	def set_version(self):
		# set the next patch release by default
		doctype = creqit.qb.DocType("Package Release")
		if not self.major:
			self.major = (
				creqit.qb.from_(doctype)
				.where(doctype.package == self.package)
				.select(Max(doctype.minor))
				.run()[0][0]
				or 0
			)

		if not self.minor:
			self.minor = (
				creqit.qb.from_(doctype)
				.where(doctype.package == self.package)
				.select(Max("minor"))
				.run()[0][0]
				or 0
			)
		if not self.patch:
			value = (
				creqit.qb.from_(doctype)
				.where(doctype.package == self.package)
				.select(Max("patch"))
				.run()[0][0]
				or 0
			)
			self.patch = value + 1

	def autoname(self):
		self.set_version()
		self.name = "{}-{}.{}.{}".format(
			creqit.db.get_value("Package", self.package, "package_name"), self.major, self.minor, self.patch
		)

	def validate(self):
		if self.publish:
			self.export_files()

	def export_files(self):
		"""Export all the documents in this package to site/packages folder"""
		package = creqit.get_doc("Package", self.package)

		self.export_modules()
		self.export_package_files(package)
		self.make_tarfile(package)

	def export_modules(self):
		for m in creqit.get_all("Module Def", dict(package=self.package)):
			module = creqit.get_doc("Module Def", m.name)
			for l in module.meta.links:
				if l.link_doctype == "Module Def":
					continue
				# all documents of the type in the module
				for d in creqit.get_all(l.link_doctype, dict(module=m.name)):
					export_doc(creqit.get_doc(l.link_doctype, d.name))

	def export_package_files(self, package):
		# write readme
		with open(creqit.get_site_path("packages", package.package_name, "README.md"), "w") as readme:
			readme.write(package.readme)

		# write license
		if package.license:
			with open(creqit.get_site_path("packages", package.package_name, "LICENSE.md"), "w") as license:
				license.write(package.license)

		# write package.json as `creqit_package.json`
		with open(
			creqit.get_site_path("packages", package.package_name, package.package_name + ".json"), "w"
		) as packagefile:
			packagefile.write(creqit.as_json(package.as_dict(no_nulls=True)))

	def make_tarfile(self, package):
		# make tarfile
		filename = f"{self.name}.tar.gz"
		subprocess.check_output(
			["tar", "czf", filename, package.package_name], cwd=creqit.get_site_path("packages")
		)

		# move file
		subprocess.check_output(
			["mv", creqit.get_site_path("packages", filename), creqit.get_site_path("public", "files")]
		)

		# make attachment
		file = creqit.get_doc(
			doctype="File",
			file_url="/" + os.path.join("files", filename),
			attached_to_doctype=self.doctype,
			attached_to_name=self.name,
		)

		# Set path to tarball
		self.path = file.file_url

		file.flags.ignore_duplicate_entry_error = True
		file.insert()
