# Sawa Youth CRM with Surveys — Optimized Portal

Added views:
- Most Active Users page
- Event attendee list page for each workshop/event
- AI Session attendee list page
- Buttons from dashboard and events pages
- Search inside each attendee view

Run:

```bash
cd sawa_youth_crm_with_surveys
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open: http://127.0.0.1:5000


## New Survey Features
- Survey Builder section
- Create, edit, and delete survey forms
- Add survey responses manually
- Search and delete survey responses


## Survey Fix
- Surveys are now a separate Survey Library.
- You can add a survey with a Google Sheet / Excel link.
- Survey names no longer affect member attendance.
- You can still add manual responses if needed.
