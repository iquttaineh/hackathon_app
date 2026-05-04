# -*- coding: utf-8 -*-
# Copyright (c) 2025, GJU and contributors
# For license information, please see license.txt

from __future__ import unicode_literals

import os

import frappe
from frappe.model.document import Document


ALLOWED_EMAIL_DOMAIN = "@gju.edu.jo"
MAX_ATTACHMENTS = 3
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
ALLOWED_EXTENSIONS = [".ppt", ".pptx", ".pdf", ".mp4", ".avi", ".mov", ".wmv", ".mkv"]
DOCTYPE_NAME = "Hackathon Registration Form"


class HackathonRegistrationForm(Document):
    def validate(self):
        """Validate registration form before saving."""
        self.normalize_student_email()
        self.validate_duplicate_registration()

    def normalize_student_email(self):
        """Validate email by domain only."""
        if not self.student_email:
            frappe.throw("Student email is required.")

        student_email = self.student_email.strip().lower()

        if not student_email.endswith(ALLOWED_EMAIL_DOMAIN):
            frappe.throw("Access is limited to eligible university email accounts only.")

        self.student_email = student_email

    def validate_duplicate_registration(self):
        """Prevent more than one registration document per email."""
        if not self.student_email:
            return

        existing = frappe.db.exists(
            DOCTYPE_NAME,
            {
                "student_email": self.student_email,
                "name": ["!=", self.name],
            },
        )

        if existing:
            frappe.throw("A registration already exists for this email address.")


@frappe.whitelist(allow_guest=True)
def submit_registration_form(data):
    """
    Create or update a hackathon registration form.

    This version is aligned with the updated DocType fields:
    student_name, university_id, major, solution_name, student_email,
    academic_year, solution_category, the_problem, solution.

    It validates only the submitted email domain.
    Attachments are stored as Frappe File records linked to this document.
    """
    try:
        data = frappe.parse_json(data)

        required_fields = [
            "student_name",
            "academic_year",
            "university_id",
            "major",
            "solution_name",
            "solution_category",
            "the_problem",
            "solution",
            "student_email",
        ]

        for field in required_fields:
            if not (data.get(field) or "").strip():
                return {
                    "success": False,
                    "message": f"Missing required field: {field}",
                }

        student_email = (data.get("student_email") or "").strip().lower()

        if not student_email.endswith(ALLOWED_EMAIL_DOMAIN):
            return {
                "success": False,
                "message": "Access is limited to eligible university email accounts only.",
            }

        attachments = normalize_attachments(data)
        attachment_validation = validate_attachments_payload(attachments)

        if not attachment_validation["valid"]:
            return {
                "success": False,
                "message": attachment_validation["message"],
            }

        existing_name = data.get("name") or frappe.db.exists(
            DOCTYPE_NAME,
            {"student_email": student_email},
        )

        if existing_name:
            registration = frappe.get_doc(DOCTYPE_NAME, existing_name)
            is_update = True
        else:
            registration = frappe.new_doc(DOCTYPE_NAME)
            is_update = False

        registration.update(
            {
                "student_name": data.get("student_name"),
                "student_email": student_email,
                "academic_year": data.get("academic_year"),
                "university_id": data.get("university_id"),
                "major": data.get("major"),
                "solution_name": data.get("solution_name"),
                "solution_category": data.get("solution_category"),
                "the_problem": data.get("the_problem"),
                "solution": data.get("solution"),
            }
        )

        if is_update:
            registration.save(ignore_permissions=True)
        else:
            registration.insert(ignore_permissions=True)

        sync_registration_attachments(registration.name, attachments)

        frappe.db.commit()

        return {
            "success": True,
            "message": "Registration updated successfully!" if is_update else "Registration submitted successfully!",
            "registration_id": registration.name,
        }

    except Exception:
        frappe.log_error(frappe.get_traceback(), "Hackathon Registration Error")
        return {
            "success": False,
            "message": "An error occurred while submitting your registration. Please try again.",
        }


@frappe.whitelist(allow_guest=True)
def check_existing_registration(email):
    """Check if a registration exists and return saved values plus linked files."""
    try:
        email = (email or "").strip().lower()

        if not email:
            return {"exists": False}

        if not email.endswith(ALLOWED_EMAIL_DOMAIN):
            return {
                "exists": False,
                "error": "Access is limited to eligible university email accounts only.",
            }

        existing = frappe.db.exists(
            DOCTYPE_NAME,
            {"student_email": email},
        )

        if not existing:
            return {"exists": False}

        registration = frappe.get_doc(DOCTYPE_NAME, existing)

        return {
            "exists": True,
            "registration_id": registration.name,
            "student_name": registration.student_name,
            "student_email": registration.student_email,
            "academic_year": registration.academic_year,
            "university_id": registration.university_id,
            "major": registration.major,
            "solution_name": registration.solution_name,
            "solution_category": registration.solution_category,
            "the_problem": registration.the_problem,
            "solution": registration.solution,
            "attachments": get_registration_attachments(registration.name),
        }

    except Exception:
        frappe.log_error(frappe.get_traceback(), "Check Registration Error")
        return {
            "exists": False,
            "error": "Could not load existing registration.",
        }


