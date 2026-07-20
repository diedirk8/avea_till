# Project Structure

## Purpose

This document describes the structure of the Avea Till module and explains where new functionality should be added.

The goal is to keep the project organised, maintainable and easy to understand.

---

# Repository Structure

```
avea_till/
│
├── docs/
├── README.md
├── .gitignore
└── avea_till/
    ├── models/
    ├── security/
    ├── static/
    ├── views/
    ├── __init__.py
    └── __manifest__.py
```

---

# Folder Responsibilities

## models/

Contains all business logic.

Examples:

- Till Movements
- Cash Ledger
- Reports
- Dashboard calculations

No user interface should be implemented here.

---

## views/

Contains XML files.

Examples:

- Menus
- Forms
- Lists
- Search Views
- Actions

Views should contain presentation only.

---

## security/

Contains:

- Access Rights
- Security Groups
- Record Rules

Security should never be hardcoded in Python.

---

## static/

Contains static resources.

Examples:

- Icons
- Images
- JavaScript
- CSS

---

## docs/

Project documentation.

Every important architectural decision should be documented here.

---

# Design Philosophy

Business logic belongs in Python.

Presentation belongs in XML.

Configuration belongs in data files.

Documentation belongs in the docs folder.