# Sessions + Attendance Tracking Upgrade

Added:
- Add sessions while managing an event.
- Events can now have multiple sessions.
- Add attendees to full event or specific session.
- Search existing members before adding attendance.
- Create new member if the person does not exist.
- Attendance records automatically appear in each member profile.
- Remove attendance records.
- Manage sessions from each event page.

Recommended flow:
1. Go to Events.
2. Click "View Sessions / Attendees".
3. Add sessions if needed.
4. Click "+ Add Attendee".
5. Search existing member.
6. Select session.
7. Save attendance.

For Supabase:
- If your database already used the previous schema, run `sessions_attendance_migration.sql` in Supabase SQL Editor.