@frappe.whitelist(allow_guest=True)
def validate_file_upload(file_url):
    """Validate one uploaded file."""
    try:
        if not file_url:
            return {
                "valid": False,
                "message": "No file provided.",
            }

        file_name = frappe.db.get_value("File", {"file_url": file_url}, "name")

        if not file_name:
            return {
                "valid": False,
                "message": "File not found.",
            }

        file_doc = frappe.get_doc("File", file_name)
        return validate_file_doc(file_doc)

    except Exception:
        frappe.log_error(frappe.get_traceback(), "File Validation Error")
        return {
            "valid": False,
            "message": "Could not validate file.",
        }


def normalize_attachments(data):
    """Accept the frontend attachments JSON/list."""
    attachments = data.get("attachments") or []

    if isinstance(attachments, str):
        attachments = frappe.parse_json(attachments)

    if not isinstance(attachments, list):
        attachments = []

    return attachments


def validate_attachments_payload(attachments):
    """Validate attachment count, existence, size, and extension."""
    if not attachments:
        return {
            "valid": False,
            "message": "Please upload at least one file.",
        }

    if len(attachments) > MAX_ATTACHMENTS:
        return {
            "valid": False,
            "message": f"You can upload a maximum of {MAX_ATTACHMENTS} files.",
        }

    seen_urls = set()

    for attachment in attachments:
        file_url = attachment.get("file_url") or attachment.get("attachment")

        if not file_url:
            return {
                "valid": False,
                "message": "Invalid attachment data.",
            }

        if file_url in seen_urls:
            return {
                "valid": False,
                "message": "Duplicate attachment found.",
            }

        seen_urls.add(file_url)

        file_name = frappe.db.get_value("File", {"file_url": file_url}, "name")

        if not file_name:
            return {
                "valid": False,
                "message": f"File not found: {file_url}",
            }

        file_doc = frappe.get_doc("File", file_name)
        validation = validate_file_doc(file_doc)

        if not validation["valid"]:
            return validation

    return {
        "valid": True,
        "message": "Attachments are valid.",
    }


def validate_file_doc(file_doc):
    """Validate a Frappe File document."""
    file_size = file_doc.file_size or 0

    if file_size > MAX_FILE_SIZE:
        return {
            "valid": False,
            "message": f"File size {file_size / (1024 * 1024):.2f}MB exceeds 10MB limit.",
        }

    file_extension = os.path.splitext(file_doc.file_name or "")[1].lower()

    if file_extension not in ALLOWED_EXTENSIONS:
        return {
            "valid": False,
            "message": f"File type {file_extension} is not allowed.",
        }

    return {
        "valid": True,
        "message": "File is valid.",
        "file_name": file_doc.file_name,
        "file_size": file_size,
        "file_url": file_doc.file_url,
    }


def sync_registration_attachments(registration_name, attachments):
    """
    Attach selected files to the registration document.
    Files previously attached to this registration but removed by the user are detached.
    """
    selected_urls = {
        attachment.get("file_url") or attachment.get("attachment")
        for attachment in attachments
        if attachment.get("file_url") or attachment.get("attachment")
    }

    existing_files = frappe.get_all(
        "File",
        filters={
            "attached_to_doctype": DOCTYPE_NAME,
            "attached_to_name": registration_name,
        },
        fields=["name", "file_url"],
    )

    for existing_file in existing_files:
        if existing_file.file_url not in selected_urls:
            file_doc = frappe.get_doc("File", existing_file.name)
            file_doc.attached_to_doctype = None
            file_doc.attached_to_name = None
            file_doc.save(ignore_permissions=True)

    for file_url in selected_urls:
        file_name = frappe.db.get_value("File", {"file_url": file_url}, "name")

        if not file_name:
            continue

        file_doc = frappe.get_doc("File", file_name)
        file_doc.attached_to_doctype = DOCTYPE_NAME
        file_doc.attached_to_name = registration_name
        file_doc.is_private = 0
        file_doc.save(ignore_permissions=True)


def get_registration_attachments(registration_name):
    """Return files attached to a registration document."""
    files = frappe.get_all(
        "File",
        filters={
            "attached_to_doctype": DOCTYPE_NAME,
            "attached_to_name": registration_name,
        },
        fields=["name", "file_name", "file_url", "file_size"],
        order_by="creation asc",
        limit=MAX_ATTACHMENTS,
    )

    return [
        {
            "id": file.name,
            "file_name": file.file_name,
            "file_url": file.file_url,
            "file_size": file.file_size or "",
        }
        for file in files
    ]
